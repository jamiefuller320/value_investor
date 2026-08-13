"""Tests for director–worker research trial orchestration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from value_investor.research.director_worker import (
    build_fallback_task_plan,
    estimate_director_worker_cost_usd,
    extract_json_object,
    normalize_task_plan,
    run_director_worker_trial,
)
from value_investor.research.document import ResearchDocument
from value_investor.summary import CompanyReport


def _report(*, interim_overlay: bool = False) -> CompanyReport:
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
        interim_quality_overlay=interim_overlay,
    )


def test_extract_json_object_from_fenced_block():
    text = """Here is the plan:
```json
{"schema_version": 1, "tasks": [{"id": "t1", "type": "screen_context"}]}
```
"""
    payload = extract_json_object(text)
    assert payload["tasks"][0]["id"] == "t1"


def test_build_fallback_task_plan_includes_gap_inventory_when_thin(tmp_path: Path):
    sources = tmp_path / "sources"
    (sources / "filings" / "bodies").mkdir(parents=True)
    (sources / "filings" / "bodies" / "annual.txt").write_text("Revenue £100m", encoding="utf-8")
    (sources / "filings" / "filings_index.json").write_text(
        '{"filings": [{"period": "annual", "body_path": "filings/bodies/annual.txt"}], "summary": {"total": 1, "with_body": 1}}',
        encoding="utf-8",
    )
    inventory = {
        "thin": ["news_manifest", "screening_snapshot"],
        "available": {"filings_bodies": True, "news_manifest": False},
    }
    plan = build_fallback_task_plan(
        report=_report(interim_overlay=True),
        inventory=inventory,
        sources_dir=sources,
        max_tasks=5,
    )
    types = {task["type"] for task in plan["tasks"]}
    assert "summarize_filing_body" in types
    assert "gap_inventory" in types
    assert any("interim-quality" in q for q in plan["open_questions"])


def test_normalize_task_plan_filters_invalid_types():
    raw = {
        "tasks": [
            {"id": "a", "type": "invalid_type", "target": "x"},
            {"id": "b", "type": "screen_context", "target": "screening_snapshot.json"},
        ]
    }
    plan = normalize_task_plan(raw, max_tasks=5)
    assert plan["tasks"][0]["type"] == "summarize_filing_body"
    assert plan["tasks"][1]["type"] == "screen_context"


def test_estimate_director_worker_cost_scales_with_workers():
    one = estimate_director_worker_cost_usd(
        worker_count=1, director_model="grok-4.6", worker_model="composer-2.5"
    )
    three = estimate_director_worker_cost_usd(
        worker_count=3, director_model="grok-4.6", worker_model="composer-2.5"
    )
    assert three > one


@patch("value_investor.research.director_worker.run_director_synthesis")
@patch("value_investor.research.director_worker.run_worker_task")
@patch("value_investor.research.director_worker.run_director_plan")
@patch("value_investor.research.director_worker.prepare_shared_research_sources")
def test_run_director_worker_trial_writes_manifest(
    mock_prepare,
    mock_plan,
    mock_worker,
    mock_synthesis,
    tmp_path: Path,
):
    inventory = {"thin": ["alternate_news"], "filings_summary": {"total": 1, "with_body": 1}}
    source_counts = {
        "financial_years": 3,
        "news_articles": 10,
        "filings_total": 1,
        "filings_annual": 1,
        "filings_interim": 0,
        "filings_with_body": 1,
    }
    mock_prepare.return_value = (inventory, source_counts)
    mock_plan.return_value = (
        {
            "schema_version": 1,
            "source": "director",
            "open_questions": ["Q1"],
            "procedural_suggestions": [],
            "tasks": [
                {
                    "id": "t1",
                    "type": "screen_context",
                    "target": "screening_snapshot.json",
                    "focus": "models passed",
                    "priority": 1,
                }
            ],
        },
        "director-plan-agent",
    )
    mock_worker.return_value = {
        "task_id": "t1",
        "task_type": "screen_context",
        "status": "completed",
        "findings": ["15/22 models passed"],
        "figures": [],
        "gaps": [],
        "sources_read": ["screening_snapshot.json"],
    }
    doc = ResearchDocument(
        ticker="AAA.L",
        name="Alpha PLC",
        signal="strong_buy",
        version=1,
        created_at="2026-08-13T00:00:00+00:00",
        updated_at="2026-08-13T00:00:00+00:00",
        mode="director_worker",
        executive_summary="Summary.",
        investment_thesis="Thesis.",
        financial_review="FY revenue £100m per filings/bodies/annual.txt.",
        risks_and_flags="Cyclical risk.\nRiskTags: cyclical",
        news_highlights="News.",
        research_verdict="accumulate",
        research_risk_level="medium",
        research_confidence=0.7,
        research_rationale="Case holds.",
    )
    mock_synthesis.return_value = (doc, "director-synth-agent")

    run = run_director_worker_trial(
        report=_report(),
        api_key="test-key",
        output_root=tmp_path / "dw",
        primary_output_dir=tmp_path / "output",
        record_spend=False,
    )

    assert (run.output_dir / "director_plan.json").exists()
    assert (run.output_dir / "workers" / "t1.json").exists()
    assert (run.output_dir / "worker_results.json").exists()
    assert (run.output_dir / "research.md").exists()
    assert (run.output_dir / "manifest.json").exists()
    assert run.worker_results[0]["status"] == "completed"
    mock_worker.assert_called_once()
    mock_synthesis.assert_called_once()
