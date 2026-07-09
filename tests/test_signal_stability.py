"""Tests for signal stability and conviction."""

from datetime import UTC, datetime

import pandas as pd

from value_investor.signal_stability import (
    compute_stability,
    conviction_score,
    enrich_signals_with_stability,
)


def test_conviction_increases_with_persistence():
    low = conviction_score(
        blended_composite=0.8,
        families_passed=3,
        family_count=4,
        data_quality_score=0.9,
        weeks_at_signal=1,
    )
    high = conviction_score(
        blended_composite=0.8,
        families_passed=3,
        family_count=4,
        data_quality_score=0.9,
        weeks_at_signal=4,
    )
    assert high > low


def test_compute_stability_detects_persistent_signal():
    history = pd.DataFrame([
        {
            "run_at": "2026-06-10T07:00:00+00:00",
            "ticker": "AAA.L",
            "signal": "strong_buy",
            "signal_rank": 4,
            "conviction_score": 0.7,
            "data_quality_score": 0.8,
        },
        {
            "run_at": "2026-06-17T07:00:00+00:00",
            "ticker": "AAA.L",
            "signal": "strong_buy",
            "signal_rank": 4,
            "conviction_score": 0.72,
            "data_quality_score": 0.8,
        },
    ])
    info = compute_stability(
        history,
        ticker="AAA.L",
        current_signal="strong_buy",
        current_rank=4,
        blended_composite=0.8,
        families_passed=3,
        family_count=4,
        data_quality_score=0.85,
        current_run_at=datetime(2026, 6, 24, 7, 0, tzinfo=UTC),
    )
    assert info.weeks_at_signal >= 2
    assert info.signal_trend == "stable"
    assert info.stability_label in ("building", "persistent")


def test_enrich_signals_adds_conviction_columns():
    signals = pd.DataFrame([
        {
            "ticker": "AAA.L",
            "signal": "buy",
            "signal_rank": 3,
            "composite_score": 0.7,
            "sector_composite_score": 0.75,
            "families_passed": 2,
            "family_count": 4,
            "data_quality_score": 0.8,
        }
    ])
    history = pd.DataFrame(columns=[
        "run_at", "ticker", "signal", "signal_rank", "conviction_score", "data_quality_score"
    ])
    out = enrich_signals_with_stability(
        signals,
        history,
        run_at=datetime(2026, 7, 8, 7, 0, tzinfo=UTC),
    )
    assert "conviction_score" in out.columns
    assert "stability_label" in out.columns
