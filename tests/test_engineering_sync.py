"""Tests for engineering queue / agent synchronisation."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.engineering_sync import (
    audit_compile_drop_risk,
    resolve_dispatch_task_id,
    run_engineering_sync,
)
from value_investor.engineering_tasks import (
    EngineeringTask,
    _merge_task_rows,
)


def _task(task_id: str, *, title: str = "Build CH PDF fetch") -> EngineeringTask:
    return EngineeringTask(
        id=task_id,
        area="ingest",
        title=title,
        summary=title,
        priority="high",
        priority_score=99.0,
        source="post_run_review",
    )


def test_open_task_ids_not_dropped_after_merge_guard():
    existing = [_task("eng-20260802-02", title="Old open task").to_dict()]
    compiled = [_task("eng-20260803-01", title="Brand new compiled task")]
    merged = _merge_task_rows(existing, compiled)
    ids = {row["id"] for row in merged if row.get("status") == "open"}
    assert "eng-20260802-02" in ids
    assert "eng-20260803-01" in ids


def test_resolve_dispatch_task_id_falls_back_when_stale(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            _task("eng-20260802-02", title="Stale task").to_dict(),
            _task("eng-20260803-29", title="Current top task").to_dict(),
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")
    assert resolve_dispatch_task_id("eng-20260802-02", tasks_path=tasks_path) == "eng-20260802-02"
    payload["tasks"][0]["status"] = "merged"
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")
    assert resolve_dispatch_task_id("eng-20260802-02", tasks_path=tasks_path) == "eng-20260803-29"


def test_audit_compile_drop_risk_empty_without_artifacts(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(
        json.dumps({"tasks": [_task("eng-20260802-02").to_dict()]}), encoding="utf-8"
    )
    assert audit_compile_drop_risk(tasks_path=tasks_path, output_dir=tmp_path / "output") == []


def test_run_engineering_sync_flags_recent_failures(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(
        json.dumps({"tasks": [_task("eng-20260803-29").to_dict()]}), encoding="utf-8"
    )
    report = run_engineering_sync(
        tasks_path=tasks_path,
        recent_agent_failures=[{"id": 1, "created_at": "2026-08-03T08:00:00Z"}],
        apply=False,
    )
    assert report.recent_agent_failures == 1
    assert report.should_redispatch is True
