"""Tests for Phase B structured-verdict slim agents."""

from pathlib import Path
from unittest.mock import patch

from value_investor.research.agent import (
    clip_rationale,
    run_gap_fill_research_agent,
    run_initial_research_agent,
    run_weekly_research_update_agent,
)
from value_investor.research.document import ResearchDocument, render_research_markdown
from value_investor.summary import CompanyReport


def _report() -> CompanyReport:
    return CompanyReport(
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


def _existing_doc() -> ResearchDocument:
    return ResearchDocument(
        ticker="AAA.L",
        name="Alpha PLC",
        signal="strong_buy",
        version=1,
        created_at="2026-07-01T00:00:00+00:00",
        updated_at="2026-07-01T00:00:00+00:00",
        mode="structured_verdict",
        research_verdict="accumulate",
        research_risk_level="low",
        research_confidence=0.8,
        research_rationale="Screen confirmed.",
        risk_tags=["pension"],
        question_outcomes=[
            {
                "question": "Is the pension deficit funded?",
                "status": "unresolved",
                "evidence": "Still missing IR PDF.",
            }
        ],
    )


def test_clip_rationale_enforces_budget():
    assert clip_rationale("short") == "short"
    clipped = clip_rationale("x" * 300)
    assert clipped is not None
    assert len(clipped) <= 240
    assert clipped.endswith("...")


@patch("value_investor.research.agent._run_agent_prompt")
def test_initial_agent_defaults_to_structured_verdict(mock_prompt, tmp_path: Path):
    mock_prompt.return_value = (
        """RESEARCH VERDICT
Verdict: accumulate
Risk: medium
Confidence: 0.66
Rationale: Filings support the screen case without new red flags.
RiskTags: cyclical, leverage
""",
        "agent-1",
    )
    sources = tmp_path / "sources"
    sources.mkdir()
    doc, _ = run_initial_research_agent(
        report=_report(),
        sources_dir=sources,
        api_key="test-key",
    )
    assert doc.mode == "structured_verdict"
    assert doc.research_verdict == "accumulate"
    assert doc.executive_summary == ""
    assert "cyclical" in doc.risk_tags
    markdown = render_research_markdown(doc)
    assert "Phase B structured verdict" in markdown
    assert "EXECUTIVE SUMMARY" not in markdown


@patch("value_investor.research.agent._run_agent_prompt")
def test_weekly_structured_update_revises_verdict(mock_prompt, tmp_path: Path):
    mock_prompt.return_value = (
        """WEEKLY UPDATE
Probe announced.

RESEARCH VERDICT
Verdict: caution
Risk: high
Confidence: 0.5
Rationale: Governance risk rose.
RiskTags: governance
""",
        "agent-3",
    )
    sources = tmp_path / "sources"
    sources.mkdir()
    news = tmp_path / "news.json"
    news.write_text("[]", encoding="utf-8")
    markdown = tmp_path / "memo.md"
    markdown.write_text("# memo", encoding="utf-8")
    updated = run_weekly_research_update_agent(
        existing=_existing_doc(),
        sources_dir=sources,
        news_batch_path=news,
        markdown_path=markdown,
        api_key="test-key",
    )
    assert updated.mode == "structured_verdict_update"
    assert updated.research_verdict == "caution"
    assert updated.weekly_updates[-1]["prior_verdict"] == "accumulate"


@patch("value_investor.research.agent._run_agent_prompt")
def test_gap_fill_defaults_to_structured(mock_prompt, tmp_path: Path):
    mock_prompt.return_value = (
        """GAP FILL UPDATE
Q: Is the pension deficit funded?
Status: unresolved
Evidence: Still missing IR PDF.
SourcesTried: filings_index
NextSources: company IR PDF

RESEARCH VERDICT
Verdict: accumulate
Risk: medium
Confidence: 0.7
Rationale: Gap remains but screen case intact.
RiskTags: pension

RESEARCH MODEL SUGGESTIONS
- area: ingest | priority: high | suggestion: Fetch IR PDFs
""",
        "agent-4",
    )
    sources = tmp_path / "sources"
    sources.mkdir()
    markdown = tmp_path / "memo.md"
    markdown.write_text("# memo", encoding="utf-8")
    existing = _existing_doc()
    existing.financial_review = "Legacy financial review kept."
    result = run_gap_fill_research_agent(
        existing=existing,
        sources_dir=sources,
        markdown_path=markdown,
        open_questions=["Is the pension deficit funded?"],
        api_key="test-key",
    )
    assert result.document.mode == "structured_verdict_gap_fill"
    assert result.document.financial_review == "Legacy financial review kept."
    assert result.document.research_verdict == "accumulate"
