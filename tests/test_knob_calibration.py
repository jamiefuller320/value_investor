"""Tests for walk-forward knob calibration and full-period shadow bootstrap."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.calibration_endurance import (
    ENDURANCE_FILENAME,
    refresh_calibration_endurance,
)
from value_investor.knob_calibration import (
    CALIBRATION_PROVENANCE_FILENAME,
    KNOB_CALIBRATION_PRIORS_FILENAME,
    RANKING_FULL_PERIOD,
    KnobCandidate,
    KnobGridAxis,
    calibrate_track,
    fold_fitness,
    iter_grid_candidates,
    spawn_calibrated_shadow_track,
    spawn_calibration_shadow_tracks,
    walk_forward_fold_ranges,
    write_knob_calibration_priors,
)
from value_investor.knob_retrospective import (
    rank_buy_tier_forward_performers,
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
            {"ticker": "DDD.L", "signal": "buy", "conviction_score": 0.2, "price": 10},
            {"ticker": "EEE.L", "signal": "buy", "conviction_score": 0.15, "price": 10},
        ],
        "candidates": [
            {
                "ticker": "AAA.L",
                "signal": "buy",
                "conviction_score": 0.9,
                "price": 10,
                "sector": "Banks",
            },
            {
                "ticker": "BBB.L",
                "signal": "buy",
                "conviction_score": 0.8,
                "price": 10,
                "sector": "Mining",
            },
            {
                "ticker": "CCC.L",
                "signal": "buy",
                "conviction_score": 0.7,
                "price": 10,
                "sector": "Tech",
            },
            {
                "ticker": "DDD.L",
                "signal": "buy",
                "conviction_score": 0.2,
                "price": 10,
                "sector": "Retail",
            },
            {
                "ticker": "EEE.L",
                "signal": "buy",
                "conviction_score": 0.15,
                "price": 10,
                "sector": "Media",
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


def _priced_entry(day: int, prices: dict[str, float]) -> dict:
    entry = _calibration_log_entry(gate={"local_time": f"2026-08-{day:02d}T12:00:00+00:00"})
    for row in entry["screen_buy_tier"]:
        row["price"] = prices.get(row["ticker"], row["price"])
    for row in entry["candidates"]:
        row["price"] = prices.get(row["ticker"], row["price"])
    return entry


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


def test_rank_buy_tier_forward_performers_orders_winners():
    acted = [
        _priced_entry(1, {"AAA.L": 10, "BBB.L": 10, "CCC.L": 10, "DDD.L": 10, "EEE.L": 10}),
        _priced_entry(3, {"AAA.L": 12, "BBB.L": 11, "CCC.L": 10, "DDD.L": 9, "EEE.L": 8}),
        _priced_entry(5, {"AAA.L": 14, "BBB.L": 12, "CCC.L": 10, "DDD.L": 8, "EEE.L": 6}),
    ]
    ranked = rank_buy_tier_forward_performers(acted, top_k=2, bottom_k=2)
    assert ranked["top_performers"][0] == "AAA.L"
    assert set(ranked["bottom_performers"]) == {"DDD.L", "EEE.L"}


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
    assert result["bootstrap_priors"]
    assert result["recommended_prior"] is not None
    assert result["recommended_prior"]["knobs"]["max_positions"] in {3, 4}


def test_full_period_retrospective_prefers_higher_conviction_floor(tmp_path: Path):
    track = tmp_path / "rules"
    track.mkdir()
    config = AutomationConfig()
    config.track_id = "rules"
    config.max_positions = 5
    config.min_conviction = 0.0
    config.sector_cap = 1.0
    (track / "config.json").write_text(json.dumps(config.to_dict()), encoding="utf-8")
    (track / "automated_fund.json").write_text(
        json.dumps(
            {
                "config": {
                    "name": "Rules",
                    "mode": "automated",
                    "initial_cash": 1000.0,
                    "trade_cost_pct": 0.0,
                    "max_positions": 5,
                },
                "cash": 1000.0,
                "holdings": {},
                "trades": [],
                "equity_curve": [],
                "rebalance_state": {"exit_streak": {}, "reentry_cooldown": {}},
            }
        ),
        encoding="utf-8",
    )

    price_path = [
        {"AAA.L": 10, "BBB.L": 10, "CCC.L": 10, "DDD.L": 10, "EEE.L": 10},
        {"AAA.L": 12, "BBB.L": 11, "CCC.L": 10.5, "DDD.L": 9, "EEE.L": 8},
        {"AAA.L": 14, "BBB.L": 12, "CCC.L": 11, "DDD.L": 8, "EEE.L": 7},
        {"AAA.L": 16, "BBB.L": 13, "CCC.L": 11.5, "DDD.L": 7, "EEE.L": 6},
        {"AAA.L": 18, "BBB.L": 14, "CCC.L": 12, "DDD.L": 6, "EEE.L": 5},
        {"AAA.L": 20, "BBB.L": 15, "CCC.L": 12.5, "DDD.L": 5, "EEE.L": 4},
        {"AAA.L": 22, "BBB.L": 16, "CCC.L": 13, "DDD.L": 4, "EEE.L": 3},
        {"AAA.L": 24, "BBB.L": 17, "CCC.L": 13.5, "DDD.L": 3, "EEE.L": 2},
    ]
    for day, prices in enumerate(price_path, start=1):
        append_rebalance_log(track, _priced_entry(day, prices))

    axes = (
        KnobGridAxis("max_positions", (5,)),
        KnobGridAxis("min_conviction", (0.0, 0.65)),
        KnobGridAxis("sector_cap", (1.0,)),
        KnobGridAxis("skip_timing_wait", (True,)),
    )
    result = calibrate_track(
        track,
        axes=axes,
        n_folds=3,
        ranking_mode=RANKING_FULL_PERIOD,
        use_cohort_fitness=False,
        bootstrap_top_n=2,
        winner_loser_top_k=2,
        winner_loser_bottom_k=2,
    )
    assert result["ranking_mode"] == RANKING_FULL_PERIOD
    assert result["candidates_ranked"]
    assert len(result["bootstrap_priors"]) == 2
    top = result["candidates_ranked"][0]
    assert top["winner_loser"] is not None
    assert "full_period_retrospective" in top
    # High conviction floor should avoid weak DDD/EEE losers.
    assert top["knobs"]["min_conviction"] >= 0.65
    assert (result["readiness"].get("score_gap_vs_runner_up") or 0) > 0


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


def _seed_ai_judgment_parent(tmp_path: Path, *, with_bootstrap: bool = False) -> Path:
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
    (paper_root / "config.json").write_text(
        json.dumps(AutomationConfig().to_dict()), encoding="utf-8"
    )
    priors = {
        "scope": "knob_calibration_multi",
        "calibrated_at": "2026-08-18T00:00:00+00:00",
        "tracks": {
            "ai_judgment": {
                "ranking_mode": RANKING_FULL_PERIOD,
                "readiness": {
                    "ready_for_shadow_bootstrap": True,
                    "acted_entries": 12,
                    "score_gap_vs_runner_up": 0.02,
                },
                "recommended_prior": {
                    "rank": 1,
                    "knobs": {
                        "max_positions": 5,
                        "skip_timing_wait": True,
                        "min_conviction": 0.0,
                        "sector_cap": 0.2,
                    },
                    "confidence": "low",
                    "full_period_score": 0.12,
                },
            }
        },
    }
    if with_bootstrap:
        priors["tracks"]["ai_judgment"]["bootstrap_priors"] = [
            {
                "rank": 1,
                "knobs": {
                    "max_positions": 5,
                    "skip_timing_wait": True,
                    "min_conviction": 0.0,
                    "sector_cap": 0.2,
                },
                "confidence": "medium",
                "full_period_score": 0.12,
                "shadow_track_id": "ai_judgment_calibrated",
            },
            {
                "rank": 2,
                "knobs": {
                    "max_positions": 4,
                    "skip_timing_wait": True,
                    "min_conviction": 0.15,
                    "sector_cap": 0.25,
                },
                "confidence": "low",
                "full_period_score": 0.08,
                "shadow_track_id": "ai_judgment_calibrated_r2",
            },
            {
                "rank": 3,
                "knobs": {
                    "max_positions": 3,
                    "skip_timing_wait": True,
                    "min_conviction": 0.25,
                    "sector_cap": 0.3,
                },
                "confidence": "low",
                "full_period_score": 0.05,
                "shadow_track_id": "ai_judgment_calibrated_r3",
            },
        ]
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


def test_spawn_competing_shadow_tracks(tmp_path: Path):
    paper_root = _seed_ai_judgment_parent(tmp_path, with_bootstrap=True)
    result = spawn_calibration_shadow_tracks(paper_root, top_n=3)
    assert result["spawned"] is True
    assert len(result["shadows"]) == 3
    dirs = learning_track_dirs(paper_root)
    assert "ai_judgment_calibrated" in dirs
    assert "ai_judgment_calibrated_r2" in dirs
    assert "ai_judgment_calibrated_r3" in dirs
    cfg_r2 = json.loads(
        (paper_root / "ai_judgment_calibrated_r2" / "config.json").read_text(encoding="utf-8")
    )
    assert cfg_r2["is_calibration_shadow"] is True
    assert cfg_r2["max_positions"] == 4
    assert cfg_r2["min_conviction"] == 0.15


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


def test_endurance_ledger_lists_competing_shadows(tmp_path: Path):
    paper_root = _seed_ai_judgment_parent(tmp_path, with_bootstrap=True)
    spawn_calibration_shadow_tracks(paper_root, top_n=3)
    # Seed fake decision_review metrics on rank-1 shadow.
    shadow = paper_root / "ai_judgment_calibrated"
    (shadow / "decision_review.json").write_text(
        json.dumps(
            {
                "metrics": {
                    "total_return": 0.05,
                    "cost_drag": 0.01,
                    "excess_after_costs": 0.02,
                    "equity_marks": 6,
                    "trade_count": 3,
                }
            }
        ),
        encoding="utf-8",
    )
    (paper_root / "ai_judgment" / "decision_review.json").write_text(
        json.dumps(
            {
                "metrics": {
                    "total_return": 0.01,
                    "excess_after_costs": 0.0,
                    "equity_marks": 6,
                    "trade_count": 2,
                }
            }
        ),
        encoding="utf-8",
    )
    (paper_root / "decision_review.json").write_text(
        json.dumps(
            {
                "metrics": {
                    "total_return": -0.01,
                    "excess_after_costs": -0.02,
                    "equity_marks": 6,
                    "trade_count": 2,
                }
            }
        ),
        encoding="utf-8",
    )
    payload = refresh_calibration_endurance(paper_root)
    assert payload["observe_only"] is True
    assert (paper_root / ENDURANCE_FILENAME).exists()
    assert len(payload["shadows"]) == 3
    rank1 = next(row for row in payload["shadows"] if row["rank"] == 1)
    assert rank1["status"] == "surviving"
    assert payload["survivors"]
