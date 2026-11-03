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

import csv
import json
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

DEFAULT_LATEST_PATH = Path("docs/data/latest.json")
DEFAULT_RESEARCH_ROOT = Path("docs/data/research")
DEFAULT_LIBRARY_ROOT = Path("docs/data/library")
DEFAULT_STORE_PATH = Path("docs/data/operating_decline_gate.json")

SCHEMA_VERSION = 1
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
STORE_FAILED_TITLE = "Operating-decline gate failed"

REVENUE_DROP_PCT = 0.05
REVENUE_FLAT_TOLERANCE_PCT = 0.01
MARGIN_DROP_PP = 0.03
EPS_ANNUAL_DROP_PCT = 0.20
EPS_INTERIM_DROP_PCT = 0.10
FCF_SHARP_FALL_PCT = 0.50
SOFT_SIGNALS_TO_DECLINE = 2
WARNING_LOOKBACK_DAYS = 180
COVERAGE_WARN_SHARE = 0.80
FLAGGED_NAMES_IN_FINDING = 5

REVENUE_LABELS = ("Total Revenue", "Operating Revenue")
OPERATING_INCOME_LABELS = ("Operating Income", "Total Operating Income As Reported", "EBIT")
EPS_LABELS = ("Diluted EPS", "Basic EPS")
FCF_LABEL = "Free Cash Flow"
OPERATING_CASHFLOW_LABEL = "Operating Cash Flow"
CAPEX_LABEL = "Capital Expenditure"

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
SRC_SCREEN_ROW = "latest.json reports"
SRC_FILINGS = "filings_index.json"


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


def _year_series(statement: Any, labels: tuple[str, ...], as_of: date) -> dict[int, float]:
    """Annual values by fiscal-year int, first available label wins per year."""
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
        for label in labels:
            value = _num(row.get(label))
            if value is not None:
                out[year] = value
                break
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


def _fcf_series(cash_flow: Any, as_of: date) -> dict[int, float]:
    direct = _year_series(cash_flow, (FCF_LABEL,), as_of)
    derived: dict[int, float] = {}
    ocf = _year_series(cash_flow, (OPERATING_CASHFLOW_LABEL,), as_of)
    capex = _year_series(cash_flow, (CAPEX_LABEL,), as_of)
    for year, value in ocf.items():
        if year in capex and year not in direct:
            derived[year] = value + capex[year]
    return {**derived, **direct}


def _not_evaluable(why: str) -> dict[str, Any]:
    return {"evaluable": False, "fired": False, "why": why}


def _check_revenue(income: Any, as_of: date, source: str) -> tuple[dict, list[dict]]:
    pair = _latest_pair(_year_series(income, REVENUE_LABELS, as_of), as_of)
    if pair is None or pair[1] is None:
        return _not_evaluable("revenue_missing_or_stale"), []
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
        "latest_year": year,
        "change_pct": round(change, 4),
        "prior_change_pct": None if prior_change is None else round(prior_change, 4),
    }
    return check, reasons


def _check_margin(income: Any, as_of: date, source: str) -> tuple[dict, list[dict]]:
    revenue = _year_series(income, REVENUE_LABELS, as_of)
    operating = _year_series(income, OPERATING_INCOME_LABELS, as_of)
    margins = {y: operating[y] / revenue[y] for y in operating if revenue.get(y, 0.0) > 0}
    pair = _latest_pair(margins, as_of)
    if pair is None or pair[1] is None:
        return _not_evaluable("operating_income_missing_or_stale"), []
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
        "latest_year": year,
        "latest_margin": round(latest, 4),
        "prior_margin": round(prior[1], 4),
        "change_pp": round(-drop, 4),
    }
    return check, reasons


def _check_eps_annual(income: Any, as_of: date, source: str) -> tuple[dict, list[dict]]:
    pair = _latest_pair(_year_series(income, EPS_LABELS, as_of), as_of)
    if pair is None or pair[1] is None:
        return _not_evaluable("annual_eps_missing_or_stale"), []
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
        "latest_year": year,
        "latest": round(latest, 4),
        "prior": round(prior[1], 4),
    }
    return check, reasons


def _check_eps_interim(row: dict) -> tuple[dict, list[dict]]:
    decline = _num(row.get("interim_eps_decline_pct"))
    if decline is None:
        return _not_evaluable("interim_eps_not_on_screen_row"), []
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
        "interim_eps_decline_pct": round(decline, 4),
    }
    return check, reasons


def _check_fcf(cash_flow: Any, as_of: date, source: str) -> tuple[dict, list[dict]]:
    pair = _latest_pair(_fcf_series(cash_flow, as_of), as_of)
    if pair is None or pair[1] is None:
        return _not_evaluable("fcf_missing_or_stale"), []
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
) -> dict[str, Any]:
    """Pure verdict from screen row, annual statements and filings headlines.

    Hard checks (any one => ``declining``): revenue fell more than
    ``REVENUE_DROP_PCT`` or two consecutive annual declines; operating margin fell
    more than ``MARGIN_DROP_PP``; FCF turned negative after a positive year; a
    profit warning / guidance cut headline in the lookback window.
    Soft checks (``SOFT_SIGNALS_TO_DECLINE`` together => ``declining``): annual
    EPS fall, interim EPS fall, sharp FCF fall, dividend cut flag, impairment /
    downgrade headline. ``insufficient_data`` when no adverse signal fired and
    revenue plus (margin or EPS) could not be evaluated. Only items dated on or
    before ``as_of`` are used.
    """
    as_of_date = _to_date(as_of)
    if as_of_date is None:
        raise ValueError("as_of must be a date or ISO date string")
    row = row if isinstance(row, dict) else {}
    usable, financials_note = _financials_usable(financials, as_of_date)
    statements = usable or {}
    income = statements.get("income_statement")
    cash_flow = statements.get("cash_flow")
    source = f"{SRC_FINANCIALS} (as of {as_of_date.isoformat()})"

    checks: dict[str, dict[str, Any]] = {}
    reasons: list[dict] = []
    for name, (check, found) in (
        ("revenue", _check_revenue(income, as_of_date, source)),
        ("operating_margin", _check_margin(income, as_of_date, source)),
        ("eps_annual", _check_eps_annual(income, as_of_date, source)),
        ("eps_interim", _check_eps_interim(row)),
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


def _load_sources(sources_dir: Path) -> tuple[dict | None, list | None]:
    financials = _read_json(sources_dir / "financials_annual.json")
    index = _read_json(sources_dir / "filings" / "filings_index.json")
    filings = index.get("filings") if isinstance(index, dict) else None
    return (
        financials if isinstance(financials, dict) else None,
        filings if isinstance(filings, list) else None,
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


def _empty_summary() -> dict[str, int]:
    return {
        "names": 0,
        "clear": 0,
        "declining": 0,
        "insufficient_data": 0,
        "buy_tier_names": 0,
        "buy_tier_covered": 0,
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
        financials, filings = _load_sources(sources_dir)
        result = assess_operating_decline(scored_row, financials, filings, as_of=as_of_date)
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
        if entry["market"] == LIVE_MARKET_ID and entry["signal"] in BUY_TIER_SIGNALS:
            summary["buy_tier_names"] += 1
            if entry["verdict"] != "insufficient_data":
                summary["buy_tier_covered"] += 1

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
                f"flagged declining {len(flagged)}"
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
    ]
    for ticker_name, entry in _flagged_buy_tier(payload):
        codes = ", ".join(r["code"] for r in entry.get("reasons") or [])
        lines.append(f"  declining buy-tier: {ticker_name} ({codes})")
    return "\n".join(lines) + "\n"
