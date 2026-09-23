"""Tests for dual-path sleeve episodes (observe-only, v2 widest window)."""

import json
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


def _fund_with_holding(ticker: str = "AAA.L", *, grace: bool = False) -> PaperFund:
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
        ticker=ticker,
        shares=1,
        avg_cost=100,
        name="Alpha",
        sector="Tech",
        momentum_grace=grace,
        grace_started_at="2026-09-01T09:30:00+01:00" if grace else None,
    )
    return fund


def test_opens_near_buy_and_buy_tier(tmp_path: Path):
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
            "ticker": "NEAR.L",
            "name": "Near buy",
            "signal": "hold",
            "conviction_score": 0.35,
            "price": 50,
        },
        {
            "ticker": "WEAK.L",
            "name": "Below pre_buy",
            "signal": "hold",
            "conviction_score": 0.10,
            "price": 40,
        },
    ]
    review = run_sleeve_episodes_pass(
        output_dir=tmp_path,
        fund=fund,
        track_id="rules",
        candidates=candidates,
        prices_by_ticker={"AAA.L": 100, "NEAR.L": 50, "WEAK.L": 40},
        as_of="2026-09-22T09:30:00+01:00",
        config=SleeveEpisodeConfig(exit_confirm_screens=2, post_grace_extra_days=30),
    )
    assert review["open_count"] == 2
    store = json.loads((tmp_path / EPISODES_FILENAME).read_text(encoding="utf-8"))
    by_ticker = {ep["ticker"]: ep for ep in store["open"]}
    assert set(by_ticker) == {"AAA.L", "NEAR.L"}
    assert by_ticker["AAA.L"]["capital_status"] == CAPITAL_ON_BOOK
    assert by_ticker["AAA.L"]["first_buy_tier_at"] is not None
    assert by_ticker["NEAR.L"]["capital_status"] == CAPITAL_NEVER_FUNDED
    assert by_ticker["NEAR.L"]["first_near_buy_at"] is not None
    assert by_ticker["NEAR.L"]["first_buy_tier_at"] is None


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
    store = json.loads((tmp_path / EPISODES_FILENAME).read_text(encoding="utf-8"))
    ep = store["open"][0]
    assert ep["capital_status"] == CAPITAL_OFF_BOOK
    assert ep["status"] == "open"


def test_fallback_close_after_confirms_plus_extra_days(tmp_path: Path):
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
    weak = {
        "ticker": "AAA.L",
        "name": "Alpha",
        "signal": "hold",
        "conviction_score": 0.10,
        "price": 98,
    }
    cfg = SleeveEpisodeConfig(exit_confirm_screens=2, post_grace_extra_days=30)
    run_sleeve_episodes_pass(
        output_dir=tmp_path,
        fund=fund,
        track_id="rules",
        candidates=[buy],
        prices_by_ticker={"AAA.L": 100},
        as_of="2026-09-01T09:30:00+01:00",
        config=cfg,
    )
    # Leave wide zone (below near-buy floor)
    run_sleeve_episodes_pass(
        output_dir=tmp_path,
        fund=fund,
        track_id="rules",
        candidates=[weak],
        prices_by_ticker={"AAA.L": 98},
        as_of="2026-09-02T09:30:00+01:00",
        config=cfg,
    )
    store = json.loads((tmp_path / EPISODES_FILENAME).read_text(encoding="utf-8"))
    assert store["open"][0]["exit_streak"] == 1
    assert store["open"][0]["experimental_exit_due_at"] is None

    run_sleeve_episodes_pass(
        output_dir=tmp_path,
        fund=fund,
        track_id="rules",
        candidates=[weak],
        prices_by_ticker={"AAA.L": 97},
        as_of="2026-09-03T09:30:00+01:00",
        config=cfg,
    )
    store = json.loads((tmp_path / EPISODES_FILENAME).read_text(encoding="utf-8"))
    assert store["open"][0]["exit_streak"] == 2
    assert store["open"][0]["experimental_exit_due_at"] == "2026-10-03"
    assert len(store["open"]) == 1

    # Before due — still open
    review = run_sleeve_episodes_pass(
        output_dir=tmp_path,
        fund=fund,
        track_id="rules",
        candidates=[weak],
        prices_by_ticker={"AAA.L": 96},
        as_of="2026-10-02T09:30:00+01:00",
        config=cfg,
    )
    assert review["open_count"] == 1

    review = run_sleeve_episodes_pass(
        output_dir=tmp_path,
        fund=fund,
        track_id="rules",
        candidates=[weak],
        prices_by_ticker={"AAA.L": 95},
        as_of="2026-10-03T09:30:00+01:00",
        config=cfg,
    )
    assert review["open_count"] == 0
    assert review["closed_count"] == 1
    store = json.loads((tmp_path / EPISODES_FILENAME).read_text(encoding="utf-8"))
    assert "post_grace_extra_days" in store["closed"][0]["latest_exit_reason"]


def test_grace_end_plus_extra_days_closes(tmp_path: Path):
    fund = _fund_with_holding("AAA.L", grace=True)
    buy = {
        "ticker": "AAA.L",
        "name": "Alpha",
        "signal": "buy",
        "conviction_score": 0.9,
        "price": 100,
    }
    hold_weak = {
        "ticker": "AAA.L",
        "name": "Alpha",
        "signal": "hold",
        "conviction_score": 0.1,
        "price": 95,
    }
    cfg = SleeveEpisodeConfig(
        exit_confirm_screens=1,
        post_grace_extra_days=30,
        grace_weeks=6,
    )
    run_sleeve_episodes_pass(
        output_dir=tmp_path,
        fund=fund,
        track_id="momentum_grace",
        candidates=[buy],
        prices_by_ticker={"AAA.L": 100},
        as_of="2026-09-01T09:30:00+01:00",
        config=cfg,
    )
    store = json.loads((tmp_path / EPISODES_FILENAME).read_text(encoding="utf-8"))
    assert store["open"][0]["grace_started_at"] is not None

    # Leave buy-tier while still in grace on the fund
    run_sleeve_episodes_pass(
        output_dir=tmp_path,
        fund=fund,
        track_id="momentum_grace",
        candidates=[hold_weak],
        prices_by_ticker={"AAA.L": 95},
        as_of="2026-09-02T09:30:00+01:00",
        config=cfg,
    )
    # Clear grace on the position → grace_ended + due
    fund.holdings["AAA.L"].momentum_grace = False
    fund.holdings["AAA.L"].grace_started_at = None
    run_sleeve_episodes_pass(
        output_dir=tmp_path,
        fund=fund,
        track_id="momentum_grace",
        candidates=[hold_weak],
        prices_by_ticker={"AAA.L": 94},
        as_of="2026-09-10T09:30:00+01:00",
        config=cfg,
    )
    store = json.loads((tmp_path / EPISODES_FILENAME).read_text(encoding="utf-8"))
    ep = store["open"][0]
    assert ep["grace_ended_at"] == "2026-09-10T09:30:00+01:00"
    assert ep["experimental_exit_due_at"] == "2026-10-10"

    review = run_sleeve_episodes_pass(
        output_dir=tmp_path,
        fund=fund,
        track_id="momentum_grace",
        candidates=[hold_weak],
        prices_by_ticker={"AAA.L": 90},
        as_of="2026-10-10T09:30:00+01:00",
        config=cfg,
    )
    assert review["closed_count"] == 1
    store = json.loads((tmp_path / EPISODES_FILENAME).read_text(encoding="utf-8"))
    assert "grace end" in store["closed"][0]["latest_exit_reason"]


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
