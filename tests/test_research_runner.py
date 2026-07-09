"""Tests for research runner orchestration."""

from unittest.mock import patch

import pandas as pd

from value_investor.research.document import ResearchDocument
from value_investor.research.runner import eligible_strong_buys, run_research_for_strong_buys
from value_investor.summary import build_company_reports


def _strong_buy_report():
    signals = pd.DataFrame([
        {
            "ticker": "AAA.L",
            "name": "Alpha PLC",
            "sector": "Financials",
            "signal": "strong_buy",
            "models_passed": 10,
            "model_count": 18,
            "composite_score": 0.8,
            "sector_composite_score": 0.82,
            "families_passed": 3,
            "passed_families": "cheapness,quality,dividend",
            "data_quality_score": 0.85,
            "metrics_present": 18,
            "metrics_total": 20,
            "weeks_at_signal": 3,
            "signal_trend": "stable",
            "conviction_score": 0.72,
            "stability_label": "building",
            "timing_signal": "accumulate",
            "timing_score": 0.75,
            "rsi_14": 34.0,
            "price_vs_sma200_pct": -0.08,
            "timing_reasons": ["RSI below neutral (34)"],
            "action_note": "Strong Buy — favourable entry timing",
        }
    ])
    model_results = pd.DataFrame([
        {
            "ticker": "AAA.L",
            "model_name": "Graham Defensive",
            "passed": True,
            "score": 1.0,
            "reasons": "[]",
            "failed_criteria": "[]",
        }
    ])
    return build_company_reports(signals, model_results)[0]


def test_eligible_strong_buys_filters_low_quality():
    report = _strong_buy_report()
    report_low_quality = _strong_buy_report()
    report_low_quality.data_quality_score = 0.4
    eligible = eligible_strong_buys([report, report_low_quality])
    assert len(eligible) == 1
    assert eligible[0].ticker == "AAA.L"


@patch("value_investor.research.runner.run_initial_research_agent")
@patch("value_investor.research.runner.ingest_research_sources")
def test_run_research_for_strong_buys_creates_initial_memo(mock_ingest, mock_initial, tmp_path):
    mock_ingest.return_value = {
        "financials_path": "f.json",
        "snapshot_path": "s.json",
        "news_manifest_path": "n.json",
        "news_batch_path": "b.json",
        "financial_years": 5,
        "news_total": 12,
        "news_new": 12,
    }
    mock_initial.return_value = (
        ResearchDocument(
            ticker="AAA.L",
            name="Alpha PLC",
            signal="strong_buy",
            version=1,
            created_at="2026-07-08T00:00:00+00:00",
            updated_at="2026-07-08T00:00:00+00:00",
            mode="initial",
            executive_summary="Deep memo.",
            agent_id="agent-1",
        ),
        "agent-1",
    )

    summary = run_research_for_strong_buys(
        reports=[_strong_buy_report()],
        output_dir=tmp_path,
        api_key="test-key",
    )

    assert summary.created == 1
    assert summary.documents[0].executive_summary == "Deep memo."
    assert (tmp_path / "research" / "AAA.L" / "research.md").exists()
