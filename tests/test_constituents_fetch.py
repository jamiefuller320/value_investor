"""Tests for LSE → Yahoo ticker mapping, index fetches, and fetch retries."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from value_investor.constituents import (
    fetch_ftse100_constituents,
    fetch_ftse250_constituents,
    fetch_ftse350_constituents,
    fetch_universe_constituents,
    normalize_tickers,
    to_lse_ticker,
)
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


def test_fetch_ftse250_parses_ticker_column():
    html = """
    <table>
      <tr><th>Company</th><th>Ticker</th><th>FTSE Industry Classification Benchmark sector</th></tr>
      <tr><td>EasyJet</td><td>EZJ</td><td>Travel and Leisure</td></tr>
      <tr><td>ITV</td><td>ITV</td><td>Media</td></tr>
    </table>
    """
    with patch("value_investor.constituents._fetch_wikipedia_html", return_value=html):
        fetch_ftse250_constituents.cache_clear()
        df = fetch_ftse250_constituents()
    assert set(df["ticker"]) == {"EZJ.L", "ITV.L"}
    assert set(df["index"]) == {"FTSE 250"}


def test_fetch_ftse350_dedupes_preferring_ftse100():
    ftse100 = pd.DataFrame(
        [
            {"ticker": "BKG.L", "name": "Berkeley 100", "sector": "Home", "epic": "BKG", "index": "FTSE 100"},
            {"ticker": "SHEL.L", "name": "Shell", "sector": "Energy", "epic": "SHEL", "index": "FTSE 100"},
        ]
    )
    ftse250 = pd.DataFrame(
        [
            {"ticker": "BKG.L", "name": "Berkeley 250", "sector": "Home", "epic": "BKG", "index": "FTSE 250"},
            {"ticker": "EZJ.L", "name": "EasyJet", "sector": "Travel", "epic": "EZJ", "index": "FTSE 250"},
        ]
    )
    with (
        patch("value_investor.constituents.fetch_ftse100_constituents", return_value=ftse100),
        patch("value_investor.constituents.fetch_ftse250_constituents", return_value=ftse250),
    ):
        fetch_ftse350_constituents.cache_clear()
        combined = fetch_ftse350_constituents()
    assert len(combined) == 3
    berkeley = combined.loc[combined["ticker"] == "BKG.L"].iloc[0]
    assert berkeley["name"] == "Berkeley 100"
    assert berkeley["index"] == "FTSE 100"
    assert "EZJ.L" in set(combined["ticker"])


def test_fetch_universe_constituents_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown universe"):
        fetch_universe_constituents("nasdaq")


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
