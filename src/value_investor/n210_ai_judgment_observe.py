"""N210 sealed observe-only: fixed-stake AI/filter judgment (B3).

registration_id: ``strand-e-ai-judgment-fixed-stake-v0``

Walks archived weekly screen snapshots, opens progressive fixed-stake episodes
when a name newly clears the AI/filter identity (``adjusted_signal`` buy-tier +
``research_verdict=accumulate`` + ``min_conviction=0.6``), and exits at 63
trading days or identity break. Scores fair-cost episode % independently of
fund NAV. Unfiltered buy-tier cohort median is report-only.

Observe-only — never writes strand A books, knobs, or ``decision-review --apply``.
Does not steal P1 from holdings / N200 (launch-queue waiter). Does not touch
matched-30 fund twins (B3 dual).

See ``docs/ops/n210-ai-judgment-observe.md``.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from value_investor.backtest import RunSnapshot, load_run_snapshots
from value_investor.market_trading_costs import (
    LEGACY_STRESS_TRADE_COST_PCT,
    LIVE_PAPER_MARKET_ID,
    costs_for_market,
)
from value_investor.paper_fund import BUY_SIGNALS
from value_investor.research.verdict import coerce_research_verdict
from value_investor.sealed_lifecycle import with_fair_cost_open_mark
from value_investor.volume_interestingness import (
    N210_INTERESTINGNESS_TITLE,
    VOLUME_THICKNESS_SUMMARY_SUFFIX,
    evaluate_n210_interestingness,
    interestingness_finding,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = Path("docs/data")
DEFAULT_STORE_PATH = Path("docs/data/n210_ai_judgment_observe.json")
DEFAULT_REGISTRATION_PATH = Path("docs/data/n210_ai_judgment_registration.json")
DEFAULT_OPS_STATUS_PATH = Path("docs/data/ops_status.json")
DEFAULT_OPS_DOC = Path("docs/ops/n210-ai-judgment-observe.md")

REGISTRATION_ID = "strand-e-ai-judgment-fixed-stake-v0"
DEFERRED_ID = "N210"
IDENTITY_ID = "ai_filter_accumulate_min_conviction_0_6"
SUCCESS_METRIC_ID = "smooth_ret_cohort_median"
SCHEMA_VERSION = 2
PIPELINE_HEALTH_SCHEMA_VERSION = 1
SEAL_MARKER_ID = "n210-seal-v0"
WALKER_MARKER_ID = "n210-episode-walker-v0"
PIPELINE_STATUS = "episode_walker_active"
# Legacy stub label retained for ops-history / grep; no longer emitted.
STUB_PIPELINE_STATUS = "stub_awaiting_episode_walker"

DEFAULT_STALE_AFTER_HOURS = 30.0
DEFAULT_STORE_LAG_WARN_HOURS = 2.0
PIPELINE_HEALTH_DISCLAIMER = (
    "Phase floor and sample-thickness volume gate measure factory mechanism "
    "throughput — not alpha or capital readiness (F8). Alone-path "
    "interestingness is separate Push/checklist heat. Fixed-stake episode % "
    "is independent of fund NAV. Open episodes with 0 completed is honest "
    "thin-marks state while the walker runs. Observe-only; never assessment "
    "primary crown; matched-30 pots untouched."
)

VOLUME_MIN_EPISODES = 48
VOLUME_MIN_WEEKS = 8
PHASE_ENTRIES_PER_WEEK_FLOOR = 8.0
FIXED_STAKE_UNITS = 100.0
HOLD_TRADING_DAYS = 63
MIN_CONVICTION = 0.6
MAX_EPISODES = 500
DEFAULT_MARKET_ID = LIVE_PAPER_MARKET_ID
STRESS_TRADE_COST_PCT = LEGACY_STRESS_TRADE_COST_PCT

FINDING_TITLE = "N210 AI-judgment observe refreshed"
STORE_FAILED_TITLE = "N210 AI-judgment observe failed"
VOLUME_GATE_TITLE = "N210 volume gate ready for review"
INTERESTINGNESS_TITLE = N210_INTERESTINGNESS_TITLE
STUB_TITLE = "N210 AI-judgment observe registered (awaiting episode pipeline)"

F9_BIND_FIELDS = (
    "key_filing_bodies",
    "fcf_basis_bound",
    "overlay_bound",
    "memo_recent",
)

ELIGIBILITY_MODE = "entry_fields_required_f9_or_pass"

LEARNING_QUESTION = (
    "On threshold-eligible FTSE names, does the AI/filter identity "
    "(adjusted_signal + research_verdict=accumulate, min_conviction=0.6) "
    "improve fair-cost episode % vs an unfiltered buy-tier draw of the same "
    "eligible set, sized as a fixed-stake mechanical test?"
)

BUY_TIER_BASELINE = {
    "id": "unfiltered_buy_tier_fixed_stake_v0",
    "definition": (
        "Same universe and market-native returns; raw screen buy/strong_buy "
        "(no adjusted_signal / accumulate / conviction floor); same 63 "
        "trading-day or leave-buy-tier exit; same fixed 100 local stake; "
        "fair per-market costs. Excess vs strategy is report-only."
    ),
    "identity_id": "raw_buy_tier",
    "use_adjusted_signal": False,
    "require_research_accumulate": False,
    "min_conviction": 0.0,
    "hold_trading_days": HOLD_TRADING_DAYS,
    "fixed_stake_units": FIXED_STAKE_UNITS,
    "role": "report_only",
}

# Minimal UK holidays for weekday busday when no session calendar is available.
_FTSE_HOLIDAYS = frozenset(
    {
        "2025-01-01",
        "2025-04-18",
        "2025-04-21",
        "2025-05-05",
        "2025-05-26",
        "2025-08-25",
        "2025-12-25",
        "2025-12-26",
        "2026-01-01",
        "2026-04-03",
        "2026-04-06",
        "2026-05-04",
        "2026-05-25",
        "2026-08-31",
        "2026-12-25",
        "2026-12-28",
    }
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_run_at(value: str) -> datetime:
    from value_investor.backtest import _parse_run_at

    return _parse_run_at(value)


def _days_between(start: str, end: str) -> int:
    return max(0, int((_parse_run_at(end) - _parse_run_at(start)).total_seconds() // 86400))


def trading_days_between(start: str, end: str) -> int:
    """Count trading days in ``(start, end]`` with a small UK holiday table."""
    a = _parse_run_at(start).date()
    b = _parse_run_at(end).date()
    if b <= a:
        return 0
    holidays = sorted(_FTSE_HOLIDAYS)
    try:
        return int(np.busday_count(a, b, holidays=holidays))
    except Exception:  # noqa: BLE001 — never break observe on calendar quirks
        from datetime import timedelta

        days = 0
        cur = a + timedelta(days=1)
        while cur <= b:
            if cur.weekday() < 5 and cur.isoformat() not in _FTSE_HOLIDAYS:
                days += 1
            cur += timedelta(days=1)
        return days


def _truthy_bind(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"", "none", "null"}:
        return None
    if text in {"0", "false", "no", "missing", "stale"}:
        return False
    return True


def row_f9_eligible(row: dict[str, Any]) -> tuple[bool, str]:
    """F9 per-name binds when present; else pass with note (archive MVP)."""
    present = 0
    for bind_field in F9_BIND_FIELDS:
        flag = _truthy_bind(row.get(bind_field))
        if flag is None:
            continue
        present += 1
        if not flag:
            return False, f"f9_fail:{bind_field}"
    if present == 0:
        return True, "eligibility_mode=row_fields_or_pass"
    return True, "f9_binds_ok"


def _row_market_id(row: dict[str, Any], default: str = DEFAULT_MARKET_ID) -> str:
    mid = str(row.get("market_id") or row.get("market") or "").strip()
    return mid or default


def _screen_signal(row: dict[str, Any], *, use_adjusted_signal: bool) -> str:
    signal = str(row.get("signal") or "").strip()
    if use_adjusted_signal:
        adjusted = row.get("adjusted_signal")
        if adjusted is not None and str(adjusted).strip():
            signal = str(adjusted).strip()
    return signal


def _conviction(row: dict[str, Any]) -> float | None:
    raw = row.get("conviction_score")
    if raw is None:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    if val != val:  # NaN
        return None
    return val


def _entry_filter_state(
    row: dict[str, Any],
    *,
    use_adjusted_signal: bool,
    require_research_accumulate: bool,
    min_conviction: float,
    skip_timing_wait: bool = True,
) -> tuple[bool, str, dict[str, Any]]:
    """Return (passes, note, detail). Missing required AI fields → soft gap."""
    signal = _screen_signal(row, use_adjusted_signal=use_adjusted_signal)
    conviction = _conviction(row)
    verdict_raw = row.get("research_verdict")
    verdict = (
        coerce_research_verdict(str(verdict_raw) if verdict_raw is not None else None)
        if require_research_accumulate
        else None
    )
    detail = {
        "signal": signal,
        "use_adjusted_signal": use_adjusted_signal,
        "research_verdict": verdict,
        "conviction_score": conviction,
        "min_conviction": float(min_conviction),
        "require_research_accumulate": require_research_accumulate,
        "timing_signal": row.get("timing_signal"),
    }
    if use_adjusted_signal and not str(row.get("adjusted_signal") or "").strip():
        # Prefer explicit overlay; fall back to raw signal only when present.
        if not str(row.get("signal") or "").strip():
            return False, "soft_gap_missing_signal", detail
    if signal not in BUY_SIGNALS:
        return False, "not_buy_tier", detail
    if skip_timing_wait and row.get("timing_signal") == "wait":
        return False, "timing_wait", detail
    if require_research_accumulate:
        if verdict_raw is None or str(verdict_raw).strip() == "":
            return False, "soft_gap_missing_research_verdict", detail
        if verdict != "accumulate":
            return False, "research_not_accumulate", detail
    if float(min_conviction) > 0:
        if conviction is None:
            return False, "soft_gap_missing_conviction", detail
        if conviction < float(min_conviction):
            return False, "conviction_below_floor", detail
    return True, "entry_filters_clear", detail


def episode_return(
    entry_price: float,
    exit_price: float,
    *,
    trade_cost_pct: float | None = None,
    buy_cost_pct: float | None = None,
    sell_cost_pct: float | None = None,
) -> float:
    """Round-trip cost-aware simple return (stake cancels — % only)."""
    raw = exit_price / entry_price - 1.0
    if buy_cost_pct is not None and sell_cost_pct is not None:
        return raw - float(buy_cost_pct) - float(sell_cost_pct)
    if trade_cost_pct is None:
        raise ValueError("Provide buy_cost_pct+sell_cost_pct or trade_cost_pct")
    return raw - 2.0 * float(trade_cost_pct)


def fixed_stake_pnl(
    entry_price: float,
    exit_price: float,
    *,
    stake_units: float = FIXED_STAKE_UNITS,
    buy_cost_pct: float,
    sell_cost_pct: float,
) -> dict[str, float]:
    """P&L on a fixed local-currency stake; scoreboard uses ``return_pct`` only."""
    ret = episode_return(
        entry_price, exit_price, buy_cost_pct=buy_cost_pct, sell_cost_pct=sell_cost_pct
    )
    return {
        "stake_units": float(stake_units),
        "return_pct": ret,
        "pnl_local": float(stake_units) * ret,
    }


def _snapshot_rows(snapshot: RunSnapshot) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in snapshot.signals:
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue
        price = snapshot.prices.get(ticker)
        if price is None or float(price) <= 0:
            continue
        out[ticker] = row
    return out


def _price_at(snapshots: list[RunSnapshot], idx: int, ticker: str) -> float | None:
    price = snapshots[idx].prices.get(ticker)
    if price is None or float(price) <= 0:
        return None
    return float(price)


def _latest_quote(
    snapshots: list[RunSnapshot],
    ticker: str,
    *,
    from_idx: int = 0,
) -> tuple[float | None, str | None]:
    """Latest real archive quote for ``ticker`` at or after ``from_idx``."""
    start = max(0, int(from_idx))
    for idx in range(len(snapshots) - 1, start - 1, -1):
        price = _price_at(snapshots, idx, ticker)
        if price is not None:
            return price, snapshots[idx].run_at
    return None, None


def _median_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(float(statistics.median(values)), 6)


@dataclass(frozen=True)
class N210Config:
    market_id: str = DEFAULT_MARKET_ID
    buy_cost_pct: float | None = None
    sell_cost_pct: float | None = None
    stress_trade_cost_pct: float = STRESS_TRADE_COST_PCT
    volume_min_episodes: int = VOLUME_MIN_EPISODES
    volume_min_weeks: int = VOLUME_MIN_WEEKS
    phase_entries_per_week_floor: float = PHASE_ENTRIES_PER_WEEK_FLOOR
    hold_trading_days: int = HOLD_TRADING_DAYS
    fixed_stake_units: float = FIXED_STAKE_UNITS
    min_conviction: float = MIN_CONVICTION
    max_episodes: int = MAX_EPISODES
    skip_timing_wait: bool = True

    def primary_buy_sell(self, market_id: str | None = None) -> tuple[float, float]:
        if self.buy_cost_pct is not None and self.sell_cost_pct is not None:
            return float(self.buy_cost_pct), float(self.sell_cost_pct)
        model = costs_for_market(market_id or self.market_id)
        return float(model.buy_pct), float(model.sell_pct)

    def primary_cost_fields(self, market_id: str | None = None) -> dict[str, Any]:
        mid = market_id or self.market_id
        model = costs_for_market(mid)
        buy, sell = self.primary_buy_sell(mid)
        return {
            "primary": "fair_market_table",
            "market_id": model.market_id,
            "buy_cost_pct": round(buy, 6),
            "sell_cost_pct": round(sell, 6),
            "round_trip_pct": round(buy + sell, 6),
            "trade_cost_pct_symmetric_proxy": round((buy + sell) / 2.0, 6),
            "source": model.source,
            "stress_trade_cost_pct": float(self.stress_trade_cost_pct),
            "stress_role": "report_only",
        }


def build_registration_payload(*, sealed_at: str | None = None) -> dict[str, Any]:
    cfg = N210Config()
    cost = cfg.primary_cost_fields()
    return {
        "schema_version": SCHEMA_VERSION,
        "registration_id": REGISTRATION_ID,
        "deferred_id": DEFERRED_ID,
        "status": "sealed_observe_only",
        "sealed_at": sealed_at or "2026-10-15",
        "observe_only": True,
        "influences_live": False,
        "b3_epoch": True,
        "pipeline_status": PIPELINE_STATUS,
        "learning_question": LEARNING_QUESTION,
        "identity_id": IDENTITY_ID,
        "success_metric_id": SUCCESS_METRIC_ID,
        "o2_identity": IDENTITY_ID,
        "entry_filters": {
            "use_adjusted_signal": True,
            "require_research_accumulate": True,
            "min_conviction": MIN_CONVICTION,
            "skip_timing_wait": True,
            "source": "ai_judgment_fair_gate_identity",
            "note": (
                "Reuse existing AI/filter gates (F4) — no new screen extras. "
                "Known limit: gate may not bind at 0.6 (same as parent; N189)."
            ),
        },
        "buy_trigger": "next_eligible_weekly_refresh_after_filters_clear",
        "exit": {
            "hold_trading_days": HOLD_TRADING_DAYS,
            "or_identity_break": True,
            "whichever_first": True,
            "archive_trading_day_proxy": "busday_uk_holidays",
        },
        "sizing": {
            "mode": "fixed_stake",
            "stake_units": FIXED_STAKE_UNITS,
            "stake_currency": "local_market",
            "cash_fund_nav": "parked",
            "scoreboard_unit": "fair_cost_episode_pct",
            "dca": "not_on_v0",
        },
        "universe": {
            "markets": "ftse350",
            "returns": "market_native",
            "fx_conversion": False,
        },
        "buy_tier_baseline": BUY_TIER_BASELINE,
        "o3_volume_gate": {
            "completed_entry_episodes_min": VOLUME_MIN_EPISODES,
            "calendar_weeks_spanned_min": VOLUME_MIN_WEEKS,
            "rule": "both_required",
        },
        "o4_smoother": SUCCESS_METRIC_ID,
        "o5_primacy": {
            "primary": "absolute_smoothed_return_fair_costs",
            "unfiltered_buy_tier_excess": "report_only",
            "stress_cost": "report_only",
            "matched30_fund_nav": "separate_instrument",
        },
        "o6_phase_floor": {
            "entries_per_week_target": PHASE_ENTRIES_PER_WEEK_FLOOR,
            "note": "mechanism floor only — not alpha",
        },
        "cost_basis": cost,
        "trade_cost_pct": cost["trade_cost_pct_symmetric_proxy"],
        "buy_cost_pct": cost["buy_cost_pct"],
        "sell_cost_pct": cost["sell_cost_pct"],
        "stress_trade_cost_pct": cost["stress_trade_cost_pct"],
        "eligibility_mode": ELIGIBILITY_MODE,
        "launch_queue": {
            "enqueued": True,
            "rank_note": (
                "B3 judgment observe — Data deepen / shortlist demand waits behind "
                "holdings and already-running sealed units (N200). Do not steal P1."
            ),
            "doc": "docs/ops/data-pillar-priorities.md",
        },
        "constraints": [
            "observe_only",
            "no_live_strand_a_writes",
            "no_decision_review_apply",
            "no_new_screen_extras",
            "f8_fail_closed",
            "fixed_stake_not_fund_nav",
            "fair_costs_primary",
            "stress_cost_report_only",
            "o3_alone_first",
            "b3_dual_shadow",
            "no_matched30_touch",
            "logged_change_markers",
        ],
        "ops_doc": str(DEFAULT_OPS_DOC),
        "observe_store": str(DEFAULT_STORE_PATH),
        "matched_fund_twin_track": "ai_judgment_matched30_fair",
        "matched_control_twin_track": "buy_tier_matched30_fair",
    }


def _find_exit_index(
    snapshots: list[RunSnapshot],
    entry_idx: int,
    ticker: str,
    *,
    hold_trading_days: int,
    use_adjusted_signal: bool,
    require_research_accumulate: bool,
    min_conviction: float,
    skip_timing_wait: bool,
) -> tuple[int | None, str | None]:
    """Exit at hold horizon or identity break, whichever first."""
    entry_at = snapshots[entry_idx].run_at
    for j in range(entry_idx + 1, len(snapshots)):
        row_map = _snapshot_rows(snapshots[j])
        row = row_map.get(ticker)
        reason: str | None = None
        if row is None:
            reason = "identity_break_missing_row"
        else:
            ok, note, _ = _entry_filter_state(
                row,
                use_adjusted_signal=use_adjusted_signal,
                require_research_accumulate=require_research_accumulate,
                min_conviction=min_conviction,
                skip_timing_wait=skip_timing_wait,
            )
            if not ok and not note.startswith("soft_gap_missing"):
                reason = f"identity_break_{note}"
            # Soft-gap mid-flight: do not invent a break — wait for horizon.
        if reason is not None:
            return j, reason
        held = trading_days_between(entry_at, snapshots[j].run_at)
        if held >= hold_trading_days:
            return j, "hold_trading_days"
    return None, None


def _sealed_lifecycle_rows(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from value_investor.sealed_lifecycle import slim_lifecycle_episodes

    return slim_lifecycle_episodes(episodes)


def build_n210_observe(
    snapshots: list[RunSnapshot],
    *,
    cfg: N210Config | None = None,
    generated_at: str | None = None,
    prior_markers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Score N210 fixed-stake AI-filter episodes from archive snapshots."""
    cfg = cfg or N210Config()
    cost_fields = cfg.primary_cost_fields()
    stress_pct = float(cfg.stress_trade_cost_pct)

    strategy_returns: list[float] = []
    control_returns: list[float] = []
    stress_returns: list[float] = []
    episodes: list[dict[str, Any]] = []
    open_episodes: list[dict[str, Any]] = []
    skipped_missing_fields = 0
    skipped_ineligible = 0
    skipped_filters = 0

    prev_strategy: set[str] = set()
    prev_control: set[str] = set()

    for i, snap in enumerate(snapshots):
        row_map = _snapshot_rows(snap)
        strategy_clear: set[str] = set()
        control_clear: set[str] = set()
        for ticker, row in row_map.items():
            ok, note, _ = _entry_filter_state(
                row,
                use_adjusted_signal=True,
                require_research_accumulate=True,
                min_conviction=cfg.min_conviction,
                skip_timing_wait=cfg.skip_timing_wait,
            )
            if ok:
                strategy_clear.add(ticker)
            elif note.startswith("soft_gap_missing") and ticker not in prev_strategy:
                # Count candidates that look buyish but lack overlay fields.
                raw_sig = str(row.get("signal") or "").strip()
                if raw_sig in BUY_SIGNALS or str(row.get("adjusted_signal") or "").strip():
                    skipped_missing_fields += 1

            ctrl_ok, _ctrl_note, _ = _entry_filter_state(
                row,
                use_adjusted_signal=False,
                require_research_accumulate=False,
                min_conviction=0.0,
                skip_timing_wait=cfg.skip_timing_wait,
            )
            if ctrl_ok:
                control_clear.add(ticker)

        # Progressive strategy entries.
        for ticker in sorted(strategy_clear - prev_strategy):
            row = row_map[ticker]
            eligible, elig_note = row_f9_eligible(row)
            if not eligible:
                skipped_ineligible += 1
                continue
            ok, note, detail = _entry_filter_state(
                row,
                use_adjusted_signal=True,
                require_research_accumulate=True,
                min_conviction=cfg.min_conviction,
                skip_timing_wait=cfg.skip_timing_wait,
            )
            if not ok:
                if note.startswith("soft_gap_missing"):
                    skipped_missing_fields += 1
                else:
                    skipped_filters += 1
                continue

            mid = _row_market_id(row, cfg.market_id)
            exit_idx, exit_reason = _find_exit_index(
                snapshots,
                i,
                ticker,
                hold_trading_days=cfg.hold_trading_days,
                use_adjusted_signal=True,
                require_research_accumulate=True,
                min_conviction=cfg.min_conviction,
                skip_timing_wait=cfg.skip_timing_wait,
            )
            buy_pct, sell_pct = cfg.primary_buy_sell(mid)
            if exit_idx is None:
                # Display-only open mark from real archive quotes; not path primary.
                p_entry = _price_at(snapshots, i, ticker)
                p_mark, mark_at = _latest_quote(snapshots, ticker, from_idx=i)
                open_episodes.append(
                    with_fair_cost_open_mark(
                        {
                            "ticker": ticker,
                            "market_id": mid,
                            "cohort": "ai_filter",
                            "entry_run_at": snap.run_at,
                            "status": "open",
                            "eligibility": elig_note,
                            "entry_detail": detail,
                            "fixed_stake_units": cfg.fixed_stake_units,
                            "influences_live": False,
                        },
                        entry_price=p_entry,
                        mark_price=p_mark,
                        buy_cost_pct=buy_pct,
                        sell_cost_pct=sell_pct,
                        mark_run_at=mark_at,
                    )
                )
                continue

            p_entry = _price_at(snapshots, i, ticker)
            p_exit = _price_at(snapshots, exit_idx, ticker)
            if p_entry is None or p_exit is None:
                continue

            stake = fixed_stake_pnl(
                p_entry,
                p_exit,
                stake_units=cfg.fixed_stake_units,
                buy_cost_pct=buy_pct,
                sell_cost_pct=sell_pct,
            )
            strategy_returns.append(stake["return_pct"])
            stress_ret = episode_return(p_entry, p_exit, trade_cost_pct=stress_pct)
            stress_returns.append(stress_ret)

            episodes.append(
                {
                    "ticker": ticker,
                    "market_id": mid,
                    "cohort": "ai_filter",
                    "entry_run_at": snap.run_at,
                    "exit_run_at": snapshots[exit_idx].run_at,
                    "hold_trading_days": trading_days_between(
                        snap.run_at, snapshots[exit_idx].run_at
                    ),
                    "exit_reason": exit_reason,
                    "eligibility": elig_note,
                    "entry_detail": detail,
                    "fixed_stake_units": cfg.fixed_stake_units,
                    "return_pct": round(stake["return_pct"], 6),
                    "pnl_local_report_only": round(stake["pnl_local"], 6),
                    "return_pct_stress_report_only": round(stress_ret, 6),
                    "scoreboard_unit": "fair_cost_episode_pct",
                    "independent_of_fund_nav": True,
                    "influences_live": False,
                }
            )
            if len(episodes) >= cfg.max_episodes:
                break

        # Progressive unfiltered buy-tier control (report-only cohort).
        if len(episodes) < cfg.max_episodes:
            for ticker in sorted(control_clear - prev_control):
                row = row_map[ticker]
                eligible, elig_note = row_f9_eligible(row)
                if not eligible:
                    continue
                mid = _row_market_id(row, cfg.market_id)
                exit_idx, exit_reason = _find_exit_index(
                    snapshots,
                    i,
                    ticker,
                    hold_trading_days=cfg.hold_trading_days,
                    use_adjusted_signal=False,
                    require_research_accumulate=False,
                    min_conviction=0.0,
                    skip_timing_wait=cfg.skip_timing_wait,
                )
                if exit_idx is None:
                    continue
                buy_pct, sell_pct = cfg.primary_buy_sell(mid)
                p_entry = _price_at(snapshots, i, ticker)
                p_exit = _price_at(snapshots, exit_idx, ticker)
                if p_entry is None or p_exit is None:
                    continue
                stake = fixed_stake_pnl(
                    p_entry,
                    p_exit,
                    stake_units=cfg.fixed_stake_units,
                    buy_cost_pct=buy_pct,
                    sell_cost_pct=sell_pct,
                )
                control_returns.append(stake["return_pct"])

        prev_strategy = strategy_clear
        prev_control = control_clear
        if len(episodes) >= cfg.max_episodes:
            break

    absolute_primary = _median_or_none(strategy_returns)
    control_median = _median_or_none(control_returns)
    stress_median = _median_or_none(stress_returns)
    control_excess = None
    if absolute_primary is not None and control_median is not None:
        control_excess = round(absolute_primary - control_median, 6)

    weeks = 0
    if len(snapshots) >= 2:
        weeks = max(1, _days_between(snapshots[0].run_at, snapshots[-1].run_at) // 7)
    elif snapshots:
        weeks = 1
    entries_per_week = round(len(episodes) / weeks, 3) if weeks else None
    volume_gate_met = len(episodes) >= cfg.volume_min_episodes and weeks >= cfg.volume_min_weeks
    phase_ok = entries_per_week is not None and entries_per_week >= cfg.phase_entries_per_week_floor

    seal_marker = {
        "id": SEAL_MARKER_ID,
        "marker_id": SEAL_MARKER_ID,
        "at": "2026-10-15",
        "summary": (
            "B3 lock: seal fixed-stake AI/filter judgment observe as "
            "evidentiary primary for filter LQ (shadow until volume gates)."
        ),
    }
    walker_marker = {
        "id": WALKER_MARKER_ID,
        "marker_id": WALKER_MARKER_ID,
        "at": generated_at or _utc_now(),
        "summary": (
            "Episode walker active: progressive fixed-stake entries on AI/filter "
            "clear; 63d or identity-break exit; fair-cost episode % primary; "
            "unfiltered buy-tier excess report-only; influences_live=false."
        ),
    }
    markers = list(prior_markers or [])
    if not any(
        m.get("id") == SEAL_MARKER_ID or m.get("marker_id") == SEAL_MARKER_ID for m in markers
    ):
        markers.insert(0, seal_marker)
    if not any(
        m.get("id") == WALKER_MARKER_ID or m.get("marker_id") == WALKER_MARKER_ID for m in markers
    ):
        markers.append(walker_marker)

    out: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or _utc_now(),
        "registration_id": REGISTRATION_ID,
        "deferred_id": DEFERRED_ID,
        "status": "sealed_observe_only",
        "observe_only": True,
        "influences_live": False,
        "independent_of_fund_nav": True,
        "b3_epoch": True,
        "pipeline_status": PIPELINE_STATUS,
        "learning_question": LEARNING_QUESTION,
        "identity_id": IDENTITY_ID,
        "success_metric_id": SUCCESS_METRIC_ID,
        "eligibility_mode": ELIGIBILITY_MODE,
        "sizing": {
            "mode": "fixed_stake",
            "stake_units": cfg.fixed_stake_units,
            "cash_fund_nav": "parked",
            "scoreboard_unit": "fair_cost_episode_pct",
            "independent_of_fund_nav": True,
        },
        "buy_tier_baseline": BUY_TIER_BASELINE,
        "cost_basis": cost_fields,
        "snapshot_count": len(snapshots),
        "completed_entry_episodes": len(episodes),
        "open_entry_episodes": len(open_episodes),
        "control_completed_entry_episodes_report_only": len(control_returns),
        "skipped_missing_entry_fields": skipped_missing_fields,
        "skipped_ineligible": skipped_ineligible,
        "skipped_filters": skipped_filters,
        "calendar_weeks_spanned": weeks,
        "volume_gate": {
            "min_episodes": cfg.volume_min_episodes,
            "min_weeks": cfg.volume_min_weeks,
            "met": volume_gate_met,
            "rule": "both_required",
            "role": "sample_thickness_pipeline_badge",
        },
        "phase": {
            "entries_per_week": entries_per_week,
            "floor": cfg.phase_entries_per_week_floor,
            "floor_met": phase_ok,
        },
        "path_scoreboard": {
            "primary": "absolute_smoothed_return_fair_costs",
            "success_metric_id": SUCCESS_METRIC_ID,
            "scoreboard_unit": "fair_cost_episode_pct",
            "smooth_ret_cohort_median": absolute_primary,
            "smooth_ret_cohort_median_stress_report_only": stress_median,
            "unfiltered_buy_tier_smooth_ret_cohort_median_report_only": control_median,
            "unfiltered_buy_tier_excess_report_only": control_excess,
            "completed_entry_episodes": len(strategy_returns),
            "open_entry_episodes": len(open_episodes),
            "n": len(strategy_returns),
            "independent_of_fund_nav": True,
            "companions": {
                "volume_toward_gate": f"{len(episodes)}/{cfg.volume_min_episodes}",
                "open_episodes": len(open_episodes),
                "calendar_weeks_spanned": weeks,
                "weeks_toward_gate": f"{weeks}/{cfg.volume_min_weeks}",
                "control_episodes_report_only": len(control_returns),
                "stress_cost": "report_only",
            },
            "note": (
                "Primary is fair-cost episode % cohort median on fixed-stake "
                "AI/filter entries. Fund NAV / cash drag not used. Unfiltered "
                "buy-tier excess and stress 3%/side are report-only (F8). "
                "Matched-30 fund twins are a separate B3 instrument."
            ),
        },
        "stress_scoreboard_report_only": {
            "trade_cost_pct_per_side": stress_pct,
            "smooth_ret_cohort_median": stress_median,
            "n": len(stress_returns),
            "role": "report_only",
        },
        "launch_queue": {
            "enqueued": True,
            "rank_note": (
                "Waiter behind holdings + running sealed units (N200). "
                "Do not divert P1 deepen until launch-queue head."
            ),
            "doc": "docs/ops/data-pillar-priorities.md",
        },
        "change_markers": markers,
        "episodes_sample": episodes[:25],
        "open_episodes_sample": open_episodes[:25],
        "lifecycle_episodes": _sealed_lifecycle_rows([*episodes, *open_episodes]),
        "soft_gaps": [
            (
                "AI overlay fields (adjusted_signal / research_verdict / "
                "conviction_score) may be sparse on older archive rows — "
                "fail-closed soft-gap skip (F8)."
            ),
            "Do not crown assessment_model primary from this observe (F8 / B3).",
            "Matched-30 pots are untouched — separate portfolio-shape twin.",
        ],
        "ops_doc": str(DEFAULT_OPS_DOC),
    }
    out["interestingness_gate"] = evaluate_n210_interestingness(out)
    return out


def refresh_n210_ai_judgment_observe(
    *,
    output_dir: Path | None = None,
    store_path: Path | None = None,
    registration_path: Path | None = None,
    persist: bool = True,
    cfg: N210Config | None = None,
    generated_at: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Load FTSE archive history, score fixed-stake AI-filter episodes, persist."""
    data_dir = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR
    store = Path(store_path) if store_path is not None else DEFAULT_STORE_PATH
    reg_path = (
        Path(registration_path) if registration_path is not None else DEFAULT_REGISTRATION_PATH
    )
    cfg = cfg or N210Config()

    prior_markers: list[dict[str, Any]] = []
    if store.is_file():
        try:
            prior = json.loads(store.read_text(encoding="utf-8"))
            markers = prior.get("change_markers")
            if isinstance(markers, list):
                prior_markers = [m for m in markers if isinstance(m, dict)]
        except (OSError, json.JSONDecodeError):
            prior_markers = []

    snapshots = load_run_snapshots(data_dir)
    when = generated_at
    if when is None and now is not None:
        when = now.isoformat()
    payload = build_n210_observe(
        snapshots,
        cfg=cfg,
        generated_at=when,
        prior_markers=prior_markers,
    )
    registration = build_registration_payload()
    if persist:
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        reg_path.write_text(json.dumps(registration, indent=2) + "\n", encoding="utf-8")
        from value_investor.sealed_lifecycle import publish_sealed_lifecycle_projection

        publish_sealed_lifecycle_projection(store.parent)
        payload["store_path"] = str(store)
        payload["registration_path"] = str(reg_path)
    return payload


def ops_findings_from_n210_observe(payload: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = [
        {
            "severity": "info",
            "category": "research",
            "title": FINDING_TITLE,
            "summary": (
                f"N210 ({REGISTRATION_ID}) refreshed; pipeline={payload.get('pipeline_status')}; "
                f"episodes={payload.get('completed_entry_episodes', 0)} "
                f"(open={payload.get('open_entry_episodes', 0)}); "
                f"weeks={payload.get('calendar_weeks_spanned', 0)}; "
                f"volume_gate_met={bool((payload.get('volume_gate') or {}).get('met'))}. "
                "Observe-only; influences_live=false; matched-30 untouched."
            ),
            "auto_fixable": False,
        }
    ]
    # Only emit legacy stub finding if a caller still passes a stub payload.
    if payload.get("pipeline_status") == STUB_PIPELINE_STATUS:
        findings.append(
            {
                "severity": "info",
                "category": "research",
                "title": STUB_TITLE,
                "summary": (
                    "B3 judgment observe is sealed as a registration stub. Episode walker "
                    "not yet producing marks — do not promote or apply knobs (F8). "
                    "Fair-cost episode % is the judgment primary once volume exists."
                ),
                "auto_fixable": False,
            }
        )
    gate = payload.get("volume_gate") or {}
    if gate.get("met"):
        findings.append(
            {
                "severity": "info",
                "category": "research",
                "title": VOLUME_GATE_TITLE,
                "summary": (
                    f"N210 sample thickness met (≥{VOLUME_MIN_EPISODES} episodes and "
                    f"≥{VOLUME_MIN_WEEKS} weeks). {VOLUME_THICKNESS_SUMMARY_SUFFIX}"
                ),
                "auto_fixable": False,
            }
        )
    # Always re-evaluate from current path fields (store stamp may lag).
    interesting_gate = evaluate_n210_interestingness(payload)
    interesting = interestingness_finding(
        title=INTERESTINGNESS_TITLE,
        gate=interesting_gate,
        strand_note="N210 AI-judgment (matched-30 crown separate).",
    )
    if interesting is not None:
        findings.append(interesting)
    return findings


def format_n210_observe_text(payload: dict[str, Any]) -> str:
    gate = payload.get("volume_gate") or {}
    path = payload.get("path_scoreboard") or {}
    lines = [
        f"N210 AI-judgment observe ({payload.get('registration_id')})",
        f"  status: {payload.get('status')}  pipeline: {payload.get('pipeline_status')}",
        f"  influences_live: {payload.get('influences_live')}",
        f"  episodes: {payload.get('completed_entry_episodes')} "
        f"(open={payload.get('open_entry_episodes', 0)})  "
        f"weeks: {payload.get('calendar_weeks_spanned')}",
        f"  median fair-cost episode %: {path.get('smooth_ret_cohort_median')}",
        f"  buy-tier excess (report-only): {path.get('unfiltered_buy_tier_excess_report_only')}",
        f"  volume_gate: met={gate.get('met')} "
        f"(need ≥{gate.get('min_episodes')}/{gate.get('min_weeks')}w)",
        f"  LQ: {payload.get('learning_question')}",
    ]
    return "\n".join(lines) + "\n"


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _hours_since(then: datetime | None, *, now: datetime) -> float | None:
    if then is None:
        return None
    return round((now - then).total_seconds() / 3600.0, 2)


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    path = Path(path)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _freshness_block(
    *,
    as_of: datetime | None,
    now: datetime,
    ops_run_at: datetime | None,
    stale_after_hours: float,
    store_lag_warn_hours: float,
    present: bool,
) -> dict[str, Any]:
    age_h = _hours_since(as_of, now=now)
    store_lag_h = None
    if as_of is not None and ops_run_at is not None and ops_run_at > as_of:
        store_lag_h = round((ops_run_at - as_of).total_seconds() / 3600.0, 2)

    if not present:
        state = "missing"
        label = "Missing"
        detail = "N210 observe store not published yet."
    elif age_h is None:
        state = "unknown"
        label = "Unknown"
        detail = "Store present but no usable timestamp."
    elif age_h >= stale_after_hours:
        state = "stale"
        label = "Stale"
        detail = f"Last refresh {age_h:.1f}h ago (limit {stale_after_hours:.0f}h)."
    elif store_lag_h is not None and store_lag_h >= store_lag_warn_hours:
        state = "lagging"
        label = "Lagging ops"
        detail = f"Store trails ops_status by {store_lag_h:.1f}h."
    else:
        state = "fresh"
        label = "Fresh"
        detail = f"Last refresh {age_h:.1f}h ago."

    return {
        "state": state,
        "label": label,
        "detail": detail,
        "as_of": as_of.isoformat() if as_of else None,
        "age_hours": age_h,
        "store_lag_hours": store_lag_h,
        "stale_after_hours": float(stale_after_hours),
    }


def _ops_n210_check_status(ops_status: dict[str, Any] | None) -> dict[str, Any]:
    findings = (ops_status or {}).get("findings")
    rows = findings if isinstance(findings, list) else []
    titles = {str(row.get("title") or "") for row in rows if isinstance(row, dict)}
    failed = STORE_FAILED_TITLE in titles
    refreshed = FINDING_TITLE in titles
    if failed:
        return {
            "ops_check_ok": False,
            "ops_finding_present": True,
            "detail": f"Ops finding: {STORE_FAILED_TITLE}",
        }
    if refreshed:
        return {
            "ops_check_ok": True,
            "ops_finding_present": True,
            "detail": f"Ops finding: {FINDING_TITLE}",
        }
    return {
        "ops_check_ok": False,
        "ops_finding_present": False,
        "detail": "No N210 ops finding in latest ops_status.",
    }


def build_n210_pipeline_health_projection(
    payload: dict[str, Any] | None = None,
    *,
    store_path: Path | None = None,
    ops_status_path: Path | None = None,
    ops_status: dict[str, Any] | None = None,
    now: datetime | None = None,
    stale_after_hours: float = DEFAULT_STALE_AFTER_HOURS,
    store_lag_warn_hours: float = DEFAULT_STORE_LAG_WARN_HOURS,
) -> dict[str, Any]:
    """Slim dashboard projection: phase, volume, open/completed, freshness.

    Reads the committed observe store (does **not** re-score archive history).
    Thin marks (0 completed + open > 0) are honest — walker alive, not a fail.
    Never assessment primary / never capital-ready (F8 / B3).
    """
    clock = now or datetime.now(UTC)
    store = Path(store_path) if store_path is not None else DEFAULT_STORE_PATH
    if payload is None:
        payload = _safe_read_json(store)
    present = isinstance(payload, dict) and bool(payload)

    if ops_status is None:
        ops_path = Path(ops_status_path) if ops_status_path is not None else DEFAULT_OPS_STATUS_PATH
        ops_status = _safe_read_json(ops_path)

    ops_run_at = _parse_dt((ops_status or {}).get("run_at"))
    store_as_of = _parse_dt((payload or {}).get("generated_at")) if present else None
    freshness = _freshness_block(
        as_of=store_as_of,
        now=clock,
        ops_run_at=ops_run_at,
        stale_after_hours=stale_after_hours,
        store_lag_warn_hours=store_lag_warn_hours,
        present=present,
    )
    ops_check = _ops_n210_check_status(ops_status)

    phase_raw = (payload or {}).get("phase") if present else None
    phase = phase_raw if isinstance(phase_raw, dict) else {}
    volume_raw = (payload or {}).get("volume_gate") if present else None
    volume = volume_raw if isinstance(volume_raw, dict) else {}
    path = (
        (payload or {}).get("path_scoreboard")
        if present and isinstance((payload or {}).get("path_scoreboard"), dict)
        else {}
    )
    companions = path.get("companions") if isinstance(path.get("companions"), dict) else {}

    episodes = int((payload or {}).get("completed_entry_episodes") or 0) if present else 0
    open_episodes = int((payload or {}).get("open_entry_episodes") or 0) if present else 0
    weeks = int((payload or {}).get("calendar_weeks_spanned") or 0) if present else 0
    pipeline_status = (str((payload or {}).get("pipeline_status") or "") if present else "") or None
    stub_gone = bool(
        present and pipeline_status != STUB_PIPELINE_STATUS and pipeline_status == PIPELINE_STATUS
    )
    walker_active = bool(present and pipeline_status == PIPELINE_STATUS)

    entries_pw = phase.get("entries_per_week")
    floor = phase.get("floor", PHASE_ENTRIES_PER_WEEK_FLOOR)
    floor_met = bool(phase.get("floor_met")) if present and "floor_met" in phase else False
    volume_met = bool(volume.get("met")) if present and "met" in volume else False
    freshness_ok = freshness["state"] in {"fresh", "lagging"}
    ops_ok = bool(ops_check["ops_check_ok"]) or (freshness["state"] == "fresh" and present)
    functioning = bool(present and freshness_ok and ops_ok)

    if not present:
        headline = "N210 observe store missing — pipeline not yet published."
    elif not functioning:
        headline = (
            f"N210 pipeline attention — freshness={freshness['state']}; "
            f"pipeline={pipeline_status or 'unknown'}; "
            f"open={open_episodes} completed={episodes}; "
            f"volume gate {'met' if volume_met else 'not met'}."
        )
    elif episodes == 0 and open_episodes > 0:
        headline = (
            f"N210 pipeline functioning — walker active; "
            f"{open_episodes} open / 0 completed (thin marks OK); "
            f"volume not yet met ({weeks} wk); "
            f"{SUCCESS_METRIC_ID}=null until first closes."
        )
    else:
        headline = (
            f"N210 pipeline functioning — phase {entries_pw}/{floor} "
            f"entries/week; volume {'met' if volume_met else 'not met'} "
            f"({episodes} ep / {weeks} wk; open={open_episodes}); "
            f"{SUCCESS_METRIC_ID}={path.get('smooth_ret_cohort_median')}."
        )

    return {
        "schema_version": PIPELINE_HEALTH_SCHEMA_VERSION,
        "generated_at": clock.isoformat(),
        "observe_only": True,
        "influences_live": False,
        "not_alpha_signal": True,
        "not_capital_ready": True,
        "not_assessment_primary": True,
        "independent_of_fund_nav": True,
        "launch_queue_waiter": True,
        "b3_epoch": True,
        "registration_id": (payload or {}).get("registration_id") or REGISTRATION_ID,
        "deferred_id": (payload or {}).get("deferred_id") or DEFERRED_ID,
        "headline": headline,
        "disclaimer": PIPELINE_HEALTH_DISCLAIMER,
        "store_present": present,
        "store_generated_at": store_as_of.isoformat() if store_as_of else None,
        "pipeline_status": pipeline_status,
        "stub_gone": stub_gone,
        "walker_active": walker_active,
        "phase": {
            "entries_per_week": entries_pw,
            "floor": floor,
            "floor_met": floor_met,
        },
        "volume_gate": {
            "met": volume_met,
            "episodes": episodes,
            "open_episodes": open_episodes,
            "weeks": weeks,
            "min_episodes": volume.get("min_episodes", VOLUME_MIN_EPISODES),
            "min_weeks": volume.get("min_weeks", VOLUME_MIN_WEEKS),
            "role": "sample_thickness_pipeline_badge",
        },
        "interestingness_gate": (
            (payload or {}).get("interestingness_gate")
            if present and isinstance((payload or {}).get("interestingness_gate"), dict)
            else evaluate_n210_interestingness(payload or {})
            if present
            else {"met": False, "thickness_met": False}
        ),
        "path_scoreboard": {
            "smooth_ret_cohort_median": path.get("smooth_ret_cohort_median"),
            "unfiltered_buy_tier_excess_report_only": path.get(
                "unfiltered_buy_tier_excess_report_only"
            ),
            "completed_entry_episodes": path.get("completed_entry_episodes", episodes),
            "open_entry_episodes": path.get("open_entry_episodes", open_episodes),
            "n": path.get("n", episodes),
            "independent_of_fund_nav": True,
            "companions": companions
            or {
                "volume_toward_gate": f"{episodes}/{VOLUME_MIN_EPISODES}",
                "open_episodes": open_episodes,
                "calendar_weeks_spanned": weeks,
            },
        },
        "freshness": freshness,
        "pipeline": {
            "functioning": functioning,
            "ops_check_ok": bool(ops_check["ops_check_ok"]),
            "ops_finding_present": bool(ops_check["ops_finding_present"]),
            "ops_run_at": ops_run_at.isoformat() if ops_run_at else None,
            "detail": f"{ops_check['detail']} {freshness['detail']}".strip(),
        },
        "ops_doc": str(DEFAULT_OPS_DOC),
    }
