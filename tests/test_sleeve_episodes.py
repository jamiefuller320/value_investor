"""Tests for dual-path sleeve episodes (observe-only)."""

from pathlib import Path

from value_investor.paper_fund import PaperFund, PaperFundConfig, Position
from value_investor.sleeve_episodes import (
    CAPITAL_NEVER_FUNDED,
    CAPITAL_OFF_BOOK,
    CAPITAL_ON_BOOK,
    EPISODES_FILENAME,
    SleeveEpisodeConfig,
    run_sleeve_episodes_pass,
)


def _fund_with_holding(ticker: str = "AAA.L") -> PaperFund:
    fund = PaperFund.create(
        PaperFundConfig(
            name="Sleeve test",
            mode="automated",
            initial_cash=0,
            trade_cost_pct=0.0,
            max_positions=3,
        )
    )
    fund.holdings[ticker] = Position(
        ticker=ticker, shares=1, avg_cost=100, name="Alpha", sector="Tech"
    )
    return fund


def test_opens_never_funded_and_on_book_episodes(tmp_path: Path):
    fund = _fund_with_holding("AAA.L")
    candidates = [
        {
            "ticker": "AAA.L",
            "name": "Alpha",
            "signal": "strong_buy",
            "conviction_score": 0.9,
            "price": 100,
        },
        {
            "ticker": "BBB.L",
            "name": "Beta",
            "signal": "buy",
            "conviction_score": 0.8,
            "price": 50,
        },
        {
            "ticker": "HOLD.L",
            "name": "Hold only",
            "signal": "hold",
            "conviction_score": 0.5,
            "price": 10,
        },
    ]
    review = run_sleeve_episodes_pass(
        output_dir=tmp_path,
        fund=fund,
        track_id="rules",
        candidates=candidates,
        prices_by_ticker={"AAA.L": 100, "BBB.L": 50, "HOLD.L": 10},
        as_of="2026-09-22T09:30:00+01:00",
        config=SleeveEpisodeConfig(exit_confirm_screens=2),
    )
    assert review["open_count"] == 2
    assert review["open_by_capital_status"][CAPITAL_ON_BOOK] == 1
    assert review["open_by_capital_status"][CAPITAL_NEVER_FUNDED] == 1
    import json

    store = json.loads((tmp_path / EPISODES_FILENAME).read_text(encoding="utf-8"))
    tickers = {ep["ticker"] for ep in store["open"]}
    assert tickers == {"AAA.L", "BBB.L"}
    by_ticker = {ep["ticker"]: ep for ep in store["open"]}
    assert by_ticker["AAA.L"]["capital_status"] == CAPITAL_ON_BOOK
    assert by_ticker["BBB.L"]["capital_status"] == CAPITAL_NEVER_FUNDED


def test_on_book_then_off_book_keeps_episode_open(tmp_path: Path):
    fund = _fund_with_holding("AAA.L")
    candidates = [
        {
            "ticker": "AAA.L",
            "name": "Alpha",
            "signal": "buy",
            "conviction_score": 0.9,
            "price": 110,
        }
    ]
    run_sleeve_episodes_pass(
        output_dir=tmp_path,
        fund=fund,
        track_id="rules",
        candidates=candidates,
        prices_by_ticker={"AAA.L": 110},
        as_of="2026-09-22T09:30:00+01:00",
    )
    # Sell capital while still buy-tier → off_book, episode stays open
    fund.holdings.clear()
    review = run_sleeve_episodes_pass(
        output_dir=tmp_path,
        fund=fund,
        track_id="rules",
        candidates=candidates,
        trades=[{"ticker": "AAA.L", "side": "sell"}],
        prices_by_ticker={"AAA.L": 105},
        as_of="2026-09-23T09:30:00+01:00",
    )
    assert review["open_count"] == 1
    import json

    store = json.loads((tmp_path / EPISODES_FILENAME).read_text(encoding="utf-8"))
    ep = store["open"][0]
    assert ep["capital_status"] == CAPITAL_OFF_BOOK
    assert ep["off_book_at"] is not None
    assert ep["status"] == "open"


def test_latest_exit_after_confirm_screens(tmp_path: Path):
    fund = PaperFund.create(
        PaperFundConfig(name="Empty", mode="automated", initial_cash=1000, trade_cost_pct=0)
    )
    buy = {
        "ticker": "AAA.L",
        "name": "Alpha",
        "signal": "buy",
        "conviction_score": 0.9,
        "price": 100,
    }
    hold = {
        "ticker": "AAA.L",
        "name": "Alpha",
        "signal": "hold",
        "conviction_score": 0.4,
        "price": 98,
    }
    run_sleeve_episodes_pass(
        output_dir=tmp_path,
        fund=fund,
        track_id="rules",
        candidates=[buy],
        prices_by_ticker={"AAA.L": 100},
        as_of="2026-09-20T09:30:00+01:00",
        config=SleeveEpisodeConfig(exit_confirm_screens=2),
    )
    run_sleeve_episodes_pass(
        output_dir=tmp_path,
        fund=fund,
        track_id="rules",
        candidates=[hold],
        prices_by_ticker={"AAA.L": 98},
        as_of="2026-09-21T09:30:00+01:00",
        config=SleeveEpisodeConfig(exit_confirm_screens=2),
    )
    import json

    store = json.loads((tmp_path / EPISODES_FILENAME).read_text(encoding="utf-8"))
    assert len(store["open"]) == 1
    assert store["open"][0]["exit_streak"] == 1

    review = run_sleeve_episodes_pass(
        output_dir=tmp_path,
        fund=fund,
        track_id="rules",
        candidates=[hold],
        prices_by_ticker={"AAA.L": 97},
        as_of="2026-09-22T09:30:00+01:00",
        config=SleeveEpisodeConfig(exit_confirm_screens=2),
    )
    assert review["open_count"] == 0
    assert review["closed_count"] == 1
    store = json.loads((tmp_path / EPISODES_FILENAME).read_text(encoding="utf-8"))
    assert store["closed"][0]["capital_status"] == CAPITAL_NEVER_FUNDED
    assert store["closed"][0]["latest_exit_at"] is not None


def test_hard_avoid_closes_immediately(tmp_path: Path):
    fund = _fund_with_holding("AAA.L")
    run_sleeve_episodes_pass(
        output_dir=tmp_path,
        fund=fund,
        track_id="ai_judgment",
        candidates=[
            {
                "ticker": "AAA.L",
                "name": "Alpha",
                "signal": "buy",
                "conviction_score": 0.9,
                "price": 100,
            }
        ],
        prices_by_ticker={"AAA.L": 100},
        as_of="2026-09-20T09:30:00+01:00",
    )
    review = run_sleeve_episodes_pass(
        output_dir=tmp_path,
        fund=fund,
        track_id="ai_judgment",
        candidates=[
            {
                "ticker": "AAA.L",
                "name": "Alpha",
                "signal": "avoid",
                "conviction_score": 0.1,
                "price": 80,
            }
        ],
        prices_by_ticker={"AAA.L": 80},
        as_of="2026-09-21T09:30:00+01:00",
    )
    assert review["closed_count"] == 1
    assert review["open_by_capital_status"][CAPITAL_ON_BOOK] == 0
