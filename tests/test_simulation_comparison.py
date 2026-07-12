"""Tests for screen vs research-overlay simulation comparison."""

import pytest

from value_investor.backtest import BENCHMARK_TICKER, RunSnapshot
from value_investor.simulator import (
    SimulatorConfig,
    format_simulation_comparison_text,
    run_simulation_comparison,
    simulation_comparison_from_dict,
)


def _snapshot(run_at: str, signals: list[dict], prices: dict[str, float] | None = None) -> RunSnapshot:
    return RunSnapshot(
        run_at=run_at,
        prices=prices or {"AAA.L": 100.0, "BBB.L": 50.0, BENCHMARK_TICKER: 8000.0},
        signals=signals,
    )


def test_run_simulation_comparison_diverges_with_overlay_data():
    snapshots = [
        _snapshot(
            "2026-06-01T07:00:00+00:00",
            [
                {
                    "ticker": "AAA.L",
                    "signal": "strong_buy",
                    "adjusted_signal": "hold",
                    "conviction_score": 0.9,
                    "timing_signal": "accumulate",
                },
                {
                    "ticker": "BBB.L",
                    "signal": "buy",
                    "adjusted_signal": "buy",
                    "conviction_score": 0.7,
                    "timing_signal": "accumulate",
                },
            ],
        ),
        _snapshot(
            "2026-06-15T07:00:00+00:00",
            [
                {
                    "ticker": "AAA.L",
                    "signal": "strong_buy",
                    "adjusted_signal": "hold",
                    "conviction_score": 0.9,
                    "timing_signal": "accumulate",
                },
                {
                    "ticker": "BBB.L",
                    "signal": "buy",
                    "adjusted_signal": "buy",
                    "conviction_score": 0.7,
                    "timing_signal": "accumulate",
                },
            ],
            {"AAA.L": 110.0, "BBB.L": 55.0, BENCHMARK_TICKER: 8040.0},
        ),
    ]

    comparison = run_simulation_comparison(snapshots)
    assert comparison.screen.has_results()
    assert comparison.overlay.has_results()
    assert "AAA.L" in comparison.screen.holdings
    assert "AAA.L" not in comparison.overlay.holdings
    assert "BBB.L" in comparison.overlay.holdings
    assert comparison.comparison_note

    payload = comparison.to_dict()
    restored = simulation_comparison_from_dict(payload)
    assert restored.overlay.total_return == pytest.approx(comparison.overlay.total_return, rel=1e-3)

    text = format_simulation_comparison_text(comparison)
    assert "Screen only" in text
    assert "research overlay" in text.lower()
    assert comparison.comparison_note in text


def test_comparison_note_when_no_research_data():
    snapshots = [
        _snapshot(
            "2026-06-01T07:00:00+00:00",
            [{"ticker": "AAA.L", "signal": "strong_buy", "conviction_score": 0.9, "timing_signal": "accumulate"}],
        ),
        _snapshot(
            "2026-06-15T07:00:00+00:00",
            [{"ticker": "AAA.L", "signal": "strong_buy", "conviction_score": 0.9, "timing_signal": "accumulate"}],
            {"AAA.L": 110.0, BENCHMARK_TICKER: 8040.0},
        ),
    ]

    comparison = run_simulation_comparison(snapshots, SimulatorConfig(max_positions=1))
    assert comparison.screen.final_value == comparison.overlay.final_value
    assert "No research verdicts" in comparison.comparison_note
