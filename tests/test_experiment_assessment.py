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


def test_refresh_preserves_and_sets_initiated_at(tmp_path: Path):
    data_dir = tmp_path / "data"
    paper_root = data_dir / "paper_automation"
    paper_root.mkdir(parents=True)
    prior_time = "2026-08-01T00:00:00+00:00"
    (data_dir / "experiment_assessment.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "experiments": [
                    {
                        "experiment_id": "ai_judgment_calibrated",
                        "kind": "calibration_shadow",
                        "initiated_at": prior_time,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (paper_root / "calibration_shadow_endurance.json").write_text(
        json.dumps(
            {
                "shadows": [
                    {
                        "shadow_track_id": "ai_judgment_calibrated",
                        "rank": 1,
                        "status": "observing",
                        "knobs": {},
                        "metrics": {"equity_marks": 1},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    payload = refresh_experiment_assessment(data_dir, paper_root=paper_root)
    row = next(r for r in payload["experiments"] if r["experiment_id"] == "ai_judgment_calibrated")
    assert row["initiated_at"] == prior_time



def test_ack_moves_recommend_monitoring_to_continue(tmp_path: Path):
    from value_investor.experiment_assessment import ack_experiment_tasks

    data_dir = tmp_path / "data"
    paper_root = data_dir / "paper_automation"
    paper_root.mkdir(parents=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "analysis_tasks.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "ana-ack-01",
                        "area": "monitoring",
                        "title": "Exit shadow thickness gate",
                        "status": "proposed",
                        "promote_to": "manual",
                        "evidence": {},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "learning_director_tasks.json").write_text(
        json.dumps({"tasks": []}), encoding="utf-8"
    )
    (data_dir / "paper_learning_tasks.json").write_text(
        json.dumps({"tasks": []}), encoding="utf-8"
    )
    (paper_root / "learning_tracks_exit_timing.json").write_text(
        json.dumps({"readiness": {"ready_for_probability_analysis": True}}),
        encoding="utf-8",
    )
    (paper_root / "learning_tracks_exit_shadow.json").write_text(
        json.dumps({"closed_total": 0, "tracks": {}}),
        encoding="utf-8",
    )

    before = refresh_experiment_assessment(data_dir, paper_root=paper_root)
    row = next(r for r in before["experiments"] if r["experiment_id"] == "ana-ack-01")
    assert row["status"] == "recommend"
    assert row["human_ack_required"] is True

    result = ack_experiment_tasks(
        data_dir,
        ["ana-ack-01"],
        note="Accept thickness pre-gate",
        modifications="Dual-suite: keep as A/B pre-gate; no grace knobs until thick.",
        refresh=True,
        sync_task_status=False,
    )
    assert result["updated"] == ["ana-ack-01"]
    assert "ana-ack-01" not in (result.get("recommendations") or [])

    payload = refresh_experiment_assessment(data_dir, paper_root=paper_root)
    after = next(r for r in payload["experiments"] if r["experiment_id"] == "ana-ack-01")
    assert after["status"] == "continue"
    assert after["human_ack_required"] is False
    assert after["task_status"] == "accepted"
    assert payload["summary"]["human_ack_pending"] == 0
    task = json.loads((data_dir / "analysis_tasks.json").read_text(encoding="utf-8"))["tasks"][0]
    assert task["status"] == "accepted"
    assert task["evidence"]["human_ack"]["note"] == "Accept thickness pre-gate"
