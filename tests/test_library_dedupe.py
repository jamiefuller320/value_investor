"""Tests for cross-market ticker dedupe."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from value_investor.library_dedupe import (
    canonical_library_ticker,
    existing_library_research_tickers,
    select_deduped_research_targets,
    summarize_ticker_overlaps,
)


def test_canonical_library_ticker():
    assert canonical_library_ticker(" aapl ") == "AAPL"
    assert canonical_library_ticker("ADS.DE") == "ADS.DE"


def test_summarize_ticker_overlaps_counts_pairs():
    payload = summarize_ticker_overlaps(
        {
            "sp500": ["AAPL", "MSFT", "XOM"],
            "nasdaq100": ["AAPL", "MSFT", "MDB"],
            "asx200": ["BHP.AX"],
        }
    )
    assert payload["tickers_in_multiple_markets"] == 2
    pairs = {(tuple(p["markets"]), p["overlap_count"]) for p in payload["pairs"]}
    assert (("nasdaq100", "sp500"), 2) in pairs


def test_select_deduped_research_targets_prefers_earlier_market():
    queues = {
        "sp500": [
            SimpleNamespace(ticker="AAPL", name="Apple", signal="buy", conviction_score=0.9),
            SimpleNamespace(ticker="XOM", name="Exxon", signal="buy", conviction_score=0.8),
        ],
        "nasdaq100": [
            SimpleNamespace(ticker="AAPL", name="Apple", signal="strong_buy", conviction_score=0.95),
            SimpleNamespace(ticker="MDB", name="Mongo", signal="buy", conviction_score=0.7),
        ],
    }
    selected, skipped = select_deduped_research_targets(
        research_markets=["sp500", "nasdaq100"],
        per_market_queues=queues,
        research_cap=3,
        already_researched=set(),
    )
    tickers = [(m, r.ticker) for m, r in selected]
    assert ("sp500", "AAPL") in tickers
    assert ("nasdaq100", "AAPL") not in tickers
    assert ("nasdaq100", "MDB") in tickers
    assert any(s["ticker"] == "AAPL" and s["market"] == "nasdaq100" for s in skipped)


def test_select_skips_already_researched(tmp_path: Path):
    research = tmp_path / "markets" / "sp500" / "screen" / "research" / "AAPL"
    research.mkdir(parents=True)
    (research / "research.md").write_text("# memo\n", encoding="utf-8")
    assert "AAPL" in existing_library_research_tickers(tmp_path)

    queues = {
        "nasdaq100": [
            SimpleNamespace(ticker="AAPL", name="Apple", signal="buy", conviction_score=0.9),
            SimpleNamespace(ticker="MDB", name="Mongo", signal="buy", conviction_score=0.7),
        ],
    }
    selected, skipped = select_deduped_research_targets(
        research_markets=["nasdaq100"],
        per_market_queues=queues,
        research_cap=5,
        already_researched=existing_library_research_tickers(tmp_path),
    )
    assert [r.ticker for _, r in selected] == ["MDB"]
    assert skipped[0]["ticker"] == "AAPL"


def test_grow_library_reuses_fetch_for_overlap(tmp_path: Path, monkeypatch):
    import pandas as pd

    from value_investor import data_library as dl

    def fake_constituents(market_id: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"ticker": "AAPL", "name": "Apple", "sector": "Tech", "epic": "AAPL", "index": market_id, "market": market_id},
                {"ticker": f"ONLY{market_id[:2].upper()}", "name": "Unique", "sector": "Tech", "epic": "X", "index": market_id, "market": market_id},
            ]
        )

    monkeypatch.setitem(dl.CONSTITUENT_FETCHERS, "sp500", lambda: fake_constituents("sp500"))
    monkeypatch.setitem(dl.CONSTITUENT_FETCHERS, "nasdaq100", lambda: fake_constituents("nasdaq100"))

    calls: list[str] = []

    def fake_fetch(ticker, name=None, sector=None):
        calls.append(ticker)
        return {"ticker": ticker, "name": name, "trailing_pe": 10.0}

    root = tmp_path / "library"
    dl.grow_library(
        root,
        markets=["sp500", "nasdaq100"],
        max_tickers_per_run=10,
        stale_days=7,
        refresh_constituents_first=True,
        retention_days=0,
        fetch_fn=fake_fetch,
    )
    # AAPL fetched once; uniques once each.
    assert calls.count("AAPL") == 1
    assert len(calls) == 3
