"""Memo source-quality scoring for learning and refinement feedback."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from value_investor.research.document import ResearchDocument
from value_investor.research.gap_fill_sources import EVIDENCE_LADDER, inspect_local_sources

GRADE_THRESHOLDS = (
    (0.75, "strong"),
    (0.55, "adequate"),
    (0.35, "thin"),
    (0.0, "poor"),
)


def score_research_sources(
    *,
    source_counts: dict[str, int] | None = None,
    inventory: dict[str, Any] | None = None,
    question_outcomes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Score memo source richness on a 0–1 scale with explainable drivers.

    Components:
    - filing bodies (35%)
    - financial depth (20%)
    - news coverage (15%)
    - evidence ladder completeness (20%)
    - gap-fill resolution (10%)
    """
    counts = dict(source_counts or {})
    inv = inventory or {}
    thin = list(inv.get("thin") or [])

    filings_total = max(int(counts.get("filings_total") or 0), 0)
    filings_with_body = max(int(counts.get("filings_with_body") or 0), 0)
    filing_ratio = filings_with_body / max(filings_total, 1)
    if int(counts.get("filings_annual") or 0) >= 2:
        filing_ratio = min(1.0, filing_ratio + 0.15)
    filing_score = min(1.0, filing_ratio)

    financial_years = int(counts.get("financial_years") or 0)
    financial_score = min(financial_years / 5.0, 1.0)

    news_articles = int(counts.get("news_articles") or 0)
    news_score = min(news_articles / 30.0, 1.0)

    ladder_total = len(EVIDENCE_LADDER)
    ladder_score = 1.0 - (len(thin) / ladder_total if ladder_total else 0.0)

    outcomes = list(question_outcomes or [])
    if outcomes:
        resolved = sum(1 for row in outcomes if str(row.get("status") or "").lower() == "resolved")
        gap_score = resolved / len(outcomes)
    else:
        gap_score = 1.0

    source_quality_score = round(
        0.35 * filing_score
        + 0.20 * financial_score
        + 0.15 * news_score
        + 0.20 * ladder_score
        + 0.10 * gap_score,
        3,
    )
    grade = next(g for threshold, g in GRADE_THRESHOLDS if source_quality_score >= threshold)

    drivers = {
        "filing_bodies": round(filing_score, 3),
        "financial_years": round(financial_score, 3),
        "news_coverage": round(news_score, 3),
        "evidence_ladder": round(ladder_score, 3),
        "gap_resolution": round(gap_score, 3),
    }
    return {
        "source_quality_score": source_quality_score,
        "grade": grade,
        "thin_gaps": thin,
        "drivers": drivers,
        "filings_with_body": filings_with_body,
        "filings_total": filings_total,
    }


def attach_memo_quality(
    doc: ResearchDocument,
    *,
    sources_dir: Path | None = None,
    question_outcomes: list[dict[str, Any]] | None = None,
) -> ResearchDocument:
    """Compute and attach memo_quality to a research document."""
    inventory = inspect_local_sources(sources_dir) if sources_dir else {}
    doc.memo_quality = score_research_sources(
        source_counts=doc.source_counts,
        inventory=inventory,
        question_outcomes=question_outcomes,
    )
    return doc
