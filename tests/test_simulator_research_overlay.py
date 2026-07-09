"""Tests for simulator research overlay options."""

from value_investor.backtest import BENCHMARK_TICKER, RunSnapshot
from value_investor.simulator import SimulatorConfig, run_simulation


def _snapshot(run_at: str, signals: list[dict]) -> RunSnapshot:
    return RunSnapshot(
        run_at=run_at,
        prices={"AAA.L": 100.0, "BBB.L": 50.0, BENCHMARK_TICKER: 8000.0},
        signals=signals,
    )


def test_simulation_uses_adjusted_signal_when_enabled():
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
        ),
    ]

    default_summary = run_simulation(snapshots)
    overlay_summary = run_simulation(
        snapshots,
        SimulatorConfig(use_adjusted_signal=True),
    )

    assert "AAA.L" in default_summary.holdings
    assert "AAA.L" not in overlay_summary.holdings
    assert "BBB.L" in overlay_summary.holdings


def test_simulation_require_research_accumulate():
    snapshots = [
        _snapshot(
            "2026-06-01T07:00:00+00:00",
            [
                {
                    "ticker": "AAA.L",
                    "signal": "strong_buy",
                    "research_verdict": "caution",
                    "conviction_score": 0.9,
                    "timing_signal": "accumulate",
                },
                {
                    "ticker": "BBB.L",
                    "signal": "strong_buy",
                    "research_verdict": "accumulate",
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
                    "research_verdict": "caution",
                    "conviction_score": 0.9,
                    "timing_signal": "accumulate",
                },
                {
                    "ticker": "BBB.L",
                    "signal": "strong_buy",
                    "research_verdict": "accumulate",
                    "conviction_score": 0.7,
                    "timing_signal": "accumulate",
                },
            ],
        ),
    ]

    summary = run_simulation(
        snapshots,
        SimulatorConfig(require_research_accumulate=True),
    )

    assert "AAA.L" not in summary.holdings
    assert "BBB.L" in summary.holdings
