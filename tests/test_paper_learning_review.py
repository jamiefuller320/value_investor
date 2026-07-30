"""Tests for optional paper learning churn review."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.paper_learning_review import (
    build_paper_learning_payload,
    compile_paper_learning_tasks,
    has_enough_paper_learning_inputs,
    parse_paper_learning_review,
)
from value_investor.review_policy import load_review_policy, paper_learning_review_enabled


def test_parse_paper_learning_review_sections():
    text = """CHURN SUMMARY
Cost drag easing on rules track.

PER-TRACK DIAGNOSIS
- rules: cost_drag 8%

PROPOSED EXPERIMENTS
1. [paper_churn] Raise exit_confirm_screens to 3 — fewer flicker exits

DEFER
- Live capital automation
"""
    review = parse_paper_learning_review(text)
    assert "easing" in review.churn_summary
    assert "rules" in review.per_track_diagnosis
    assert "[paper_churn]" in review.proposed_experiments


def test_build_payload_includes_churn_health(tmp_path: Path):
    data_dir = tmp_path / "docs" / "data"
    paper = data_dir / "paper_automation"
    paper.mkdir(parents=True)
    (paper / "review_policy.json").write_text(
        json.dumps({"paper_learning_review": {"enabled": True}}),
        encoding="utf-8",
    )
    (paper / "learning_tracks_churn_health.json").write_text(
        json.dumps({"tracks": {"rules": {"decision_review": {"cost_drag": 0.05}}}}),
        encoding="utf-8",
    )
    payload = build_paper_learning_payload(data_dir=data_dir, output_dir=tmp_path / "output")
    ok, _ = has_enough_paper_learning_inputs(payload)
    assert ok is True
    assert payload["churn_health"]["tracks"]["rules"]["decision_review"]["cost_drag"] == 0.05


def test_compile_paper_learning_tasks_filters_areas(tmp_path: Path):
    review = parse_paper_learning_review(
        "PROPOSED EXPERIMENTS\n"
        "1. [paper_churn] Tune hold buffer — less churn\n"
        "2. [scoring] Change assign_signal — not allowed here\n"
    )
    tasks_path = tmp_path / "paper_learning_tasks.json"
    compiled = compile_paper_learning_tasks(review, run_stamp="20260730", tasks_path=tasks_path)
    assert compiled["task_count"] == 1
    assert compiled["tasks"][0]["area"] == "paper_churn"
    assert compiled["tasks"][0]["promote_to"] == "manual"


def test_review_policy_defaults_enabled(tmp_path: Path):
    policy_path = tmp_path / "review_policy.json"
    policy = load_review_policy(policy_path)
    assert paper_learning_review_enabled(policy_path) is True
    assert policy["paper_learning_review"]["enabled"] is True
