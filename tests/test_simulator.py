"""Tests for portfolio simulation."""

from value_investor.backtest import BENCHMARK_TICKER, RunSnapshot
from value_investor.simulator import SimulatorConfig, format_simulation_text, run_simulation


def _snapshot(
    run_at: str,
    prices: dict[str, float],
    signals: list[dict],
) -> RunSnapshot:
    return RunSnapshot(run_at=run_at, prices=prices, signals=signals)


def test_simulation_grows_with_rising_picks_and_costs_apply():
    snapshots = [
        _snapshot(
            "2026-06-01T07:00:00+00:00",
            {"AAA.L": 100.0, "BBB.L": 50.0, BENCHMARK_TICKER: 8000.0},
            [
                {"ticker": "AAA.L", "signal": "strong_buy", "conviction_score": 0.9, "data_quality_score": 0.8},
                {"ticker": "BBB.L", "signal": "buy", "conviction_score": 0.7, "data_quality_score": 0.8},
            ],
        ),
        _snapshot(
            "2026-06-15T07:00:00+00:00",
            {"AAA.L": 110.0, "BBB.L": 52.0, BENCHMARK_TICKER: 8040.0},
            [
                {"ticker": "AAA.L", "signal": "strong_buy", "conviction_score": 0.92, "data_quality_score": 0.8},
                {"ticker": "BBB.L", "signal": "buy", "conviction_score": 0.72, "data_quality_score": 0.8},
            ],
        ),
    ]

    summary = run_simulation(snapshots, SimulatorConfig(initial_capital=1000, trade_cost_pct=0.03))

    assert summary.has_results()
    assert summary.final_value > 1000
    assert summary.total_costs > 0
    assert summary.trade_count >= 2
    assert summary.benchmark_return > 0


def test_simulation_skips_wait_timing_for_new_buys():
    snapshots = [
        _snapshot(
            "2026-06-01T07:00:00+00:00",
            {"AAA.L": 100.0, "BBB.L": 50.0, BENCHMARK_TICKER: 8000.0},
            [
                {
                    "ticker": "AAA.L",
                    "signal": "strong_buy",
                    "conviction_score": 0.9,
                    "data_quality_score": 0.8,
                    "timing_signal": "wait",
                },
                {
                    "ticker": "BBB.L",
                    "signal": "buy",
                    "conviction_score": 0.7,
                    "data_quality_score": 0.8,
                    "timing_signal": "accumulate",
                },
            ],
        ),
        _snapshot(
            "2026-06-15T07:00:00+00:00",
            {"AAA.L": 110.0, "BBB.L": 55.0, BENCHMARK_TICKER: 8040.0},
            [
                {
                    "ticker": "AAA.L",
                    "signal": "strong_buy",
                    "conviction_score": 0.9,
                    "data_quality_score": 0.8,
                    "timing_signal": "wait",
                },
                {
                    "ticker": "BBB.L",
                    "signal": "buy",
                    "conviction_score": 0.7,
                    "data_quality_score": 0.8,
                    "timing_signal": "accumulate",
                },
            ],
        ),
    ]

    summary = run_simulation(snapshots)
    assert "AAA.L" not in summary.holdings
    assert "BBB.L" in summary.holdings


def test_simulation_insufficient_history():
    summary = run_simulation([
        _snapshot("2026-06-01T07:00:00+00:00", {"AAA.L": 100.0}, [])
    ])
    text = format_simulation_text(summary)
    assert "2 archived runs" in text


def test_simulation_trade_plan_limit_blocks_entry():
    snapshots = [
        _snapshot(
            "2026-06-01T07:00:00+00:00",
            {"AAA.L": 100.0, BENCHMARK_TICKER: 8000.0},
            [
                {
                    "ticker": "AAA.L",
                    "signal": "strong_buy",
                    "conviction_score": 0.9,
                    "data_quality_score": 0.8,
                    "core_order": "limit",
                    "core_limit": 90.0,
                    "tactical_stop_loss": 80.0,
                    "tactical_take_profit": 120.0,
                }
            ],
        ),
        _snapshot(
            "2026-06-15T07:00:00+00:00",
            {"AAA.L": 101.0, BENCHMARK_TICKER: 8010.0},
            [
                {
                    "ticker": "AAA.L",
                    "signal": "strong_buy",
                    "conviction_score": 0.9,
                    "data_quality_score": 0.8,
                    "core_order": "limit",
                    "core_limit": 90.0,
                    "tactical_stop_loss": 80.0,
                    "tactical_take_profit": 120.0,
                }
            ],
        ),
    ]
    blocked = run_simulation(
        snapshots, SimulatorConfig(use_trade_plan_levels=True, trade_cost_pct=0.0)
    )
    assert "AAA.L" not in blocked.holdings
    assert blocked.trade_count == 0

    market = run_simulation(
        snapshots, SimulatorConfig(use_trade_plan_levels=False, trade_cost_pct=0.0)
    )
    assert "AAA.L" in market.holdings


def test_simulation_trade_plan_stop_exits_position():
    snapshots = [
        _snapshot(
            "2026-06-01T07:00:00+00:00",
            {"AAA.L": 100.0, BENCHMARK_TICKER: 8000.0},
            [
                {
                    "ticker": "AAA.L",
                    "signal": "strong_buy",
                    "conviction_score": 0.9,
                    "data_quality_score": 0.8,
                    "core_order": "market",
                    "tactical_stop_loss": 95.0,
                    "tactical_take_profit": 130.0,
                }
            ],
        ),
        _snapshot(
            "2026-06-15T07:00:00+00:00",
            {"AAA.L": 90.0, BENCHMARK_TICKER: 7990.0},
            [
                {
                    "ticker": "AAA.L",
                    "signal": "strong_buy",
                    "conviction_score": 0.9,
                    "data_quality_score": 0.8,
                    "core_order": "market",
                    "tactical_stop_loss": 95.0,
                    "tactical_take_profit": 130.0,
                }
            ],
        ),
    ]
    summary = run_simulation(
        snapshots, SimulatorConfig(use_trade_plan_levels=True, trade_cost_pct=0.0)
    )
    assert "AAA.L" not in summary.holdings
    assert any(t.side == "sell" for t in summary.trades)
