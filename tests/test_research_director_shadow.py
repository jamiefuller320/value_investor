"""Tests for observe-only director shadow logging."""

from __future__ import annotations

from pathlib import Path

from value_investor.research.director_baseline import build_director_baseline
from value_investor.research.director_shadow import (
    RECOMMEND_ESCALATE,
    RECOMMEND_MONITOR,
    RECOMMEND_RE_ESCALATE,
    append_shadow_log_entry,
    evaluate_director_shadow,
    load_shadow_log,
    record_director_shadow_entry,
)
from value_investor.research.document import ResearchDocument
from value_investor.summary import CompanyReport


def _report(**kwargs) -> CompanyReport:
    defaults = dict(
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
        interim_quality_overlay=False,
    )
    defaults.update(kwargs)
    return CompanyReport(**defaults)


def _doc(**kwargs) -> ResearchDocument:
    defaults = dict(
        ticker="VTY.L",
        name="Vistry Group PLC",
        signal="strong_buy",
        version=1,
        created_at="2026-08-13T00:00:00+00:00",
        updated_at="2026-08-13T00:00:00+00:00",
        mode="initial",
        research_verdict="accumulate",
        research_confidence=0.65,
        source_counts={"filings_total": 7, "filings_with_body": 7},
    )
    defaults.update(kwargs)
    return ResearchDocument(**defaults)


def test_evaluate_director_shadow_recommends_escalate_on_thin_sources():
    decision = evaluate_director_shadow(
        report=_report(interim_quality_overlay=True),
        doc=_doc(),
        sources_dir=None,
        research_action="created",
    )
    assert decision.recommended_action == RECOMMEND_ESCALATE
    assert decision.escalation["should_escalate"] is True


def test_evaluate_director_shadow_recommends_monitor_when_baseline_present():
    baseline = build_director_baseline(
        report=_report(),
        task_plan={"open_questions": ["Q1"], "meta_reflection": []},
        worker_results=[],
        inventory={"thin": ["news_manifest"]},
        source_counts={"filings_annual": 1, "filings_with_body": 7},
        run_id="run-1",
        output_dir="out",
        research_verdict="caution",
        research_confidence=0.4,
    )
    decision = evaluate_director_shadow(
        report=_report(),
        doc=_doc(director_baseline=baseline),
        sources_dir=None,
        research_action="updated",
    )
    assert decision.recommended_action == RECOMMEND_MONITOR
    assert decision.material_change is not None
    assert decision.material_change["material_change"] is False


def test_evaluate_director_shadow_recommends_re_escalate_on_material_change():
    baseline = build_director_baseline(
        report=_report(),
        task_plan={"open_questions": [], "meta_reflection": []},
        worker_results=[],
        inventory={"thin": ["news_manifest"]},
        source_counts={"filings_annual": 0, "filings_with_body": 7},
        run_id="run-1",
        output_dir="out",
        research_verdict="caution",
        research_confidence=0.4,
    )
    decision = evaluate_director_shadow(
        report=_report(),
        doc=_doc(
            director_baseline=baseline,
            source_counts={"filings_annual": 1, "filings_with_body": 8},
        ),
        sources_dir=None,
        research_action="updated",
    )
    assert decision.recommended_action == RECOMMEND_RE_ESCALATE
    assert decision.material_change["material_change"] is True


def test_record_director_shadow_entry_appends_log(tmp_path: Path):
    log_path = tmp_path / "shadow_log.json"
    entry = record_director_shadow_entry(
        report=_report(),
        doc=_doc(),
        sources_dir=None,
        research_action="created",
        shadow_log_path=log_path,
    )
    assert entry["mode"] == "shadow"
    log = load_shadow_log(log_path)
    assert len(log["entries"]) == 1
    assert log["entries"][0]["ticker"] == "VTY.L"


def test_append_shadow_log_entry_trims_to_max(tmp_path: Path):
    log_path = tmp_path / "shadow_log.json"
    for idx in range(3):
        append_shadow_log_entry({"idx": idx}, path=log_path, max_entries=2)
    log = load_shadow_log(log_path)
    assert len(log["entries"]) == 2
    assert log["entries"][0]["idx"] == 1
