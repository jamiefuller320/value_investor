"""Tests for value screening models."""

import pandas as pd

from value_investor.models import ALL_MODELS
from value_investor.models.graham import GrahamDefensiveModel
from value_investor.models.net_net import NetNetModel
from value_investor.models.piotroski import PiotroskiFScoreModel
from value_investor.scoring import evaluate_universe, summarize_by_ticker
from value_investor.signals import Signal, assign_signal


def test_all_models_registered():
    assert len(ALL_MODELS) >= 18
    ids = {m.id for m in ALL_MODELS}
    assert len(ids) == len(ALL_MODELS)
    assert "magic_formula" in ids
    assert "piotroski_f" in ids
    assert "graham_net_net" in ids


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


def test_net_net_passes_below_liquidation_value():
    model = NetNetModel()
    result = model.evaluate({"ncav": 1200, "market_cap": 1000})
    assert result.passed is True
    assert result.score >= 1.0


def test_piotroski_scores_financial_strength():
    model = PiotroskiFScoreModel()
    row = {
        "net_income": 100,
        "operating_cashflow": 150,
        "return_on_assets": 0.1,
        "return_on_assets_prev": 0.08,
        "leverage": 0.3,
        "leverage_prev": 0.35,
        "current_ratio_bs": 2.0,
        "current_ratio_bs_prev": 1.8,
        "shares_outstanding": 100,
        "shares_outstanding_prev": 102,
        "gross_margin": 0.4,
        "gross_margin_prev": 0.38,
        "asset_turnover": 1.2,
        "asset_turnover_prev": 1.1,
    }
    result = model.evaluate(row)
    assert result.passed is True
    assert result.score >= 0.75


def test_assign_signal_strong_buy_scales_with_model_count():
    signal = assign_signal(
        models_passed=6,
        model_count=18,
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
            "ebit": 180,
            "total_assets": 2000,
            "total_current_liabilities": 500,
            "total_revenue": 1500,
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
            "ebit": 80,
            "total_assets": 3000,
            "total_current_liabilities": 800,
            "total_revenue": 1200,
        },
    ]

    df = pd.DataFrame(universe)
    results = evaluate_universe(df)
    summary = summarize_by_ticker(results)

    assert len(summary) == 2
    assert "models_passed" in summary.columns
    assert results["model_id"].nunique() == len(ALL_MODELS)
