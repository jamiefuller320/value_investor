"""Orchestrate deep research for buy-tier recommendations."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from value_investor.data_quality import MIN_QUALITY_FOR_BUY, MIN_QUALITY_FOR_STRONG_BUY
from value_investor.research.agent import (
    run_initial_research_agent,
    run_weekly_research_update_agent,
)
from value_investor.research.document import ResearchDocument, ResearchSummary
from value_investor.research.ingest import ingest_research_sources
from value_investor.research.source_quality import attach_memo_quality
from value_investor.research.store import ResearchStore
from value_investor.research.timeline import (
    build_sources_as_of,
    build_weekly_delta,
    revision_id_from_datetime,
)
from value_investor.research.verdict import effective_screen_signal
from value_investor.summary import CompanyReport

logger = logging.getLogger(__name__)

# Weekly memo budget for FTSE 350: all quality strong buys first, then top buys.
DEFAULT_RESEARCH_WEEKLY_CAP = 12
# Extra weekly updates for names that left the buy list but still have a memo.
DEFAULT_RESEARCH_ALUMNI_CAP = 12


def _rank_key(report: CompanyReport) -> tuple[float, float]:
    composite = report.composite_score if report.composite_score is not None else -1.0
    return (report.conviction_score, composite)


def _normalize_ticker_set(tickers: set[str] | None) -> set[str]:
    return {str(t).strip().upper() for t in (tickers or set()) if str(t).strip()}


def _memo_at_map(memo_at_by_ticker: dict[str, str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in (memo_at_by_ticker or {}).items():
        ticker = str(key or "").strip().upper()
        token = str(value or "").strip()
        if ticker and token:
            out[ticker] = token
    return out


def _rememo_rank_key(
    report: CompanyReport,
    *,
    holdings: set[str],
    memo_at_by_ticker: dict[str, str],
) -> tuple[int, str, float, float]:
    """Holdings first, then oldest memo activity, then conviction (desc)."""
    ticker = str(report.ticker or "").strip().upper()
    held_rank = 0 if ticker in holdings else 1
    memo_at = memo_at_by_ticker.get(ticker) or ""
    composite = report.composite_score if report.composite_score is not None else -1.0
    conviction = report.conviction_score if report.conviction_score is not None else 0.0
    return (held_rank, memo_at, -conviction, -composite)


def _order_rememo_band(
    pool: list[CompanyReport],
    *,
    already_researched: set[str] | None,
    holdings: set[str] | None,
    memo_at_by_ticker: dict[str, str] | None,
) -> list[CompanyReport]:
    """Reorder already-memo'd actives: holdings → oldest memo_at → conviction.

    First-time (no memo) names keep their relative order and stay ahead of the
    rememo band when present. Cap size is unchanged — this only reorders spend.
    """
    if holdings is None and memo_at_by_ticker is None:
        return pool
    already = _normalize_ticker_set(already_researched)
    held = _normalize_ticker_set(holdings)
    memo_map = _memo_at_map(memo_at_by_ticker)
    first: list[CompanyReport] = []
    rememo: list[CompanyReport] = []
    for report in pool:
        ticker = str(report.ticker or "").strip().upper()
        if ticker and ticker not in already:
            first.append(report)
        else:
            rememo.append(report)
    rememo.sort(key=lambda r: _rememo_rank_key(r, holdings=held, memo_at_by_ticker=memo_map))
    return first + rememo


def _buy_tier_signal(report: CompanyReport) -> str:
    """Screen signal after FCF/research caps for research spend gating."""
    return effective_screen_signal(report.signal, report.adjusted_signal)


def _fcf_mismatch_unresolved(report: CompanyReport) -> bool:
    """True when filing/screen FCF diverge and no policy FCF is locked.

    Policy FCF may come from a reviewed bridge or from automatic majority /
    filing-aligned fallback (``bridge_resolved`` / ``auto_policy_resolved``).
    """
    bundle = report.fcf if isinstance(report.fcf, dict) else None
    if not bundle:
        return False
    mismatched = bool(bundle.get("filing_screen_mismatch"))
    if not mismatched:
        return False
    if bool(bundle.get("bridge_resolved")) or bool(bundle.get("auto_policy_resolved")):
        return False
    if bundle.get("policy_fcf") is not None and str(bundle.get("source") or "").startswith(
        ("auto_", "policy_")
    ):
        return False
    # Deterministic auto path available when filing or company-adjusted exists.
    if bundle.get("filing_aligned") is not None or bundle.get("company_adjusted") is not None:
        return False
    return True


def eligible_strong_buys(reports: list[CompanyReport]) -> list[CompanyReport]:
    """Quality-gated strong buys only (no weekly cap). Prefer eligible_research_targets()."""
    return [
        report
        for report in reports
        if _buy_tier_signal(report) == "strong_buy"
        and report.data_quality_score >= MIN_QUALITY_FOR_STRONG_BUY
    ]


def eligible_research_targets(
    reports: list[CompanyReport],
    *,
    weekly_cap: int = DEFAULT_RESEARCH_WEEKLY_CAP,
    already_researched: set[str] | None = None,
    prefer_first_time: bool = False,
    holdings: set[str] | None = None,
    memo_at_by_ticker: dict[str, str] | None = None,
) -> list[CompanyReport]:
    """
    Select active buy-tier names for deep research memos.

    Priority: quality strong buys (all, ranked), then top quality buys to fill
    remaining slots up to weekly_cap.

    When ``prefer_first_time`` is True, names with no research memo are ordered
    ahead of rememo/refresh candidates before the cap is applied (N114 parity
    with library ``prefer_first_time_research_queues``). Cap size is unchanged.

    After first-time preference, already-memo'd refresh candidates can be reordered
    as holdings first, then oldest ``memo_at`` (typically ``updated_at``), then
    conviction — P1 live-path memo freshness on FTSE holdings ∪ buy-tier without
    widening the Sunday cap or spraying rememo without bodies.
    """
    if weekly_cap <= 0:
        return []

    strong = [
        report
        for report in reports
        if _buy_tier_signal(report) == "strong_buy"
        and report.data_quality_score >= MIN_QUALITY_FOR_STRONG_BUY
        and not _fcf_mismatch_unresolved(report)
    ]
    buys = [
        report
        for report in reports
        if _buy_tier_signal(report) == "buy"
        and report.data_quality_score >= MIN_QUALITY_FOR_BUY
        and not _fcf_mismatch_unresolved(report)
    ]
    strong.sort(key=_rank_key, reverse=True)
    buys.sort(key=_rank_key, reverse=True)
    pool = strong + buys
    if prefer_first_time:
        from value_investor.library_dedupe import prefer_first_time_reports

        pool = prefer_first_time_reports(pool, already_researched)
    pool = _order_rememo_band(
        pool,
        already_researched=already_researched,
        holdings=holdings,
        memo_at_by_ticker=memo_at_by_ticker,
    )
    return pool[:weekly_cap]


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
        if _buy_tier_signal(report) in {"strong_buy", "buy"}:
            # Still an active pick; handled by eligible_research_targets.
            continue
        candidates.append((doc.updated_at or "", report))

    candidates.sort(key=lambda item: item[0])  # oldest memo first
    return [report for _, report in candidates[:alumni_cap]]


def _memo_at_by_ticker_from_docs(docs: list) -> dict[str, str]:
    """Last memo activity per ticker (``updated_at``, else ``created_at``)."""
    out: dict[str, str] = {}
    for doc in docs:
        ticker = str(getattr(doc, "ticker", "") or "").strip().upper()
        if not ticker:
            continue
        token = str(
            getattr(doc, "updated_at", None) or getattr(doc, "created_at", None) or ""
        ).strip()
        if token:
            out[ticker] = token
    return out


def _default_paper_holdings() -> set[str]:
    """Primary-track paper holdings for Sunday rememo ranking (empty if unavailable)."""
    try:
        from value_investor.decision_input_inventory import load_paper_holdings

        return load_paper_holdings()
    except Exception:  # noqa: BLE001
        return set()


def select_research_targets(
    reports: list[CompanyReport],
    store: ResearchStore,
    *,
    weekly_cap: int = DEFAULT_RESEARCH_WEEKLY_CAP,
    continue_alumni: bool = True,
    alumni_cap: int = DEFAULT_RESEARCH_ALUMNI_CAP,
    prefer_first_time: bool = True,
    holdings: set[str] | None = None,
) -> tuple[list[CompanyReport], list[CompanyReport]]:
    """
    Active buy-tier targets plus optional alumni weekly updates.

    Returns ``(active_targets, alumni_targets)``. Combined list preserves active
    first so new initials and current picks are never starved by alumni refreshes.

    By default (``prefer_first_time=True``), active selection puts no-memo
    buy-tier names ahead of rememo of already-memo'd names inside the weekly
    cap — same structural rule as library Sunday N114. Among already-memo'd
    actives, rememo order is holdings → oldest memo activity → conviction
    (P1 memo freshness on the live decision pack). Alumni path is unchanged
    (already-memo'd drop-offs only). Weekday rememo still cannot create first
    memos; this only reorders Sunday ``--research-docs`` spend. Cap unchanged.
    """
    docs = store.list_documents()
    already = {doc.ticker for doc in docs}
    memo_at_by_ticker = _memo_at_by_ticker_from_docs(docs)
    held = holdings if holdings is not None else _default_paper_holdings()
    active = eligible_research_targets(
        reports,
        weekly_cap=weekly_cap,
        already_researched=already,
        prefer_first_time=prefer_first_time,
        holdings=held,
        memo_at_by_ticker=memo_at_by_ticker,
    )
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
    director_shadow: bool = True,
) -> ResearchSummary:
    """
    Create or update per-ticker research memos.

    Active path: quality strong buys first, then top quality buys until weekly_cap.
    Within that pool, no-memo names are preferred ahead of rememo (N114 parity)
    so first-time buy-tier fills the cap before refreshing already-memo'd picks.
    Already-memo'd actives then rank holdings → oldest memo activity → conviction
    (Sunday cap unchanged; no rememo burst / no widen without filing bodies).
    Alumni path: continue weekly updates for names that dropped off the buy list
    but still have a memo and remain in the screen (up to alumni_cap, oldest first).

    First run: ingest Yahoo financials, news, and primary filings (UK RNS or
    US SEC EDGAR — annual + interim when discoverable), then deep agent pass.
    Subsequent weekly runs: refresh filings/news and append a weekly update section.

    When ``director_shadow`` is True (default), log observe-only escalation decisions
    after each Composer memo without calling director–worker agents.
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

    if director_shadow:
        from value_investor.research.director_shadow import (
            record_director_shadow_entry,
            write_shadow_run_summary,
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
            if director_shadow and action in {"created", "updated"}:
                entry = record_director_shadow_entry(
                    report=report,
                    doc=doc,
                    sources_dir=store.sources_dir(report.ticker),
                    research_action=action,
                    run_output_dir=str(output_dir),
                )
                summary.director_shadow.append(entry)
        except Exception as exc:  # noqa: BLE001
            message = f"{report.ticker}: {exc}"
            logger.exception("Research failed for %s", report.ticker)
            summary.errors.append(message)

    if director_shadow and summary.director_shadow:
        write_shadow_run_summary(summary.director_shadow, output_dir=output_dir)

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
        deepen_history=True,
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
        attach_memo_quality(doc, sources_dir=sources_dir)
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
    attach_memo_quality(updated, sources_dir=sources_dir)
    store.save(
        updated,
        run_at=effective_run_at,
        sources_as_of=sources_as_of,
        delta=delta,
    )
    return updated, "updated"


def load_existing_research(
    output_dir: Path, *, tickers: list[str] | None = None
) -> list[ResearchDocument]:
    store = ResearchStore(output_dir)
    if tickers:
        docs = [store.load(ticker) for ticker in tickers]
        return [doc for doc in docs if doc is not None]
    return store.list_documents()
