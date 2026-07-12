"""Tests for model family aggregation."""

import pandas as pd

from value_investor.model_families import MODEL_FAMILIES, summarize_by_family


def test_summarize_by_family_counts_independent_passes():
    model_results = pd.DataFrame([
        {"ticker": "AAA.L", "model_id": "graham_defensive", "passed": True, "score": 1.0},
        {"ticker": "AAA.L", "model_id": "deep_value", "passed": True, "score": 0.9},
        {"ticker": "AAA.L", "model_id": "piotroski_f", "passed": True, "score": 0.8},
        {"ticker": "AAA.L", "model_id": "high_dividend", "passed": False, "score": 0.2},
        {"ticker": "BBB.L", "model_id": "graham_defensive", "passed": True, "score": 0.7},
        {"ticker": "BBB.L", "model_id": "piotroski_f", "passed": False, "score": 0.3},
    ])

    summary = summarize_by_family(model_results)
    alpha = summary[summary["ticker"] == "AAA.L"].iloc[0]
    beta = summary[summary["ticker"] == "BBB.L"].iloc[0]

    assert alpha["families_passed"] == 2
    assert "cheapness" in alpha["passed_families"]
    assert "quality" in alpha["passed_families"]
    assert beta["families_passed"] == 1
    assert len(MODEL_FAMILIES) == 5
