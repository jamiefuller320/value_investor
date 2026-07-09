"""Tests for research document parsing and rendering."""

from value_investor.research.document import (
    ResearchDocument,
    parse_research_sections,
    render_research_markdown,
)


def test_parse_research_sections():
    text = """EXECUTIVE SUMMARY
Strong cash generation and cheap valuation.

INVESTMENT THESIS
Passes quality and dividend screens.

FINANCIAL REVIEW
Revenue grew over five years.

RISKS AND RED FLAGS
Cyclical loan losses.

NEWS HIGHLIGHTS
Recent capital return announcement.

RESEARCH VERDICT
Verdict: accumulate
Risk: low
Confidence: 0.80
Rationale: Screen metrics confirmed by five-year trends.
"""
    sections = parse_research_sections(text)
    assert "cash generation" in sections["executive_summary"]
    assert "quality" in sections["investment_thesis"]
    assert "five years" in sections["financial_review"]
    assert "Cyclical" in sections["risks_and_flags"]
    assert "capital return" in sections["news_highlights"]
    assert "accumulate" in sections["research_verdict"]


def test_parse_weekly_update_section():
    text = """WEEKLY UPDATE
No material news this week; thesis unchanged.
"""
    sections = parse_research_sections(text)
    assert "unchanged" in sections["weekly_update"]


def test_render_research_markdown_includes_sections():
    doc = ResearchDocument(
        ticker="AAA.L",
        name="Alpha PLC",
        signal="strong_buy",
        version=2,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-07-08T00:00:00+00:00",
        mode="weekly_update",
        executive_summary="Executive text.",
        investment_thesis="Thesis text.",
        financial_review="Financial text.",
        risks_and_flags="Risk text.",
        news_highlights="News text.",
        weekly_updates=[{"date": "2026-07-08", "summary": "Weekly note."}],
    )
    markdown = render_research_markdown(doc)
    assert "# Alpha PLC (AAA.L)" in markdown
    assert "EXECUTIVE SUMMARY" in markdown
    assert "Weekly updates" in markdown
    assert "Weekly note." in markdown


def test_render_research_markdown_includes_verdict():
    doc = ResearchDocument(
        ticker="AAA.L",
        name="Alpha PLC",
        signal="strong_buy",
        version=1,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-07-08T00:00:00+00:00",
        mode="initial",
        research_verdict="accumulate",
        research_risk_level="low",
        research_confidence=0.85,
        research_rationale="Thesis confirmed.",
    )
    markdown = render_research_markdown(doc)
    assert "RESEARCH VERDICT" in markdown
    assert "Verdict: accumulate" in markdown
    assert "Thesis confirmed." in markdown
