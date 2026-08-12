"""Tests for weekly research agent verdict revision."""

from pathlib import Path
from unittest.mock import patch

from value_investor.research.agent import (
    run_gap_fill_research_agent,
    run_initial_research_agent,
    run_weekly_research_update_agent,
)
from value_investor.research.document import ResearchDocument
from value_investor.summary import CompanyReport


def _existing_doc() -> ResearchDocument:
    return ResearchDocument(
        ticker="AAA.L",
        name="Alpha PLC",
        signal="strong_buy",
        version=1,
        created_at="2026-07-01T00:00:00+00:00",
        updated_at="2026-07-01T00:00:00+00:00",
        mode="initial",
        executive_summary="Attractive on valuation.",
        risks_and_flags="Pension deficit not fully funded.",
        risk_tags=["pension"],
        question_outcomes=[
            {
                "question": "Is the pension deficit funded?",
                "status": "unresolved",
                "evidence": "Still missing IR PDF.",
            }
        ],
        research_verdict="accumulate",
        research_risk_level="low",
        research_confidence=0.8,
        research_rationale="Screen confirmed by quality metrics.",
    )


@patch("value_investor.research.agent._run_agent_prompt")
def test_weekly_agent_revises_verdict_when_material_news(mock_prompt, tmp_path: Path):
    mock_prompt.return_value = (
        """WEEKLY UPDATE
Regulatory probe announced; thesis weakened.

RESEARCH VERDICT
Verdict: caution
Risk: high
Confidence: 0.55
Rationale: Probe raises governance risk not captured in screens.
""",
        "agent-1",
    )
    existing = _existing_doc()
    sources = tmp_path / "sources"
    sources.mkdir()
    news_batch = tmp_path / "news_batch.json"
    news_batch.write_text("[]", encoding="utf-8")
    markdown = tmp_path / "research.md"
    markdown.write_text("# Alpha", encoding="utf-8")

    updated = run_weekly_research_update_agent(
        existing=existing,
        sources_dir=sources,
        news_batch_path=news_batch,
        markdown_path=markdown,
        api_key="test-key",
    )

    assert updated.research_verdict == "caution"
    assert updated.research_risk_level == "high"
    assert updated.research_confidence == 0.55
    assert updated.weekly_updates[-1]["prior_verdict"] == "accumulate"
    assert updated.weekly_updates[-1]["new_verdict"] == "caution"


@patch("value_investor.research.agent._run_agent_prompt")
def test_weekly_agent_keeps_verdict_when_unchanged(mock_prompt, tmp_path: Path):
    mock_prompt.return_value = (
        """WEEKLY UPDATE
No material news this week.

RESEARCH VERDICT
Verdict: accumulate
Risk: low
Confidence: 0.80
Rationale: Thesis unchanged.
""",
        "agent-1",
    )
    existing = _existing_doc()
    sources = tmp_path / "sources"
    sources.mkdir()
    news_batch = tmp_path / "news_batch.json"
    news_batch.write_text("[]", encoding="utf-8")
    markdown = tmp_path / "research.md"
    markdown.write_text("# Alpha", encoding="utf-8")

    updated = run_weekly_research_update_agent(
        existing=existing,
        sources_dir=sources,
        news_batch_path=news_batch,
        markdown_path=markdown,
        api_key="test-key",
    )

    assert updated.research_verdict == "accumulate"
    assert "prior_verdict" not in updated.weekly_updates[-1]


@patch("value_investor.research.agent._run_agent_prompt")
def test_weekly_prompt_injects_prior_risks_and_open_questions(mock_prompt, tmp_path: Path):
    mock_prompt.return_value = (
        """WEEKLY UPDATE
No material news.

Q: Is the pension deficit funded?
Status: unresolved
Evidence: no bearing this week

RESEARCH VERDICT
Verdict: accumulate
Risk: low
Confidence: 0.80
Rationale: Thesis unchanged.
""",
        "agent-1",
    )
    existing = _existing_doc()
    sources = tmp_path / "sources"
    sources.mkdir()
    news_batch = tmp_path / "news_batch.json"
    news_batch.write_text("[]", encoding="utf-8")
    markdown = tmp_path / "research.md"
    markdown.write_text("# Alpha", encoding="utf-8")

    updated = run_weekly_research_update_agent(
        existing=existing,
        sources_dir=sources,
        news_batch_path=news_batch,
        markdown_path=markdown,
        api_key="test-key",
    )

    prompt = mock_prompt.call_args.kwargs["prompt"]
    assert "Pension deficit not fully funded." in prompt
    assert "Is the pension deficit funded?" in prompt
    assert "Prior RiskTags: pension" in prompt
    assert updated.question_outcomes
    assert updated.question_outcomes[0]["status"] == "unresolved"
    assert updated.risk_tags == ["pension"]


@patch("value_investor.research.agent._run_agent_prompt")
def test_initial_agent_parses_risk_tags(mock_prompt, tmp_path: Path):
    mock_prompt.return_value = (
        """EXECUTIVE SUMMARY
Cheap quality.

INVESTMENT THESIS
Screen confirmed.

FINANCIAL REVIEW
Stable margins.

RISKS AND RED FLAGS
Cyclical fee income.
RiskTags: cyclical, leverage

NEWS HIGHLIGHTS
Quiet week.

RESEARCH VERDICT
Verdict: accumulate
Risk: medium
Confidence: 0.70
Rationale: Confirmed.
""",
        "agent-1",
    )
    sources = tmp_path / "sources"
    sources.mkdir()
    report = CompanyReport(
        ticker="AAA.L",
        name="Alpha PLC",
        sector="Financials",
        signal="strong_buy",
        models_passed=10,
        model_count=18,
        composite_score=0.8,
        sector_composite_score=0.8,
        families_passed=3,
        passed_families="cheapness",
        data_quality_score=0.9,
        metrics_present=18,
        metrics_total=20,
        weeks_at_signal=1,
        signal_trend="new",
        conviction_score=0.7,
        stability_label="new",
        timing_signal="accumulate",
        timing_score=0.7,
        rsi_14=40.0,
        price_vs_sma200_pct=-0.05,
        action_note="Strong Buy",
        trade_plan=None,
        summary="ok",
        passed_models=["graham"],
        key_metrics={},
    )
    doc, _ = run_initial_research_agent(
        report=report,
        sources_dir=sources,
        api_key="test-key",
    )
    assert doc.risk_tags == ["cyclical", "leverage"]


@patch("value_investor.research.agent._run_agent_prompt")
def test_gap_fill_persists_question_outcomes_on_document(mock_prompt, tmp_path: Path):
    mock_prompt.return_value = (
        """GAP FILL UPDATE
Q: Is the pension deficit funded?
Status: partially_resolved
Evidence: Note 18 shows deficit narrowed.
SourcesTried: filings_bodies
NextSources: none

FINANCIAL REVIEW
Deficit narrowed.

RISKS AND RED FLAGS
Pension still material.
RiskTags: pension

RESEARCH VERDICT
Verdict: accumulate
Risk: medium
Confidence: 0.65
Rationale: Gap narrowed.

RESEARCH MODEL SUGGESTIONS
- area: ingest | priority: high | suggestion: Pull IR PDFs
""",
        "agent-2",
    )
    existing = _existing_doc()
    sources = tmp_path / "sources"
    sources.mkdir()
    markdown = tmp_path / "research.md"
    markdown.write_text("# Alpha", encoding="utf-8")
    result = run_gap_fill_research_agent(
        existing=existing,
        sources_dir=sources,
        markdown_path=markdown,
        open_questions=["Is the pension deficit funded?"],
        api_key="test-key",
    )
    assert result.document.question_outcomes
    assert result.document.question_outcomes[0]["status"] == "partially_resolved"
    assert result.document.risk_tags == ["pension"]
    assert result.question_outcomes[0]["question"] == "Is the pension deficit funded?"
