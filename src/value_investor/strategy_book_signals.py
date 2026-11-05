"""Point-in-time entry signal for the strategy book.

The forward walker (plan step 2.3) imports this module. It does not decide
episodes, fills, or exits. One failure, or a missing input, is not eligible.

Primary price rule (registration section 3): RSI(14) below 35 and the close
equal to the minimum of the 10 chart sessions ending at *t* (ties count).
The pre-registered alternative (RSI below 40 and at least 3 percent under
SMA(10)) is reported and does not gate a signal or a memo.

Screen runs and gate stores apply only to sessions strictly after their
calendar date (registration section 2). Files dated after *t* are not used.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.decision_input_inventory import (
    DEFAULT_MEMO_MAX_AGE_DAYS,
    _memo_age_days,
    _overlay_bound,
)
from value_investor.library_decision_input_inventory import (
    _index_as_of,
    _memo_as_of,
    evaluate_library_fcf_basis,
    graduated_market_ids,
    library_screen_free_cashflow,
)
from value_investor.paper_fund import BUY_SIGNALS
from value_investor.price_charts import chart_filename
from value_investor.sector_headwind_gate import FTSE_MARKET
from value_investor.storage import read_json
from value_investor.technical_analysis import _rsi

# Registration section 3, primary rule. ``_rsi`` period is 14.
RSI_PERIOD = 14
# Strictly below. ``TradePlanConfig.accumulate_rsi_limit_gate`` is 35.
RSI_LEVEL = 35
# Chart sessions ending at *t*. Ties count. A shorter history does not fire.
LOW_WINDOW_SESSIONS = 10

# Registration section 3, pre-registered alternative. Report-only.
# It does not open a forward episode and it does not request a memo.
ALT_RSI_LEVEL = 40
ALT_SMA_WINDOW = 10
# At least this fraction under the 10-session simple average.
ALT_SMA_DISTANCE = 0.03

# Registration section 2: memo age uses the existing 21-day maximum.
MEMO_MAX_AGE_DAYS = DEFAULT_MEMO_MAX_AGE_DAYS

# Registration section 3: no fill when the next session is more than 5 calendar days after *t*.
MAX_FILL_GAP_CALENDAR_DAYS = 5

# Registration section 3: a forward chart more than 5 calendar days behind the
# decision date produces no signal that day.
STALE_CHART_CALENDAR_DAYS = 5

# Registration section 5. Review spacing on the primary exit.
REVIEW_INDEXES = (63, 126, 189)

# ``_rsi`` is finite after 15 closes (diff plus ewm min_periods=14).
_RSI_MIN_CLOSES = RSI_PERIOD + 1

_RUN_PREFIX = "run_"


@dataclass
class Check:
    """One eligibility check. ``passed`` false is fail-closed."""

    name: str
    passed: bool
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "passed": self.passed,
            "reason": self.reason,
        }
        if self.detail:
            payload["detail"] = self.detail
        return payload


@dataclass
class NameSignal:
    """Every check for one buy-tier name on session *t*."""

    market: str
    ticker: str
    session: str
    checks: dict[str, Check]
    input_paths: list[str] = field(default_factory=list)
    screen_row: dict[str, Any] = field(default_factory=dict)

    def check(self, name: str) -> Check:
        return self.checks[name]

    @property
    def price_entry(self) -> bool:
        return self.checks["price_entry"].passed

    @property
    def eligible_except_memo(self) -> bool:
        """Parts 1–3, the primary price rule, and the three non-memo F9-B binds."""
        names = (
            "part1_signal",
            "price_entry",
            "part2_decline",
            "part3_sector",
            "key_filing_bodies",
            "fcf_basis_bound",
            "overlay_bound",
        )
        return all(self.checks[name].passed for name in names)

    @property
    def memo_needed(self) -> bool:
        """Stale or missing memo, and the next stored bar is not a dropped gap."""
        if not self.eligible_except_memo or self.checks["memo_recent"].passed:
            return False
        gap = self.checks.get("fill_gap")
        return gap is None or gap.passed

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "ticker": self.ticker,
            "session": self.session,
            "price_entry": self.price_entry,
            "eligible_except_memo": self.eligible_except_memo,
            "memo_needed": self.memo_needed,
            "alternative_entry": self.checks["alternative_entry"].passed,
            "checks": {name: row.to_dict() for name, row in self.checks.items()},
            "input_paths": list(self.input_paths),
        }


@dataclass
class MarketSignals:
    market: str
    session: str
    names: list[NameSignal]
    screen_path: str | None = None
    screen_run_at: str | None = None
    error: str | None = None

    @property
    def buy_tier(self) -> int:
        return len(self.names)

    @property
    def signals(self) -> int:
        return sum(1 for row in self.names if row.price_entry)

    @property
    def all_but_memo(self) -> int:
        return sum(1 for row in self.names if row.eligible_except_memo)

    @property
    def memo_needed(self) -> int:
        return sum(1 for row in self.names if row.memo_needed)


@dataclass(frozen=True)
class RepoPaths:
    root: Path
    data: Path
    history: Path
    charts: Path
    research: Path
    library: Path
    market_status: Path
    decline: Path
    sector: Path
    observe: Path
    registration: Path
    memo_log: Path
    summary: Path


def repo_paths(repo_root: Path | None = None) -> RepoPaths:
    root = Path(repo_root) if repo_root is not None else Path()
    data = root / "docs" / "data"
    library = data / "library"
    return RepoPaths(
        root=root,
        data=data,
        history=data / "history",
        charts=data / "charts",
        research=data / "research",
        library=library,
        market_status=data / "market_status.json",
        decline=data / "operating_decline_gate.json",
        sector=data / "sector_headwind_gate.json",
        observe=data / "strategy_book_observe.json",
        registration=data / "strategy_book_registration.json",
        memo_log=data / "strategy_book_memo_log.jsonl",
        summary=data / "strategy_book_memo_job.json",
    )


def universe_markets(market_status: Path) -> list[str]:
    """FTSE 350 plus each library market with ``is_graduated`` true.

    FTSE is the live screen, not a graduated library market (section 2).
    A missing status file yields FTSE only. Library markets are not invented.
    """
    library = [mid for mid in graduated_market_ids(market_status) if mid != FTSE_MARKET]
    return [FTSE_MARKET, *library]


def session_end(day: date) -> datetime:
    """UTC end of the session calendar day. A later timestamp is after *t*."""
    return datetime.combine(day, time(23, 59, 59), tzinfo=UTC)


def parse_day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def next_weekday(day: date) -> date:
    cursor = day + timedelta(days=1)
    while cursor.weekday() >= 5:
        cursor += timedelta(days=1)
    return cursor


def rsi_below(value: float | None, level: float) -> bool:
    """True only for a finite RSI strictly below ``level``."""
    if value is None or isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(number):
        return False
    return number < float(level)


def rsi_last(closes: list[float]) -> float | None:
    """Wilder RSI(14) via ``technical_analysis._rsi`` on the prefix through *t*."""
    if len(closes) < _RSI_MIN_CLOSES:
        return None
    series = _rsi(pd.Series(closes, dtype="float64"), period=RSI_PERIOD)
    raw = series.iloc[-1]
    if raw is None or pd.isna(raw):
        return None
    number = float(raw)
    if not math.isfinite(number):
        return None
    return number


def median_gap_days(days: list[date]) -> float | None:
    if len(days) < 2:
        return None
    gaps = sorted((b - a).days for a, b in zip(days, days[1:], strict=False))
    mid = len(gaps) // 2
    if len(gaps) % 2:
        return float(gaps[mid])
    return (gaps[mid - 1] + gaps[mid]) / 2.0


def chart_is_thinned(days: list[date]) -> bool:
    """A downsampled tape has a median gap above one calendar day.

    Registration section 12: a thinned tape changes RSI(14). A daily tape's
    median gap is 1 (weekday steps), with weekend gaps in the tail.
    """
    gap = median_gap_days(days)
    return gap is not None and gap > 1


def load_chart_closes(
    path: Path,
    session: date,
) -> tuple[list[date], list[float], list[date]]:
    """Closes on or before ``session``, plus every date in the file.

    Bars dated after ``session`` are ignored. Returns (prefix days, prefix
    closes, all days in the file).
    """
    if not path.is_file():
        return [], [], []
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return [], [], []
    if not isinstance(payload, dict):
        return [], [], []
    raw_dates = payload.get("dates") or []
    raw_closes = payload.get("closes") or []
    pairs: list[tuple[date, float]] = []
    for raw_day, raw_close in zip(raw_dates, raw_closes, strict=False):
        day = parse_day(raw_day)
        if day is None:
            continue
        try:
            close = float(raw_close)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(close) or close <= 0:
            continue
        pairs.append((day, close))
    pairs.sort(key=lambda item: item[0])
    dedup: dict[date, float] = {}
    for day, close in pairs:
        dedup[day] = close
    ordered = sorted(dedup.items())
    all_days = [day for day, _close in ordered]
    prefix = [(day, close) for day, close in ordered if day <= session]
    return (
        [day for day, _close in prefix],
        [close for _day, close in prefix],
        all_days,
    )


def _filename_day(path: Path) -> date | None:
    digits = "".join(ch for ch in path.name if ch.isdigit())
    if len(digits) < 8:
        return None
    try:
        return datetime.strptime(digits[:8], "%Y%m%d").date()
    except ValueError:
        return None


def _run_calendar_day(path: Path, payload: dict[str, Any]) -> date | None:
    from value_investor.buy_tier_flip_lag import _parse_dt

    stamped = _parse_dt(payload.get("run_at"))
    if stamped is not None:
        return stamped.date()
    name = path.name
    digits = "".join(ch for ch in name if ch.isdigit())
    if len(digits) >= 8:
        try:
            return datetime.strptime(digits[:8], "%Y%m%d").date()
        except ValueError:
            return None
    return None


def newest_screen_run(
    history_dir: Path,
    session: date,
) -> tuple[Path | None, dict[str, Any] | None, date | None]:
    """Newest ``run_*`` whose calendar date is strictly before ``session``.

    Registration section 2: a run applies to chart sessions strictly after the
    run's calendar date. The run dated 2026-11-01 does not qualify that day's
    close, and it does not qualify an earlier close.
    """
    if not history_dir.is_dir():
        return None, None, None
    candidates: list[Path] = []
    for path in history_dir.iterdir():
        name = path.name
        if not path.is_file() or not name.startswith(_RUN_PREFIX):
            continue
        if not (name.endswith(".json") or name.endswith(".json.gz")):
            continue
        candidates.append(path)
    candidates.sort(key=lambda item: item.name, reverse=True)
    for path in candidates:
        hinted = _filename_day(path)
        # The run file is named with its calendar date. A later name cannot
        # qualify this session, so it is not opened.
        if hinted is not None and hinted >= session:
            continue
        try:
            payload = read_json(path)
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        run_day = _run_calendar_day(path, payload)
        if run_day is None or run_day >= session:
            continue
        return path, payload, run_day
    return None, None, None


def screen_rows(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Ticker → row. Library runs use ``signals``; FTSE history uses ``reports``."""
    if not isinstance(payload, dict):
        return {}
    raw = payload.get("signals")
    if not isinstance(raw, list) or not raw:
        raw = payload.get("reports")
    rows: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, list):
        return rows
    for row in raw:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip().upper()
        if ticker and ticker not in rows:
            rows[ticker] = row
    return rows


def _store_as_of(payload: dict[str, Any] | None) -> date | None:
    if not isinstance(payload, dict):
        return None
    return parse_day(payload.get("as_of"))


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _verdict_in_force(store_as_of: date | None, session: date) -> str | None:
    """None when the store may be used. Otherwise a fail-closed reason.

    A verdict applies to sessions strictly after the store's ``as_of`` date.
    A file dated after *t* is not read as a pass.
    """
    if store_as_of is None:
        return "store_missing"
    if store_as_of > session:
        return "store_after_session"
    if store_as_of >= session:
        return "verdict_not_in_force"
    return None


def _decline_verdict(
    payload: dict[str, Any] | None,
    ticker: str,
    session: date,
) -> Check:
    blocked = _verdict_in_force(_store_as_of(payload), session)
    if blocked is not None:
        return Check("part2_decline", False, blocked, {"as_of": _iso(_store_as_of(payload))})
    names = payload.get("names") if isinstance(payload, dict) else None
    entry = _lookup(names, ticker)
    if not isinstance(entry, dict):
        return Check("part2_decline", False, "missing_verdict")
    verdict = str(entry.get("verdict") or "").strip()
    passed = verdict == "clear"
    reason = "clear" if passed else (verdict or "missing_verdict")
    return Check(
        "part2_decline",
        passed,
        reason,
        {"verdict": verdict or None, "as_of": _iso(_store_as_of(payload))},
    )


def _sector_verdict(
    payload: dict[str, Any] | None,
    market: str,
    ticker: str,
    session: date,
) -> Check:
    blocked = _verdict_in_force(_store_as_of(payload), session)
    if blocked is not None:
        return Check("part3_sector", False, blocked, {"as_of": _iso(_store_as_of(payload))})
    by_market = payload.get("names_by_market") if isinstance(payload, dict) else None
    market_names = _lookup(by_market, market)
    entry = _lookup(market_names, ticker)
    if not isinstance(entry, dict):
        return Check("part3_sector", False, "missing_verdict")
    verdict = str(entry.get("sector_verdict") or "").strip()
    basis = str(entry.get("sector_basis") or "").strip() or None
    passed = verdict == "sound"
    reason = "sound" if passed else (verdict or "missing_verdict")
    return Check(
        "part3_sector",
        passed,
        reason,
        {
            "sector_verdict": verdict or None,
            "sector_basis": basis,
            "as_of": _iso(_store_as_of(payload)),
        },
    )


def _lookup(mapping: Any, key: str) -> Any:
    if not isinstance(mapping, dict):
        return None
    if key in mapping:
        return mapping[key]
    folded = key.casefold()
    upper = key.upper()
    for raw, value in mapping.items():
        text = str(raw)
        if text.casefold() == folded or text.upper() == upper:
            return value
    return None


def _iso(day: date | None) -> str | None:
    return day.isoformat() if day is not None else None


def _price_checks(
    *,
    chart_path: Path,
    session: date,
) -> tuple[dict[str, Check], list[date], list[str]]:
    days, closes, all_days = load_chart_closes(chart_path, session)
    paths = [str(chart_path)] if chart_path.is_file() else []
    detail_base = {"chart": chart_path.name}
    if not days or not closes:
        missing = Check("rsi_below_35", False, "missing_chart", detail_base)
        low = Check("ten_session_low", False, "missing_chart", detail_base)
        price = Check("price_entry", False, "missing_chart", detail_base)
        alt = Check("alternative_entry", False, "missing_chart", detail_base)
        return (
            {
                "rsi_below_35": missing,
                "ten_session_low": low,
                "price_entry": price,
                "alternative_entry": alt,
            },
            all_days,
            paths,
        )
    if days[-1] != session:
        reason = "session_not_in_chart"
        detail = {**detail_base, "last_bar": days[-1].isoformat()}
        blank = Check("rsi_below_35", False, reason, detail)
        return (
            {
                "rsi_below_35": blank,
                "ten_session_low": Check("ten_session_low", False, reason, detail),
                "price_entry": Check("price_entry", False, reason, detail),
                "alternative_entry": Check("alternative_entry", False, reason, detail),
            },
            all_days,
            paths,
        )
    if chart_is_thinned(days):
        detail = {**detail_base, "median_gap_days": median_gap_days(days)}
        blank = Check("rsi_below_35", False, "thinned_chart", detail)
        return (
            {
                "rsi_below_35": blank,
                "ten_session_low": Check("ten_session_low", False, "thinned_chart", detail),
                "price_entry": Check("price_entry", False, "thinned_chart", detail),
                "alternative_entry": Check("alternative_entry", False, "thinned_chart", detail),
            },
            all_days,
            paths,
        )

    rsi = rsi_last(closes)
    rsi_ok = rsi_below(rsi, RSI_LEVEL)
    rsi_reason = "below_35" if rsi_ok else ("not_finite" if rsi is None else "not_below_35")
    rsi_check = Check(
        "rsi_below_35",
        rsi_ok,
        rsi_reason,
        {"rsi_14": None if rsi is None else round(rsi, 4), "level": RSI_LEVEL},
    )

    if len(closes) < LOW_WINDOW_SESSIONS:
        low_check = Check(
            "ten_session_low",
            False,
            "shorter_than_10",
            {"closes": len(closes), "window": LOW_WINDOW_SESSIONS},
        )
        low_ok = False
    else:
        window = closes[-LOW_WINDOW_SESSIONS:]
        low_ok = closes[-1] == min(window)
        low_check = Check(
            "ten_session_low",
            low_ok,
            "is_low" if low_ok else "not_low",
            {
                "close": closes[-1],
                "window_min": min(window),
                "window": LOW_WINDOW_SESSIONS,
            },
        )

    price_ok = rsi_ok and low_ok
    price_reason = "primary" if price_ok else "primary_failed"
    price_check = Check("price_entry", price_ok, price_reason)

    alt_rsi = rsi_below(rsi, ALT_RSI_LEVEL)
    if len(closes) < ALT_SMA_WINDOW:
        alt = Check("alternative_entry", False, "shorter_than_10", {"closes": len(closes)})
    else:
        sample = closes[-ALT_SMA_WINDOW:]
        sma = sum(sample) / float(ALT_SMA_WINDOW)
        distance = (sma - closes[-1]) / sma if sma else None
        far = distance is not None and distance >= ALT_SMA_DISTANCE
        alt_ok = alt_rsi and far
        if alt_ok:
            alt_reason = "alternative"
        elif not alt_rsi:
            alt_reason = "rsi_not_below_40"
        else:
            alt_reason = "not_3pct_under_sma10"
        alt = Check(
            "alternative_entry",
            alt_ok,
            alt_reason,
            {
                "rsi_14": None if rsi is None else round(rsi, 4),
                "sma10": round(sma, 6),
                "distance": None if distance is None else round(distance, 6),
                "rsi_level": ALT_RSI_LEVEL,
                "distance_min": ALT_SMA_DISTANCE,
            },
        )
    return (
        {
            "rsi_below_35": rsi_check,
            "ten_session_low": low_check,
            "price_entry": price_check,
            "alternative_entry": alt,
        },
        all_days,
        paths,
    )


def _next_session(all_days: list[date], session: date) -> tuple[date, bool]:
    """Next chart session after *t*, or the next weekday when that bar is absent.

    The boolean is true when the date is a stored bar. A stored gap over
    ``MAX_FILL_GAP_CALENDAR_DAYS`` drops the signal (section 3).
    """
    later = [day for day in all_days if day > session]
    if later:
        return later[0], True
    return next_weekday(session), False


def _filing_paths(research_root: Path, ticker: str) -> list[Path]:
    base = research_root / ticker
    names = [
        base / "research.json",
        base / "sources" / "filings" / "filings_index.json",
        base / "sources" / "financials_annual.json",
        base / "sources" / "sec_companyfacts.json",
        base / "sources" / "fcf_bridge.json",
    ]
    return [path for path in names if path.is_file()]


def _library_snapshot_as_of(session: date) -> datetime:
    """Close of *t* for the library screen CSV and the FCF source files.

    A snapshot timestamp after this is not a pass. The forward job reads the
    snapshots after they refresh and before the next close.
    """
    return session_end(session)


def _binds(
    *,
    market: str,
    ticker: str,
    row: dict[str, Any],
    research_root: Path,
    session: date,
    memo_as_of: datetime,
) -> tuple[dict[str, Check], list[str]]:
    as_of = session_end(session)
    paths = [str(path) for path in _filing_paths(research_root, ticker)]
    index = _index_as_of(ticker, research_root=research_root, as_of=as_of)
    bodies_ok = bool(index.get("key_bodies"))
    bodies = Check(
        "key_filing_bodies",
        bodies_ok,
        "key_bodies" if bodies_ok else "missing_key_bodies",
        {
            "filings_with_body": index.get("filings_with_body"),
            "filings_total": index.get("filings_total"),
        },
    )

    if market == FTSE_MARKET:
        overlay_flag = row.get("fcf_basis_overlay")
        fcf_ok = isinstance(overlay_flag, bool)
        fcf = Check(
            "fcf_basis_bound",
            fcf_ok,
            "boolean_overlay" if fcf_ok else "overlay_not_boolean",
            {"fcf_basis_overlay": overlay_flag if isinstance(overlay_flag, bool) else None},
        )
    else:
        # History rows do not carry free_cashflow. The figure lives on the
        # market's latest_signals.csv, dated by latest_summary.json run_at.
        snapshot_as_of = _library_snapshot_as_of(session)
        screen = library_screen_free_cashflow(
            research_root.parent,
            ticker,
            as_of=snapshot_as_of,
        )
        paths.extend(str(item) for item in screen.get("paths") or [])
        if screen.get("reason"):
            fcf = Check(
                "fcf_basis_bound",
                False,
                str(screen.get("reason")),
                {"free_cashflow": None},
            )
        else:
            detail = evaluate_library_fcf_basis(
                research_root / ticker,
                screen_fcf=screen.get("free_cashflow"),
                as_of=snapshot_as_of,
            )
            fcf_ok = bool(detail.get("fcf_basis_bound"))
            fcf = Check(
                "fcf_basis_bound",
                fcf_ok,
                "evaluated" if fcf_ok else "not_evaluable",
                {
                    "free_cashflow": screen.get("free_cashflow"),
                    "fcf_basis_overlay": detail.get("fcf_basis_overlay"),
                    "fcf_basis_source": detail.get("fcf_basis_source"),
                },
            )

    has_memo, memo_at, disk_verdict = _memo_as_of(
        ticker, research_root=research_root, as_of=memo_as_of
    )
    # Overlay uses the screen row, then a disk verdict dated on or before *t*.
    _has_at_t, _at_t, verdict_at_t = _memo_as_of(ticker, research_root=research_root, as_of=as_of)
    screen_verdict = _clean(row.get("research_verdict"))
    verdict = screen_verdict or verdict_at_t
    adjusted = _clean(row.get("adjusted_signal"))
    overlay_ok = _overlay_bound({"adjusted_signal": adjusted}, research_verdict=verdict)
    overlay = Check(
        "overlay_bound",
        bool(overlay_ok),
        "bound" if overlay_ok else "unbound",
        {"research_verdict": verdict, "adjusted_signal": adjusted},
    )

    age = _memo_age_days(memo_at, now=memo_as_of) if has_memo else None
    recent = bool(has_memo and age is not None and age <= float(MEMO_MAX_AGE_DAYS))
    if recent:
        memo_reason = "recent"
    elif not has_memo:
        memo_reason = "missing"
    else:
        memo_reason = "older_than_21_days"
    memo = Check(
        "memo_recent",
        recent,
        memo_reason,
        {
            "memo_at": memo_at.isoformat() if memo_at else None,
            "memo_age_days": age,
            "max_age_days": MEMO_MAX_AGE_DAYS,
            "disk_verdict": disk_verdict,
        },
    )
    return (
        {
            "key_filing_bodies": bodies,
            "fcf_basis_bound": fcf,
            "overlay_bound": overlay,
            "memo_recent": memo,
        },
        paths,
    )


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in {"", "none", "nan", "null"}:
        return None
    return text


def research_root_for(paths: RepoPaths, market: str) -> Path:
    if market == FTSE_MARKET:
        return paths.research
    return paths.library / "markets" / market / "screen" / "research"


def history_dir_for(paths: RepoPaths, market: str) -> Path:
    if market == FTSE_MARKET:
        return paths.history
    return paths.library / "markets" / market / "screen" / "history"


def evaluate_ticker(
    *,
    market: str,
    ticker: str,
    session: date,
    row: dict[str, Any] | None,
    paths: RepoPaths,
    decline_payload: dict[str, Any] | None,
    sector_payload: dict[str, Any] | None,
    screen_path: Path | None,
) -> NameSignal:
    """Every check for one name. A missing row fails part 1."""
    token = str(ticker or "").strip().upper()
    signal = str((row or {}).get("signal") or "").strip()
    part1_ok = signal in BUY_SIGNALS
    part1 = Check(
        "part1_signal",
        part1_ok,
        signal if part1_ok else (signal or "no_screen_row"),
        {"signal": signal or None},
    )
    chart_path = paths.charts / chart_filename(token)
    price, all_days, chart_paths = _price_checks(chart_path=chart_path, session=session)
    next_day, stored_next = _next_session(all_days, session)
    gap_days = (next_day - session).days if stored_next else None
    research_root = research_root_for(paths, market)
    binds, filing_paths = _binds(
        market=market,
        ticker=token,
        row=row or {},
        research_root=research_root,
        session=session,
        memo_as_of=session_end(next_day),
    )
    gap_over = bool(stored_next and gap_days is not None and gap_days > MAX_FILL_GAP_CALENDAR_DAYS)
    # Section 3: a hole longer than 5 calendar days drops the signal. No memo.
    fill_gap = Check(
        "fill_gap",
        not gap_over,
        "gap_over_5_days" if gap_over else ("stored_next" if stored_next else "next_not_stored"),
        {
            "next_session": next_day.isoformat(),
            "stored_next": stored_next,
            "gap_calendar_days": gap_days,
        },
    )
    decline = _decline_verdict(decline_payload, token, session)
    sector = _sector_verdict(sector_payload, market, token, session)
    checks = {
        "part1_signal": part1,
        **price,
        "part2_decline": decline,
        "part3_sector": sector,
        **binds,
        "fill_gap": fill_gap,
    }
    inputs: list[str] = []
    if screen_path is not None:
        inputs.append(str(screen_path))
    inputs.extend(chart_paths)
    if paths.decline.is_file():
        inputs.append(str(paths.decline))
    if paths.sector.is_file():
        inputs.append(str(paths.sector))
    inputs.extend(filing_paths)
    # De-duplicate while keeping order.
    seen: set[str] = set()
    unique: list[str] = []
    for item in inputs:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return NameSignal(
        market=market,
        ticker=token,
        session=session.isoformat(),
        checks=checks,
        input_paths=unique,
        screen_row=dict(row or {}),
    )


def evaluate_market(
    market: str,
    session: date,
    *,
    paths: RepoPaths | None = None,
    repo_root: Path | None = None,
    decline_payload: dict[str, Any] | None = None,
    sector_payload: dict[str, Any] | None = None,
    load_stores: bool = True,
) -> MarketSignals:
    """Buy-tier names on ``session`` with every check filled in.

    Names whose raw signal is not ``buy`` or ``strong_buy`` are omitted.
    """
    book = paths or repo_paths(repo_root)
    screen_path, payload, run_day = newest_screen_run(history_dir_for(book, market), session)
    if load_stores and decline_payload is None:
        decline_payload = _load_json(book.decline)
    if load_stores and sector_payload is None:
        sector_payload = _load_json(book.sector)
    rows = screen_rows(payload)
    names: list[NameSignal] = []
    for ticker in sorted(rows):
        row = rows[ticker]
        signal = str(row.get("signal") or "").strip()
        if signal not in BUY_SIGNALS:
            continue
        names.append(
            evaluate_ticker(
                market=market,
                ticker=ticker,
                session=session,
                row=row,
                paths=book,
                decline_payload=decline_payload,
                sector_payload=sector_payload,
                screen_path=screen_path,
            )
        )
    run_at = None
    if isinstance(payload, dict) and payload.get("run_at"):
        run_at = str(payload.get("run_at"))
    elif run_day is not None:
        run_at = run_day.isoformat()
    return MarketSignals(
        market=market,
        session=session.isoformat(),
        names=names,
        screen_path=str(screen_path) if screen_path is not None else None,
        screen_run_at=run_at,
        error=None if screen_path is not None else "no_screen_run",
    )


def review_memo_needs(
    observe: dict[str, Any] | None,
    *,
    market: str,
    session: date,
) -> list[dict[str, Any]]:
    """Launched episodes whose review index is 63, 126 or 189 on ``session``.

    A missing observe store yields nothing. The walker writes ``episodes``
    with ``reviews`` of ``{index, session}`` (or ``review_sessions`` keyed by
    index). This does not invent episodes from charts.
    """
    if not isinstance(observe, dict):
        return []
    episodes = observe.get("episodes")
    if not isinstance(episodes, list):
        return []
    found: list[dict[str, Any]] = []
    session_iso = session.isoformat()
    for episode in episodes:
        if not isinstance(episode, dict):
            continue
        ep_market = str(episode.get("market") or episode.get("market_id") or "").strip()
        if ep_market != market:
            continue
        if not _episode_launched(episode) or _episode_closed(episode):
            continue
        ticker = str(episode.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        for index, review_day in _review_dates(episode):
            if index not in REVIEW_INDEXES or review_day != session_iso:
                continue
            found.append(
                {
                    "ticker": ticker,
                    "market": market,
                    "session": session_iso,
                    "review_index": index,
                    "episode_id": episode.get("episode_id"),
                }
            )
    return found


def _episode_launched(episode: dict[str, Any]) -> bool:
    if episode.get("launched") is True:
        return True
    if episode.get("launched_at") or episode.get("launch_session"):
        return True
    return str(episode.get("state") or episode.get("status") or "").strip() == "launched"


def _episode_closed(episode: dict[str, Any]) -> bool:
    state = str(episode.get("state") or episode.get("status") or "").strip().lower()
    return state in {"closed", "exited", "sold"}


def _review_dates(episode: dict[str, Any]) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    reviews = episode.get("reviews")
    if isinstance(reviews, list):
        for row in reviews:
            if not isinstance(row, dict):
                continue
            try:
                index = int(row.get("index"))
            except (TypeError, ValueError):
                continue
            day = parse_day(row.get("session") or row.get("date"))
            if day is not None:
                out.append((index, day.isoformat()))
    keyed = episode.get("review_sessions")
    if isinstance(keyed, dict):
        for raw_index, raw_day in keyed.items():
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                continue
            day = parse_day(raw_day)
            if day is not None:
                out.append((index, day.isoformat()))
    return out


__all__ = [
    "ALT_RSI_LEVEL",
    "ALT_SMA_DISTANCE",
    "ALT_SMA_WINDOW",
    "BUY_SIGNALS",
    "FTSE_MARKET",
    "LOW_WINDOW_SESSIONS",
    "MAX_FILL_GAP_CALENDAR_DAYS",
    "MEMO_MAX_AGE_DAYS",
    "REVIEW_INDEXES",
    "RSI_LEVEL",
    "RSI_PERIOD",
    "STALE_CHART_CALENDAR_DAYS",
    "Check",
    "MarketSignals",
    "NameSignal",
    "RepoPaths",
    "chart_is_thinned",
    "evaluate_market",
    "evaluate_ticker",
    "history_dir_for",
    "newest_screen_run",
    "repo_paths",
    "research_root_for",
    "review_memo_needs",
    "rsi_below",
    "rsi_last",
    "universe_markets",
]
