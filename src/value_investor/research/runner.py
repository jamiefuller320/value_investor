"""Orchestrate deep research for strong buy recommendations."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from value_investor.data_quality import MIN_QUALITY_FOR_STRONG_BUY
from value_investor.research.agent import run_initial_research_agent, run_weekly_research_update_agent
from value_investor.research.document import ResearchDocument, ResearchSummary
from value_investor.research.ingest import ingest_research_sources
from value_investor.research.store import ResearchStore
from value_investor.research.timeline import build_sources_as_of, build_weekly_delta, revision_id_from_datetime
from value_investor.summary import CompanyReport

logger = logging.getLogger(__name__)


def eligible_strong_buys(reports: list[CompanyReport]) -> list[CompanyReport]:
    return [
        report
        for report in reports
        if report.signal == "strong_buy"
        and report.data_quality_score >= MIN_QUALITY_FOR_STRONG_BUY
    ]


def run_research_for_strong_buys(
    *,
    reports: list[CompanyReport],
    output_dir: Path,
    api_key: str,
    model: str = "composer-2.5",
    cwd: str | None = None,
    force_initial: bool = False,
    run_at: datetime | None = None,
) -> ResearchSummary:
    """
    Create or update per-ticker research memos for all strong buys.

    First run: ingest five years of financials + one year of news, then deep agent pass.
    Subsequent weekly runs: fetch new headlines and append a weekly update section.
    """
    store = ResearchStore(output_dir)
    targets = eligible_strong_buys(reports)
    summary = ResearchSummary(documents=[], created=0, updated=0, skipped=0, errors=[])

    for report in targets:
        try:
            doc, action = _process_ticker(
                report=report,
                store=store,
                api_key=api_key,
                model=model,
                cwd=cwd,
                force_initial=force_initial,
                run_at=run_at,
            )
            summary.documents.append(doc)
            if action == "created":
                summary.created += 1
            elif action == "updated":
                summary.updated += 1
            else:
                summary.skipped += 1
        except Exception as exc:  # noqa: BLE001
            message = f"{report.ticker}: {exc}"
            logger.exception("Research failed for %s", report.ticker)
            summary.errors.append(message)

    summary.documents.sort(key=lambda item: item.name)
    return summary


def _process_ticker(
    *,
    report: CompanyReport,
    store: ResearchStore,
    api_key: str,
    model: str,
    cwd: str | None,
    force_initial: bool,
    run_at: datetime | None,
) -> tuple[ResearchDocument, str]:
    sources_dir = store.sources_dir(report.ticker)
    existing = None if force_initial else store.load(report.ticker)
    since: datetime | None = None
    if existing and existing.updated_at:
        try:
            since = datetime.fromisoformat(existing.updated_at.replace("Z", "+00:00"))
        except ValueError:
            since = None

    source_meta = ingest_research_sources(
        ticker=report.ticker,
        company_name=report.name,
        screening_snapshot=report.to_dict(),
        sources_dir=sources_dir,
        since=since,
    )

    effective_run_at = run_at or datetime.now(UTC)

    if existing is None:
        doc, _agent_id = run_initial_research_agent(
            report=report,
            sources_dir=sources_dir,
            api_key=api_key,
            model=model,
            cwd=cwd,
        )
        doc.source_counts = {
            "financial_years": source_meta["financial_years"],
            "news_articles": source_meta["news_total"],
        }
        as_of = datetime.fromisoformat(doc.updated_at.replace("Z", "+00:00"))
        sources_as_of = build_sources_as_of(
            sources_dir=sources_dir,
            source_meta=source_meta,
            as_of=as_of,
            revision_id=revision_id_from_datetime(as_of),
        )
        store.save(
            doc,
            run_at=effective_run_at,
            sources_as_of=sources_as_of,
        )
        return doc, "created"

    updated = run_weekly_research_update_agent(
        existing=existing,
        sources_dir=sources_dir,
        news_batch_path=Path(source_meta["news_batch_path"]),
        markdown_path=store.markdown_path(report.ticker),
        api_key=api_key,
        model=model,
        cwd=cwd,
    )
    updated.source_counts = {
        "financial_years": source_meta["financial_years"],
        "news_articles": source_meta["news_total"],
    }
    weekly_summary = updated.weekly_updates[-1]["summary"] if updated.weekly_updates else ""
    as_of = datetime.fromisoformat(updated.updated_at.replace("Z", "+00:00"))
    sources_as_of = build_sources_as_of(
        sources_dir=sources_dir,
        source_meta=source_meta,
        as_of=as_of,
        revision_id=revision_id_from_datetime(as_of),
    )
    delta = build_weekly_delta(prior=existing, updated=updated, weekly_summary=weekly_summary)
    store.save(
        updated,
        run_at=effective_run_at,
        sources_as_of=sources_as_of,
        delta=delta,
    )
    return updated, "updated"


def load_existing_research(output_dir: Path, *, tickers: list[str] | None = None) -> list[ResearchDocument]:
    store = ResearchStore(output_dir)
    if tickers:
        docs = [store.load(ticker) for ticker in tickers]
        return [doc for doc in docs if doc is not None]
    return store.list_documents()
