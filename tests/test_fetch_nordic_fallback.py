"""Tests for Nordic/Irish fetch resilience."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from value_investor.fetch import fetch_company_metrics
from value_investor.library_screen import metrics_row_is_usable


def test_metrics_row_is_usable_requires_valuation_field():
    assert metrics_row_is_usable({"last_price": 10.0}) is False
    assert metrics_row_is_usable({"market_cap": 1e9}) is True


def _chart_only(url: str, **_kwargs) -> str:
    if "/v8/finance/chart/" in url:
        return json.dumps(
            {"chart": {"result": [{"meta": {"regularMarketPrice": 251.4, "longName": "ABB Ltd"}}]}}
        )
    raise OSError("offline in tests")


def test_fetch_clears_soft_errors_when_chart_recovers():
    stock = MagicMock()
    stock.balance_sheet = None
    stock.income_stmt = None
    stock.cashflow = None
    with (
        patch(
            "value_investor.fetch._load_ticker_payload",
            return_value=(stock, {}, None),
        ),
        patch("value_investor.providers.http_get_text", side_effect=_chart_only),
    ):
        metrics = fetch_company_metrics("ABB.ST", market="omxs30")
    assert metrics.last_price == 251.4
    assert metrics.data_sources.get("last_price") == "yahoo_chart"
    assert not any("exchangeTimezoneName" in str(err) for err in metrics.errors)
