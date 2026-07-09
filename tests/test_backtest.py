"""Tests for signal backtest framework."""

from value_investor.backtest import (
    BacktestSummary,
    RunSnapshot,
    compute_backtest,
    format_backtest_text,
)


def _snapshot(run_at: str, ticker: str, signal: str, entry_price: float, exit_price: float):
    return (
        RunSnapshot(
            run_at=run_at,
            prices={ticker: entry_price, "^FTSE": 1000},
            signals=[{"ticker": ticker, "signal": signal, "conviction_score": 0.8, "data_quality_score": 0.9}],
        ),
        RunSnapshot(
            run_at=run_at.replace("T07:", "T08:") if "T07:" in run_at else run_at + "+1w",
            prices={ticker: exit_price, "^FTSE": 1010},
            signals=[{"ticker": ticker, "signal": signal, "conviction_score": 0.8, "data_quality_score": 0.9}],
        ),
    )


def test_compute_backtest_with_two_snapshots():
    entry = RunSnapshot(
        run_at="2026-06-01T07:00:00+00:00",
        prices={"AAA.L": 100.0, "^FTSE": 8000.0},
        signals=[{"ticker": "AAA.L", "signal": "strong_buy", "conviction_score": 0.8, "data_quality_score": 0.9}],
    )
    exit_snap = RunSnapshot(
        run_at="2026-06-15T07:00:00+00:00",
        prices={"AAA.L": 110.0, "^FTSE": 8040.0},
        signals=[{"ticker": "AAA.L", "signal": "strong_buy", "conviction_score": 0.85, "data_quality_score": 0.9}],
    )

    summary = compute_backtest([entry, exit_snap])

    assert summary.run_count == 2
    assert summary.has_results()
    strong_buy = [h for h in summary.horizons if h.signal == "strong_buy" and h.horizon_days == 7]
    assert strong_buy
    assert strong_buy[0].avg_return == 0.1
    assert strong_buy[0].excess_return > 0


def test_backtest_insufficient_history_note():
    summary = BacktestSummary(run_count=1, note="Need at least 2 archived runs")
    text = format_backtest_text(summary)
    assert "2 archived runs" in text
