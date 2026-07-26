"""Deterministic ingest-only improvement pass before gap-fill."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.research.gap_fill import DEFAULT_SUGGESTIONS_PATH
from value_investor.research.gap_fill_sources import (
    ALTERNATE_SOURCE_CATALOG,
    _market_bucket,
    deepen_thin_filings_if_needed,
    execute_planned_alternate_sources,
    inspect_local_sources,
    suggest_alternate_sources,
)
from value_investor.research.ingest import ingest_research_sources
from value_investor.research.store import ResearchStore
from value_investor.storage import read_json, write_json
from value_investor.summary import CompanyReport

logger = logging.getLogger(__name__)

DEFAULT_INGEST_IMPROVEMENT_CAP = 5
KNOWN_SOURCE_IDS = frozenset(
    {
        "companies_house_accounts",
        "investegate_rns_full",
        "company_ir_presentation",
        "sec_exhibits",
        "exchange_filings_full",
    }
)

_SOURCE_KEYWORD_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "companies_house_accounts",
        (
            "companies house",
            "filed accounts",
            "filed-accounts",
            "ixbrl",
            "ch bodies",
            "ch pdf",
            "ocr companies house",
        ),
    ),
    (
        "investegate_rns_full",
        (
            "investegate",
            "rns direct",
            "lse rns",
            "google news redirect",
            "google news wrapper",
            "full investegate",
        ),
    ),
    (
        "company_ir_presentation",
        (
            "ir presentation",
            "results presentation",
            "investor relations",
            "investor pages",
            "company_ir",
            "annual report pdf",
            "results deck",
            "capital markets",
        ),
    ),
    (
        "sec_exhibits",
        (
            "sec ",
            "edgar",
            "20-f",
            "6-k",
            "10-k",
            "10-q",
            "sedar",
            "aif",
        ),
    ),
    (
        "exchange_filings_full",
        (
            "euronext",
            "asx announcement",
            "hkex",
            "exchange filing",
            "sedar+",
            "national register",
            "announcement full-text",
        ),
    ),
)


@dataclass
class IngestImprovementTarget:
    ticker: str
    name: str
    signal: str
    filings_total: int = 0
    filings_with_body: int = 0
    indexed_without_body: int = 0
    ingest_suggestion_count: int = 0
    priority_score: float = 0.0


@dataclass
class IngestImprovementSummary:
    targets: list[IngestImprovementTarget] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    improved: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "targets": [
                {
                    "ticker": target.ticker,
                    "name": target.name,
                    "signal": target.signal,
                    "filings_total": target.filings_total,
                    "filings_with_body": target.filings_with_body,
                    "indexed_without_body": target.indexed_without_body,
                    "ingest_suggestion_count": target.ingest_suggestion_count,
                    "priority_score": target.priority_score,
                }
                for target in self.targets
            ],
            "results": self.results,
            "improved": self.improved,
            "skipped": self.skipped,
            "errors": self.errors,
        }


def map_suggestion_to_source_ids(suggestion: str) -> list[str]:
    """Map free-text ingest suggestions to known alternate source fetcher ids."""
    text = str(suggestion or "").lower()
    matched: list[str] = []
    for source_id, keywords in _SOURCE_KEYWORD_RULES:
        if any(keyword in text for keyword in keywords):
            matched.append(source_id)
    return matched


def _load_ingest_suggestions(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.exists():
        return {}
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return {}
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for row in payload.get("suggestions") or []:
        if str(row.get("area") or "").lower() != "ingest":
            continue
        ticker = str(row.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        by_ticker.setdefault(ticker, []).append(row)
    return by_ticker


def _filing_coverage(store: ResearchStore, ticker: str) -> dict[str, int]:
    index_path = store.sources_dir(ticker) / "filings" / "filings_index.json"
    coverage = {
        "filings_total": 0,
        "filings_annual": 0,
        "filings_interim": 0,
        "filings_with_body": 0,
        "indexed_without_body": 0,
    }
    if not index_path.exists():
        return coverage
    try:
        index = read_json(index_path)
    except (OSError, ValueError, TypeError):
        return coverage
    summary = index.get("summary") or {}
    filings = list(index.get("filings") or [])
    coverage.update(
        {
            "filings_total": int(summary.get("total") or len(filings)),
            "filings_annual": int(summary.get("annual") or 0),
            "filings_interim": int(summary.get("interim") or 0),
            "filings_with_body": int(summary.get("with_body") or 0),
        }
    )
    coverage["indexed_without_body"] = sum(
        1 for row in filings if not row.get("has_body")
    )
    return coverage


def _priority_score(
    coverage: dict[str, int],
    suggestions: list[dict[str, Any]],
    *,
    signal: str,
) -> float:
    score = 0.0
    if coverage["filings_total"] == 0:
        score += 12.0
    elif coverage["indexed_without_body"] > 0:
        score += 6.0 + min(coverage["indexed_without_body"], 10)
    elif coverage["filings_with_body"] < max(1, coverage["filings_annual"]):
        score += 4.0
    for row in suggestions:
        priority = str(row.get("priority") or "").lower()
        if priority == "high":
            score += 3.0
        elif priority == "medium":
            score += 1.5
        else:
            score += 0.5
    if signal == "strong_buy":
        score += 2.0
    return score


def select_ingest_improvement_targets(
    reports: list[CompanyReport],
    *,
    output_dir: Path,
    suggestions_path: Path = DEFAULT_SUGGESTIONS_PATH,
    max_targets: int = DEFAULT_INGEST_IMPROVEMENT_CAP,
) -> list[IngestImprovementTarget]:
    """Rank buy-tier tickers that need ingest hardening before gap-fill."""
    store = ResearchStore(output_dir)
    suggestions_by_ticker = _load_ingest_suggestions(suggestions_path)
    candidates: list[IngestImprovementTarget] = []

    for report in reports:
        if report.signal not in ("strong_buy", "buy"):
            continue
        coverage = _filing_coverage(store, report.ticker)
        suggestions = suggestions_by_ticker.get(report.ticker.upper(), [])
        score = _priority_score(coverage, suggestions, signal=report.signal)
        if score <= 0:
            continue
        candidates.append(
            IngestImprovementTarget(
                ticker=report.ticker,
                name=report.name,
                signal=report.signal,
                filings_total=coverage["filings_total"],
                filings_with_body=coverage["filings_with_body"],
                indexed_without_body=coverage["indexed_without_body"],
                ingest_suggestion_count=len(suggestions),
                priority_score=score,
            )
        )

    candidates.sort(
        key=lambda row: (
            -row.priority_score,
            row.indexed_without_body,
            -row.ingest_suggestion_count,
        )
    )
    return candidates[: max(0, int(max_targets))]


def _catalog_item(source_id: str, *, market: str | None, ticker: str) -> dict[str, str] | None:
    bucket = _market_bucket(market, ticker)
    catalog = list(ALTERNATE_SOURCE_CATALOG.get(bucket) or [])
    catalog.extend(
        item
        for item in ALTERNATE_SOURCE_CATALOG["default"]
        if item["id"] not in {row["id"] for row in catalog}
    )
    for item in catalog:
        if item.get("id") == source_id:
            return dict(item)
    return None


def _planned_sources_for_ticker(
    *,
    ticker: str,
    market: str | None,
    inventory: dict[str, Any],
    ingest_suggestions: list[dict[str, Any]],
    open_questions: list[str] | None = None,
) -> list[dict[str, Any]]:
    questions = open_questions or [
        "Obtain annual and interim regulatory filing bodies for FINANCIAL REVIEW."
    ]
    ranked: dict[str, dict[str, Any]] = {}

    for row in ingest_suggestions:
        for source_id in map_suggestion_to_source_ids(str(row.get("suggestion") or "")):
            item = _catalog_item(source_id, market=market, ticker=ticker)
            if item is None:
                continue
            priority = str(row.get("priority") or "medium").lower()
            score = {"high": 5, "medium": 3, "low": 1}.get(priority, 2)
            existing = ranked.get(source_id)
            if existing is None or int(existing.get("score") or 0) < score:
                ranked[source_id] = {**item, "score": str(score)}

    for item in suggest_alternate_sources(
        ticker=ticker,
        market=market,
        inventory=inventory,
        open_questions=questions,
    ):
        source_id = str(item.get("id") or "")
        if source_id not in KNOWN_SOURCE_IDS:
            continue
        existing = ranked.get(source_id)
        candidate_score = int(item.get("score") or 0)
        if existing is None or int(existing.get("score") or 0) < candidate_score:
            ranked[source_id] = dict(item)

    planned = sorted(
        ranked.values(),
        key=lambda row: int(row.get("score") or 0),
        reverse=True,
    )
    return planned[:3]


def run_ingest_improvement_pass(
    *,
    reports: list[CompanyReport],
    output_dir: Path,
    market: str | None = None,
    max_targets: int = DEFAULT_INGEST_IMPROVEMENT_CAP,
    suggestions_path: Path = DEFAULT_SUGGESTIONS_PATH,
) -> IngestImprovementSummary:
    """
  Run bounded ingest hardening on thin buy-tier tickers before gap-fill.

  Uses only existing fetchers (Companies House, Investegate, IR PDFs, SEC/SEDAR).
  Does not modify scoring, prompts, or repository code.
    """
    targets = select_ingest_improvement_targets(
        reports,
        output_dir=output_dir,
        suggestions_path=suggestions_path,
        max_targets=max_targets,
    )
    summary = IngestImprovementSummary(targets=targets)
    if not targets:
        return summary

    store = ResearchStore(output_dir)
    suggestions_by_ticker = _load_ingest_suggestions(suggestions_path)

    for target in targets:
        try:
            report = next(
                (row for row in reports if row.ticker == target.ticker),
                None,
            )
            if report is None:
                summary.skipped += 1
                continue
            sources_dir = store.sources_dir(target.ticker)
            source_meta = ingest_research_sources(
                ticker=target.ticker,
                company_name=target.name,
                screening_snapshot=report.to_dict(),
                sources_dir=sources_dir,
                since=None,
                market=market,
                deepen_history=True,
            )
            inventory = inspect_local_sources(sources_dir)
            ingest_suggestions = suggestions_by_ticker.get(target.ticker.upper(), [])
            planned = _planned_sources_for_ticker(
                ticker=target.ticker,
                market=market,
                inventory=inventory,
                ingest_suggestions=ingest_suggestions,
            )
            mapped_source_ids = sorted(
                {
                    source_id
                    for row in ingest_suggestions
                    for source_id in map_suggestion_to_source_ids(
                        str(row.get("suggestion") or "")
                    )
                }
            )

            before = int(
                (inventory.get("filings_summary") or {}).get("with_body")
                or inventory.get("filings_indexed_bodies")
                or 0
            )
            alternate = execute_planned_alternate_sources(
                ticker=target.ticker,
                company_name=target.name,
                sources_dir=sources_dir,
                planned=planned,
                market=market,
            )
            deepen = deepen_thin_filings_if_needed(
                ticker=target.ticker,
                company_name=target.name,
                sources_dir=sources_dir,
                market=market,
                filings_summary=source_meta.get("filings_summary") or {},
            )
            after_inventory = inspect_local_sources(sources_dir)
            after = int(
                (after_inventory.get("filings_summary") or {}).get("with_body")
                or after_inventory.get("filings_indexed_bodies")
                or before
            )
            improved = after > before
            if improved:
                summary.improved += 1
            elif deepen.get("skipped"):
                summary.skipped += 1

            summary.results.append(
                {
                    "ticker": target.ticker,
                    "name": target.name,
                    "with_body_before": before,
                    "with_body_after": after,
                    "improved": improved,
                    "mapped_source_ids": mapped_source_ids,
                    "planned_sources": [row.get("id") for row in planned],
                    "alternate_sources": alternate,
                    "deepen": deepen,
                }
            )
        except Exception as exc:  # noqa: BLE001
            message = f"{target.ticker}: {exc}"
            logger.exception("Ingest improvement pass failed for %s", target.ticker)
            summary.errors.append(message)

    write_json(
        output_dir / "ingest_improvement_summary.json",
        {
            "run_at": datetime.now(UTC).isoformat(),
            **summary.to_dict(),
        },
        compact=True,
    )
    return summary
