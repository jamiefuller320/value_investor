"""N201 sealed observe-only: short-horizon plain-EY + 12–1 momentum.

registration_id: ``strand-c-short-horizon-value-mom-v0``

Walks archived weekly screen snapshots, opens fixed-stake episodes when a name
newly clears plain EY top-30% local **and** 12–1 momentum > 0 **and**
``financial_health`` pass, and exits at 63 trading days or identity/quality
break. Scores fair-cost episode % independently of fund NAV.

Observe-only — never writes strand A books, knobs, or ``decision-review --apply``.
Independent of sealed N200.

See ``docs/ops/n201-value-mom-observe.md`` and Project store
``alternate-strand-learning-questions.md``.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.backtest import RunSnapshot, load_run_snapshots
from value_investor.market_trading_costs import (
    LEGACY_STRESS_TRADE_COST_PCT,
    LIVE_PAPER_MARKET_ID,
    costs_for_market,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = Path("docs/data")
DEFAULT_STORE_PATH = Path("docs/data/n201_value_mom_observe.json")
DEFAULT_REGISTRATION_PATH = Path("docs/data/n201_value_mom_registration.json")
DEFAULT_OPS_STATUS_PATH = Path("docs/data/ops_status.json")
DEFAULT_OPS_DOC = Path("docs/ops/n201-value-mom-observe.md")

REGISTRATION_ID = "strand-c-short-horizon-value-mom-v0"
DEFERRED_ID = "N201"
IDENTITY_ID = "plain_ey_top30_mom_12_1_financial_health"
SUCCESS_METRIC_ID = "smooth_ret_cohort_median"
SCHEMA_VERSION = 1
PIPELINE_HEALTH_SCHEMA_VERSION = 1

DEFAULT_STALE_AFTER_HOURS = 30.0
DEFAULT_STORE_LAG_WARN_HOURS = 2.0
PIPELINE_HEALTH_DISCLAIMER = (
    "Phase floor and volume gate measure factory mechanism throughput — "
    "not alpha or capital readiness (F8). Fixed-stake episode % is "
    "independent of fund NAV. Observe-only."
)

DEFAULT_MARKET_ID = LIVE_PAPER_MARKET_ID
STRESS_TRADE_COST_PCT = LEGACY_STRESS_TRADE_COST_PCT
SEAL_MARKER_ID = "n201-seal-v0"
VOLUME_MIN_EPISODES = 48
VOLUME_MIN_WEEKS = 8
PHASE_ENTRIES_PER_WEEK_FLOOR = 8.0
HOLD_TRADING_DAYS = 63
FIXED_STAKE_UNITS = 100.0
EY_TOP_SHARE = 0.30
MAX_EPISODES = 500
# ~12 calendar months / 1 month on weekly archive for momentum proxy.
MOM_LOOKBACK_WEEKS_12 = 52
MOM_LOOKBACK_WEEKS_1 = 4

F9_BIND_FIELDS = (
    "key_filing_bodies",
    "fcf_basis_bound",
    "overlay_bound",
    "memo_recent",
)

LEARNING_QUESTION = (
    "Across live ∪ admitted markets, do observe-only selective ~3m "
    "plain-EY + momentum entries (market-native, no FX), sized as a "
    "fixed-stake mechanical test, beat a patient plain-value hold on the "
    "same eligible set after fair local costs?"
)

FINDING_TITLE = "N201 value-mom observe refreshed"
STORE_FAILED_TITLE = "N201 value-mom observe failed"
VOLUME_GATE_TITLE = "N201 volume gate ready for review"

# Soft gaps (MVP): archive history often lacks EY / mom / financial_health fields.
ELIGIBILITY_MODE = "entry_fields_required_f9_or_pass"

PATIENT_HOLD_BASELINE = {
    "id": "patient_plain_ey_hold_v0",
    "definition": (
        "Same universe and market-native returns; plain EY top-30% local; "
        "no momentum filter; same financial_health pass; same 63 trading-day "
        "or identity/quality-break exit; same fixed 100 local-currency stake; "
        "fair per-market costs. Excess vs strategy is report-only."
    ),
    "identity_id": "plain_ey_top30_financial_health",
    "momentum_filter": False,
    "financial_health_required": True,
    "hold_trading_days": HOLD_TRADING_DAYS,
    "fixed_stake_units": FIXED_STAKE_UNITS,
    "role": "report_only",
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_run_at(value: str) -> datetime:
    from value_investor.backtest import _parse_run_at

    return _parse_run_at(value)


def _days_between(start: str, end: str) -> int:
    return max(0, int((_parse_run_at(end) - _parse_run_at(start)).total_seconds() // 86400))


def _trading_days_between(start: str, end: str) -> int:
    """Weekday count between timestamps (archive proxy for trading days)."""
    a = _parse_run_at(start).date()
    b = _parse_run_at(end).date()
    if b <= a:
        return 0
    days = 0
    cur = a + timedelta(days=1)
    while cur <= b:
        if cur.weekday() < 5:
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
    """F9 per-name binds when present; else pass with note (archive MVP).

    Capital influence remains fail-closed elsewhere (F8) — this observe lane
    never promotes.
    """
    present = 0
    for field in F9_BIND_FIELDS:
        flag = _truthy_bind(row.get(field))
        if flag is None:
            continue
        present += 1
        if not flag:
            return False, f"f9_fail:{field}"
    if present == 0:
        return True, "eligibility_mode=row_fields_or_pass"
    return True, "f9_binds_ok"


def _row_market_id(row: dict[str, Any], default: str = DEFAULT_MARKET_ID) -> str:
    mid = str(row.get("market_id") or row.get("market") or "").strip()
    return mid or default


def _financial_health_pass(row: dict[str, Any]) -> bool | None:
    """True/False when known; None when archive row lacks the gate."""
    flag = row.get("financial_health_pass")
    if flag is None:
        flag = row.get("financial_health")
    if isinstance(flag, bool):
        return flag
    if isinstance(flag, (int, float)):
        return bool(flag)
    if isinstance(flag, str):
        text = flag.strip().lower()
        if text in {"pass", "passed", "true", "1", "yes"}:
            return True
        if text in {"fail", "failed", "false", "0", "no"}:
            return False
    models = row.get("models_passed")
    if isinstance(models, list):
        if "financial_health" in models:
            return True
        # List present but model absent → treat as fail only when other model
        # ids are enumerated (enriched rows). Bare history uses a float count.
        if models and all(isinstance(m, str) for m in models):
            return False
    return None


def _earnings_yield(row: dict[str, Any]) -> float | None:
    for key in ("earnings_yield", "earnings_yield_pe", "earnings_yield_ebit"):
        raw = row.get(key)
        if raw is None:
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if val == val:  # not NaN
            return val
    return None


def _momentum_12_1_from_row(row: dict[str, Any]) -> float | None:
    for key in ("momentum_12_1", "mom_12_1"):
        raw = row.get(key)
        if raw is None:
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if val == val:
            return val
    return None


def _price_at(snapshots: list[RunSnapshot], idx: int, ticker: str) -> float | None:
    price = snapshots[idx].prices.get(ticker)
    if price is None or float(price) <= 0:
        return None
    return float(price)


def _momentum_12_1_from_prices(
    snapshots: list[RunSnapshot],
    idx: int,
    ticker: str,
) -> float | None:
    """Weekly-archive proxy: close[~12m]→close[~1m] return when row field absent."""
    i_recent = idx - MOM_LOOKBACK_WEEKS_1
    i_old = idx - MOM_LOOKBACK_WEEKS_12
    if i_recent < 0 or i_old < 0:
        return None
    p_recent = _price_at(snapshots, i_recent, ticker)
    p_old = _price_at(snapshots, i_old, ticker)
    if p_recent is None or p_old is None or p_old <= 0:
        return None
    return p_recent / p_old - 1.0


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


def _plain_ey_top_share(
    rows_by_ticker: dict[str, dict[str, Any]],
    *,
    top_share: float = EY_TOP_SHARE,
) -> set[str]:
    """Local (snapshot) top ``top_share`` by positive earnings yield.

    Mirrors ``historical_screen_replay.plain_value_tickers`` (positive EY,
    cutoff at quantile ``1 - top_share``).
    """
    scored: list[tuple[str, float]] = []
    for ticker, row in rows_by_ticker.items():
        ey = _earnings_yield(row)
        if ey is None or ey <= 0:
            continue
        scored.append((ticker, ey))
    if not scored:
        return set()
    yields = sorted(ey for _, ey in scored)
    # Linear interpolation quantile at (1 - top_share), matching pandas default.
    pos = (len(yields) - 1) * (1.0 - top_share)
    lo = int(pos)
    hi = min(lo + 1, len(yields) - 1)
    frac = pos - lo
    cutoff = yields[lo] * (1.0 - frac) + yields[hi] * frac
    return {t for t, ey in scored if ey >= cutoff}


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


def _entry_filter_state(
    row: dict[str, Any],
    *,
    in_ey_top: bool,
    momentum: float | None,
    require_momentum: bool,
) -> tuple[bool, str, dict[str, Any]]:
    """Return (passes, note, detail). Missing required fields → not pass."""
    ey = _earnings_yield(row)
    fh = _financial_health_pass(row)
    detail = {
        "earnings_yield": ey,
        "in_ey_top30_local": in_ey_top,
        "momentum_12_1": momentum,
        "financial_health_pass": fh,
        "require_momentum": require_momentum,
    }
    if ey is None or fh is None:
        return False, "soft_gap_missing_entry_fields", detail
    if require_momentum and momentum is None:
        return False, "soft_gap_missing_momentum", detail
    if not in_ey_top:
        return False, "ey_not_top30", detail
    if not fh:
        return False, "financial_health_fail", detail
    if require_momentum and not (momentum is not None and momentum > 0):
        return False, "momentum_not_positive", detail
    return True, "entry_filters_clear", detail


@dataclass(frozen=True)
class N201Config:
    market_id: str = DEFAULT_MARKET_ID
    buy_cost_pct: float | None = None
    sell_cost_pct: float | None = None
    stress_trade_cost_pct: float = STRESS_TRADE_COST_PCT
    volume_min_episodes: int = VOLUME_MIN_EPISODES
    volume_min_weeks: int = VOLUME_MIN_WEEKS
    phase_entries_per_week_floor: float = PHASE_ENTRIES_PER_WEEK_FLOOR
    hold_trading_days: int = HOLD_TRADING_DAYS
    fixed_stake_units: float = FIXED_STAKE_UNITS
    ey_top_share: float = EY_TOP_SHARE
    max_episodes: int = MAX_EPISODES

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
            "per_market_tables": True,
            "fx_conversion": False,
        }


def build_registration_payload(*, sealed_at: str | None = None) -> dict[str, Any]:
    """Canonical seal record written to ``n201_value_mom_registration.json``."""
    cfg = N201Config()
    cost = cfg.primary_cost_fields()
    return {
        "schema_version": SCHEMA_VERSION,
        "registration_id": REGISTRATION_ID,
        "deferred_id": DEFERRED_ID,
        "status": "sealed_observe_only",
        "sealed_at": sealed_at or "2026-10-12",
        "observe_only": True,
        "influences_live": False,
        "independent_of_n200": True,
        "learning_question": LEARNING_QUESTION,
        "identity_id": IDENTITY_ID,
        "success_metric_id": SUCCESS_METRIC_ID,
        "o2_identity": IDENTITY_ID,
        "entry_filters": {
            "plain_ey_top_share_local": EY_TOP_SHARE,
            "momentum_12_1_gt": 0.0,
            "financial_health": "pass",
            "all_required": True,
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
            "markets": "ftse350_plus_admitted",
            "returns": "market_native",
            "fx_conversion": False,
        },
        "buy_trigger": "next_eligible_weekly_refresh_after_filters_clear",
        "exit": {
            "hold_trading_days": HOLD_TRADING_DAYS,
            "or_identity_quality_break": True,
            "whichever_first": True,
            "archive_trading_day_proxy": "weekday_count",
        },
        "patient_hold_baseline": PATIENT_HOLD_BASELINE,
        "o3_volume_gate": {
            "completed_entry_episodes_min": VOLUME_MIN_EPISODES,
            "calendar_weeks_spanned_min": VOLUME_MIN_WEEKS,
            "rule": "both_required",
        },
        "o4_smoother": SUCCESS_METRIC_ID,
        "o5_primacy": {
            "primary": "absolute_smoothed_return_fair_costs",
            "patient_hold_excess": "report_only",
            "stress_cost": "report_only",
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
        "soft_gaps": [
            (
                "Live FTSE history signal rows often lack earnings_yield / "
                "momentum_12_1 / financial_health_pass; MVP scores only rows "
                "with required entry fields (or price-proxy momentum). Zero "
                "episodes until enrichment — fail-closed for capital (F8)."
            ),
            (
                "Admitted-market weekly archive panels not fully wired into "
                "this walker; v0 primarily consumes ftse350 history plus any "
                "enriched market_id rows present on snapshots."
            ),
            (
                "Hold of 63 trading days uses weekday-count proxy on the "
                "weekly archive (no exchange holiday calendar)."
            ),
        ],
        "launch_queue": {
            "enqueued": True,
            "rank_note": (
                "Newly sealed — Data deepen / shortlist demand waits behind "
                "holdings and already-running sealed units (N200). Do not "
                "steal P1 from ranks 1–2."
            ),
            "doc": "docs/ops/data-pillar-priorities.md",
        },
        "shrink_policy": "new_twins_failure_mode_ladder_not_mid_flight_prune",
        "constraints": [
            "observe_only",
            "no_live_strand_a_writes",
            "no_decision_review_apply",
            "no_new_screen_extras",
            "f9_eligibility",
            "f8_fail_closed",
            "fixed_stake_not_fund_nav",
            "fair_costs_primary",
            "stress_cost_report_only",
            "patient_hold_excess_report_only",
            "independent_of_n200",
            "logged_change_markers",
            "no_fx_conversion",
        ],
        "ops_doc": str(DEFAULT_OPS_DOC),
        "observe_store": str(DEFAULT_STORE_PATH),
    }


def _median_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(float(statistics.median(values)), 6)


def _resolve_momentum(
    snapshots: list[RunSnapshot],
    idx: int,
    ticker: str,
    row: dict[str, Any],
) -> float | None:
    mom = _momentum_12_1_from_row(row)
    if mom is not None:
        return mom
    return _momentum_12_1_from_prices(snapshots, idx, ticker)


def _find_exit_index(
    snapshots: list[RunSnapshot],
    entry_idx: int,
    ticker: str,
    *,
    hold_trading_days: int,
    ey_top_by_snap: list[set[str]],
) -> tuple[int | None, str | None]:
    """Exit at hold horizon or identity/quality break, whichever first."""
    entry_at = snapshots[entry_idx].run_at
    for j in range(entry_idx + 1, len(snapshots)):
        row_map = _snapshot_rows(snapshots[j])
        row = row_map.get(ticker)
        reason: str | None = None
        if row is None:
            reason = "identity_break_missing_row"
        else:
            fh = _financial_health_pass(row)
            in_ey = ticker in ey_top_by_snap[j]
            if fh is False:
                reason = "quality_break_financial_health"
            elif _earnings_yield(row) is not None and not in_ey:
                reason = "identity_break_ey_band"
            # If EY/FH fields missing mid-flight, do not invent a break —
            # wait for horizon (soft-gap tolerant for open episodes).
        if reason is not None:
            return j, reason
        if _trading_days_between(entry_at, snapshots[j].run_at) >= hold_trading_days:
            return j, "hold_trading_days"
    return None, None


def build_n201_observe(
    snapshots: list[RunSnapshot],
    *,
    cfg: N201Config | None = None,
    generated_at: str | None = None,
    prior_markers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Score N201 fixed-stake episodes from archive snapshots (pure; no I/O)."""
    cfg = cfg or N201Config()
    cost_fields = cfg.primary_cost_fields()
    stress_pct = float(cfg.stress_trade_cost_pct)

    # Precompute local EY top sets per snapshot (among rows with EY present).
    row_maps = [_snapshot_rows(s) for s in snapshots]
    ey_top_by_snap = [_plain_ey_top_share(rm, top_share=cfg.ey_top_share) for rm in row_maps]

    strategy_returns: list[float] = []
    patient_returns: list[float] = []
    stress_returns: list[float] = []
    episodes: list[dict[str, Any]] = []
    skipped_missing_fields = 0
    skipped_ineligible = 0
    skipped_filters = 0

    prev_strategy: set[str] = set()
    for i, snap in enumerate(snapshots):
        row_map = row_maps[i]
        ey_top = ey_top_by_snap[i]
        strategy_clear: set[str] = set()
        for ticker, row in row_map.items():
            mom = _resolve_momentum(snapshots, i, ticker, row)
            ok, note, _detail = _entry_filter_state(
                row, in_ey_top=ticker in ey_top, momentum=mom, require_momentum=True
            )
            if note.startswith("soft_gap_missing"):
                # Count once per new candidate attempt only below.
                pass
            if ok:
                strategy_clear.add(ticker)

        for ticker in sorted(strategy_clear - prev_strategy):
            row = row_map[ticker]
            eligible, elig_note = row_f9_eligible(row)
            if not eligible:
                skipped_ineligible += 1
                continue
            mom = _resolve_momentum(snapshots, i, ticker, row)
            ok, note, detail = _entry_filter_state(
                row, in_ey_top=True, momentum=mom, require_momentum=True
            )
            if not ok:
                if note.startswith("soft_gap_missing"):
                    skipped_missing_fields += 1
                else:
                    skipped_filters += 1
                continue

            exit_idx, exit_reason = _find_exit_index(
                snapshots,
                i,
                ticker,
                hold_trading_days=cfg.hold_trading_days,
                ey_top_by_snap=ey_top_by_snap,
            )
            if exit_idx is None:
                continue  # still open

            mid = _row_market_id(row, cfg.market_id)
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
            strategy_returns.append(stake["return_pct"])
            stress_ret = episode_return(p_entry, p_exit, trade_cost_pct=stress_pct)
            stress_returns.append(stress_ret)

            # Patient-hold twin entry: same snap if EY+FH clear without mom.
            patient_ok, _, _ = _entry_filter_state(
                row, in_ey_top=ticker in ey_top, momentum=mom, require_momentum=False
            )
            patient_ret: float | None = None
            if patient_ok:
                p_exit_idx, _p_reason = _find_exit_index(
                    snapshots,
                    i,
                    ticker,
                    hold_trading_days=cfg.hold_trading_days,
                    ey_top_by_snap=ey_top_by_snap,
                )
                if p_exit_idx is not None:
                    p_p_exit = _price_at(snapshots, p_exit_idx, ticker)
                    if p_p_exit is not None:
                        patient_stake = fixed_stake_pnl(
                            p_entry,
                            p_p_exit,
                            stake_units=cfg.fixed_stake_units,
                            buy_cost_pct=buy_pct,
                            sell_cost_pct=sell_pct,
                        )
                        patient_ret = patient_stake["return_pct"]
                        patient_returns.append(patient_ret)

            episodes.append(
                {
                    "ticker": ticker,
                    "market_id": mid,
                    "entry_run_at": snap.run_at,
                    "exit_run_at": snapshots[exit_idx].run_at,
                    "hold_trading_days": _trading_days_between(
                        snap.run_at, snapshots[exit_idx].run_at
                    ),
                    "exit_reason": exit_reason,
                    "eligibility": elig_note,
                    "entry_detail": detail,
                    "fixed_stake_units": cfg.fixed_stake_units,
                    "return_pct": round(stake["return_pct"], 6),
                    "pnl_local_report_only": round(stake["pnl_local"], 6),
                    "return_pct_stress_report_only": round(stress_ret, 6),
                    "patient_hold_return_pct_report_only": (
                        None if patient_ret is None else round(patient_ret, 6)
                    ),
                    "scoreboard_unit": "fair_cost_episode_pct",
                    "independent_of_fund_nav": True,
                }
            )
            if len(episodes) >= cfg.max_episodes:
                break

        # Count soft-gap skips for names that looked cheap-ish but lacked fields
        for ticker, row in row_map.items():
            if ticker in strategy_clear or ticker in prev_strategy:
                continue
            mom = _resolve_momentum(snapshots, i, ticker, row)
            _ok, note, _ = _entry_filter_state(
                row,
                in_ey_top=ticker in ey_top,
                momentum=mom,
                require_momentum=True,
            )
            if note.startswith("soft_gap_missing") and ticker not in prev_strategy:
                # Avoid double-count explosion: only when EY present (candidate)
                if _earnings_yield(row) is not None:
                    skipped_missing_fields += 1

        prev_strategy = strategy_clear
        if len(episodes) >= cfg.max_episodes:
            break

    absolute_primary = _median_or_none(strategy_returns)
    patient_median = _median_or_none(patient_returns)
    stress_median = _median_or_none(stress_returns)
    patient_excess = None
    if absolute_primary is not None and patient_median is not None:
        patient_excess = round(absolute_primary - patient_median, 6)

    weeks = 0
    if len(snapshots) >= 2:
        weeks = max(1, _days_between(snapshots[0].run_at, snapshots[-1].run_at) // 7)
    elif snapshots:
        weeks = 1
    entries_per_week = round(len(episodes) / weeks, 3) if weeks else None
    volume_gate_met = len(episodes) >= cfg.volume_min_episodes and weeks >= cfg.volume_min_weeks
    phase_ok = entries_per_week is not None and entries_per_week >= cfg.phase_entries_per_week_floor

    seal_marker = {
        "marker_id": SEAL_MARKER_ID,
        "at": "2026-10-12T00:00:00+00:00",
        "lever": "horizon_product",
        "before_id": None,
        "after_id": REGISTRATION_ID,
        "registration_id": REGISTRATION_ID,
        "reason": (
            "Initial seal: plain EY top-30% local + 12–1 mom > 0 + "
            "financial_health pass; fixed 100 local stake; 63d or break exit; "
            "fair-cost smooth_ret_cohort_median primary; patient-hold excess "
            "report-only. Independent of N200."
        ),
        "eligible_set_ref": ELIGIBILITY_MODE,
        "success_metric_id": SUCCESS_METRIC_ID,
        "applies_to": "observe_only",
    }
    markers = list(prior_markers or [])
    if not any(m.get("marker_id") == seal_marker["marker_id"] for m in markers):
        markers.insert(0, seal_marker)

    return {
        "schema_version": SCHEMA_VERSION,
        "registration_id": REGISTRATION_ID,
        "deferred_id": DEFERRED_ID,
        "generated_at": generated_at or _utc_now(),
        "observe_only": True,
        "influences_live": False,
        "independent_of_n200": True,
        "identity_id": IDENTITY_ID,
        "success_metric_id": SUCCESS_METRIC_ID,
        "learning_question": LEARNING_QUESTION,
        "eligibility_mode": ELIGIBILITY_MODE,
        "sizing": {
            "mode": "fixed_stake",
            "stake_units": cfg.fixed_stake_units,
            "cash_fund_nav": "parked",
            "scoreboard_unit": "fair_cost_episode_pct",
            "independent_of_fund_nav": True,
        },
        "patient_hold_baseline": PATIENT_HOLD_BASELINE,
        "cost_basis": cost_fields,
        "snapshot_count": len(snapshots),
        "completed_entry_episodes": len(episodes),
        "skipped_missing_entry_fields": skipped_missing_fields,
        "skipped_ineligible": skipped_ineligible,
        "skipped_filters": skipped_filters,
        "calendar_weeks_spanned": weeks,
        "volume_gate": {
            "min_episodes": cfg.volume_min_episodes,
            "min_weeks": cfg.volume_min_weeks,
            "met": volume_gate_met,
        },
        "phase": {
            "entries_per_week": entries_per_week,
            "floor": cfg.phase_entries_per_week_floor,
            "floor_met": phase_ok,
        },
        "path_scoreboard": {
            "primary": "absolute_smoothed_return_fair_costs",
            "success_metric_id": SUCCESS_METRIC_ID,
            "smooth_ret_cohort_median": absolute_primary,
            "smooth_ret_cohort_median_stress_report_only": stress_median,
            "patient_hold_smooth_ret_cohort_median_report_only": patient_median,
            "patient_hold_excess_report_only": patient_excess,
            "n": len(strategy_returns),
            "independent_of_fund_nav": True,
            "note": (
                "Primary is fair-cost episode % cohort median on fixed-stake "
                "entries. Fund NAV / cash drag not used. Patient-hold excess "
                "and stress 3%/side are report-only (F8)."
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
        },
        "change_markers": markers,
        "episodes_sample": episodes[:25],
        "ops_doc": str(DEFAULT_OPS_DOC),
    }


def refresh_n201_value_mom_observe(
    *,
    output_dir: Path | None = None,
    store_path: Path | None = None,
    registration_path: Path | None = None,
    persist: bool = True,
    cfg: N201Config | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Load archive history, score episodes, optionally persist stores."""
    data_dir = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR
    store = Path(store_path) if store_path is not None else DEFAULT_STORE_PATH
    reg_path = (
        Path(registration_path) if registration_path is not None else DEFAULT_REGISTRATION_PATH
    )

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
    payload = build_n201_observe(
        snapshots,
        cfg=cfg,
        generated_at=generated_at,
        prior_markers=prior_markers,
    )
    registration = build_registration_payload()

    if persist:
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        reg_path.write_text(json.dumps(registration, indent=2) + "\n", encoding="utf-8")
    return payload


def ops_findings_from_n201_observe(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Map observe store → ops-monitor finding dicts (observe-only)."""
    findings: list[dict[str, Any]] = []
    n = int(payload.get("completed_entry_episodes") or 0)
    weeks = int(payload.get("calendar_weeks_spanned") or 0)
    phase = payload.get("phase") if isinstance(payload.get("phase"), dict) else {}
    path = (
        payload.get("path_scoreboard") if isinstance(payload.get("path_scoreboard"), dict) else {}
    )
    missing = int(payload.get("skipped_missing_entry_fields") or 0)
    findings.append(
        {
            "severity": "info",
            "category": "research",
            "title": FINDING_TITLE,
            "summary": (
                f"{REGISTRATION_ID}: {n} completed episodes over {weeks} weeks; "
                f"entries/week={phase.get('entries_per_week')}; "
                f"{SUCCESS_METRIC_ID}={path.get('smooth_ret_cohort_median')} "
                f"(fair costs primary; fixed-stake %; independent of fund NAV); "
                f"patient_hold_excess_report_only="
                f"{path.get('patient_hold_excess_report_only')}; "
                f"stress_3pct_report_only="
                f"{path.get('smooth_ret_cohort_median_stress_report_only')}; "
                f"skipped_missing_entry_fields={missing}. "
                "Observe-only — launch-queue waiter; no live writes (F8)."
            ),
            "auto_fixable": False,
        }
    )
    volume = payload.get("volume_gate") if isinstance(payload.get("volume_gate"), dict) else {}
    if volume.get("met"):
        findings.append(
            {
                "severity": "info",
                "category": "research",
                "title": VOLUME_GATE_TITLE,
                "summary": (
                    f"Volume gate met (episodes>={VOLUME_MIN_EPISODES} and "
                    f"weeks>={VOLUME_MIN_WEEKS}). Human may review; "
                    "no auto-promote."
                ),
                "auto_fixable": False,
            }
        )
    return findings


def format_n201_observe_text(payload: dict[str, Any]) -> str:
    path = (
        payload.get("path_scoreboard") if isinstance(payload.get("path_scoreboard"), dict) else {}
    )
    phase = payload.get("phase") if isinstance(payload.get("phase"), dict) else {}
    volume = payload.get("volume_gate") if isinstance(payload.get("volume_gate"), dict) else {}
    cost = payload.get("cost_basis") if isinstance(payload.get("cost_basis"), dict) else {}
    lines = [
        f"N201 {payload.get('registration_id')} (observe-only)",
        f"  episodes={payload.get('completed_entry_episodes')} "
        f"weeks={payload.get('calendar_weeks_spanned')} "
        f"entries/week={phase.get('entries_per_week')}",
        f"  {SUCCESS_METRIC_ID}={path.get('smooth_ret_cohort_median')} "
        f"(fair {cost.get('market_id')} RT={cost.get('round_trip_pct')}; "
        f"fixed-stake %; independent of fund NAV)",
        f"  patient_hold_excess_report_only={path.get('patient_hold_excess_report_only')}",
        f"  stress_3pct_report_only={path.get('smooth_ret_cohort_median_stress_report_only')}",
        f"  volume_gate_met={volume.get('met')} phase_floor_met={phase.get('floor_met')}",
        f"  skipped_missing_entry_fields={payload.get('skipped_missing_entry_fields')}",
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
        detail = "N201 observe store not published yet."
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


def _ops_n201_check_status(ops_status: dict[str, Any] | None) -> dict[str, Any]:
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
        "detail": "No N201 ops finding in latest ops_status.",
    }


def build_n201_pipeline_health_projection(
    payload: dict[str, Any] | None = None,
    *,
    store_path: Path | None = None,
    ops_status_path: Path | None = None,
    ops_status: dict[str, Any] | None = None,
    now: datetime | None = None,
    stale_after_hours: float = DEFAULT_STALE_AFTER_HOURS,
    store_lag_warn_hours: float = DEFAULT_STORE_LAG_WARN_HOURS,
) -> dict[str, Any]:
    """Slim dashboard projection: phase, volume, freshness (mechanism only)."""
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
    ops_check = _ops_n201_check_status(ops_status)

    phase_raw = (payload or {}).get("phase") if present else None
    phase = phase_raw if isinstance(phase_raw, dict) else {}
    volume_raw = (payload or {}).get("volume_gate") if present else None
    volume = volume_raw if isinstance(volume_raw, dict) else {}
    episodes = int((payload or {}).get("completed_entry_episodes") or 0) if present else 0
    weeks = int((payload or {}).get("calendar_weeks_spanned") or 0) if present else 0
    path = (
        (payload or {}).get("path_scoreboard")
        if present and isinstance((payload or {}).get("path_scoreboard"), dict)
        else {}
    )

    entries_pw = phase.get("entries_per_week")
    floor = phase.get("floor", PHASE_ENTRIES_PER_WEEK_FLOOR)
    floor_met = bool(phase.get("floor_met")) if present and "floor_met" in phase else False
    volume_met = bool(volume.get("met")) if present and "met" in volume else False
    freshness_ok = freshness["state"] in {"fresh", "lagging"}
    ops_ok = bool(ops_check["ops_check_ok"]) or (freshness["state"] == "fresh" and present)
    functioning = bool(present and freshness_ok and ops_ok)

    if not present:
        headline = "N201 observe store missing — pipeline not yet published."
    elif not functioning:
        headline = (
            f"N201 pipeline attention — freshness={freshness['state']}; "
            f"phase floor {'met' if floor_met else 'not met'}; "
            f"volume gate {'met' if volume_met else 'not met'}."
        )
    else:
        headline = (
            f"N201 pipeline functioning — phase {entries_pw}/{floor} "
            f"entries/week; volume {'met' if volume_met else 'not met'} "
            f"({episodes} ep / {weeks} wk); "
            f"{SUCCESS_METRIC_ID}={path.get('smooth_ret_cohort_median')}."
        )

    return {
        "schema_version": PIPELINE_HEALTH_SCHEMA_VERSION,
        "generated_at": clock.isoformat(),
        "observe_only": True,
        "influences_live": False,
        "not_alpha_signal": True,
        "not_capital_ready": True,
        "independent_of_fund_nav": True,
        "launch_queue_waiter": True,
        "registration_id": (payload or {}).get("registration_id") or REGISTRATION_ID,
        "deferred_id": (payload or {}).get("deferred_id") or DEFERRED_ID,
        "headline": headline,
        "disclaimer": PIPELINE_HEALTH_DISCLAIMER,
        "store_present": present,
        "store_generated_at": store_as_of.isoformat() if store_as_of else None,
        "phase": {
            "entries_per_week": entries_pw,
            "floor": floor,
            "floor_met": floor_met,
        },
        "volume_gate": {
            "met": volume_met,
            "episodes": episodes,
            "weeks": weeks,
            "min_episodes": volume.get("min_episodes", VOLUME_MIN_EPISODES),
            "min_weeks": volume.get("min_weeks", VOLUME_MIN_WEEKS),
        },
        "path_scoreboard": {
            "smooth_ret_cohort_median": path.get("smooth_ret_cohort_median"),
            "patient_hold_excess_report_only": path.get("patient_hold_excess_report_only"),
            "independent_of_fund_nav": True,
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
