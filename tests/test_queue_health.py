"""Tests for queue health dashboard snapshot."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.queue_health import build_queue_health_snapshot, refresh_queue_health_ui
from value_investor.storage import write_json


def _write_tasks(path: Path, payload: dict) -> None:
    write_json(path, payload, compact=False)


def test_build_queue_health_idle_snapshot(tmp_path: Path, monkeypatch):
    tasks_path = tmp_path / "engineering_tasks.json"
    _write_tasks(tasks_path, {"tasks": []})
    ops_path = tmp_path / "ops_status.json"
    write_json(
        ops_path,
        {
            "run_at": "2026-09-10T12:00:00+00:00",
            "overall": "ok",
            "should_dispatch_engineering": False,
        },
    )
    monkeypatch.setattr(
        "value_investor.queue_health.COMMITTED_TASKS_PATH",
        tasks_path,
    )
    snapshot = build_queue_health_snapshot(
        tasks_path=tasks_path,
        ops_status_path=ops_path,
        open_prs=[],
    )
    assert snapshot["overall"] == "idle"
    assert snapshot["merge_lane"]["state"] == "idle"
    assert snapshot["agent_lane"]["state"] == "idle"


def test_build_queue_health_blocked_agent_lane(tmp_path: Path, monkeypatch):
    tasks_path = tmp_path / "engineering_tasks.json"
    _write_tasks(
        tasks_path,
        {
            "tasks": [
                {
                    "id": "eng-20260910-99",
                    "status": "open",
                    "priority_score": 10.0,
                    "allowed_paths": ["src/value_investor/research/filings.py"],
                    "title": "blocked hunter",
                }
            ],
            "queue_clearing": {
                "pause_active": True,
                "attention_parked_count": 8,
            },
        },
    )
    ops_path = tmp_path / "ops_status.json"
    write_json(ops_path, {"run_at": "2026-09-10T12:00:00+00:00", "overall": "warn"})
    snapshot = build_queue_health_snapshot(
        tasks_path=tasks_path,
        ops_status_path=ops_path,
        open_prs=[],
    )
    assert snapshot["agent_lane"]["blocked"] is True
    assert snapshot["agent_lane"]["pause_active"] is True
    assert snapshot["overall"] == "blocked"


def test_refresh_queue_health_writes_sidecar(tmp_path: Path, monkeypatch):
    tasks_path = tmp_path / "engineering_tasks.json"
    _write_tasks(tasks_path, {"tasks": []})
    automation_path = tmp_path / "automation.json"
    write_json(automation_path, {"settings": {}})
    health_path = tmp_path / "queue_health.json"
    ops_path = tmp_path / "ops_status.json"
    write_json(ops_path, {"run_at": "2026-09-10T12:00:00+00:00", "overall": "ok"})

    result = refresh_queue_health_ui(
        automation_path=automation_path,
        latest_path=tmp_path / "missing.json",
        queue_health_path=health_path,
        tasks_path=tasks_path,
        ops_status_path=ops_path,
        open_prs=[],
    )
    assert result["overall"] == "idle"
    payload = json.loads(health_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    auto = json.loads(automation_path.read_text(encoding="utf-8"))
    assert auto["queue_health"]["overall"] == "idle"
