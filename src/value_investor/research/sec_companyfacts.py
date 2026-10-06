"""SEC EDGAR companyfacts — filed XBRL cash-flow facts for US memo names (L544).

Writes ``sources/sec_companyfacts.json`` next to ``financials_annual.json``:
annual operating cash flow, capital expenditure and dividends paid as tagged in
each 10-K / 20-F / 40-F, with accession number and filed date per value.

This is the US analogue of Companies House iXBRL accounts for the memo FCF
basis. It is a memo source only: scoring still reads the Yahoo-derived
``filing_aligned`` basis. ``sec_companyfacts_coverage`` compares the two
(observe-only) before any promotion into ``reconcile_fcf``.

Docs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, resolve_json_path, write_json

logger = logging.getLogger(__name__)

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SOURCE_FILENAME = "sec_companyfacts.json"
SCHEMA_VERSION = 1
MAX_ANNUAL_PERIODS = 5
DEFAULT_MAX_AGE_DAYS = 30
DEFAULT_BACKFILL_MAX_TICKERS = 40
# SEC fair access allows 10 requests/second; stay well under it.
REQUEST_SLEEP_S = 0.2
US_SEC_MARKETS = ("sp500", "nasdaq100", "us_adr_asia")

ANNUAL_FORMS = frozenset({"10-K", "10-K/A", "10-KT", "20-F", "20-F/A", "40-F", "40-F/A"})
# Annual duration window; excludes the 3-month Q4 facts that 10-Ks also carry.
MIN_ANNUAL_DAYS = 340
MAX_ANNUAL_DAYS = 380

# Concept priority per metric. The first concept tagged for a period wins.
METRIC_CONCEPTS: dict[str, tuple[tuple[str, str], ...]] = {
    "operating_cashflow": (
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
        ("ifrs-full", "CashFlowsFromUsedInOperatingActivities"),
    ),
    "capital_expenditure": (
        ("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment"),
        ("us-gaap", "PaymentsToAcquireProductiveAssets"),
        ("us-gaap", "PaymentsToAcquireOtherPropertyPlantAndEquipment"),
        ("us-gaap", "PaymentsToAcquireOilAndGasPropertyAndEquipment"),
        ("us-gaap", "PaymentsToAcquireOilAndGasProperty"),
        ("us-gaap", "PaymentsForCapitalImprovements"),
        ("ifrs-full", "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"),
        ("ifrs-full", "PurchaseOfPropertyPlantAndEquipment"),
    ),
    "dividends_paid": (
        ("us-gaap", "PaymentsOfDividends"),
        ("us-gaap", "PaymentsOfDividendsCommonStock"),
        ("ifrs-full", "DividendsPaidClassifiedAsFinancingActivities"),
        ("ifrs-full", "DividendsPaid"),
    ),
}

CompanyfactsFetcher = Callable[[int], dict[str, Any] | None]


def _parse_day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _is_annual_fact(fact: dict[str, Any]) -> bool:
    if str(fact.get("form") or "").upper() not in ANNUAL_FORMS:
        return False
    start = _parse_day(fact.get("start"))
    end = _parse_day(fact.get("end"))
    if start is None or end is None:
        return False
    return MIN_ANNUAL_DAYS <= (end - start).days <= MAX_ANNUAL_DAYS


def _currency_units(units: dict[str, Any]) -> list[str]:
    """Currency unit keys (``USD`` first); skips share / per-share units."""
    keys = [k for k in units if len(k) == 3 and k.isalpha() and k.isupper()]
    return sorted(keys, key=lambda k: (k != "USD", k))


def _annual_values_for_concept(concept_block: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Latest-filed annual value per period end for one concept."""
    units = concept_block.get("units") or {}
    out: dict[str, dict[str, Any]] = {}
    for unit in _currency_units(units):
        for fact in units.get(unit) or []:
            if not isinstance(fact, dict) or not _is_annual_fact(fact):
                continue
            try:
                value = float(fact["val"])
            except (KeyError, TypeError, ValueError):
                continue
            end = str(fact["end"])[:10]
            filed = str(fact.get("filed") or "")
            prior = out.get(end)
            row = {
                "value": value,
                "unit": unit,
                "form": str(fact.get("form") or ""),
                "filed": filed,
                "accn": str(fact.get("accn") or ""),
                "first_filed": filed if prior is None else min(prior["first_filed"], filed),
            }
            if prior is None or filed >= prior["filed"]:
                out[end] = row
            else:
                prior["first_filed"] = row["first_filed"]
        if out:
            break
    return out


def extract_annual_cashflow_facts(
    payload: dict[str, Any],
    *,
    max_periods: int = MAX_ANNUAL_PERIODS,
) -> list[dict[str, Any]]:
    """Annual OCF / capex / dividends per fiscal period end, newest first."""
    facts = payload.get("facts") or {}
    by_end: dict[str, dict[str, Any]] = {}
    for metric, concepts in METRIC_CONCEPTS.items():
        for taxonomy, concept in concepts:
            block = (facts.get(taxonomy) or {}).get(concept)
            if not isinstance(block, dict):
                continue
            for end, row in _annual_values_for_concept(block).items():
                period = by_end.setdefault(end, {"period_end": end})
                if metric in period:
                    continue
                period[metric] = {**row, "concept": f"{taxonomy}:{concept}"}

    periods: list[dict[str, Any]] = []
    for end in sorted(by_end, reverse=True):
        period = by_end[end]
        if "operating_cashflow" not in period:
            continue
        ocf = period["operating_cashflow"]
        capex = period.get("capital_expenditure")
        period["fiscal_year_label"] = end[:4]
        period["currency"] = ocf["unit"]
        period["free_cashflow"] = (
            ocf["value"] - abs(capex["value"])
            if capex is not None and capex["unit"] == ocf["unit"]
            else None
        )
        periods.append(period)
        if len(periods) >= max_periods:
            break
    return periods


def build_companyfacts_source(
    payload: dict[str, Any],
    *,
    ticker: str,
    cik: int,
    fetched_at: datetime | None = None,
) -> dict[str, Any]:
    annual = extract_annual_cashflow_facts(payload)
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "sec_companyfacts",
        "ticker": ticker.strip().upper(),
        "cik": int(cik),
        "entity_name": payload.get("entityName"),
        "url": COMPANYFACTS_URL.format(cik=int(cik)),
        "fetched_at": (fetched_at or datetime.now(UTC)).isoformat(),
        "note": (
            "Annual cash-flow facts as tagged in SEC 10-K/20-F/40-F XBRL (latest filed "
            "value per period; first_filed kept for point-in-time use). "
            "free_cashflow = operating_cashflow − capital_expenditure (PP&E only). "
            "Primary-filing figures: prefer over Yahoo financials_annual.json."
        ),
        "annual": annual,
        "latest": annual[0] if annual else None,
    }


def fetch_companyfacts(cik: int, *, timeout: int = 60) -> dict[str, Any] | None:
    from value_investor.research.filings import _http_get, _sec_user_agent

    try:
        raw = _http_get(
            COMPANYFACTS_URL.format(cik=int(cik)),
            headers={"User-Agent": _sec_user_agent(), "Accept": "application/json"},
            timeout=timeout,
        )
        payload = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            logger.warning("SEC companyfacts HTTP %s for CIK %s", exc.code, cik)
        return None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        logger.warning("SEC companyfacts fetch failed for CIK %s: %s", cik, exc)
        return None
    return payload if isinstance(payload, dict) else None


def load_companyfacts_source(sources_dir: Path) -> dict[str, Any] | None:
    resolved = resolve_json_path(Path(sources_dir) / SOURCE_FILENAME)
    if resolved is None:
        return None
    try:
        payload = read_json(resolved)
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def companyfacts_source_age_days(
    sources_dir: Path,
    *,
    now: datetime | None = None,
) -> float | None:
    payload = load_companyfacts_source(sources_dir)
    if not payload:
        return None
    try:
        fetched = datetime.fromisoformat(str(payload.get("fetched_at")).replace("Z", "+00:00"))
    except ValueError:
        return None
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=UTC)
    return ((now or datetime.now(UTC)) - fetched).total_seconds() / 86400.0


def refresh_sec_companyfacts_source(
    *,
    ticker: str,
    sources_dir: Path,
    cik: int | None = None,
    fetcher: CompanyfactsFetcher | None = None,
    cik_resolver: Callable[[str], int | None] | None = None,
) -> dict[str, Any]:
    """Fetch companyfacts for ``ticker`` and write ``sources/sec_companyfacts.json``."""
    normalized = ticker.strip().upper()
    if cik is None:
        if cik_resolver is None:
            from value_investor.research.filings import resolve_sec_cik as cik_resolver
        cik = cik_resolver(normalized)
    if cik is None:
        return {"written": False, "ticker": normalized, "note": "cik_unresolved"}
    payload = (fetcher or fetch_companyfacts)(int(cik))
    if not payload:
        return {"written": False, "ticker": normalized, "cik": int(cik), "note": "fetch_failed"}
    source = build_companyfacts_source(payload, ticker=normalized, cik=int(cik))
    if not source["annual"]:
        return {
            "written": False,
            "ticker": normalized,
            "cik": int(cik),
            "note": "no_annual_cashflow_facts",
        }
    path = Path(sources_dir) / SOURCE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, source, compact=True, compress=False)
    latest = source["latest"] or {}
    return {
        "written": True,
        "ticker": normalized,
        "cik": int(cik),
        "path": str(path),
        "latest_period_end": latest.get("period_end"),
        "latest_free_cashflow": latest.get("free_cashflow"),
        "periods": len(source["annual"]),
    }


@dataclass
class CompanyfactsBackfillResult:
    market_id: str
    candidates: int = 0
    attempted: list[str] = field(default_factory=list)
    written: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "market_id": self.market_id,
            "candidates": self.candidates,
            "attempted": len(self.attempted),
            "written": self.written,
            "failed": self.failed,
        }


def _memo_signal(ticker_dir: Path) -> str:
    try:
        payload = json.loads((ticker_dir / "research.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(payload.get("signal") or "") if isinstance(payload, dict) else ""


def backfill_candidates(
    research_dir: Path,
    *,
    max_age_days: float = DEFAULT_MAX_AGE_DAYS,
    now: datetime | None = None,
) -> list[tuple[str, Path]]:
    """Memo tickers missing or holding stale companyfacts, missing first, strong_buy first."""
    research_dir = Path(research_dir)
    if not research_dir.is_dir():
        return []
    ranked: list[tuple[tuple[int, int, str], str, Path]] = []
    for ticker_dir in sorted(p for p in research_dir.iterdir() if p.is_dir()):
        sources_dir = ticker_dir / "sources"
        if not sources_dir.is_dir():
            continue
        age = companyfacts_source_age_days(sources_dir, now=now)
        if age is not None and age < max_age_days:
            continue
        signal_rank = 0 if _memo_signal(ticker_dir) == "strong_buy" else 1
        ranked.append(
            ((0 if age is None else 1, signal_rank, ticker_dir.name), ticker_dir.name, sources_dir)
        )
    ranked.sort(key=lambda row: row[0])
    return [(ticker, sources_dir) for _, ticker, sources_dir in ranked]


def backfill_market_sec_companyfacts(
    market_id: str,
    *,
    library_root: Path,
    max_tickers: int = DEFAULT_BACKFILL_MAX_TICKERS,
    max_age_days: float = DEFAULT_MAX_AGE_DAYS,
    fetcher: CompanyfactsFetcher | None = None,
    cik_resolver: Callable[[str], int | None] | None = None,
    sleep_s: float = REQUEST_SLEEP_S,
) -> CompanyfactsBackfillResult:
    """Bounded companyfacts hydrate for one US library market's memo tickers."""
    from value_investor.research.market_store import committed_research_dir

    result = CompanyfactsBackfillResult(market_id=market_id)
    research_dir = committed_research_dir(market_id, library_root=Path(library_root))
    candidates = backfill_candidates(research_dir, max_age_days=max_age_days)
    result.candidates = len(candidates)
    for ticker, sources_dir in candidates[: max(0, int(max_tickers))]:
        result.attempted.append(ticker)
        try:
            meta = refresh_sec_companyfacts_source(
                ticker=ticker,
                sources_dir=sources_dir,
                fetcher=fetcher,
                cik_resolver=cik_resolver,
            )
        except Exception as exc:  # noqa: BLE001 — one name must not stop the batch
            result.failed[ticker] = str(exc)
            continue
        if meta.get("written"):
            result.written.append(ticker)
        else:
            result.failed[ticker] = str(meta.get("note") or "not_written")
        if sleep_s > 0:
            time.sleep(sleep_s)
    return result


def backfill_us_markets_sec_companyfacts(
    market_ids: Iterable[str],
    *,
    library_root: Path,
    max_tickers: int = DEFAULT_BACKFILL_MAX_TICKERS,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    return [
        backfill_market_sec_companyfacts(
            market_id,
            library_root=library_root,
            max_tickers=max_tickers,
            **kwargs,
        ).to_dict()
        for market_id in market_ids
        if market_id in US_SEC_MARKETS
    ]
