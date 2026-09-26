"""Tests for human-task acks and board sort / enrichment."""

from __future__ import annotations

from pathlib import Path

from value_investor.human_task_ack import run_human_task_ack
from value_investor.human_task_acks import load_human_task_acks, record_human_task_ack
from value_investor.human_task_cards import APPROVAL_GATE_IDS, build_human_tasks_board
from value_investor.human_tasks_checklist import load_human_tasks_checklist
from value_investor.storage import write_json


def test_board_sorts_new_info_before_acked(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    # Minimal analysis artifacts so fingerprints differ
    write_json(
        data_dir / "experiment_assessment.json",
        {
            "generated_at": "2026-09-26T12:00:00+00:00",
            "experiments": [{"experiment_id": "u4", "status": "recommend"}],
        },
    )
    write_json(
        data_dir / "engineering_tasks.json",
        {
            "updated_at": "2026-09-26T11:00:00+00:00",
            "tasks": [
                {
                    "id": "eng-old",
                    "status": "parked",
                    "title": "Old park",
                    "parked_at": "2026-09-01T00:00:00+00:00",
                }
            ],
            "traffic_control": {"pause_active": False},
        },
    )
    # Copy checklist path is default — board loads from repo checklist
    board = build_human_tasks_board(data_dir=data_dir)
    human = board["tasks"]
    assert human
    assert all(not row["automated"] for row in human)
    # Ack one task with matching fingerprint → goes to acked bucket
    target = next(row for row in human if row["id"] == "sunday-promote-knobs-gate")
    fp = target["analysis"]["fingerprint"]
    record_human_task_ack(
        data_dir,
        task_id="sunday-promote-knobs-gate",
        decision="ack_observe",
        finding_fingerprint=fp,
    )
    board2 = build_human_tasks_board(data_dir=data_dir)
    buckets = [row["sort_bucket"] for row in board2["tasks"]]
    assert "acked" in buckets
    acked_ids = [row["id"] for row in board2["tasks"] if row["sort_bucket"] == "acked"]
    assert acked_ids[-1] == "sunday-promote-knobs-gate" or "sunday-promote-knobs-gate" in acked_ids
    # Last group should be acked
    assert board2["tasks"][-1]["sort_bucket"] == "acked"

    # Stale fingerprint → new_info rises
    record_human_task_ack(
        data_dir,
        task_id="sunday-promote-knobs-gate",
        decision="ack_observe",
        finding_fingerprint="stale-old-fp",
    )
    board3 = build_human_tasks_board(data_dir=data_dir)
    promote = next(row for row in board3["tasks"] if row["id"] == "sunday-promote-knobs-gate")
    assert promote["sort_bucket"] == "new_info"
    assert board3["tasks"][0]["sort_bucket"] in {"new_info", "unacked"}
    assert promote["ack"]["stale"] is True


def test_approval_gates_cover_promotion_ids():
    assert "sunday-promote-knobs-gate" in APPROVAL_GATE_IDS
    assert "adhoc-live-capital-pack" in APPROVAL_GATE_IDS
    board = build_human_tasks_board(data_dir=Path("docs/data"))
    promote = next(row for row in board["tasks"] if row["id"] == "sunday-promote-knobs-gate")
    assert promote["approval_gate"] is True


def test_run_human_task_ack_writes_store(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    write_json(
        data_dir / "analysis_review.json",
        {"generated_at": "2026-09-26T10:00:00+00:00", "summary": "ok"},
    )
    result = run_human_task_ack(
        data_dir,
        task_id="sunday-read-analysis-review",
        decision="ack_observe",
        source="test",
    )
    assert result["ok"] is True
    store = load_human_task_acks(data_dir)
    assert any(row.get("task_id") == "sunday-read-analysis-review" for row in store["acks"])
    assert (data_dir / "human_tasks_board.json").is_file()


def test_euro_ingest_cron_reimport_is_automated():
    payload = load_human_tasks_checklist()
    tasks = [task for section in payload["sections"] for task in section["tasks"]]
    row = next(task for task in tasks if task["id"] == "adhoc-euro-ingest-cron-reimport")
    assert row["automated"] is True
    assert "import-ingest-crons" in row["summary"]


def test_checklist_human_count_matches_board():
    checklist = load_human_tasks_checklist()
    human_ids = {
        task["id"]
        for section in checklist["sections"]
        for task in section["tasks"]
        if not task.get("automated")
    }
    board = build_human_tasks_board(data_dir=Path("docs/data"))
    board_ids = {row["id"] for row in board["tasks"]}
    assert board_ids == human_ids
