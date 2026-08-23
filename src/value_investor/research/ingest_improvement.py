"""Deterministic ingest-only improvement pass before gap-fill."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.ingest_backlog import (
    DEFAULT_BACKLOG_PATH,
    backlog_tickers,
    load_ingest_backlog,
    prioritize_backlog_targets,
    record_ingest_backlog_after_pass,
)
from value_investor.research.filings import (
    fetch_filings_ir_allowlist,
    period_body_coverage,
    refetch_ir_allowlist_filing_bodies,
    refetch_residual_filing_bodies,
    refetch_uk_primary_filing_bodies,
    sanitize_filings_index,
)
from value_investor.research.gap_fill import DEFAULT_SUGGESTIONS_PATH
from value_investor.research.gap_fill_sources import (
    ALTERNATE_SOURCE_CATALOG,
    _market_bucket,
    attach_screen_run_manifest,
    deepen_thin_filings_if_needed,
    execute_planned_alternate_sources,
    inspect_local_sources,
    suggest_alternate_sources,
)
from value_investor.research.ingest import ingest_research_sources, install_fetch_cashflow_fallback
from value_investor.research.ingest_bootstrap import (
    BOOTSTRAP_SEED_CAP,
    bootstrap_buy_tier_research,
    canonical_sources_dir,
    prefer_filing_index_path,
)
from value_investor.research.store import ResearchStore
from value_investor.storage import read_json, resolve_json_path, write_json
from value_investor.summary import CompanyReport

logger = logging.getLogger(__name__)

DEFAULT_INGEST_IMPROVEMENT_CAP = 15
DEFAULT_WEEKDAY_BATCH_MAX_TARGETS = 12
DEFAULT_WEEKDAY_BOOTSTRAP_SEED_CAP = 6
DEFAULT_PER_TICKER_MAX_SECONDS = 320.0
PER_TICKER_MIN_BUDGET_SECONDS = 120.0
DEFAULT_INGEST_REFETCH_MAX_BODIES = 20
DEFAULT_BACKFILL_MAX_BODIES = 40
UNMEASURED_PRIORITY_BONUS = 10.0
# Buy-tier tickers with recurring indexed-without-body gaps — batch-prioritized in ingest pass.
BODY_GAP_BATCH_TICKERS = frozenset({"ITV.L", "GFTU.L", "MGNS.L", "AEP.L"})
BODY_GAP_BATCH_PRIORITY_BONUS = 8.0
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
            "consolidated statement",
            "consolidated cash-flow",
            "cash-flow statement",
            "pension note",
            "borrowings",
            "covenant",
            "segment note",
            "segment information",
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
            "allowlisted ir",
            "ir allowlist",
            "ir url",
            "cash-flow note",
            "cash flow statement",
            "exceptional item",
            "related party",
            "segment information",
            "geographic segment",
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
    partial: bool = False
    runtime_seconds: float = 0.0
    runtime_cutoff: bool = False
    targets_planned: int = 0
    targets_completed: int = 0
    targets_deferred: int = 0
    cutoff_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
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
            "partial": self.partial,
            "runtime_seconds": round(self.runtime_seconds, 1),
            "runtime_cutoff": self.runtime_cutoff,
            "targets_planned": self.targets_planned,
            "targets_completed": self.targets_completed,
            "targets_deferred": self.targets_deferred,
            "cutoff_reason": self.cutoff_reason,
        }
        return payload


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


def _resolve_sources_dir(store: ResearchStore, ticker: str, output_dir: Path) -> Path:
    return canonical_sources_dir(output_dir, ticker)


def _filing_coverage(store: ResearchStore, ticker: str, output_dir: Path) -> dict[str, int]:
    from value_investor.engineering_queue import _coverage_from_index

    coverage = {
        "filings_total": 0,
        "filings_annual": 0,
        "filings_interim": 0,
        "filings_trading_update": 0,
        "filings_with_body": 0,
        "indexed_without_body": 0,
        "annual_with_body": 0,
        "interim_with_body": 0,
        "trading_update_with_body": 0,
    }
    index_path = prefer_filing_index_path(ticker, output_dir=output_dir)
    if index_path is None:
        return coverage
    measured = _coverage_from_index(index_path)
    coverage.update(measured)
    try:
        index = read_json(index_path)
        filings = list(index.get("filings") or [])
        summary = index.get("summary") or {}
        coverage["filings_annual"] = int(summary.get("annual") or 0)
        coverage["filings_interim"] = int(summary.get("interim") or 0)
        coverage["filings_trading_update"] = int(summary.get("trading_update") or 0)
        coverage["indexed_without_body"] = sum(1 for row in filings if not row.get("has_body"))
        period_cov = period_body_coverage(filings)
        coverage["annual_with_body"] = int(period_cov["annual"]["with_body"])
        coverage["interim_with_body"] = int(period_cov["interim"]["with_body"])
        coverage["trading_update_with_body"] = int(period_cov["trading_update"]["with_body"])
    except (OSError, ValueError, TypeError):
        pass
    return coverage


def _is_uk_listed(*, market: str | None, ticker: str) -> bool:
    return _market_bucket(market, ticker) == "uk"


def _has_outstanding_ingest_gap(coverage: dict[str, int]) -> bool:
    """True when indexed filings or period buckets still lack bodies."""
    if coverage["filings_total"] == 0:
        return True
    if coverage["indexed_without_body"] > 0:
        return True
    if coverage["filings_with_body"] == 0 and coverage["filings_total"] > 0:
        return True
    annual_gap = max(
        0,
        coverage["filings_annual"] - coverage.get("annual_with_body", 0),
    )
    interim_gap = max(
        0,
        coverage["filings_interim"] - coverage.get("interim_with_body", 0),
    )
    trading_gap = max(
        0,
        coverage.get("filings_trading_update", 0) - coverage.get("trading_update_with_body", 0),
    )
    return annual_gap > 0 or interim_gap > 0 or trading_gap > 0


def _priority_score(
    coverage: dict[str, int],
    suggestions: list[dict[str, Any]],
    *,
    signal: str,
    market: str | None = None,
    ticker: str = "",
) -> float:
    score = 0.0
    if coverage["filings_total"] == 0:
        score += 12.0 + UNMEASURED_PRIORITY_BONUS
    elif coverage["indexed_without_body"] > 0:
        score += 6.0 + min(coverage["indexed_without_body"], 10)
    else:
        annual_gap = max(
            0,
            coverage["filings_annual"] - coverage.get("annual_with_body", 0),
        )
        interim_gap = max(
            0,
            coverage["filings_interim"] - coverage.get("interim_with_body", 0),
        )
        if annual_gap > 0:
            score += 4.0 + min(annual_gap, 5)
        if interim_gap > 0:
            score += 2.0 + min(interim_gap, 3)
        trading_gap = max(
            0,
            coverage.get("filings_trading_update", 0) - coverage.get("trading_update_with_body", 0),
        )
        if trading_gap > 0:
            score += 0.5
    if (
        coverage["filings_with_body"] == 0
        and coverage["filings_total"] > 0
        and _is_uk_listed(market=market, ticker=ticker)
    ):
        score += 4.0
    if coverage["filings_with_body"] == 0 and coverage["filings_total"] > 0:
        score += 50.0
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
    if ticker.upper() in BODY_GAP_BATCH_TICKERS and coverage["indexed_without_body"] > 0:
        score += BODY_GAP_BATCH_PRIORITY_BONUS
    return score


def select_ingest_improvement_targets(
    reports: list[CompanyReport],
    *,
    output_dir: Path,
    suggestions_path: Path = DEFAULT_SUGGESTIONS_PATH,
    max_targets: int = DEFAULT_INGEST_IMPROVEMENT_CAP,
    backlog_tickers: list[str] | None = None,
    require_outstanding_gaps: bool = False,
    pin_tickers: list[str] | None = None,
) -> list[IngestImprovementTarget]:
    """Rank buy-tier tickers that need ingest hardening before gap-fill."""
    store = ResearchStore(output_dir)
    suggestions_by_ticker = _load_ingest_suggestions(suggestions_path)
    candidates: list[IngestImprovementTarget] = []
    pin_set = {str(t or "").strip().upper() for t in (pin_tickers or []) if str(t or "").strip()}

    for report in reports:
        if report.signal not in ("strong_buy", "buy"):
            continue
        if pin_set and report.ticker.upper() not in pin_set:
            continue
        coverage = _filing_coverage(store, report.ticker, output_dir)
        suggestions = suggestions_by_ticker.get(report.ticker.upper(), [])
        score = _priority_score(
            coverage,
            suggestions,
            signal=report.signal,
            market="ftse350" if report.ticker.upper().endswith(".L") else None,
            ticker=report.ticker,
        )
        if score <= 0:
            continue
        if require_outstanding_gaps and not _has_outstanding_ingest_gap(coverage):
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
    if backlog_tickers:
        candidates = prioritize_backlog_targets(candidates, backlog_tickers)
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
    filings_with_body: int | None = None,
) -> list[dict[str, Any]]:
    questions = open_questions or [
        "Obtain annual and interim regulatory filing bodies for FINANCIAL REVIEW."
    ]
    ranked: dict[str, dict[str, Any]] = {}
    with_body = (
        int(filings_with_body)
        if filings_with_body is not None
        else int((inventory.get("filings_summary") or {}).get("with_body") or 0)
    )

    if _is_uk_listed(market=market, ticker=ticker) and with_body == 0:
        ch_item = _catalog_item("companies_house_accounts", market=market, ticker=ticker)
        if ch_item is not None:
            ranked["companies_house_accounts"] = {**ch_item, "score": "10"}

    if fetch_filings_ir_allowlist(ticker):
        ir_item = _catalog_item("company_ir_presentation", market=market, ticker=ticker)
        if ir_item is not None:
            existing = ranked.get("company_ir_presentation")
            score = "8"
            if existing is None or int(existing.get("score") or 0) < int(score):
                ranked["company_ir_presentation"] = {**ir_item, "score": score}

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


def _ingest_pass_should_cutoff(
    started: float,
    *,
    max_runtime_seconds: float | None,
    per_ticker_max_seconds: float | None,
) -> tuple[bool, str | None]:
    if max_runtime_seconds is None:
        return False, None
    elapsed = time.monotonic() - started
    if elapsed >= max_runtime_seconds:
        return True, "runtime_budget"
    if (
        per_ticker_max_seconds is not None
        and elapsed + per_ticker_max_seconds > max_runtime_seconds
    ):
        return True, "per_ticker_budget"
    return False, None


def _finalize_ingest_cutoff(summary: IngestImprovementSummary, reason: str | None) -> None:
    summary.partial = True
    summary.runtime_cutoff = True
    summary.cutoff_reason = reason
    summary.targets_planned = len(summary.targets)
    summary.targets_completed = len(summary.results)
    summary.targets_deferred = max(0, summary.targets_planned - summary.targets_completed)


def run_ingest_improvement_pass(
    *,
    reports: list[CompanyReport],
    output_dir: Path,
    market: str | None = None,
    max_targets: int = DEFAULT_INGEST_IMPROVEMENT_CAP,
    suggestions_path: Path = DEFAULT_SUGGESTIONS_PATH,
    bootstrap_seed_cap: int | None = None,
    max_runtime_seconds: float | None = None,
    per_ticker_max_seconds: float | None = DEFAULT_PER_TICKER_MAX_SECONDS,
    backlog_path: Path = DEFAULT_BACKLOG_PATH,
    max_bodies: int = DEFAULT_INGEST_REFETCH_MAX_BODIES,
    require_outstanding_gaps: bool = False,
    pin_tickers: list[str] | None = None,
    intensive_gap_closure: bool = False,
    prune_failed_residual_fetches: bool = False,
) -> IngestImprovementSummary:
    """
    Run bounded ingest hardening on thin buy-tier tickers before gap-fill.

    Uses only existing fetchers (Companies House, Investegate, IR PDFs, SEC/SEDAR).
    Does not modify scoring, prompts, or repository code.
    """
    bootstrap_buy_tier_research(
        reports,
        output_dir=output_dir,
        market=market,
        seed_cap=bootstrap_seed_cap if bootstrap_seed_cap is not None else BOOTSTRAP_SEED_CAP,
    )
    backlog_payload = load_ingest_backlog(backlog_path)
    pending_backlog = backlog_tickers(backlog_payload)
    targets = select_ingest_improvement_targets(
        reports,
        output_dir=output_dir,
        suggestions_path=suggestions_path,
        max_targets=max_targets,
        backlog_tickers=pending_backlog or None,
        require_outstanding_gaps=require_outstanding_gaps,
        pin_tickers=pin_tickers,
    )
    summary = IngestImprovementSummary(targets=targets)
    summary.targets_planned = len(targets)
    if not targets:
        record_ingest_backlog_after_pass(
            targets=[],
            completed_tickers=[],
            runtime_cutoff=False,
            path=backlog_path,
        )
        return summary

    store = ResearchStore(output_dir)
    suggestions_by_ticker = _load_ingest_suggestions(suggestions_path)
    started = time.monotonic()

    for target in targets:
        should_cutoff, cutoff_reason = _ingest_pass_should_cutoff(
            started,
            max_runtime_seconds=max_runtime_seconds,
            per_ticker_max_seconds=per_ticker_max_seconds,
        )
        if should_cutoff:
            _finalize_ingest_cutoff(summary, cutoff_reason)
            logger.warning(
                "Ingest improvement stopped (%s) after %.0fs runtime budget (max=%.0fs)",
                cutoff_reason or "cutoff",
                time.monotonic() - started,
                max_runtime_seconds or 0,
            )
            break

        try:
            report = next(
                (row for row in reports if row.ticker == target.ticker),
                None,
            )
            if report is None:
                summary.skipped += 1
                continue
            sources_dir = _resolve_sources_dir(store, target.ticker, output_dir)
            sources_dir.mkdir(parents=True, exist_ok=True)
            sanitize_filings_index(
                sources_dir / "filings",
                company_name=target.name,
                ticker=target.ticker,
            )
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
            before = int(
                (inventory.get("filings_summary") or {}).get("with_body")
                or inventory.get("filings_indexed_bodies")
                or 0
            )
            ch_refetch: dict[str, Any] = {}
            investegate_refetch: dict[str, Any] = {}
            ticker_rns_refetch: dict[str, Any] = {}
            indexed_refetch: dict[str, Any] = {}
            residual_refetch: dict[str, Any] = {}
            if _is_uk_listed(market=market, ticker=target.ticker):
                primary_refetch = refetch_uk_primary_filing_bodies(
                    sources_dir / "filings",
                    ticker=target.ticker,
                    company_name=target.name,
                    max_bodies=max_bodies,
                )
                ch_refetch = dict(primary_refetch.get("companies_house") or {})
                indexed_refetch = dict(primary_refetch.get("rns") or {})
                investegate_refetch = dict(indexed_refetch.get("investegate") or {})
                ticker_rns_refetch = dict(indexed_refetch.get("ticker_rns") or {})
                residual_refetch = dict(primary_refetch.get("residual") or {})
                if int(primary_refetch.get("fetched") or 0) > 0:
                    inventory = inspect_local_sources(sources_dir)
                    before = int(
                        (inventory.get("filings_summary") or {}).get("with_body")
                        or inventory.get("filings_indexed_bodies")
                        or before
                    )
            else:
                residual_refetch = refetch_residual_filing_bodies(
                    sources_dir / "filings",
                    ticker=target.ticker,
                    company_name=target.name,
                    max_bodies=max_bodies,
                    prune_unfetchable_after_attempt=prune_failed_residual_fetches,
                )
                if int(residual_refetch.get("fetched") or 0) > 0:
                    inventory = inspect_local_sources(sources_dir)
                    before = int(
                        (inventory.get("filings_summary") or {}).get("with_body")
                        or inventory.get("filings_indexed_bodies")
                        or before
                    )
            planned = _planned_sources_for_ticker(
                ticker=target.ticker,
                market=market,
                inventory=inventory,
                ingest_suggestions=ingest_suggestions,
                filings_with_body=before,
            )
            ir_refetch: dict[str, Any] = {}
            ir_presentation_metrics: dict[str, Any] = {}
            ir_allowlist_rows = fetch_filings_ir_allowlist(target.ticker)
            if ir_allowlist_rows:
                ir_refetch = refetch_ir_allowlist_filing_bodies(
                    sources_dir / "filings",
                    target.ticker,
                    company_name=target.name,
                    max_bodies=max_bodies,
                )
                ir_refetch["mandatory"] = True
                ir_refetch["allowlist_count"] = len(ir_allowlist_rows)
                from value_investor.research.filings import extract_ir_presentation_metrics

                ir_presentation_metrics = extract_ir_presentation_metrics(
                    sources_dir / "filings",
                    target.ticker,
                    sources_dir=sources_dir,
                )
                if int(ir_refetch.get("fetched") or 0) > 0:
                    inventory = inspect_local_sources(sources_dir)
                    before = int(
                        (inventory.get("filings_summary") or {}).get("with_body")
                        or inventory.get("filings_indexed_bodies")
                        or before
                    )
            screen_run_manifest = attach_screen_run_manifest(
                sources_dir,
                target.ticker,
                market=market,
            )
            mapped_source_ids = sorted(
                {
                    source_id
                    for row in ingest_suggestions
                    for source_id in map_suggestion_to_source_ids(str(row.get("suggestion") or ""))
                }
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
            from value_investor.research.filings import reconcile_filings_index_body_flags

            reconcile_filings_index_body_flags(
                sources_dir / "filings",
                company_name=target.name,
                ticker=target.ticker,
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
                    "quarterly_cashflow_usable": bool(
                        (after_inventory.get("available") or {}).get("yahoo_quarterly_cashflow")
                    ),
                    "quarterly_income_usable": bool(
                        (after_inventory.get("available") or {}).get("yahoo_quarterly_income")
                    ),
                    "ttm_cashflow_suppressed": bool(
                        (
                            read_json(sources_dir / "financials_annual.json").get(
                                "cashflow_metrics"
                            )
                            or {}
                        ).get("ttm_cashflow_suppressed")
                        if resolve_json_path(sources_dir / "financials_annual.json") is not None
                        else False
                    ),
                    "mapped_source_ids": mapped_source_ids,
                    "planned_sources": [row.get("id") for row in planned],
                    "ch_refetch": ch_refetch,
                    "investegate_refetch": investegate_refetch,
                    "ticker_rns_refetch": ticker_rns_refetch,
                    "indexed_refetch": indexed_refetch,
                    "residual_refetch": residual_refetch,
                    "ir_refetch": ir_refetch,
                    "ir_presentation_metrics": ir_presentation_metrics,
                    "screen_run_manifest": screen_run_manifest,
                    "alternate_sources": alternate,
                    "deepen": deepen,
                }
            )
        except Exception as exc:  # noqa: BLE001
            message = f"{target.ticker}: {exc}"
            logger.exception("Ingest improvement pass failed for %s", target.ticker)
            summary.errors.append(message)

    summary.runtime_seconds = time.monotonic() - started
    if not summary.runtime_cutoff:
        summary.targets_completed = len(summary.results)
        summary.targets_deferred = max(0, summary.targets_planned - summary.targets_completed)
    completed_tickers = [str(row.get("ticker") or "") for row in summary.results]
    backlog_result = record_ingest_backlog_after_pass(
        targets=targets,
        completed_tickers=completed_tickers,
        runtime_cutoff=summary.runtime_cutoff,
        path=backlog_path,
    )
    write_json(
        output_dir / "ingest_improvement_summary.json",
        {
            "run_at": datetime.now(UTC).isoformat(),
            "backlog": backlog_result,
            **summary.to_dict(),
        },
        compact=True,
    )
    return summary


install_fetch_cashflow_fallback()
