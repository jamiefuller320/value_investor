"""Tests for the investment-trust screening track."""

from __future__ import annotations

import pandas as pd

from value_investor.models.trusts import (
    ALL_TRUST_MODELS,
    DeepDiscountTrustModel,
    TrustPremiumRiskModel,
)
from value_investor.scoring import evaluate_universe, summarize_by_ticker
from value_investor.signals import Signal
from value_investor.trust_metrics import (
    add_trust_derived_metrics,
    discount_from_price_to_book,
    normalize_yield,
    resolve_trust_dividend_yield,
    score_trust_data_quality,
)
from value_investor.trust_signals import assign_trust_signal, build_trust_signals
from value_investor.trust_summary import build_trust_reports, trust_key_metrics
from value_investor.emailer import format_html_report, format_text_report


def test_normalize_yield_handles_percent_and_fraction():
    assert normalize_yield(10.47) == 0.1047
    assert normalize_yield(0.04) == 0.04
    assert normalize_yield(None) is None


def test_resolve_trust_dividend_yield_from_rate_and_mcap():
    # UKW-style: rate in £, price in pence — use mcap/shares for GBP price.
    yld = resolve_trust_dividend_yield(
        dividend_yield=None,
        dividend_rate=0.104,
        last_price=103.6,
        book_value=1.335,
        market_cap=2_236_327_424,
        shares_outstanding=2_158_617_000,
    )
    assert yld is not None
    assert 0.08 < yld < 0.12

    # Prefer explicit percent yield when present.
    assert resolve_trust_dividend_yield(
        dividend_yield=10.47,
        dividend_rate=0.076,
        last_price=73.2,
        book_value=1.04,
        market_cap=1e9,
        shares_outstanding=1e9,
    ) == 0.1047


def test_discount_from_price_to_book():
    assert discount_from_price_to_book(None) is None
    assert abs(discount_from_price_to_book(0.70) - 0.30) < 1e-9
    assert abs(discount_from_price_to_book(1.10) - (-0.10)) < 1e-9


def test_trust_quality_scores_discount_fields():
    row = {
        "market_cap": 1e9,
        "last_price": 100,
        "price_to_book": 0.8,
        "book_value": 1.2,
        "discount_to_nav": 0.2,
        "dividend_yield": 0.06,
        "trailing_pe": 8,
        "average_volume": 100000,
        "fifty_two_week_low": 80,
        "fifty_two_week_high": 120,
        "shares_outstanding": 1e8,
        "errors": [],
    }
    score, present, total = score_trust_data_quality(row)
    assert present == total == 11
    assert score == 1.0


def test_deep_discount_and_premium_risk_models():
    universe = pd.DataFrame(
        [
            {"ticker": "CHEAP.L", "discount_to_nav": 0.25, "dividend_yield": 0.08, "trailing_pe": 6},
            {"ticker": "A.L", "discount_to_nav": 0.12, "dividend_yield": 0.04, "trailing_pe": 10},
            {"ticker": "B.L", "discount_to_nav": 0.08, "dividend_yield": 0.035, "trailing_pe": 11},
            {"ticker": "MID.L", "discount_to_nav": 0.05, "dividend_yield": 0.03, "trailing_pe": 12},
            {"ticker": "RICH.L", "discount_to_nav": -0.15, "dividend_yield": 0.02, "trailing_pe": 20},
        ]
    )
    discount_model = DeepDiscountTrustModel().fit(universe)
    cheap = discount_model.evaluate(universe.iloc[0].to_dict())
    rich = discount_model.evaluate(universe.iloc[4].to_dict())
    assert cheap.passed
    assert not rich.passed

    risk = TrustPremiumRiskModel()
    assert risk.evaluate(universe.iloc[0].to_dict()).passed
    assert not risk.evaluate(universe.iloc[4].to_dict()).passed


def test_build_trust_signals_and_reports():
    universe = pd.DataFrame(
        [
            {
                "ticker": "CHEAP.L",
                "name": "Cheap Trust",
                "sector": "Investment Trusts",
                "market_cap": 1e9,
                "last_price": 90,
                "price_to_book": 0.75,
                "book_value": 1.2,
                "dividend_yield": 0.07,
                "trailing_pe": 7,
                "average_volume": 200000,
                "fifty_two_week_low": 70,
                "fifty_two_week_high": 110,
                "shares_outstanding": 1e8,
                "errors": [],
            },
            {
                "ticker": "RICH.L",
                "name": "Rich Trust",
                "sector": "Investment Trusts",
                "market_cap": 2e9,
                "last_price": 120,
                "price_to_book": 1.20,
                "book_value": 1.0,
                "dividend_yield": 0.01,
                "trailing_pe": 25,
                "average_volume": 50000,
                "fifty_two_week_low": 100,
                "fifty_two_week_high": 130,
                "shares_outstanding": 1e8,
                "errors": [],
            },
        ]
    )
    universe = add_trust_derived_metrics(universe)
    from value_investor.trust_metrics import add_trust_data_quality_scores

    universe = add_trust_data_quality_scores(universe)
    models = [model.__class__() for model in ALL_TRUST_MODELS]
    results = evaluate_universe(universe, models=models)
    summary = summarize_by_ticker(results)
    signals = build_trust_signals(universe, results, summary)
    assert len(signals) == 2
    cheap = signals.loc[signals["ticker"] == "CHEAP.L"].iloc[0]
    assert cheap["signal"] in {"strong_buy", "buy", "hold"}
    assert cheap["discount_to_nav"] > 0

    reports = build_trust_reports(signals, results)
    assert len(reports) == 2
    metrics = trust_key_metrics(cheap)
    assert "Discount" in metrics or "P/B" in metrics

    text = format_text_report(
        run_at="2026-07-14",
        reports=[],
        trust_reports=reports,
        excluded_investment_vehicles=2,
    )
    html = format_html_report(
        run_at="2026-07-14",
        reports=[],
        trust_reports=reports,
        excluded_investment_vehicles=2,
    )
    assert "INVESTMENT TRUST TRACK" in text
    assert "Investment trust track" in html
    assert "Cheap Trust" in text


def test_assign_trust_signal_thresholds():
    strong = assign_trust_signal(
        models_passed=3,
        model_count=5,
        mean_model_score=0.7,
        composite_score=0.7,
        families_passed=2,
        data_quality_score=0.8,
        risk_family_passed=True,
        risk_mean_score=0.7,
        has_errors=False,
        discount_to_nav=0.15,
    )
    assert strong == Signal.STRONG_BUY

    premium_strong = assign_trust_signal(
        models_passed=3,
        model_count=5,
        mean_model_score=0.7,
        composite_score=0.7,
        families_passed=2,
        data_quality_score=0.8,
        risk_family_passed=True,
        risk_mean_score=0.7,
        has_errors=False,
        discount_to_nav=-0.05,
    )
    assert premium_strong == Signal.BUY
