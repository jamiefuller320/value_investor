"""Tests for director escalation gate."""

from __future__ import annotations

from value_investor.research.director_escalation import evaluate_director_escalation
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
    )
    defaults.update(kwargs)
    return ResearchDocument(**defaults)


def test_escalation_requires_composer_memo_first():
    decision = evaluate_director_escalation(
        report=_report(),
        existing_doc=None,
        source_quality={"grade": "thin"},
        inventory={"thin": ["yahoo_financials", "news_manifest"]},
    )
    assert decision.should_escalate is False
    assert "Composer initial memo" in decision.reasons[0]


def test_escalation_fires_on_thin_sources_and_overlay():
    decision = evaluate_director_escalation(
        report=_report(interim_quality_overlay=True),
        existing_doc=_doc(),
        source_quality={"grade": "thin", "thin_gaps": ["yahoo_financials"]},
        inventory={"thin": ["yahoo_financials", "screening_snapshot"]},
    )
    assert decision.should_escalate is True
    assert "thin_sources" in decision.triggers
    assert "interim_quality_overlay" in decision.triggers


def test_escalation_fires_on_screen_memo_mismatch():
    decision = evaluate_director_escalation(
        report=_report(signal="strong_buy"),
        existing_doc=_doc(research_verdict="caution", research_confidence=0.4),
        source_quality={"grade": "adequate"},
        inventory={"thin": []},
    )
    assert decision.should_escalate is True
    assert "screen_memo_mismatch" in decision.triggers


def test_escalation_clear_when_no_triggers():
    decision = evaluate_director_escalation(
        report=_report(),
        existing_doc=_doc(research_verdict="accumulate", research_confidence=0.75),
        source_quality={"grade": "adequate"},
        inventory={"thin": []},
    )
    assert decision.should_escalate is False
