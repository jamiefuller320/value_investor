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
import logging
import statistics
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from value_investor.backtest import RunSnapshot, load_run_snapshots
from value_investor.data_library import DEFAULT_LIBRARY_ROOT
from value_investor.market_trading_costs import (
    LEGACY_STRESS_TRADE_COST_PCT,
    LIVE_PAPER_MARKET_ID,
    costs_for_market,
)

logger = logging.getLogger(__name__)

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
DEFAULT_LIBRARY_POLICY_PATH = Path("docs/data/library/policy.json")
STRESS_TRADE_COST_PCT = LEGACY_STRESS_TRADE_COST_PCT
SEAL_MARKER_ID = "n201-seal-v0"
VOLUME_MIN_EPISODES = 48
VOLUME_MIN_WEEKS = 8
PHASE_ENTRIES_PER_WEEK_FLOOR = 8.0
HOLD_TRADING_DAYS = 63
FIXED_STAKE_UNITS = 100.0
EY_TOP_SHARE = 0.30
MAX_EPISODES = 500
# Classic 12–1: return from ~12 calendar months ago to ~1 month ago.
MOM_LOOKBACK_MONTHS_12 = 12
MOM_LOOKBACK_MONTHS_1 = 1
MOM_BAR_TOLERANCE_DAYS = 10
MOM_PRICE_FETCH_PERIOD = "2y"
# Cap external price fetches per refresh (observe-only; fail-closed beyond).
DEFAULT_MAX_MOMENTUM_PRICE_FETCHES = 400
ARCHIVE_ENRICH_MAX_DAY_DELTA = 3

# Display names / ids used on dashboard archives and library model dumps.
_FH_MODEL_IDS = frozenset({"financial_health"})
_FH_MODEL_NAMES = frozenset({"financial health"})

# Minimal exchange holidays (ISO dates) when no session calendar is available.
# Kept small on purpose — prefer session calendars derived from price bars.
_MARKET_HOLIDAYS: dict[str, frozenset[str]] = {
    "ftse350": frozenset(
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
    ),
    "ftse_smallcap": frozenset(),  # filled below from ftse350
    "aim": frozenset(),
    "sp500": frozenset(
        {
            "2025-01-01",
            "2025-01-20",
            "2025-02-17",
            "2025-04-18",
            "2025-05-26",
            "2025-06-19",
            "2025-07-04",
            "2025-09-01",
            "2025-11-27",
            "2025-12-25",
            "2026-01-01",
            "2026-01-19",
            "2026-02-16",
            "2026-04-03",
            "2026-05-25",
            "2026-06-19",
            "2026-07-03",
            "2026-09-07",
            "2026-11-26",
            "2026-12-25",
        }
    ),
}
_MARKET_HOLIDAYS["ftse_smallcap"] = _MARKET_HOLIDAYS["ftse350"]
_MARKET_HOLIDAYS["aim"] = _MARKET_HOLIDAYS["ftse350"]
_MARKET_HOLIDAYS["nasdaq100"] = _MARKET_HOLIDAYS["sp500"]
_MARKET_HOLIDAYS["us_adr_asia"] = _MARKET_HOLIDAYS["sp500"]

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


def _holidays_for_market(market_id: str) -> list[str]:
    mid = str(market_id or DEFAULT_MARKET_ID).strip() or DEFAULT_MARKET_ID
    holidays = _MARKET_HOLIDAYS.get(mid)
    if holidays is None:
        # Unknown market: UK table is a conservative default for weekday busday.
        holidays = _MARKET_HOLIDAYS.get(DEFAULT_MARKET_ID, frozenset())
    return sorted(holidays)


def trading_days_between(
    start: str,
    end: str,
    *,
    market_id: str = DEFAULT_MARKET_ID,
    sessions: set[date] | frozenset[date] | None = None,
) -> int:
    """Count trading days in ``(start, end]``.

    Prefer an explicit session calendar (from price bars) when provided; else
    numpy busday with a small per-market holiday table; weekdays-only is the
    last-resort fallback when holiday data is empty.
    """
    a = _parse_run_at(start).date()
    b = _parse_run_at(end).date()
    if b <= a:
        return 0
    if sessions:
        return sum(1 for d in sessions if a < d <= b)
    holidays = _holidays_for_market(market_id)
    try:
        return int(np.busday_count(a, b, holidays=holidays))
    except Exception:  # noqa: BLE001 — never break observe on calendar quirks
        days = 0
        cur = a + timedelta(days=1)
        while cur <= b:
            if cur.weekday() < 5 and cur.isoformat() not in holidays:
                days += 1
            cur += timedelta(days=1)
        return days


def _trading_days_between(start: str, end: str) -> int:
    """Backward-compatible default (FTSE holiday table)."""
    return trading_days_between(start, end, market_id=DEFAULT_MARKET_ID)


def sessions_from_price_frames(
    frames: dict[str, pd.DataFrame],
) -> set[date]:
    """Union of session dates present on fetched/panel price frames."""
    out: set[date] = set()
    for frame in frames.values():
        if frame is None or getattr(frame, "empty", True):
            continue
        idx = pd.to_datetime(frame.index)
        for ts in idx:
            try:
                out.add(pd.Timestamp(ts).date())
            except (TypeError, ValueError):
                continue
    return out


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


def _model_token_match(value: Any, *, ids: frozenset[str], names: frozenset[str]) -> bool:
    text = str(value or "").strip().lower().replace("-", " ").replace("_", " ")
    text = " ".join(text.split())
    if not text:
        return False
    if text in ids or text in names:
        return True
    # Dashboard archives use display names like "Financial Health".
    compact = text.replace(" ", "")
    return compact in {x.replace(" ", "") for x in names} or compact in ids


def _financial_health_pass(row: dict[str, Any]) -> bool | None:
    """True/False when known; None when archive row lacks the gate."""
    flag = row.get("financial_health_pass")
    if flag is None:
        flag = row.get("financial_health")
    if isinstance(flag, bool):
        return flag
    if isinstance(flag, (int, float)) and flag == flag:
        return bool(flag)
    if isinstance(flag, str):
        text = flag.strip().lower()
        if text in {"pass", "passed", "true", "1", "yes"}:
            return True
        if text in {"fail", "failed", "false", "0", "no"}:
            return False

    # Explicit model pass/fail lists (dashboard archives / library dumps).
    passed_models = row.get("passed_models")
    failed_models = row.get("failed_models")
    if isinstance(passed_models, list) and any(
        _model_token_match(m, ids=_FH_MODEL_IDS, names=_FH_MODEL_NAMES) for m in passed_models
    ):
        return True
    if isinstance(failed_models, list) and any(
        _model_token_match(m, ids=_FH_MODEL_IDS, names=_FH_MODEL_NAMES) for m in failed_models
    ):
        return False
    # Both lists present and enumerated → FH was evaluated and did not pass.
    if (
        isinstance(passed_models, list)
        and isinstance(failed_models, list)
        and (passed_models or failed_models)
        and all(isinstance(m, str) for m in (*passed_models, *failed_models))
    ):
        return False

    model_passes = row.get("model_passes")
    if isinstance(model_passes, dict) and "financial_health" in model_passes:
        return bool(model_passes.get("financial_health"))

    models = row.get("models_passed")
    if isinstance(models, list):
        if any(_model_token_match(m, ids=_FH_MODEL_IDS, names=_FH_MODEL_NAMES) for m in models):
            return True
        # List present but model absent → treat as fail only when other model
        # ids/names are enumerated (enriched rows). Bare history uses a float count.
        if models and all(isinstance(m, str) for m in models):
            return False
    return None


def _coerce_positive_float(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip().replace(",", "").replace("%", "")
        if not text or text.lower() in {"n/a", "na", "none", "null", "-"}:
            return None
        raw = text
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    if val != val:  # NaN
        return None
    return val


def _earnings_yield(row: dict[str, Any]) -> float | None:
    """EY from explicit fields, else 1/P/E from screen metrics already on the row."""
    for key in ("earnings_yield", "earnings_yield_pe", "earnings_yield_ebit"):
        val = _coerce_positive_float(row.get(key))
        if val is not None:
            return val

    for key in ("trailing_pe", "pe", "forward_pe"):
        pe = _coerce_positive_float(row.get(key))
        if pe is not None and pe > 0:
            return 1.0 / pe

    for nest_key in ("key_metrics", "screening_inputs", "metrics"):
        nest = row.get(nest_key)
        if not isinstance(nest, dict):
            continue
        for key in ("earnings_yield", "earnings_yield_pe", "earnings_yield_ebit"):
            val = _coerce_positive_float(nest.get(key))
            if val is not None:
                return val
        for key in ("P/E", "p/e", "trailing_pe", "pe", "PE"):
            pe = _coerce_positive_float(nest.get(key))
            if pe is not None and pe > 0:
                return 1.0 / pe
    return None


def _momentum_12_1_from_row(row: dict[str, Any]) -> float | None:
    for key in ("momentum_12_1", "mom_12_1"):
        raw = row.get(key)
        if raw is None:
            continue
        try:
            num = float(raw)
        except (TypeError, ValueError):
            continue
        if num == num:  # not NaN (negative mom is valid)
            return num
    return None


def _price_at(snapshots: list[RunSnapshot], idx: int, ticker: str) -> float | None:
    price = snapshots[idx].prices.get(ticker)
    if price is None or float(price) <= 0:
        return None
    return float(price)


def _close_near(
    frame: pd.DataFrame,
    target: datetime | pd.Timestamp,
    *,
    tol_days: int = MOM_BAR_TOLERANCE_DAYS,
) -> float | None:
    """Nearest Close to ``target`` within ``tol_days`` (prefer on/before)."""
    if frame is None or frame.empty:
        return None
    idx = pd.to_datetime(frame.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert(None)
    work = frame.copy()
    work.index = idx
    target_ts = pd.Timestamp(target)
    if target_ts.tzinfo is not None:
        target_ts = target_ts.tz_localize(None)

    before = work.loc[work.index <= target_ts]
    if not before.empty:
        last = before.index[-1]
        if (target_ts - last).days <= tol_days:
            close = before.iloc[-1].get("Close", before.iloc[-1].iloc[0])
            val = _coerce_positive_float(close)
            return val if val is not None and val > 0 else None

    deltas = abs(work.index - target_ts)
    nearest = work.index[int(deltas.argmin())]
    if abs((nearest - target_ts).days) <= tol_days:
        close = work.loc[nearest].get("Close", work.loc[nearest].iloc[0])
        val = _coerce_positive_float(close)
        return val if val is not None and val > 0 else None
    return None


def _momentum_12_1_from_frame(
    frame: pd.DataFrame,
    as_of: str | datetime,
) -> float | None:
    """Classic 12–1 from a daily price frame; None when bars missing (fail-closed)."""
    as_of_ts = pd.Timestamp(_parse_run_at(as_of) if isinstance(as_of, str) else as_of)
    p_recent = _close_near(frame, as_of_ts - pd.DateOffset(months=MOM_LOOKBACK_MONTHS_1))
    p_old = _close_near(frame, as_of_ts - pd.DateOffset(months=MOM_LOOKBACK_MONTHS_12))
    if p_recent is None or p_old is None or p_old <= 0:
        return None
    return p_recent / p_old - 1.0


def _momentum_12_1_from_prices(
    snapshots: list[RunSnapshot],
    idx: int,
    ticker: str,
) -> float | None:
    """Calendar 12–1 from snapshot price marks when a year of marks exists."""
    if idx < 0 or idx >= len(snapshots):
        return None
    as_of = _parse_run_at(snapshots[idx].run_at)
    target_recent = as_of - pd.DateOffset(months=MOM_LOOKBACK_MONTHS_1)
    target_old = as_of - pd.DateOffset(months=MOM_LOOKBACK_MONTHS_12)

    def _nearest_price(target: pd.Timestamp) -> float | None:
        best: tuple[int, float] | None = None
        tgt_date = pd.Timestamp(target).date()
        for snap in snapshots:
            price = snap.prices.get(ticker)
            if price is None or float(price) <= 0:
                continue
            day_delta = abs((_parse_run_at(snap.run_at).date() - tgt_date).days)
            if day_delta > MOM_BAR_TOLERANCE_DAYS:
                continue
            if best is None or day_delta < best[0]:
                best = (day_delta, float(price))
        return None if best is None else best[1]

    p_recent = _nearest_price(target_recent)
    p_old = _nearest_price(target_old)
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
    fetch_momentum_prices: bool = True
    max_momentum_price_fetches: int = DEFAULT_MAX_MOMENTUM_PRICE_FETCHES
    price_frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    trading_sessions: frozenset[date] | None = None

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
            "archive_trading_day_proxy": "session_calendar_or_busday_holidays",
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
                "Entry fields: observe refresh enriches EY from key_metrics P/E "
                "/ trailing_pe / earnings_yield_* and financial_health from "
                "passed_models/failed_models (archive + library panels). "
                "12–1 mom uses calendar lookback on snapshot prices, then "
                "optional daily price fetch (cap per refresh). Still "
                "fail-closed when fields/bars remain missing (F8)."
            ),
            (
                "Admitted-market weekly panels: walker loads library "
                "signals_*.csv + models_*.json.gz for "
                "ladder.admitted_learning_markets when present; residual "
                "markets without screen panels are listed on the observe "
                "store (panel_coverage)."
            ),
            (
                "Hold of 63 trading days uses session dates from fetched/"
                "panel price bars when available, else numpy busday with a "
                "small per-market holiday table (weekday fallback only if "
                "that fails)."
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
    *,
    price_frames: dict[str, pd.DataFrame] | None = None,
) -> float | None:
    mom = _momentum_12_1_from_row(row)
    if mom is not None:
        return mom
    frames = price_frames or {}
    frame = frames.get(ticker)
    if frame is not None:
        mom = _momentum_12_1_from_frame(frame, snapshots[idx].run_at)
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
    market_id: str = DEFAULT_MARKET_ID,
    sessions: set[date] | frozenset[date] | None = None,
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
        held = trading_days_between(
            entry_at,
            snapshots[j].run_at,
            market_id=market_id,
            sessions=sessions,
        )
        if held >= hold_trading_days:
            return j, "hold_trading_days"
    return None, None


def _ensure_momentum_price_frames(
    snapshots: list[RunSnapshot],
    *,
    cfg: N201Config,
    market_id: str,
) -> dict[str, pd.DataFrame]:
    """Fetch daily bars for EY-top ∩ FH candidates still missing 12–1 mom.

    Mutates ``cfg.price_frames`` in place when present so a shared cache can
    span FTSE + admitted markets within one refresh.
    """
    frames = cfg.price_frames
    if frames is None:
        frames = {}
    if not cfg.fetch_momentum_prices:
        return frames

    wanted: list[str] = []
    for i, snap in enumerate(snapshots):
        row_map = _snapshot_rows(snap)
        ey_top = _plain_ey_top_share(row_map, top_share=cfg.ey_top_share)
        for ticker in ey_top:
            row = row_map[ticker]
            if _financial_health_pass(row) is not True:
                continue
            if _momentum_12_1_from_row(row) is not None:
                continue
            if (
                ticker in frames
                and _momentum_12_1_from_frame(frames[ticker], snap.run_at) is not None
            ):
                continue
            if _momentum_12_1_from_prices(snapshots, i, ticker) is not None:
                continue
            if ticker not in wanted:
                wanted.append(ticker)

    already = len(frames)
    remaining = max(0, int(cfg.max_momentum_price_fetches) - already)
    # Only fetch tickers not already cached.
    to_fetch = [t for t in wanted if t not in frames][:remaining]
    if not to_fetch:
        return frames
    try:
        from value_investor.technical_analysis import fetch_price_history

        fetched = fetch_price_history(to_fetch, period=MOM_PRICE_FETCH_PERIOD, market=market_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("N201 momentum price fetch failed for %s: %s", market_id, exc)
        return frames
    frames.update(fetched)
    return frames


def build_n201_observe(
    snapshots: list[RunSnapshot],
    *,
    cfg: N201Config | None = None,
    generated_at: str | None = None,
    prior_markers: list[dict[str, Any]] | None = None,
    panel_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score N201 fixed-stake episodes from archive snapshots.

    May fetch daily prices for 12–1 when ``cfg.fetch_momentum_prices`` is set
    (observe-only enrichment; still fail-closed when bars are missing).
    """
    cfg = cfg or N201Config()
    cost_fields = cfg.primary_cost_fields()
    stress_pct = float(cfg.stress_trade_cost_pct)
    price_frames = _ensure_momentum_price_frames(snapshots, cfg=cfg, market_id=cfg.market_id)
    sessions: set[date] | frozenset[date] | None = cfg.trading_sessions
    if sessions is None and price_frames:
        sessions = frozenset(sessions_from_price_frames(price_frames))

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
            mom = _resolve_momentum(snapshots, i, ticker, row, price_frames=price_frames)
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
            mom = _resolve_momentum(snapshots, i, ticker, row, price_frames=price_frames)
            ok, note, detail = _entry_filter_state(
                row, in_ey_top=True, momentum=mom, require_momentum=True
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
                ey_top_by_snap=ey_top_by_snap,
                market_id=mid,
                sessions=sessions,
            )
            if exit_idx is None:
                continue  # still open

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
                    market_id=mid,
                    sessions=sessions,
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
                    "hold_trading_days": trading_days_between(
                        snap.run_at,
                        snapshots[exit_idx].run_at,
                        market_id=mid,
                        sessions=sessions,
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
            mom = _resolve_momentum(snapshots, i, ticker, row, price_frames=price_frames)
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

    hold_mode = "session_calendar" if sessions else "busday_with_market_holidays"
    out: dict[str, Any] = {
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
        "hold_trading_day_mode": hold_mode,
        "momentum_price_frames_used": len(price_frames),
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
    if panel_coverage is not None:
        out["panel_coverage"] = panel_coverage
    return out


def _archive_enrichment_by_day(archive_dir: Path) -> dict[str, dict[str, dict[str, Any]]]:
    """date ISO → ticker → {earnings_yield, financial_health_pass, ...} from reports."""
    from value_investor.archive_history import list_dashboard_archives

    out: dict[str, dict[str, dict[str, Any]]] = {}
    if not Path(archive_dir).is_dir():
        return out
    for run_at, path in list_dashboard_archives(Path(archive_dir)):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        reports = payload.get("reports") if isinstance(payload, dict) else None
        if not isinstance(reports, list):
            continue
        day = run_at.date().isoformat()
        by_ticker: dict[str, dict[str, Any]] = {}
        for row in reports:
            if not isinstance(row, dict):
                continue
            ticker = str(row.get("ticker") or "").strip()
            if not ticker:
                continue
            slim: dict[str, Any] = {}
            for key in (
                "passed_models",
                "failed_models",
                "key_metrics",
                "screening_inputs",
                "trailing_pe",
                "earnings_yield",
                "earnings_yield_pe",
                "earnings_yield_ebit",
                "financial_health_pass",
                "market_id",
            ):
                if key in row:
                    slim[key] = row[key]
            # Derive EY from key_metrics P/E when explicit EY absent.
            if slim.get("earnings_yield") is None and isinstance(slim.get("key_metrics"), dict):
                pe = _coerce_positive_float(slim["key_metrics"].get("P/E"))
                if pe is not None and pe > 0:
                    slim["earnings_yield"] = 1.0 / pe
            if slim.get("financial_health_pass") is None:
                fh = _financial_health_pass(slim)
                if fh is not None:
                    slim["financial_health_pass"] = fh
            if slim:
                by_ticker[ticker] = slim
        if by_ticker:
            out[day] = by_ticker
    return out


def _nearest_archive_day(
    day: str, archive_days: list[str], *, max_delta: int = ARCHIVE_ENRICH_MAX_DAY_DELTA
) -> str | None:
    if day in archive_days:
        return day
    if not archive_days:
        return None
    target = date.fromisoformat(day)
    best = min(archive_days, key=lambda d: abs((date.fromisoformat(d) - target).days))
    if abs((date.fromisoformat(best) - target).days) <= max_delta:
        return best
    return None


def enrich_snapshots_from_archives(
    snapshots: list[RunSnapshot],
    archive_dir: Path,
) -> list[RunSnapshot]:
    """In-memory merge of dashboard archive entry fields onto history rows."""
    by_day = _archive_enrichment_by_day(archive_dir)
    if not by_day:
        return snapshots
    days = sorted(by_day)
    enriched: list[RunSnapshot] = []
    for snap in snapshots:
        day = _parse_run_at(snap.run_at).date().isoformat()
        src_day = _nearest_archive_day(day, days)
        amap = by_day.get(src_day or "", {})
        if not amap:
            enriched.append(snap)
            continue
        new_signals: list[dict[str, Any]] = []
        for row in snap.signals:
            merged = dict(row)
            extra = amap.get(str(merged.get("ticker") or "").strip()) or {}
            for key, value in extra.items():
                if merged.get(key) is None:
                    merged[key] = value
            if merged.get("market_id") is None:
                merged["market_id"] = DEFAULT_MARKET_ID
            new_signals.append(merged)
        enriched.append(RunSnapshot(run_at=snap.run_at, prices=snap.prices, signals=new_signals))
    return enriched


def _fh_pass_from_models_rows(models: list[dict[str, Any]]) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for row in models:
        if not isinstance(row, dict):
            continue
        if str(row.get("model_id") or "") != "financial_health":
            continue
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue
        out[ticker] = bool(row.get("passed"))
    return out


def load_library_market_snapshots(
    library_root: Path,
    market_id: str,
    *,
    max_panels: int | None = None,
) -> list[RunSnapshot]:
    """Build RunSnapshots from library ``signals_*.csv`` + ``models_*.json.gz``.

    Uses existing screen outputs only (F4 — no new screen extras).
    """
    from value_investor.library_screen import screen_dir_for
    from value_investor.storage import read_json

    screen_dir = screen_dir_for(Path(library_root), market_id)
    if not screen_dir.is_dir():
        return []

    import re

    stamp_re = re.compile(r"signals_(\d{8}_\d{6})\.csv$")
    panels: list[tuple[datetime, Path]] = []
    for path in sorted(screen_dir.glob("signals_*.csv")):
        match = stamp_re.match(path.name)
        if not match:
            continue
        stamp = match.group(1)
        try:
            run_at = datetime.strptime(stamp, "%Y%m%d_%H%M%S").replace(tzinfo=UTC)
        except ValueError:
            continue
        panels.append((run_at, path))
    if max_panels is not None and max_panels > 0:
        panels = panels[-max_panels:]

    history_dir = screen_dir / "history"
    snapshots: list[RunSnapshot] = []
    for run_at, signals_path in panels:
        try:
            frame = pd.read_csv(signals_path)
        except (OSError, ValueError, pd.errors.ParserError):
            continue
        if frame.empty or "ticker" not in frame.columns:
            continue
        stamp = run_at.strftime("%Y%m%d_%H%M%S")
        models_path = history_dir / f"models_{stamp}.json.gz"
        if not models_path.is_file():
            models_path = screen_dir / f"models_{stamp}.json.gz"
        fh_map: dict[str, bool] = {}
        if models_path.is_file():
            try:
                models_payload = read_json(models_path)
                models = models_payload.get("models") if isinstance(models_payload, dict) else None
                if isinstance(models, list):
                    fh_map = _fh_pass_from_models_rows(models)
            except (OSError, ValueError, TypeError, KeyError):
                fh_map = {}

        # Prefer prices from matching run snapshot when present.
        prices: dict[str, float] = {}
        run_path = history_dir / f"run_{stamp}.json.gz"
        if run_path.is_file():
            try:
                run_payload = read_json(run_path)
                raw_prices = run_payload.get("prices") if isinstance(run_payload, dict) else None
                if isinstance(raw_prices, dict):
                    for ticker, price in raw_prices.items():
                        val = _coerce_positive_float(price)
                        if val is not None and val > 0:
                            prices[str(ticker)] = val
            except (OSError, ValueError, TypeError, KeyError):
                prices = {}

        signals: list[dict[str, Any]] = []
        for _, row in frame.iterrows():
            ticker = str(row.get("ticker") or "").strip()
            if not ticker:
                continue
            sig: dict[str, Any] = {
                "ticker": ticker,
                "signal": str(row.get("signal") or "hold"),
                "market_id": market_id,
            }
            for col in (
                "earnings_yield",
                "earnings_yield_pe",
                "earnings_yield_ebit",
                "trailing_pe",
                "conviction_score",
                "data_quality_score",
                "timing_signal",
                "adjusted_signal",
                "research_verdict",
            ):
                if col in frame.columns and pd.notna(row.get(col)):
                    sig[col] = row.get(col)
            if ticker in fh_map:
                sig["financial_health_pass"] = fh_map[ticker]
            last_price = (
                _coerce_positive_float(row.get("last_price"))
                if "last_price" in frame.columns
                else None
            )
            if last_price is not None and last_price > 0:
                prices.setdefault(ticker, last_price)
            if ticker not in prices:
                continue
            signals.append(sig)
        if not signals:
            continue
        snapshots.append(RunSnapshot(run_at=run_at.isoformat(), prices=prices, signals=signals))
    return snapshots


def _admitted_markets(policy_path: Path | None = None) -> list[str]:
    path = Path(policy_path) if policy_path is not None else DEFAULT_LIBRARY_POLICY_PATH
    if not path.is_file():
        return []
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    if not isinstance(policy, dict):
        return []
    from value_investor.market_shard_admission import admitted_learning_markets_for_policy

    return list(admitted_learning_markets_for_policy(policy))


def _merge_observe_payloads(
    payloads: list[dict[str, Any]],
    *,
    generated_at: str | None,
    prior_markers: list[dict[str, Any]],
    panel_coverage: dict[str, Any],
    cfg: N201Config,
) -> dict[str, Any]:
    if not payloads:
        return build_n201_observe(
            [],
            cfg=cfg,
            generated_at=generated_at,
            prior_markers=prior_markers,
            panel_coverage=panel_coverage,
        )
    if len(payloads) == 1:
        out = dict(payloads[0])
        out["panel_coverage"] = panel_coverage
        return out

    episodes: list[dict[str, Any]] = []
    strategy_returns: list[float] = []
    patient_returns: list[float] = []
    stress_returns: list[float] = []
    skipped_missing = 0
    skipped_ineligible = 0
    skipped_filters = 0
    snapshot_count = 0
    markers = list(prior_markers)
    for payload in payloads:
        snapshot_count += int(payload.get("snapshot_count") or 0)
        skipped_missing += int(payload.get("skipped_missing_entry_fields") or 0)
        skipped_ineligible += int(payload.get("skipped_ineligible") or 0)
        skipped_filters += int(payload.get("skipped_filters") or 0)
        for ep in payload.get("episodes_sample") or []:
            if isinstance(ep, dict):
                episodes.append(ep)
                if ep.get("return_pct") is not None:
                    strategy_returns.append(float(ep["return_pct"]))
                if ep.get("patient_hold_return_pct_report_only") is not None:
                    patient_returns.append(float(ep["patient_hold_return_pct_report_only"]))
                if ep.get("return_pct_stress_report_only") is not None:
                    stress_returns.append(float(ep["return_pct_stress_report_only"]))
        for marker in payload.get("change_markers") or []:
            if isinstance(marker, dict) and marker.get("marker_id") not in {
                m.get("marker_id") for m in markers
            }:
                markers.append(marker)

    # Prefer full episode counts from each market payload (not just samples).
    completed = sum(int(p.get("completed_entry_episodes") or 0) for p in payloads)
    # Recompute medians from samples when full return vectors unavailable.
    # Prefer path_scoreboard n when present by gathering listed sample returns only
    # for display; primary uses sample pool when markets exceed sample cap.
    # Better: each market payload path_scoreboard has the true median for that
    # market's full episode set — combine via weighted-by-n median of returns from
    # episodes_sample is incomplete. Re-score path from per-market scoreboards'
    # stored medians only when n matches sample; otherwise keep concatenated samples
    # and set n=completed with median over samples as approximation.
    # Collect returns from each payload's episodes_sample PLUS synthesize from
    # completed counts by re-running is too heavy — instead have build store all
    # returns? For v0 merge, recompute by concatenating each market's sample and
    # also reading path_scoreboard when completed == sample length.
    all_strategy: list[float] = []
    all_patient: list[float] = []
    all_stress: list[float] = []
    for payload in payloads:
        n = int(payload.get("completed_entry_episodes") or 0)
        sample = [e for e in (payload.get("episodes_sample") or []) if isinstance(e, dict)]
        if n <= len(sample):
            for ep in sample[:n]:
                if ep.get("return_pct") is not None:
                    all_strategy.append(float(ep["return_pct"]))
                if ep.get("patient_hold_return_pct_report_only") is not None:
                    all_patient.append(float(ep["patient_hold_return_pct_report_only"]))
                if ep.get("return_pct_stress_report_only") is not None:
                    all_stress.append(float(ep["return_pct_stress_report_only"]))
        else:
            # Incomplete sample — fall back to that market's published median once.
            path = (
                payload.get("path_scoreboard")
                if isinstance(payload.get("path_scoreboard"), dict)
                else {}
            )
            med = path.get("smooth_ret_cohort_median")
            if med is not None and n > 0:
                all_strategy.extend([float(med)] * n)
            pmed = path.get("patient_hold_smooth_ret_cohort_median_report_only")
            if pmed is not None:
                all_patient.append(float(pmed))
            smed = path.get("smooth_ret_cohort_median_stress_report_only")
            if smed is not None:
                all_stress.append(float(smed))

    absolute_primary = _median_or_none(all_strategy)
    patient_median = _median_or_none(all_patient)
    stress_median = _median_or_none(all_stress)
    patient_excess = None
    if absolute_primary is not None and patient_median is not None:
        patient_excess = round(absolute_primary - patient_median, 6)

    weeks = max(int(p.get("calendar_weeks_spanned") or 0) for p in payloads)
    entries_per_week = round(completed / weeks, 3) if weeks else None
    volume_gate_met = completed >= cfg.volume_min_episodes and weeks >= cfg.volume_min_weeks
    phase_ok = entries_per_week is not None and entries_per_week >= cfg.phase_entries_per_week_floor
    base = payloads[0]
    return {
        **base,
        "generated_at": generated_at or _utc_now(),
        "snapshot_count": snapshot_count,
        "completed_entry_episodes": completed,
        "skipped_missing_entry_fields": skipped_missing,
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
            **(
                base.get("path_scoreboard") if isinstance(base.get("path_scoreboard"), dict) else {}
            ),
            "smooth_ret_cohort_median": absolute_primary,
            "smooth_ret_cohort_median_stress_report_only": stress_median,
            "patient_hold_smooth_ret_cohort_median_report_only": patient_median,
            "patient_hold_excess_report_only": patient_excess,
            "n": completed,
            "independent_of_fund_nav": True,
        },
        "stress_scoreboard_report_only": {
            "trade_cost_pct_per_side": cfg.stress_trade_cost_pct,
            "smooth_ret_cohort_median": stress_median,
            "n": len(all_stress),
            "role": "report_only",
        },
        "change_markers": markers,
        "episodes_sample": episodes[:25],
        "panel_coverage": panel_coverage,
        "markets_scored": [
            str(p.get("cost_basis", {}).get("market_id") or p.get("market_id") or "")
            for p in payloads
        ],
    }


def refresh_n201_value_mom_observe(
    *,
    output_dir: Path | None = None,
    store_path: Path | None = None,
    registration_path: Path | None = None,
    persist: bool = True,
    cfg: N201Config | None = None,
    generated_at: str | None = None,
    library_root: Path | None = None,
    library_policy_path: Path | None = None,
    include_admitted_markets: bool = True,
) -> dict[str, Any]:
    """Load FTSE history (+ archive enrich) and admitted library panels; score."""
    data_dir = Path(output_dir) if output_dir is not None else DEFAULT_OUTPUT_DIR
    store = Path(store_path) if store_path is not None else DEFAULT_STORE_PATH
    reg_path = (
        Path(registration_path) if registration_path is not None else DEFAULT_REGISTRATION_PATH
    )
    lib_root = Path(library_root) if library_root is not None else DEFAULT_LIBRARY_ROOT
    cfg = cfg or N201Config()

    prior_markers: list[dict[str, Any]] = []
    if store.is_file():
        try:
            prior = json.loads(store.read_text(encoding="utf-8"))
            markers = prior.get("change_markers")
            if isinstance(markers, list):
                prior_markers = [m for m in markers if isinstance(m, dict)]
        except (OSError, json.JSONDecodeError):
            prior_markers = []

    ftse_snapshots = enrich_snapshots_from_archives(
        load_run_snapshots(data_dir), data_dir / "archive"
    )
    payloads: list[dict[str, Any]] = []
    # Share a fetch budget across markets (FTSE first).
    shared_frames: dict[str, pd.DataFrame] = dict(cfg.price_frames or {})
    fetch_budget = int(cfg.max_momentum_price_fetches)

    ftse_cfg = N201Config(
        market_id=cfg.market_id,
        buy_cost_pct=cfg.buy_cost_pct,
        sell_cost_pct=cfg.sell_cost_pct,
        stress_trade_cost_pct=cfg.stress_trade_cost_pct,
        volume_min_episodes=cfg.volume_min_episodes,
        volume_min_weeks=cfg.volume_min_weeks,
        phase_entries_per_week_floor=cfg.phase_entries_per_week_floor,
        hold_trading_days=cfg.hold_trading_days,
        fixed_stake_units=cfg.fixed_stake_units,
        ey_top_share=cfg.ey_top_share,
        max_episodes=cfg.max_episodes,
        fetch_momentum_prices=cfg.fetch_momentum_prices,
        max_momentum_price_fetches=fetch_budget,
        price_frames=shared_frames,
        trading_sessions=cfg.trading_sessions,
    )
    ftse_payload = build_n201_observe(
        ftse_snapshots,
        cfg=ftse_cfg,
        generated_at=generated_at,
        prior_markers=prior_markers,
    )
    payloads.append(ftse_payload)
    fetch_budget = max(0, int(cfg.max_momentum_price_fetches) - len(shared_frames))

    panel_loaded: list[str] = []
    panel_missing: list[str] = []
    panel_counts: dict[str, int] = {DEFAULT_MARKET_ID: len(ftse_snapshots)}

    if include_admitted_markets:
        for mid in _admitted_markets(library_policy_path):
            snaps = load_library_market_snapshots(lib_root, mid)
            if not snaps:
                panel_missing.append(mid)
                continue
            panel_loaded.append(mid)
            panel_counts[mid] = len(snaps)
            remaining_episodes = max(
                0,
                cfg.max_episodes
                - sum(int(p.get("completed_entry_episodes") or 0) for p in payloads),
            )
            if remaining_episodes <= 0:
                break
            mid_cfg = N201Config(
                market_id=mid,
                buy_cost_pct=cfg.buy_cost_pct,
                sell_cost_pct=cfg.sell_cost_pct,
                stress_trade_cost_pct=cfg.stress_trade_cost_pct,
                volume_min_episodes=cfg.volume_min_episodes,
                volume_min_weeks=cfg.volume_min_weeks,
                phase_entries_per_week_floor=cfg.phase_entries_per_week_floor,
                hold_trading_days=cfg.hold_trading_days,
                fixed_stake_units=cfg.fixed_stake_units,
                ey_top_share=cfg.ey_top_share,
                max_episodes=remaining_episodes,
                fetch_momentum_prices=cfg.fetch_momentum_prices and fetch_budget > 0,
                max_momentum_price_fetches=int(cfg.max_momentum_price_fetches),
                price_frames=shared_frames,
                trading_sessions=cfg.trading_sessions,
            )
            market_payload = build_n201_observe(
                snaps,
                cfg=mid_cfg,
                generated_at=generated_at,
                prior_markers=[],
            )
            payloads.append(market_payload)
            fetch_budget = max(0, int(cfg.max_momentum_price_fetches) - len(shared_frames))

    panel_coverage = {
        "ftse_snapshots": len(ftse_snapshots),
        "admitted_loaded": panel_loaded,
        "admitted_missing_or_empty": panel_missing,
        "panel_snapshot_counts": panel_counts,
        "library_root": str(lib_root),
    }
    payload = _merge_observe_payloads(
        payloads,
        generated_at=generated_at,
        prior_markers=prior_markers,
        panel_coverage=panel_coverage,
        cfg=cfg,
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
