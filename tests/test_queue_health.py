"""Tests for queue health dashboard snapshot."""

from __future__ import annotations

import json
from datetime import UTC, datetime
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
    assert snapshot.get("library_stall_parks") == []


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


def test_queue_health_embeds_n200_pipeline_health(tmp_path: Path, monkeypatch):
    tasks_path = tmp_path / "engineering_tasks.json"
    _write_tasks(tasks_path, {"tasks": []})
    ops_path = tmp_path / "ops_status.json"
    write_json(
        ops_path,
        {
            "run_at": "2026-10-11T12:30:00+00:00",
            "overall": "ok",
            "findings": [{"title": "N200 tech-timing observe refreshed"}],
        },
    )
    write_json(
        tmp_path / "n200_tech_timing_observe.json",
        {
            "registration_id": "strand-b-plain-value-tech-timing-v0",
            "generated_at": "2026-10-11T12:00:00+00:00",
            "completed_entry_episodes": 40,
            "calendar_weeks_spanned": 9,
            "phase": {"entries_per_week": 6.0, "floor": 5.0, "floor_met": True},
            "volume_gate": {"met": True, "min_episodes": 24, "min_weeks": 8},
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
        now=datetime(2026, 10, 11, 13, 0, tzinfo=UTC),
    )
    n200 = snapshot["n200_pipeline_health"]
    assert n200["phase"]["floor_met"] is True
    assert n200["volume_gate"]["met"] is True
    assert n200["not_capital_ready"] is True
    assert n200["pipeline"]["functioning"] is True
