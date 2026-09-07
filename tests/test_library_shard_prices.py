"""Library shard paper-auto must price US/ASX tickers, not rewrite them to .L."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from value_investor.paper_automation import infer_paper_market_id, refresh_candidate_marks
from value_investor.technical_analysis import yahoo_symbols_for_tickers


def test_yahoo_symbols_use_market_suffixes_not_lse():
    mapped = yahoo_symbols_for_tickers(["AAPL", "MSFT"], market="sp500")
    assert mapped == {"AAPL": "AAPL", "MSFT": "MSFT"}
    mapped_asx = yahoo_symbols_for_tickers(["BHP", "BHP.AX"], market="asx200")
    assert mapped_asx == {"BHP": "BHP.AX", "BHP.AX": "BHP.AX"}
    mapped_ftse = yahoo_symbols_for_tickers(["SHEL"])
    assert mapped_ftse == {"SHEL": "SHEL.L"}


def test_refresh_candidate_marks_keeps_last_price_when_yahoo_empty():
    rows = [
        {"ticker": "AAPL", "signal": "buy", "last_price": 180.0},
        {"ticker": "BHP.AX", "signal": "buy", "last_price": 42.5},
    ]
    with patch(
        "value_investor.paper_automation.fetch_price_history",
        return_value={},
    ) as mocked:
        marked = refresh_candidate_marks(rows, market="sp500")
    mocked.assert_called_once()
    assert mocked.call_args.kwargs.get("market") == "sp500"
    by_ticker = {row["ticker"]: row for row in marked}
    assert by_ticker["AAPL"]["price"] == 180.0
    assert by_ticker["BHP.AX"]["last"] == 42.5


def test_refresh_candidate_marks_skips_yahoo_when_listed_prices_complete():
    rows = [{"ticker": "AAPL", "signal": "buy", "last_price": 180.0}]
    with patch(
        "value_investor.paper_automation.fetch_price_history",
        return_value={},
    ) as mocked:
        marked = refresh_candidate_marks(rows, market="sp500", prefer_listed_prices=True)
    mocked.assert_not_called()
    assert marked[0]["price"] == 180.0


def test_infer_paper_market_id_from_shard_meta(tmp_path: Path):
    shard = tmp_path / "markets" / "sp500"
    track = shard / "buy_tier_level"
    track.mkdir(parents=True)
    (shard / "shard_meta.json").write_text(
        '{"market_id": "sp500"}',
        encoding="utf-8",
    )
    assert infer_paper_market_id(track) == "sp500"
