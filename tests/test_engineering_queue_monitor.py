"""Tests for engineering queue monitor snapshots."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from value_investor.engineering_queue_monitor import (
    append_queue_monitor_snapshot,
    build_queue_monitor_snapshot,
    load_monitor_snapshots,
    summarize_monitor_window,
)
from value_investor.engineering_tasks import EngineeringTask
from value_investor.storage import write_json


def _write_tasks(tmp_path: Path, tasks: list[EngineeringTask]) -> Path:
    path = tmp_path / "engineering_tasks.json"
    write_json(path, {"tasks": [t.to_dict() for t in tasks]}, compact=False)
    return path


def test_build_and_append_monitor_snapshot(tmp_path: Path):
    tasks_path = _write_tasks(
        tmp_path,
        [
            EngineeringTask(
                id="eng-20260101-01",
                area="ingest",
                title="Fetch bodies",
                summary="x",
                priority="high",
                priority_score=90.0,
                source="post_run_review",
                status="open",
                allowed_paths=["src/value_investor/fetch.py", "tests/test_fetch.py"],
            )
        ],
    )
    now = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
    snap = build_queue_monitor_snapshot(
        tasks_path=tasks_path,
        open_prs=[],
        agent_running_count=0,
        event_source="schedule",
        now=now,
    )
    assert snap["dispatch"]["should_dispatch"] is True
    assert snap["queue"]["open_count"] == 1
    assert snap["clash"]["dispatch_eligible_count"] >= 1

    jsonl = tmp_path / "monitor.jsonl"
    append_queue_monitor_snapshot(snap, path=jsonl, max_lines=10)
    rows = load_monitor_snapshots(path=jsonl)
    assert len(rows) == 1
    assert rows[0]["event_source"] == "schedule"


def test_summarize_monitor_window(tmp_path: Path):
    jsonl = tmp_path / "monitor.jsonl"
    base = datetime(2026, 9, 17, 10, 0, tzinfo=UTC)
    for i in range(3):
        snap = {
            "recorded_at": (base + timedelta(hours=i)).isoformat(),
            "dispatch": {"should_dispatch": i % 2 == 0, "reason": "test"},
            "queue": {"open_count": 1 if i else 0, "pr_open_count": 0},
            "clash": {"dispatch_eligible_count": 0 if i == 1 else 1},
            "pauses": {"traffic_pause_active": False},
            "github": {"open_engineering_pr_numbers": []},
        }
        append_queue_monitor_snapshot(snap, path=jsonl, max_lines=10)

    summary = summarize_monitor_window(load_monitor_snapshots(path=jsonl), hours=24.0, now=base + timedelta(hours=3))
    assert summary["snapshot_count"] == 3
    assert summary["should_dispatch_true_count"] == 2
    assert summary["eligible_zero_open_positive"] == 1
