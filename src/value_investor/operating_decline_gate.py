"""Operating-decline gate v0 (observe-only): is a name's operating performance declining?

Strategy part 2 "not declining" (deferred N250). One verdict per name:
``clear`` / ``declining`` / ``insufficient_data``, each with cited reasons. Missing
data never passes. The same verdict is the later thesis-break trigger for a
recovery hold.

Observe-only — ``influences_live`` is false. Reads committed files only (no
network); never writes books, knobs, signals or ``decision-review --apply``.

See ``docs/ops/operating-decline-gate.md``.
"""

from __future__ import annotations

import calendar
import csv
import json
import math
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

DEFAULT_LATEST_PATH = Path("docs/data/latest.json")
DEFAULT_RESEARCH_ROOT = Path("docs/data/research")
DEFAULT_LIBRARY_ROOT = Path("docs/data/library")
DEFAULT_STORE_PATH = Path("docs/data/operating_decline_gate.json")

SCHEMA_VERSION = 3
LIVE_MARKET_ID = "ftse350"
BUY_TIER_SIGNALS = frozenset({"buy", "strong_buy"})

LEARNING_QUESTION = (
    "For each name in the FTSE 350 screen (and admitted library markets where the "
    "same inputs exist), can we produce a cited, point-in-time-safe verdict of "
    "whether operating performance is declining, with coverage of every FTSE "
    "buy-tier name?"
)

FINDING_TITLE = "Operating-decline gate refreshed (observe)"
COVERAGE_GAP_TITLE = "Operating-decline gate coverage gap"
INTERIM_COVERAGE_TITLE = "Operating-decline gate interim revenue coverage"
STORE_FAILED_TITLE = "Operating-decline gate failed"

REVENUE_DROP_PCT = 0.05
REVENUE_FLAT_TOLERANCE_PCT = 0.01
MARGIN_DROP_PP = 0.03
EPS_ANNUAL_DROP_PCT = 0.20
EPS_INTERIM_DROP_PCT = 0.10
INTERIM_REVENUE_DROP_PCT = REVENUE_DROP_PCT
INTERIM_YOY_WINDOW_DAYS = 45
INTERIM_MAX_AGE_DAYS = 460
INTERIM_PUBLICATION_LAG_DAYS = 200
FCF_SHARP_FALL_PCT = 0.50
SOFT_SIGNALS_TO_DECLINE = 2
WARNING_LOOKBACK_DAYS = 180
COVERAGE_WARN_SHARE = 0.80
# Buy-tier interim revenue, measured on the 2026-11-05 backfill at 30/65 (46%).
# The daily finding warns only if coverage falls below this share, and only once
# at least this many buy-tier names are in the store (a three-name fixture must
# not trip it).
BUY_TIER_INTERIM_REVENUE_FLOOR = 0.45
BUY_TIER_INTERIM_REVENUE_MIN_NAMES = 20
FLAGGED_NAMES_IN_FINDING = 5

REVENUE_LABELS = ("Total Revenue", "Operating Revenue")
INTERIM_REVENUE_LABELS = ("Total Revenue", "Operating Revenue", "Revenue")
OPERATING_INCOME_LABELS = ("Operating Income", "Total Operating Income As Reported", "EBIT")
EPS_LABELS = ("Diluted EPS", "Basic EPS")
FCF_LABEL = "Free Cash Flow"
OPERATING_CASHFLOW_LABEL = "Operating Cash Flow"
CAPEX_LABEL = "Capital Expenditure"
FCF_DERIVED_LABEL = f"{OPERATING_CASHFLOW_LABEL} + {CAPEX_LABEL}"

HARD_PHRASES = (
    "profit warning",
    "profits warning",
    "guidance cut",
    "cuts guidance",
    "cut guidance",
    "cuts its guidance",
    "lower guidance",
    "lowers guidance",
    "lowered guidance",
    "reduces guidance",
    "reduced guidance",
    "guidance downgrade",
    "downgrades guidance",
    "downgrades its guidance",
)
UPDATE_PHRASES = ("trading update", "trading statement")
BELOW_EXPECTATIONS_PHRASES = (
    "below expectations",
    "below market expectations",
    "below consensus",
    "behind expectations",
)
SOFT_PHRASES = ("downgrade", "impairment")
THIRD_PARTY_NEWS_SOURCE_PREFIXES = ("google_news",)

HARD_REASON_CODES = frozenset(
    {
        "revenue_decline",
        "revenue_two_year_decline",
        "interim_revenue_decline",
        "operating_margin_drop",
        "fcf_turned_negative",
        "profit_warning",
    }
)
SOFT_REASON_CODES = frozenset(
    {
        "eps_decline_annual",
        "eps_decline_interim",
        "fcf_sharp_fall",
        "dividend_cut",
        "impairment_or_downgrade",
    }
)

FINANCIAL_CHECKS = frozenset({"revenue", "operating_margin", "eps_annual", "fcf"})

SRC_FINANCIALS = "financials_annual.json"
SRC_QUARTERLY = "financials_annual.json quarterly_income"
SRC_FILING_INTERIM = "filing_interim_financials.json"
SRC_SCREEN_ROW = "latest.json reports"
SRC_FILINGS = "filings_index.json"
_HALF_YEAR_EPS_KINDS = ("diluted", "basic", "adjusted", "statutory")

_PERIOD_END_RE = re.compile(
    r"\b(?:ended|ending|to)\s+(\d{1,2})\s+([A-Za-z]+)\s+(20\d{2})\b",
    re.IGNORECASE,
)
_HIGHLIGHT_EPS_PAIRS = (
    ("adjusted_eps_pence", "adjusted_eps_pence", "prior_adjusted_eps_pence"),
    ("statutory_eps_pence", "statutory_eps_pence", "prior_statutory_eps_pence"),
)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return (value.astimezone(UTC) if value.tzinfo else value).date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _pct(value: float) -> str:
    return f"{value * 100:+.1f}%"


def _year_series(statement: Any, label: str, as_of: date) -> dict[int, float]:
    """Annual values by fiscal-year int for one row label, finite values only."""
    out: dict[int, float] = {}
    if not isinstance(statement, dict):
        return out
    for key, row in statement.items():
        try:
            year = int(str(key)[:4])
        except ValueError:
            continue
        if year > as_of.year or not isinstance(row, dict):
            continue
        value = _num(row.get(label))
        if value is not None:
            out[year] = value
    return out


def _latest_pair(
    series: dict[int, float], as_of: date
) -> tuple[tuple[int, float], tuple[int, float] | None, tuple[int, float] | None] | None:
    """Latest year, the consecutive prior year, and the year before that (when present)."""
    if not series:
        return None
    latest_year = max(series)
    age = as_of.year - latest_year
    if age > 2 or (age == 2 and as_of.month > 3):
        return None
    latest = (latest_year, series[latest_year])
    prior = (latest_year - 1, series[latest_year - 1]) if latest_year - 1 in series else None
    prior2 = (latest_year - 2, series[latest_year - 2]) if latest_year - 2 in series else None
    return latest, prior, (prior2 if prior else None)


Candidates = list[tuple[str, dict[int, float]]]


def _select_series(candidates: Candidates, as_of: date) -> tuple[str, tuple] | None:
    """One label for every compared year: first candidate holding the latest and prior year.

    The latest year is the newest year on any candidate, so a preferred label that stops
    a year early loses to a fallback label that reaches the newest year.
    """
    years = [y for _, series in candidates for y in series]
    if not years:
        return None
    latest_year = max(years)
    for label, series in candidates:
        if latest_year in series and latest_year - 1 in series:
            pair = _latest_pair(series, as_of)
            return None if pair is None else (label, pair)
    return None


def _fcf_candidates(cash_flow: Any, as_of: date) -> Candidates:
    ocf = _year_series(cash_flow, OPERATING_CASHFLOW_LABEL, as_of)
    capex = _year_series(cash_flow, CAPEX_LABEL, as_of)
    derived = {y: ocf[y] + capex[y] for y in ocf if y in capex}
    return [
        (FCF_LABEL, _year_series(cash_flow, FCF_LABEL, as_of)),
        (FCF_DERIVED_LABEL, derived),
    ]


def _label_candidates(statement: Any, labels: tuple[str, ...], as_of: date) -> Candidates:
    return [(label, _year_series(statement, label, as_of)) for label in labels]


def _not_evaluable(why: str) -> dict[str, Any]:
    return {"evaluable": False, "fired": False, "why": why}


def _check_revenue(income: Any, as_of: date, source: str) -> tuple[dict, list[dict]]:
    picked = _select_series(_label_candidates(income, REVENUE_LABELS, as_of), as_of)
    if picked is None or picked[1][1] is None:
        return _not_evaluable("revenue_missing_or_stale"), []
    label, pair = picked
    (year, latest), prior, prior2 = pair[0], pair[1], pair[2]
    if prior[1] <= 0:
        return _not_evaluable("prior_revenue_non_positive"), []
    change = latest / prior[1] - 1.0
    prior_change = None
    if prior2 is not None and prior2[1] > 0:
        prior_change = prior[1] / prior2[1] - 1.0
    reasons: list[dict] = []
    detail = f"FY{year} revenue {latest:,.0f} vs FY{prior[0]} {prior[1]:,.0f} ({_pct(change)})"
    two_year = (
        prior_change is not None
        and change < -REVENUE_FLAT_TOLERANCE_PCT
        and prior_change < -REVENUE_FLAT_TOLERANCE_PCT
    )
    if change < -REVENUE_DROP_PCT:
        reasons.append({"code": "revenue_decline", "detail": detail, "source": source})
    if two_year:
        reasons.append(
            {
                "code": "revenue_two_year_decline",
                "detail": f"{detail}; prior year {_pct(prior_change)}",
                "source": source,
            }
        )
    check = {
        "evaluable": True,
        "fired": bool(reasons),
        "strength": "hard",
        "label": label,
        "latest_year": year,
        "change_pct": round(change, 4),
        "prior_change_pct": None if prior_change is None else round(prior_change, 4),
    }
    return check, reasons


def _check_margin(income: Any, as_of: date, source: str) -> tuple[dict, list[dict]]:
    candidates: Candidates = []
    for revenue_label in REVENUE_LABELS:
        revenue = _year_series(income, revenue_label, as_of)
        for operating_label in OPERATING_INCOME_LABELS:
            operating = _year_series(income, operating_label, as_of)
            candidates.append(
                (
                    f"{operating_label} / {revenue_label}",
                    {y: operating[y] / revenue[y] for y in operating if revenue.get(y, 0.0) > 0},
                )
            )
    picked = _select_series(candidates, as_of)
    if picked is None or picked[1][1] is None:
        return _not_evaluable("operating_income_missing_or_stale"), []
    label, pair = picked
    (year, latest), prior = pair[0], pair[1]
    drop = prior[1] - latest
    reasons: list[dict] = []
    if drop > MARGIN_DROP_PP:
        reasons.append(
            {
                "code": "operating_margin_drop",
                "detail": (
                    f"FY{year} operating margin {latest * 100:.1f}% vs FY{prior[0]} "
                    f"{prior[1] * 100:.1f}% ({-drop * 100:+.1f}pp)"
                ),
                "source": source,
            }
        )
    check = {
        "evaluable": True,
        "fired": bool(reasons),
        "strength": "hard",
        "label": label,
        "latest_year": year,
        "latest_margin": round(latest, 4),
        "prior_margin": round(prior[1], 4),
        "change_pp": round(-drop, 4),
    }
    return check, reasons


def _check_eps_annual(income: Any, as_of: date, source: str) -> tuple[dict, list[dict]]:
    picked = _select_series(_label_candidates(income, EPS_LABELS, as_of), as_of)
    if picked is None or picked[1][1] is None:
        return _not_evaluable("annual_eps_missing_or_stale"), []
    label, pair = picked
    (year, latest), prior = pair[0], pair[1]
    fell = prior[1] > 0 and latest < prior[1] * (1.0 - EPS_ANNUAL_DROP_PCT)
    reasons: list[dict] = []
    if fell:
        reasons.append(
            {
                "code": "eps_decline_annual",
                "detail": f"FY{year} EPS {latest:.2f} vs FY{prior[0]} {prior[1]:.2f}",
                "source": source,
            }
        )
    check = {
        "evaluable": True,
        "fired": fell,
        "strength": "soft",
        "label": label,
        "latest_year": year,
        "latest": round(latest, 4),
        "prior": round(prior[1], 4),
    }
    return check, reasons


def _iso(day: date | None) -> str | None:
    return None if day is None else day.isoformat()


def _interim_stale(day: date, as_of: date) -> bool:
    return (as_of - day).days > INTERIM_MAX_AGE_DAYS


def _month_number(name: str) -> int | None:
    key = name.strip().lower()
    for index, full in enumerate(calendar.month_name):
        if full and full.lower() == key:
            return index
    for index, abbr in enumerate(calendar.month_abbr):
        if abbr and abbr.lower() == key:
            return index
    return None


def _parse_dmy(day: str, month: str, year: str) -> date | None:
    month_number = _month_number(month)
    if month_number is None:
        return None
    try:
        return date(int(year), month_number, int(day))
    except ValueError:
        return None


def _period_end_near(text: str, published: date) -> date | None:
    earliest = published - timedelta(days=INTERIM_PUBLICATION_LAG_DAYS)
    found: list[date] = []
    for match in _PERIOD_END_RE.finditer(text):
        parsed = _parse_dmy(match.group(1), match.group(2), match.group(3))
        if parsed is not None and earliest <= parsed <= published:
            found.append(parsed)
    return max(found) if found else None


def _rows_by_period(quarterly: Any, as_of: date) -> dict[date, dict]:
    rows: dict[date, dict] = {}
    if not isinstance(quarterly, dict):
        return rows
    for key, row in quarterly.items():
        period_end = _to_date(key)
        if period_end is None or period_end > as_of or not isinstance(row, dict):
            continue
        rows[period_end] = row
    return rows


def _latest_interim_period(rows: dict[date, dict]) -> date | None:
    dated = [
        period
        for period, row in rows.items()
        if any(_num(row.get(label)) is not None for label in (*INTERIM_REVENUE_LABELS, *EPS_LABELS))
    ]
    return max(dated) if dated else None


def _prior_period(rows: dict[date, dict], latest: date) -> date | None:
    try:
        target = latest.replace(year=latest.year - 1)
    except ValueError:
        target = latest.replace(year=latest.year - 1, day=28)
    best: tuple[int, date] | None = None
    for period in rows:
        if period >= latest:
            continue
        delta = abs((period - target).days)
        if delta <= INTERIM_YOY_WINDOW_DAYS and (best is None or delta < best[0]):
            best = (delta, period)
    return None if best is None else best[1]


def _label_on_both(
    rows: dict[date, dict], latest: date, prior: date, labels: tuple[str, ...]
) -> tuple[str, float, float] | None:
    latest_row = rows.get(latest) or {}
    prior_row = rows.get(prior) or {}
    for label in labels:
        current = _num(latest_row.get(label))
        previous = _num(prior_row.get(label))
        if current is not None and previous is not None:
            return label, current, previous
    return None


def _quarterly_yoy(
    quarterly: Any, labels: tuple[str, ...], as_of: date
) -> tuple[dict[str, Any] | None, str | None]:
    """YoY pair for the latest interim period, or a why when the series cannot be compared."""
    rows = _rows_by_period(quarterly, as_of)
    latest = _latest_interim_period(rows)
    if latest is None:
        return None, None
    if _interim_stale(latest, as_of):
        return {"period_end": _iso(latest)}, "interim_stale"
    prior = _prior_period(rows, latest)
    if prior is None:
        return {"period_end": _iso(latest)}, "interim_prior_period_missing"
    picked = _label_on_both(rows, latest, prior, labels)
    if picked is None:
        return {"period_end": _iso(latest), "prior_period_end": _iso(prior)}, (
            "interim_metric_missing_on_latest_period"
        )
    label, current, previous = picked
    return {
        "label": label,
        "latest": current,
        "prior": previous,
        "period_end": latest,
        "prior_period_end": prior,
        "source": SRC_QUARTERLY,
    }, None


def _published_for_id(filings_index: list | None, source_id: str) -> date | None:
    if not source_id:
        return None
    for item in filings_index or []:
        if isinstance(item, dict) and str(item.get("id") or "") == source_id:
            return _to_date(item.get("published_at"))
    return None


def _highlights_eps(
    filing_interim: dict | None, filings_index: list | None, as_of: date
) -> dict[str, Any] | None:
    if not isinstance(filing_interim, dict):
        return None
    extracted = _to_date(filing_interim.get("extracted_at"))
    if extracted is not None and extracted > as_of:
        return None
    highlights = filing_interim.get("interim_highlights")
    if not isinstance(highlights, dict):
        return None
    picked: tuple[str, float, float] | None = None
    for label, current_key, prior_key in _HIGHLIGHT_EPS_PAIRS:
        current = _num(highlights.get(current_key))
        previous = _num(highlights.get(prior_key))
        if current is None or previous is None or previous <= 0:
            continue
        picked = (label, current, previous)
        break
    if picked is None:
        return None
    source_id = str(highlights.get("source_body_id") or "")
    published = _published_for_id(filings_index, source_id)
    if published is None or published > as_of or _interim_stale(published, as_of):
        return None
    headline = str(highlights.get("headline") or "")
    return {
        "label": picked[0],
        "latest": picked[1],
        "prior": picked[2],
        "period_end": _period_end_near(headline, published),
        "prior_period_end": None,
        "published_at": published,
        "source": f"{SRC_FILING_INTERIM}:{source_id}",
    }


def _screen_eps(row: dict) -> tuple[dict, list[dict]] | None:
    decline = _num(row.get("interim_eps_decline_pct"))
    if decline is None:
        return None
    fired = decline >= EPS_INTERIM_DROP_PCT
    reasons = (
        [
            {
                "code": "eps_decline_interim",
                "detail": f"interim EPS down {decline * 100:.1f}% vs prior-year interim",
                "source": SRC_SCREEN_ROW,
            }
        ]
        if fired
        else []
    )
    check = {
        "evaluable": True,
        "fired": fired,
        "strength": "soft",
        "source": SRC_SCREEN_ROW,
        "period_end": None,
        "prior_period_end": None,
        "interim_eps_decline_pct": round(decline, 4),
    }
    return check, reasons


def _numeric_eps_check(obs: dict[str, Any]) -> tuple[dict, list[dict]]:
    latest = float(obs["latest"])
    prior = float(obs["prior"])
    if prior <= 0:
        return _not_evaluable("prior_eps_non_positive"), []
    change = round(latest / prior - 1.0, 4)
    decline = round(-change, 4)
    fired = decline >= EPS_INTERIM_DROP_PCT
    period_end = obs.get("period_end")
    prior_end = obs.get("prior_period_end")
    period_text = _iso(period_end) if isinstance(period_end, date) else period_end
    prior_text = _iso(prior_end) if isinstance(prior_end, date) else prior_end
    detail = (
        f"interim {obs['label']} {latest:.4g} vs {prior:.4g} ({_pct(change)}) "
        f"period {period_text or 'unknown'} vs {prior_text or 'prior interim'}"
    )
    reasons = (
        [{"code": "eps_decline_interim", "detail": detail, "source": obs["source"]}]
        if fired
        else []
    )
    published = obs.get("published_at")
    check = {
        "evaluable": True,
        "fired": fired,
        "strength": "soft",
        "label": obs["label"],
        "source": obs["source"],
        "period_end": period_text,
        "prior_period_end": prior_text,
        "latest": round(latest, 4),
        "prior": round(prior, 4),
        "change_pct": change,
        "interim_eps_decline_pct": decline,
    }
    if isinstance(published, date):
        check["published_at"] = published.isoformat()
    elif isinstance(published, str) and published:
        check["published_at"] = published
    citation = obs.get("citation")
    if citation:
        check["citation"] = citation
    return check, reasons


def _body_eps_check(interim_body: dict | None, as_of: date) -> tuple[dict, list[dict]] | None:
    if not isinstance(interim_body, dict):
        return None
    decline = _num(interim_body.get("decline_pct"))
    published = _to_date(interim_body.get("published_at"))
    if (
        decline is None
        or published is None
        or published > as_of
        or _interim_stale(published, as_of)
    ):
        return None
    period_end = _to_date(interim_body.get("period_end"))
    if period_end is not None and (period_end > as_of or period_end > published):
        period_end = None
    fired = decline >= EPS_INTERIM_DROP_PCT
    source = str(interim_body.get("source") or "filings body")
    period_text = _iso(period_end)
    detail = (
        f"interim EPS down {decline * 100:.1f}% vs prior-year interim "
        f"(published {published.isoformat()}"
        + (f", period {period_text}" if period_text else "")
        + ")"
    )
    reasons = [{"code": "eps_decline_interim", "detail": detail, "source": source}] if fired else []
    check = {
        "evaluable": True,
        "fired": fired,
        "strength": "soft",
        "label": "interim filing prose",
        "source": source,
        "period_end": period_text,
        "prior_period_end": None,
        "published_at": published.isoformat(),
        "interim_eps_decline_pct": round(decline, 4),
    }
    return check, reasons


def _select_half_year_comparison(filing_interim: dict | None, as_of: date) -> dict[str, Any] | None:
    """Newest half-year results row that was published on or before ``as_of``.

    A newer row that was not extracted blocks an older one. A filing published
    after ``as_of``, or one whose publication or period end is older than
    ``INTERIM_MAX_AGE_DAYS``, is not in the set, so the previous row can be used.
    """
    if not isinstance(filing_interim, dict):
        return None
    rows = filing_interim.get("half_year_comparisons")
    if not isinstance(rows, list):
        return None
    usable: list[tuple[str, dict[str, Any]]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        published = _to_date(row.get("published_at"))
        if published is None or published > as_of or _interim_stale(published, as_of):
            continue
        period_end = _to_date(row.get("period_end"))
        if period_end is not None and (period_end > as_of or _interim_stale(period_end, as_of)):
            continue
        usable.append((published.isoformat() + str(row.get("source_filing_id") or ""), row))
    if not usable:
        return None
    usable.sort(key=lambda item: item[0], reverse=True)
    newest = usable[0][1]
    if newest.get("status") != "extracted":
        return None
    return newest


def _half_year_source(row: dict[str, Any]) -> str:
    return f"{SRC_FILING_INTERIM}:{row.get('source_filing_id') or 'unknown'}"


def _revenue_from_half_year(
    filing_interim: dict | None, as_of: date
) -> tuple[dict, list[dict]] | None:
    row = _select_half_year_comparison(filing_interim, as_of)
    if row is None:
        return None
    revenue = row.get("revenue")
    if not isinstance(revenue, dict):
        return None
    latest = _num(revenue.get("current"))
    prior = _num(revenue.get("prior"))
    if latest is None or prior is None or latest <= 0 or prior <= 0:
        return None
    change = round(latest / prior - 1.0, 4)
    fired = change < -INTERIM_REVENUE_DROP_PCT
    period_end = row.get("period_end")
    prior_end = row.get("prior_period_end")
    label = str(revenue.get("label") or "revenue")
    source = _half_year_source(row)
    detail = (
        f"interim {label} {latest:,.4g} vs {prior:,.4g} ({_pct(change)}) "
        f"period {period_end or 'unknown'} vs {prior_end or 'prior half'}"
    )
    reasons = (
        [{"code": "interim_revenue_decline", "detail": detail, "source": source}] if fired else []
    )
    published = _to_date(row.get("published_at"))
    check: dict[str, Any] = {
        "evaluable": True,
        "fired": fired,
        "strength": "hard",
        "label": label,
        "source": source,
        "period_end": period_end,
        "prior_period_end": prior_end,
        "latest": round(latest, 4),
        "prior": round(prior, 4),
        "change_pct": change,
        "unit": revenue.get("unit"),
        "currency": revenue.get("currency"),
    }
    if published is not None:
        check["published_at"] = published.isoformat()
    if revenue.get("snippet"):
        check["citation"] = revenue["snippet"]
    return check, reasons


def _eps_from_half_year(filing_interim: dict | None, as_of: date) -> dict[str, Any] | None:
    row = _select_half_year_comparison(filing_interim, as_of)
    if row is None:
        return None
    by_kind: dict[str, dict[str, Any]] = {}
    for item in row.get("eps") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        if kind and kind not in by_kind:
            by_kind[kind] = item
    for kind in _HALF_YEAR_EPS_KINDS:
        item = by_kind.get(kind)
        if item is None:
            continue
        current = _num(item.get("current"))
        prior = _num(item.get("prior"))
        if current is None or prior is None or prior <= 0:
            continue
        return {
            "label": str(item.get("label") or kind),
            "latest": current,
            "prior": prior,
            "period_end": row.get("period_end"),
            "prior_period_end": row.get("prior_period_end"),
            "published_at": _to_date(row.get("published_at")),
            "source": _half_year_source(row),
            "citation": item.get("snippet"),
        }
    return None


def _check_eps_interim(
    row: dict,
    quarterly: Any,
    filing_interim: dict | None,
    interim_body: dict | None,
    filings_index: list | None,
    as_of: date,
) -> tuple[dict, list[dict]]:
    """One interim EPS comparison. The first evaluable source replaces the rest."""
    observation, why = _quarterly_yoy(quarterly, EPS_LABELS, as_of)
    if observation is not None and why is None:
        check, reasons = _numeric_eps_check(observation)
        if check["evaluable"]:
            return check, reasons
    half_year = _eps_from_half_year(filing_interim, as_of)
    if half_year is not None:
        check, reasons = _numeric_eps_check(half_year)
        if check["evaluable"]:
            return check, reasons
    highlights = _highlights_eps(filing_interim, filings_index, as_of)
    if highlights is not None:
        check, reasons = _numeric_eps_check(highlights)
        if check["evaluable"]:
            return check, reasons
    body = _body_eps_check(interim_body, as_of)
    if body is not None:
        return body
    screen = _screen_eps(row)
    if screen is not None:
        return screen
    if why is not None:
        check = _not_evaluable(why)
        check.update(
            {key: value for key, value in (observation or {}).items() if value is not None}
        )
        check["source"] = SRC_QUARTERLY
        return check, []
    return _not_evaluable("interim_eps_not_on_screen_row"), []


def _check_interim_revenue(
    quarterly: Any,
    as_of: date,
    financials_note: str | None,
    filing_interim: dict | None = None,
) -> tuple[dict, list[dict]]:
    observation, why = _quarterly_yoy(quarterly, INTERIM_REVENUE_LABELS, as_of)
    if observation is not None and why is None:
        prior = float(observation["prior"])
        if prior > 0:
            return _interim_revenue_from_quarterly(observation)
    half_year = _revenue_from_half_year(filing_interim, as_of)
    if half_year is not None:
        return half_year
    if why is not None or observation is None:
        if observation is None and financials_note:
            return _not_evaluable(financials_note), []
        if why is None:
            return _not_evaluable("interim_revenue_missing"), []
        check = _not_evaluable(why)
        check.update(observation or {})
        check["source"] = SRC_QUARTERLY
        return check, []
    return _not_evaluable("prior_revenue_non_positive"), []


def _interim_revenue_from_quarterly(observation: dict[str, Any]) -> tuple[dict, list[dict]]:
    latest = float(observation["latest"])
    prior = float(observation["prior"])
    change = round(latest / prior - 1.0, 4)
    period_end = observation["period_end"]
    prior_end = observation["prior_period_end"]
    detail = (
        f"interim {observation['label']} {latest:,.0f} vs {prior:,.0f} ({_pct(change)}) "
        f"period {period_end.isoformat()} vs {prior_end.isoformat()}"
    )
    fired = change < -INTERIM_REVENUE_DROP_PCT
    reasons = (
        [{"code": "interim_revenue_decline", "detail": detail, "source": SRC_QUARTERLY}]
        if fired
        else []
    )
    check = {
        "evaluable": True,
        "fired": fired,
        "strength": "hard",
        "label": observation["label"],
        "source": SRC_QUARTERLY,
        "period_end": period_end.isoformat(),
        "prior_period_end": prior_end.isoformat(),
        "latest": round(latest, 2),
        "prior": round(prior, 2),
        "change_pct": change,
    }
    return check, reasons


def _check_fcf(cash_flow: Any, as_of: date, source: str) -> tuple[dict, list[dict]]:
    picked = _select_series(_fcf_candidates(cash_flow, as_of), as_of)
    if picked is None or picked[1][1] is None:
        return _not_evaluable("fcf_missing_or_stale"), []
    label, pair = picked
    (year, latest), prior = pair[0], pair[1]
    reasons: list[dict] = []
    strength = "soft"
    if prior[1] > 0 and latest < 0:
        strength = "hard"
        reasons.append(
            {
                "code": "fcf_turned_negative",
                "detail": f"FY{year} FCF {latest:,.0f} after FY{prior[0]} {prior[1]:,.0f}",
                "source": source,
            }
        )
    elif prior[1] > 0 and latest < prior[1] * (1.0 - FCF_SHARP_FALL_PCT):
        reasons.append(
            {
                "code": "fcf_sharp_fall",
                "detail": f"FY{year} FCF {latest:,.0f} vs FY{prior[0]} {prior[1]:,.0f}",
                "source": source,
            }
        )
    check = {
        "evaluable": True,
        "fired": bool(reasons),
        "strength": strength if reasons else "soft",
        "label": label,
        "latest_year": year,
        "latest": round(latest, 2),
        "prior": round(prior[1], 2),
    }
    return check, reasons


def _check_dividend(row: dict) -> tuple[dict, list[dict]]:
    flag = row.get("interim_dividend_cut_flagged")
    if not isinstance(flag, bool):
        return _not_evaluable("dividend_flag_not_on_screen_row"), []
    reasons = (
        [
            {
                "code": "dividend_cut",
                "detail": "interim results flag a dividend cut",
                "source": SRC_SCREEN_ROW,
            }
        ]
        if flag
        else []
    )
    return {"evaluable": True, "fired": flag, "strength": "soft"}, reasons


def _headline_text(item: dict) -> str:
    return f"{item.get('headline') or ''} {item.get('summary') or ''}".lower()


def _classify_headline(text: str) -> str | None:
    if any(p in text for p in HARD_PHRASES):
        return "profit_warning"
    if any(u in text for u in UPDATE_PHRASES) and any(
        b in text for b in BELOW_EXPECTATIONS_PHRASES
    ):
        return "profit_warning"
    if any(p in text for p in SOFT_PHRASES):
        return "impairment_or_downgrade"
    return None


def _check_warnings(filings_index: list | None, as_of: date) -> tuple[dict, list[dict]]:
    if filings_index is None:
        return _not_evaluable("no_filings_index"), []
    window_start = as_of - timedelta(days=WARNING_LOOKBACK_DAYS)
    scanned = 0
    hits: dict[str, list[tuple[date, dict]]] = {}
    for item in filings_index:
        if not isinstance(item, dict):
            continue
        if str(item.get("source") or "").startswith(THIRD_PARTY_NEWS_SOURCE_PREFIXES):
            continue
        published = _to_date(item.get("published_at"))
        if published is None or published > as_of or published < window_start:
            continue
        scanned += 1
        code = _classify_headline(_headline_text(item))
        if code:
            hits.setdefault(code, []).append((published, item))
    reasons: list[dict] = []
    for code in ("profit_warning", "impairment_or_downgrade"):
        found = sorted(hits.get(code, []), key=lambda pair: pair[0], reverse=True)
        if not found:
            continue
        published, item = found[0]
        headline = str(item.get("headline") or "")[:120]
        extra = f" (+{len(found) - 1} more)" if len(found) > 1 else ""
        reasons.append(
            {
                "code": code,
                "detail": f"{published.isoformat()} {headline}{extra}",
                "source": f"{SRC_FILINGS}:{item.get('id') or item.get('url') or 'unknown'}",
            }
        )
    check = {
        "evaluable": True,
        "fired": bool(reasons),
        "strength": "hard" if "profit_warning" in hits else "soft",
        "scanned_items": scanned,
        "lookback_days": WARNING_LOOKBACK_DAYS,
    }
    return check, reasons


def _financials_usable(financials: dict | None, as_of: date) -> tuple[dict | None, str | None]:
    if not isinstance(financials, dict):
        return None, "financials_missing"
    fetched = _to_date(financials.get("fetched_at"))
    if fetched is not None and fetched > as_of:
        return None, "financials_fetched_after_as_of"
    return financials, None


def assess_operating_decline(
    row: dict,
    financials: dict | None,
    filings_index: list | None,
    *,
    as_of: Any,
    filing_interim: dict | None = None,
    interim_body: dict | None = None,
) -> dict[str, Any]:
    """Pure verdict from screen row, statements, interim sources and filings headlines.

    Hard checks (any one => ``declining``): annual or interim revenue fell by more
    than ``REVENUE_DROP_PCT`` (interim is year-on-year, not sequential), two
    consecutive annual declines, operating margin fell more than ``MARGIN_DROP_PP``,
    FCF turned negative after a positive year, or a profit warning / guidance cut
    headline in the lookback window.
    Soft checks (``SOFT_SIGNALS_TO_DECLINE`` together => ``declining``): annual
    EPS fall, one interim EPS fall, sharp FCF fall, dividend cut flag, impairment /
    downgrade headline. Interim EPS uses the first evaluable source only (quarterly
    series, half-year filing extract, filing interim highlights, half-year filing
    prose, then the screen row). Interim revenue uses the quarterly series, then
    the half-year filing extract when that series is not evaluable.
    ``insufficient_data`` when no adverse signal fired and revenue plus (margin or
    EPS) could not be evaluated. Only periods and filings dated on or before
    ``as_of`` are used.
    """
    as_of_date = _to_date(as_of)
    if as_of_date is None:
        raise ValueError("as_of must be a date or ISO date string")
    row = row if isinstance(row, dict) else {}
    usable, financials_note = _financials_usable(financials, as_of_date)
    statements = usable or {}
    income = statements.get("income_statement")
    cash_flow = statements.get("cash_flow")
    quarterly = statements.get("quarterly_income")
    source = f"{SRC_FINANCIALS} (as of {as_of_date.isoformat()})"

    checks: dict[str, dict[str, Any]] = {}
    reasons: list[dict] = []
    for name, (check, found) in (
        ("revenue", _check_revenue(income, as_of_date, source)),
        (
            "interim_revenue",
            _check_interim_revenue(quarterly, as_of_date, financials_note, filing_interim),
        ),
        ("operating_margin", _check_margin(income, as_of_date, source)),
        ("eps_annual", _check_eps_annual(income, as_of_date, source)),
        (
            "eps_interim",
            _check_eps_interim(
                row, quarterly, filing_interim, interim_body, filings_index, as_of_date
            ),
        ),
        ("fcf", _check_fcf(cash_flow, as_of_date, source)),
        ("dividend", _check_dividend(row)),
        ("profit_warning", _check_warnings(filings_index, as_of_date)),
    ):
        if not check["evaluable"] and financials_note and name in FINANCIAL_CHECKS:
            check["why"] = financials_note
        checks[name] = check
        reasons.extend(found)

    hard = [r for r in reasons if r["code"] in HARD_REASON_CODES]
    soft = [r for r in reasons if r["code"] in SOFT_REASON_CODES]
    revenue_ok = checks["revenue"]["evaluable"]
    trend_ok = checks["operating_margin"]["evaluable"] or any(
        checks[k]["evaluable"] for k in ("eps_annual", "eps_interim")
    )

    if hard or len(soft) >= SOFT_SIGNALS_TO_DECLINE:
        verdict = "declining"
    elif not (revenue_ok and trend_ok):
        verdict = "insufficient_data"
        for name in ("revenue", "operating_margin"):
            if not checks[name]["evaluable"]:
                reasons.append(
                    {
                        "code": f"{name}_not_evaluable",
                        "detail": str(checks[name].get("why") or "not evaluable"),
                        "source": SRC_FINANCIALS,
                    }
                )
        if not trend_ok:
            reasons.append(
                {
                    "code": "eps_not_evaluable",
                    "detail": "no annual or interim EPS comparison available",
                    "source": SRC_FINANCIALS,
                }
            )
    else:
        verdict = "clear"
    return {"verdict": verdict, "reasons": reasons, "checks": checks}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _is_interim_results(item: dict) -> bool:
    from value_investor.research.half_year_extract import is_half_year_results_row

    return is_half_year_results_row(item)


def _resolve_filing_body(sources_dir: Path, item: dict) -> Path | None:
    from value_investor.research.filings import resolve_filing_body_path_for_row

    return resolve_filing_body_path_for_row(item, sources_dir / "filings" / "bodies")


def _interim_body_from_filings(
    sources_dir: Path, filings: list | None, as_of: date
) -> dict[str, Any] | None:
    """Latest dated half-year results body, parsed with the existing EPS-decline reader."""
    best: tuple[date, dict] | None = None
    for item in filings or []:
        if not isinstance(item, dict) or not _is_interim_results(item):
            continue
        published = _to_date(item.get("published_at"))
        if published is None or published > as_of or _interim_stale(published, as_of):
            continue
        if best is None or published > best[0]:
            best = (published, item)
    if best is None:
        return None
    published, item = best
    path = _resolve_filing_body(sources_dir, item)
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    from value_investor.scoring.fcf import parse_interim_eps_decline_pct

    decline = parse_interim_eps_decline_pct(text)
    if decline is None:
        return None
    headline = str(item.get("headline") or "")
    period_end = _period_end_near(f"{headline}\n{text[:8000]}", published)
    filing_id = str(item.get("id") or "unknown")
    return {
        "decline_pct": decline,
        "published_at": published.isoformat(),
        "period_end": _iso(period_end),
        "source": f"filings/{filing_id}",
    }


def _extract_half_year_in_memory(sources_dir: Path, ticker: str) -> dict | None:
    """Parse half-year bodies without writing, for a read-only gate refresh."""
    filings_dir = sources_dir / "filings"
    if not (filings_dir / "filings_index.json").is_file():
        return None
    from value_investor.research.filings import extract_filing_interim_financials

    return extract_filing_interim_financials(filings_dir, ticker, sources_dir=None)


def _load_sources(
    sources_dir: Path, as_of: date
) -> tuple[dict | None, list | None, dict | None, dict | None]:
    financials = _read_json(sources_dir / "financials_annual.json")
    index = _read_json(sources_dir / "filings" / "filings_index.json")
    filings = index.get("filings") if isinstance(index, dict) else None
    filings_list = filings if isinstance(filings, list) else None
    filing_interim = _read_json(sources_dir / "filing_interim_financials.json")
    if not isinstance(filing_interim, dict):
        filing_interim = None
    # ``extracted_at`` is when we parsed the file, not when the company reported.
    # Half-year rows are kept and selected by ``published_at``. Legacy highlights
    # still fail closed on a future ``extracted_at`` inside ``_highlights_eps``.
    body = _interim_body_from_filings(sources_dir, filings_list, as_of)
    return (
        financials if isinstance(financials, dict) else None,
        filings_list,
        filing_interim,
        body,
    )


def _library_rows(library_root: Path) -> list[tuple[str, dict, Path]]:
    out: list[tuple[str, dict, Path]] = []
    markets_dir = library_root / "markets"
    if not markets_dir.is_dir():
        return out
    for market_dir in sorted(p for p in markets_dir.iterdir() if p.is_dir()):
        signals = market_dir / "screen" / "latest_signals.csv"
        research = market_dir / "screen" / "research"
        if not signals.is_file() or not research.is_dir():
            continue
        try:
            with signals.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except (OSError, UnicodeDecodeError, csv.Error):
            continue
        for row in rows:
            ticker = str(row.get("ticker") or "").strip().upper()
            if ticker and (research / ticker / "sources" / "financials_annual.json").is_file():
                out.append((market_dir.name, row, research / ticker / "sources"))
    return out


def _resolve_as_of(as_of: Any) -> date:
    resolved = _to_date(as_of) if as_of is not None else datetime.now(UTC).date()
    if resolved is None:
        raise ValueError(f"unparseable as_of: {as_of!r}")
    return resolved


def _empty_summary() -> dict[str, Any]:
    return {
        "names": 0,
        "clear": 0,
        "declining": 0,
        "insufficient_data": 0,
        "buy_tier_names": 0,
        "buy_tier_covered": 0,
        "names_with_interim_eps": 0,
        "names_with_interim_revenue": 0,
        "buy_tier_with_interim_revenue": 0,
        "buy_tier_with_interim_eps": 0,
        "latest_fiscal_year_counts": {},
    }


def refresh_operating_decline_gate(
    *,
    latest_path: Path = DEFAULT_LATEST_PATH,
    research_root: Path = DEFAULT_RESEARCH_ROOT,
    store_path: Path = DEFAULT_STORE_PATH,
    persist: bool = True,
    as_of: Any = None,
    library_root: Path | None = DEFAULT_LIBRARY_ROOT,
) -> dict[str, Any]:
    """Score every FTSE screen name (then library names with research sources).

    Committed files only. FTSE names win a ticker collision with library markets.
    """
    as_of_date = _resolve_as_of(as_of)
    if persist:
        # A newly ingested half-year body is extracted in this same daily step,
        # before the gate reads ``filing_interim_financials.json``.
        from value_investor.research.filings import backfill_filing_interim_financials

        backfill_filing_interim_financials(
            Path(research_root),
            Path(library_root) if library_root is not None else None,
        )
    latest = _read_json(Path(latest_path))
    latest = latest if isinstance(latest, dict) else {}
    run_date = _to_date(latest.get("run_at"))
    row_after_as_of = run_date is not None and run_date > as_of_date

    names: dict[str, dict[str, Any]] = {}

    def score(market: str, row: dict, sources_dir: Path, *, sanitize: bool) -> None:
        ticker = str(row.get("ticker") or "").strip().upper()
        if not ticker or ticker in names:
            return
        scored_row = {} if sanitize else row
        financials, filings, filing_interim, interim_body = _load_sources(sources_dir, as_of_date)
        if not persist:
            fresh = _extract_half_year_in_memory(sources_dir, ticker)
            if fresh is not None:
                filing_interim = fresh
        result = assess_operating_decline(
            scored_row,
            financials,
            filings,
            as_of=as_of_date,
            filing_interim=filing_interim,
            interim_body=interim_body,
        )
        names[ticker] = {
            "market": market,
            "sector": str(row.get("sector") or "") or None,
            "signal": str(row.get("signal") or "") or None,
            **result,
        }

    for row in latest.get("reports") or []:
        if isinstance(row, dict) and row.get("ticker"):
            ticker = str(row["ticker"]).strip().upper()
            score(
                LIVE_MARKET_ID,
                row,
                Path(research_root) / ticker / "sources",
                sanitize=row_after_as_of,
            )
    if library_root is not None:
        for market, row, sources_dir in _library_rows(Path(library_root)):
            score(market, row, sources_dir, sanitize=False)

    summary = _empty_summary()
    for entry in names.values():
        summary["names"] += 1
        summary[entry["verdict"]] += 1
        if entry["checks"]["eps_interim"]["evaluable"]:
            summary["names_with_interim_eps"] += 1
        if entry["checks"]["interim_revenue"]["evaluable"]:
            summary["names_with_interim_revenue"] += 1
        revenue_year = entry["checks"]["revenue"].get("latest_year")
        if revenue_year is not None:
            counts = summary["latest_fiscal_year_counts"]
            counts[str(revenue_year)] = counts.get(str(revenue_year), 0) + 1
        if entry["market"] == LIVE_MARKET_ID and entry["signal"] in BUY_TIER_SIGNALS:
            summary["buy_tier_names"] += 1
            if entry["verdict"] != "insufficient_data":
                summary["buy_tier_covered"] += 1
            if entry["checks"]["interim_revenue"]["evaluable"]:
                summary["buy_tier_with_interim_revenue"] += 1
            if entry["checks"]["eps_interim"]["evaluable"]:
                summary["buy_tier_with_interim_eps"] += 1

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "as_of": as_of_date.isoformat(),
        "observe_only": True,
        "influences_live": False,
        "learning_question": LEARNING_QUESTION,
        "summary": summary,
        "names": dict(sorted(names.items())),
    }
    if persist:
        store = Path(store_path)
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    return payload


def _flagged_buy_tier(payload: dict[str, Any]) -> list[tuple[str, dict]]:
    names = payload.get("names") if isinstance(payload.get("names"), dict) else {}
    return [
        (ticker, entry)
        for ticker, entry in names.items()
        if isinstance(entry, dict)
        and entry.get("market") == LIVE_MARKET_ID
        and entry.get("signal") in BUY_TIER_SIGNALS
        and entry.get("verdict") == "declining"
    ]


def _fy_counts_text(summary: dict[str, Any]) -> str:
    counts = summary.get("latest_fiscal_year_counts")
    if not isinstance(counts, dict) or not counts:
        return "n/a"
    return ", ".join(f"{year}:{n}" for year, n in sorted(counts.items(), reverse=True))


def ops_findings_from_operating_decline_gate(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Map the store to ops-monitor finding dicts (observe-only, never auto-fixable)."""
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    buy_names = int(summary.get("buy_tier_names") or 0)
    covered = int(summary.get("buy_tier_covered") or 0)
    flagged = _flagged_buy_tier(payload)
    flagged_text = "; ".join(
        f"{ticker} ({', '.join(r['code'] for r in entry.get('reasons') or [])})"
        for ticker, entry in flagged[:FLAGGED_NAMES_IN_FINDING]
    )
    more = (
        f" (+{len(flagged) - FLAGGED_NAMES_IN_FINDING} more)"
        if len(flagged) > FLAGGED_NAMES_IN_FINDING
        else ""
    )
    findings: list[dict[str, Any]] = [
        {
            "severity": "info",
            "category": "research",
            "title": FINDING_TITLE,
            "summary": (
                f"as_of {payload.get('as_of')}: {summary.get('names', 0)} names — "
                f"clear {summary.get('clear', 0)}, declining {summary.get('declining', 0)}, "
                f"insufficient_data {summary.get('insufficient_data', 0)}; "
                f"FTSE buy-tier covered {covered}/{buy_names}, "
                f"flagged declining {len(flagged)}; "
                f"interim EPS on {summary.get('names_with_interim_eps', 0)} names, "
                f"interim revenue on {summary.get('names_with_interim_revenue', 0)} names, "
                f"FTSE buy-tier interim revenue "
                f"{summary.get('buy_tier_with_interim_revenue', 0)}/{buy_names}, "
                f"interim EPS {summary.get('buy_tier_with_interim_eps', 0)}/{buy_names}, "
                f"latest revenue FY {_fy_counts_text(summary)}"
                + (f": {flagged_text}{more}" if flagged else "")
                + ". Observe-only — influences_live false; no book, knob or signal writes."
            ),
            "auto_fixable": False,
        }
    ]
    if buy_names == 0 or covered / buy_names < COVERAGE_WARN_SHARE:
        findings.append(
            {
                "severity": "warn",
                "category": "research",
                "title": COVERAGE_GAP_TITLE,
                "summary": (
                    f"Only {covered}/{buy_names} FTSE buy-tier names have a clear/declining "
                    f"verdict (floor {COVERAGE_WARN_SHARE:.0%}); the rest are "
                    "insufficient_data — annual statements or EPS comparison missing. "
                    "Observe-only; no rememo/ingest spray from this finding alone."
                ),
                "auto_fixable": False,
            }
        )
    interim_revenue = int(summary.get("buy_tier_with_interim_revenue") or 0)
    if (
        buy_names >= BUY_TIER_INTERIM_REVENUE_MIN_NAMES
        and interim_revenue / buy_names < BUY_TIER_INTERIM_REVENUE_FLOOR
    ):
        findings.append(
            {
                "severity": "warn",
                "category": "research",
                "title": INTERIM_COVERAGE_TITLE,
                "summary": (
                    f"FTSE buy-tier interim revenue is evaluable on "
                    f"{interim_revenue}/{buy_names} names "
                    f"({interim_revenue / buy_names:.0%}), below the "
                    f"{BUY_TIER_INTERIM_REVENUE_FLOOR:.0%} floor. The half-year filing "
                    "extract is the source when Yahoo has no prior-year quarter. "
                    "Observe-only; no rememo or ingest spray from this finding alone."
                ),
                "auto_fixable": False,
            }
        )
    return findings


def format_operating_decline_text(payload: dict[str, Any], *, ticker: str | None = None) -> str:
    names = payload.get("names") if isinstance(payload.get("names"), dict) else {}
    if ticker:
        entry = names.get(ticker.strip().upper())
        if not isinstance(entry, dict):
            return f"{ticker.upper()}: not in the gate store\n"
        lines = [
            f"{ticker.upper()} [{entry.get('market')}, {entry.get('signal')}]: "
            f"{entry.get('verdict')} (as_of {payload.get('as_of')})"
        ]
        lines += [
            f"  - {r['code']}: {r['detail']}  [{r['source']}]" for r in entry.get("reasons") or []
        ]
        for name, check in (entry.get("checks") or {}).items():
            lines.append(f"  check {name}: {json.dumps(check, sort_keys=True)}")
        return "\n".join(lines) + "\n"
    summary = payload.get("summary") or {}
    lines = [
        f"Operating-decline gate (observe-only) as_of {payload.get('as_of')}",
        f"  names {summary.get('names')}: clear {summary.get('clear')}, "
        f"declining {summary.get('declining')}, "
        f"insufficient_data {summary.get('insufficient_data')}",
        f"  FTSE buy-tier covered {summary.get('buy_tier_covered')}/{summary.get('buy_tier_names')}",
        f"  interim comparisons: revenue {summary.get('names_with_interim_revenue', 0)}, "
        f"EPS {summary.get('names_with_interim_eps', 0)}",
        f"  FTSE buy-tier interim revenue "
        f"{summary.get('buy_tier_with_interim_revenue', 0)}/"
        f"{summary.get('buy_tier_names', 0)}, "
        f"interim EPS {summary.get('buy_tier_with_interim_eps', 0)}/"
        f"{summary.get('buy_tier_names', 0)}",
    ]
    for ticker_name, entry in _flagged_buy_tier(payload):
        codes = ", ".join(r["code"] for r in entry.get("reasons") or [])
        lines.append(f"  declining buy-tier: {ticker_name} ({codes})")
    return "\n".join(lines) + "\n"
