"""Pre-registered model-mix search (registration ``hms-v1``).

Learning question (fixed in ``docs/data/historical_model_mix_registration.json``
before any licensed data is bought): which of the screen's 22 models, and five
published signals they do not cover, rank next month's returns reliably in both
US replay universes (S&P 500 and mid caps), and does an equal-weight mix of only
those beat the frozen screen's own model mix at the same breadth, out of sample?

Selection uses the development window only and a fixed rule with no fitted
weights: a candidate is kept when its monthly rank IC is reliably positive in
every universe and positive in both halves of the window; near-duplicates are
then dropped. The mix ranks names by the mean of the kept candidates'
percentile ranks and holds the top 30%, equal weight, monthly, costed like the
plain value book. The holdout is revealed once, after the selection is
committed and before either replay holdout (whose committed series carry
per-model holdout results).

Research only (N33): the screen code is never edited, and a mix that wins is a
proposal for a cold-start paper twin. Only aggregates are committed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from value_investor import historical_screen_replay as hsr
from value_investor import rule_search as rs

DEFAULT_REGISTRATION_PATH = hsr.REPO_ROOT / "docs/data/historical_model_mix_registration.json"
DEFAULT_STORE_PATH = Path("docs/data") / hsr.MODEL_MIX_STORE_NAME
MIX_CODE_PATHS = ("model_mix_search.py", "rule_search.py", "sharadar_replay_adapter.py")
SCORE_VARIANT = "dividend_units_fixed"
REPLAY_STORE_NAMES = (hsr.DEFAULT_STORE_PATH.name, hsr.MIDCAP_STORE_PATH.name)
BOOKS = ("mix", "frozen_composite", "all_candidates")

STALE_REGISTRATION_TITLE = "Historical model-mix search registration predates screen or mix code"
STALE_VERDICT_TITLE = "Historical model-mix search verdict no longer describes the live code"
HOLDOUT_REUSED_TITLE = "Historical model-mix search holdout revealed more than once"


def mix_code_fingerprint(package_dir: Path = hsr.PACKAGE_DIR) -> str:
    digest = hashlib.sha256()
    for rel in MIX_CODE_PATHS:
        path = Path(package_dir) / rel
        digest.update(rel.encode())
        digest.update(hsr.fingerprint_file_bytes(path) if path.exists() else b"<missing>")
    return digest.hexdigest()


def load_registration(path: Path = DEFAULT_REGISTRATION_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# --- Candidates ----------------------------------------------------------------------------


def _num(frame: pd.DataFrame, col: str) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[col], errors="coerce")


def _ratio(num: pd.Series, den: pd.Series) -> pd.Series:
    return (num / den).where(den > 0)


def gross_profitability(panel: pd.DataFrame) -> pd.Series:
    gross_profit = _num(panel, "gross_margin") * _num(panel, "total_revenue")
    return _ratio(gross_profit, _num(panel, "total_assets"))


def accruals(panel: pd.DataFrame) -> pd.Series:
    accrued = _num(panel, "net_income") - _num(panel, "operating_cashflow")
    return _ratio(accrued, _num(panel, "total_assets"))


def net_share_issuance(panel: pd.DataFrame) -> pd.Series:
    return _ratio(_num(panel, "shares_outstanding"), _num(panel, "shares_outstanding_prev")) - 1.0


def asset_growth(panel: pd.DataFrame) -> pd.Series:
    return _ratio(_num(panel, "total_assets"), _num(panel, "total_assets_prev")) - 1.0


PANEL_SIGNALS: dict[str, Callable[[pd.DataFrame], pd.Series]] = {
    "gross_profitability": gross_profitability,
    "accruals": accruals,
    "net_share_issuance": net_share_issuance,
    "asset_growth": asset_growth,
}


def momentum_12_1(data: rs.SearchData, ticker: str, day: pd.Timestamp) -> float:
    """Return from twelve months to one month before ``day``; NaN without fresh bars."""
    series = data.series.get(ticker)
    if series is None:
        return float("nan")
    recent = data.bar_at(ticker, day - pd.DateOffset(months=1))
    old = data.bar_at(ticker, day - pd.DateOffset(months=12))
    if recent is None or old is None or not series.close[old] > 0:
        return float("nan")
    return float(series.close[recent] / series.close[old] - 1.0)


PRICE_SIGNALS: dict[str, Callable[[rs.SearchData, str, pd.Timestamp], float]] = {
    "momentum_12_1": momentum_12_1,
}


def candidate_specs(registration: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Candidate id → kind (model, panel, price) and direction (+1: higher is better)."""
    cands = registration["candidates"]
    out: dict[str, dict[str, Any]] = {
        model: {"kind": "model", "direction": 1} for model in cands["models"]["ids"]
    }
    for spec in cands["published"]:
        if spec["id"] in out:
            raise ValueError(f"Candidate id {spec['id']!r} is registered twice")
        known = PANEL_SIGNALS if spec["kind"] == "panel" else PRICE_SIGNALS
        if spec["id"] not in known:
            raise ValueError(f"No {spec['kind']} signal named {spec['id']!r}")
        out[spec["id"]] = {"kind": spec["kind"], "direction": int(spec["direction"])}
    return out


@dataclass
class UniverseData:
    name: str
    data: rs.SearchData
    # Per rebalance date: one row per ticker, one column per candidate, higher is better.
    scores: dict[pd.Timestamp, pd.DataFrame]
    composite: dict[pd.Timestamp, pd.Series]


def build_universe(
    name: str,
    baseline: pd.DataFrame,
    scored: pd.DataFrame,
    panel: pd.DataFrame,
    daily: pd.DataFrame,
    haircuts: Mapping[str, float],
    registration: Mapping[str, Any],
) -> UniverseData:
    """``baseline``: the screen as it runs (composite, plain value sort, names);
    ``scored``: the signal cache the model candidates are read from."""
    data = rs.SearchData(baseline, panel, daily, haircuts, registration)
    specs = candidate_specs(registration)
    base = baseline.assign(as_of=baseline["as_of"].map(rs._naive))
    composite = {
        day: pd.Series(
            pd.to_numeric(g["composite_score"], errors="coerce").to_numpy(),
            index=g["ticker"].astype(str),
        )
        for day, g in base.groupby("as_of")
    }
    pan = panel.assign(as_of=panel["as_of"].map(rs._naive), ticker=panel["ticker"].astype(str))
    for cid, spec in specs.items():
        if spec["kind"] == "panel":
            pan[cid] = PANEL_SIGNALS[cid](pan) * spec["direction"]
    panel_ids = [c for c, s in specs.items() if s["kind"] == "panel"]
    panel_by_date = {
        day: g.drop_duplicates("ticker").set_index("ticker")[panel_ids]
        for day, g in pan.groupby("as_of")
    }
    model_scores = scored.assign(as_of=scored["as_of"].map(rs._naive))
    scores: dict[pd.Timestamp, pd.DataFrame] = {}
    for day, g in model_scores.groupby("as_of"):
        g = g.drop_duplicates("ticker")
        tickers = pd.Index(g["ticker"].astype(str), name="ticker")
        frame = pd.DataFrame(index=tickers)
        published = panel_by_date.get(day)
        for cid, spec in specs.items():
            if spec["kind"] == "model":
                col = f"{hsr.MODEL_SCORE_PREFIX}{cid}"
                frame[cid] = (
                    pd.to_numeric(g[col], errors="coerce").to_numpy() if col in g else np.nan
                )
            elif spec["kind"] == "panel":
                frame[cid] = (
                    published[cid].reindex(tickers).to_numpy() if published is not None else np.nan
                )
            else:
                fn = PRICE_SIGNALS[cid]
                frame[cid] = [fn(data, t, day) * spec["direction"] for t in tickers]
        scores[day] = frame
    return UniverseData(name=name, data=data, scores=scores, composite=composite)


# --- Windows, ICs, and selection --------------------------------------------------------------


@dataclass
class WindowPanel:
    dates: list[pd.Timestamp]
    # Month k (dates[k] → dates[k + 1]): return per name screened with a fresh bar.
    returns: list[dict[str, float]]
    scores: list[pd.DataFrame]
    composite: list[pd.Series]


def window_panel(
    universe: UniverseData, window: Mapping[str, str], ids: Sequence[str]
) -> WindowPanel:
    data = universe.data
    dates = data.window_dates(window)
    if len(dates) < 2:
        raise ValueError(f"{universe.name}: no rebalance months in window {dict(window)}")
    screens = {s.date: s for s in data.screens}
    returns: list[dict[str, float]] = []
    scores: list[pd.DataFrame] = []
    composite: list[pd.Series] = []
    for k, day in enumerate(dates[:-1]):
        names = sorted(
            t for t in screens[day].signal if t in data.series and data.bar_at(t, day) is not None
        )
        returns.append({t: rs._month_return(data, t, day, dates[k + 1])[0] for t in names})
        frame = universe.scores.get(day, pd.DataFrame())
        scores.append(frame.reindex(index=names, columns=list(ids)))
        composite.append(universe.composite.get(day, pd.Series(dtype=float)).reindex(names))
    return WindowPanel(dates=dates, returns=returns, scores=scores, composite=composite)


def rank_ic(score: pd.Series, ret: pd.Series, *, min_names: int) -> float | None:
    ok = score.notna() & ret.notna()
    if int(ok.sum()) < min_names:
        return None
    a, b = score[ok].rank().to_numpy(), ret[ok].rank().to_numpy()
    if a.std() == 0 or b.std() == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def ic_summary(
    ics: Sequence[float | None], coverage: Sequence[float], settings: Mapping[str, Any], *, z: float
) -> dict[str, Any]:
    values = np.asarray([v for v in ics if v is not None], dtype=float)
    half = len(values) // 2
    halves = (
        [round(float(values[:half].mean()), 4), round(float(values[half:].mean()), 4)]
        if half
        else [None, None]
    )
    ci = rs.mean_ci(values, lag=settings["lag"], z=z)
    median_coverage = float(np.median(coverage)) if len(coverage) else 0.0
    reasons = []
    if median_coverage < settings["min_coverage"]:
        reasons.append("coverage")
    if len(values) < settings["min_months"]:
        reasons.append("too_few_months")
    if ci["low"] is None or not ci["low"] > 0:
        reasons.append("ic_not_reliably_positive")
    if any(h is None or not h > 0 for h in halves):
        reasons.append("ic_not_positive_in_both_halves")
    return {
        "months": len(values),
        "median_coverage": round(median_coverage, 4),
        "coverage_ok": median_coverage >= settings["min_coverage"],
        "mean_ic": ci,
        "ic_halves": halves,
        "eligible": not reasons,
        "reasons": reasons,
    }


def candidate_window_stats(
    panel: WindowPanel, ids: Sequence[str], settings: Mapping[str, Any], *, z: float
) -> tuple[dict[str, dict[str, Any]], dict[str, list[float | None]]]:
    ics: dict[str, list[float | None]] = {c: [] for c in ids}
    coverage: dict[str, list[float]] = {c: [] for c in ids}
    for rets, frame in zip(panel.returns, panel.scores, strict=True):
        ret = pd.Series(rets, dtype=float).reindex(frame.index)
        for c in ids:
            col = frame[c]
            coverage[c].append(float(col.notna().mean()) if len(col) else 0.0)
            ics[c].append(rank_ic(col, ret, min_names=settings["min_names"]))
    stats = {c: ic_summary(ics[c], coverage[c], settings, z=z) for c in ids}
    return stats, ics


def mean_rank_correlation(panel: WindowPanel, ids: Sequence[str]) -> pd.DataFrame:
    """Mean over months of the cross-sectional Spearman correlation between candidates."""
    ids = list(ids)
    total = np.zeros((len(ids), len(ids)))
    count = np.zeros((len(ids), len(ids)))
    for frame in panel.scores:
        if len(frame) < 3:
            continue
        corr = frame[ids].corr(method="spearman", min_periods=3).to_numpy()
        ok = ~np.isnan(corr)
        total[ok] += corr[ok]
        count[ok] += 1
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(count > 0, total / np.where(count > 0, count, 1), np.nan)
    return pd.DataFrame(mean, index=ids, columns=ids)


def select_candidates(
    stats: Mapping[str, Mapping[str, Mapping[str, Any]]],
    correlations: Mapping[str, pd.DataFrame],
    registration: Mapping[str, Any],
) -> dict[str, Any]:
    """The registered rule: eligible in every universe, then drop near-duplicates."""
    universes = list(stats)
    ids = list(stats[universes[0]])
    threshold = float(registration["redundancy"]["max_mean_rank_correlation"])
    eligible = [c for c in ids if all(stats[u][c]["eligible"] for u in universes)]

    def strength(c: str) -> float:
        return float(np.mean([stats[u][c]["mean_ic"]["mean"] for u in universes]))

    def similarity(a: str, b: str) -> float:
        vals = [float(correlations[u].at[a, b]) for u in universes]
        vals = [v for v in vals if v == v]
        return float(np.mean(vals)) if vals else 0.0

    kept: list[str] = []
    redundant: dict[str, str] = {}
    for c in sorted(eligible, key=lambda c: (-round(strength(c), 6), c)):
        clash = next((k for k in kept if similarity(c, k) > threshold), None)
        if clash is None:
            kept.append(c)
        else:
            redundant[c] = clash
    covered = [c for c in ids if all(stats[u][c]["coverage_ok"] for u in universes)]
    return {"kept": kept, "dropped_redundant": redundant, "eligible": eligible, "covered": covered}


# --- Books --------------------------------------------------------------------------------


def top_share(scores: pd.Series, share: float) -> set[str]:
    s = scores.dropna()
    if s.empty:
        return set()
    cutoff = s.quantile(1.0 - share)
    return set(s.index[s >= cutoff].astype(str))


def mix_score(frame: pd.DataFrame, kept: Sequence[str], min_share: float) -> pd.Series:
    if not kept:
        return pd.Series(dtype=float)
    ranks = frame[list(kept)].rank(pct=True)
    enough = ranks.notna().sum(axis=1) >= math.ceil(min_share * len(kept))
    return ranks.mean(axis=1).where(enough)


def book_returns(
    panel: WindowPanel, picks: Sequence[set[str]], fallback: np.ndarray, *, cost_per_side: float
) -> tuple[np.ndarray, int]:
    """Equal weight over each month's picks, costed on turnover (as the plain value book)."""
    out = np.zeros(len(panel.returns))
    prev: dict[str, float] = {}
    fallback_months = 0
    for k, rets in enumerate(panel.returns):
        names = sorted(t for t in picks[k] if t in rets)
        if not names:
            out[k] = fallback[k]
            fallback_months += 1
            prev = {}
            continue
        w = 1.0 / len(names)
        turnover = sum(abs(w - prev.get(t, 0.0)) for t in names)
        turnover += sum(v for t, v in prev.items() if t not in names)
        gross = float(np.mean([rets[t] for t in names]))
        out[k] = gross - cost_per_side * turnover
        growth = 1.0 + gross
        prev = {t: w * (1.0 + rets[t]) / growth for t in names} if growth > 0 else {}
    return out, fallback_months


def build_books(
    panel: WindowPanel,
    data: rs.SearchData,
    selection: Mapping[str, Any],
    settings: Mapping[str, Any],
    *,
    cost_per_side: float,
    singles: bool = False,
) -> dict[str, Any]:
    plain = rs.plain_value_book(data, panel.dates, cost_per_side=cost_per_side)
    cap, eq = rs.benchmark_returns(data, panel.dates)
    share, min_share = settings["top_share"], settings["min_share"]

    def run(picks: list[set[str]]) -> np.ndarray:
        return book_returns(panel, picks, eq, cost_per_side=cost_per_side)[0]

    def mixed(ids: Sequence[str]) -> np.ndarray:
        return run([top_share(mix_score(f, ids, min_share), share) for f in panel.scores])

    out: dict[str, Any] = {
        "plain_value": plain.returns,
        "cap_weighted": cap,
        "equal_weighted": eq,
        "frozen_composite": run([top_share(c, share) for c in panel.composite]),
    }
    if selection["covered"]:
        out["all_candidates"] = mixed(selection["covered"])
    if selection["kept"]:
        out["mix"] = mixed(selection["kept"])
    if singles:
        out["singles"] = {
            c: run([top_share(f[c], share) for f in panel.scores]) for c in selection["covered"]
        }
    return out


def _annualised(x: np.ndarray) -> float:
    return round(float(np.expm1(12 * np.mean(x))), 4)


def book_metrics(
    portfolio: np.ndarray,
    plain: np.ndarray,
    cap: np.ndarray,
    settings: Mapping[str, Any],
    *,
    z: float,
) -> dict[str, Any]:
    log_ex = np.log1p(portfolio) - np.log1p(plain)
    log_cap = np.log1p(portfolio) - np.log1p(cap)
    lag = settings["lag"]
    return {
        "months": len(portfolio),
        "annualised_return": _annualised(np.log1p(portfolio)),
        "annualised_excess_plain_value": _annualised(log_ex),
        "horizons": {
            str(h): rs.horizon_probability(log_ex, h, lag=lag, z=z) for h in settings["horizons"]
        },
        "market_context": {
            "annualised_excess_cap": _annualised(log_cap),
            "horizons_vs_cap_weighted": {
                str(h): rs.horizon_probability(log_cap, h, lag=lag, z=z)
                for h in settings["horizons"]
            },
        },
    }


def _rounded(x: Sequence[float | None]) -> list[float | None]:
    return [None if v is None else round(float(v), 6) for v in x]


def _series(panel: WindowPanel, books: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"month_starts": [d.date().isoformat() for d in panel.dates[:-1]]}
    for name in (*BOOKS, "plain_value", "cap_weighted", "equal_weighted"):
        if name in books:
            out[name] = _rounded(books[name])
    return out


def _paired(a: np.ndarray, b: np.ndarray, settings: Mapping[str, Any], *, z: float) -> dict:
    ci = rs.mean_ci(a - b, lag=settings["lag"], z=z)
    return {"monthly": ci, "verdict": rs._verdict_increment(ci)}


# --- Search and reveal ------------------------------------------------------------------------


def _settings(registration: Mapping[str, Any]) -> dict[str, Any]:
    obj, el, mix = registration["objective"], registration["eligibility"], registration["mix"]
    return {
        "horizons": [int(h) for h in obj["report_horizons_months"]],
        "lag": int(obj["long_run_lag_months"]),
        "z_search": float(obj["z_search"]),
        "z_holdout": float(obj["z_holdout"]),
        "stress_cost": float(registration["costs"]["stress_per_side"]),
        "top_share": float(mix["top_share"]),
        "min_share": float(mix["min_share_of_kept_scored"]),
        "min_names": int(el["min_names_per_month"]),
        "min_months": int(el["min_months"]),
        "min_coverage": float(el["min_median_coverage"]),
        "cscv_blocks": int(registration["overfitting"]["cscv_blocks"]),
    }


def _base_cost(registration: Mapping[str, Any], universe: str) -> float:
    return float(registration["universes"][universe]["cost_base_per_side"])


def run_search(
    universes: Mapping[str, UniverseData], registration: Mapping[str, Any]
) -> dict[str, Any]:
    """Score every candidate on the development window and apply the registered rule."""
    s = _settings(registration)
    window = registration["windows"]["development"]
    ids = list(candidate_specs(registration))
    panels = {u: window_panel(d, window, ids) for u, d in universes.items()}
    stats: dict[str, dict[str, dict[str, Any]]] = {}
    ics: dict[str, dict[str, list[float | None]]] = {}
    correlations: dict[str, pd.DataFrame] = {}
    for u, panel in panels.items():
        stats[u], ics[u] = candidate_window_stats(panel, ids, s, z=s["z_search"])
        correlations[u] = mean_rank_correlation(panel, ids)
    selection = select_candidates(stats, correlations, registration)

    books: dict[str, Any] = {}
    overfitting: dict[str, Any] = {}
    series: dict[str, Any] = {}
    candidates: dict[str, dict[str, Any]] = {c: {} for c in ids}
    for u, panel in panels.items():
        built = build_books(
            panel,
            universes[u].data,
            selection,
            s,
            cost_per_side=_base_cost(registration, u),
            singles=True,
        )
        plain, cap = built["plain_value"], built["cap_weighted"]
        books[u] = {
            name: book_metrics(built[name], plain, cap, s, z=s["z_search"])
            for name in BOOKS
            if name in built
        }
        books[u]["plain_value_annualised_excess_cap"] = _annualised(np.log1p(plain) - np.log1p(cap))
        singles = built["singles"]
        for c in ids:
            single = singles.get(c)
            candidates[c][u] = {
                **stats[u][c],
                "book_annualised_excess_plain_value": None
                if single is None
                else _annualised(np.log1p(single) - np.log1p(plain)),
            }
        excess = (
            np.column_stack([np.log1p(singles[c]) - np.log1p(plain) for c in singles])
            if singles
            else np.zeros((len(plain), 0))
        )
        trial_sharpes = [
            float(np.mean(col) / np.std(col, ddof=1)) if np.std(col, ddof=1) > 0 else float("nan")
            for col in excess.T
        ]
        overfitting[u] = {
            "pbo_cscv": rs.pbo_cscv(excess, blocks=s["cscv_blocks"]) if singles else None,
            "deflated_sharpe_mix": rs.deflated_sharpe(
                np.log1p(built["mix"]) - np.log1p(plain), trial_sharpes
            )
            if "mix" in built
            else None,
        }
        series[u] = {
            **_series(panel, built),
            "candidate_rank_ic": {c: _rounded(ics[u][c]) for c in ids},
        }
    eligible = selection["eligible"]
    pooled = {
        a: {
            b: round(float(np.nanmean([correlations[u].at[a, b] for u in panels])), 4)
            for b in eligible
        }
        for a in eligible
    }
    return {
        "run_at": datetime.now(UTC).isoformat(),
        "window": dict(window),
        "universes": list(panels),
        "candidates_tested": len(ids),
        "candidates": candidates,
        "selection": selection,
        "eligible_rank_correlation": pooled,
        "books": books,
        "overfitting": overfitting,
        "series": series,
    }


def decide(universes: Mapping[str, Any], kept: Sequence[str]) -> str:
    if not kept:
        return "no_reliable_candidates"
    base = [entry["base"] for entry in universes.values()]
    adds = [b["mix_minus_frozen_composite"]["verdict"] == "adds" for b in base]
    fails = any(b["mix_verdict_vs_plain_value"] == "fail" for b in base)
    if all(adds) and not fails:
        return "mix_adds_in_both"
    if any(adds):
        return "partial"
    return "no_gain_over_frozen_mix"


def run_reveal(
    universes: Mapping[str, UniverseData],
    registration: Mapping[str, Any],
    selection: Mapping[str, Any],
) -> dict[str, Any]:
    """Holdout for the mix and its references in every universe, at base and stress cost."""
    s = _settings(registration)
    z = s["z_holdout"]
    window = registration["windows"]["holdout"]
    ids = list(candidate_specs(registration))
    out: dict[str, Any] = {"run_at": datetime.now(UTC).isoformat(), "window": dict(window)}
    per_universe: dict[str, Any] = {}
    for u, universe in universes.items():
        panel = window_panel(universe, window, ids)
        stats, _ = candidate_window_stats(panel, ids, s, z=z)
        entry: dict[str, Any] = {
            "candidates": {
                c: {k: stats[c][k] for k in ("months", "median_coverage", "mean_ic", "ic_halves")}
                for c in ids
            }
        }
        for cost_label, cost in (
            ("base", _base_cost(registration, u)),
            ("stress", s["stress_cost"]),
        ):
            built = build_books(panel, universe.data, selection, s, cost_per_side=cost)
            plain, cap = built["plain_value"], built["cap_weighted"]
            block: dict[str, Any] = {
                name: book_metrics(built[name], plain, cap, s, z=z)
                for name in BOOKS
                if name in built
            }
            block["frozen_composite_verdict_vs_plain_value"] = rs._verdict_p_lower(
                block["frozen_composite"]["horizons"], registration
            )
            if "mix" in built:
                block["mix_minus_frozen_composite"] = _paired(
                    built["mix"], built["frozen_composite"], s, z=z
                )
                block["mix_verdict_vs_plain_value"] = rs._verdict_p_lower(
                    block["mix"]["horizons"], registration
                )
                if "all_candidates" in built:
                    block["mix_minus_all_candidates"] = _paired(
                        built["mix"], built["all_candidates"], s, z=z
                    )
            block["series"] = _series(panel, built)
            entry[cost_label] = block
        per_universe[u] = entry
    out["universes"] = per_universe
    out["decision"] = decide(per_universe, selection["kept"])
    return out


# --- Store, gates, CLI ----------------------------------------------------------------------


def _check_fingerprints(registration: Mapping[str, Any]) -> None:
    if registration.get("screen_code_fingerprint") != hsr.screen_code_fingerprint():
        raise ValueError("Screen code changed since registration; run `register` first.")
    if registration.get("mix_code_fingerprint") != mix_code_fingerprint():
        raise ValueError("Mix code changed since registration; run `register` first.")


def _check_builds(builds: Mapping[str, Path], registration: Mapping[str, Any]) -> None:
    wanted = set(registration["universes"])
    if set(builds) != wanted:
        raise ValueError(f"Builds for {sorted(wanted)} are required; got {sorted(builds)}")


def replay_reveals(store_path: Path = DEFAULT_STORE_PATH) -> list[str]:
    """Replay stores beside ``store_path`` whose holdout has been revealed."""
    out = []
    for name in REPLAY_STORE_NAMES:
        store = rs._read_json(Path(store_path).parent / name) or {}
        if store.get("holdout_reveals"):
            out.append(name)
    return out


def load_universe(build_dir: Path, registration: Mapping[str, Any], universe: str) -> UniverseData:
    build_dir = Path(build_dir)
    if hsr._inside_repo(build_dir):
        raise ValueError(
            f"{build_dir} is inside the repository. Licensed data must stay outside this public repo."
        )
    panel = pd.read_csv(build_dir / "panel.csv.gz")
    market = registration["market_id"]
    baseline = hsr.cached_replay_signals(
        panel, market_id=market, cache_path=build_dir / hsr.SIGNAL_CACHE_NAME
    )
    scored = hsr.cached_replay_signals(
        panel,
        market_id=market,
        cache_path=build_dir / hsr.signal_cache_name(SCORE_VARIANT),
        transform=SCORE_VARIANT,
    )
    daily = pd.read_csv(build_dir / "daily.csv.gz")
    term = pd.read_csv(build_dir / "terminal_baseline.csv")
    haircuts = dict(zip(term["ticker"].astype(str), term["haircut"].astype(float), strict=True))
    return build_universe(universe, baseline, scored, panel, daily, haircuts, registration)


def selection_committed(store_path: Path = DEFAULT_STORE_PATH) -> bool:
    store = rs._read_json(store_path) or {}
    return bool((store.get("search") or {}).get("selection"))


def search(
    builds: Mapping[str, Path],
    *,
    registration_path: Path = DEFAULT_REGISTRATION_PATH,
    store_path: Path = DEFAULT_STORE_PATH,
) -> dict[str, Any]:
    registration = load_registration(registration_path)
    _check_fingerprints(registration)
    _check_builds(builds, registration)
    store = rs._read_json(store_path) or {}
    if store.get("holdout_reveals"):
        raise ValueError("Holdout already revealed; a new search needs a new registration_id.")
    revealed = replay_reveals(store_path)
    if revealed:
        raise ValueError(
            f"Replay holdout already revealed in {', '.join(revealed)}: its committed series "
            "carry per-model holdout results, so a selection now would not be blind. "
            "hms-v1 can no longer run; open a new registration with a later holdout."
        )
    universes = {u: load_universe(path, registration, u) for u, path in builds.items()}
    result = run_search(universes, registration)
    payload = {
        **store,
        "registration_id": registration.get("registration_id"),
        "search": result,
        "holdout_reveals": [],
    }
    rs._write_json(store_path, payload)
    return payload


def reveal(
    builds: Mapping[str, Path],
    *,
    registration_path: Path = DEFAULT_REGISTRATION_PATH,
    store_path: Path = DEFAULT_STORE_PATH,
) -> dict[str, Any]:
    registration = load_registration(registration_path)
    _check_fingerprints(registration)
    _check_builds(builds, registration)
    store = rs._read_json(store_path) or {}
    selection = (store.get("search") or {}).get("selection")
    if not selection:
        raise ValueError("No committed selection; run `search` and commit the store first.")
    reveals = list(store.get("holdout_reveals") or [])
    if reveals:
        print("Holdout already revealed; this reveal is recorded as exploratory.")
    universes = {u: load_universe(path, registration, u) for u, path in builds.items()}
    result = run_reveal(universes, registration, selection)
    reveals.append({"at": result["run_at"], "evidence": not reveals})
    payload = {**store, "holdout": result, "holdout_reveals": reveals}
    rs._write_json(store_path, payload)
    return payload


def register(
    registration_path: Path = DEFAULT_REGISTRATION_PATH, store_path: Path = DEFAULT_STORE_PATH
) -> dict[str, str]:
    store = rs._read_json(store_path) or {}
    if store.get("holdout_reveals"):
        raise ValueError("Holdout already revealed; open a new registration_id instead.")
    registration = load_registration(registration_path)
    candidate_specs(registration)
    registration["screen_code_fingerprint"] = hsr.screen_code_fingerprint()
    registration["mix_code_fingerprint"] = mix_code_fingerprint()
    registration["registered_at"] = datetime.now(UTC).isoformat()
    rs._write_json(registration_path, registration)
    return {
        "screen_code_fingerprint": registration["screen_code_fingerprint"],
        "mix_code_fingerprint": registration["mix_code_fingerprint"],
    }


def status_block(
    registration_path: Path = DEFAULT_REGISTRATION_PATH, store_path: Path = DEFAULT_STORE_PATH
) -> dict[str, Any] | None:
    """Daily ops-monitor view (embedded in ``historical_screen_replay.json``)."""
    if not Path(registration_path).exists():
        return None
    registration = load_registration(registration_path)
    store = rs._read_json(store_path) or {}
    selection = (store.get("search") or {}).get("selection") or {}
    return {
        "registration_id": registration.get("registration_id"),
        "matches_screen_code": registration.get("screen_code_fingerprint")
        == hsr.screen_code_fingerprint(),
        "matches_mix_code": registration.get("mix_code_fingerprint") == mix_code_fingerprint(),
        "kept": selection.get("kept"),
        "decision": (store.get("holdout") or {}).get("decision"),
        "holdout_reveals": list(store.get("holdout_reveals") or []),
    }


def findings_from_block(block: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not block:
        return []
    findings: list[dict[str, Any]] = []
    reveals = block.get("holdout_reveals") or []
    current = block.get("matches_screen_code") and block.get("matches_mix_code")
    if current is False:
        if reveals:
            findings.append(
                {
                    "severity": "warn",
                    "category": "backtest",
                    "title": STALE_VERDICT_TITLE,
                    "summary": (
                        "Screen or model-mix code changed after the hms-v1 holdout was revealed. "
                        "Its verdicts describe the registered candidates only. See "
                        "docs/ops/historical-model-mix.md."
                    ),
                    "auto_fixable": False,
                }
            )
        else:
            findings.append(
                {
                    "severity": "info",
                    "category": "backtest",
                    "title": STALE_REGISTRATION_TITLE,
                    "summary": (
                        "Screen or model-mix code changed since hms-v1 was registered. Run "
                        "`ftse-model-mix register` before the licensed run; the holdout is "
                        "still sealed."
                    ),
                    "auto_fixable": False,
                }
            )
    if len(reveals) > 1:
        findings.append(
            {
                "severity": "warn",
                "category": "backtest",
                "title": HOLDOUT_REUSED_TITLE,
                "summary": (
                    f"The model-mix holdout was revealed {len(reveals)} times. Only the first "
                    "reveal is evidence."
                ),
                "auto_fixable": False,
            }
        )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ftse-model-mix", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Fingerprints, selection, and reveals")
    sub.add_parser("register", help="Re-freeze fingerprints while the holdout is sealed")
    for name, text in (
        ("search", "Score every candidate on the development window and apply the rule"),
        ("reveal", "Evaluate the mix and its references on the holdout (once)"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("--build", type=Path, required=True, help="S&P 500 build-panel output")
        p.add_argument(
            "--midcap-build", type=Path, required=True, help="build-panel --universe midcap output"
        )
    args = parser.parse_args(argv)
    if args.command == "status":
        print(json.dumps(status_block(), indent=2))
    elif args.command == "register":
        print(json.dumps(register(), indent=2))
    else:
        builds = {"sp500": args.build, "midcap": args.midcap_build}
        if args.command == "search":
            payload = search(builds)
            result = payload["search"]
            print(
                json.dumps(
                    {"selection": result["selection"], "overfitting": result["overfitting"]},
                    indent=2,
                )
            )
        else:
            payload = reveal(builds)
            print(json.dumps(payload["holdout"]["decision"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
