"""Tests for Nordic/Irish fetch resilience."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from value_investor.fetch import fetch_company_metrics
from value_investor.library_screen import metrics_row_is_usable


def test_metrics_row_is_usable_requires_valuation_field():
    assert metrics_row_is_usable({"last_price": 10.0}) is False
    assert metrics_row_is_usable({"market_cap": 1e9}) is True


def test_fetch_clears_soft_errors_when_chart_recovers():
    """Empty primary payload recovers via fallbacks; soft timezone errors clear.

    Mock fallbacks — do not hit live Yahoo/Stooq (CI flake on HTTP 429).
    """
    stock = MagicMock()
    stock.balance_sheet = None
    stock.income_stmt = None
    stock.cashflow = None

    def fake_fallbacks(ticker, payload):
        updated = dict(payload)
        updated["last_price"] = 512.0
        updated["market_cap"] = 1.2e11
        return updated, {"last_price": "yahoo_chart"}, ["yahoo_chart: soft miss"]

    with (
        patch(
            "value_investor.fetch._load_ticker_payload",
            return_value=(stock, {}, None),
        ),
        patch(
            "value_investor.fetch.apply_fallback_providers",
            side_effect=fake_fallbacks,
        ),
    ):
        metrics = fetch_company_metrics("ABB.ST", market="omxs30")

    assert metrics.last_price == 512.0
    assert not any("exchangeTimezoneName" in str(err) for err in metrics.errors)
    assert not any("no market data returned" in str(err).lower() for err in metrics.errors)
