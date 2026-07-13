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
    assert "Research memos" in html
    assert "Alpha PLC" in html


def test_research_documents_for_reports_includes_buys():
    import pandas as pd

    from value_investor.research.format import research_documents_for_reports
    from value_investor.summary import build_company_reports

    signals = pd.DataFrame(
        [
            {
                "ticker": "AAA.L",
                "name": "Alpha",
                "sector": "Financials",
                "signal": "strong_buy",
                "models_passed": 10,
                "model_count": 18,
                "composite_score": 0.8,
                "data_quality_score": 0.9,
                "metrics_present": 18,
                "metrics_total": 20,
                "weeks_at_signal": 1,
                "signal_trend": "stable",
                "conviction_score": 0.8,
                "stability_label": "new",
            },
            {
                "ticker": "BBB.L",
                "name": "Beta",
                "sector": "Energy",
                "signal": "buy",
                "models_passed": 8,
                "model_count": 18,
                "composite_score": 0.7,
                "data_quality_score": 0.8,
                "metrics_present": 16,
                "metrics_total": 20,
                "weeks_at_signal": 1,
                "signal_trend": "stable",
                "conviction_score": 0.6,
                "stability_label": "new",
            },
            {
                "ticker": "CCC.L",
                "name": "Gamma",
                "sector": "Utilities",
                "signal": "hold",
                "models_passed": 4,
                "model_count": 18,
                "composite_score": 0.4,
                "data_quality_score": 0.8,
                "metrics_present": 16,
                "metrics_total": 20,
                "weeks_at_signal": 1,
                "signal_trend": "stable",
                "conviction_score": 0.3,
                "stability_label": "new",
            },
        ]
    )
    model_results = pd.DataFrame(
        [
            {
                "ticker": "AAA.L",
                "model_name": "Graham Defensive",
                "passed": True,
                "score": 1.0,
                "reasons": "[]",
                "failed_criteria": "[]",
            }
        ]
    )
    reports = build_company_reports(signals, model_results)
    docs = [
        ResearchDocument(
            ticker="AAA.L",
            name="Alpha",
            signal="strong_buy",
            version=1,
            created_at="2026-07-01T00:00:00+00:00",
            updated_at="2026-07-01T00:00:00+00:00",
            mode="initial",
        ),
        ResearchDocument(
            ticker="BBB.L",
            name="Beta",
            signal="buy",
            version=1,
            created_at="2026-07-01T00:00:00+00:00",
            updated_at="2026-07-01T00:00:00+00:00",
            mode="initial",
        ),
        ResearchDocument(
            ticker="CCC.L",
            name="Gamma",
            signal="hold",
            version=1,
            created_at="2026-07-01T00:00:00+00:00",
            updated_at="2026-07-01T00:00:00+00:00",
            mode="initial",
        ),
    ]
    ordered = research_documents_for_reports(reports, docs)
    assert [d.ticker for d in ordered] == ["AAA.L", "BBB.L"]
