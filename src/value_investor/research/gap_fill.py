"""Research improvement loop: resolve qualitative red flags from deep analysis."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.deep_analysis import DeepAnalysis
from value_investor.research.agent import run_gap_fill_research_agent
from value_investor.research.document import ResearchDocument
from value_investor.research.gap_fill_sources import prepare_gap_fill_source_pack
from value_investor.research.ingest import ingest_research_sources
from value_investor.research.store import ResearchStore
from value_investor.research.timeline import (
    build_sources_as_of,
    build_weekly_delta,
    revision_id_from_datetime,
)
from value_investor.summary import CompanyReport

logger = logging.getLogger(__name__)

DEFAULT_GAP_FILL_CAP = 3
DEFAULT_SUGGESTIONS_PATH = Path("docs/data/research_model_suggestions.json")

_TICKER_TOKEN = re.compile(r"\b([A-Z]{1,5}(?:\.[A-Z]{1,2})?)\b")
_DEEPER_RESEARCH_SPLIT = re.compile(
    r"(?i)names?\s+(?:worth|for)\s+deeper\s+research|\bopen questions?\b|\bred flags?\b"
)


@dataclass
class GapFillTarget:
    ticker: str
    name: str
    report: CompanyReport
    questions: list[str] = field(default_factory=list)
    source: str = "red_flags"


@dataclass
class GapFillSummary:
    targets: list[GapFillTarget]
    documents: list[ResearchDocument] = field(default_factory=list)
    updated: int = 0
    created: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    question_outcomes: list[dict[str, Any]] = field(default_factory=list)
    model_suggestions: list[dict[str, Any]] = field(default_factory=list)
    alternate_source_plans: list[dict[str, Any]] = field(default_factory=list)
    parked_suggestions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "targets": [
                {
                    "ticker": t.ticker,
                    "name": t.name,
                    "questions": t.questions,
                    "source": t.source,
                    "signal": t.report.signal,
                }
                for t in self.targets
            ],
            "updated": self.updated,
            "created": self.created,
            "skipped": self.skipped,
            "errors": self.errors,
            "question_outcomes": self.question_outcomes,
            "model_suggestions": self.model_suggestions,
            "alternate_source_plans": self.alternate_source_plans,
            "parked_suggestions": self.parked_suggestions,
            "documents": [doc.to_dict() for doc in self.documents],
        }


def _candidate_reports(reports: list[CompanyReport]) -> dict[str, CompanyReport]:
    return {
        report.ticker.upper(): report
        for report in reports
        if report.signal in ("strong_buy", "buy")
    }


def _question_from_line(line: str, ticker: str) -> str:
    cleaned = line.strip().lstrip("-*• ").strip()
    cleaned = re.sub(r"^\*\*?|\*\*?$", "", cleaned).strip()
    # Drop leading ticker / bold ticker wrappers.
    cleaned = re.sub(
        rf"^\*?\*?{re.escape(ticker)}\*?\*?\s*[—:\-–,)]*\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned or line.strip()


def extract_gap_fill_targets(
    deep_analysis: DeepAnalysis | None,
    reports: list[CompanyReport],
    *,
    max_targets: int = DEFAULT_GAP_FILL_CAP,
) -> list[GapFillTarget]:
    """
    Pull tickers + open qualitative questions from deep-analysis red flags.

    Prefers the ``NAMES WORTH DEEPER RESEARCH`` / red-flags corpus and matches
    against current buy-tier reports.
    """
    if deep_analysis is None or max_targets <= 0:
        return []

    by_ticker = _candidate_reports(reports)
    if not by_ticker:
        return []

    corpus_parts = [
        deep_analysis.red_flags or "",
        deep_analysis.top_picks_analysis or "",
        deep_analysis.executive_intro or "",
    ]
    corpus = "\n\n".join(part for part in corpus_parts if part.strip())
    if not corpus.strip():
        return []

    focus = corpus
    split = _DEEPER_RESEARCH_SPLIT.search(corpus)
    if split:
        # Prefer the deeper-research / red-flag tail, but keep full corpus for mentions.
        focus = corpus[split.start() :]

    questions_by_ticker: dict[str, list[str]] = {ticker: [] for ticker in by_ticker}
    mention_order: list[str] = []

    for line in focus.splitlines():
        tokens = [tok.upper() for tok in _TICKER_TOKEN.findall(line)]
        matched = [tok for tok in tokens if tok in by_ticker]
        if not matched:
            continue
        for ticker in matched:
            if ticker not in mention_order:
                mention_order.append(ticker)
            question = _question_from_line(line, ticker)
            if question and question not in questions_by_ticker[ticker]:
                questions_by_ticker[ticker].append(question)

    # Name-based fallback when the model writes company names without tickers.
    lower_focus = focus.lower()
    for ticker, report in by_ticker.items():
        name = (report.name or "").strip()
        if not name or len(name) < 4:
            continue
        if name.lower() in lower_focus and ticker not in mention_order:
            mention_order.append(ticker)
            questions_by_ticker[ticker].append(
                f"Resolve qualitative red flags / open questions highlighted for {name}"
            )

    targets: list[GapFillTarget] = []
    for ticker in mention_order:
        if len(targets) >= max_targets:
            break
        report = by_ticker[ticker]
        questions = questions_by_ticker.get(ticker) or [
            f"Resolve qualitative risks called out for {report.name} ({ticker}) in the weekly deep analysis"
        ]
        targets.append(
            GapFillTarget(
                ticker=report.ticker,
                name=report.name,
                report=report,
                questions=questions[:6],
                source="red_flags",
            )
        )
    return targets


def _persist_model_suggestions(
    suggestions: list[dict[str, Any]],
    *,
    path: Path = DEFAULT_SUGGESTIONS_PATH,
) -> list[dict[str, Any]]:
    """Append unique suggestions to the rolling research-model suggestions log."""
    from value_investor.storage import read_json, write_json

    path = Path(path)
    existing: dict[str, Any] = {"suggestions": []}
    if path.exists():
        try:
            existing = read_json(path)
        except (OSError, ValueError, TypeError):
            existing = {"suggestions": []}
    known = {
        str(item.get("suggestion") or "").strip().lower()
        for item in existing.get("suggestions") or []
    }
    appended: list[dict[str, Any]] = []
    for row in suggestions:
        text = str(row.get("suggestion") or "").strip()
        if not text or text.lower() in known:
            continue
        known.add(text.lower())
        record = {
            **row,
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        existing.setdefault("suggestions", []).append(record)
        appended.append(record)
    existing["updated_at"] = datetime.now(UTC).isoformat()
    write_json(path, existing, compact=False, compress=False)
    return appended


def _park_high_priority_suggestions(
    suggestions: list[dict[str, Any]],
    *,
    enabled: bool,
) -> list[dict[str, Any]]:
    """Optionally park high-priority suggestions into deferred-ideas for review."""
    if not enabled:
        return []
    from value_investor.deferred_ideas import add_idea, write_markdown

    parked: list[dict[str, Any]] = []
    for row in suggestions:
        if str(row.get("priority") or "").lower() != "high":
            continue
        suggestion = str(row.get("suggestion") or "").strip()
        area = str(row.get("area") or "research").strip()
        if not suggestion:
            continue
        title = f"Gap-fill: {area} — {suggestion[:72]}"
        try:
            idea, created = add_idea(
                title=title,
                summary=suggestion,
                category="later",
                section="research",
                revisit_when="After next weekly email gap-fill pass confirms the gap persists",
                tags=["gap-fill", "research-model", area],
                source="research-gap-fill",
            )
            if created:
                parked.append(idea)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not park suggestion %r: %s", title, exc)
    if parked:
        try:
            write_markdown()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not refresh deferred-review.md: %s", exc)
    return parked


def run_red_flag_gap_fill(
    *,
    deep_analysis: DeepAnalysis | None,
    reports: list[CompanyReport],
    output_dir: Path,
    api_key: str,
    model: str = "composer-2.5",
    cwd: str | None = None,
    run_at: datetime | None = None,
    max_targets: int = DEFAULT_GAP_FILL_CAP,
    market: str | None = None,
    park_suggestions: bool = True,
    suggestions_path: Path = DEFAULT_SUGGESTIONS_PATH,
) -> GapFillSummary:
    """
    Re-ingest sources and run a gap-fill research pass for red-flag targets.

    Seeks alternate news / planned external sources when local filings are thin,
    and collects research-model improvement suggestions for unresolved gaps.
    """
    targets = extract_gap_fill_targets(
        deep_analysis,
        reports,
        max_targets=max_targets,
    )
    summary = GapFillSummary(targets=targets)
    if not targets:
        return summary

    store = ResearchStore(output_dir)
    effective_run_at = run_at or datetime.now(UTC)

    for target in targets:
        try:
            existing = store.load(target.ticker)
            if existing is None:
                # Seed a normal memo first so gap-fill has a baseline thesis.
                from value_investor.research.runner import _process_ticker

                doc, action = _process_ticker(
                    report=target.report,
                    store=store,
                    api_key=api_key,
                    model=model,
                    cwd=cwd,
                    force_initial=True,
                    run_at=effective_run_at,
                    market=market,
                )
                if action == "created":
                    summary.created += 1
                existing = store.load(target.ticker) or doc

            sources_dir = store.sources_dir(target.ticker)
            # Full re-ingest for gap-fill so alternate evidence is not clipped by since=.
            source_meta = ingest_research_sources(
                ticker=target.ticker,
                company_name=target.name,
                screening_snapshot=target.report.to_dict(),
                sources_dir=sources_dir,
                since=None,
                market=market,
            )
            source_pack = prepare_gap_fill_source_pack(
                ticker=target.ticker,
                company_name=target.name,
                sources_dir=sources_dir,
                open_questions=target.questions,
                market=market,
            )
            summary.alternate_source_plans.append(
                {
                    "ticker": target.ticker,
                    "planned_alternate_sources": source_pack.get("planned_alternate_sources") or [],
                    "thin": (source_pack.get("inventory") or {}).get("thin") or [],
                    "alternate_news_added": source_pack.get("alternate_news_added") or 0,
                }
            )

            agent_result = run_gap_fill_research_agent(
                existing=existing,
                sources_dir=sources_dir,
                markdown_path=store.markdown_path(target.ticker),
                open_questions=target.questions,
                api_key=api_key,
                model=model,
                cwd=cwd,
                screen_signal=target.report.signal,
            )
            updated = replace(agent_result.document, signal=target.report.signal)

            filings_summary = source_meta.get("filings_summary") or {}
            updated.source_counts = {
                "financial_years": source_meta["financial_years"],
                "news_articles": source_meta["news_total"],
                "filings_total": filings_summary.get("total", 0),
                "filings_annual": filings_summary.get("annual", 0),
                "filings_interim": filings_summary.get("interim", 0),
                "filings_with_body": filings_summary.get("with_body", 0),
            }
            as_of = datetime.fromisoformat(updated.updated_at.replace("Z", "+00:00"))
            sources_as_of = build_sources_as_of(
                sources_dir=sources_dir,
                source_meta=source_meta,
                as_of=as_of,
                revision_id=revision_id_from_datetime(as_of),
            )
            gap_summary_text = ""
            if updated.weekly_updates:
                gap_summary_text = updated.weekly_updates[-1].get("summary", "")
            delta = build_weekly_delta(
                prior=existing,
                updated=updated,
                weekly_summary=gap_summary_text,
            )
            store.save(
                updated,
                run_at=effective_run_at,
                sources_as_of=sources_as_of,
                delta=delta,
            )
            summary.documents.append(updated)
            summary.updated += 1
            for outcome in agent_result.question_outcomes:
                summary.question_outcomes.append({"ticker": target.ticker, **outcome})
            for suggestion in agent_result.model_suggestions:
                summary.model_suggestions.append(
                    {
                        "ticker": target.ticker,
                        "name": target.name,
                        **suggestion,
                    }
                )
        except Exception as exc:  # noqa: BLE001
            message = f"{target.ticker}: {exc}"
            logger.exception("Gap-fill research failed for %s", target.ticker)
            summary.errors.append(message)

    if summary.model_suggestions:
        _persist_model_suggestions(summary.model_suggestions, path=suggestions_path)
        # Also mirror beside the run outputs for publish/email consumers.
        _persist_model_suggestions(
            summary.model_suggestions,
            path=Path(output_dir) / "research_model_suggestions.json",
        )
        summary.parked_suggestions = _park_high_priority_suggestions(
            summary.model_suggestions,
            enabled=park_suggestions,
        )

    return summary
