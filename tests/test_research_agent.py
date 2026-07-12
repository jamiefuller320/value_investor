"""Tests for weekly research agent verdict revision."""

from pathlib import Path
from unittest.mock import patch

from value_investor.research.agent import run_weekly_research_update_agent
from value_investor.research.document import ResearchDocument


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
