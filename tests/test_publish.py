"""Tests for GitHub Pages dashboard publishing."""

import json
from pathlib import Path

import pandas as pd

from value_investor.publish import build_dashboard_bundle, publish_dashboard


def _write_sample_output(output_dir: Path) -> None:
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
            "passed_families": "cheapness,quality",
            "data_quality_score": 0.85,
            "metrics_present": 18,
            "metrics_total": 20,
            "weeks_at_signal": 2,
            "signal_trend": "stable",
            "conviction_score": 0.7,
            "stability_label": "building",
            "timing_signal": "accumulate",
            "timing_score": 0.75,
            "rsi_14": 34.0,
            "price_vs_sma200_pct": -0.05,
            "timing_reasons": "['RSI below neutral (34)']",
            "action_note": "Strong Buy — favourable entry timing",
            "run_at": "2026-07-08T07:00:00+00:00",
        },
        {
            "ticker": "BBB.L",
            "name": "Beta PLC",
            "sector": "Energy",
            "signal": "hold",
            "models_passed": 5,
            "model_count": 18,
            "composite_score": 0.5,
            "sector_composite_score": 0.48,
            "families_passed": 2,
            "passed_families": "cheapness",
            "data_quality_score": 0.7,
            "metrics_present": 14,
            "metrics_total": 20,
            "weeks_at_signal": 1,
            "signal_trend": "new",
            "conviction_score": 0.4,
            "stability_label": "new",
            "timing_signal": "neutral",
            "timing_score": 0.5,
            "rsi_14": 50.0,
            "price_vs_sma200_pct": 0.02,
            "timing_reasons": "[]",
            "action_note": "Hold — neutral timing",
            "run_at": "2026-07-08T07:00:00+00:00",
        },
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
    output_dir.mkdir(parents=True, exist_ok=True)
    signals.to_csv(output_dir / "latest_signals.csv", index=False)
    model_results.to_csv(output_dir / "latest_model_results.csv", index=False)
    (output_dir / "run_diff.json").write_text(
        json.dumps({"new_strong_buys": ["Alpha (AAA.L)"], "persistent_strong_buys": [], "lost_strong_buys": [], "upgrades": [], "downgrades": [], "unchanged_top_signals": 1}),
        encoding="utf-8",
    )


def test_build_dashboard_bundle_from_signals(tmp_path: Path):
    _write_sample_output(tmp_path)
    bundle = build_dashboard_bundle(tmp_path)
    assert bundle["meta"]["company_count"] == 2
    assert bundle["meta"]["strong_buy_count"] == 1
    assert bundle["reports"][0]["ticker"] == "AAA.L"
    assert bundle["run_diff"]["new_strong_buys"] == ["Alpha (AAA.L)"]


def test_publish_dashboard_writes_latest_json(tmp_path: Path):
    output_dir = tmp_path / "output"
    dest_dir = tmp_path / "docs"
    _write_sample_output(output_dir)

    path = publish_dashboard(output_dir=output_dir, dest_dir=dest_dir, include_research=False)
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["meta"]["company_count"] == 2
    assert (dest_dir / "data" / "archive" / "2026-07-08.json").exists()
