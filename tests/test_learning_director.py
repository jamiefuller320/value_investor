"""Tests for weekly Learning Director synthesis."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.learning_director import (
    build_learning_director_payload,
    compile_learning_director_tasks,
    has_enough_learning_director_inputs,
    parse_learning_director_review,
)
from value_investor.learning_director_regime import (
    build_experiment_inventory,
    build_regime_summary,
)
from value_investor.review_policy import learning_director_enabled, load_review_policy


def test_parse_learning_director_review_sections():
    text = """REGIME & ASSUMPTION CHECK
Exclusion alpha holds over full sample.

CONVERGENCE
Bottom filter and top pick diverge on 3-pos book.

COMPLEXITY & EXPERIMENT INVENTORY
3 open experiments; within budget.

VISION ROADMAP REVIEW
- regime_slices_8_16_24: HOLD — history_run_count < 16

PROPOSED ACTIONS
1. [universe] Persist weekly exclusion metrics — enable rolling slices

DEFER
- filtered_cohort_track until u4 stable 4 weeks
"""
    review = parse_learning_director_review(text)
    assert "Exclusion alpha" in review.regime_assumption_check
    assert "diverge" in review.convergence
    assert "regime_slices" in review.vision_roadmap_review
    assert "[universe]" in review.proposed_actions


def test_build_payload_includes_vision_and_regime(tmp_path: Path):
    data_dir = tmp_path / "docs" / "data"
    paper = data_dir / "paper_automation"
    paper.mkdir(parents=True)
    vision = {
        "schema_version": 1,
        "phases": [{"id": "v1_weekly_director", "status": "active"}],
        "complexity_budget": {"max_parallel_open_experiments": 5},
        "guardrails": {"observe_only": True},
    }
    (data_dir / "learning_director_vision.json").write_text(
        json.dumps(vision),
        encoding="utf-8",
    )
    (data_dir / "analysis_review.json").write_text(
        json.dumps({"reviewed_at": "2026-08-23T00:00:00+00:00", "sections": {}}),
        encoding="utf-8",
    )
    (data_dir / "exclusion_universe_review.json").write_text(
        json.dumps(
            {
                "recommended_step": {"step_id": "u4"},
                "ladder_results": [
                    {
                        "step_id": "u4",
                        "summary": {"cumulative_exclusion_alpha": 0.0053},
                        "hindsight_summary": {"mean_bottom_quartile_exclude_rate": 0.45},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (paper / "learning_tracks_review.json").write_text(
        json.dumps({"beat_market": False, "primary_excess_after_costs": -0.1}),
        encoding="utf-8",
    )
    payload = build_learning_director_payload(
        data_dir=data_dir,
        output_dir=tmp_path / "output",
        vision_path=data_dir / "learning_director_vision.json",
    )
    ok, _ = has_enough_learning_director_inputs(payload)
    assert ok is True
    assert payload["vision"]["phases"][0]["id"] == "v1_weekly_director"
    assert payload["regime_summary"]["recommended_exclusion_step"] == "u4"
    assert "primary_underperforming_market" in payload["regime_summary"]["flags"]


def test_build_experiment_inventory_counts_open_tasks(tmp_path: Path):
    data_dir = tmp_path / "docs" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "analysis_tasks.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {"id": "a1", "status": "proposed", "title": "t1"},
                    {"id": "a2", "status": "done", "title": "t2"},
                ]
            }
        ),
        encoding="utf-8",
    )
    inventory = build_experiment_inventory(data_dir)
    assert inventory["open_experiment_count"] == 1
    assert inventory["buckets"]["analysis_tasks"] == 1


def test_compile_learning_director_tasks_filters_areas(tmp_path: Path):
    review = parse_learning_director_review(
        "PROPOSED ACTIONS\n"
        "1. [universe] Persist weekly exclusion series — rolling slices\n"
        "2. [scoring] Change assign_signal — not allowed here\n"
    )
    tasks_path = tmp_path / "learning_director_tasks.json"
    compiled = compile_learning_director_tasks(review, run_stamp="20260823", tasks_path=tasks_path)
    assert compiled["task_count"] == 1
    assert compiled["tasks"][0]["area"] == "universe"
    assert compiled["tasks"][0]["source"] == "learning_director"


def test_regime_summary_flags_thin_history(tmp_path: Path):
    data_dir = tmp_path / "docs" / "data"
    data_dir.mkdir(parents=True)
    summary = build_regime_summary(data_dir, history_run_count=3)
    assert "thin_history:<8_archive_runs" in summary["flags"]


def test_review_policy_learning_director_defaults_enabled(tmp_path: Path):
    policy_path = tmp_path / "review_policy.json"
    policy = load_review_policy(policy_path)
    assert learning_director_enabled(policy_path) is True
    assert policy["learning_director"]["enabled"] is True
