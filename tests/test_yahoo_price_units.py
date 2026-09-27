"""Tests for Yahoo GBp↔GBP mid-series unit-flip normalization."""

from __future__ import annotations

import pandas as pd

from value_investor.yahoo_price_units import (
    align_price_to_reference,
    is_unit_flip_ratio,
    normalize_close_series,
    normalize_ohlcv_frame,
    normalize_price_series,
)


def test_is_unit_flip_ratio_band():
    assert is_unit_flip_ratio(100.0)
    assert is_unit_flip_ratio(0.01)
    assert is_unit_flip_ratio(99.44)
    assert is_unit_flip_ratio(0.010056)
    assert not is_unit_flip_ratio(2.0)
    assert not is_unit_flip_ratio(0.5)
    assert not is_unit_flip_ratio(0.05)
    assert not is_unit_flip_ratio(-1.0)
    assert not is_unit_flip_ratio(None)


def test_bcg_like_one_way_pence_to_pounds_flip():
    # BCG.L style: ~200p then Yahoo flips to ~£2 and stays there.
    closes = [210.0, 208.17, 200.86, 2.02, 2.05, 2.10, 2.05]
    result = normalize_price_series(closes, anchor="last")
    assert result.applied
    assert result.flip_count == 1
    assert result.values[-1] == 2.05
    # Pre-flip bars rewritten into pounds.
    assert abs(result.values[1] - 2.0817) < 1e-9
    assert abs(result.values[2] - 2.0086) < 1e-9
    assert abs(result.values[3] - 2.02) < 1e-9
    # Unit-consistent return from recommendation-week close ≈ −1.5%.
    entry, last = result.values[1], result.values[-1]
    assert abs((last / entry) - 1.0 - (-0.0152)) < 1e-3


def test_head_like_oscillating_unit_flips():
    # HEAD.L style: pence ↔ pounds flips both ways after distress lows.
    closes = [55.6, 12.0, 10.5, 5.0, 10.5, 0.1, 10.5, 0.1, 0.1]
    result = normalize_price_series(closes, anchor="last")
    assert result.applied
    assert result.flip_count >= 2
    assert result.values[-1] == 0.1
    # Entry at distressed 5p and last 10.5p → +100% in pounds.
    entry = result.values[3]
    peak = result.values[6]
    last = result.values[-1]
    assert abs(entry - 0.05) < 1e-9
    assert abs(peak - 0.105) < 1e-9
    assert abs(last - 0.1) < 1e-9
    assert abs((last / entry) - 1.0 - 1.0) < 1e-9
    # Longer-horizon distress from ~55p to ~10p is preserved (~−82%).
    assert abs((result.values[2] / result.values[0]) - 1.0 - (-0.81115)) < 1e-3


def test_real_gradual_decline_not_rewritten():
    # Multi-month distress without a ~100× session jump stays intact.
    closes = [55.6, 40.0, 25.0, 15.0, 10.5, 5.0, 10.5]
    result = normalize_price_series(closes, anchor="last")
    assert not result.applied
    assert result.values == closes


def test_align_price_to_reference():
    assert abs(align_price_to_reference(208.17, 2.05) - 2.0817) < 1e-9
    assert align_price_to_reference(0.05, 5.0) == 5.0
    assert align_price_to_reference(100.0, 102.0) == 100.0
    assert align_price_to_reference(None, 2.0) is None


def test_normalize_close_series_and_ohlcv():
    series = pd.Series([200.0, 2.0, 2.1], index=pd.date_range("2026-08-01", periods=3, freq="B"))
    normalized, meta = normalize_close_series(series)
    assert meta.applied
    assert list(normalized.round(4)) == [2.0, 2.0, 2.1]

    frame = pd.DataFrame(
        {
            "Open": [201.0, 2.01, 2.05],
            "High": [202.0, 2.05, 2.15],
            "Low": [199.0, 1.95, 2.00],
            "Close": [200.0, 2.0, 2.1],
            "Volume": [1, 2, 3],
        },
        index=series.index,
    )
    out, frame_meta = normalize_ohlcv_frame(frame)
    assert frame_meta.applied
    assert abs(out["Close"].iloc[0] - 2.0) < 1e-9
    assert abs(out["Open"].iloc[0] - 2.01) < 1e-9
    assert out["Volume"].tolist() == [1, 2, 3]
