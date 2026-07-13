"""Tests for curated alternate-source fallback providers."""

from __future__ import annotations

import json
from unittest.mock import patch

from value_investor.providers import (
    ProviderResult,
    StooqPriceProvider,
    YahooChartProvider,
    YahooQuoteSummaryProvider,
    apply_fallback_providers,
    merge_provider_result,
    to_stooq_symbol,
)
from value_investor.fetch import CompanyMetrics, _apply_metric_fallbacks


def test_to_stooq_symbol_maps_lse_class_shares():
    assert to_stooq_symbol("BT-A.L") == "bt_a.uk"
    assert to_stooq_symbol("SHEL.L") == "shel.uk"


def test_merge_provider_result_only_fills_missing():
    metrics = {"market_cap": 10.0, "trailing_pe": None}
    source_map: dict[str, str] = {}
    result = ProviderResult(
        source="test",
        metrics={"market_cap": 99.0, "trailing_pe": 12.5, "last_price": 1.5},
    )
    filled = merge_provider_result(metrics, result, source_map=source_map)
    assert metrics["market_cap"] == 10.0
    assert metrics["trailing_pe"] == 12.5
    assert metrics["last_price"] == 1.5
    assert set(filled) == {"trailing_pe", "last_price"}
    assert source_map["trailing_pe"] == "test"


def test_yahoo_quote_summary_provider_parses_modules():
    payload = {
        "quoteSummary": {
            "result": [
                {
                    "price": {
                        "longName": "Example PLC",
                        "regularMarketPrice": {"raw": 2.5},
                        "marketCap": {"raw": 1_000_000},
                    },
                    "summaryDetail": {"trailingPE": {"raw": 11.0}, "dividendYield": {"raw": 0.04}},
                    "defaultKeyStatistics": {"priceToBook": {"raw": 1.2}, "sharesOutstanding": {"raw": 400_000}},
                    "financialData": {"returnOnEquity": {"raw": 0.15}, "currentRatio": {"raw": 1.4}},
                }
            ]
        }
    }
    with patch(
        "value_investor.providers.http_get_text",
        return_value=json.dumps(payload),
    ):
        result = YahooQuoteSummaryProvider().fetch("EX.L")

    assert result.ok
    assert result.metrics["name"] == "Example PLC"
    assert result.metrics["market_cap"] == 1_000_000
    assert result.metrics["trailing_pe"] == 11.0
    assert result.metrics["shares_outstanding"] == 400_000


def test_stooq_provider_reads_latest_close():
    csv_text = "Date,Open,High,Low,Close,Volume\n2026-07-10,1,1,1,1.1,10\n2026-07-11,1,1,1,1.25,12\n"
    with patch("value_investor.providers.http_get_text", return_value=csv_text):
        result = StooqPriceProvider().fetch("SHEL.L")
    assert result.metrics["last_price"] == 1.25


def test_apply_fallback_providers_fills_gaps_and_derives_market_cap():
    class FakeQuote:
        name = "fake_quote"

        def fetch(self, ticker: str) -> ProviderResult:
            return ProviderResult(
                source=self.name,
                metrics={"last_price": 2.0, "shares_outstanding": 500_000},
            )

    metrics = {"market_cap": None, "trailing_pe": None, "errors": ["no market data returned"]}
    updated, source_map, errors = apply_fallback_providers(
        "AAA.L",
        metrics,
        providers=(FakeQuote(),),
    )
    assert updated["last_price"] == 2.0
    assert updated["shares_outstanding"] == 500_000
    assert updated["market_cap"] == 1_000_000
    assert source_map["last_price"] == "fake_quote"
    assert not errors


def test_apply_metric_fallbacks_clears_soft_primary_error():
    metrics = CompanyMetrics(ticker="AAA.L", errors=["no market data returned"])

    class FakeChart:
        name = "fake_chart"

        def fetch(self, ticker: str) -> ProviderResult:
            return ProviderResult(source=self.name, metrics={"last_price": 3.0, "market_cap": 9.0})

    with patch(
        "value_investor.fetch.apply_fallback_providers",
        side_effect=lambda ticker, payload, **kwargs: (
            {**payload, "last_price": 3.0, "market_cap": 9.0},
            {"last_price": "fake_chart", "market_cap": "fake_chart"},
            [],
        ),
    ):
        _apply_metric_fallbacks(metrics)

    assert metrics.last_price == 3.0
    assert metrics.market_cap == 9.0
    assert metrics.data_sources["market_cap"] == "fake_chart"
    assert metrics.errors == []


def test_yahoo_chart_provider_reads_meta_price():
    payload = {"chart": {"result": [{"meta": {"regularMarketPrice": 4.2, "shortName": "Chart Co"}}]}}
    with patch("value_investor.providers.http_get_text", return_value=json.dumps(payload)):
        result = YahooChartProvider().fetch("CCC.L")
    assert result.metrics["last_price"] == 4.2
    assert result.metrics["name"] == "Chart Co"
