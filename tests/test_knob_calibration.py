"""Tests for walk-forward knob calibration."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.knob_calibration import (
    KNOB_CALIBRATION_PRIORS_FILENAME,
    KnobCandidate,
    KnobGridAxis,
    calibrate_track,
    fold_fitness,
    iter_grid_candidates,
    walk_forward_fold_ranges,
    write_knob_calibration_priors,
)
from value_investor.paper_automation import AutomationConfig
from value_investor.rebalance_log import append_rebalance_log


def _calibration_log_entry(**overrides):
    base = {
        "acted": True,
        "track_id": "rules",
        "trade_cost_pct": 0.03,
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
            "use_adjusted_signal": False,
            "require_research_accumulate": False,
            "exit_confirm_screens": 2,
        },
        "screen_buy_tier": [
            {"ticker": "AAA.L", "signal": "buy", "conviction_score": 0.9, "price": 10},
            {"ticker": "BBB.L", "signal": "buy", "conviction_score": 0.8, "price": 10},
            {"ticker": "CCC.L", "signal": "buy", "conviction_score": 0.7, "price": 10},
        ],
        "candidates": [
            {"ticker": "AAA.L", "signal": "buy", "conviction_score": 0.9, "price": 10, "sector": "Banks"},
            {"ticker": "BBB.L", "signal": "buy", "conviction_score": 0.8, "price": 10, "sector": "Mining"},
            {"ticker": "CCC.L", "signal": "buy", "conviction_score": 0.7, "price": 10, "sector": "Tech"},
        ],
        "holdings_before": [],
        "holdings_after": [],
        "rebalance_state_before": {"exit_streak": {}, "reentry_cooldown": {}},
        "rebalance_state_after": {"exit_streak": {}, "reentry_cooldown": {}},
        "trades": [],
    }
    base.update(overrides)
    return base


def test_walk_forward_fold_ranges_split_chronologically():
    folds = walk_forward_fold_ranges(6, 3)
    assert folds
    assert folds[0][0] == 0
    assert folds[-1][1] == 6
    assert sum(end - start for start, end in folds) == 6


def test_iter_grid_candidates_counts_product():
    axes = (
        KnobGridAxis("max_positions", (3, 4)),
        KnobGridAxis("min_conviction", (0.0, 0.2)),
        KnobGridAxis("sector_cap", (0.2,)),
        KnobGridAxis("skip_timing_wait", (True,)),
    )
    candidates = iter_grid_candidates(axes)
    assert len(candidates) == 4


def test_fold_fitness_penalizes_cost_drag():
    replay = {"simulated_return": 0.1, "simulated_cost_drag": 0.2}
    assert fold_fitness(replay, cost_drag_lambda=0.5) == 0.0


def test_calibrate_track_ranks_candidates(tmp_path: Path):
    track = tmp_path / "rules"
    track.mkdir()
    config = AutomationConfig()
    config.track_id = "rules"
    config.max_positions = 3
    config.min_conviction = 0.0
    config.sector_cap = 0.2
    (track / "config.json").write_text(json.dumps(config.to_dict()), encoding="utf-8")
    (track / "automated_fund.json").write_text(
        json.dumps(
            {
                "config": {
                    "name": "Rules",
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
    for index, day in enumerate((1, 3, 5, 7, 9, 11)):
        append_rebalance_log(
            track,
            _calibration_log_entry(
                gate={"local_time": f"2026-08-{day:02d}T12:00:00+00:00"},
            ),
        )

    axes = (
        KnobGridAxis("max_positions", (3, 4)),
        KnobGridAxis("min_conviction", (0.0, 0.2)),
        KnobGridAxis("sector_cap", (0.2,)),
        KnobGridAxis("skip_timing_wait", (True,)),
    )
    result = calibrate_track(track, axes=axes, n_folds=3)
    assert result["scope"] == "knob_calibration"
    assert result["observe_only"] is True
    assert result["readiness"]["acted_entries"] == 6
    assert result["candidates_ranked"]
    assert result["recommended_prior"] is not None
    assert result["recommended_prior"]["knobs"]["max_positions"] in {3, 4}


def test_write_knob_calibration_priors(tmp_path: Path):
    payload = {
        "scope": "knob_calibration_multi",
        "tracks": {
            "rules": {
                "recommended_prior": {
                    "knobs": KnobCandidate(3, True, 0.2, 0.2).to_dict(),
                    "confidence": "low",
                }
            }
        },
    }
    path = write_knob_calibration_priors(tmp_path, payload)
    assert path == tmp_path / KNOB_CALIBRATION_PRIORS_FILENAME
    assert path.exists()
