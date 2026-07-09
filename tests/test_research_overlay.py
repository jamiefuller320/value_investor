"""Tests for applying research overlay to reports and signals."""

import json
from pathlib import Path

import pandas as pd

from value_investor.research.document import ResearchDocument
from value_investor.research.overlay import apply_research_overlay, enrich_signals_with_research
from value_investor.research.store import ResearchStore
from value_investor.summary import build_company_reports


def _sample_frames():
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
            "action_note": "Strong Buy — favourable entry timing",
        },
    ])
    model_results = pd.DataFrame([
        {"ticker": "AAA.L", "model_name": "Graham", "passed": True, "score": 0.9, "reasons": "['Low P/E']"},
    ])
    return signals, model_results


def test_apply_research_overlay_adjusts_report():
    signals, model_results = _sample_frames()
    report = build_company_reports(signals, model_results)[0]
    doc = ResearchDocument(
        ticker="AAA.L",
        name="Alpha PLC",
        signal="strong_buy",
        version=1,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-07-08T00:00:00+00:00",
        mode="initial",
        research_verdict="caution",
        research_risk_level="medium",
        research_confidence=0.7,
        research_rationale="Cyclical loan losses rising.",
    )

    updated = apply_research_overlay([report], [doc])[0]
    assert updated.signal == "strong_buy"
    assert updated.adjusted_signal == "buy"
    assert updated.research_verdict == "caution"
    assert updated.conviction_score < report.conviction_score
    assert "Research:" in updated.action_note
    assert "Research overlay" in updated.summary


def test_enrich_signals_with_research(tmp_path: Path):
    signals, _ = _sample_frames()
    store = ResearchStore(tmp_path)
    doc = ResearchDocument(
        ticker="AAA.L",
        name="Alpha PLC",
        signal="strong_buy",
        version=1,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-07-08T00:00:00+00:00",
        mode="initial",
        research_verdict="pass",
        research_risk_level="high",
        research_confidence=0.6,
        research_rationale="Balance sheet weaker than screen suggests.",
    )
    store.save(doc)

    enriched = enrich_signals_with_research(signals, tmp_path)
    row = enriched.iloc[0]
    assert row["research_verdict"] == "pass"
    assert row["adjusted_signal"] == "hold"
    assert row["signal"] == "strong_buy"

    meta = json.loads((tmp_path / "research" / "AAA.L" / "research.json").read_text())
    assert meta["research_verdict"] == "pass"
