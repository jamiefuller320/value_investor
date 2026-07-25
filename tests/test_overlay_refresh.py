"""Tests for dashboard overlay refresh before paper automation."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.research.overlay_refresh import refresh_dashboard_bundle
from value_investor.research.document import ResearchDocument
from value_investor.research.store import ResearchStore
from value_investor.storage import write_json


def test_refresh_dashboard_bundle_from_research_index(tmp_path: Path):
    bundle_path = tmp_path / "latest.json"
    write_json(
        bundle_path,
        {
            "run_at": "2026-07-20T00:00:00+00:00",
            "reports": [
                {
                    "ticker": "AAA.L",
                    "name": "Alpha",
                    "signal": "strong_buy",
                    "models_passed": 10,
                    "model_count": 20,
                    "composite_score": 0.8,
                    "sector_composite_score": 0.7,
                    "families_passed": 4,
                    "data_quality_score": 0.9,
                    "metrics_present": 18,
                    "metrics_total": 20,
                    "weeks_at_signal": 1,
                    "signal_trend": "new",
                    "conviction_score": 0.5,
                    "stability_label": "new",
                    "timing_signal": "neutral",
                    "timing_score": 0.0,
                    "action_note": "",
                    "summary": "Screen only",
                    "passed_models": [],
                    "key_metrics": {},
                    "research_verdict": "Verdict: pass\nRisk: high",
                    "adjusted_signal": "hold",
                }
            ],
            "research": [
                {
                    "ticker": "AAA.L",
                    "name": "Alpha",
                    "version": 2,
                    "updated_at": "2026-07-20T00:00:00+00:00",
                    "research_verdict": "accumulate",
                    "research_risk_level": "medium",
                    "research_confidence": 0.72,
                }
            ],
        },
        compact=True,
    )

    count = refresh_dashboard_bundle(bundle_path, output_dir=tmp_path / "output")
    assert count == 1

    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    report = bundle["reports"][0]
    assert report["research_verdict"] == "accumulate"
    assert report["adjusted_signal"] == "strong_buy"
    assert report["research_confidence"] == 0.72


def test_refresh_dashboard_bundle_prefers_output_research_store(tmp_path: Path):
    output_dir = tmp_path / "output"
    ticker_dir = output_dir / "research" / "BBB.L"
    ticker_dir.mkdir(parents=True)
    write_json(
        ticker_dir / "research.json",
        ResearchDocument(
            ticker="BBB.L",
            name="Beta",
            signal="buy",
            version=1,
            created_at="2026-07-01T00:00:00+00:00",
            updated_at="2026-07-01T00:00:00+00:00",
            mode="initial",
            research_verdict="caution",
            research_risk_level="high",
            research_confidence=0.4,
        ).to_dict(),
        compact=True,
    )

    bundle_path = tmp_path / "latest.json"
    write_json(
        bundle_path,
        {
            "reports": [
                {
                    "ticker": "BBB.L",
                    "name": "Beta",
                    "signal": "strong_buy",
                    "models_passed": 8,
                    "model_count": 20,
                    "composite_score": 0.7,
                    "sector_composite_score": 0.6,
                    "families_passed": 3,
                    "data_quality_score": 0.8,
                    "metrics_present": 16,
                    "metrics_total": 20,
                    "weeks_at_signal": 1,
                    "signal_trend": "new",
                    "conviction_score": 0.6,
                    "stability_label": "new",
                    "timing_signal": "neutral",
                    "timing_score": 0.0,
                    "action_note": "",
                    "summary": "",
                    "passed_models": [],
                    "key_metrics": {},
                }
            ],
            "research": [
                {
                    "ticker": "BBB.L",
                    "name": "Beta",
                    "research_verdict": "accumulate",
                }
            ],
        },
        compact=True,
    )

    count = refresh_dashboard_bundle(bundle_path, output_dir=output_dir)
    assert count == 1
    assert ResearchStore(output_dir).list_documents()[0].research_verdict == "caution"

    report = json.loads(bundle_path.read_text(encoding="utf-8"))["reports"][0]
    assert report["research_verdict"] == "caution"
    assert report["adjusted_signal"] == "buy"
