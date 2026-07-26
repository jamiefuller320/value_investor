"""Tests for screening pipeline snapshot export behaviour."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from value_investor.storage import write_json
from value_investor.summary import build_company_reports


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
    assert written["piotroski_f_score"]["score"] == 8
    assert written["piotroski_f_score"]["passed"] is True
    assert written["signal"] == "strong_buy"
