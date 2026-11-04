"""Observe-only sector headwind gate for strategy part 3, "Sector sound"."""

from __future__ import annotations

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

FINDING_TITLE = "Sector headwind gate refreshed (observe)"
COVERAGE_GAP_TITLE = "Sector headwind gate coverage gap"
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


def _decline_names(decline_verdicts: dict[str, Any] | None) -> dict[str, Any] | None:
    if decline_verdicts is None:
        return None
    names = decline_verdicts.get("names")
    if isinstance(names, dict):
        return names
    return decline_verdicts


def _reason(code: str, detail: str, source: str) -> dict[str, str]:
    return {"code": code, "detail": detail, "source": source}


def assess_sector(
    members: list[dict[str, Any]],
    *,
    charts: dict[str, dict[str, Any]],
    decline_verdicts: dict[str, Any] | None,
    as_of: Any,
) -> dict[str, Any]:
    """Return a point-in-time sector verdict without using bars after ``as_of``."""
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

    decline_names = _decline_names(decline_verdicts)
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
    decline_coverage = decline_count / total
    decline_available = decline_names is not None and _coverage_ok(decline_count, total)

    earnings_count = 0
    earnings_declining = 0
    earnings_fields: set[str] = set()
    earnings_breadth: float | None = None
    earnings_coverage = 0.0
    earnings_available = False
    if decline_available:
        earnings_component = "operating_decline_store"
        earnings_count = decline_count
        earnings_declining = decline_declining
        earnings_breadth = decline_breadth
        earnings_coverage = decline_coverage
        earnings_available = True
    else:
        for member in members:
            declining, fields = _earnings_decline(member)
            if declining is None:
                continue
            earnings_count += 1
            earnings_declining += int(declining)
            earnings_fields.update(fields)
        earnings_breadth = earnings_declining / earnings_count if earnings_count else None
        earnings_coverage = earnings_count / total
        earnings_available = _coverage_ok(earnings_count, total)
        earnings_component = "screen_fields_fallback" if earnings_available else "unavailable"

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
        reasons.append(
            _reason(
                "OPERATING_DECLINE_STORE_THIN_FALLBACK",
                (
                    f"Operating-decline coverage was {decline_count}/{total}; "
                    "material screen fields were the fallback."
                ),
                "docs/data/operating_decline_gate.json names[].verdict",
            )
        )

    if price_trigger or earnings_trigger:
        verdict = "headwind"
    elif not missing_core:
        verdict = "sound"
        earnings_source = (
            "docs/data/operating_decline_gate.json names[].verdict"
            if earnings_component == "operating_decline_store"
            else "docs/data/latest.json reports[] earnings breadth fields"
        )
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
            "operating_decline_store_present": decline_names is not None,
            "operating_decline_component_available": decline_available,
            "thresholds": thresholds,
        },
    }


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def refresh_sector_headwind_gate(
    *,
    latest_path: Path = DEFAULT_LATEST_PATH,
    charts_dir: Path = DEFAULT_CHARTS_DIR,
    decline_store: Path = DEFAULT_DECLINE_STORE,
    store_path: Path = DEFAULT_STORE_PATH,
    persist: bool = True,
    as_of: Any = None,
) -> dict[str, Any]:
    """Refresh the FTSE 350 sector store from committed, point-in-time inputs."""
    latest = _read_json(Path(latest_path))
    reports = latest.get("reports")
    if not isinstance(reports, list):
        raise ValueError(f"{latest_path} has no reports list")
    members = [row for row in reports if isinstance(row, dict) and row.get("ticker")]
    cutoff_value = (
        as_of if as_of is not None else latest.get("run_at") or latest.get("generated_at")
    )
    cutoff = _as_of_date(cutoff_value)

    charts: dict[str, dict[str, Any]] = {}
    for row in members:
        ticker = str(row.get("ticker") or "").strip()
        chart_path = Path(charts_dir) / f"{ticker}.json"
        if not chart_path.is_file():
            continue
        try:
            charts[ticker] = _read_json(chart_path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue

    decline_payload: dict[str, Any] | None = None
    if Path(decline_store).is_file():
        try:
            decline_payload = _read_json(Path(decline_store))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            decline_payload = None

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in members:
        sector = str(row.get("sector") or "").strip()
        if sector:
            grouped[sector].append(row)

    sectors: dict[str, dict[str, Any]] = {}
    names: dict[str, dict[str, Any]] = {}
    for sector in sorted(grouped):
        sector_members = grouped[sector]
        assessed = assess_sector(
            sector_members,
            charts=charts,
            decline_verdicts=decline_payload,
            as_of=cutoff,
        )
        key = f"ftse350:{sector}"
        tickers = sorted(str(row["ticker"]) for row in sector_members)
        buy_tier = sorted(
            str(row["ticker"])
            for row in sector_members
            if str(row.get("signal") or "").lower() in BUY_TIER_SIGNALS
        )
        sectors[key] = {
            "market": "ftse350",
            "sector": sector,
            **assessed,
            "members": tickers,
            "buy_tier_members": buy_tier,
        }
        for ticker in tickers:
            names[ticker] = {
                "market": "ftse350",
                "sector": sector,
                "sector_verdict": assessed["verdict"],
            }

    verdict_counts = {
        verdict: sum(1 for row in sectors.values() if row["verdict"] == verdict)
        for verdict in ("sound", "headwind", "insufficient_data")
    }
    buy_tier_names = sum(len(row["buy_tier_members"]) for row in sectors.values())
    buy_tier_in_headwind = sum(
        len(row["buy_tier_members"]) for row in sectors.values() if row["verdict"] == "headwind"
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "as_of": cutoff.isoformat(),
        "observe_only": True,
        "influences_live": False,
        "strategy_part": "3. Sector sound",
        "universe": {
            "included": ["ftse350"],
            "admitted_library_markets": "not_scored_v0_incomparable_earnings_inputs",
        },
        "summary": {
            "sectors": len(sectors),
            **verdict_counts,
            "buy_tier_names": buy_tier_names,
            "buy_tier_in_headwind_sector": buy_tier_in_headwind,
            "buy_tier_sectors": sum(1 for row in sectors.values() if row["buy_tier_members"]),
            "buy_tier_sectors_insufficient_data": sum(
                1
                for row in sectors.values()
                if row["buy_tier_members"] and row["verdict"] == "insufficient_data"
            ),
            "report_names": len(members),
            "names_with_chart_file": len(charts),
            "chart_file_coverage_share": round(len(charts) / len(members), 6) if members else 0.0,
            "operating_decline_store_available": decline_payload is not None,
        },
        "sectors": sectors,
        "names": names,
    }
    if persist:
        path = Path(store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def ops_findings_from_sector_headwind_gate(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Map the observe store to non-auto-fixable ops-monitor findings."""
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    sectors = payload.get("sectors") if isinstance(payload.get("sectors"), dict) else {}
    headwinds = sorted(
        row.get("sector") or key
        for key, row in sectors.items()
        if isinstance(row, dict) and row.get("verdict") == "headwind"
    )
    findings = [
        {
            "severity": "info",
            "category": "research",
            "title": FINDING_TITLE,
            "summary": (
                f"{summary.get('sectors', 0)} sectors: sound={summary.get('sound', 0)}, "
                f"headwind={summary.get('headwind', 0)}, "
                f"insufficient_data={summary.get('insufficient_data', 0)}; "
                f"headwind sectors={', '.join(headwinds) or 'none'}; "
                f"buy-tier names in headwind sectors="
                f"{summary.get('buy_tier_in_headwind_sector', 0)}. "
                "Observe-only; influences_live=false; no book or knob edits."
            ),
            "auto_fixable": False,
        }
    ]
    gaps = sorted(
        row.get("sector") or key
        for key, row in sectors.items()
        if isinstance(row, dict)
        and row.get("verdict") == "insufficient_data"
        and row.get("buy_tier_members")
    )
    if gaps:
        findings.append(
            {
                "severity": "warn",
                "category": "research",
                "title": COVERAGE_GAP_TITLE,
                "summary": (
                    "Buy-tier sectors lack enough point-in-time gate data: "
                    f"{', '.join(gaps)}. Fail closed; observe-only; no automated ingest, "
                    "book, signal, or knob action."
                ),
                "auto_fixable": False,
            }
        )
    return findings
