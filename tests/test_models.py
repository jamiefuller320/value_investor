"""Tests for value screening models."""

from value_investor.models.graham import GrahamDefensiveModel
from value_investor.scoring import evaluate_universe, summarize_by_ticker
from value_investor.signals import Signal, assign_signal


def test_graham_defensive_passes_cheap_dividend_payer():
    model = GrahamDefensiveModel()
    row = {
        "trailing_pe": 10.0,
        "price_to_book": 1.2,
        "current_ratio": 2.5,
        "dividend_yield": 0.04,
    }
    result = model.evaluate(row)
    assert result.passed is True
    assert result.score >= 0.9


def test_assign_signal_strong_buy():
    signal = assign_signal(
        models_passed=3,
        model_count=4,
        mean_model_score=0.75,
        composite_score=0.8,
        has_errors=False,
    )
    assert signal == Signal.STRONG_BUY


def test_evaluate_universe_produces_summary():
    universe = [
        {
            "ticker": "AAA.L",
            "name": "Alpha",
            "trailing_pe": 8,
            "price_to_book": 1.0,
            "dividend_yield": 0.05,
            "current_ratio": 2.5,
            "debt_to_equity": 40,
            "return_on_equity": 0.15,
            "profit_margins": 0.1,
            "earnings_growth": 0.05,
            "free_cashflow": 100,
            "market_cap": 1000,
            "enterprise_value": 1100,
            "ebitda": 200,
        },
        {
            "ticker": "BBB.L",
            "name": "Beta",
            "trailing_pe": 30,
            "price_to_book": 5.0,
            "dividend_yield": 0.01,
            "current_ratio": 1.0,
            "debt_to_equity": 150,
            "return_on_equity": 0.05,
            "profit_margins": 0.02,
            "earnings_growth": -0.1,
            "free_cashflow": -50,
            "market_cap": 2000,
            "enterprise_value": 2500,
            "ebitda": 100,
        },
    ]
    import pandas as pd

    df = pd.DataFrame(universe)
    results = evaluate_universe(df)
    summary = summarize_by_ticker(results)

    assert len(summary) == 2
    assert "models_passed" in summary.columns
    assert results["model_id"].nunique() >= 3
