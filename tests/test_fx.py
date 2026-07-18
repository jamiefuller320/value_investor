"""Tests for paper FX policy and reporting-currency conversion."""

from __future__ import annotations

from value_investor.fx import (
    PaperFxPolicy,
    convert_prices_to_reporting,
    currency_for_market,
    currency_for_ticker,
)


def test_currency_inference_from_ticker_and_market():
    assert currency_for_ticker("SHEL.L") == "GBP"
    assert currency_for_ticker("BHP.AX") == "AUD"
    assert currency_for_ticker("SAP.DE") == "EUR"
    assert currency_for_ticker("AEM.TO") == "CAD"
    assert currency_for_ticker("AAPL") == "USD"
    assert currency_for_market("asx200") == "AUD"
    assert currency_for_market("euro_stoxx50") == "EUR"
    assert currency_for_market("sp500") == "USD"
    assert currency_for_market("tsx60") == "CAD"
    assert currency_for_market("ftse_smallcap") == "GBP"
    assert currency_for_ticker("AAPL", market="ftse350") == "GBP"


def test_paper_fx_policy_defaults_unhedged():
    policy = PaperFxPolicy()
    assert policy.reporting_currency == "GBP"
    assert policy.hedge_assumption == "none"
    data = policy.to_dict()
    assert data["hedge_assumption"] == "none"
    assert "GBP" in data["supported_currencies"]


def test_convert_prices_to_reporting_with_provided_rates():
    prices = {"AAA.L": 10.0, "BBB": 20.0, "CCC.AX": 5.0}
    currencies = {"AAA.L": "GBP", "BBB": "USD", "CCC.AX": "AUD"}
    rates = {"GBP": 1.0, "USD": 0.8, "AUD": 0.5}
    converted, meta = convert_prices_to_reporting(
        prices,
        price_currencies=currencies,
        reporting_currency="GBP",
        rates=rates,
    )
    assert converted["AAA.L"] == 10.0
    assert converted["BBB"] == 16.0
    assert converted["CCC.AX"] == 2.5
    assert meta["conversion_issues"] == []
    assert meta["hedge_assumption"] == "none"


def test_convert_prices_fail_open_when_rate_missing():
    prices = {"XYZ": 100.0}
    converted, meta = convert_prices_to_reporting(
        prices,
        price_currencies={"XYZ": "JPY"},
        reporting_currency="GBP",
        rates={"GBP": 1.0},
    )
    assert converted["XYZ"] == 100.0
    assert meta["conversion_issues"]
