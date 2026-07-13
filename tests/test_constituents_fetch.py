"""Tests for LSE → Yahoo ticker mapping and fetch retries."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from value_investor.constituents import normalize_tickers, to_lse_ticker
from value_investor import fetch as fetch_mod


@pytest.mark.parametrize(
    ("epic", "expected"),
    [
        ("BARC", "BARC.L"),
        ("barc.l", "BARC.L"),
        ("BT.A", "BT-A.L"),
        ("BT.A.L", "BT-A.L"),
        ("BT-A", "BT-A.L"),
        ("BTA", "BT-A.L"),
        ("III", "III.L"),
    ],
)
def test_to_lse_ticker_maps_share_classes(epic: str, expected: str):
    assert to_lse_ticker(epic) == expected


def test_normalize_tickers_applies_mapping():
    assert normalize_tickers(["BT.A", " SHEL "]) == ["BT-A.L", "SHEL.L"]


def test_fetch_company_metrics_retries_transient_timeout(monkeypatch):
    monkeypatch.setattr(fetch_mod, "FETCH_RETRY_DELAY_SECONDS", 0)

    calls = {"n": 0}

    class FlakyTicker:
        def __init__(self, symbol: str):
            self.symbol = symbol

        @property
        def info(self):
            calls["n"] += 1
            if calls["n"] < 3:
                raise TimeoutError("Operation timed out after 30002 milliseconds")
            return {
                "longName": "Aberdeen Group",
                "sector": "Financial Services",
                "marketCap": 1_000_000,
                "trailingPE": 10.0,
            }

        @property
        def fast_info(self):
            return SimpleNamespace(market_cap=1_000_000)

        @property
        def balance_sheet(self):
            return None

        @property
        def income_stmt(self):
            return None

        @property
        def cashflow(self):
            return None

    with patch.object(fetch_mod.yf, "Ticker", side_effect=FlakyTicker):
        metrics = fetch_mod.fetch_company_metrics("ABDN.L")

    assert calls["n"] == 3
    assert metrics.ticker == "ABDN.L"
    assert metrics.market_cap == 1_000_000
    assert metrics.errors == []


def test_fetch_company_metrics_resolves_bt_a_symbol():
    seen: list[str] = []

    class DummyTicker:
        def __init__(self, symbol: str):
            seen.append(symbol)

        @property
        def info(self):
            return {"longName": "BT Group", "marketCap": 2_000_000}

        @property
        def fast_info(self):
            return SimpleNamespace(market_cap=2_000_000)

        @property
        def balance_sheet(self):
            return None

        @property
        def income_stmt(self):
            return None

        @property
        def cashflow(self):
            return None

    with patch.object(fetch_mod.yf, "Ticker", side_effect=DummyTicker):
        metrics = fetch_mod.fetch_company_metrics("BT.A")

    assert seen == ["BT-A.L"]
    assert metrics.ticker == "BT-A.L"
    assert metrics.name == "BT Group"
