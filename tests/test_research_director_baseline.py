"""Tests for director baseline and material-change detection."""

from __future__ import annotations

from value_investor.research.director_baseline import (
    build_director_baseline,
    evaluate_material_change,
    figure_fingerprint,
)
from value_investor.summary import CompanyReport


def _report() -> CompanyReport:
    return CompanyReport(
        ticker="VTY.L",
        name="Vistry Group PLC",
        sector="Consumer Cyclical",
        signal="strong_buy",
        models_passed=12,
        model_count=22,
        composite_score=0.9,
        sector_composite_score=0.85,
        families_passed=5,
        passed_families="cheapness,quality",
        data_quality_score=0.9,
        metrics_present=20,
        metrics_total=20,
        weeks_at_signal=1,
        signal_trend="new",
        conviction_score=0.7,
        stability_label="new",
        timing_signal="neutral",
        timing_score=0.5,
        rsi_14=50.0,
        price_vs_sma200_pct=0.0,
        action_note="Buy",
        trade_plan=None,
        summary="Housebuilder.",
        passed_models=["pe"],
        key_metrics={"pe": 8.0},
    )


def test_figure_fingerprint_stable_for_same_worker_results():
    workers = [
        {
            "figures": [
                {"metric": "revenue", "value": "£4.2bn", "period": "FY2025"},
            ]
        }
    ]
    assert figure_fingerprint(workers) == figure_fingerprint(workers)


def test_build_director_baseline_captures_open_questions():
    baseline = build_director_baseline(
        report=_report(),
        task_plan={"open_questions": ["Is dividend cover sustainable?"], "meta_reflection": []},
        worker_results=[{"figures": []}],
        inventory={"thin": ["news_manifest"]},
        source_counts={"filings_total": 7, "filings_with_body": 7},
        run_id="20260813T120000Z",
        output_dir="docs/data/research_director_worker/VTY.L/run",
        research_verdict="caution",
        research_confidence=0.42,
    )
    assert baseline["open_questions"] == ["Is dividend cover sustainable?"]
    assert baseline["screen_signal"] == "strong_buy"
    assert baseline["research_verdict"] == "caution"


def test_material_change_detects_new_annual_filing():
    baseline = build_director_baseline(
        report=_report(),
        task_plan={"open_questions": [], "meta_reflection": []},
        worker_results=[],
        inventory={"thin": ["news_manifest"]},
        source_counts={"filings_annual": 0, "filings_interim": 0, "filings_with_body": 7},
        run_id="run-1",
        output_dir="out",
        research_verdict="caution",
        research_confidence=0.4,
    )
    decision = evaluate_material_change(
        baseline=baseline,
        report=_report(),
        inventory={"thin": ["news_manifest"]},
        source_counts={"filings_annual": 1, "filings_interim": 0, "filings_with_body": 8},
    )
    assert decision.material_change is True
    assert "new_filings_annual" in decision.triggers


def test_material_change_skips_thin_ladder_when_inventory_not_inspected():
    baseline = build_director_baseline(
        report=_report(),
        task_plan={"open_questions": [], "meta_reflection": []},
        worker_results=[],
        inventory={"thin": ["news_manifest"]},
        source_counts={"filings_annual": 1, "filings_with_body": 7},
        run_id="run-1",
        output_dir="out",
        research_verdict="caution",
        research_confidence=0.4,
    )
    decision = evaluate_material_change(
        baseline=baseline,
        report=_report(),
        inventory=None,
        source_counts={"filings_annual": 1, "filings_with_body": 7},
    )
    assert decision.material_change is False


def test_material_change_false_when_unchanged():
    baseline = build_director_baseline(
        report=_report(),
        task_plan={"open_questions": [], "meta_reflection": []},
        worker_results=[],
        inventory={"thin": ["news_manifest"]},
        source_counts={"filings_annual": 1, "filings_with_body": 7},
        run_id="run-1",
        output_dir="out",
        research_verdict="caution",
        research_confidence=0.4,
    )
    decision = evaluate_material_change(
        baseline=baseline,
        report=_report(),
        inventory={"thin": ["news_manifest"]},
        source_counts={"filings_annual": 1, "filings_with_body": 7},
    )
    assert decision.material_change is False
