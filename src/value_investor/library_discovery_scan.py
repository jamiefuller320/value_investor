"""Scan-then-target filing discovery for library markets (maintenance parity)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.data_library import DEFAULT_LIBRARY_ROOT
from value_investor.ingest_discovery_scan import (
    DiscoveryScanSummary,
    TickerDiscoveryHit,
    collect_curiosity_for_rows,
    merge_discovery_into_index,
)
from value_investor.library_screen import screen_dir_for
from value_investor.research.companies_house import fetch_filings_companies_house
from value_investor.research.filings import (
    _base_symbol,
    _load_prior_filings_rows,
    _sec_edgar_supplement_allowed,
    fetch_filings_asia_news,
    fetch_filings_asx_direct,
    fetch_filings_asx_news,
    fetch_filings_esef_direct,
    fetch_filings_euro_news,
    fetch_filings_investegate_company,
    fetch_filings_ir_allowlist,
    fetch_filings_sec_edgar,
    fetch_filings_ticker_api,
    fetch_filings_tsx_news,
    merge_filings,
    resolve_filings_regime,
)
from value_investor.research.store import ResearchStore
from value_investor.storage import write_json
from value_investor.summary import CompanyReport

logger = logging.getLogger(__name__)

LIBRARY_DISCOVERY_SUMMARY_PATH = Path(
    "docs/data/library/library_ingest_discovery_scan_summary.json"
)
LIBRARY_DISCOVERY_CURIOSITY_PATH = Path(
    "docs/data/library/library_ingest_discovery_curiosity.json"
)


def list_regime_filings_index_only(
    *,
    ticker: str,
    company_name: str,
    market: str | None = None,
) -> list[dict[str, Any]]:
    """Listing-only fetch for a ticker regime (no body download)."""
    regime = resolve_filings_regime(market, ticker)
    groups: list[list[dict[str, Any]]] = []

    if regime == "uk_rns":
        groups.extend(
            [
                fetch_filings_ticker_api(ticker=ticker, company_name=company_name),
                fetch_filings_investegate_company(ticker=ticker, company_name=company_name),
                fetch_filings_companies_house(ticker=ticker, company_name=company_name),
                fetch_filings_ir_allowlist(ticker),
            ]
        )
    elif regime == "sec_edgar":
        groups.append(fetch_filings_sec_edgar(ticker=ticker))
    elif regime == "asx_announcements":
        groups.extend(
            [
                fetch_filings_asx_direct(company_name=company_name, ticker=ticker),
                fetch_filings_asx_news(company_name=company_name, ticker=ticker),
            ]
        )
    elif regime == "euro_filings":
        groups.extend(
            [
                fetch_filings_esef_direct(company_name=company_name, ticker=ticker),
                fetch_filings_euro_news(company_name=company_name, ticker=ticker, market=market),
                fetch_filings_investegate_company(ticker=ticker, company_name=company_name),
            ]
        )
        if _sec_edgar_supplement_allowed(ticker, company_name):
            groups.append(
                fetch_filings_sec_edgar(
                    ticker=_base_symbol(ticker),
                    include_current_reports=False,
                )
            )
    elif regime == "tsx_announcements":
        groups.append(fetch_filings_tsx_news(company_name=company_name, ticker=ticker))
    elif regime == "asia_filings":
        groups.append(fetch_filings_asia_news(company_name=company_name, ticker=ticker))
    else:
        logger.debug("No listing regime for market=%s ticker=%s", market, ticker)

    groups.append(fetch_filings_ir_allowlist(ticker))
    return merge_filings(*groups) if groups else []


def _filing_row_keys(row: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for field in ("id", "url", "headline", "published_at"):
        value = str(row.get(field) or "").strip()
        if value:
            keys.add(f"{field}:{value}")
    return keys


def _index_key_set(rows: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for row in rows:
        out.update(_filing_row_keys(row))
    return out


def scan_library_ticker_for_new_filings(
    report: CompanyReport,
    *,
    library_root: Path,
    market_id: str,
    persist_index: bool = True,
) -> TickerDiscoveryHit:
    """Listing-only discovery for one library market ticker."""
    hit = TickerDiscoveryHit(
        ticker=report.ticker,
        name=report.name,
        signal=report.signal,
    )
    screen_dir = screen_dir_for(library_root, market_id)
    store = ResearchStore(screen_dir)
    sources_dir = store.sources_dir(report.ticker)
    filings_dir = sources_dir / "filings"
    filings_dir.mkdir(parents=True, exist_ok=True)

    prior = _load_prior_filings_rows(filings_dir)
    hit.prior_count = len(prior)
    prior_keys = _index_key_set(prior)

    try:
        discovered = list_regime_filings_index_only(
            ticker=report.ticker,
            company_name=report.name,
            market=market_id,
        )
    except Exception as exc:  # noqa: BLE001
        hit.error = str(exc)
        logger.warning("Library discovery scan failed for %s: %s", report.ticker, exc)
        return hit

    hit.listed_count = len(discovered)
    new_rows: list[dict[str, Any]] = []
    for row in discovered:
        keys = _filing_row_keys(row)
        if keys and keys.isdisjoint(prior_keys):
            new_rows.append(row)
    hit.new_rows = new_rows
    hit.new_row_count = len(new_rows)
    hit.curiosity = collect_curiosity_for_rows(discovered)

    if persist_index and (new_rows or prior):
        try:
            merge_discovery_into_index(
                filings_dir=filings_dir,
                ticker=report.ticker,
                company_name=report.name,
                discovered=discovered,
                market=market_id,
            )
        except Exception as exc:  # noqa: BLE001
            hit.error = (hit.error or "") + f"; merge failed: {exc}"
            logger.warning("Library discovery merge failed for %s: %s", report.ticker, exc)

    return hit


def run_library_buy_tier_discovery_scan(
    reports: list[CompanyReport],
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    market_id: str,
    scan_cap: int | None = None,
    persist_index: bool = True,
    persist_summary: bool = True,
    summary_path: Path = LIBRARY_DISCOVERY_SUMMARY_PATH,
    curiosity_path: Path = LIBRARY_DISCOVERY_CURIOSITY_PATH,
) -> DiscoveryScanSummary:
    """Scan library buy-tier tickers for new listing rows (no body download)."""
    buy = [row for row in reports if row.signal in ("strong_buy", "buy")]
    buy.sort(
        key=lambda row: (0 if row.signal == "strong_buy" else 1, -row.conviction_score, row.ticker)
    )
    if scan_cap is not None and scan_cap >= 0:
        buy = buy[: int(scan_cap)]

    summary = DiscoveryScanSummary()
    for report in buy:
        hit = scan_library_ticker_for_new_filings(
            report,
            library_root=library_root,
            market_id=market_id,
            persist_index=persist_index,
        )
        summary.scanned += 1
        summary.tickers.append(hit)
        if hit.error:
            summary.errors += 1
        if hit.has_work:
            summary.hits += 1
        summary.new_rows_total += hit.new_row_count
        summary.curiosity_total += len(hit.curiosity)

    if persist_summary:
        payload = {
            "run_at": datetime.now(UTC).isoformat(),
            "market_id": market_id,
            "scan_cap": scan_cap,
            **summary.to_dict(),
        }
        write_json(summary_path, payload, compact=False)
        curiosity_payload = {
            "updated_at": datetime.now(UTC).isoformat(),
            "market_id": market_id,
            "note": summary.note,
            "prioritization_weights": summary.prioritization_weights,
            "engineering_never_complete": True,
            "entries": [
                {
                    "ticker": hit.ticker,
                    "signal": hit.signal,
                    "curiosity": [c.to_dict() for c in hit.curiosity],
                    "new_row_count": hit.new_row_count,
                }
                for hit in summary.tickers
                if hit.curiosity
            ],
        }
        write_json(curiosity_path, curiosity_payload, compact=False)

    logger.info(
        "Library discovery scan %s: scanned=%d hits=%d new_rows=%d curiosity=%d errors=%d",
        market_id,
        summary.scanned,
        summary.hits,
        summary.new_rows_total,
        summary.curiosity_total,
        summary.errors,
    )
    return summary


__all__ = [
    "LIBRARY_DISCOVERY_CURIOSITY_PATH",
    "LIBRARY_DISCOVERY_SUMMARY_PATH",
    "list_regime_filings_index_only",
    "run_library_buy_tier_discovery_scan",
    "scan_library_ticker_for_new_filings",
]
