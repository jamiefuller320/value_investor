"""Tests for memo source-quality scoring."""

from __future__ import annotations

from pathlib import Path

from value_investor.research.document import ResearchDocument
from value_investor.research.source_quality import attach_memo_quality, score_research_sources


def test_score_research_sources_weights_components():
    result = score_research_sources(
        source_counts={
            "filings_total": 10,
            "filings_with_body": 10,
            "filings_annual": 3,
            "financial_years": 5,
            "news_articles": 30,
        },
        inventory={"thin": []},
        question_outcomes=[
            {"status": "resolved"},
            {"status": "resolved"},
        ],
    )
    assert result["grade"] == "strong"
    assert result["source_quality_score"] >= 0.75
    assert result["drivers"]["filing_bodies"] >= 0.9
    assert result["drivers"]["gap_resolution"] == 1.0


def test_score_research_sources_penalizes_thin_ladder_and_unresolved():
    result = score_research_sources(
        source_counts={
            "filings_total": 8,
            "filings_with_body": 1,
            "filings_annual": 0,
            "financial_years": 1,
            "news_articles": 2,
        },
        inventory={"thin": ["filings_bodies", "yahoo_financials", "alternate_news"]},
        question_outcomes=[{"status": "unresolved"}],
    )
    assert result["grade"] in {"thin", "poor", "adequate"}
    assert result["source_quality_score"] < 0.55
    assert "filings_bodies" in result["thin_gaps"]


def test_attach_memo_quality_uses_local_inventory(tmp_path: Path):
    sources_dir = tmp_path / "sources"
    filings_dir = sources_dir / "filings"
    filings_dir.mkdir(parents=True)
    (filings_dir / "index.json").write_text('{"filings": []}', encoding="utf-8")

    doc = ResearchDocument(
        ticker="AAA.L",
        name="Alpha",
        signal="strong_buy",
        version=1,
        created_at="2026-07-01T00:00:00+00:00",
        updated_at="2026-07-01T00:00:00+00:00",
        mode="initial",
        source_counts={
            "filings_total": 4,
            "filings_with_body": 2,
            "financial_years": 3,
            "news_articles": 10,
        },
    )
    attach_memo_quality(
        doc,
        sources_dir=sources_dir,
        question_outcomes=[{"status": "partially_resolved"}],
    )
    assert doc.memo_quality
    assert "source_quality_score" in doc.memo_quality
    assert "grade" in doc.memo_quality
    assert doc.memo_quality["drivers"]["gap_resolution"] < 1.0
