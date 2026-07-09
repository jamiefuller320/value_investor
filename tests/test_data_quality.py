"""Tests for data quality scoring."""

from value_investor.data_quality import (
    MIN_QUALITY_FOR_ANALYSIS,
    add_data_quality_scores,
    quality_label,
    score_data_quality,
)


def test_score_data_quality_full_row():
    row = {
        "market_cap": 1000,
        "trailing_pe": 10,
        "price_to_book": 1.0,
        "dividend_yield": 0.04,
        "current_ratio": 2.0,
        "debt_to_equity": 40,
        "return_on_equity": 0.12,
        "return_on_assets": 0.08,
        "profit_margins": 0.1,
        "free_cashflow": 100,
        "enterprise_value": 1100,
        "ebitda": 200,
        "ebit": 180,
        "total_revenue": 1500,
        "total_assets": 2000,
        "net_income": 120,
        "operating_cashflow": 150,
        "book_value": 800,
        "shares_outstanding": 100,
        "total_current_assets": 500,
        "errors": [],
    }
    score, present, total = score_data_quality(row)
    assert score == 1.0
    assert present == total == 20
    assert quality_label(score) == "high"


def test_score_data_quality_penalises_sparse_row():
    row = {"market_cap": 1000, "trailing_pe": 10, "errors": ["no market data"]}
    score, present, _ = score_data_quality(row)
    assert present < 5
    assert score < MIN_QUALITY_FOR_ANALYSIS


def test_add_data_quality_scores_to_frame():
    import pandas as pd

    frame = pd.DataFrame([{"market_cap": 1, "trailing_pe": 10}])
    out = add_data_quality_scores(frame)
    assert "data_quality_score" in out.columns
    assert out["metrics_present"].iloc[0] == 2
