"""Scan-then-target filing discovery for maintenance ingest.

Cheap listing-only discovery across buy-tier names, diff vs local
``filings_index.json``, merge new index rows without body download, then hand
hits to the existing deepen/select path.

Curiosity: novel filing ``source`` labels and unfamiliar URL hosts are recorded
so engineering never assumes a market's fetch surface is finished. Prioritization
weights are explicit for later compute throttling; defaults do not throttle.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from value_investor.research.companies_house import fetch_filings_companies_house
from value_investor.research.filings import (
    _load_prior_filings_rows,
    fetch_filings_investegate_company,
    fetch_filings_ir_allowlist,
    fetch_filings_ticker_api,
    merge_filings,
    summarize_filings,
)
from value_investor.research.ingest_bootstrap import (
    canonical_filings_dir,
    prefer_filing_index_path,
)
from value_investor.storage import write_json
from value_investor.summary import CompanyReport

logger = logging.getLogger(__name__)

DEFAULT_DISCOVERY_CURIOSITY_PATH = Path("docs/data/ingest_discovery_curiosity.json")
DEFAULT_DISCOVERY_SCAN_SUMMARY_PATH = Path("docs/data/ingest_discovery_scan_summary.json")

# Known UK / shared filing row sources. Anything else is curiosity fuel.
KNOWN_FILING_SOURCES = frozenset(
    {
        "ticker_rns_api",
        "investegate_direct",
        "investegate_resolved",
        "companies_house",
        "google_news_investegate",
        "ir_allowlist",
        "sec_edgar",
        "asx_direct",
        "google_news_asx",
        "esef_direct",
        "belgium_official",
        "google_news_euro",
        "google_news_tsx",
        "google_news_asia",
    }
)

KNOWN_URL_HOST_SUFFIXES = (
    "investegate.co.uk",
    "londonstockexchange.com",
    "companieshouse.gov.uk",
    "sec.gov",
    "xbrl.org",
    "euronext.com",
    "google.com",
    "news.google.com",
)

# Explicit weights — raise/lower later under compute constraints; no throttling today.
DEFAULT_PRIORITIZATION_WEIGHTS: dict[str, float] = {
    "new_index_rows": 8.0,
    "new_index_row_cap": 10.0,
    "unknown_source": 4.0,
    "unknown_host": 2.0,
    "strong_buy": 1.0,  # multiplier applied in score helper (additive bonus elsewhere)
}


@dataclass
class DiscoveryCuriosityItem:
    kind: str
    detail: str
    source: str | None = None
    url: str | None = None
    headline: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "detail": self.detail,
            "source": self.source,
            "url": self.url,
            "headline": self.headline,
        }


@dataclass
class TickerDiscoveryHit:
    ticker: str
    name: str
    signal: str
    new_row_count: int = 0
    new_rows: list[dict[str, Any]] = field(default_factory=list)
    curiosity: list[DiscoveryCuriosityItem] = field(default_factory=list)
    listed_count: int = 0
    prior_count: int = 0
    error: str | None = None

    @property
    def has_work(self) -> bool:
        return self.new_row_count > 0 or bool(self.curiosity)

    def priority_bonus(self, weights: dict[str, float] | None = None) -> float:
        w = {**DEFAULT_PRIORITIZATION_WEIGHTS, **(weights or {})}
        bonus = 0.0
        if self.new_row_count > 0:
            bonus += float(w["new_index_rows"]) + min(
                self.new_row_count, float(w["new_index_row_cap"])
            )
        unknown_sources = sum(1 for c in self.curiosity if c.kind == "unknown_source")
        unknown_hosts = sum(1 for c in self.curiosity if c.kind == "unknown_host")
        bonus += unknown_sources * float(w["unknown_source"])
        bonus += unknown_hosts * float(w["unknown_host"])
        return bonus

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "signal": self.signal,
            "new_row_count": self.new_row_count,
            "listed_count": self.listed_count,
            "prior_count": self.prior_count,
            "priority_bonus": self.priority_bonus(),
            "curiosity": [item.to_dict() for item in self.curiosity],
            "new_row_ids": [str(r.get("id") or "") for r in self.new_rows[:20]],
            "error": self.error,
        }


@dataclass
class DiscoveryScanSummary:
    scanned: int = 0
    hits: int = 0
    new_rows_total: int = 0
    curiosity_total: int = 0
    errors: int = 0
    tickers: list[TickerDiscoveryHit] = field(default_factory=list)
    prioritization_weights: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_PRIORITIZATION_WEIGHTS)
    )
    runtime_cutoff: bool = False
    note: str = (
        "Scan-then-target: listing-only discovery; deepen uses existing ingest pass. "
        "Library sprint caps discovery wall-clock so body deepen still runs. "
        "Engineering fetch surface is never assumed complete."
    )

    def hits_by_ticker(self) -> dict[str, TickerDiscoveryHit]:
        return {hit.ticker.upper(): hit for hit in self.tickers if hit.has_work}

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "hits": self.hits,
            "new_rows_total": self.new_rows_total,
            "curiosity_total": self.curiosity_total,
            "errors": self.errors,
            "runtime_cutoff": self.runtime_cutoff,
            "prioritization_weights": dict(self.prioritization_weights),
            "note": self.note,
            "tickers": [hit.to_dict() for hit in self.tickers],
        }


def _filing_row_keys(row: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    row_id = str(row.get("id") or "").strip().lower()
    if row_id:
        keys.add(f"id:{row_id}")
    url = str(row.get("url") or "").strip().lower()
    if url:
        keys.add(f"url:{url}")
    headline = (row.get("headline") or "").strip().lower()
    published = (str(row.get("published_at") or ""))[:10]
    if headline:
        keys.add(f"hp:{headline}|{published}")
    return keys


def _index_key_set(rows: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for row in rows:
        keys |= _filing_row_keys(row)
    return keys


def _host_is_known(host: str) -> bool:
    host = (host or "").strip().lower().removeprefix("www.")
    if not host:
        return True
    return any(host == suffix or host.endswith("." + suffix) for suffix in KNOWN_URL_HOST_SUFFIXES)


def collect_curiosity_for_rows(
    rows: list[dict[str, Any]],
    *,
    known_sources: frozenset[str] = KNOWN_FILING_SOURCES,
) -> list[DiscoveryCuriosityItem]:
    """Flag novel sources / hosts so we stay curious about fetch surface growth."""
    items: list[DiscoveryCuriosityItem] = []
    seen: set[str] = set()
    for row in rows:
        source = str(row.get("source") or "").strip()
        if source and source not in known_sources:
            key = f"source:{source}"
            if key not in seen:
                seen.add(key)
                items.append(
                    DiscoveryCuriosityItem(
                        kind="unknown_source",
                        detail=f"Filing source {source!r} not in known UK/shared catalog",
                        source=source,
                        url=str(row.get("url") or "") or None,
                        headline=str(row.get("headline") or "") or None,
                    )
                )
        url = str(row.get("url") or "").strip()
        if url:
            host = urlparse(url).hostname or ""
            if host and not _host_is_known(host):
                key = f"host:{host.lower()}"
                if key not in seen:
                    seen.add(key)
                    items.append(
                        DiscoveryCuriosityItem(
                            kind="unknown_host",
                            detail=f"Unfamiliar filing URL host {host!r}",
                            source=source or None,
                            url=url,
                            headline=str(row.get("headline") or "") or None,
                        )
                    )
    return items


def list_uk_filings_index_only(
    *,
    ticker: str,
    company_name: str,
    max_ch_accounts: int = 8,
    max_rns_items: int = 40,
    max_investegate_items: int = 40,
) -> list[dict[str, Any]]:
    """Cheap UK listing fetch — no body download."""
    groups: list[list[dict[str, Any]]] = [
        fetch_filings_ticker_api(
            ticker=ticker,
            company_name=company_name,
            max_items=max_rns_items,
        ),
        fetch_filings_investegate_company(
            ticker=ticker,
            company_name=company_name,
            max_items=max_investegate_items,
        ),
        fetch_filings_companies_house(
            ticker=ticker,
            company_name=company_name,
            max_accounts=max_ch_accounts,
        ),
        fetch_filings_ir_allowlist(ticker),
    ]
    return merge_filings(*groups)


def merge_discovery_into_index(
    *,
    filings_dir: Path,
    ticker: str,
    company_name: str,
    discovered: list[dict[str, Any]],
    market: str | None = "ftse350",
) -> dict[str, Any]:
    """
    Merge listing-only rows into ``filings_index.json`` without downloading bodies.

    Preserves existing ``has_body`` / ``body_path`` via ``merge_filings`` preference.
    """
    filings_dir = Path(filings_dir)
    filings_dir.mkdir(parents=True, exist_ok=True)
    prior = _load_prior_filings_rows(filings_dir)
    # Ensure discovered rows stay body-less so we do not clobber existing bodies
    # unless merge prefers prior body-bearing rows (it does via +50 has_body score).
    cleaned_discovered = []
    for row in discovered:
        item = dict(row)
        if not item.get("has_body"):
            item["has_body"] = False
            item["body_path"] = None
        cleaned_discovered.append(item)
    merged = merge_filings(prior, cleaned_discovered)
    index = {
        "ticker": ticker,
        "company_name": company_name,
        "market": market,
        "regime": "uk_rns",
        "fetched_at": datetime.now(UTC).isoformat(),
        "note": (
            "Scan-then-target listing merge (no body download). "
            "Bodies filled by subsequent deepen pass."
        ),
        "sources_used": sorted({str(r.get("source")) for r in merged if r.get("source")}),
        "summary": summarize_filings(merged),
        "filings": merged,
        "discovery_scan_at": datetime.now(UTC).isoformat(),
    }
    write_json(filings_dir / "filings_index.json", index, compact=True, compress=False)
    return {
        "prior_count": len(prior),
        "listed_count": len(discovered),
        "merged_count": len(merged),
        "summary": index["summary"],
    }


def scan_ticker_for_new_filings(
    report: CompanyReport,
    *,
    output_dir: Path,
    market: str | None = "ftse350",
    persist_index: bool = True,
) -> TickerDiscoveryHit:
    """List UK sources for one ticker, diff vs local index, optionally merge."""
    hit = TickerDiscoveryHit(
        ticker=report.ticker,
        name=report.name,
        signal=report.signal,
    )
    index_path = prefer_filing_index_path(report.ticker, output_dir=output_dir)
    if index_path is not None:
        filings_dir = Path(index_path).parent
    else:
        filings_dir = canonical_filings_dir(output_dir, report.ticker)
    prior = _load_prior_filings_rows(filings_dir)
    hit.prior_count = len(prior)
    prior_keys = _index_key_set(prior)

    try:
        discovered = list_uk_filings_index_only(
            ticker=report.ticker,
            company_name=report.name,
        )
    except Exception as exc:  # noqa: BLE001 — scan must not abort the weekday loop
        hit.error = str(exc)
        logger.warning("Discovery scan failed for %s: %s", report.ticker, exc)
        return hit

    hit.listed_count = len(discovered)
    new_rows: list[dict[str, Any]] = []
    for row in discovered:
        keys = _filing_row_keys(row)
        if keys and keys.isdisjoint(prior_keys):
            new_rows.append(row)
    hit.new_rows = new_rows
    hit.new_row_count = len(new_rows)
    # Curiosity across all listed rows (not only new) so recurring novel sources surface
    hit.curiosity = collect_curiosity_for_rows(discovered)

    if persist_index and (new_rows or prior):
        try:
            merge_discovery_into_index(
                filings_dir=filings_dir,
                ticker=report.ticker,
                company_name=report.name,
                discovered=discovered,
                market=market,
            )
        except Exception as exc:  # noqa: BLE001
            hit.error = (hit.error or "") + f"; merge failed: {exc}"
            logger.warning("Discovery merge failed for %s: %s", report.ticker, exc)

    return hit


def run_buy_tier_discovery_scan(
    reports: list[CompanyReport],
    *,
    output_dir: Path,
    market: str | None = "ftse350",
    scan_cap: int | None = None,
    persist_index: bool = True,
    persist_summary: bool = True,
    summary_path: Path = DEFAULT_DISCOVERY_SCAN_SUMMARY_PATH,
    curiosity_path: Path = DEFAULT_DISCOVERY_CURIOSITY_PATH,
    weights: dict[str, float] | None = None,
) -> DiscoveryScanSummary:
    """
    Scan buy-tier tickers for new listing rows (no body download).

    ``scan_cap`` is reserved for later compute throttling; ``None`` means all
    buy-tier names (no throttle).
    """
    buy = [row for row in reports if row.signal in ("strong_buy", "buy")]
    buy.sort(
        key=lambda row: (0 if row.signal == "strong_buy" else 1, -row.conviction_score, row.ticker)
    )
    if scan_cap is not None and scan_cap >= 0:
        buy = buy[: int(scan_cap)]

    summary = DiscoveryScanSummary(
        prioritization_weights={**DEFAULT_PRIORITIZATION_WEIGHTS, **(weights or {})}
    )
    for report in buy:
        hit = scan_ticker_for_new_filings(
            report,
            output_dir=output_dir,
            market=market,
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
            "market": market,
            "scan_cap": scan_cap,
            **summary.to_dict(),
        }
        write_json(summary_path, payload, compact=False)
        curiosity_payload = {
            "updated_at": datetime.now(UTC).isoformat(),
            "market": market,
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
        "Discovery scan: scanned=%d hits=%d new_rows=%d curiosity=%d errors=%d",
        summary.scanned,
        summary.hits,
        summary.new_rows_total,
        summary.curiosity_total,
        summary.errors,
    )
    return summary


__all__ = [
    "DEFAULT_DISCOVERY_CURIOSITY_PATH",
    "DEFAULT_DISCOVERY_SCAN_SUMMARY_PATH",
    "DEFAULT_PRIORITIZATION_WEIGHTS",
    "KNOWN_FILING_SOURCES",
    "DiscoveryCuriosityItem",
    "DiscoveryScanSummary",
    "TickerDiscoveryHit",
    "collect_curiosity_for_rows",
    "list_uk_filings_index_only",
    "merge_discovery_into_index",
    "run_buy_tier_discovery_scan",
    "scan_ticker_for_new_filings",
]
