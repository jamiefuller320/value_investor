"""Observe-only sector headwind gate for strategy part 3, "Sector sound"."""

from __future__ import annotations

import csv
import gzip
import json
import math
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from statistics import fmean
from typing import Any

from value_investor.operating_decline_gate import EPS_INTERIM_DROP_PCT

DEFAULT_LATEST_PATH = Path("docs/data/latest.json")
DEFAULT_CHARTS_DIR = Path("docs/data/charts")
DEFAULT_DECLINE_STORE = Path("docs/data/operating_decline_gate.json")
DEFAULT_STORE_PATH = Path("docs/data/sector_headwind_gate.json")
DEFAULT_MARKET_STATUS = Path("docs/data/market_status.json")
DEFAULT_LIBRARY_ROOT = Path("docs/data/library")
DEFAULT_LABEL_HISTORY = Path("docs/data/sector_label_history.jsonl")
FTSE_MARKET = "ftse350"
SCREEN_EARNINGS_FIELDS = (
    "interim_eps_decline_pct",
    "yahoo_normalized_income_growth_pct",
    "adjusted_eps_growth_pct",
)

SCHEMA_VERSION = 1
MIN_MEMBERS_WITH_DATA = 4
MIN_COVERAGE_SHARE = 0.60
PRICE_BREADTH_HEADWIND = 0.65
SECTOR_RETURN_126D_HEADWIND = -0.10
EARNINGS_BREADTH_HEADWIND = 0.50
DECLINE_BREADTH_HEADWIND = 0.50
SCREEN_EARNINGS_GROWTH_DECLINE_PCT = -0.05
RETURN_LOOKBACK_63D = 63
RETURN_LOOKBACK_126D = 126
TRAILING_HIGH_LOOKBACK = 252
BUY_TIER_SIGNALS = frozenset({"buy", "strong_buy"})
VERDICTS = ("sound", "headwind", "insufficient_data")

# Frozen regional groups for the member-count fallback. A market that is not
# listed here is never rescored across peers. Only markets graduated at
# refresh, plus the live FTSE 350, contribute members.
REGIONAL_GROUPS: dict[str, tuple[str, ...]] = {
    "uk": ("ftse350", "ftse_smallcap", "aim"),
    "europe": (
        "aex",
        "atx",
        "bel20",
        "cac40",
        "dax",
        "euro_stoxx50",
        "ftse_mib",
        "ibex35",
        "iseq20",
        "omxs30",
        "psi20",
        "smi",
    ),
    "north_america": ("sp500", "nasdaq100", "tsx60"),
    "asia_pacific": ("hang_seng", "sti", "us_adr_asia", "asx200"),
}
REGION_BY_MARKET: dict[str, str] = {
    market: region for region, markets in REGIONAL_GROUPS.items() for market in markets
}

FINDING_TITLE = "Sector headwind gate refreshed (observe)"
COVERAGE_GAP_TITLE = "Sector headwind gate coverage gap"
FALLBACK_FINDING_TITLE = "Sector headwind gate fallback reliance (observe)"
STORE_FAILED_TITLE = "Sector headwind gate refresh failed"


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _as_of_date(value: Any) -> date:
    if value is None:
        return datetime.now(UTC).date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        raise ValueError("as_of must not be blank")
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return date.fromisoformat(text[:10])


def _chart_rows_as_of(chart: dict[str, Any], as_of: date) -> list[tuple[date, float, float | None]]:
    dates = chart.get("dates")
    closes = chart.get("closes")
    sma200 = chart.get("sma200_series")
    if not isinstance(dates, list) or not isinstance(closes, list):
        return []
    sma_values = sma200 if isinstance(sma200, list) else []
    rows: list[tuple[date, float, float | None]] = []
    for index, (raw_day, raw_close) in enumerate(zip(dates, closes, strict=False)):
        try:
            day = _as_of_date(raw_day)
        except (TypeError, ValueError):
            continue
        close = _finite_float(raw_close)
        if day > as_of or close is None or close <= 0:
            continue
        average = _finite_float(sma_values[index]) if index < len(sma_values) else None
        rows.append((day, close, average))
    rows.sort(key=lambda row: row[0])
    return rows


def _latest_close_and_sma(
    rows: list[tuple[date, float, float | None]],
) -> tuple[float, float] | None:
    if not rows:
        return None
    close = rows[-1][1]
    average = rows[-1][2]
    if average is None and len(rows) >= 200:
        average = fmean(row[1] for row in rows[-200:])
    if average is None or average <= 0:
        return None
    return close, average


def _equal_weight_return(
    series: list[list[tuple[date, float, float | None]]],
    lookback: int,
) -> tuple[float | None, int]:
    returns = [
        rows[-1][1] / rows[-(lookback + 1)][1] - 1.0
        for rows in series
        if len(rows) > lookback and rows[-(lookback + 1)][1] > 0
    ]
    if len(returns) < MIN_MEMBERS_WITH_DATA:
        return None, len(returns)
    return fmean(returns), len(returns)


def _equal_weight_drawdown(
    series: list[list[tuple[date, float, float | None]]],
) -> tuple[float | None, int, int]:
    eligible = [rows for rows in series if len(rows) >= 2]
    if len(eligible) < MIN_MEMBERS_WITH_DATA:
        return None, len(eligible), 0
    returns_by_day: dict[date, list[float]] = defaultdict(list)
    for rows in eligible:
        for prior, current in zip(
            rows[-(TRAILING_HIGH_LOOKBACK + 1) : -1],
            rows[-TRAILING_HIGH_LOOKBACK:],
            strict=False,
        ):
            if prior[1] > 0:
                returns_by_day[current[0]].append(current[1] / prior[1] - 1.0)
    daily_returns = [
        fmean(values)
        for _, values in sorted(returns_by_day.items())
        if len(values) >= MIN_MEMBERS_WITH_DATA
    ][-TRAILING_HIGH_LOOKBACK:]
    if not daily_returns:
        return None, len(eligible), 0
    index_path = [1.0]
    for daily_return in daily_returns:
        index_path.append(index_path[-1] * (1.0 + daily_return))
    peak = max(index_path)
    drawdown = index_path[-1] / peak - 1.0 if peak > 0 else None
    return drawdown, len(eligible), len(daily_returns)


def _coverage_ok(count: int, total: int) -> bool:
    return count >= MIN_MEMBERS_WITH_DATA and count / total >= MIN_COVERAGE_SHARE


def _earnings_decline(row: dict[str, Any]) -> tuple[bool | None, list[str]]:
    observed: list[tuple[str, float]] = []
    for field in (
        "interim_eps_decline_pct",
        "yahoo_normalized_income_growth_pct",
        "adjusted_eps_growth_pct",
    ):
        value = _finite_float(row.get(field))
        if value is not None:
            observed.append((field, value))
    if not observed:
        return None, []
    declining = any(
        (field == "interim_eps_decline_pct" and value >= EPS_INTERIM_DROP_PCT)
        or (field != "interim_eps_decline_pct" and value <= SCREEN_EARNINGS_GROWTH_DECLINE_PCT)
        for field, value in observed
    )
    return declining, [field for field, _ in observed]


def _member_library_earnings(
    member: dict[str, Any],
    decline_row: Any,
    *,
    allow_growth: bool,
) -> tuple[bool, str, list[str]] | None:
    """Per-member earnings input for a library or regional score.

    A usable decline-store verdict wins. ``earnings_growth`` is the library
    screen fallback and is read only when ``allow_growth`` is set. v0 screen
    fields still count when neither of those is present.
    """
    if isinstance(decline_row, dict):
        verdict = str(decline_row.get("verdict") or "")
        if verdict in {"clear", "declining"}:
            return verdict == "declining", "decline_store", []
    if allow_growth:
        growth = _finite_float(member.get("earnings_growth"))
        if growth is not None:
            declining = growth <= SCREEN_EARNINGS_GROWTH_DECLINE_PCT
            return declining, "screen_earnings_growth", ["earnings_growth"]
    declining, fields = _earnings_decline(member)
    if declining is None:
        return None
    return declining, "screen_fields", fields


def _decline_names(decline_verdicts: dict[str, Any] | None) -> dict[str, Any] | None:
    if decline_verdicts is None:
        return None
    names = decline_verdicts.get("names")
    if isinstance(names, dict):
        return names
    return decline_verdicts


def _decline_names_for_cutoff(
    decline_verdicts: dict[str, Any] | None,
    cutoff: date,
) -> dict[str, Any] | None:
    """Use decline rows only when the snapshot is not dated after ``cutoff``.

    A payload with no ``as_of`` is the in-memory shape the scorer already
    accepts. A stored snapshot dated after the decision date is later
    information and is ignored, the same way chart bars after ``cutoff`` are.
    """
    if not isinstance(decline_verdicts, dict):
        return None
    if "as_of" in decline_verdicts:
        try:
            if _as_of_date(decline_verdicts.get("as_of")) > cutoff:
                return None
        except (TypeError, ValueError):
            return None
    return _decline_names(decline_verdicts)


def _reason(code: str, detail: str, source: str) -> dict[str, str]:
    return {"code": code, "detail": detail, "source": source}


def assess_sector(
    members: list[dict[str, Any]],
    *,
    charts: dict[str, dict[str, Any]],
    decline_verdicts: dict[str, Any] | None,
    as_of: Any,
    earnings_growth_fallback: bool = False,
    earnings_growth_tickers: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Return a point-in-time sector verdict without using bars after ``as_of``.

    ``earnings_growth_fallback`` switches library members to a per-name
    earnings input: decline-store verdict, else ``earnings_growth`` for tickers
    in ``earnings_growth_tickers``, else the v0 screen fields. The default
    keeps the FTSE rule (decline store for the whole sector when it covers,
    otherwise the v0 screen fields only).
    """
    cutoff = _as_of_date(as_of)
    total = len(members)
    reasons: list[dict[str, str]] = []
    thresholds = {
        "minimum_members_with_data": MIN_MEMBERS_WITH_DATA,
        "minimum_coverage_share": MIN_COVERAGE_SHARE,
        "price_breadth_headwind": PRICE_BREADTH_HEADWIND,
        "sector_return_126d_headwind": SECTOR_RETURN_126D_HEADWIND,
        "earnings_breadth_headwind": EARNINGS_BREADTH_HEADWIND,
        "decline_breadth_headwind": DECLINE_BREADTH_HEADWIND,
        "interim_eps_decline_member": EPS_INTERIM_DROP_PCT,
        "screen_earnings_growth_decline_member": SCREEN_EARNINGS_GROWTH_DECLINE_PCT,
    }
    if total < MIN_MEMBERS_WITH_DATA:
        return {
            "verdict": "insufficient_data",
            "reasons": [
                _reason(
                    "TOO_FEW_SECTOR_MEMBERS",
                    f"{total} members; at least {MIN_MEMBERS_WITH_DATA} are required.",
                    "docs/data/latest.json reports[].sector",
                )
            ],
            "metrics": {
                "member_count": total,
                "as_of": cutoff.isoformat(),
                "earnings_component": "unavailable",
                "earnings_breadth_sources": {"decline_store": 0, "screen_earnings_growth": 0},
                "earnings_fallback_used": False,
                "thresholds": thresholds,
            },
        }

    chart_series: dict[str, list[tuple[date, float, float | None]]] = {}
    below_sma = 0
    price_count = 0
    for member in members:
        ticker = str(member.get("ticker") or "").strip()
        chart = charts.get(ticker)
        if not ticker or not isinstance(chart, dict):
            continue
        rows = _chart_rows_as_of(chart, cutoff)
        if rows:
            chart_series[ticker] = rows
        latest = _latest_close_and_sma(rows)
        if latest is not None:
            price_count += 1
            below_sma += int(latest[0] < latest[1])
    price_breadth = below_sma / price_count if price_count else None
    price_coverage = price_count / total
    price_available = _coverage_ok(price_count, total)

    all_series = list(chart_series.values())
    return_63d, return_63d_count = _equal_weight_return(all_series, RETURN_LOOKBACK_63D)
    return_126d, return_126d_count = _equal_weight_return(all_series, RETURN_LOOKBACK_126D)
    drawdown_1y, drawdown_count, drawdown_days = _equal_weight_drawdown(all_series)
    trend_available = return_126d is not None and _coverage_ok(return_126d_count, total)

    decline_names = _decline_names_for_cutoff(decline_verdicts, cutoff)
    from value_investor.fund_or_trust import is_fund_or_trust_entry

    # Funds and trusts have no operating verdict, so they leave the earnings and
    # decline breadth (numerator and coverage base) but stay in price breadth.
    fund_tickers: set[str] = set()
    if decline_names is not None:
        for member in members:
            ticker = str(member.get("ticker") or "").strip()
            if is_fund_or_trust_entry(decline_names.get(ticker)):
                fund_tickers.add(ticker)
    operating_total = total - len(fund_tickers)
    decline_count = 0
    decline_declining = 0
    if decline_names is not None:
        for member in members:
            ticker = str(member.get("ticker") or "").strip()
            row = decline_names.get(ticker)
            if not isinstance(row, dict):
                continue
            verdict = str(row.get("verdict") or "")
            if verdict not in {"clear", "declining"}:
                continue
            decline_count += 1
            decline_declining += int(verdict == "declining")
    decline_breadth = decline_declining / decline_count if decline_count else None
    decline_coverage = decline_count / operating_total if operating_total else 0.0
    decline_available = (
        decline_names is not None
        and operating_total > 0
        and _coverage_ok(decline_count, operating_total)
    )

    earnings_fields: set[str] = set()
    earnings_breadth_sources = {"decline_store": 0, "screen_earnings_growth": 0}
    screen_field_count = 0
    if earnings_growth_fallback:
        if earnings_growth_tickers is None:
            allowed_growth = frozenset(
                str(member.get("ticker") or "").strip() for member in members
            )
        else:
            allowed_growth = earnings_growth_tickers
        earnings_declining = 0
        for member in members:
            ticker = str(member.get("ticker") or "").strip()
            if ticker in fund_tickers:
                continue
            decline_row = decline_names.get(ticker) if isinstance(decline_names, dict) else None
            observed = _member_library_earnings(
                member,
                decline_row,
                allow_growth=bool(ticker) and ticker in allowed_growth,
            )
            if observed is None:
                continue
            declining, source, fields = observed
            if source == "decline_store":
                earnings_breadth_sources["decline_store"] += 1
            elif source == "screen_earnings_growth":
                earnings_breadth_sources["screen_earnings_growth"] += 1
            else:
                screen_field_count += 1
            earnings_declining += int(declining)
            earnings_fields.update(fields)
        earnings_count = (
            earnings_breadth_sources["decline_store"]
            + earnings_breadth_sources["screen_earnings_growth"]
            + screen_field_count
        )
        earnings_breadth = earnings_declining / earnings_count if earnings_count else None
        earnings_coverage = earnings_count / operating_total if operating_total else 0.0
        earnings_available = operating_total > 0 and _coverage_ok(earnings_count, operating_total)
        if not earnings_available:
            earnings_component = "unavailable"
        elif earnings_breadth_sources["screen_earnings_growth"]:
            earnings_component = "screen_earnings_growth_fallback"
        elif screen_field_count:
            earnings_component = "screen_fields_fallback"
        else:
            earnings_component = "operating_decline_store"
    elif decline_available:
        earnings_component = "operating_decline_store"
        earnings_count = decline_count
        earnings_declining = decline_declining
        earnings_breadth = decline_breadth
        earnings_coverage = decline_coverage
        earnings_available = True
        earnings_breadth_sources["decline_store"] = decline_count
    else:
        earnings_count = 0
        earnings_declining = 0
        for member in members:
            if str(member.get("ticker") or "").strip() in fund_tickers:
                continue
            declining, fields = _earnings_decline(member)
            if declining is None:
                continue
            earnings_count += 1
            earnings_declining += int(declining)
            earnings_fields.update(fields)
        earnings_breadth = earnings_declining / earnings_count if earnings_count else None
        earnings_coverage = earnings_count / operating_total if operating_total else 0.0
        earnings_available = operating_total > 0 and _coverage_ok(earnings_count, operating_total)
        earnings_component = "screen_fields_fallback" if earnings_available else "unavailable"
    earnings_fallback_used = earnings_breadth_sources["screen_earnings_growth"] > 0

    price_trigger = bool(
        price_available
        and trend_available
        and price_breadth is not None
        and return_126d is not None
        and price_breadth >= PRICE_BREADTH_HEADWIND
        and return_126d < SECTOR_RETURN_126D_HEADWIND
    )
    earnings_trigger = bool(
        earnings_available
        and earnings_breadth is not None
        and earnings_breadth >= EARNINGS_BREADTH_HEADWIND
    )
    if price_trigger:
        reasons.append(
            _reason(
                "PRICE_BREADTH_AND_TREND_HEADWIND",
                (
                    f"{price_breadth:.1%} are below 200d average and equal-weight "
                    f"126d return is {return_126d:.1%}."
                ),
                "docs/data/charts/{TICKER}.json dates/closes/sma200_series",
            )
        )
    if earnings_trigger and earnings_component == "screen_fields_fallback":
        reasons.append(
            _reason(
                "EARNINGS_BREADTH_HEADWIND",
                f"{earnings_breadth:.1%} of {earnings_count} covered members show decline.",
                "docs/data/latest.json reports[] earnings breadth fields",
            )
        )
    if earnings_trigger and earnings_component == "operating_decline_store":
        reasons.append(
            _reason(
                "OPERATING_DECLINE_BREADTH_HEADWIND",
                f"{decline_breadth:.1%} of {decline_count} covered members are declining.",
                "docs/data/operating_decline_gate.json names[].verdict",
            )
        )
    if earnings_trigger and earnings_component == "screen_earnings_growth_fallback":
        reasons.append(
            _reason(
                "EARNINGS_BREADTH_HEADWIND",
                (
                    f"{earnings_breadth:.1%} of {earnings_count} covered members show decline "
                    f"(decline_store={earnings_breadth_sources['decline_store']}, "
                    "screen_earnings_growth="
                    f"{earnings_breadth_sources['screen_earnings_growth']})."
                ),
                "docs/data/library/markets/<market>/screen/latest_signals.csv earnings_growth",
            )
        )

    missing_core: list[str] = []
    if not price_available:
        missing_core.append("price breadth")
    if not trend_available:
        missing_core.append("126d sector trend")
    if not earnings_available:
        missing_core.append("earnings breadth")
    if not reasons and missing_core:
        reasons.append(
            _reason(
                "INSUFFICIENT_CORE_COVERAGE",
                (
                    "Missing sufficient "
                    + ", ".join(missing_core)
                    + f"; each needs {MIN_MEMBERS_WITH_DATA}+ members and {MIN_COVERAGE_SHARE:.0%} coverage."
                ),
                "docs/data/latest.json; docs/data/charts/{TICKER}.json",
            )
        )
    if decline_names is None:
        reasons.append(
            _reason(
                "OPERATING_DECLINE_STORE_UNAVAILABLE",
                "Operating-decline breadth was unavailable; material screen fields were the fallback.",
                "docs/data/operating_decline_gate.json",
            )
        )
    elif not decline_available:
        thin_detail = (
            f"Operating-decline coverage was {decline_count}/{total}; "
            "material screen fields were the fallback."
        )
        if earnings_fallback_used:
            thin_detail = (
                f"Operating-decline coverage was {decline_count}/{total}; "
                f"{earnings_breadth_sources['screen_earnings_growth']} members used "
                "earnings_growth."
            )
        reasons.append(
            _reason(
                "OPERATING_DECLINE_STORE_THIN_FALLBACK",
                thin_detail,
                "docs/data/operating_decline_gate.json names[].verdict",
            )
        )
    if earnings_fallback_used:
        reasons.append(
            _reason(
                "SCREEN_EARNINGS_GROWTH_FALLBACK",
                (
                    f"{earnings_breadth_sources['screen_earnings_growth']} of {total} members "
                    "used Yahoo quarterly earnings_growth because the decline store had no "
                    "usable verdict for them."
                ),
                "docs/data/library/markets/<market>/screen/latest_signals.csv earnings_growth",
            )
        )

    if price_trigger or earnings_trigger:
        verdict = "headwind"
    elif not missing_core:
        verdict = "sound"
        if earnings_component == "operating_decline_store":
            earnings_source = "docs/data/operating_decline_gate.json names[].verdict"
        elif earnings_component == "screen_earnings_growth_fallback":
            earnings_source = (
                "docs/data/library/markets/<market>/screen/latest_signals.csv earnings_growth"
            )
        else:
            earnings_source = "docs/data/latest.json reports[] earnings breadth fields"
        reasons.insert(
            0,
            _reason(
                "NO_BROAD_HEADWIND",
                (
                    "Price breadth/trend and the selected earnings/operating breadth "
                    "stay below headwind thresholds."
                ),
                f"docs/data/charts/{{TICKER}}.json; {earnings_source}",
            ),
        )
    else:
        verdict = "insufficient_data"

    return {
        "verdict": verdict,
        "reasons": reasons,
        "metrics": {
            "member_count": total,
            "as_of": cutoff.isoformat(),
            "price_below_sma200_count": below_sma,
            "price_member_count": price_count,
            "price_coverage_share": round(price_coverage, 6),
            "price_below_sma200_share": (
                round(price_breadth, 6) if price_breadth is not None else None
            ),
            "sector_return_63d": round(return_63d, 6) if return_63d is not None else None,
            "sector_return_63d_member_count": return_63d_count,
            "sector_return_126d": round(return_126d, 6) if return_126d is not None else None,
            "sector_return_126d_member_count": return_126d_count,
            "sector_drawdown_from_1y_high": (
                round(drawdown_1y, 6) if drawdown_1y is not None else None
            ),
            "sector_drawdown_member_count": drawdown_count,
            "sector_drawdown_lookback_trading_days": drawdown_days,
            "earnings_declining_count": earnings_declining,
            "earnings_member_count": earnings_count,
            "earnings_coverage_share": round(earnings_coverage, 6),
            "earnings_component": earnings_component,
            "earnings_declining_share": (
                round(earnings_breadth, 6) if earnings_breadth is not None else None
            ),
            "earnings_fields_used": sorted(earnings_fields),
            "operating_declining_count": decline_declining,
            "operating_decline_member_count": decline_count,
            "operating_decline_coverage_share": round(decline_coverage, 6),
            "operating_declining_share": (
                round(decline_breadth, 6) if decline_breadth is not None else None
            ),
            "fund_or_trust_member_count": len(fund_tickers),
            "operating_decline_store_present": decline_names is not None,
            "operating_decline_component_available": decline_available,
            "earnings_breadth_sources": earnings_breadth_sources,
            "earnings_fallback_used": earnings_fallback_used,
            "thresholds": thresholds,
        },
    }


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _load_chart_cache(
    charts_dir: Path,
    tickers: list[str],
    cache: dict[str, dict[str, Any] | None],
) -> dict[str, dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = {}
    for ticker in tickers:
        if ticker not in cache:
            chart_path = Path(charts_dir) / f"{ticker}.json"
            chart: dict[str, Any] | None = None
            if chart_path.is_file():
                try:
                    payload = _read_json(chart_path)
                    chart = payload if isinstance(payload, dict) else None
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    chart = None
            cache[ticker] = chart
        cached = cache[ticker]
        if isinstance(cached, dict):
            loaded[ticker] = cached
    return loaded


def _dedupe_members(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        ticker = str(row.get("ticker") or "").strip()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        unique.append(row)
    return unique


def _earnings_input_census(members: list[dict[str, Any]]) -> dict[str, Any]:
    """Which v0 earnings-breadth fields this membership file actually carries."""
    present = {
        field: sum(1 for row in members if _finite_float(row.get(field)) is not None)
        for field in SCREEN_EARNINGS_FIELDS
    }
    return {
        "v0_screen_fields": {field: count for field, count in present.items() if count},
        "earnings_growth_names": sum(
            1 for row in members if _finite_float(row.get("earnings_growth")) is not None
        ),
        "earnings_growth_used": False,
    }


def _insufficient_reasons(assessed: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for row in assessed.get("reasons") or []:
        if not isinstance(row, dict):
            continue
        code = row.get("code")
        detail = str(row.get("detail") or "")
        if code == "TOO_FEW_SECTOR_MEMBERS":
            reasons.append("too few members")
        elif code == "INSUFFICIENT_CORE_COVERAGE":
            if "price breadth" in detail:
                reasons.append("chart coverage")
            if "126d sector trend" in detail:
                reasons.append("chart history")
            if "earnings breadth" in detail:
                reasons.append("earnings breadth")
    return reasons


def _decision_date(
    screen_date: date,
    explicit_as_of: Any,
    decline_payload: dict[str, Any] | None,
) -> date:
    """Decision date for one market.

    An explicit ``as_of`` is the cutoff. Otherwise the date is the screen date,
    moved forward to the decline snapshot when that snapshot is newer, so the
    daily refresh can use the decline verdicts just written and still ignore
    chart bars after the decision date.
    """
    if explicit_as_of is not None:
        return _as_of_date(explicit_as_of)
    cutoff = screen_date
    if isinstance(decline_payload, dict) and decline_payload.get("as_of") is not None:
        try:
            decline_day = _as_of_date(decline_payload.get("as_of"))
        except (TypeError, ValueError):
            decline_day = None
        if decline_day is not None and decline_day > cutoff:
            cutoff = decline_day
    return cutoff


def _read_signal_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle) if isinstance(row, dict)]


def _screen_date_from_market(market_dir: Path) -> date | None:
    summary_path = market_dir / "screen" / "latest_summary.json"
    if summary_path.is_file():
        try:
            summary = _read_json(summary_path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            summary = {}
        if isinstance(summary, dict):
            for key in ("run_at", "generated_at", "as_of"):
                if summary.get(key):
                    try:
                        return _as_of_date(summary[key])
                    except (TypeError, ValueError):
                        continue
    history = market_dir / "screen" / "history"
    runs = sorted(history.glob("run_*.json.gz")) if history.is_dir() else []
    if not runs:
        return None
    try:
        with gzip.open(runs[-1], "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict) and payload.get("run_at"):
        try:
            return _as_of_date(payload["run_at"])
        except (TypeError, ValueError):
            return None
    return None


def _graduated_library_markets(status: dict[str, Any]) -> tuple[list[str], list[dict[str, str]]]:
    graduated: list[str] = []
    skipped: list[dict[str, str]] = []
    markets = status.get("markets")
    if not isinstance(markets, list):
        return graduated, skipped
    for row in markets:
        if not isinstance(row, dict):
            continue
        market_id = str(row.get("market_id") or "").strip()
        if not market_id or market_id == FTSE_MARKET:
            continue
        if row.get("is_graduated") is True:
            graduated.append(market_id)
        else:
            skipped.append({"market": market_id, "reason": "not_graduated"})
    return graduated, skipped


def _name_entry(
    *,
    market: str,
    sector: str,
    verdict: str,
    screen_date: str,
    earnings_fallback_used: bool,
    sector_key: str,
) -> dict[str, Any]:
    return {
        "market": market,
        "sector": sector,
        "sector_verdict": verdict,
        "sector_basis": "own_market",
        "own_market_verdict": verdict,
        "screen_date": screen_date,
        "earnings_fallback_used": earnings_fallback_used,
        "deciding_sector_key": sector_key,
    }


def _project_market(
    *,
    market: str,
    members: list[dict[str, Any]],
    charts: dict[str, dict[str, Any]],
    decline_payload: dict[str, Any] | None,
    cutoff: date,
    screen_date: date,
    earnings_growth_fallback: bool = False,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, Any],
    list[dict[str, str]],
    dict[str, list[dict[str, Any]]],
]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    missing_sector_buy: list[str] = []
    for row in _dedupe_members(members):
        ticker = str(row.get("ticker") or "").strip()
        sector = str(row.get("sector") or "").strip()
        if not sector:
            if str(row.get("signal") or "").lower() in BUY_TIER_SIGNALS:
                missing_sector_buy.append(ticker)
            continue
        grouped[sector].append(row)

    sectors: dict[str, dict[str, Any]] = {}
    names: dict[str, dict[str, Any]] = {}
    label_rows: list[dict[str, str]] = []
    buy_insufficient: list[dict[str, Any]] = []
    screen_iso = screen_date.isoformat()
    cutoff_iso = cutoff.isoformat()
    growth_allowed = earnings_growth_fallback and screen_date <= cutoff
    for sector in sorted(grouped):
        sector_members = grouped[sector]
        sector_tickers = [str(row.get("ticker") or "").strip() for row in sector_members]
        assessed = assess_sector(
            sector_members,
            charts=charts,
            decline_verdicts=decline_payload,
            as_of=cutoff,
            earnings_growth_fallback=earnings_growth_fallback,
            earnings_growth_tickers=(
                frozenset(ticker for ticker in sector_tickers if ticker)
                if growth_allowed
                else frozenset()
            ),
        )
        key = f"{market}:{sector}"
        tickers = sorted(ticker for ticker in sector_tickers if ticker)
        buy_tier = sorted(
            str(row["ticker"]).strip()
            for row in sector_members
            if str(row.get("signal") or "").lower() in BUY_TIER_SIGNALS
        )
        fallback_used = bool(assessed.get("metrics", {}).get("earnings_fallback_used"))
        sectors[key] = {
            "market": market,
            "sector": sector,
            "screen_date": screen_iso,
            "scope": "own_market",
            "earnings_fallback_used": fallback_used,
            **assessed,
            "members": tickers,
            "buy_tier_members": buy_tier,
        }
        why = _insufficient_reasons(assessed) if assessed["verdict"] == "insufficient_data" else []
        if assessed["verdict"] == "insufficient_data":
            buy_insufficient.extend(
                {
                    "ticker": ticker,
                    "sector": sector,
                    "reasons": why,
                    "sector_basis": "own_market",
                }
                for ticker in buy_tier
            )
        for ticker in tickers:
            names[ticker] = _name_entry(
                market=market,
                sector=sector,
                verdict=assessed["verdict"],
                screen_date=screen_iso,
                earnings_fallback_used=fallback_used,
                sector_key=key,
            )
            label_rows.append(
                {
                    "market": market,
                    "ticker": ticker,
                    "sector": sector,
                    "screen_date": screen_iso,
                    "as_of": cutoff_iso,
                }
            )

    buy_by_verdict = {
        verdict: sum(
            len(row["buy_tier_members"]) for row in sectors.values() if row["verdict"] == verdict
        )
        for verdict in ("sound", "headwind", "insufficient_data")
    }
    verdict_counts = {
        verdict: sum(1 for row in sectors.values() if row["verdict"] == verdict)
        for verdict in ("sound", "headwind", "insufficient_data")
    }
    unique_members = _dedupe_members(members)
    member_count = len(unique_members)
    chart_count = sum(1 for row in unique_members if str(row.get("ticker") or "").strip() in charts)
    market_summary = {
        "sectors": len(sectors),
        **verdict_counts,
        "members": member_count,
        "buy_tier_names": sum(buy_by_verdict.values()),
        "buy_tier_by_verdict": buy_by_verdict,
        "buy_tier_in_headwind_sector": buy_by_verdict["headwind"],
        "buy_tier_in_insufficient_data_sector": buy_by_verdict["insufficient_data"],
        "buy_tier_sectors": sum(1 for row in sectors.values() if row["buy_tier_members"]),
        "buy_tier_sectors_insufficient_data": sum(
            1
            for row in sectors.values()
            if row["buy_tier_members"] and row["verdict"] == "insufficient_data"
        ),
        "buy_tier_insufficient_data": buy_insufficient,
        "buy_tier_missing_sector": sorted(missing_sector_buy),
        "names_with_chart_file": chart_count,
        "chart_file_coverage_share": (
            round(chart_count / member_count, 6) if member_count else 0.0
        ),
        "screen_date": screen_iso,
        "as_of": cutoff_iso,
        "earnings_inputs": _earnings_input_census(members),
    }
    if any(bool(row.get("earnings_fallback_used")) for row in sectors.values()):
        market_summary["earnings_inputs"]["earnings_growth_used"] = True
    return sectors, names, market_summary, label_rows, grouped


def _last_recorded_labels(path: Path) -> dict[tuple[str, str], str]:
    last: dict[tuple[str, str], str] = {}
    if not path.is_file():
        return last
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            market = str(row.get("market") or "")
            ticker = str(row.get("ticker") or "")
            sector = row.get("sector")
            if market and ticker and isinstance(sector, str):
                last[(market, ticker)] = sector
    return last


def append_sector_labels(path: Path, rows: list[dict[str, str]]) -> int:
    """Append a row only when a (market, ticker) sector label is new or changed."""
    last = _last_recorded_labels(path)
    fresh: list[dict[str, str]] = []
    for row in rows:
        key = (row["market"], row["ticker"])
        if last.get(key) == row["sector"]:
            continue
        fresh.append(row)
        last[key] = row["sector"]
    if not fresh:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in fresh:
            handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
    return len(fresh)


def sector_label_as_of(
    market: str,
    ticker: str,
    on: Any,
    *,
    path: Path = DEFAULT_LABEL_HISTORY,
) -> str | None:
    """Sector label in force on ``on``: the latest row whose ``as_of`` is on or before it."""
    cutoff = _as_of_date(on)
    chosen: str | None = None
    chosen_day: date | None = None
    chosen_index = -1
    history = Path(path)
    if not history.is_file():
        return None
    with history.open(encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            if str(row.get("market") or "") != market or str(row.get("ticker") or "") != ticker:
                continue
            sector = row.get("sector")
            if not isinstance(sector, str):
                continue
            try:
                day = _as_of_date(row.get("as_of"))
            except (TypeError, ValueError):
                continue
            if day > cutoff:
                continue
            if (
                chosen_day is None
                or day > chosen_day
                or (day == chosen_day and index >= chosen_index)
            ):
                chosen = sector
                chosen_day = day
                chosen_index = index
    return chosen


def _is_member_count_failure(assessed: dict[str, Any]) -> bool:
    """True only for the member-count rule, not chart or breadth coverage."""
    if assessed.get("verdict") != "insufficient_data":
        return False
    return any(
        isinstance(row, dict) and row.get("code") == "TOO_FEW_SECTOR_MEMBERS"
        for row in assessed.get("reasons") or []
    )


def _verdict_grid() -> dict[str, int]:
    return {verdict: 0 for verdict in VERDICTS}


def _sum_grids(
    rows: list[dict[str, Any]],
    key: str,
    outer_keys: tuple[str, ...],
) -> dict[str, dict[str, int]]:
    total = {outer: _verdict_grid() for outer in outer_keys}
    for row in rows:
        part = row.get(key) if isinstance(row.get(key), dict) else {}
        for outer in outer_keys:
            src = part.get(outer) if isinstance(part.get(outer), dict) else {}
            for verdict in VERDICTS:
                total[outer][verdict] += int(src.get(verdict) or 0)
    return total


def _recompute_buy_tier_summary(
    summary: dict[str, Any],
    names: dict[str, dict[str, Any]],
    own_sectors: dict[str, dict[str, Any]],
    regional_sectors: dict[str, dict[str, Any]],
) -> None:
    """Recount buy-tier names from the verdict in force."""
    buy_by_verdict = _verdict_grid()
    by_basis = {"own_market": _verdict_grid(), "regional": _verdict_grid()}
    by_fallback = {"used": _verdict_grid(), "not_used": _verdict_grid()}
    insufficient: list[dict[str, Any]] = []
    for row in own_sectors.values():
        sector = str(row.get("sector") or "")
        for ticker in row.get("buy_tier_members") or []:
            name = names.get(str(ticker))
            if not isinstance(name, dict):
                continue
            verdict = str(name.get("sector_verdict") or "")
            if verdict not in buy_by_verdict:
                continue
            buy_by_verdict[verdict] += 1
            basis = str(name.get("sector_basis") or "own_market")
            if basis not in by_basis:
                basis = "own_market"
            by_basis[basis][verdict] += 1
            fallback_key = "used" if name.get("earnings_fallback_used") else "not_used"
            by_fallback[fallback_key][verdict] += 1
            if verdict != "insufficient_data":
                continue
            if basis == "regional":
                source = regional_sectors.get(str(name.get("deciding_sector_key") or ""), row)
            else:
                source = row
            insufficient.append(
                {
                    "ticker": ticker,
                    "sector": sector,
                    "reasons": _insufficient_reasons(source if isinstance(source, dict) else row),
                    "sector_basis": basis,
                }
            )
    summary["buy_tier_by_verdict"] = buy_by_verdict
    summary["buy_tier_in_headwind_sector"] = buy_by_verdict["headwind"]
    summary["buy_tier_in_insufficient_data_sector"] = buy_by_verdict["insufficient_data"]
    summary["buy_tier_by_basis"] = by_basis
    summary["buy_tier_by_earnings_fallback"] = by_fallback
    summary["buy_tier_insufficient_data"] = insufficient
    if any(bool(name.get("earnings_fallback_used")) for name in names.values()):
        earnings_inputs = summary.get("earnings_inputs")
        if isinstance(earnings_inputs, dict):
            earnings_inputs["earnings_growth_used"] = True


def _charts_for(
    tickers: set[str],
    chart_cache: dict[str, dict[str, Any] | None],
) -> dict[str, dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = {}
    for ticker in tickers:
        cached = chart_cache.get(ticker)
        if isinstance(cached, dict):
            loaded[ticker] = cached
    return loaded


def _apply_regional_fallbacks(
    states: dict[str, dict[str, Any]],
    *,
    decline_payload: dict[str, Any] | None,
    chart_cache: dict[str, dict[str, Any] | None],
) -> dict[str, dict[str, Any]]:
    """Rescore sectors that failed only the member-count rule across a region.

    Own-market sector rows stay as scored. Name rows whose own market was too
    small take the regional verdict as the verdict in force. A market outside
    ``REGIONAL_GROUPS`` is left on its own-market verdict. A market that was
    not scored (not graduated, or not the live FTSE 350) contributes no members.
    """
    needed: set[tuple[str, str]] = set()
    for market, state in states.items():
        region = REGION_BY_MARKET.get(market)
        if region is None:
            continue
        for row in state["sectors"].values():
            label = str(row.get("sector") or "")
            if label and _is_member_count_failure(row):
                needed.add((region, label))

    regional: dict[str, dict[str, Any]] = {}
    for region, label in sorted(needed):
        contributors = [
            market
            for market in REGIONAL_GROUPS[region]
            if market in states and label in states[market]["grouped"]
        ]
        if not contributors:
            continue
        cutoff = min(states[market]["cutoff"] for market in contributors)
        pooled: list[dict[str, Any]] = []
        seen: set[str] = set()
        growth_tickers: set[str] = set()
        member_count_by_market: dict[str, int] = {}
        for market in contributors:
            allow_growth = market != FTSE_MARKET and states[market]["screen_date"] <= cutoff
            rows = states[market]["grouped"][label]
            member_count_by_market[market] = len(rows)
            for row in rows:
                ticker = str(row.get("ticker") or "").strip()
                if not ticker or ticker in seen:
                    continue
                seen.add(ticker)
                pooled.append(row)
                if allow_growth:
                    growth_tickers.add(ticker)
        assessed = assess_sector(
            pooled,
            charts=_charts_for(seen, chart_cache),
            decline_verdicts=decline_payload,
            as_of=cutoff,
            earnings_growth_fallback=True,
            earnings_growth_tickers=frozenset(growth_tickers),
        )
        key = f"region:{region}:{label}"
        metrics = assessed.get("metrics") if isinstance(assessed.get("metrics"), dict) else {}
        fallback_used = bool(metrics.get("earnings_fallback_used"))
        governed_buy: list[str] = []
        governed_markets: list[str] = []
        for market in contributors:
            own = states[market]["sectors"].get(f"{market}:{label}")
            if not isinstance(own, dict) or not _is_member_count_failure(own):
                continue
            governed_markets.append(market)
            for ticker in own.get("buy_tier_members") or []:
                if ticker not in governed_buy:
                    governed_buy.append(str(ticker))
            for name in states[market]["names"].values():
                if name.get("sector") != label:
                    continue
                name["sector_verdict"] = assessed["verdict"]
                name["sector_basis"] = "regional"
                name["region"] = region
                name["earnings_fallback_used"] = fallback_used
                name["deciding_sector_key"] = key
        regional[key] = {
            "scope": "regional",
            "region": region,
            "sector": label,
            "market": None,
            "contributing_markets": contributors,
            "governed_markets": governed_markets,
            "member_count_by_market": member_count_by_market,
            "screen_dates": {
                market: states[market]["screen_date"].isoformat() for market in contributors
            },
            "earnings_fallback_used": fallback_used,
            **assessed,
            "members": sorted(seen),
            "buy_tier_members": sorted(governed_buy),
        }

    for state in states.values():
        _recompute_buy_tier_summary(
            state["summary"],
            state["names"],
            state["sectors"],
            regional,
        )
    return regional


def _mostly_insufficient_library_markets(sectors: dict[str, Any]) -> list[str]:
    counts: dict[str, list[int]] = {}
    for key, row in sectors.items():
        if str(key).startswith("region:"):
            continue
        if not isinstance(row, dict) or row.get("scope") == "regional":
            continue
        if not row.get("buy_tier_members"):
            continue
        market = str(row.get("market") or FTSE_MARKET)
        if market == FTSE_MARKET:
            continue
        bucket = counts.setdefault(market, [0, 0])
        bucket[0] += 1
        if row.get("verdict") == "insufficient_data":
            bucket[1] += 1
    named: list[str] = []
    for market in sorted(counts):
        buy_sectors, insufficient = counts[market]
        if buy_sectors and insufficient * 2 > buy_sectors:
            named.append(f"{market} ({insufficient}/{buy_sectors})")
    return named


def _load_decline_payload(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = _read_json(path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _overall_summary(
    by_market: dict[str, dict[str, Any]],
    *,
    decline_available: bool,
    regional_sectors: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    verdicts = ("sound", "headwind", "insufficient_data")
    totals = {verdict: 0 for verdict in verdicts}
    sectors = 0
    buy_tier_names = 0
    buy_tier_in_headwind = 0
    buy_tier_sectors = 0
    buy_tier_sectors_insufficient = 0
    report_names = 0
    charts = 0
    for row in by_market.values():
        sectors += int(row.get("sectors") or 0)
        for verdict in verdicts:
            totals[verdict] += int(row.get(verdict) or 0)
        buy_tier_names += int(row.get("buy_tier_names") or 0)
        buy_tier_in_headwind += int(row.get("buy_tier_in_headwind_sector") or 0)
        buy_tier_sectors += int(row.get("buy_tier_sectors") or 0)
        buy_tier_sectors_insufficient += int(row.get("buy_tier_sectors_insufficient_data") or 0)
        report_names += int(row.get("members") or 0)
        charts += int(row.get("names_with_chart_file") or 0)
    return {
        "markets": len(by_market),
        "sectors": sectors,
        **totals,
        "buy_tier_names": buy_tier_names,
        "buy_tier_in_headwind_sector": buy_tier_in_headwind,
        "buy_tier_in_insufficient_data_sector": sum(
            int(row.get("buy_tier_in_insufficient_data_sector") or 0) for row in by_market.values()
        ),
        "buy_tier_sectors": buy_tier_sectors,
        "buy_tier_sectors_insufficient_data": buy_tier_sectors_insufficient,
        "report_names": report_names,
        "names_with_chart_file": charts,
        "chart_file_coverage_share": round(charts / report_names, 6) if report_names else 0.0,
        "operating_decline_store_available": decline_available,
        "buy_tier_by_basis": _sum_grids(
            list(by_market.values()),
            "buy_tier_by_basis",
            ("own_market", "regional"),
        ),
        "buy_tier_by_earnings_fallback": _sum_grids(
            list(by_market.values()),
            "buy_tier_by_earnings_fallback",
            ("used", "not_used"),
        ),
        "regional_sectors": len(regional_sectors or {}),
        "regional_by_verdict": {
            verdict: sum(
                1 for row in (regional_sectors or {}).values() if row.get("verdict") == verdict
            )
            for verdict in VERDICTS
        },
        "by_market": by_market,
    }


def refresh_sector_headwind_gate(
    *,
    latest_path: Path = DEFAULT_LATEST_PATH,
    charts_dir: Path = DEFAULT_CHARTS_DIR,
    decline_store: Path = DEFAULT_DECLINE_STORE,
    store_path: Path = DEFAULT_STORE_PATH,
    market_status_path: Path = DEFAULT_MARKET_STATUS,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    label_history_path: Path = DEFAULT_LABEL_HISTORY,
    persist: bool = True,
    as_of: Any = None,
) -> dict[str, Any]:
    """Refresh FTSE 350 and graduated library sectors from point-in-time inputs.

    Library markets come from ``is_graduated`` on the market-status file. Each
    market is scored on its own membership first. A sector that is
    ``insufficient_data`` only because it has fewer than four members is
    rescored across its frozen region. The flat ``names`` map stays the FTSE
    projection, with the verdict in force. ``names_by_market`` holds one
    verdict per (market, ticker).
    """
    latest = _read_json(Path(latest_path))
    reports = latest.get("reports")
    if not isinstance(reports, list):
        raise ValueError(f"{latest_path} has no reports list")
    ftse_members = [row for row in reports if isinstance(row, dict) and row.get("ticker")]
    screen_raw = latest.get("run_at") or latest.get("generated_at")
    ftse_screen = _as_of_date(screen_raw)
    decline_payload = _load_decline_payload(Path(decline_store))
    ftse_cutoff = _decision_date(ftse_screen, as_of, decline_payload)

    chart_cache: dict[str, dict[str, Any] | None] = {}
    ftse_charts = _load_chart_cache(
        Path(charts_dir),
        [str(row.get("ticker") or "").strip() for row in ftse_members],
        chart_cache,
    )
    ftse_sectors, ftse_names, ftse_summary, label_rows, ftse_grouped = _project_market(
        market=FTSE_MARKET,
        members=ftse_members,
        charts=ftse_charts,
        decline_payload=decline_payload,
        cutoff=ftse_cutoff,
        screen_date=ftse_screen,
    )
    sectors: dict[str, dict[str, Any]] = dict(ftse_sectors)
    by_market = {FTSE_MARKET: ftse_summary}
    names_by_market = {FTSE_MARKET: ftse_names}
    states: dict[str, dict[str, Any]] = {
        FTSE_MARKET: {
            "grouped": ftse_grouped,
            "sectors": ftse_sectors,
            "names": ftse_names,
            "summary": ftse_summary,
            "cutoff": ftse_cutoff,
            "screen_date": ftse_screen,
        }
    }
    scored_library: list[str] = []
    not_scored: list[dict[str, str]] = []

    status_path = Path(market_status_path)
    if status_path.is_file():
        try:
            status = _read_json(status_path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            status = {}
            not_scored.append({"market": "*", "reason": "market_status_unreadable"})
        graduated, skipped = _graduated_library_markets(status if isinstance(status, dict) else {})
        not_scored.extend(skipped)
        root = Path(library_root)
        for market in dict.fromkeys(graduated):
            market_dir = root / "markets" / market
            signals = market_dir / "screen" / "latest_signals.csv"
            if not signals.is_file():
                not_scored.append({"market": market, "reason": "missing_screen"})
                continue
            screen_date = _screen_date_from_market(market_dir)
            if screen_date is None:
                not_scored.append({"market": market, "reason": "missing_screen_date"})
                continue
            try:
                library_members = _read_signal_rows(signals)
            except (OSError, UnicodeDecodeError, csv.Error):
                not_scored.append({"market": market, "reason": "unreadable_screen"})
                continue
            cutoff = _decision_date(screen_date, as_of, decline_payload)
            library_charts = _load_chart_cache(
                Path(charts_dir),
                [str(row.get("ticker") or "").strip() for row in library_members],
                chart_cache,
            )
            market_sectors, market_names, market_summary, market_labels, grouped = _project_market(
                market=market,
                members=library_members,
                charts=library_charts,
                decline_payload=decline_payload,
                cutoff=cutoff,
                screen_date=screen_date,
                earnings_growth_fallback=True,
            )
            sectors.update(market_sectors)
            names_by_market[market] = market_names
            by_market[market] = market_summary
            label_rows.extend(market_labels)
            scored_library.append(market)
            states[market] = {
                "grouped": grouped,
                "sectors": market_sectors,
                "names": market_names,
                "summary": market_summary,
                "cutoff": cutoff,
                "screen_date": screen_date,
            }
    else:
        not_scored.append({"market": "*", "reason": "market_status_missing"})

    regional_sectors = _apply_regional_fallbacks(
        states,
        decline_payload=decline_payload,
        chart_cache=chart_cache,
    )
    sectors.update(regional_sectors)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "as_of": ftse_cutoff.isoformat(),
        "observe_only": True,
        "influences_live": False,
        "strategy_part": "3. Sector sound",
        "universe": {
            "included": [FTSE_MARKET, *scored_library],
            "admitted_library_markets": scored_library,
            "not_scored": not_scored,
            "regional_groups": {
                region: list(markets) for region, markets in REGIONAL_GROUPS.items()
            },
        },
        "summary": _overall_summary(
            by_market,
            decline_available=decline_payload is not None,
            regional_sectors=regional_sectors,
        ),
        "sectors": sectors,
        "names": ftse_names,
        "names_by_market": names_by_market,
    }
    if persist:
        path = Path(store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        append_sector_labels(Path(label_history_path), label_rows)
    return payload


def _is_own_market_sector(key: str, row: dict[str, Any]) -> bool:
    if str(key).startswith("region:") or row.get("scope") == "regional":
        return False
    return True


def _grid_text(grid: Any) -> str:
    if not isinstance(grid, dict):
        return "none"
    parts: list[str] = []
    for key, counts in grid.items():
        if not isinstance(counts, dict):
            continue
        parts.append(
            f"{key} sound={int(counts.get('sound') or 0)} "
            f"headwind={int(counts.get('headwind') or 0)} "
            f"insufficient_data={int(counts.get('insufficient_data') or 0)}"
        )
    return "; ".join(parts) or "none"


def _headwind_label(key: str, row: dict[str, Any]) -> str:
    market = str(row.get("market") or "")
    sector = str(row.get("sector") or key)
    if market and market != FTSE_MARKET:
        return f"{market}:{sector}"
    return sector


def ops_findings_from_sector_headwind_gate(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Map the observe store to non-auto-fixable ops-monitor findings."""
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    sectors = payload.get("sectors") if isinstance(payload.get("sectors"), dict) else {}
    ftse_headwinds = sorted(
        _headwind_label(key, row)
        for key, row in sectors.items()
        if isinstance(row, dict)
        and _is_own_market_sector(key, row)
        and row.get("verdict") == "headwind"
        and str(row.get("market") or FTSE_MARKET) == FTSE_MARKET
    )
    library_headwinds = sorted(
        _headwind_label(key, row)
        for key, row in sectors.items()
        if isinstance(row, dict)
        and _is_own_market_sector(key, row)
        and row.get("verdict") == "headwind"
        and str(row.get("market") or "") not in {"", FTSE_MARKET}
    )
    named_headwinds = ftse_headwinds + library_headwinds[:12]
    extra_headwinds = max(0, len(library_headwinds) - 12)
    headwind_text = ", ".join(named_headwinds) or "none"
    if extra_headwinds:
        headwind_text += f", and {extra_headwinds} more library sectors"
    findings = [
        {
            "severity": "info",
            "category": "research",
            "title": FINDING_TITLE,
            "summary": (
                f"{summary.get('markets', 1)} markets, {summary.get('sectors', 0)} sectors: "
                f"sound={summary.get('sound', 0)}, "
                f"headwind={summary.get('headwind', 0)}, "
                f"insufficient_data={summary.get('insufficient_data', 0)}; "
                f"headwind sectors={headwind_text}; "
                f"buy-tier names in headwind sectors="
                f"{summary.get('buy_tier_in_headwind_sector', 0)}. "
                "Observe-only; influences_live=false; no book or knob edits."
            ),
            "auto_fixable": False,
        }
    ]
    gaps = sorted(
        str(row.get("sector") or key)
        for key, row in sectors.items()
        if isinstance(row, dict)
        and _is_own_market_sector(key, row)
        and row.get("verdict") == "insufficient_data"
        and row.get("buy_tier_members")
        and str(row.get("market") or FTSE_MARKET) == FTSE_MARKET
    )
    mostly = _mostly_insufficient_library_markets(sectors)
    if gaps or mostly:
        parts: list[str] = []
        if gaps:
            parts.append(
                "Buy-tier sectors lack enough point-in-time gate data: " + ", ".join(gaps) + "."
            )
        if mostly:
            parts.append(
                "Library markets whose buy-tier sectors are mostly insufficient_data: "
                + ", ".join(mostly)
                + "."
            )
        parts.append(
            "Fail closed; observe-only; no automated ingest, book, signal, or knob action."
        )
        findings.append(
            {
                "severity": "warn",
                "category": "research",
                "title": COVERAGE_GAP_TITLE,
                "summary": " ".join(parts),
                "auto_fixable": False,
            }
        )
    findings.append(
        {
            "severity": "info",
            "category": "research",
            "title": FALLBACK_FINDING_TITLE,
            "summary": (
                "Buy-tier names by sector basis: "
                + _grid_text(summary.get("buy_tier_by_basis"))
                + ". Buy-tier names by earnings fallback: "
                + _grid_text(summary.get("buy_tier_by_earnings_fallback"))
                + ". Signal-risk labels for the strategy book; observe-only; "
                "influences_live=false; no rememo, ingest, or fetch."
            ),
            "auto_fixable": False,
        }
    )
    return findings
