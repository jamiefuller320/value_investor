"""Tests for portfolio diversification advice."""

from value_investor.portfolio_diversity import (
    CandidatePick,
    PortfolioHolding,
    advise_diversification,
    candidates_from_reports,
    holdings_from_actions,
    sector_weights,
)


def test_sector_weights_equal_when_missing():
    holdings = [
        PortfolioHolding(ticker="AAA.L", sector="Energy"),
        PortfolioHolding(ticker="BBB.L", sector="Energy"),
        PortfolioHolding(ticker="CCC.L", sector="Financials"),
    ]
    weights = sector_weights(holdings)
    assert abs(weights["Energy"] - 2 / 3) < 1e-9
    assert abs(weights["Financials"] - 1 / 3) < 1e-9


def test_advise_prefers_underweight_sector():
    holdings = [
        PortfolioHolding(ticker="SHEL.L", sector="Energy", weight=0.5),
        PortfolioHolding(ticker="BP.L", sector="Energy", weight=0.5),
    ]
    candidates = [
        CandidatePick(
            ticker="HSBA.L",
            name="HSBC",
            sector="Financials",
            signal="buy",
            conviction_score=0.7,
        ),
        CandidatePick(
            ticker="BP.L",
            name="BP",
            sector="Energy",
            signal="strong_buy",
            conviction_score=0.95,
        ),
        CandidatePick(
            ticker="NG.L",
            name="National Grid",
            sector="Energy",
            signal="strong_buy",
            conviction_score=0.9,
        ),
    ]
    advice = advise_diversification(holdings, candidates, top_n=3)
    assert advice.holdings_count == 2
    assert any("Energy" in warning for warning in advice.concentration_warnings)
    assert advice.ranked_candidates
    # Already held BP excluded; high-conviction Energy add should lose to Financials.
    assert advice.ranked_candidates[0].ticker == "HSBA.L"
    assert advice.ranked_candidates[0].diversity_score > advice.ranked_candidates[-1].diversity_score


def test_holdings_from_actions_collapses_legs():
    actions = [
        {
            "ticker": "RIO.L",
            "name": "Rio",
            "sector": "Basic Materials",
            "status": "open",
            "leg": "core",
            "allocation_pct": 0.6,
        },
        {
            "ticker": "RIO.L",
            "name": "Rio",
            "sector": "Basic Materials",
            "status": "open",
            "leg": "tactical",
            "allocation_pct": 0.4,
        },
        {
            "ticker": "SHEL.L",
            "status": "closed",
            "allocation_pct": 1.0,
        },
    ]
    holdings = holdings_from_actions(actions)
    assert len(holdings) == 1
    assert holdings[0].ticker == "RIO.L"
    assert abs(holdings[0].weight - 1.0) < 1e-9


def test_candidates_from_reports_filters_signals():
    reports = [
        {"ticker": "AAA.L", "name": "A", "sector": "X", "signal": "strong_buy", "conviction_score": 0.8},
        {"ticker": "BBB.L", "name": "B", "sector": "Y", "signal": "hold", "conviction_score": 0.9},
        {"ticker": "CCC.L", "name": "C", "sector": "Z", "signal": "buy", "conviction_score": 0.6},
    ]
    candidates = candidates_from_reports(reports)
    assert [c.ticker for c in candidates] == ["AAA.L", "CCC.L"]


def test_empty_book_summary():
    advice = advise_diversification([], [])
    assert advice.holdings_count == 0
    assert "No actioned holdings" in advice.summary
