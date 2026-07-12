"""Tests for research email formatting."""

from value_investor.research.document import ResearchDocument, ResearchSummary
from value_investor.research.format import format_research_html, format_research_text


def test_format_research_text_includes_paths():
    doc = ResearchDocument(
        ticker="AAA.L",
        name="Alpha PLC",
        signal="strong_buy",
        version=1,
        created_at="2026-07-01T00:00:00+00:00",
        updated_at="2026-07-08T00:00:00+00:00",
        mode="initial",
        executive_summary="Attractive on valuation and quality.",
        research_path="output/research/AAA.L/research.md",
    )
    summary = ResearchSummary(documents=[doc], created=1)
    text = format_research_text(summary, [doc])
    assert text is not None
    assert "Alpha PLC" in text
    assert "research.md" in text


def test_format_research_text_shows_verdict_revision():
    doc = ResearchDocument(
        ticker="AAA.L",
        name="Alpha PLC",
        signal="strong_buy",
        version=2,
        created_at="2026-07-01T00:00:00+00:00",
        updated_at="2026-07-08T00:00:00+00:00",
        mode="weekly_update",
        executive_summary="Attractive on valuation.",
        research_verdict="caution",
        weekly_updates=[
            {
                "date": "2026-07-08",
                "summary": "Regulatory probe announced.",
                "prior_verdict": "accumulate",
                "new_verdict": "caution",
            }
        ],
    )
    text = format_research_text(None, [doc])
    assert text is not None
    assert "Verdict revised" in text
    assert "Weekly:" in text


def test_format_research_html_renders_table():
    doc = ResearchDocument(
        ticker="AAA.L",
        name="Alpha PLC",
        signal="strong_buy",
        version=1,
        created_at="2026-07-01T00:00:00+00:00",
        updated_at="2026-07-08T00:00:00+00:00",
        mode="initial",
        executive_summary="Attractive on valuation.",
    )
    html = format_research_html([doc], ResearchSummary(documents=[doc], created=1))
    assert "Strong buy research" in html
    assert "Alpha PLC" in html
