"""Tests for cohort-selection fitness."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.cohort_selection_fitness import (
    blend_calibration_score,
    collect_cohort_observations,
    discover_knob_axis_discriminability,
    summarize_cohort_observations,
)
from value_investor.knob_calibration import calibrate_track
from value_investor.paper_automation import AutomationConfig
from value_investor.rebalance_log import append_rebalance_log


def _calibration_log_entry(**overrides):
    base = {
        "acted": True,
        "track_id": "ai_judgment",
        "trade_cost_pct": 0.03,
        "strategy_mode": "automated",
        "gate": {"local_time": "2026-08-01T12:00:00+00:00"},
        "nav_before": 1000.0,
        "nav_after": 1000.0,
        "cash_before": 1000.0,
        "cash_after": 1000.0,
        "contributed_capital_before": 1000.0,
        "selection": {
            "skip_timing_wait": True,
            "min_conviction": 0.0,
            "sector_cap": 0.3,
            "use_adjusted_signal": True,
            "require_research_accumulate": True,
            "exit_confirm_screens": 2,
        },
        "screen_buy_tier": [
            {
                "ticker": "AAA.L",
                "signal": "strong_buy",
                "adjusted_signal": "strong_buy",
                "conviction_score": 0.9,
                "price": 100,
            },
            {
                "ticker": "BBB.L",
                "signal": "strong_buy",
                "adjusted_signal": "strong_buy",
                "conviction_score": 0.8,
                "price": 100,
            },
            {
                "ticker": "CCC.L",
                "signal": "strong_buy",
                "adjusted_signal": "strong_buy",
                "conviction_score": 0.7,
                "price": 100,
            },
            {
                "ticker": "DDD.L",
                "signal": "buy",
                "adjusted_signal": "buy",
                "conviction_score": 0.4,
                "price": 100,
            },
        ],
        "candidates": [
            {
                "ticker": "AAA.L",
                "signal": "strong_buy",
                "adjusted_signal": "strong_buy",
                "conviction_score": 0.9,
                "price": 100,
                "sector": "Banks",
                "research_verdict": "accumulate",
            },
            {
                "ticker": "BBB.L",
                "signal": "strong_buy",
                "adjusted_signal": "strong_buy",
                "conviction_score": 0.8,
                "price": 100,
                "sector": "Mining",
                "research_verdict": "accumulate",
            },
            {
                "ticker": "CCC.L",
                "signal": "strong_buy",
                "adjusted_signal": "strong_buy",
                "conviction_score": 0.7,
                "price": 100,
                "sector": "Tech",
                "research_verdict": "accumulate",
            },
            {
                "ticker": "DDD.L",
                "signal": "buy",
                "adjusted_signal": "buy",
                "conviction_score": 0.4,
                "price": 100,
                "sector": "Tech",
                "research_verdict": "accumulate",
            },
        ],
        "holdings_before": [],
        "holdings_after": [],
        "rebalance_state_before": {"exit_streak": {}, "reentry_cooldown": {}},
        "rebalance_state_after": {"exit_streak": {}, "reentry_cooldown": {}},
        "trades": [],
    }
    base.update(overrides)
    return base


def test_collect_cohort_observations_tracks_selected_and_rejected(tmp_path: Path):
    acted = []
    for day, prices in ((1, 100), (3, 110), (5, 105)):
        acted.append(
            _calibration_log_entry(
                gate={"local_time": f"2026-08-{day:02d}T12:00:00+00:00"},
                candidates=[
                    {
                        "ticker": "AAA.L",
                        "signal": "strong_buy",
                        "adjusted_signal": "strong_buy",
                        "conviction_score": 0.9,
                        "price": prices,
                        "sector": "Banks",
                        "research_verdict": "accumulate",
                    },
                    {
                        "ticker": "BBB.L",
                        "signal": "strong_buy",
                        "adjusted_signal": "strong_buy",
                        "conviction_score": 0.8,
                        "price": prices,
                        "sector": "Mining",
                        "research_verdict": "accumulate",
                    },
                    {
                        "ticker": "CCC.L",
                        "signal": "strong_buy",
                        "adjusted_signal": "strong_buy",
                        "conviction_score": 0.7,
                        "price": prices,
                        "sector": "Tech",
                        "research_verdict": "accumulate",
                    },
                    {
                        "ticker": "DDD.L",
                        "signal": "buy",
                        "adjusted_signal": "buy",
                        "conviction_score": 0.4,
                        "price": prices,
                        "sector": "Tech",
                        "research_verdict": "accumulate",
                    },
                ],
            )
        )
    observations = collect_cohort_observations(
        acted,
        max_positions=2,
        skip_timing_wait=True,
        min_conviction=0.0,
        sector_cap=0.5,
        use_adjusted_signal=True,
        require_research_accumulate=True,
    )
    assert observations
    roles = {obs.role for obs in observations}
    assert "selected" in roles or "new_buy" in roles
    assert "rejected" in roles


def test_summarize_cohort_observations_computes_spread():
    from value_investor.cohort_selection_fitness import CohortObservation

    summary = summarize_cohort_observations(
        [
            CohortObservation("AAA.L", 0, "selected", 0.1),
            CohortObservation("BBB.L", 0, "selected", 0.05),
            CohortObservation("CCC.L", 0, "rejected", -0.05),
            CohortObservation("DDD.L", 0, "rejected", -0.1),
        ]
    )
    assert summary["cohort_hit_rate"] == 1.0
    assert summary["selection_spread"] is not None
    assert summary["selection_spread"] > 0


def test_blend_calibration_score_weights_components():
    blended = blend_calibration_score(0.5, 0.1, cohort_weight=0.6)
    assert blended == 0.4 * 0.5 + 0.6 * 0.1


def test_discover_knob_axis_discriminability_detects_flat_axis():
    rows = [
        {"knobs": {"max_positions": 3, "min_conviction": 0.0}, "blended_score": 0.2},
        {"knobs": {"max_positions": 4, "min_conviction": 0.0}, "blended_score": 0.5},
        {"knobs": {"max_positions": 3, "min_conviction": 0.2}, "blended_score": 0.21},
        {"knobs": {"max_positions": 4, "min_conviction": 0.2}, "blended_score": 0.49},
    ]
    result = discover_knob_axis_discriminability(
        rows,
        ("max_positions", "min_conviction"),
        score_key="blended_score",
    )
    assert result["max_positions"]["discriminatory"] is True
    assert result["min_conviction"]["discriminatory"] is False


def test_calibrate_track_enables_cohort_fitness_for_ai_judgment(tmp_path: Path):
    track = tmp_path / "ai_judgment"
    track.mkdir()
    config = AutomationConfig()
    config.track_id = "ai_judgment"
    config.use_adjusted_signal = True
    config.require_research_accumulate = True
    (track / "config.json").write_text(json.dumps(config.to_dict()), encoding="utf-8")
    (track / "automated_fund.json").write_text(
        json.dumps(
            {
                "config": {
                    "name": "AI",
                    "mode": "automated",
                    "initial_cash": 1000.0,
                    "trade_cost_pct": 0.03,
                    "max_positions": 3,
                },
                "cash": 1000.0,
                "holdings": {},
                "trades": [],
                "rebalance_state": {"exit_streak": {}, "reentry_cooldown": {}},
            }
        ),
        encoding="utf-8",
    )
    for day in (1, 3, 5, 7, 9, 11):
        append_rebalance_log(
            track, _calibration_log_entry(gate={"local_time": f"2026-08-{day:02d}T12:00:00+00:00"})
        )

    result = calibrate_track(track, n_folds=3)
    assert result["readiness"]["use_cohort_fitness"] is True
    assert result["knob_axis_discriminability"]
    top = result["candidates_ranked"][0]
    assert "blended_score" in top
    assert top.get("cohort_selection") is not None
