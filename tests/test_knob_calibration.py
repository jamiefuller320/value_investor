"""Tests for walk-forward knob calibration."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.knob_calibration import (
    CALIBRATION_PROVENANCE_FILENAME,
    KNOB_CALIBRATION_PRIORS_FILENAME,
    KnobCandidate,
    KnobGridAxis,
    calibrate_track,
    fold_fitness,
    iter_grid_candidates,
    spawn_calibrated_shadow_track,
    walk_forward_fold_ranges,
    write_knob_calibration_priors,
)
from value_investor.paper_automation import (
    AI_JUDGMENT_CALIBRATED_TRACK_ID,
    AutomationConfig,
    learning_track_dirs,
)
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
    for _index, day in enumerate((1, 3, 5, 7, 9, 11)):
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


def _seed_ai_judgment_parent(tmp_path: Path) -> Path:
    paper_root = tmp_path / "paper"
    ai_dir = paper_root / "ai_judgment"
    ai_dir.mkdir(parents=True)
    config = AutomationConfig()
    config.track_id = "ai_judgment"
    config.is_primary_learning_track = True
    config.use_adjusted_signal = True
    config.require_research_accumulate = True
    config.max_positions = 3
    config.min_conviction = 0.3
    config.sector_cap = 0.2
    config.initial_cash = 1000.0
    (ai_dir / "config.json").write_text(json.dumps(config.to_dict()), encoding="utf-8")
    (paper_root / "config.json").write_text(json.dumps(AutomationConfig().to_dict()), encoding="utf-8")
    priors = {
        "scope": "knob_calibration_multi",
        "calibrated_at": "2026-08-18T00:00:00+00:00",
        "tracks": {
            "ai_judgment": {
                "recommended_prior": {
                    "knobs": {
                        "max_positions": 5,
                        "skip_timing_wait": True,
                        "min_conviction": 0.0,
                        "sector_cap": 0.2,
                    },
                    "confidence": "low",
                }
            }
        },
    }
    write_knob_calibration_priors(paper_root, priors)
    return paper_root


def test_spawn_calibrated_shadow_track_creates_frozen_book(tmp_path: Path):
    paper_root = _seed_ai_judgment_parent(tmp_path)
    result = spawn_calibrated_shadow_track(paper_root)
    assert result["spawned"] is True
    assert result["shadow_track_id"] == AI_JUDGMENT_CALIBRATED_TRACK_ID
    shadow_dir = paper_root / "ai_judgment_calibrated"
    assert (shadow_dir / "config.json").exists()
    assert (shadow_dir / "automated_fund.json").exists()
    assert (shadow_dir / CALIBRATION_PROVENANCE_FILENAME).exists()
    cfg = json.loads((shadow_dir / "config.json").read_text(encoding="utf-8"))
    assert cfg["is_calibration_shadow"] is True
    assert cfg["max_positions"] == 5
    assert cfg["min_conviction"] == 0.0
    assert AI_JUDGMENT_CALIBRATED_TRACK_ID in learning_track_dirs(paper_root)


def test_spawn_calibrated_shadow_idempotent_without_force(tmp_path: Path):
    paper_root = _seed_ai_judgment_parent(tmp_path)
    first = spawn_calibrated_shadow_track(paper_root)
    fund_path = paper_root / "ai_judgment_calibrated" / "automated_fund.json"
    fund_path.write_text(fund_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    second = spawn_calibrated_shadow_track(paper_root)
    assert first["spawned"] is True
    assert second["spawned"] is True
    assert second["respawned_fund"] is False


def test_decision_review_skips_apply_for_calibration_shadow(tmp_path: Path):
    from value_investor.decision_review import run_decision_review

    paper_root = _seed_ai_judgment_parent(tmp_path)
    spawn_calibrated_shadow_track(paper_root)
    shadow_dir = paper_root / "ai_judgment_calibrated"
    result = run_decision_review(output_dir=shadow_dir, apply=True, force=True)
    assert result.applied is False
    assert "frozen" in (result.note or "").lower()
    cfg = json.loads((shadow_dir / "config.json").read_text(encoding="utf-8"))
    assert cfg["max_positions"] == 5
