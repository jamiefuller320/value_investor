"""Tests for unified experiment assessment ledger."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.calibration_endurance import refresh_calibration_endurance
from value_investor.experiment_assessment import (
    map_endurance_status_to_assessment,
    refresh_experiment_assessment,
    slim_experiment_assessment_for_review,
    sync_task_assessment_status,
)


def test_map_endurance_status_to_assessment():
    assert map_endurance_status_to_assessment("failed", gate_marks=6, min_marks=4) == "fail"
    assert map_endurance_status_to_assessment("surviving", gate_marks=6, min_marks=4) == "recommend"
    assert map_endurance_status_to_assessment("observing", gate_marks=6, min_marks=4) == "continue"
    assert map_endurance_status_to_assessment("observing", gate_marks=2, min_marks=4) == "observing"


def test_refresh_experiment_assessment_includes_shadows_and_tasks(tmp_path: Path):
    data_dir = tmp_path / "data"
    paper_root = data_dir / "paper_automation"
    shadow = paper_root / "ai_judgment_calibrated"
    shadow.mkdir(parents=True)
    (paper_root / "ai_judgment").mkdir(parents=True)
    (paper_root / "rules").mkdir(parents=True)
    (shadow / "decision_review.json").write_text(
        json.dumps(
            {
                "metrics": {
                    "total_return": 0.05,
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
                }
            }
        ),
        encoding="utf-8",
    )
    (paper_root / "rules" / "decision_review.json").write_text(
        json.dumps(
            {
                "metrics": {
                    "total_return": -0.01,
                    "excess_after_costs": -0.02,
                    "equity_marks": 6,
                }
            }
        ),
        encoding="utf-8",
    )
    (shadow / "calibration_provenance.json").write_text(
        json.dumps({"spawned_at": "2026-08-01T00:00:00+00:00", "shadow_knobs": {}}),
        encoding="utf-8",
    )
    (shadow / "config.json").write_text(
        json.dumps(
            {
                "track_id": "ai_judgment_calibrated",
                "is_calibration_shadow": True,
                "calibration_parent_track": "ai_judgment",
            }
        ),
        encoding="utf-8",
    )
    refresh_calibration_endurance(paper_root)

    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "analysis_tasks.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "ana-20260824-01",
                        "area": "scoring",
                        "title": "Test scoring experiment",
                        "status": "proposed",
                        "promote_to": "engineering_queue",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "trajectory_evidence_review.json").write_text(
        json.dumps(
            {
                "outcome_summary": {"labeled_event_count": 50},
                "model_focus_candidates": [
                    {
                        "kind": "transition_key",
                        "key": "hold->buy",
                        "count": 25,
                        "why": "weak hit rate",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = refresh_experiment_assessment(data_dir, paper_root=paper_root)
    assert (data_dir / "experiment_assessment.json").exists()
    assert payload["observe_only"] is True
    kinds = {row["kind"] for row in payload["experiments"]}
    assert "calibration_shadow" in kinds
    assert "analysis_task" in kinds
    shadow_row = next(row for row in payload["experiments"] if row["kind"] == "calibration_shadow")
    assert shadow_row["status"] in {"continue", "recommend", "observing", "fail"}
    task_row = next(row for row in payload["experiments"] if row["kind"] == "analysis_task")
    assert task_row["status"] == "recommend"
    assert task_row["forward_evidence"]["trajectory"]["labeled_event_count"] == 50
    assert payload["schema_version"] == 2

    slim = slim_experiment_assessment_for_review(payload)
    assert slim is not None
    assert slim["summary"]["total"] == len(payload["experiments"])


def test_sync_task_assessment_status_flags_recommend(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    tasks_path = data_dir / "analysis_tasks.json"
    tasks_path.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "ana-test-01",
                        "area": "scoring",
                        "title": "Scoring tweak",
                        "status": "proposed",
                        "evidence": {},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    experiments = [
        {
            "experiment_id": "ana-test-01",
            "kind": "analysis_task",
            "status": "recommend",
            "forward_evidence": {"trajectory": {"labeled_event_count": 40}},
        }
    ]
    result = sync_task_assessment_status(experiments, data_dir)
    assert "ana-test-01" in result["updated"]
    saved = json.loads(tasks_path.read_text(encoding="utf-8"))
    task = saved["tasks"][0]
    assert task["status"] == "proposed"
    assert task["evidence"]["assessment_recommend"] is True
    assert task["evidence"]["assessment_status"] == "recommend"
