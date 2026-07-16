"""Orchestrate deep research for buy-tier recommendations."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from value_investor.data_quality import MIN_QUALITY_FOR_BUY, MIN_QUALITY_FOR_STRONG_BUY
from value_investor.research.agent import run_initial_research_agent, run_weekly_research_update_agent
from value_investor.research.document import ResearchDocument, ResearchSummary
from value_investor.research.ingest import ingest_research_sources
from value_investor.research.store import ResearchStore
from value_investor.research.timeline import build_sources_as_of, build_weekly_delta, revision_id_from_datetime
from value_investor.summary import CompanyReport

logger = logging.getLogger(__name__)

# Weekly memo budget for FTSE 350: all quality strong buys first, then top buys.
DEFAULT_RESEARCH_WEEKLY_CAP = 12
# Extra weekly updates for names that left the buy list but still have a memo.
DEFAULT_RESEARCH_ALUMNI_CAP = 12


def _rank_key(report: CompanyReport) -> tuple[float, float]:
    composite = report.composite_score if report.composite_score is not None else -1.0
    return (report.conviction_score, composite)


def eligible_strong_buys(reports: list[CompanyReport]) -> list[CompanyReport]:
    """Quality-gated strong buys only (no weekly cap). Prefer eligible_research_targets()."""
    return [
        report
        for report in reports
        if report.signal == "strong_buy"
        and report.data_quality_score >= MIN_QUALITY_FOR_STRONG_BUY
    ]


def eligible_research_targets(
    reports: list[CompanyReport],
    *,
    weekly_cap: int = DEFAULT_RESEARCH_WEEKLY_CAP,
) -> list[CompanyReport]:
    """
    Select active buy-tier names for deep research memos.

    Priority: quality strong buys (all, ranked), then top quality buys to fill
    remaining slots up to weekly_cap.
    """
    if weekly_cap <= 0:
        return []

    strong = [
        report
        for report in reports
        if report.signal == "strong_buy"
        and report.data_quality_score >= MIN_QUALITY_FOR_STRONG_BUY
    ]
    buys = [
        report
        for report in reports
        if report.signal == "buy" and report.data_quality_score >= MIN_QUALITY_FOR_BUY
    ]
    strong.sort(key=_rank_key, reverse=True)
    buys.sort(key=_rank_key, reverse=True)

    selected = strong[:weekly_cap]
    remaining = weekly_cap - len(selected)
    if remaining > 0:
        selected.extend(buys[:remaining])
    return selected


def eligible_alumni_research_targets(
    reports: list[CompanyReport],
    store: ResearchStore,
    *,
    alumni_cap: int = DEFAULT_RESEARCH_ALUMNI_CAP,
    exclude_tickers: set[str] | None = None,
) -> list[CompanyReport]:
    """
    Select previously researched names that are no longer on the buy-tier pick list.

    Only includes tickers that still appear in the current screen reports (so we have
    an up-to-date signal/snapshot). Ranked by oldest ``updated_at`` first so stale
    memos are refreshed preferentially — maximising longitudinal decision data.
    """
    if alumni_cap <= 0:
        return []

    exclude = set(exclude_tickers or ())
    by_ticker = {report.ticker: report for report in reports}
    candidates: list[tuple[str, CompanyReport]] = []
    for doc in store.list_documents():
        if doc.ticker in exclude:
            continue
        report = by_ticker.get(doc.ticker)
        if report is None:
            # Left the screened universe — skip until/unless re-listed.
            continue
        if report.signal in {"strong_buy", "buy"}:
            # Still an active pick; handled by eligible_research_targets.
            continue
        candidates.append((doc.updated_at or "", report))

    candidates.sort(key=lambda item: item[0])  # oldest memo first
    return [report for _, report in candidates[:alumni_cap]]


def select_research_targets(
    reports: list[CompanyReport],
    store: ResearchStore,
    *,
    weekly_cap: int = DEFAULT_RESEARCH_WEEKLY_CAP,
    continue_alumni: bool = True,
    alumni_cap: int = DEFAULT_RESEARCH_ALUMNI_CAP,
) -> tuple[list[CompanyReport], list[CompanyReport]]:
    """
    Active buy-tier targets plus optional alumni weekly updates.

    Returns ``(active_targets, alumni_targets)``. Combined list preserves active
    first so new initials and current picks are never starved by alumni refreshes.
    """
    active = eligible_research_targets(reports, weekly_cap=weekly_cap)
    if not continue_alumni:
        return active, []
    alumni = eligible_alumni_research_targets(
        reports,
        store,
        alumni_cap=alumni_cap,
        exclude_tickers={report.ticker for report in active},
    )
    return active, alumni


def run_research_for_strong_buys(
    *,
    reports: list[CompanyReport],
    output_dir: Path,
    api_key: str,
    model: str = "composer-2.5",
    cwd: str | None = None,
    force_initial: bool = False,
    run_at: datetime | None = None,
    weekly_cap: int = DEFAULT_RESEARCH_WEEKLY_CAP,
    continue_alumni: bool = True,
    alumni_cap: int = DEFAULT_RESEARCH_ALUMNI_CAP,
    market: str | None = None,
) -> ResearchSummary:
    """
    Create or update per-ticker research memos.

    Active path: quality strong buys first, then top quality buys until weekly_cap.
    Alumni path: continue weekly updates for names that dropped off the buy list
    but still have a memo and remain in the screen (up to alumni_cap, oldest first).

    First run: ingest Yahoo financials, news, and primary filings (UK RNS or
    US SEC EDGAR — annual + interim when discoverable), then deep agent pass.
    Subsequent weekly runs: refresh filings/news and append a weekly update section.
    """
    store = ResearchStore(output_dir)
    active, alumni = select_research_targets(
        reports,
        store,
        weekly_cap=weekly_cap,
        continue_alumni=continue_alumni,
        alumni_cap=alumni_cap,
    )
    alumni_tickers = {report.ticker for report in alumni}
    targets = [*active, *alumni]
    summary = ResearchSummary(
        documents=[],
        created=0,
        updated=0,
        skipped=0,
        errors=[],
        active_count=len(active),
        alumni_count=len(alumni),
    )

    for report in targets:
        try:
            doc, action = _process_ticker(
                report=report,
                store=store,
                api_key=api_key,
                model=model,
                cwd=cwd,
                # Alumni already have memos — never force a fresh initial pass.
                force_initial=force_initial and report.ticker not in alumni_tickers,
                run_at=run_at,
                market=market,
            )
            summary.documents.append(doc)
            if action == "created":
                summary.created += 1
            elif action == "updated":
                summary.updated += 1
                if report.ticker in alumni_tickers:
                    summary.alumni_updated += 1
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
    market: str | None = None,
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
        market=market,
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
        filings_summary = source_meta.get("filings_summary") or {}
        doc.source_counts = {
            "financial_years": source_meta["financial_years"],
            "news_articles": source_meta["news_total"],
            "filings_total": filings_summary.get("total", 0),
            "filings_annual": filings_summary.get("annual", 0),
            "filings_interim": filings_summary.get("interim", 0),
            "filings_with_body": filings_summary.get("with_body", 0),
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
        screen_signal=report.signal,
    )
    updated = replace(updated, signal=report.signal)
    filings_summary = source_meta.get("filings_summary") or {}
    updated.source_counts = {
        "financial_years": source_meta["financial_years"],
        "news_articles": source_meta["news_total"],
        "filings_total": filings_summary.get("total", 0),
        "filings_annual": filings_summary.get("annual", 0),
        "filings_interim": filings_summary.get("interim", 0),
        "filings_with_body": filings_summary.get("with_body", 0),
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
