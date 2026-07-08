"""Tests for sector-relative scoring."""

import pandas as pd

from value_investor.sector_scoring import add_sector_scores, sector_composite_score


def test_sector_composite_prefers_cheap_name_within_sector():
    universe = pd.DataFrame([
        {
            "ticker": "AAA.L",
            "sector": "Financials",
            "trailing_pe": 8.0,
            "price_to_book": 0.8,
            "dividend_yield": 0.05,
            "free_cashflow": 100,
            "market_cap": 1000,
            "enterprise_value": 900,
            "ebitda": 150,
            "return_on_equity": 0.14,
        },
        {
            "ticker": "BBB.L",
            "sector": "Financials",
            "trailing_pe": 16.0,
            "price_to_book": 1.8,
            "dividend_yield": 0.02,
            "free_cashflow": 50,
            "market_cap": 1000,
            "enterprise_value": 1100,
            "ebitda": 100,
            "return_on_equity": 0.08,
        },
        {
            "ticker": "CCC.L",
            "sector": "Financials",
            "trailing_pe": 20.0,
            "price_to_book": 2.5,
            "dividend_yield": 0.01,
            "free_cashflow": -20,
            "market_cap": 1000,
            "enterprise_value": 1200,
            "ebitda": 80,
            "return_on_equity": 0.05,
        },
    ])

    cheap_score = sector_composite_score(universe, universe.iloc[0].to_dict())
    expensive_score = sector_composite_score(universe, universe.iloc[2].to_dict())

    assert cheap_score is not None
    assert expensive_score is not None
    assert cheap_score > expensive_score

    scored = add_sector_scores(universe)
    assert "sector_composite_score" in scored.columns
