"""Holistic post-run synthesis after weekly email deep analysis and gap-fill."""

from __future__ import annotations

import logging
import os
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions

from value_investor.deep_analysis import DeepAnalysis
from value_investor.research.gap_fill import DEFAULT_SUGGESTIONS_PATH, GapFillSummary
from value_investor.research.store import ResearchStore
from value_investor.storage import read_json, write_json
from value_investor.summary import CompanyReport

logger = logging.getLogger(__name__)

DEFAULT_SUGGESTIONS_LOOKBACK_DAYS = 14


@dataclass
class PostRunReview:
    executive_summary: str
    persistent_weaknesses: str
    this_week_findings: str
    improvement_plan: str
    defer: str

    @property
    def full_text(self) -> str:
        parts = [
            ("EXECUTIVE SUMMARY", self.executive_summary),
            ("PERSISTENT WEAKNESSES", self.persistent_weaknesses),
            ("THIS WEEK'S FINDINGS", self.this_week_findings),
            ("PRIORITISED IMPROVEMENT PLAN", self.improvement_plan),
            ("DEFER", self.defer),
        ]
        return "\n\n".join(
            f"{heading}\n{body.strip()}"
            for heading, body in parts
            if body.strip()
        )


def _normalize_heading(line: str) -> str:
    text = line.strip().lstrip("#").strip()
    if text.startswith("**") and text.endswith("**") and len(text) > 4:
        text = text[2:-2].strip()
    return text.rstrip(":").strip().upper()


def _parse_post_run_review(text: str) -> PostRunReview:
    section_keys = {
        "EXECUTIVE SUMMARY": "executive_summary",
        "PERSISTENT WEAKNESSES": "persistent_weaknesses",
        "THIS WEEK'S FINDINGS": "this_week_findings",
        "THIS WEEKS FINDINGS": "this_week_findings",
        "PRIORITISED IMPROVEMENT PLAN": "improvement_plan",
        "PRIORITIZED IMPROVEMENT PLAN": "improvement_plan",
        "DEFER": "defer",
        "DO NOT BUILD YET": "defer",
    }
    sections = {key: "" for key in section_keys.values()}
    current = "executive_summary"
    lines: list[str] = []

    for line in text.splitlines():
        upper = _normalize_heading(line)
        if upper in section_keys:
            if lines:
                sections[current] = "\n".join(lines).strip()
                lines = []
            current = section_keys[upper]
            continue
        lines.append(line)

    if lines:
        sections[current] = "\n".join(lines).strip()

    if not any(sections.values()):
        sections["executive_summary"] = text.strip()

    return PostRunReview(**sections)


def _load_suggestions(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = read_json(path)
    except (OSError, ValueError, TypeError):
        return []
    return list(data.get("suggestions") or [])


def _suggestion_rollup(suggestions: list[dict[str, Any]]) -> dict[str, Any]:
    by_area = Counter(str(row.get("area") or "research") for row in suggestions)
    by_priority = Counter(str(row.get("priority") or "medium") for row in suggestions)
    high = [
        row
        for row in suggestions
        if str(row.get("priority") or "").lower() == "high"
    ]
    return {
        "total": len(suggestions),
        "by_area": dict(by_area),
        "by_priority": dict(by_priority),
        "high_priority_count": len(high),
        "high_priority_samples": [
            {
                "ticker": row.get("ticker"),
                "area": row.get("area"),
                "suggestion": str(row.get("suggestion") or "")[:240],
            }
            for row in high[:12]
        ],
    }


def _recent_suggestions(
    suggestions: list[dict[str, Any]],
    *,
    since: datetime | None,
    lookback_days: int = DEFAULT_SUGGESTIONS_LOOKBACK_DAYS,
) -> list[dict[str, Any]]:
    if since is None:
        return suggestions
    cutoff = since
    if lookback_days > 0:
        from datetime import timedelta

        cutoff = since - timedelta(days=lookback_days)
    recent: list[dict[str, Any]] = []
    for row in suggestions:
        stamp = str(row.get("recorded_at") or "").strip()
        if not stamp:
            continue
        try:
            recorded = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if recorded >= cutoff:
            recent.append(row)
    return recent


def _filing_coverage_for_ticker(store: ResearchStore, ticker: str) -> dict[str, Any]:
    index_path = store.sources_dir(ticker) / "filings" / "filings_index.json"
    coverage = {
        "ticker": ticker,
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


def _memo_snapshot(store: ResearchStore, ticker: str) -> dict[str, Any] | None:
    doc = store.load(ticker)
    if doc is None:
        return None
    quality = doc.memo_quality or {}
    return {
        "ticker": doc.ticker,
        "name": doc.name,
        "version": doc.version,
        "mode": doc.mode,
        "research_verdict": doc.research_verdict,
        "source_counts": doc.source_counts,
        "memo_quality_grade": quality.get("grade"),
        "source_quality_score": quality.get("source_quality_score"),
        "unresolved_questions": quality.get("unresolved_questions"),
    }


def build_post_run_payload(
    *,
    reports: list[CompanyReport],
    output_dir: Path,
    run_at: datetime | None = None,
    deep_analysis: DeepAnalysis | None = None,
    gap_fill_summary: GapFillSummary | None = None,
    suggestions_path: Path = DEFAULT_SUGGESTIONS_PATH,
) -> dict[str, Any]:
    """Assemble deterministic inputs for the post-run synthesis agent."""
    effective_run_at = run_at or datetime.now(UTC)
    store = ResearchStore(output_dir)

    buy_reports = [r for r in reports if r.signal in ("strong_buy", "buy")]
    signal_counts = Counter(r.signal for r in reports)

    all_suggestions = _load_suggestions(suggestions_path)
    recent_suggestions = _recent_suggestions(all_suggestions, since=effective_run_at)

    filing_coverage = [
        _filing_coverage_for_ticker(store, report.ticker) for report in buy_reports[:20]
    ]
    memo_snapshots = [
        snap
        for report in buy_reports[:20]
        if (snap := _memo_snapshot(store, report.ticker)) is not None
    ]

    gap_fill_payload: dict[str, Any] | None = None
    if gap_fill_summary is not None:
        unresolved = [
            row
            for row in gap_fill_summary.question_outcomes
            if str(row.get("status") or "").lower()
            in {"unresolved", "partially_resolved"}
        ]
        gap_fill_payload = {
            "targets": [
                {
                    "ticker": target.ticker,
                    "name": target.name,
                    "questions": target.questions,
                }
                for target in gap_fill_summary.targets
            ],
            "created": gap_fill_summary.created,
            "updated": gap_fill_summary.updated,
            "errors": gap_fill_summary.errors,
            "follow_ups": gap_fill_summary.follow_ups,
            "unresolved_questions": unresolved[:20],
            "fetch_attempts": gap_fill_summary.fetch_attempts,
            "this_run_suggestions": gap_fill_summary.model_suggestions,
        }

    deep_payload: dict[str, str] | None = None
    if deep_analysis is not None:
        deep_payload = {
            "executive_intro": deep_analysis.executive_intro[:2000],
            "top_picks_analysis": deep_analysis.top_picks_analysis[:3000],
            "red_flags": deep_analysis.red_flags[:3000],
        }

    thin_filings = [
        row
        for row in filing_coverage
        if row["filings_total"] > 0
        and row["filings_with_body"] < max(1, row["filings_annual"])
    ]

    return {
        "run_at": effective_run_at.isoformat(),
        "signal_distribution": dict(signal_counts),
        "buy_tier_count": len(buy_reports),
        "filing_coverage": filing_coverage,
        "thin_filing_tickers": [row["ticker"] for row in thin_filings[:10]],
        "memo_snapshots": memo_snapshots,
        "deep_analysis": deep_payload,
        "gap_fill": gap_fill_payload,
        "suggestions_backlog": _suggestion_rollup(all_suggestions),
        "suggestions_recent": _suggestion_rollup(recent_suggestions),
        "suggestions_path": str(suggestions_path),
    }


def _build_post_run_prompt(payload_path: Path) -> str:
    return f"""You are the research-ops analyst for an automated FTSE value screener.

Read the structured JSON at: {payload_path}

It contains this week's screen distribution, buy-tier filing coverage, memo quality
snapshots, deep-analysis excerpts, gap-fill outcomes, and accumulated research-model
suggestions (backlog + recent).

Write FIVE plain-text sections with headings exactly as shown:

EXECUTIVE SUMMARY
3–5 sentences on the biggest systemic weaknesses exposed this run and whether they
block conviction on top picks.

PERSISTENT WEAKNESSES
Bullet list of recurring themes across the backlog (ingest vs scoring vs prompt).
Cluster duplicate suggestions; cite frequency where the JSON supports it.

THIS WEEK'S FINDINGS
What changed this run: gap-fill resolutions, new gaps, verdict shifts, fetch failures.
Reference tickers from gap_fill and memo_snapshots only when present in the JSON.

PRIORITISED IMPROVEMENT PLAN
Numbered top 5 engineering actions for the next sprint. Each line:
``N. [area] Action — expected impact on research quality``
Prefer ingest fixes that unlock multiple tickers before one-off prompt tweaks.

DEFER
Bullets for ideas that should NOT be built yet, with a one-line revisit trigger each.

Rules:
- Do not invent tickers, metrics, or filing counts — only use the JSON.
- Distinguish filing-ingest gaps from scoring-metadata gaps from prompt gaps.
- Be specific enough that an engineer can open a ticket from each plan item.
"""


def run_post_run_review(
    *,
    reports: list[CompanyReport],
    output_dir: Path,
    api_key: str,
    model: str = "composer-2.5",
    cwd: str | None = None,
    run_at: datetime | None = None,
    deep_analysis: DeepAnalysis | None = None,
    gap_fill_summary: GapFillSummary | None = None,
    suggestions_path: Path = DEFAULT_SUGGESTIONS_PATH,
) -> PostRunReview:
    """Run a single agent pass to synthesise weekly weaknesses into an improvement plan."""
    payload = build_post_run_payload(
        reports=reports,
        output_dir=output_dir,
        run_at=run_at,
        deep_analysis=deep_analysis,
        gap_fill_summary=gap_fill_summary,
        suggestions_path=suggestions_path,
    )
    if not (
        payload.get("deep_analysis")
        or payload.get("gap_fill")
        or payload.get("memo_snapshots")
        or int((payload.get("suggestions_backlog") or {}).get("total") or 0) > 0
    ):
        raise RuntimeError(
            "Post-run review needs deep analysis, gap-fill, research memos, or suggestions backlog"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    payload_path = output_dir / "post_run_review_payload.json"
    write_json(payload_path, payload, compact=True)

    try:
        agent_result = Agent.prompt(
            _build_post_run_prompt(payload_path.resolve()),
            AgentOptions(
                api_key=api_key,
                model=model,
                local=LocalAgentOptions(cwd=cwd or os.getcwd()),
            ),
        )
    except CursorAgentError as err:
        raise RuntimeError(f"Post-run review agent startup failed: {err.message}") from err

    if agent_result.status == "error":
        raise RuntimeError(f"Post-run review agent run failed: {agent_result.id}")

    text = (agent_result.result or "").strip()
    review = _parse_post_run_review(text)
    (output_dir / "post_run_review.md").write_text(review.full_text, encoding="utf-8")
    return review
