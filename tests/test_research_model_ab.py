"""Tests for L88 research model A/B compare."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from value_investor.research.document import ResearchDocument
from value_investor.research.model_ab import (
    estimate_model_memo_usd,
    format_comparison_markdown,
    report_for_ticker,
    run_model_ab_compare,
    score_memo_rubric,
)
from value_investor.summary import CompanyReport


def _report() -> CompanyReport:
    return CompanyReport(
        ticker="AAA.L",
        name="Alpha PLC",
        sector="Industrials",
        signal="strong_buy",
        models_passed=12,
        model_count=22,
        composite_score=0.8,
        sector_composite_score=0.75,
        families_passed=5,
        passed_families="cheapness,quality",
        data_quality_score=0.9,
        metrics_present=20,
        metrics_total=20,
        weeks_at_signal=2,
        signal_trend="new",
        conviction_score=0.7,
        stability_label="stable",
        timing_signal="neutral",
        timing_score=0.5,
        rsi_14=45.0,
        price_vs_sma200_pct=1.0,
        action_note="Buy",
        trade_plan=None,
        summary="Cheap quality name.",
        passed_models=["fcf_yield"],
        key_metrics={"pe": 10.0},
    )


def _memo_doc(*, financial_review: str, risks: str = "RiskTags: cyclical") -> ResearchDocument:
    return ResearchDocument(
        ticker="AAA.L",
        name="Alpha PLC",
        signal="strong_buy",
        version=1,
        created_at="2026-08-13T00:00:00+00:00",
        updated_at="2026-08-13T00:00:00+00:00",
        mode="initial",
        executive_summary="Summary.",
        investment_thesis="Thesis.",
        financial_review=financial_review,
        risks_and_flags=risks,
        news_highlights="News.",
        research_verdict="accumulate",
        research_risk_level="medium",
        research_confidence=0.7,
        research_rationale="Filing-backed case.",
    )


def test_score_memo_rubric_prefers_filing_citations():
    strong = _memo_doc(
        financial_review=(
            "FY2025 revenue £1.2bn per annual report body in filings/bodies/annual.txt; "
            "interim 10-Q confirms margin trend."
        )
    )
    weak = _memo_doc(
        financial_review="Revenue grew per financials_annual.json (Yahoo fallback only)."
    )
    inventory = {"thin": []}

    strong_score = score_memo_rubric(strong, inventory=inventory)
    weak_score = score_memo_rubric(weak, inventory=inventory)

    assert strong_score.citation_accuracy > weak_score.citation_accuracy
    assert strong_score.filing_alignment > weak_score.filing_alignment
    assert strong_score.composite > weak_score.composite


def test_score_memo_rubric_flags_missing_gaps_when_sources_thin():
    doc = _memo_doc(financial_review="Revenue £100m with no source markers.")
    inventory = {"thin": ["filings_bodies", "yahoo_financials"]}

    score = score_memo_rubric(doc, inventory=inventory)

    assert score.gap_honesty < 1.0
    assert any("thin" in note.lower() for note in score.notes)


def test_estimate_model_memo_usd_scales_with_rates():
    assert estimate_model_memo_usd("composer-2.5", baseline_usd=0.4) == 0.4
    assert estimate_model_memo_usd("grok-4.6", baseline_usd=0.4) > 0.4


def test_report_for_ticker_case_insensitive():
    reports = [_report()]
    assert report_for_ticker(reports, "aaa.l") is reports[0]
    assert report_for_ticker(reports, "ZZZ.L") is None


@patch("value_investor.research.model_ab.run_initial_research_agent")
@patch("value_investor.research.model_ab._prepare_shared_sources")
def test_run_model_ab_compare_writes_artifacts(
    mock_prepare,
    mock_agent,
    tmp_path: Path,
):
    inventory = {"thin": [], "filings_summary": {"total": 2, "with_body": 2}}
    source_counts = {
        "financial_years": 5,
        "news_articles": 20,
        "filings_total": 2,
        "filings_annual": 1,
        "filings_interim": 1,
        "filings_with_body": 2,
    }
    mock_prepare.return_value = (inventory, source_counts)

    baseline_doc = _memo_doc(
        financial_review="Annual report in filings/bodies/annual.txt shows £100m revenue."
    )
    challenger_doc = _memo_doc(
        financial_review=(
            "10-K and interim RNS in filings/bodies/ bodies confirm £100m revenue "
            "and covenant headroom."
        ),
        risks="Missing pension note — unavailable in filing extract.\nRiskTags: pension",
    )
    mock_agent.side_effect = [
        (baseline_doc, "agent-base"),
        (challenger_doc, "agent-chall"),
    ]

    comparison = run_model_ab_compare(
        report=_report(),
        api_key="test-key",
        output_root=tmp_path / "ab",
        primary_output_dir=tmp_path / "output",
        record_spend=False,
    )

    assert comparison.output_dir.exists()
    assert (comparison.output_dir / "comparison.json").exists()
    assert (comparison.output_dir / "comparison.md").exists()
    assert (comparison.output_dir / "baseline" / "research.md").exists()
    assert (comparison.output_dir / "challenger" / "research.md").exists()
    markdown = format_comparison_markdown(comparison)
    assert "Citation accuracy" in markdown
    assert comparison.winner in {"baseline", "challenger", "tie"}
