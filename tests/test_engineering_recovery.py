"""Tests for engineering queue self-repair."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.engineering_recovery import (
    housekeep_parked_tasks,
    reconcile_merged_pr_open_tasks,
    record_agent_no_diff_run,
    recover_engineering_queue,
    retry_failed_tasks,
    summarize_parked_tasks,
    summarize_parked_tasks_needing_attention,
)
from value_investor.engineering_tasks import (
    EngineeringTask,
    load_engineering_tasks,
    mark_task_status,
)


def _task(
    task_id: str, *, status: str = "open", title: str = "Build CH PDF fetch"
) -> EngineeringTask:
    return EngineeringTask(
        id=task_id,
        area="ingest",
        title=title,
        summary=title,
        priority="high",
        priority_score=99.0,
        source="post_run_review",
        status=status,
    )


def test_retry_failed_tasks_reopens_after_cooldown(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    old = (datetime.now(UTC) - timedelta(hours=30)).isoformat()
    payload = {
        "tasks": [
            _task("eng-20260729-01", status="failed").to_dict()
            | {"failure_count": 1, "last_failed_at": old}
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")

    reopened, parked = retry_failed_tasks(tasks_path=tasks_path, apply=True, max_retries=2)
    assert reopened == ["eng-20260729-01"]
    assert parked == []
    updated = load_engineering_tasks(tasks_path)
    assert updated["tasks"][0]["status"] == "open"


def test_retry_failed_tasks_parks_when_retries_exhausted(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            _task("eng-20260729-01", status="failed").to_dict()
            | {"failure_count": 2, "last_failed_at": datetime.now(UTC).isoformat()}
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")

    reopened, parked = retry_failed_tasks(tasks_path=tasks_path, apply=True, max_retries=2)
    assert reopened == []
    assert len(parked) == 1
    updated = load_engineering_tasks(tasks_path)
    assert updated["tasks"][0]["status"] == "parked"
    assert "manual review" in str(updated["tasks"][0].get("parked_reason"))


def test_recover_engineering_queue_marks_merged_before_orphan_reset(tmp_path: Path, monkeypatch):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            _task("eng-20260812-04", status="pr_open").to_dict()
            | {"branch_name": "cursor/eng-20260812-04-1de3"},
            _task("eng-20260729-02", status="pr_open").to_dict()
            | {"branch_name": "cursor/eng-20260729-02-1de3"},
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")

    def fake_merged(branch: str, **kwargs: object) -> dict[str, Any] | None:
        if branch == "cursor/eng-20260812-04-1de3":
            return {
                "html_url": "https://github.com/jamiefuller320/value_investor/pull/260",
                "number": 260,
                "merged_at": "2026-08-12T12:34:00Z",
            }
        return None

    monkeypatch.setattr(
        "value_investor.engineering_recovery.find_merged_pull_for_branch",
        fake_merged,
    )

    result = recover_engineering_queue(tasks_path=tasks_path, open_prs=[], apply=True)
    assert result.merged == ["eng-20260812-04"]
    assert result.reconciled == ["eng-20260729-02"]
    updated = load_engineering_tasks(tasks_path)
    by_id = {row["id"]: row for row in updated["tasks"]}
    assert by_id["eng-20260812-04"]["status"] == "merged"
    assert by_id["eng-20260812-04"]["pr_number"] == 260
    assert by_id["eng-20260729-02"]["status"] == "open"


def test_reconcile_merged_restores_open_task_without_branch_name(tmp_path: Path, monkeypatch):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            _task("eng-20260812-04", status="open").to_dict(),
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(
        "value_investor.engineering_recovery.find_merged_pull_for_branch",
        lambda branch, **kwargs: (
            {
                "html_url": "https://github.com/jamiefuller320/value_investor/pull/260",
                "number": 260,
                "merged_at": "2026-08-12T12:34:00Z",
            }
            if branch == "cursor/eng-20260812-04-1de3"
            else None
        ),
    )

    merged = reconcile_merged_pr_open_tasks(tasks_path=tasks_path, apply=True)
    assert merged == ["eng-20260812-04"]
    updated = load_engineering_tasks(tasks_path)
    assert updated["tasks"][0]["status"] == "merged"
    assert updated["tasks"][0]["branch_name"] == "cursor/eng-20260812-04-1de3"


def test_recover_engineering_queue_reconciles_orphans(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            _task("eng-20260729-02", status="pr_open").to_dict()
            | {"branch_name": "cursor/eng-20260729-02-1de3"},
            _task("eng-20260729-01").to_dict(),
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")

    result = recover_engineering_queue(tasks_path=tasks_path, open_prs=[], apply=True)
    assert result.reconciled == ["eng-20260729-02"]
    updated = load_engineering_tasks(tasks_path)
    assert updated["tasks"][0]["status"] == "open"


def test_mark_task_status_increments_failure_count(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(
        json.dumps({"tasks": [_task("eng-20260729-01").to_dict()]}),
        encoding="utf-8",
    )
    mark_task_status("eng-20260729-01", "failed", path=tasks_path, committed_path=tasks_path)
    updated = load_engineering_tasks(tasks_path)
    assert updated["tasks"][0]["failure_count"] == 1
    mark_task_status("eng-20260729-01", "failed", path=tasks_path, committed_path=tasks_path)
    updated = load_engineering_tasks(tasks_path)
    assert updated["tasks"][0]["failure_count"] == 2


def test_summarize_parked_tasks(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(
        json.dumps(
            {
                "tasks": [
                    _task("eng-20260729-01", status="parked").to_dict()
                    | {
                        "parked_reason": "CI blocked",
                        "parked_at": "2026-07-29T00:00:00+00:00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    rows = summarize_parked_tasks(tasks_path)
    assert len(rows) == 1
    assert rows[0]["id"] == "eng-20260729-01"
    assert rows[0]["needs_attention"] is True
    assert rows[0]["parked_policy"] == "ci_blocked"


def test_summarize_parked_tasks_needing_attention_skips_no_diff(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(
        json.dumps(
            {
                "tasks": [
                    _task("eng-20260804-01", status="parked").to_dict()
                    | {
                        "parked_reason": "agent produced no code changes 2 time(s) (cap 2) — manual review",
                        "parked_policy": "no_diff_cap",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert summarize_parked_tasks_needing_attention(tasks_path) == []


def test_housekeep_parked_tasks_cancels_duplicate_of_merged(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(
        json.dumps(
            {
                "tasks": [
                    _task("eng-20260726-05", status="merged").to_dict(),
                    _task("eng-20260804-36", status="parked").to_dict()
                    | {
                        "parked_policy": "duplicate",
                        "duplicate_of": "eng-20260726-05",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    result = housekeep_parked_tasks(tasks_path=tasks_path, apply=True)
    assert len(result.cancelled) == 1
    assert result.cancelled[0].task_id == "eng-20260804-36"
    updated = load_engineering_tasks(tasks_path)
    parked = next(row for row in updated["tasks"] if row["id"] == "eng-20260804-36")
    assert parked["status"] == "cancelled"
    assert parked["duplicate_of"] == "eng-20260726-05"


def test_record_agent_no_diff_run_increments_then_parks(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(
        json.dumps({"tasks": [_task("eng-20260804-36").to_dict()]}),
        encoding="utf-8",
    )

    first = record_agent_no_diff_run(
        "eng-20260804-36",
        tasks_path=tasks_path,
        max_runs=2,
    )
    assert first["recorded"] is True
    assert first["parked"] is False
    assert first["no_diff_count"] == 1

    second = record_agent_no_diff_run(
        "eng-20260804-36",
        tasks_path=tasks_path,
        max_runs=2,
    )
    assert second["parked"] is True
    updated = load_engineering_tasks(tasks_path)
    assert updated["tasks"][0]["status"] == "parked"
    assert "no code changes" in str(updated["tasks"][0].get("parked_reason"))
    assert updated["tasks"][0].get("parked_policy") == "no_diff_cap"
