"""Tests for verify-before-trade decision packs."""

from value_investor.decision_pack import (
    LEVELS_GAP,
    THESIS_GAP,
    attach_decision_packs,
    build_decision_pack,
    format_decision_packs_text,
)
from value_investor.emailer import format_text_report
from value_investor.research.document import ResearchDocument
from value_investor.summary import CompanyReport
from value_investor.technical_analysis import TradePlan


def _report(**overrides) -> CompanyReport:
    base = dict(
        ticker="AAA.L",
        name="Alpha PLC",
        sector="Financials",
        signal="strong_buy",
        models_passed=10,
        model_count=18,
        composite_score=0.8,
        sector_composite_score=0.82,
        families_passed=3,
        passed_families="cheapness,quality",
        data_quality_score=0.85,
        metrics_present=18,
        metrics_total=20,
        weeks_at_signal=3,
        signal_trend="stable",
        conviction_score=0.72,
        stability_label="building",
        timing_signal="accumulate",
        timing_score=0.75,
        rsi_14=34.0,
        price_vs_sma200_pct=-0.08,
        action_note="Strong Buy — favourable entry timing",
        trade_plan=TradePlan(
            core_order="limit",
            core_limit=98.5,
            core_allocation_pct=0.65,
            tactical_order="limit",
            tactical_limit=95.0,
            tactical_allocation_pct=0.35,
            tactical_stop_loss=92.0,
            tactical_take_profit=105.0,
            trade_plan_summary=(
                "Trade plan: core 65% limit £98.50; tactical 35% limit £95.00; "
                "tactical stop £92.00, target £105.00."
            ),
        ),
        summary="Cheap quality name with building conviction.",
        passed_models=["graham"],
        key_metrics={},
    )
    base.update(overrides)
    return CompanyReport(**base)


def test_full_pack_with_research_memo():
    research = ResearchDocument(
        ticker="AAA.L",
        name="Alpha PLC",
        signal="strong_buy",
        version=1,
        created_at="2026-07-01T00:00:00+00:00",
        updated_at="2026-07-01T00:00:00+00:00",
        mode="initial",
        executive_summary="Solid balance sheet.",
        investment_thesis="Franchise cash generation supports the cheap valuation.",
        risks_and_flags="Cyclical fee income; key-person risk.",
        research_verdict="accumulate",
        research_risk_level="medium",
        research_confidence=0.7,
    )
    pack = build_decision_pack(_report(), research)
    assert "Franchise cash generation" in pack.thesis
    assert "£98.50" in pack.levels
    assert "core sleeve" in pack.size
    assert "Cyclical fee income" in pack.risks
    assert pack.gaps == []
    assert pack.high_conviction is True
    assert any("verify figures" in item.lower() for item in pack.verify)


def test_thin_pack_explicit_gaps():
    pack = build_decision_pack(
        _report(
            trade_plan=None,
            summary="",
            research_verdict=None,
            data_quality_score=0.4,
        )
    )
    assert pack.thesis == THESIS_GAP
    assert pack.levels == LEVELS_GAP
    assert "thesis" in pack.gaps
    assert "levels" in pack.gaps
    assert pack.high_conviction is False
    assert any("incomplete" in item.lower() for item in pack.verify)


def test_caution_verdict_desizes():
    pack = build_decision_pack(
        _report(research_verdict="caution", research_confidence=0.3),
        ResearchDocument(
            ticker="AAA.L",
            name="Alpha",
            signal="strong_buy",
            version=1,
            created_at="x",
            updated_at="x",
            mode="initial",
            investment_thesis="Thin filings.",
            risks_and_flags="Unresolved covenants.",
            research_verdict="caution",
            research_confidence=0.3,
        ),
    )
    assert pack.high_conviction is False
    joined = " ".join(pack.verify).lower()
    assert "caution" in joined
    assert "low" in joined


def test_attach_decision_packs_on_buy_tier_only():
    reports = [
        {"ticker": "AAA.L", "name": "A", "signal": "strong_buy", "conviction_score": 0.8},
        {"ticker": "BBB.L", "name": "B", "signal": "hold", "conviction_score": 0.2},
    ]
    attach_decision_packs(reports)
    assert "decision_pack" in reports[0]
    assert "decision_pack" not in reports[1]
    assert "Verify" in " ".join(reports[0]["decision_pack"]["verify"]) or reports[0][
        "decision_pack"
    ]["verify"]


def test_email_includes_verify_before_trade_section():
    text = format_text_report(run_at="2026-07-21", reports=[_report()])
    assert "VERIFY-BEFORE-TRADE PACKS" in text
    assert "Alpha PLC" in text
    packs_text = format_decision_packs_text([build_decision_pack(_report())])
    assert packs_text is not None
    assert "Thesis:" in packs_text
