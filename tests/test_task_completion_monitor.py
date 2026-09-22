"""Tests for task / PR completion monitor aggregation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from value_investor.pr_fix_occasions import record_pr_fix_occasion
from value_investor.queue_health import build_queue_health_snapshot
from value_investor.storage import write_json
from value_investor.task_completion_monitor import build_task_completion_monitor


def test_build_task_completion_monitor_today_yesterday_and_history(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    fix_path = tmp_path / "pr_fix_occasions.json"
    now = datetime(2026, 9, 22, 15, 0, tzinfo=UTC)
    write_json(
        tasks_path,
        {
            "tasks": [
                {
                    "id": "eng-today-auto",
                    "status": "merged",
                    "title": "auto today",
                    "merged_at": "2026-09-22T10:00:00+00:00",
                    "auto_merge": True,
                    "pr_number": 1,
                    "evidence": {"merge_class": "ingest_narrow"},
                },
                {
                    "id": "eng-today-manual",
                    "status": "merged",
                    "title": "manual today",
                    "merged_at": "2026-09-22T11:00:00+00:00",
                    "auto_merge": False,
                    "pr_number": 2,
                    "evidence": {"merge_class": "human"},
                },
                {
                    "id": "eng-yest-manual",
                    "status": "merged",
                    "title": "manual yesterday",
                    "merged_at": "2026-09-21T09:00:00+00:00",
                    "auto_merge": False,
                    "pr_number": 3,
                },
                {
                    "id": "eng-older-auto",
                    "status": "merged",
                    "title": "older auto",
                    "merged_at": "2026-09-15T09:00:00+00:00",
                    "auto_merge": True,
                    "pr_number": 4,
                    "evidence": {"merge_class": "ci_fix"},
                },
            ]
        },
        compact=False,
    )
    record_pr_fix_occasion(
        source="human_request",
        kind="ci_check",
        failure_reason="pytest",
        pr_number=10,
        path=fix_path,
        apply=True,
        now=datetime(2026, 9, 22, 12, 0, tzinfo=UTC),
    )
    record_pr_fix_occasion(
        source="traffic_controller",
        kind="merge_conflict",
        failure_reason="conflict",
        pr_number=11,
        path=fix_path,
        apply=True,
        now=datetime(2026, 9, 21, 12, 0, tzinfo=UTC),
    )
    record_pr_fix_occasion(
        source="traffic_controller",
        kind="merge_conflict",
        failure_reason="conflict2",
        pr_number=12,
        path=fix_path,
        apply=True,
        now=datetime(2026, 9, 21, 13, 0, tzinfo=UTC),
    )

    monitor = build_task_completion_monitor(
        tasks_path=tasks_path,
        pr_fix_path=fix_path,
        days=14,
        now=now,
    )
    assert monitor["today"]["date"] == "2026-09-22"
    assert monitor["today"]["merged_total"] == 2
    assert monitor["today"]["merged_auto"] == 1
    assert monitor["today"]["merged_manual"] == 1
    assert monitor["today"]["verified"] == 1
    assert monitor["today"]["fix_interventions"] == 1
    assert monitor["today"]["fix_ci_check"] == 1

    assert monitor["yesterday"]["date"] == "2026-09-21"
    assert monitor["yesterday"]["merged_total"] == 1
    assert monitor["yesterday"]["merged_manual"] == 1
    assert monitor["yesterday"]["fix_interventions"] == 2
    assert monitor["yesterday"]["fix_merge_conflict"] == 2

    assert len(monitor["history"]) == 14
    by_day = {row["date"]: row for row in monitor["history"]}
    assert by_day["2026-09-15"]["merged_auto"] == 1
    assert by_day["2026-09-20"]["merged_total"] == 0
    assert len(monitor["merges_today"]) == 2
    assert len(monitor["merges_yesterday"]) == 1


def test_queue_health_includes_completion_monitor(tmp_path: Path, monkeypatch):
    tasks_path = tmp_path / "engineering_tasks.json"
    write_json(tasks_path, {"tasks": []}, compact=False)
    ops_path = tmp_path / "ops_status.json"
    write_json(ops_path, {"run_at": "2026-09-22T12:00:00+00:00", "overall": "ok"})
    fix_path = tmp_path / "pr_fix.json"
    write_json(fix_path, {"occasions": []}, compact=False)
    monkeypatch.setattr(
        "value_investor.queue_health.COMMITTED_TASKS_PATH",
        tasks_path,
    )
    now = datetime(2026, 9, 22, 16, 0, tzinfo=UTC)
    snapshot = build_queue_health_snapshot(
        tasks_path=tasks_path,
        ops_status_path=ops_path,
        open_prs=[],
        pr_fix_path=fix_path,
        now=now,
    )
    assert "completion_monitor" in snapshot
    assert snapshot["completion_monitor"]["today"]["date"] == "2026-09-22"
    assert snapshot["completion_monitor"]["yesterday"]["date"] == "2026-09-21"
    assert len(snapshot["completion_monitor"]["history"]) == 14
