"""N215 soft-veto → MONITOR → reentry observe (labels only).

Frozen pair: WARN+ band gate × R1 breakout-wait (R5 timeout 40d + R6 worsen
−15% pinned inside). Walks forward from sealed buy_ts with bars date ≤ t only.
Never influences live fills.

See ``docs/ops/n215-reentry-observe.md`` and Project store
``technical-veto-reentry-lq.md``.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.n215_technical_veto_observe import (
    BAND_WARN_LO,
    DEEP_LOSER,
    LARGE_WINNER,
    LOOKBACK_TRADING_DAYS,
    outcome_bucket,
    score_episode,
)
from value_investor.n215_technical_veto_observe import (
    RECIPE_ID as SOFT_RECIPE_ID,
)
from value_investor.price_charts import chart_filename

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = Path("docs/data")
DEFAULT_STORE_PATH = Path("docs/data/n215_reentry_observe.json")
DEFAULT_REGISTRATION_PATH = Path("docs/data/n215_reentry_registration.json")
DEFAULT_OPS_DOC = Path("docs/ops/n215-reentry-observe.md")
DEFAULT_N200_STORE = Path("docs/data/n200_tech_timing_observe.json")
DEFAULT_CHARTS_DIR = Path("docs/data/charts")
DEFAULT_SOFT_STORE = Path("docs/data/n215_technical_veto_observe.json")

REGISTRATION_ID = "n215-reentry-warn-r1-v0"
PAIR_ID = "WARN+_R1"
REENTRY_RULE_ID = "R1"
BAND_GATE = "WARN+"
DEFERRED_ID = "N215"
SCHEMA_VERSION = 1

LEARNING_QUESTION = (
    "Among soft-vetoed (WARN+) sealed N200 names that later became large winners "
    "under sealed baseline fair-cost, how often would frozen MONITOR rule R1 "
    "(breakout-wait; R5=40d / R6=−15%) have re-admitted before opportunity "
    "expired — vs never (timeout / worsen)? Companion: path-cost Δ vs sealed "
    "baseline on recovered names; abandon rate on WARN+ deep losers. "
    "Observe labels only — no live gate."
)

FINDING_TITLE = "N215 reentry observe (WARN+×R1) refreshed"
STORE_FAILED_TITLE = "N215 reentry observe failed"

# ---------------------------------------------------------------------------
# Frozen pins (pre-registered before scoring — do not retune on this cohort)
# ---------------------------------------------------------------------------

BREAKOUT_PCT = 0.01  # close > pre-t0 swing high by ≥1%
R5_TIMEOUT_SESSIONS = 40
R6_WORSEN_DD = -0.15  # drawdown from t0 close
MIN_FORWARD_BARS = 1  # need at least one post-buy bar to evaluate


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _med(xs: list[float]) -> float | None:
    if not xs:
        return None
    ys = sorted(xs)
    m = len(ys) // 2
    if len(ys) % 2:
        return ys[m]
    return (ys[m - 1] + ys[m]) / 2.0


def load_chart_series(
    charts_dir: Path,
    ticker: str,
) -> tuple[list[str], list[float]] | None:
    """Load full chart date/close series. None if missing/empty."""
    path = Path(charts_dir) / chart_filename(ticker)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    dates_raw = payload.get("dates") or []
    closes_raw = payload.get("closes") or []
    dates: list[str] = []
    closes: list[float] = []
    for i, raw_d in enumerate(dates_raw):
        if i >= len(closes_raw) or closes_raw[i] is None:
            continue
        try:
            c = float(closes_raw[i])
        except (TypeError, ValueError):
            continue
        if math.isnan(c) or math.isinf(c):
            continue
        dates.append(str(raw_d)[:10])
        closes.append(c)
    if not closes:
        return None
    return dates, closes


def pre_t0_swing_high(closes: list[float], t0_idx: int) -> float:
    """Lookback max close on bars ≤ t0 (frozen R1 reference peak)."""
    start = max(0, t0_idx + 1 - LOOKBACK_TRADING_DAYS)
    window = closes[start : t0_idx + 1]
    if not window:
        return closes[t0_idx]
    return max(window)


def _close_on_or_after(dates: list[str], closes: list[float], day: str) -> float | None:
    for d, c in zip(dates, closes, strict=True):
        if d >= day:
            return c
    return closes[-1] if closes else None


def _close_on_day(dates: list[str], closes: list[float], day: str) -> float | None:
    for d, c in zip(dates, closes, strict=True):
        if d == day:
            return c
    return None


def alt_path_return(
    *,
    dates: list[str],
    closes: list[float],
    reentry_idx: int,
    exit_day: str | None,
    baseline_hold_bars: int,
) -> tuple[float | None, str | None, dict[str, Any]]:
    """Fair-cost-style close→close path from reentry to exit proxy.

    Freeze: prefer sealed exit close when exit_day > reentry_day; else hold
    ``baseline_hold_bars`` trading days past reentry (or chart end).
    """
    reentry_px = closes[reentry_idx]
    if reentry_px <= 0:
        return None, None, {"reason": "nonpositive_reentry_px"}
    reentry_day = dates[reentry_idx]
    detail: dict[str, Any] = {
        "reentry_day": reentry_day,
        "reentry_px": reentry_px,
        "baseline_hold_bars": baseline_hold_bars,
    }
    exit_px: float | None = None
    exit_proxy_day: str | None = None
    method: str | None = None
    if exit_day and exit_day > reentry_day:
        px = _close_on_day(dates, closes, exit_day)
        if px is None:
            px = _close_on_or_after(dates, closes, exit_day)
        if px is not None:
            exit_px = px
            exit_proxy_day = exit_day
            method = "sealed_exit"
    if exit_px is None:
        hold = max(1, int(baseline_hold_bars) if baseline_hold_bars > 0 else 1)
        end_idx = min(len(closes) - 1, reentry_idx + hold)
        if end_idx <= reentry_idx:
            return None, None, {**detail, "reason": "no_post_reentry_bars"}
        exit_px = closes[end_idx]
        exit_proxy_day = dates[end_idx]
        method = "matched_hold_bars"
    detail["exit_proxy_day"] = exit_proxy_day
    detail["exit_px"] = exit_px
    detail["method"] = method
    return (exit_px / reentry_px) - 1.0, exit_proxy_day, detail


def walk_r1_monitor(
    *,
    dates: list[str],
    closes: list[float],
    buy_day: str,
    exit_day: str | None,
) -> dict[str, Any]:
    """Causal MONITOR walk for frozen R1 (+ R5/R6). Point-in-time only."""
    # t0 = last bar with date <= buy_day
    t0_idx = None
    for i, d in enumerate(dates):
        if d <= buy_day:
            t0_idx = i
        else:
            break
    if t0_idx is None:
        return {
            "evaluable": False,
            "label": "unevaluable",
            "reason": "no_bars_leq_buy_ts",
        }
    forward = len(dates) - (t0_idx + 1)
    if forward < MIN_FORWARD_BARS:
        return {
            "evaluable": False,
            "label": "unevaluable",
            "reason": "insufficient_forward_bars",
            "forward_bars": forward,
            "t0_idx": t0_idx,
            "t0_day": dates[t0_idx],
        }

    t0_close = closes[t0_idx]
    swing_high = pre_t0_swing_high(closes, t0_idx)
    breakout_level = swing_high * (1.0 + BREAKOUT_PCT)
    # Baseline hold length in trading bars (for alt-path matched horizon)
    exit_idx = None
    if exit_day:
        for i, d in enumerate(dates):
            if d >= exit_day:
                exit_idx = i
                break
    baseline_hold = (exit_idx - t0_idx) if exit_idx is not None and exit_idx > t0_idx else 5

    sessions_walked = 0
    min_dd = 0.0
    for step in range(1, R5_TIMEOUT_SESSIONS + 1):
        i = t0_idx + step
        if i >= len(closes):
            return {
                "evaluable": True,
                "label": "still_monitor_eop",
                "reason": "chart_ended_before_timeout",
                "sessions_walked": sessions_walked,
                "t0_day": dates[t0_idx],
                "t0_close": t0_close,
                "pre_t0_swing_high": swing_high,
                "breakout_level": breakout_level,
                "min_drawdown_from_t0": min_dd,
                "forward_bars_available": forward,
            }
        sessions_walked = step
        px = closes[i]
        dd = (px / t0_close) - 1.0 if t0_close > 0 else 0.0
        if dd < min_dd:
            min_dd = dd
        # R6 worsen abandon (checked before reentry same day — fail-closed skip)
        if dd <= R6_WORSEN_DD:
            return {
                "evaluable": True,
                "label": "abandoned_worsen",
                "reason": "r6_worsen",
                "sessions_walked": sessions_walked,
                "abandon_day": dates[i],
                "abandon_px": px,
                "t0_day": dates[t0_idx],
                "t0_close": t0_close,
                "pre_t0_swing_high": swing_high,
                "breakout_level": breakout_level,
                "min_drawdown_from_t0": min_dd,
                "drawdown_at_abandon": dd,
            }
        # R1 clear signal
        if px > breakout_level:
            alt_ret, exit_proxy, alt_detail = alt_path_return(
                dates=dates,
                closes=closes,
                reentry_idx=i,
                exit_day=exit_day,
                baseline_hold_bars=baseline_hold,
            )
            return {
                "evaluable": True,
                "label": "reentered",
                "reason": "r1_breakout",
                "sessions_walked": sessions_walked,
                "reentry_day": dates[i],
                "reentry_px": px,
                "t0_day": dates[t0_idx],
                "t0_close": t0_close,
                "pre_t0_swing_high": swing_high,
                "breakout_level": breakout_level,
                "min_drawdown_from_t0": min_dd,
                "alt_path_return": alt_ret,
                "exit_proxy_day": exit_proxy,
                "alt_path_detail": alt_detail,
                "baseline_hold_bars": baseline_hold,
            }

    return {
        "evaluable": True,
        "label": "abandoned_timeout",
        "reason": "r5_timeout",
        "sessions_walked": sessions_walked,
        "t0_day": dates[t0_idx],
        "t0_close": t0_close,
        "pre_t0_swing_high": swing_high,
        "breakout_level": breakout_level,
        "min_drawdown_from_t0": min_dd,
        "forward_bars_available": forward,
    }


def meets_band_gate(band: str, *, gate: str = BAND_GATE) -> bool:
    if gate == "WARN+":
        return band in {"WARN", "SOFT_VETO", "HARD_CANDIDATE"}
    if gate == "SOFT_VETO+":
        return band in {"SOFT_VETO", "HARD_CANDIDATE"}
    return False


def frozen_pair_blob() -> dict[str, Any]:
    return {
        "registration_id": REGISTRATION_ID,
        "pair_id": PAIR_ID,
        "band_gate": BAND_GATE,
        "band_gate_threshold": BAND_WARN_LO,
        "soft_recipe_id": SOFT_RECIPE_ID,
        "reentry_rule": REENTRY_RULE_ID,
        "reentry_rule_name": "breakout-wait",
        "breakout_pct": BREAKOUT_PCT,
        "pre_t0_swing_high": (f"max close in lookback {LOOKBACK_TRADING_DAYS}d with date ≤ buy_ts"),
        "r5_timeout_sessions": R5_TIMEOUT_SESSIONS,
        "r6_worsen_dd": R6_WORSEN_DD,
        "companion_gates_reported": ["WARN+", "SOFT_VETO+"],
        "deep_loser": DEEP_LOSER,
        "large_winner": LARGE_WINNER,
        "point_in_time": "forward walk uses bars with date ≤ t at each step",
        "note": (
            "Pre-registered before scoring. One progressive cell only — "
            "do not retune mid-cohort; Layer B separate from soft-band admit."
        ),
    }


def build_registration_payload(*, generated_at: str | None = None) -> dict[str, Any]:
    return {
        "registration_id": REGISTRATION_ID,
        "pair_id": PAIR_ID,
        "deferred_id": DEFERRED_ID,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or _utc_now(),
        "observe_only": True,
        "influences_live": False,
        "learning_question": LEARNING_QUESTION,
        "ops_doc": str(DEFAULT_OPS_DOC),
        "pair": frozen_pair_blob(),
        "cohort": {
            "primary": "N200 closed lifecycle episodes with soft band ≥ WARN",
            "soft_band_source": "score_episode / n215 soft-band recipe v0",
        },
    }


def _load_closed_episodes(store_path: Path) -> list[dict[str, Any]]:
    if not store_path.is_file():
        return []
    try:
        payload = json.loads(store_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("lifecycle_episodes") or []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "").lower() != "closed":
            continue
        ticker = str(row.get("ticker") or "").strip()
        buy_ts = str(row.get("entry_run_at") or "").strip()
        if not ticker or not buy_ts:
            continue
        fc = row.get("fair_cost_return")
        try:
            fair_cost = float(fc) if fc is not None else None
        except (TypeError, ValueError):
            fair_cost = None
        out.append(
            {
                "ticker": ticker,
                "book": "N200",
                "buy_ts": buy_ts,
                "exit_run_at": row.get("exit_run_at"),
                "fair_cost": fair_cost,
            }
        )
    return out


def score_reentry_episode(
    *,
    ticker: str,
    buy_ts: str,
    exit_run_at: str | None,
    fair_cost: float | None,
    charts_dir: Path,
    soft_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Soft-band at buy_ts + R1 monitor walk. Missing evidence → unevaluable."""
    buy_day = str(buy_ts)[:10]
    exit_day = str(exit_run_at)[:10] if exit_run_at else None
    bucket = outcome_bucket(fair_cost)
    base: dict[str, Any] = {
        "ticker": ticker,
        "book": "N200",
        "buy_ts": buy_ts,
        "buy_day": buy_day,
        "exit_run_at": exit_run_at,
        "exit_day": exit_day,
        "fair_cost": fair_cost,
        "bucket": bucket,
        "registration_id": REGISTRATION_ID,
        "pair_id": PAIR_ID,
        "influences_live": False,
        "observe_only": True,
    }

    if soft_row is None:
        soft_row = score_episode(
            ticker=ticker,
            book="N200",
            buy_ts=buy_ts,
            fair_cost=fair_cost,
            charts_dir=charts_dir,
        )
    band = str(soft_row.get("band") or "PASS")
    risk_score = float(soft_row.get("risk_score") or 0.0)
    base.update(
        {
            "soft_band": band,
            "risk_score": risk_score,
            "soft_fail_closed": bool(soft_row.get("fail_closed")),
            "soft_coverage": bool(soft_row.get("coverage")),
            "in_warn_plus": meets_band_gate(band, gate="WARN+"),
            "in_soft_plus": meets_band_gate(band, gate="SOFT_VETO+"),
        }
    )
    if not base["in_warn_plus"]:
        return {
            **base,
            "monitor_eligible": False,
            "evaluable": False,
            "label": "not_in_gate",
            "reason": "soft_band_below_WARN",
        }

    series = load_chart_series(charts_dir, ticker)
    if series is None:
        return {
            **base,
            "monitor_eligible": True,
            "evaluable": False,
            "label": "unevaluable",
            "reason": "missing_chart",
        }
    dates, closes = series
    walk = walk_r1_monitor(
        dates=dates,
        closes=closes,
        buy_day=buy_day,
        exit_day=exit_day,
    )
    label = str(walk.get("label") or "unevaluable")
    evaluable = bool(walk.get("evaluable"))
    path_delta = None
    alt_ret = walk.get("alt_path_return")
    if label == "reentered" and alt_ret is not None and fair_cost is not None:
        try:
            path_delta = float(alt_ret) - float(fair_cost)
        except (TypeError, ValueError):
            path_delta = None
    return {
        **base,
        "monitor_eligible": True,
        "evaluable": evaluable,
        "label": label,
        "reason": walk.get("reason"),
        "sessions_to_outcome": walk.get("sessions_walked"),
        "reentry_day": walk.get("reentry_day"),
        "abandon_day": walk.get("abandon_day"),
        "pre_t0_swing_high": walk.get("pre_t0_swing_high"),
        "breakout_level": walk.get("breakout_level"),
        "min_drawdown_from_t0": walk.get("min_drawdown_from_t0"),
        "alt_path_return": alt_ret,
        "path_cost_delta": path_delta,
        "exit_proxy_day": walk.get("exit_proxy_day"),
        "alt_path_detail": walk.get("alt_path_detail"),
        "walk": {
            k: v
            for k, v in walk.items()
            if k
            not in {
                "alt_path_detail",
            }
        },
    }


def _gate_rollup(rows: list[dict[str, Any]], *, gate: str) -> dict[str, Any]:
    if gate == "WARN+":
        gated = [r for r in rows if r.get("in_warn_plus")]
    else:
        gated = [r for r in rows if r.get("in_soft_plus")]
    large = [r for r in gated if r.get("bucket") == "large_winner"]
    deep = [r for r in gated if r.get("bucket") == "deep_loser"]

    def _terminal(subset: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Evaluable with a decisive label (exclude still_monitor_eop from rates)
        return [
            r
            for r in subset
            if r.get("evaluable")
            and r.get("label") in {"reentered", "abandoned_timeout", "abandoned_worsen"}
        ]

    large_term = _terminal(large)
    deep_term = _terminal(deep)
    large_readmit = [r for r in large_term if r.get("label") == "reentered"]
    large_never = [
        r for r in large_term if r.get("label") in {"abandoned_timeout", "abandoned_worsen"}
    ]
    deep_abandon = [
        r for r in deep_term if r.get("label") in {"abandoned_timeout", "abandoned_worsen"}
    ]
    deep_readmit = [r for r in deep_term if r.get("label") == "reentered"]
    still = [r for r in gated if r.get("label") == "still_monitor_eop"]
    uneval = [r for r in gated if r.get("label") == "unevaluable"]

    days = [
        float(r["sessions_to_outcome"])
        for r in large_readmit
        if r.get("sessions_to_outcome") is not None
    ]
    path_deltas = [
        float(r["path_cost_delta"]) for r in large_readmit if r.get("path_cost_delta") is not None
    ]
    alt_rets = [
        float(r["alt_path_return"]) for r in large_readmit if r.get("alt_path_return") is not None
    ]

    n_large_term = len(large_term)
    n_deep_term = len(deep_term)
    return {
        "gate": gate,
        "gated_n": len(gated),
        "large_winners_gated": len(large),
        "deep_losers_gated": len(deep),
        "large_terminal_n": n_large_term,
        "deep_terminal_n": n_deep_term,
        "re_admit_rate": (f"{len(large_readmit)}/{n_large_term}" if n_large_term else "0/0"),
        "re_admit_n": len(large_readmit),
        "never_rate": f"{len(large_never)}/{n_large_term}" if n_large_term else "0/0",
        "never_n": len(large_never),
        "median_days_to_reentry": _med(days),
        "path_cost_delta_median": _med(path_deltas),
        "alt_path_return_median": _med(alt_rets),
        "loser_abandon_rate": (f"{len(deep_abandon)}/{n_deep_term}" if n_deep_term else "0/0"),
        "loser_abandon_n": len(deep_abandon),
        "loser_re_admit_n": len(deep_readmit),
        "still_monitor_eop_n": len(still),
        "unevaluable_n": len(uneval),
        "large_winner_detail": [
            {
                "ticker": r.get("ticker"),
                "buy_day": r.get("buy_day"),
                "soft_band": r.get("soft_band"),
                "fair_cost": r.get("fair_cost"),
                "label": r.get("label"),
                "sessions_to_outcome": r.get("sessions_to_outcome"),
                "reentry_day": r.get("reentry_day"),
                "alt_path_return": r.get("alt_path_return"),
                "path_cost_delta": r.get("path_cost_delta"),
            }
            for r in large
        ],
        "deep_loser_detail": [
            {
                "ticker": r.get("ticker"),
                "buy_day": r.get("buy_day"),
                "soft_band": r.get("soft_band"),
                "fair_cost": r.get("fair_cost"),
                "label": r.get("label"),
                "sessions_to_outcome": r.get("sessions_to_outcome"),
            }
            for r in deep
        ],
    }


def build_n215_reentry_observe(
    episodes: list[dict[str, Any]],
    *,
    charts_dir: Path | None = None,
    soft_by_key: dict[tuple[str, str], dict[str, Any]] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Pure reentry score over sealed episode dicts."""
    chart_root = Path(charts_dir) if charts_dir is not None else DEFAULT_CHARTS_DIR
    rows: list[dict[str, Any]] = []
    for ep in episodes:
        ticker = str(ep["ticker"])
        buy_ts = str(ep["buy_ts"])
        key = (ticker, str(buy_ts)[:10])
        soft = soft_by_key.get(key) if soft_by_key else None
        rows.append(
            score_reentry_episode(
                ticker=ticker,
                buy_ts=buy_ts,
                exit_run_at=ep.get("exit_run_at"),
                fair_cost=ep.get("fair_cost"),
                charts_dir=chart_root,
                soft_row=soft,
            )
        )
    warn_rollup = _gate_rollup(rows, gate="WARN+")
    soft_rollup = _gate_rollup(rows, gate="SOFT_VETO+")
    # Primary cell verdict (observe sketch only)
    n_term = int(warn_rollup.get("large_terminal_n") or 0)
    n_readmit = int(warn_rollup.get("re_admit_n") or 0)
    n_never = int(warn_rollup.get("never_n") or 0)
    salvages = bool(n_term > 0 and n_readmit > n_never)
    return {
        "schema_version": SCHEMA_VERSION,
        "registration_id": REGISTRATION_ID,
        "pair_id": PAIR_ID,
        "deferred_id": DEFERRED_ID,
        "generated_at": generated_at or _utc_now(),
        "observe_only": True,
        "influences_live": False,
        "learning_question": LEARNING_QUESTION,
        "ops_doc": str(DEFAULT_OPS_DOC),
        "pair": frozen_pair_blob(),
        "cohort": {
            "N200_closed": len(rows),
            "warn_plus_gated": warn_rollup["gated_n"],
            "soft_plus_gated": soft_rollup["gated_n"],
            "warn_plus_large": warn_rollup["large_winners_gated"],
            "warn_plus_deep": warn_rollup["deep_losers_gated"],
        },
        "rollup": {
            "primary_WARN+_R1": warn_rollup,
            "companion_SOFT_VETO+_R1": soft_rollup,
        },
        "episodes": rows,
        "admit_recommendation": {
            "live_reentry": False,
            "live_veto": False,
            "pair_admit_worthy": False,
            "observe_sketch_salvages_soft_vetoed_winners": salvages,
            "note": (
                f"Primary WARN+×R1 re-admit {warn_rollup.get('re_admit_rate')} "
                f"never {warn_rollup.get('never_rate')}; "
                f"loser abandon {warn_rollup.get('loser_abandon_rate')}. "
                "Observe-only — Layer B not admitted; no live delay/reentry."
            ),
        },
    }


def _index_soft_store(soft_path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    if not soft_path.is_file():
        return {}
    try:
        payload = json.loads(soft_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in payload.get("episodes") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("book") or "") != "N200":
            continue
        ticker = str(row.get("ticker") or "")
        buy_day = str(row.get("buy_day") or str(row.get("buy_ts") or "")[:10])
        if ticker and buy_day:
            out[(ticker, buy_day)] = row
    return out


def refresh_n215_reentry_observe(
    *,
    output_dir: Path | None = None,
    store_path: Path | None = None,
    registration_path: Path | None = None,
    n200_store: Path | None = None,
    soft_store: Path | None = None,
    charts_dir: Path | None = None,
    persist: bool = True,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Load sealed N200 closed episodes + soft bands; walk R1 monitor."""
    data_dir = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR
    store = Path(store_path) if store_path is not None else DEFAULT_STORE_PATH
    reg_path = (
        Path(registration_path) if registration_path is not None else DEFAULT_REGISTRATION_PATH
    )
    n200_path = (
        Path(n200_store) if n200_store is not None else data_dir / "n200_tech_timing_observe.json"
    )
    soft_path = (
        Path(soft_store)
        if soft_store is not None
        else data_dir / "n215_technical_veto_observe.json"
    )
    chart_root = Path(charts_dir) if charts_dir is not None else data_dir / "charts"

    episodes = _load_closed_episodes(n200_path)
    soft_by_key = _index_soft_store(soft_path)
    payload = build_n215_reentry_observe(
        episodes,
        charts_dir=chart_root,
        soft_by_key=soft_by_key or None,
        generated_at=generated_at,
    )
    registration = build_registration_payload(generated_at=payload["generated_at"])
    if persist:
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        reg_path.write_text(json.dumps(registration, indent=2) + "\n", encoding="utf-8")
    return payload


def ops_findings_from_n215_reentry(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Map reentry observe store → ops-monitor finding dicts (warn-only)."""
    cohort = payload.get("cohort") if isinstance(payload.get("cohort"), dict) else {}
    rollup = payload.get("rollup") if isinstance(payload.get("rollup"), dict) else {}
    primary = (
        rollup.get("primary_WARN+_R1") if isinstance(rollup.get("primary_WARN+_R1"), dict) else {}
    )
    admit = (
        payload.get("admit_recommendation")
        if isinstance(payload.get("admit_recommendation"), dict)
        else {}
    )
    return [
        {
            "severity": "info",
            "category": "research",
            "title": FINDING_TITLE,
            "summary": (
                f"{REGISTRATION_ID}: N200 closed={cohort.get('N200_closed')}; "
                f"WARN+ gated={cohort.get('warn_plus_gated')} "
                f"(large={cohort.get('warn_plus_large')} "
                f"deep={cohort.get('warn_plus_deep')}); "
                f"re-admit={primary.get('re_admit_rate')} "
                f"never={primary.get('never_rate')}; "
                f"loser_abandon={primary.get('loser_abandon_rate')}; "
                f"path_Δ_med={primary.get('path_cost_delta_median')}. "
                f"salvages_sketch={admit.get('observe_sketch_salvages_soft_vetoed_winners')}. "
                "Observe-only — no live writes (F8)."
            ),
            "auto_fixable": False,
        }
    ]


def format_n215_reentry_text(payload: dict[str, Any]) -> str:
    cohort = payload.get("cohort") if isinstance(payload.get("cohort"), dict) else {}
    rollup = payload.get("rollup") if isinstance(payload.get("rollup"), dict) else {}
    primary = (
        rollup.get("primary_WARN+_R1") if isinstance(rollup.get("primary_WARN+_R1"), dict) else {}
    )
    soft = (
        rollup.get("companion_SOFT_VETO+_R1")
        if isinstance(rollup.get("companion_SOFT_VETO+_R1"), dict)
        else {}
    )
    admit = (
        payload.get("admit_recommendation")
        if isinstance(payload.get("admit_recommendation"), dict)
        else {}
    )
    lines = [
        f"N215 {payload.get('registration_id')} (observe-only reentry WARN+×R1)",
        f"pair={payload.get('pair_id')} influences_live={payload.get('influences_live')}",
        (
            f"cohort N200={cohort.get('N200_closed')} "
            f"WARN+={cohort.get('warn_plus_gated')} "
            f"(large={cohort.get('warn_plus_large')} deep={cohort.get('warn_plus_deep')})"
        ),
        (
            f"primary WARN+×R1: re-admit {primary.get('re_admit_rate')} "
            f"never {primary.get('never_rate')} "
            f"median_days={primary.get('median_days_to_reentry')} "
            f"path_Δ_med={primary.get('path_cost_delta_median')}"
        ),
        (
            f"loser abandon {primary.get('loser_abandon_rate')} "
            f"(re-admit losers={primary.get('loser_re_admit_n')})"
        ),
        (
            f"companion SOFT_VETO+×R1: re-admit {soft.get('re_admit_rate')} "
            f"never {soft.get('never_rate')} "
            f"loser_abandon {soft.get('loser_abandon_rate')}"
        ),
        f"admit: {admit.get('note')}",
    ]
    detail = primary.get("large_winner_detail") or []
    if detail:
        lines.append("large winners in WARN+:")
        for row in detail:
            lines.append(
                f"  {row.get('ticker')} {row.get('soft_band')} "
                f"fc={row.get('fair_cost')} → {row.get('label')} "
                f"d={row.get('sessions_to_outcome')} "
                f"alt={row.get('alt_path_return')} Δ={row.get('path_cost_delta')}"
            )
    return "\n".join(lines) + "\n"


# Re-export helpers tests may want
__all__ = [
    "BAND_GATE",
    "BAND_WARN_LO",
    "BREAKOUT_PCT",
    "DEFAULT_OPS_DOC",
    "DEFAULT_OUTPUT_DIR",
    "DEFAULT_REGISTRATION_PATH",
    "DEFAULT_STORE_PATH",
    "FINDING_TITLE",
    "PAIR_ID",
    "R5_TIMEOUT_SESSIONS",
    "R6_WORSEN_DD",
    "REGISTRATION_ID",
    "STORE_FAILED_TITLE",
    "build_n215_reentry_observe",
    "build_registration_payload",
    "format_n215_reentry_text",
    "frozen_pair_blob",
    "meets_band_gate",
    "ops_findings_from_n215_reentry",
    "pre_t0_swing_high",
    "refresh_n215_reentry_observe",
    "score_reentry_episode",
    "walk_r1_monitor",
]
