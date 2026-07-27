"""Tests for screening pipeline snapshot export behaviour."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import value_investor.pipeline  # noqa: F401 — installs research snapshot hooks
from value_investor.research.document import ResearchDocument
from value_investor.research.overlay import apply_research_overlay
from value_investor.research.store import ResearchStore
from value_investor.scoring.snapshot import refresh_snapshot_from_document, sync_research_verdict_snapshots
from value_investor.storage import write_json
from value_investor.summary import CompanyReport, build_company_reports


def _minimal_report(**overrides) -> CompanyReport:
    base = dict(
        ticker="FGP.L",
        name="FirstGroup plc",
        sector="Industrials",
        signal="strong_buy",
        models_passed=11,
        model_count=22,
        composite_score=0.9,
        sector_composite_score=0.85,
        families_passed=5,
        passed_families="cheapness,quality,dividend,garp,risk",
        data_quality_score=1.0,
        metrics_present=20,
        metrics_total=20,
        weeks_at_signal=1,
        signal_trend="new",
        conviction_score=0.5,
        stability_label="new",
        timing_signal="neutral",
        timing_score=0.5,
        rsi_14=50.0,
        price_vs_sma200_pct=0.0,
        action_note="",
        trade_plan=None,
        summary="test",
        passed_models=["FCF Yield"],
        key_metrics={"P/E": "9.1"},
        failed_models=["Financial Health"],
        model_failures={"Financial Health": ["weak liquidity"]},
        screening_inputs={
            "debt_to_equity": 140.0,
            "current_ratio": 0.73,
            "earnings_growth_pct": -0.072,
            "ncav_available": False,
            "dividend_yield_raw": 0.04,
        },
    )
    base.update(overrides)
    return CompanyReport(**base)


def test_screening_snapshot_written_with_failed_models_and_piotroski(tmp_path: Path):
    signals = pd.DataFrame([
        {
            "ticker": "GFTU.L",
            "name": "Grafton Group plc",
            "sector": "Industrials",
            "signal": "strong_buy",
            "models_passed": 11,
            "model_count": 22,
            "composite_score": 0.84,
            "sector_composite_score": 0.8,
            "families_passed": 5,
            "passed_families": "cheapness,quality,dividend,garp,risk",
            "data_quality_score": 1.0,
            "metrics_present": 20,
            "metrics_total": 20,
            "weeks_at_signal": 1,
            "signal_trend": "new",
            "conviction_score": 0.51,
            "stability_label": "new",
            "timing_signal": "neutral",
            "timing_score": 0.5,
            "rsi_14": 63.0,
            "price_vs_sma200_pct": 0.0,
            "timing_reasons": "[]",
            "action_note": "",
        }
    ])
    model_results = pd.DataFrame([
        {
            "ticker": "GFTU.L",
            "model_id": "buffett_quality",
            "model_name": "Buffett Quality",
            "passed": False,
            "score": 0.2,
            "reasons": "[]",
            "failed_criteria": "['ROE below threshold']",
        },
        {
            "ticker": "GFTU.L",
            "model_id": "piotroski_f",
            "model_name": "Piotroski F-Score",
            "passed": True,
            "score": 8 / 9,
            "reasons": "['F-Score=8/9', 'positive net income', 'positive operating cash flow']",
            "failed_criteria": "['asset turnover improving']",
        },
    ])

    snapshot = build_company_reports(signals, model_results)[0].to_dict()
    snapshot_path = tmp_path / "screening_snapshot.json"
    write_json(snapshot_path, snapshot, compact=True, compress=False)

    written = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert "Buffett Quality" in written["failed_models"]
    assert written["model_failures"]["Buffett Quality"] == ["ROE below threshold"]
    assert written["piotroski_f_score"]["score"] == 8
    assert written["piotroski_f_score"]["passed"] is True
    assert written["signal"] == "strong_buy"


def test_refresh_snapshot_from_document_merges_research_verdict(tmp_path: Path):
    sources_dir = tmp_path / "research" / "FGP.L" / "sources"
    sources_dir.mkdir(parents=True)
    write_json(
        sources_dir / "screening_snapshot.json",
        {"ticker": "FGP.L", "signal": "strong_buy", "research_verdict": None},
        compact=True,
    )
    doc = ResearchDocument(
        ticker="FGP.L",
        name="FirstGroup plc",
        signal="strong_buy",
        version=2,
        created_at="2026-07-26T00:00:00+00:00",
        updated_at="2026-07-26T00:00:00+00:00",
        mode="gap_fill",
        research_verdict="caution",
        research_risk_level="medium",
        research_confidence=0.62,
        research_rationale="Leverage flags confirmed.",
        research_path=str(tmp_path / "research" / "FGP.L" / "research.md"),
    )

    assert refresh_snapshot_from_document(tmp_path, doc) is True
    written = json.loads((sources_dir / "screening_snapshot.json").read_text(encoding="utf-8"))
    assert written["research_verdict"] == "caution"
    assert written["research_risk_level"] == "medium"
    assert written["research_confidence"] == 0.62
    assert written["adjusted_signal"] == "buy"


def test_sync_research_verdict_snapshots_writes_full_report(tmp_path: Path):
    report = _minimal_report()
    doc = ResearchDocument(
        ticker="FGP.L",
        name="FirstGroup plc",
        signal="strong_buy",
        version=2,
        created_at="2026-07-26T00:00:00+00:00",
        updated_at="2026-07-26T00:00:00+00:00",
        mode="gap_fill",
        research_verdict="accumulate",
        research_risk_level="low",
        research_confidence=0.7,
        research_path=str(tmp_path / "research" / "FGP.L" / "research.md"),
    )

    updated = sync_research_verdict_snapshots(tmp_path, [report], [doc])
    assert updated == 1

    snapshot_path = tmp_path / "research" / "FGP.L" / "sources" / "screening_snapshot.json"
    written = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert written["screening_inputs"]["debt_to_equity"] == 140.0
    assert written["model_failures"]["Financial Health"] == ["weak liquidity"]
    assert written["research_verdict"] == "accumulate"
    assert written["adjusted_signal"] == "strong_buy"


def test_apply_research_overlay_syncs_screening_snapshot(tmp_path: Path):
    report = _minimal_report()
    doc = ResearchDocument(
        ticker="FGP.L",
        name="FirstGroup plc",
        signal="strong_buy",
        version=2,
        created_at="2026-07-26T00:00:00+00:00",
        updated_at="2026-07-26T00:00:00+00:00",
        mode="gap_fill",
        research_verdict="caution",
        research_risk_level="medium",
        research_confidence=0.62,
        research_path=str(tmp_path / "research" / "FGP.L" / "research.md"),
    )

    updated = apply_research_overlay([report], [doc])
    assert updated[0].research_verdict == "caution"

    snapshot_path = tmp_path / "research" / "FGP.L" / "sources" / "screening_snapshot.json"
    written = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert written["research_verdict"] == "caution"
    assert written["screening_inputs"]["current_ratio"] == 0.73


def test_research_store_save_refreshes_screening_snapshot(tmp_path: Path):
    sources_dir = tmp_path / "research" / "FGP.L" / "sources"
    sources_dir.mkdir(parents=True)
    write_json(
        sources_dir / "screening_snapshot.json",
        {"ticker": "FGP.L", "signal": "strong_buy"},
        compact=True,
    )
    store = ResearchStore(tmp_path)
    doc = ResearchDocument(
        ticker="FGP.L",
        name="FirstGroup plc",
        signal="strong_buy",
        version=1,
        created_at="2026-07-26T00:00:00+00:00",
        updated_at="2026-07-26T00:00:00+00:00",
        mode="gap_fill",
        research_verdict="pass",
        research_confidence=0.5,
    )
    store.save(doc)

    written = json.loads((sources_dir / "screening_snapshot.json").read_text(encoding="utf-8"))
    assert written["research_verdict"] == "pass"
    assert written["adjusted_signal"] == "hold"
