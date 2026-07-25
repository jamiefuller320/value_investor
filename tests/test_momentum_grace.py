"""Tests for momentum grace overlay logic."""

from datetime import date

from value_investor.momentum_grace import (
    MomentumGraceConfig,
    compute_grace_levels,
    evaluate_grace_holding,
    grace_expired,
    momentum_strength,
)


def test_momentum_strength_requires_price_above_sma50():
    ok, reasons = momentum_strength(
        {
            "timing_signal": "neutral",
            "price": 110,
            "sma_50": 100,
            "sma_200": 90,
            "macd_histogram": 0.5,
            "macd_histogram_prev": 0.2,
        }
    )
    assert ok is True
    assert any("50-day" in r for r in reasons)

    weak, _ = momentum_strength(
        {
            "timing_signal": "neutral",
            "price": 95,
            "sma_50": 100,
        }
    )
    assert weak is False


def test_momentum_strength_archive_fallback_uses_timing_and_sma200():
    ok, _ = momentum_strength(
        {
            "timing_signal": "accumulate",
            "price_vs_sma200_pct": 0.05,
        }
    )
    assert ok is True

    weak, _ = momentum_strength(
        {
            "timing_signal": "wait",
            "price_vs_sma200_pct": 0.10,
        }
    )
    assert weak is False


def test_grace_entry_when_hold_signal_but_momentum_strong():
    decision = evaluate_grace_holding(
        {
            "timing_signal": "neutral",
            "price": 120,
            "sma_50": 110,
            "macd_histogram": 0.4,
            "macd_histogram_prev": 0.1,
            "atr_14": 3.0,
        },
        signal="hold",
        avg_cost=100,
        mark=120,
        momentum_grace=False,
        grace_started_at=None,
        stop_loss=95,
        take_profit=130,
        grace_entry_stop=None,
        as_of="2026-07-20",
    )
    assert decision.keep is True
    assert decision.enter_grace is True
    assert decision.stop_loss is not None
    assert decision.take_profit is not None
    assert decision.stop_loss >= 100


def test_grace_hard_exit_on_avoid():
    decision = evaluate_grace_holding(
        {"timing_signal": "neutral", "price": 120, "sma_50": 110},
        signal="avoid",
        avg_cost=100,
        mark=120,
        momentum_grace=True,
        grace_started_at="2026-07-01",
        stop_loss=105,
        take_profit=140,
        grace_entry_stop=100,
        as_of="2026-07-20",
    )
    assert decision.keep is False
    assert decision.exit_grace is True


def test_grace_expires_after_configured_weeks():
    cfg = MomentumGraceConfig(grace_weeks=6)
    assert grace_expired("2026-06-01", as_of=date(2026, 7, 20), config=cfg) is True
    assert grace_expired("2026-07-15", as_of=date(2026, 7, 20), config=cfg) is False


def test_compute_grace_levels_trails_stop_above_entry_floor():
    stop, target = compute_grace_levels(
        {
            "price": 120,
            "sma_50": 110,
            "atr_14": 4.0,
        },
        avg_cost=100,
        current_stop=105,
        current_take_profit=125,
        entry_stop_floor=100,
    )
    assert stop is not None and stop >= 100
    assert target is not None and target >= 125
