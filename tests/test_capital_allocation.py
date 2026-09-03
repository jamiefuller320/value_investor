"""Tests for graduated capital allocation scoring."""

from __future__ import annotations

from types import SimpleNamespace

from value_investor.capital_allocation import (
    CapitalAllocationConfig,
    classify_lifecycle_phase,
    entry_appetite,
    entry_sleeve_fraction,
    exit_urgency,
    score_rebalance_candidates,
    skim_fraction,
    swap_score,
)


def test_entry_appetite_timing_ordering():
    base = {
        "ticker": "AAA.L",
        "signal": "buy",
        "conviction_score": 0.6,
    }
    accumulate = entry_appetite({**base, "timing_signal": "accumulate"})
    wait = entry_appetite({**base, "timing_signal": "wait"})
    assert accumulate > wait
    assert entry_appetite({**base, "signal": "hold"}) == 0.0


def test_entry_sleeve_fraction_uses_trade_plan():
    row = {
        "signal": "buy",
        "timing_signal": "neutral",
        "trade_plan": {"core_allocation_pct": 0.72},
    }
    assert entry_sleeve_fraction(row) == 0.72


def test_exit_urgency_higher_when_left_buy_tier():
    row = {"signal": "hold", "timing_signal": "wait"}
    urgent = exit_urgency(
        row=row,
        mark=120.0,
        avg_cost=100.0,
        in_target_set=False,
        exit_streak=2,
    )
    calm = exit_urgency(
        row={"signal": "buy", "timing_signal": "accumulate"},
        mark=105.0,
        avg_cost=100.0,
        in_target_set=True,
    )
    assert urgent > calm


def test_skim_fraction_threshold():
    cfg = CapitalAllocationConfig(skim_urgency_threshold=0.55)
    assert skim_fraction(0.4, config=cfg) == 0.0
    assert skim_fraction(0.8, config=cfg) > 0.0


def test_swap_score_penalizes_costs():
    assert swap_score(
        exit_urgency_value=0.4,
        entry_appetite_value=0.7,
        trade_cost_pct=0.03,
    ) > swap_score(
        exit_urgency_value=0.4,
        entry_appetite_value=0.7,
        trade_cost_pct=0.10,
    )


def test_classify_lifecycle_phase_starter_vs_build():
    assert (
        classify_lifecycle_phase(
            held=True,
            in_target_set=True,
            current_value=30.0,
            target_value=100.0,
            exit_streak=0,
            momentum_grace=False,
            row={"signal": "buy", "timing_signal": "accumulate"},
        )
        == "starter"
    )


def test_classify_lifecycle_phase_build_vs_harvest():
    assert (
        classify_lifecycle_phase(
            held=True,
            in_target_set=True,
            current_value=50.0,
            target_value=100.0,
            exit_streak=0,
            momentum_grace=False,
            row={"signal": "buy", "timing_signal": "accumulate"},
        )
        == "build"
    )
    assert (
        classify_lifecycle_phase(
            held=True,
            in_target_set=True,
            current_value=130.0,
            target_value=100.0,
            exit_streak=0,
            momentum_grace=False,
            row={"signal": "buy", "timing_signal": "wait"},
        )
        == "harvest"
    )


def test_score_rebalance_candidates_snapshot():
    position = SimpleNamespace(shares=10.0, avg_cost=100.0, momentum_grace=False)
    snapshot = score_rebalance_candidates(
        targets=[
            {
                "ticker": "AAA.L",
                "signal": "buy",
                "timing_signal": "accumulate",
                "conviction_score": 0.8,
                "trade_plan": {"core_allocation_pct": 0.7},
            }
        ],
        holdings={"AAA.L": position},
        price_map={"AAA.L": 100.0},
        target_each=250.0,
        target_tickers={"AAA.L"},
        exit_streaks={},
    )
    assert snapshot["entries"][0]["entry_appetite"] > 0.7
    assert snapshot["entries"][0]["lifecycle"] in {"build", "full"}
