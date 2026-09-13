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
    assert "lifecycle_overlay" in kinds
    dca_row = next(
        row for row in payload["experiments"] if row["experiment_id"] == "entry_dca_overlay"
    )
    assert dca_row["status"] == "observing"
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


def test_refresh_skips_done_analysis_tasks(tmp_path: Path):
    data_dir = tmp_path / "data"
    paper_root = data_dir / "paper_automation"
    paper_root.mkdir(parents=True)
    (data_dir / "analysis_tasks.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "ana-20260728-01",
                        "area": "offline_sim",
                        "title": "Seed second weekly run",
                        "status": "done",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    payload = refresh_experiment_assessment(data_dir, paper_root=paper_root)
    ids = [row["experiment_id"] for row in payload["experiments"]]
    assert "ana-20260728-01" not in ids


def test_refresh_watch_disposition_is_not_recommend(tmp_path: Path):
    data_dir = tmp_path / "data"
    paper_root = data_dir / "paper_automation"
    paper_root.mkdir(parents=True)
    (data_dir / "learning_director_tasks.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "ldr-20260823-02",
                        "area": "monitoring",
                        "title": "Watch exclusion u4",
                        "status": "accepted",
                        "evidence": {
                            "human_disposition": "watch",
                            "assessment_recommend": True,
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (paper_root / "learning_tracks_exit_shadow.json").write_text(
        json.dumps({"tracks": {}, "readiness": {"ready_for_probability_analysis": True}}),
        encoding="utf-8",
    )
    payload = refresh_experiment_assessment(data_dir, paper_root=paper_root, sync_task_status=True)
    row = next(r for r in payload["experiments"] if r["experiment_id"] == "ldr-20260823-02")
    assert row["status"] == "continue"
    assert row["human_ack_required"] is False
    assert row["experiment_id"] not in {r["experiment_id"] for r in payload["recommendations"]}
    synced = json.loads((data_dir / "learning_director_tasks.json").read_text())["tasks"][0]
    assert synced["evidence"]["assessment_status"] == "continue"
    assert "assessment_recommend" not in synced["evidence"]


def test_refresh_skips_cancelled_analysis_tasks(tmp_path: Path):
    data_dir = tmp_path / "data"
    paper_root = data_dir / "paper_automation"
    paper_root.mkdir(parents=True)
    (data_dir / "analysis_tasks.json").write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "ana-20260728-02",
                        "area": "paper_knobs",
                        "title": "Pre vs post knob counterfactual",
                        "status": "cancelled",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    payload = refresh_experiment_assessment(data_dir, paper_root=paper_root)
    ids = [row["experiment_id"] for row in payload["experiments"]]
    assert "ana-20260728-02" not in ids


def _write_ready_dca_rollup(paper_root: Path, *, ai_first: int = 1, rules_first: int = 0) -> None:
    paper_root.mkdir(parents=True, exist_ok=True)
    (paper_root / "learning_tracks_entry_dca.json").write_text(
        json.dumps(
            {
                "scored_count": 22,
                "tracks_with_closed": 9,
                "leading_cadence": "dca_4x_weekly",
                "model_independent_hint": True,
                "readiness": {"ready_for_cadence_analysis": True},
                "tracks": {
                    "ai_judgment": {
                        "scored_count": ai_first,
                        "entry_kind_counts": {"first_entry": ai_first, "recommit": 3},
                        "winning_cadence_counts": {"dca_4x_weekly": 1},
                    },
                    "rules": {
                        "scored_count": 0,
                        "entry_kind_counts": {"first_entry": rules_first, "recommit": 4},
                        "winning_cadence_counts": {},
                    },
                    "ai_judgment_fair": {
                        "scored_count": 1,
                        "entry_kind_counts": {"first_entry": 1, "recommit": 0},
                        "winning_cadence_counts": {"dca_4x_weekly": 1},
                    },
                    "rules_fair": {
                        "scored_count": 1,
                        "entry_kind_counts": {"first_entry": 1, "recommit": 0},
                        "winning_cadence_counts": {"dca_4x_weekly": 1},
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def test_refresh_drops_acked_dca_from_recommendations(tmp_path: Path):
    from value_investor.experiment_acks import record_ack

    data_dir = tmp_path / "data"
    paper_root = data_dir / "paper_automation"
    _write_ready_dca_rollup(paper_root)
    payload = refresh_experiment_assessment(data_dir, paper_root=paper_root)
    dca = next(row for row in payload["experiments"] if row["experiment_id"] == "entry_dca_overlay")
    assert dca["status"] == "recommend"
    assert dca["human_ack_required"] is True
    assert payload["summary"]["human_ack_pending"] == 1
    assert any(row["experiment_id"] == "entry_dca_overlay" for row in payload["recommendations"])

    record_ack(
        data_dir,
        experiment_id="entry_dca_overlay",
        decision="ack_observe",
        finding=dca["forward_evidence"],
        note="observe only",
    )
    again = refresh_experiment_assessment(data_dir, paper_root=paper_root)
    dca2 = next(row for row in again["experiments"] if row["experiment_id"] == "entry_dca_overlay")
    assert dca2["status"] == "recommend"
    assert dca2["human_ack_required"] is False
    assert dca2["human_acked"] is True
    assert again["summary"]["human_ack_pending"] == 0
    assert again["recommendations"] == []
    assert again["entry_dca_adoption"]["acked"] is True
    assert again["entry_dca_adoption"]["current_stage"] == "out_of_sample_first_entry"
    slim = slim_experiment_assessment_for_review(again)
    assert slim["recommendations"] == []
    assert slim["entry_dca_adoption"]["acked"] is True


def test_ack_cli_records_and_refreshes(tmp_path: Path):
    from value_investor.experiment_assessment_cli import main as assess_main

    data_dir = tmp_path / "data"
    paper_root = data_dir / "paper_automation"
    _write_ready_dca_rollup(paper_root)
    refresh_experiment_assessment(data_dir, paper_root=paper_root)
    rc = assess_main(
        [
            "ack",
            "--data-dir",
            str(data_dir),
            "--paper-root",
            str(paper_root),
            "--experiment-id",
            "entry_dca_overlay",
            "--note",
            "observe only",
        ]
    )
    assert rc == 0
    acks = json.loads((data_dir / "experiment_acks.json").read_text(encoding="utf-8"))
    assert acks["acks"][0]["experiment_id"] == "entry_dca_overlay"
    assert acks["acks"][0]["decision"] == "ack_observe"
    ledger = json.loads((data_dir / "experiment_assessment.json").read_text(encoding="utf-8"))
    assert ledger["summary"]["human_ack_pending"] == 0
    plan = json.loads((data_dir / "entry_dca_adoption_plan.json").read_text(encoding="utf-8"))
    assert plan["current_stage"] == "out_of_sample_first_entry"
