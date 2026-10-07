"""Pre-registered point-in-time replay of the frozen value screen (L536, L542).

Learning question (fixed in ``docs/data/historical_screen_replay_registration.json``
before any licensed data is bought): in a survivorship-free point-in-time universe,
does the screen's buy tier beat (a) the equal-weight universe and (b) a plain
"cheapest 30% on earnings yield" sort of the same names, after costs?

The harness scores each historical rebalance date with ``run_library_screen`` on a
scratch library root, so the replay runs the same code as the offline screen.
Forward returns use the first panel date on or after the horizon, as in
``screen_premise_backtest``. Parity with that backtest on the committed FTSE run
snapshots is checked daily by ops-monitor.

Licensed raw data (Sharadar personal licence) must stay outside this public repo.
``run`` refuses inputs inside the repo, and only cohort-level aggregates are
written to ``docs/data/historical_screen_replay.json``. Never changes signals,
books, or knobs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, stdev
from typing import Any

import pandas as pd

from value_investor.screen_premise_backtest import spearman

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parents[1]
DEFAULT_DATA_DIR = Path("docs/data")
DEFAULT_REGISTRATION_PATH = REPO_ROOT / "docs/data/historical_screen_replay_registration.json"
DEFAULT_STORE_PATH = Path("docs/data/historical_screen_replay.json")
DEFAULT_PREMISE_STORE_PATH = Path("docs/data/screen_premise_backtest.json")

SCREEN_CODE_PATHS = (
    "models",
    "scoring/__init__.py",
    "model_families.py",
    "model_weights.py",
    "signals.py",
    "sector_scoring.py",
    "data_quality.py",
    "signal_stability.py",
)
BUY_TIER = frozenset({"buy", "strong_buy"})
Z90 = 1.645
MIN_COHORT_NAMES = 5
PARITY_HORIZONS = (7, 28)
PARITY_MAX_ABS_RETURN = 0.5
PARITY_TOLERANCE = 1.5e-4
PARITY_FIELDS = ("buy_tier_spread", "avoid_spread", "rank_ic")

PARITY_FINDING_TITLE = "Historical screen replay harness disagrees with screen-premise backtest"
STALE_REGISTRATION_TITLE = "Historical screen replay registration predates screen code"
STALE_VERDICT_TITLE = "Historical screen replay verdict no longer describes the live screen"
HOLDOUT_REUSED_TITLE = "Historical screen replay holdout revealed more than once"


def screen_code_fingerprint(package_dir: Path = PACKAGE_DIR) -> str:
    """SHA-256 over the modules that turn metrics into signals."""
    digest = hashlib.sha256()
    for rel in SCREEN_CODE_PATHS:
        path = package_dir / rel
        files = sorted(path.rglob("*.py")) if path.is_dir() else [path]
        for file in files:
            digest.update(file.relative_to(package_dir).as_posix().encode())
            digest.update(b"\0")
            digest.update(file.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def load_registration(path: Path = DEFAULT_REGISTRATION_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _utc(value: Any) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    return stamp.tz_localize(UTC) if stamp.tzinfo is None else stamp.tz_convert(UTC)


def replay_screen(panel: pd.DataFrame, *, market_id: str, scratch_root: Path) -> pd.DataFrame:
    """Score each ``as_of`` slice of a point-in-time metrics panel with the library screen.

    ``panel`` has one row per (``as_of``, ``ticker``) with ``sector`` and the
    Yahoo-style metric columns the models read. Dates run in order so signal
    history and stability build up as they did live.
    """
    from value_investor.data_library import market_dir
    from value_investor.library_screen import run_library_screen
    from value_investor.storage import write_json

    frames: list[pd.DataFrame] = []
    root = Path(scratch_root)
    for as_of, rows in sorted(panel.groupby("as_of"), key=lambda item: _utc(item[0])):
        run_at = _utc(as_of)
        records = rows.drop(columns=["as_of"]).to_dict(orient="records")
        tickers = [str(r["ticker"]) for r in records]
        mdir = market_dir(root, market_id)
        write_json(mdir / "metrics" / "latest.json.gz", records, compact=True, compress=True)
        write_json(
            mdir / "manifest.json",
            {
                "ticker_count": len(tickers),
                "coverage_count": len(tickers),
                "coverage_pct": 1.0,
                "tickers": tickers,
            },
            compact=False,
        )
        result = run_library_screen(root, market_id, run_at=run_at.to_pydatetime())
        signals = result.signals
        earnings_yield = (
            result.universe.set_index("ticker")["earnings_yield_pe"]
            if "earnings_yield_pe" in result.universe.columns
            else pd.Series(dtype=float)
        )
        blank = pd.Series([None] * len(signals), index=signals.index)
        frame = pd.DataFrame(
            {
                "as_of": run_at,
                "ticker": signals["ticker"].astype(str),
                "signal": signals["signal"].astype(str),
                "conviction_score": pd.to_numeric(
                    signals.get("conviction_score", blank), errors="coerce"
                ).fillna(0.0),
                "sector": signals.get("sector", blank).fillna(""),
            }
        )
        frame["earnings_yield"] = pd.to_numeric(
            frame["ticker"].map(earnings_yield), errors="coerce"
        )
        frames.append(frame)
    if not frames:
        return pd.DataFrame(
            columns=["as_of", "ticker", "signal", "conviction_score", "sector", "earnings_yield"]
        )
    return pd.concat(frames, ignore_index=True)


def plain_value_tickers(cohort: pd.DataFrame, top_share: float = 0.3) -> set[str]:
    """Top ``top_share`` of names by positive earnings yield (the French E/P high sort)."""
    positive = cohort.loc[pd.to_numeric(cohort["earnings_yield"], errors="coerce") > 0]
    if positive.empty:
        return set()
    cutoff = positive["earnings_yield"].quantile(1.0 - top_share)
    return set(positive.loc[positive["earnings_yield"] >= cutoff, "ticker"].astype(str))


def forward_returns(
    prices: pd.DataFrame,
    entries: Iterable[Any],
    horizon_days: int,
    *,
    terminal_haircuts: Mapping[str, float] | None = None,
) -> pd.DataFrame:
    """Per (entry, ticker) forward return from a long price panel.

    ``prices`` has ``date``, ``ticker``, ``close`` (total-return adjusted for the
    replay; raw snapshot prices for parity). Entry price is the ticker's price on
    the entry date. The exit date is the first panel date on or after
    ``entry + horizon`` (and after the entry). A ticker with no exit price whose
    series ended before the exit date and that appears in ``terminal_haircuts``
    exits at its last price times ``1 + haircut`` (delisting); otherwise it is dropped.
    """
    frame = prices.assign(date=prices["date"].map(_utc))
    dates = sorted(frame["date"].unique())
    by_key = frame.set_index(["date", "ticker"])["close"]
    last = frame.sort_values("date").groupby("ticker").tail(1).set_index("ticker")
    haircuts = dict(terminal_haircuts or {})
    rows: list[dict[str, Any]] = []
    for raw_entry in entries:
        entry = _utc(raw_entry)
        target = entry + pd.Timedelta(days=horizon_days)
        exit_date = next((d for d in dates if d >= target and d > entry), None)
        if exit_date is None:
            continue
        for ticker, p0 in frame.loc[frame["date"] == entry, ["ticker", "close"]].itertuples(
            index=False
        ):
            if not p0 or p0 <= 0:
                continue
            p1 = by_key.get((exit_date, ticker))
            exit_kind = "price"
            if p1 is not None and not pd.isna(p1) and p1 <= 0:
                continue
            if p1 is None or pd.isna(p1):
                if ticker not in haircuts or ticker not in last.index:
                    continue
                if last.at[ticker, "date"] <= entry or last.at[ticker, "date"] >= exit_date:
                    continue
                p1 = float(last.at[ticker, "close"]) * (1.0 + float(haircuts[ticker]))
                exit_kind = "terminal"
            rows.append(
                {
                    "as_of": entry,
                    "exit": exit_date,
                    "ticker": ticker,
                    "ret": float(p1) / float(p0) - 1.0,
                    "exit_kind": exit_kind,
                }
            )
    return pd.DataFrame(rows, columns=["as_of", "exit", "ticker", "ret", "exit_kind"])


def score_cohort(
    cohort: pd.DataFrame,
    *,
    max_abs_return: float | None = None,
    previous_buy: set[str] | None = None,
) -> dict[str, Any] | None:
    """Spreads for one entry date. ``cohort`` joins signals with forward returns."""
    rows = cohort
    dropped = 0
    if max_abs_return is not None:
        keep = rows["ret"].abs() <= max_abs_return
        dropped = int((~keep).sum())
        rows = rows.loc[keep]
    buy = rows.loc[rows["signal"].isin(BUY_TIER)]
    if len(rows) < MIN_COHORT_NAMES or len(buy) < MIN_COHORT_NAMES:
        return None
    universe = float(rows["ret"].mean())
    avoid = rows.loc[rows["signal"] == "avoid", "ret"]
    plain = plain_value_tickers(rows) if "earnings_yield" in rows.columns else set()
    plain_rets = rows.loc[rows["ticker"].isin(plain), "ret"]
    buy_names = set(buy["ticker"])
    turnover = (
        1.0 - len(buy_names & previous_buy) / len(buy_names) if previous_buy is not None else 1.0
    )
    rank_ic = spearman(rows["conviction_score"].astype(float).tolist(), rows["ret"].tolist())
    buy_spread = float(buy["ret"].mean()) - universe
    plain_spread = (
        float(plain_rets.mean()) - universe if len(plain_rets) >= MIN_COHORT_NAMES else None
    )
    return {
        "entry": rows["as_of"].iloc[0].isoformat(),
        "names": int(len(rows)),
        "buy_tier_names": int(len(buy)),
        "universe_return": round(universe, 4),
        "buy_tier_spread": round(buy_spread, 4),
        "avoid_spread": round(float(avoid.mean()) - universe, 4) if len(avoid) else None,
        "rank_ic": None if rank_ic is None else round(rank_ic, 4),
        "plain_value_spread": None if plain_spread is None else round(plain_spread, 4),
        "buy_minus_plain_value": (
            None if plain_spread is None else round(buy_spread - plain_spread, 4)
        ),
        "buy_tier_turnover": round(turnover, 4),
        "dropped_extreme_returns": dropped,
        "terminal_exits": int((rows.get("exit_kind") == "terminal").sum())
        if "exit_kind" in rows.columns
        else 0,
    }


def score_cohorts(
    signals: pd.DataFrame,
    returns: pd.DataFrame,
    *,
    horizon_days: int,
    max_abs_return: float | None = None,
) -> list[dict[str, Any]]:
    """Score every entry date; turnover compares with the entry one horizon earlier."""
    sig = signals.assign(as_of=signals["as_of"].map(_utc))
    rets = returns.assign(as_of=returns["as_of"].map(_utc))
    joined = sig.merge(rets, on=["as_of", "ticker"], how="inner")
    buy_by_date = {
        as_of: set(group.loc[group["signal"].isin(BUY_TIER), "ticker"])
        for as_of, group in sig.groupby("as_of")
    }
    dates = sorted(buy_by_date)
    out: list[dict[str, Any]] = []
    for as_of, cohort in sorted(joined.groupby("as_of"), key=lambda item: item[0]):
        lookback = as_of - pd.Timedelta(days=horizon_days)
        earlier = [d for d in dates if d <= lookback]
        previous = buy_by_date[earlier[-1]] if earlier else None
        scored = score_cohort(cohort, max_abs_return=max_abs_return, previous_buy=previous)
        if scored is not None:
            out.append(scored)
    return out


def summarise(values: list[float], *, step_days: float, horizon_days: int) -> dict[str, Any]:
    """Mean with a 90% interval on an overlap-discounted effective sample."""
    n = len(values)
    if n == 0:
        return {"cohorts": 0}
    avg = mean(values)
    sd = stdev(values) if n > 1 else None
    eff_n = max(1.0, n * min(step_days, horizon_days) / horizon_days)
    half = Z90 * sd / math.sqrt(eff_n) if sd is not None and eff_n >= 2 else None
    per_year = 365.0 / horizon_days
    return {
        "cohorts": n,
        "effective_n": round(eff_n, 1),
        "mean": round(avg, 4),
        "stdev": None if sd is None else round(sd, 4),
        "ci90_low": None if half is None else round(avg - half, 4),
        "ci90_high": None if half is None else round(avg + half, 4),
        "annualised_mean": round(avg * per_year, 4),
        "min_detectable_annual_edge": None if half is None else round(half * per_year, 4),
    }


def summarise_window(
    cohorts: list[dict[str, Any]],
    *,
    step_days: float,
    horizon_days: int,
    cost_per_side: float,
    stress_cost_per_side: float,
) -> dict[str, Any]:
    def pick(key: str) -> list[float]:
        return [c[key] for c in cohorts if c.get(key) is not None]

    def net(cost: float) -> list[float]:
        return [c["buy_tier_spread"] - 2.0 * cost * c["buy_tier_turnover"] for c in cohorts]

    kwargs = {"step_days": step_days, "horizon_days": horizon_days}
    return {
        "cohorts": len(cohorts),
        "first_entry": cohorts[0]["entry"] if cohorts else None,
        "last_entry": cohorts[-1]["entry"] if cohorts else None,
        "buy_tier_spread": summarise(pick("buy_tier_spread"), **kwargs),
        "buy_tier_spread_net": summarise(net(cost_per_side), **kwargs),
        "buy_tier_spread_net_stress": summarise(net(stress_cost_per_side), **kwargs),
        "plain_value_spread": summarise(pick("plain_value_spread"), **kwargs),
        "buy_minus_plain_value": summarise(pick("buy_minus_plain_value"), **kwargs),
        "avoid_spread": summarise(pick("avoid_spread"), **kwargs),
        "rank_ic": summarise(pick("rank_ic"), **kwargs),
        "mean_buy_tier_turnover": round(mean(pick("buy_tier_turnover")), 4) if cohorts else None,
        "terminal_exits": sum(int(c.get("terminal_exits") or 0) for c in cohorts),
    }


def verdict(window: dict[str, Any], primary: str) -> str:
    stats = window.get(primary) or {}
    low, high = stats.get("ci90_low"), stats.get("ci90_high")
    if low is None or high is None:
        return "too_thin"
    if low > 0:
        return "pass"
    if high < 0:
        return "fail"
    return "inconclusive"


def build_replay_results(
    signals: pd.DataFrame,
    prices: pd.DataFrame,
    registration: Mapping[str, Any],
    *,
    terminal_haircuts: Mapping[str, float] | None = None,
    reveal_holdout: bool = False,
) -> dict[str, Any]:
    """Development and (optionally) holdout windows for every registered horizon.

    Holdout cohorts are counted but their statistics stay sealed unless
    ``reveal_holdout`` is set. Per-ticker rows never leave this function.
    """
    windows = registration["windows"]
    costs = registration["costs"]
    primary = registration["primary"]
    step_days = float(registration["rebalance"]["step_days"])
    dev_end = _utc(windows["development"]["last_entry"])
    hold_start = _utc(windows["holdout"]["first_entry"])
    entries = sorted({_utc(v) for v in signals["as_of"]})
    out: dict[str, Any] = {}
    for horizon in registration["horizons_days"]:
        rets = forward_returns(prices, entries, horizon, terminal_haircuts=terminal_haircuts)
        cohorts = score_cohorts(signals, rets, horizon_days=horizon)
        dev = [c for c in cohorts if _utc(c["entry"]) <= dev_end]
        hold = [c for c in cohorts if _utc(c["entry"]) >= hold_start]
        kwargs = {
            "step_days": step_days,
            "horizon_days": horizon,
            "cost_per_side": float(costs["base_per_side"]),
            "stress_cost_per_side": float(costs["stress_per_side"]),
        }
        dev_summary = summarise_window(dev, **kwargs)
        entry: dict[str, Any] = {"horizon_days": horizon, "development": dev_summary}
        if reveal_holdout:
            entry["holdout"] = summarise_window(hold, **kwargs)
        else:
            entry["holdout"] = {"sealed": True, "cohorts": len(hold)}
        if horizon == primary["horizon_days"]:
            entry["development_verdict"] = verdict(dev_summary, primary["metric"])
            if reveal_holdout:
                entry["holdout_verdict"] = verdict(entry["holdout"], primary["metric"])
                entry["holdout_secondary_verdict"] = verdict(
                    entry["holdout"], primary["secondary_metric"]
                )
        out[str(horizon)] = entry
    return out


# --- Parity with the frozen-signal FTSE backtest ----------------------------------------


def panels_from_run_snapshots(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Signals and price panels from ``docs/data/history`` run snapshots, plus cohort entries."""
    from value_investor.backtest import load_run_snapshots
    from value_investor.screen_premise_backtest import weekly_cohorts

    snapshots = load_run_snapshots(Path(data_dir))
    price_rows = [
        {"date": snap.run_at, "ticker": ticker, "close": price}
        for snap in snapshots
        for ticker, price in snap.prices.items()
    ]
    cohorts = weekly_cohorts(snapshots)
    signal_rows = [
        {
            "as_of": snap.run_at,
            "ticker": str(row.get("ticker") or ""),
            "signal": str(row.get("signal") or ""),
            "conviction_score": float(row.get("conviction_score") or 0.0),
            "sector": str(row.get("sector") or ""),
        }
        for snap in cohorts
        for row in snap.signals
    ]
    return (
        pd.DataFrame(
            signal_rows, columns=["as_of", "ticker", "signal", "conviction_score", "sector"]
        ),
        pd.DataFrame(price_rows, columns=["date", "ticker", "close"]),
        [snap.run_at for snap in cohorts],
    )


def parity_with_screen_premise(data_dir: Path, premise: Mapping[str, Any]) -> dict[str, Any]:
    """Re-score the FTSE snapshot cohorts with this harness and diff against the premise store."""
    signals, prices, entries = panels_from_run_snapshots(data_dir)
    if signals.empty or not premise.get("horizons"):
        return {"status": "skipped", "reason": "no run snapshots or premise store"}
    checked = 0
    max_diff = 0.0
    mismatches: list[dict[str, Any]] = []
    for horizon in PARITY_HORIZONS:
        stored = {
            _utc(c["entry"]): c
            for c in ((premise["horizons"].get(str(horizon)) or {}).get("cohorts") or [])
        }
        rets = forward_returns(prices, entries, horizon)
        mine = {
            _utc(c["entry"]): c
            for c in score_cohorts(
                signals, rets, horizon_days=horizon, max_abs_return=PARITY_MAX_ABS_RETURN
            )
        }
        for entry in sorted(set(stored) | set(mine)):
            theirs, ours = stored.get(entry), mine.get(entry)
            if theirs is None or ours is None:
                mismatches.append(
                    {
                        "horizon_days": horizon,
                        "entry": entry.isoformat(),
                        "field": "cohort_presence",
                    }
                )
                continue
            for field in PARITY_FIELDS:
                a, b = theirs.get(field), ours.get(field)
                checked += 1
                if a is None and b is None:
                    continue
                if a is None or b is None or abs(float(a) - float(b)) > PARITY_TOLERANCE:
                    mismatches.append(
                        {
                            "horizon_days": horizon,
                            "entry": entry.isoformat(),
                            "field": field,
                            "premise": a,
                            "harness": b,
                        }
                    )
                    continue
                max_diff = max(max_diff, abs(float(a) - float(b)))
    return {
        "status": "ok" if not mismatches else "mismatch",
        "values_checked": checked,
        "max_abs_diff": round(max_diff, 6),
        "tolerance": PARITY_TOLERANCE,
        "mismatches": mismatches[:10],
        "mismatch_count": len(mismatches),
    }


# --- Store, findings, CLI -----------------------------------------------------------------


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def refresh_historical_screen_replay(
    data_dir: Path = DEFAULT_DATA_DIR,
    *,
    store_path: Path = DEFAULT_STORE_PATH,
    registration_path: Path = DEFAULT_REGISTRATION_PATH,
    premise_store_path: Path = DEFAULT_PREMISE_STORE_PATH,
    persist: bool = True,
) -> dict[str, Any]:
    """Daily status: registration fingerprint, harness parity, and any committed results."""
    previous = _read_json(store_path) or {}
    registration = load_registration(registration_path)
    current = screen_code_fingerprint()
    premise = _read_json(premise_store_path) or {}
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "observe_only": True,
        "registration_id": registration.get("registration_id"),
        "registration": {
            "registered_fingerprint": registration.get("screen_code_fingerprint"),
            "current_fingerprint": current,
            "matches_screen_code": registration.get("screen_code_fingerprint") == current,
        },
        "parity": parity_with_screen_premise(data_dir, premise),
        "results": previous.get("results"),
        "holdout_reveals": list(previous.get("holdout_reveals") or []),
    }
    if persist:
        _write_store(store_path, payload)
    return payload


def _write_store(path: Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def findings_from_store(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    parity = payload.get("parity") or {}
    if parity.get("status") == "mismatch":
        findings.append(
            {
                "severity": "warn",
                "category": "backtest",
                "title": PARITY_FINDING_TITLE,
                "summary": (
                    f"{parity.get('mismatch_count')} cohort values differ from "
                    "screen_premise_backtest.json beyond "
                    f"{parity.get('tolerance')}. Fix the harness before any licensed replay. "
                    "See docs/ops/historical-screen-replay.md."
                ),
                "auto_fixable": False,
            }
        )
    reveals = payload.get("holdout_reveals") or []
    matches = (payload.get("registration") or {}).get("matches_screen_code")
    if matches is False:
        if reveals:
            findings.append(
                {
                    "severity": "warn",
                    "category": "backtest",
                    "title": STALE_VERDICT_TITLE,
                    "summary": (
                        "Screen code changed after the holdout was revealed. The replay verdict "
                        "describes the registered screen, not the live one. A new run is "
                        "exploratory: the holdout is spent. See docs/ops/historical-screen-replay.md."
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
                        "Screen code changed since the replay was registered. Re-register "
                        "(python -m value_investor.historical_screen_replay register) before "
                        "the licensed run; the holdout is still sealed."
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
                    f"The holdout was revealed {len(reveals)} times. Only the first reveal is "
                    "evidence; later ones are exploratory."
                ),
                "auto_fixable": False,
            }
        )
    return findings


def _inside_repo(path: Path) -> bool:
    return Path(path).resolve().is_relative_to(REPO_ROOT.resolve())


def _read_table(path: Path) -> pd.DataFrame:
    path = Path(path)
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _data_fingerprint(*frames: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    for frame in frames:
        digest.update(pd.util.hash_pandas_object(frame, index=False).values.tobytes())
    return digest.hexdigest()


def run_replay(
    panel_path: Path,
    prices_path: Path,
    *,
    terminal_path: Path | None = None,
    registration_path: Path = DEFAULT_REGISTRATION_PATH,
    store_path: Path = DEFAULT_STORE_PATH,
    reveal_holdout: bool = False,
    scratch_root: Path | None = None,
) -> dict[str, Any]:
    """Replay the registered screen on a local point-in-time panel and commit aggregates only."""
    for path in (panel_path, prices_path, terminal_path, scratch_root):
        if path is not None and _inside_repo(path):
            raise ValueError(
                f"{path} is inside the repository. Licensed data must stay outside this public repo."
            )
    registration = load_registration(registration_path)
    if registration.get("screen_code_fingerprint") != screen_code_fingerprint():
        raise ValueError("Screen code changed since registration; run `register` first.")
    previous = _read_json(store_path) or {}
    if reveal_holdout and previous.get("holdout_reveals"):
        print("Holdout already revealed; this reveal is recorded as exploratory.")
    panel = _read_table(panel_path)
    prices = _read_table(prices_path)
    haircuts: dict[str, float] = {}
    if terminal_path is not None:
        terminal = _read_table(terminal_path)
        haircuts = dict(
            zip(terminal["ticker"].astype(str), terminal["haircut"].astype(float), strict=True)
        )
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(scratch_root) if scratch_root is not None else Path(tmp)
        signals = replay_screen(panel, market_id=registration["market_id"], scratch_root=root)
    results = build_replay_results(
        signals,
        prices,
        registration,
        terminal_haircuts=haircuts,
        reveal_holdout=reveal_holdout,
    )
    now = datetime.now(UTC).isoformat()
    reveals = list(previous.get("holdout_reveals") or [])
    if reveal_holdout:
        reveals.append({"at": now, "evidence": not reveals})
    payload = {
        **previous,
        "registration_id": registration.get("registration_id"),
        "results": {
            "run_at": now,
            "data_fingerprint": _data_fingerprint(panel, prices),
            "rebalance_dates": int(signals["as_of"].nunique()),
            "tickers": int(signals["ticker"].nunique()),
            "horizons": results,
        },
        "holdout_reveals": reveals,
    }
    _write_store(store_path, payload)
    return payload


def register(
    registration_path: Path = DEFAULT_REGISTRATION_PATH, store_path: Path = DEFAULT_STORE_PATH
) -> str:
    """Refresh the registered screen fingerprint. Refused once the holdout has been revealed."""
    store = _read_json(store_path) or {}
    if store.get("holdout_reveals"):
        raise ValueError("Holdout already revealed; open a new registration_id instead.")
    registration = load_registration(registration_path)
    registration["screen_code_fingerprint"] = screen_code_fingerprint()
    registration["registered_at"] = datetime.now(UTC).isoformat()
    _write_store(registration_path, registration)
    return registration["screen_code_fingerprint"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ftse-historical-replay", description=__doc__.split("\n")[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Refresh fingerprint and parity status (what ops-monitor runs)")
    sub.add_parser("register", help="Re-freeze the screen fingerprint while the holdout is sealed")
    run_p = sub.add_parser("run", help="Replay on a local licensed panel (outside the repo)")
    run_p.add_argument("--panel", type=Path, required=True)
    run_p.add_argument("--prices", type=Path, required=True)
    run_p.add_argument("--terminal", type=Path, help="CSV of ticker,haircut for delistings")
    run_p.add_argument("--scratch", type=Path)
    run_p.add_argument("--reveal-holdout", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "status":
        payload = refresh_historical_screen_replay()
        print(json.dumps({k: payload[k] for k in ("registration", "parity")}, indent=2))
    elif args.command == "register":
        print(register())
    else:
        payload = run_replay(
            args.panel,
            args.prices,
            terminal_path=args.terminal,
            scratch_root=args.scratch,
            reveal_holdout=args.reveal_holdout,
        )
        print(json.dumps(payload["results"]["horizons"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
