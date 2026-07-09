"""Tests for technical analysis and market timing."""

import numpy as np
import pandas as pd

from value_investor.technical_analysis import (
    TimingSignal,
    assign_timing_signal,
    combined_action,
    compute_indicators,
    format_timing_summary,
)


def _synthetic_closes(n: int = 220, *, trend: float = 0.0, noise: float = 0.5) -> pd.Series:
    rng = np.random.default_rng(42)
    prices = [100.0]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + trend + rng.normal(0, noise / 100)))
    return pd.Series(prices)


def test_assign_timing_signal_oversold_accumulate():
    signal, score, reasons = assign_timing_signal(
        rsi=28.0,
        close=95.0,
        sma_50=100.0,
        sma_200=105.0,
        macd_histogram=0.5,
        macd_histogram_prev=0.1,
    )
    assert signal == TimingSignal.ACCUMULATE
    assert score > 0.5
    assert any("RSI" in r for r in reasons)


def test_assign_timing_signal_overbought_wait():
    signal, _, reasons = assign_timing_signal(
        rsi=75.0,
        close=130.0,
        sma_50=120.0,
        sma_200=110.0,
        macd_histogram=-0.5,
        macd_histogram_prev=-0.2,
    )
    assert signal == TimingSignal.WAIT
    assert reasons


def test_compute_indicators_on_synthetic_series():
    close = _synthetic_closes(220)
    result = compute_indicators(close)
    assert result.rsi_14 is not None
    assert result.sma_200 is not None
    assert result.timing_signal in TimingSignal


def test_combined_action_merges_value_and_timing():
    assert "favourable" in combined_action("strong_buy", "accumulate").lower()
    assert "pullback" in combined_action("strong_buy", "wait").lower()
    assert "Pass" in combined_action("avoid", "accumulate")


def test_format_timing_summary():
    text = format_timing_summary("accumulate", 32.0, ["RSI oversold (32)"])
    assert "Accumulate" in text
    assert "RSI 32" in text
