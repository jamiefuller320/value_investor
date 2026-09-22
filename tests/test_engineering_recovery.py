"""Tests for engineering queue self-repair."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.engineering_recovery import (
    cancel_resolved_workflow_failure_tasks,
    count_attention_parked_tasks,
    evaluate_queue_clearing_pause,
    housekeep_parked_tasks,
    park_agent_task,
    park_workflow_permission_blocked_tasks,
    reconcile_merged_pr_open_tasks,
    record_agent_no_diff_run,
    record_queue_clearing_action,
    recover_engineering_queue,
    retry_failed_tasks,
    summarize_parked_tasks,
    summarize_parked_tasks_needing_attention,
    task_allows_workflow_files,
    unpark_agent_task,
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


def test_unpark_agent_task_reopens_and_clears_parked_fields(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            _task("eng-20260729-01", status="parked").to_dict()
            | {
                "parked_reason": "preflight blocked PR open — preflight failed",
                "parked_policy": "preflight_clash",
                "parked_at": datetime.now(UTC).isoformat(),
            }
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")

    action = unpark_agent_task(
        "eng-20260729-01",
        reason="clash cleared after parallel merges",
        tasks_path=tasks_path,
        apply=True,
    )
    assert action is not None
    assert action.action == "unpark"
    updated = load_engineering_tasks(tasks_path)
    row = updated["tasks"][0]
    assert row["status"] == "open"
    assert "parked_reason" not in row
    assert count_attention_parked_tasks(tasks_path=tasks_path) == 0


def test_retry_failed_tasks_does_not_mirror_isolated_fixture_to_committed(
    tmp_path: Path, monkeypatch
):
    """Regression: tmp_path queue updates must not overwrite committed queue."""
    committed_path = tmp_path / "committed" / "engineering_tasks.json"
    committed_path.parent.mkdir(parents=True)
    committed_path.write_text(
        json.dumps({"tasks": [_task("eng-real-queue-task").to_dict()]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "value_investor.engineering_tasks.COMMITTED_TASKS_PATH",
        committed_path,
    )

    isolated_path = tmp_path / "fixture" / "engineering_tasks.json"
    isolated_path.parent.mkdir(parents=True)
    isolated_path.write_text(
        json.dumps(
            {
                "tasks": [
                    _task("eng-20260729-01", status="failed").to_dict()
                    | {
                        "failure_count": 2,
                        "last_failed_at": datetime.now(UTC).isoformat(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    retry_failed_tasks(tasks_path=isolated_path, apply=True, max_retries=2)

    committed = load_engineering_tasks(committed_path)
    assert [row["id"] for row in committed["tasks"]] == ["eng-real-queue-task"]
    isolated = load_engineering_tasks(isolated_path)
    assert isolated["tasks"][0]["status"] == "parked"


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


def test_recover_engineering_queue_cancels_superseded_hunter(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            {
                "id": "eng-20260910-04",
                "area": "ingest",
                "title": "Hunt fetchable IR source for parked euro_depth leftover ESSITY-B.ST",
                "summary": "x",
                "priority": "low",
                "priority_score": 12.0,
                "source": "parked_source_hunter",
                "status": "open",
                "evidence": {
                    "market_id": "euro_depth",
                    "hunter_ticker": "ESSITY-B.ST",
                },
                "allowed_paths": ["src/value_investor/research/filings.py"],
                "blocked_paths": [],
            }
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")

    result = recover_engineering_queue(tasks_path=tasks_path, open_prs=[], apply=True)
    assert any(row.action == "cancel_superseded_hunter" for row in result.cancelled)
    updated = load_engineering_tasks(tasks_path)
    assert updated["tasks"][0]["status"] == "cancelled"


def test_queue_clearing_pause_activates_at_cap(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    rows = []
    for idx in range(8):
        rows.append(
            {
                "id": f"eng-parked-{idx:02d}",
                "title": f"Parked {idx}",
                "status": "parked",
                "parked_at": f"2026-09-0{idx}T10:00:00+00:00",
                "parked_reason": "draft PR checks still failing",
                "parked_policy": "ci_blocked",
            }
        )
    tasks_path.write_text(json.dumps({"tasks": rows}), encoding="utf-8")

    state = evaluate_queue_clearing_pause(tasks_path=tasks_path, apply=True)
    assert state["pause_active"] is True
    assert state["should_send_full_queue_warning"] is True
    assert count_attention_parked_tasks(tasks_path=tasks_path) == 8


def test_queue_clearing_resume_requires_count_and_idle(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    now = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)

    def _parked_rows(count: int) -> list[dict[str, Any]]:
        return [
            {
                "id": f"eng-parked-{idx:02d}",
                "title": f"Parked {idx}",
                "status": "parked",
                "parked_at": f"2026-09-0{idx}T10:00:00+00:00",
                "parked_reason": "draft PR checks still failing",
                "parked_policy": "ci_blocked",
            }
            for idx in range(count)
        ]

    tasks_path.write_text(json.dumps({"tasks": _parked_rows(8)}), encoding="utf-8")
    paused = evaluate_queue_clearing_pause(tasks_path=tasks_path, apply=True, now=now)

    tasks_path.write_text(
        json.dumps({"tasks": _parked_rows(6), "queue_clearing": paused}),
        encoding="utf-8",
    )
    record_queue_clearing_action(tasks_path=tasks_path, apply=True, now=now)
    still_paused = evaluate_queue_clearing_pause(
        tasks_path=tasks_path,
        apply=True,
        now=now + timedelta(minutes=10),
    )
    assert still_paused["pause_active"] is True
    assert still_paused.get("resume_pending") is True

    resumed = evaluate_queue_clearing_pause(
        tasks_path=tasks_path,
        apply=True,
        now=now + timedelta(minutes=31),
    )
    assert resumed["pause_active"] is False
    assert resumed.get("resumed_at")


def test_mark_task_status_records_queue_clearing_action(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    now = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    tasks_path.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "eng-parked-01",
                        "title": "Parked",
                        "status": "parked",
                        "parked_at": "2026-09-01T10:00:00+00:00",
                        "parked_reason": "draft PR checks still failing",
                        "parked_policy": "ci_blocked",
                    }
                ],
                "queue_clearing": {
                    "pause_active": True,
                    "pause_started_at": now.isoformat(),
                },
            }
        ),
        encoding="utf-8",
    )
    mark_task_status(
        "eng-parked-01",
        "cancelled",
        path=tasks_path,
        committed_path=tasks_path,
    )
    updated = load_engineering_tasks(tasks_path)
    assert updated["queue_clearing"]["last_clearing_action_at"]


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


def test_housekeep_parked_tasks_cancels_no_diff_only_when_requested(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "eng-no-diff-01",
                        "title": "No diff park",
                        "status": "parked",
                        "parked_policy": "no_diff_cap",
                        "parked_reason": "agent produced no code changes 2 time(s) (cap 2)",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    below_cap = housekeep_parked_tasks(
        tasks_path=tasks_path,
        apply=True,
        auto_cancel_no_diff_cap=False,
    )
    assert below_cap.cancelled == []
    assert load_engineering_tasks(tasks_path)["tasks"][0]["status"] == "parked"

    at_cap = housekeep_parked_tasks(
        tasks_path=tasks_path,
        apply=True,
        auto_cancel_no_diff_cap=True,
    )
    assert len(at_cap.cancelled) == 1
    assert at_cap.cancelled[0].action == "cancel_no_diff_cap"
    assert load_engineering_tasks(tasks_path)["tasks"][0]["status"] == "cancelled"


def test_housekeep_parked_tasks_cancels_superseded_parked_hunter(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "eng-hunter-parked-01",
                        "title": "Hunt fetchable IR source for parked euro_depth leftover ESSITY-B.ST",
                        "status": "parked",
                        "source": "parked_source_hunter",
                        "parked_policy": "preflight_clash",
                        "parked_reason": "preflight blocked PR open",
                        "evidence": {
                            "market_id": "euro_depth",
                            "hunter_ticker": "ESSITY-B.ST",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    result = housekeep_parked_tasks(
        tasks_path=tasks_path,
        apply=True,
        auto_cancel_superseded_parked_hunter=True,
    )
    assert len(result.cancelled) == 1
    assert result.cancelled[0].action == "cancel_superseded_parked_hunter"
    updated = load_engineering_tasks(tasks_path)
    assert updated["tasks"][0]["status"] == "cancelled"


def test_recover_engineering_queue_includes_tier1_housekeep(tmp_path: Path):
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
    result = recover_engineering_queue(tasks_path=tasks_path, open_prs=[], apply=True)
    assert result.housekeep.get("action_count") == 1
    assert result.housekeep["cancelled"][0]["action"] == "cancel_duplicate"
    updated = load_engineering_tasks(tasks_path)
    parked = next(row for row in updated["tasks"] if row["id"] == "eng-20260804-36")
    assert parked["status"] == "cancelled"


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


def test_task_allows_workflow_files():
    assert task_allows_workflow_files(
        {"allowed_paths": [".github/workflows/ingest-loop.yml", "tests/test_x.py"]}
    )
    assert not task_allows_workflow_files({"allowed_paths": ["src/value_investor/ingest_loop.py"]})


def test_cancel_resolved_workflow_failure_task(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "eng-20260826-01",
                        "status": "open",
                        "source": "workflow_failure",
                        "evidence": {
                            "workflow": "ingest-loop.yml",
                            "run_id": "32950154010",
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    cancelled = cancel_resolved_workflow_failure_tasks(
        tasks_path=tasks_path,
        apply=True,
        latest_success_by_workflow={
            "ingest-loop.yml": {"id": 33048306272, "created_at": "2026-08-27T07:05:30Z"}
        },
    )
    assert len(cancelled) == 1
    assert cancelled[0].task_id == "eng-20260826-01"
    updated = load_engineering_tasks(tasks_path)
    assert updated["tasks"][0]["status"] == "cancelled"
    assert updated["tasks"][0].get("cancelled_policy") == "workflow_recovered"


def test_github_repo_falls_back_to_git_remote(monkeypatch):
    from value_investor import engineering_recovery as er

    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)

    class _Result:
        returncode = 0
        stdout = "git@github.com:jamiefuller320/value_investor.git\n"
        stderr = ""

    monkeypatch.setattr(er.subprocess, "run", lambda *args, **kwargs: _Result())
    assert er._github_repo() == "jamiefuller320/value_investor"


def test_park_workflow_permission_blocked_tasks(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "eng-20260826-01",
                        "status": "open",
                        "allowed_paths": [".github/workflows/ingest-loop.yml"],
                    },
                    {
                        "id": "eng-20260826-02",
                        "status": "open",
                        "allowed_paths": ["src/value_investor/ingest_loop.py"],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    failures = [{"id": 1, "created_at": "2026-08-27T07:00:00Z"}]
    parked = park_workflow_permission_blocked_tasks(
        tasks_path=tasks_path,
        recent_agent_failures=failures,
        apply=True,
    )
    assert len(parked) == 1
    assert parked[0].task_id == "eng-20260826-01"
    updated = load_engineering_tasks(tasks_path)
    assert updated["tasks"][0]["status"] == "parked"
    assert updated["tasks"][0].get("parked_policy") == "workflow_permission"
    assert updated["tasks"][1]["status"] == "open"


def test_park_agent_task_cli(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(
        json.dumps({"tasks": [_task("eng-20260826-01").to_dict()]}),
        encoding="utf-8",
    )
    action = park_agent_task(
        "eng-20260826-01",
        reason="cannot push workflow without Workflows permission",
        tasks_path=tasks_path,
        apply=True,
    )
    assert action is not None
    updated = load_engineering_tasks(tasks_path)
    assert updated["tasks"][0]["status"] == "parked"
    assert updated["tasks"][0].get("parked_policy") == "workflow_permission"


def test_list_merge_sync_lag_tasks(tmp_path: Path, monkeypatch):
    from value_investor.engineering_recovery import list_merge_sync_lag_tasks

    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            _task("eng-20260915-04", status="pr_open").to_dict()
            | {"branch_name": "cursor/eng-20260915-04-1de3"},
            _task("eng-20260915-09", status="open").to_dict()
            | {"branch_name": "cursor/eng-20260915-09-1de3"},
            _task("eng-20260915-02", status="open").to_dict(),
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")

    def fake_merged(branch, **kwargs):
        mapping = {
            "cursor/eng-20260915-04-1de3": {
                "html_url": "https://github.com/example/repo/pull/652",
                "number": 652,
                "merged_at": "2026-09-15T13:49:04Z",
            },
            "cursor/eng-20260915-09-1de3": {
                "html_url": "https://github.com/example/repo/pull/653",
                "number": 653,
                "merged_at": "2026-09-15T13:49:28Z",
            },
        }
        return mapping.get(branch)

    monkeypatch.setattr(
        "value_investor.engineering_recovery.find_merged_pull_for_branch",
        fake_merged,
    )
    lagged = list_merge_sync_lag_tasks(tasks_path=tasks_path, token="x")
    ids = [row["task_id"] for row in lagged]
    assert ids == ["eng-20260915-04", "eng-20260915-09"]


def test_reconcile_open_tasks_with_live_prs_restamps_cleared_branch(tmp_path: Path):
    """#686-class: open + null branch, but live PR exists → pr_open + branch + number."""
    from value_investor.engineering_recovery import reconcile_open_tasks_with_live_prs

    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            _task("eng-20260917-06", status="open").to_dict() | {"auto_merge": True},
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")
    restamped = reconcile_open_tasks_with_live_prs(
        tasks_path=tasks_path,
        open_prs=[
            {
                "number": 686,
                "headRefName": "cursor/eng-20260917-06-1de3",
                "url": "https://github.com/example/repo/pull/686",
            }
        ],
        apply=True,
    )
    assert restamped == ["eng-20260917-06"]
    updated = load_engineering_tasks(tasks_path)["tasks"][0]
    assert updated["status"] == "pr_open"
    assert updated["branch_name"] == "cursor/eng-20260917-06-1de3"
    assert updated["pr_number"] == 686


def test_recover_does_not_orphan_reset_when_live_lookup_finds_pr(tmp_path: Path, monkeypatch):
    """Stale empty open_prs snapshot must not clear a fresh pr_open stamp."""
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            _task("eng-20260917-06", status="pr_open").to_dict()
            | {"branch_name": "cursor/eng-20260917-06-1de3"},
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(
        "value_investor.engineering_recovery.find_merged_pull_for_branch",
        lambda branch, **kwargs: None,
    )
    monkeypatch.setattr(
        "value_investor.engineering_recovery.find_open_pull_for_branch",
        lambda branch, **kwargs: (
            {
                "number": 686,
                "html_url": "https://github.com/example/repo/pull/686",
                "head": {"ref": branch},
            }
            if branch == "cursor/eng-20260917-06-1de3"
            else None
        ),
    )

    result = recover_engineering_queue(tasks_path=tasks_path, open_prs=[], apply=True)
    assert result.reconciled == []
    updated = load_engineering_tasks(tasks_path)["tasks"][0]
    assert updated["status"] == "pr_open"
    assert updated["branch_name"] == "cursor/eng-20260917-06-1de3"


def test_recover_restamps_open_before_orphan_reconcile(tmp_path: Path, monkeypatch):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            _task("eng-20260917-06", status="open").to_dict(),
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.engineering_recovery.find_merged_pull_for_branch",
        lambda branch, **kwargs: None,
    )
    monkeypatch.setattr(
        "value_investor.engineering_recovery.find_open_pull_for_branch",
        lambda branch, **kwargs: None,
    )

    result = recover_engineering_queue(
        tasks_path=tasks_path,
        open_prs=[
            {
                "number": 686,
                "headRefName": "cursor/eng-20260917-06-1de3",
                "html_url": "https://github.com/example/repo/pull/686",
            }
        ],
        apply=True,
    )
    assert result.restamped == ["eng-20260917-06"]
    assert result.reconciled == []
    updated = load_engineering_tasks(tasks_path)["tasks"][0]
    assert updated["status"] == "pr_open"
    assert updated["pr_number"] == 686


def test_allowlist_mismatches_filing_title_ops_sandbox():
    from value_investor.engineering_recovery import allowlist_mismatches_filing_title

    row = {
        "title": "Deprioritise CH parent-only filings in refetch scoring",
        "summary": "CH administrative filings",
        "allowed_paths": [
            "src/value_investor/automation_status.py",
            "src/value_investor/ops_monitor.py",
            "src/value_investor/engineering_recovery.py",
            "src/value_investor/engineering_queue.py",
            ".github/workflows/ops-monitor.yml",
            ".github/workflows/engineering-queue.yml",
            "tests/test_ops_monitor.py",
        ],
    }
    assert allowlist_mismatches_filing_title(row) is True

    ok = {
        "title": "On CH refetch passes, cite three-year margin series",
        "summary": "gap-fill",
        "allowed_paths": [
            "src/value_investor/research/gap_fill.py",
            "src/value_investor/deep_analysis.py",
            "tests/test_research_gap_fill.py",
        ],
    }
    assert allowlist_mismatches_filing_title(ok) is False


def test_housekeep_cancels_mis_scoped_preflight_park(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            _task(
                "eng-20260920-11",
                status="parked",
                title="Deprioritise CH parent-only filings in refetch scoring",
            ).to_dict()
            | {
                "parked_policy": "preflight_clash",
                "parked_reason": "preflight blocked PR open — preflight failed",
                "allowed_paths": [
                    "src/value_investor/automation_status.py",
                    "src/value_investor/ops_monitor.py",
                    "src/value_investor/engineering_recovery.py",
                    "src/value_investor/engineering_sync.py",
                    ".github/workflows/ops-monitor.yml",
                    ".github/workflows/engineering-agent.yml",
                ],
            }
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")

    result = housekeep_parked_tasks(
        tasks_path=tasks_path,
        apply=True,
        auto_cancel_mis_scoped_allowlist=True,
    )
    assert any(row.action == "cancel_mis_scoped_allowlist" for row in result.cancelled)
    updated = load_engineering_tasks(tasks_path)["tasks"][0]
    assert updated["status"] == "cancelled"
    assert updated.get("cancelled_policy") == "mis_scoped_allowlist"


def test_reconcile_merged_uses_pr_number_when_branch_lookup_empty(tmp_path: Path, monkeypatch):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            _task("eng-20260920-15", status="pr_open").to_dict()
            | {
                "branch_name": "cursor/eng-20260920-15-1de3",
                "pr_number": 764,
            }
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.engineering_recovery.find_merged_pull_for_branch",
        lambda branch, **kwargs: None,
    )
    monkeypatch.setattr(
        "value_investor.engineering_recovery.find_merged_pull_by_number",
        lambda number, **kwargs: (
            {
                "html_url": "https://github.com/jamiefuller320/value_investor/pull/764",
                "number": 764,
                "merged_at": "2026-09-20T17:40:05Z",
            }
            if int(number) == 764
            else None
        ),
    )

    merged = reconcile_merged_pr_open_tasks(tasks_path=tasks_path, apply=True)
    assert merged == ["eng-20260920-15"]
    updated = load_engineering_tasks(tasks_path)["tasks"][0]
    assert updated["status"] == "merged"
    assert updated["pr_number"] == 764


def test_find_merged_pull_falls_back_to_gh_when_rest_empty(monkeypatch):
    from value_investor.engineering_recovery import find_merged_pull_for_branch

    monkeypatch.setattr(
        "value_investor.engineering_recovery._github_repo",
        lambda: "jamiefuller320/value_investor",
    )
    monkeypatch.setattr(
        "value_investor.engineering_recovery._github_token",
        lambda: "test-token",
    )
    monkeypatch.setattr(
        "value_investor.engineering_recovery._github_api_get",
        lambda path, token=None: [],
    )
    monkeypatch.setattr(
        "value_investor.engineering_recovery._find_merged_pull_via_gh",
        lambda branch: {
            "number": 761,
            "html_url": "https://github.com/example/repo/pull/761",
            "merged_at": "2026-09-20T16:24:16Z",
        },
    )
    pr = find_merged_pull_for_branch("cursor/eng-20260920-08-1de3")
    assert pr is not None
    assert pr["number"] == 761


def test_evaluate_dispatch_heals_merge_sync(tmp_path: Path, monkeypatch):
    from value_investor.engineering_queue import evaluate_engineering_dispatch

    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            _task("eng-20260920-08", status="open").to_dict()
            | {"branch_name": "cursor/eng-20260920-08-1de3"},
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.engineering_recovery.find_merged_pull_for_branch",
        lambda branch, **kwargs: {
            "html_url": "https://github.com/example/repo/pull/761",
            "number": 761,
            "merged_at": "2026-09-20T16:24:16Z",
        },
    )
    monkeypatch.setattr(
        "value_investor.engineering_recovery.find_merged_pull_by_number",
        lambda number, **kwargs: None,
    )

    decision = evaluate_engineering_dispatch(
        tasks_path=tasks_path,
        open_prs=[],
        heal_merge_sync=True,
    )
    updated = load_engineering_tasks(tasks_path)["tasks"][0]
    assert updated["status"] == "merged"
    assert decision.should_dispatch is False
    assert "no open" in decision.reason


def test_housekeep_cancels_resolved_gap_closure(tmp_path: Path, monkeypatch):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            _task(
                "eng-20260922-01",
                status="parked",
                title="Close stubborn ingest gaps for IMB.L (chain 1/3: 0/0 bodies)",
            ).to_dict()
            | {
                "source": "ingest_gap_closure",
                "parked_policy": "preflight_clash",
                "parked_reason": "preflight blocked PR open — preflight failed",
                "evidence": {"ticker": "IMB.L", "tickers": ["IMB.L"]},
            }
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.ingest_gap_closure.gap_closure_ticker_has_gaps",
        lambda ticker, **kwargs: False,
    )

    result = housekeep_parked_tasks(
        tasks_path=tasks_path,
        apply=True,
        auto_cancel_resolved_gap_closure=True,
        auto_unpark_healed_preflight=False,
    )
    assert any(row.action == "cancel_resolved_gap_closure" for row in result.cancelled)
    assert load_engineering_tasks(tasks_path)["tasks"][0]["status"] == "cancelled"


def test_housekeep_cancels_superseded_gap_closure_sibling(tmp_path: Path, monkeypatch):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            _task(
                "eng-20260921-07",
                status="merged",
                title="Close stubborn ingest gaps for IMB.L (chain 1/3: 0/0 bodies, run igc-20260921-07)",
            ).to_dict()
            | {
                "source": "ingest_gap_closure",
                "evidence": {"ticker": "IMB.L", "chain_root_id": "igc-20260921-07"},
            },
            _task(
                "eng-20260921-08",
                status="parked",
                title="Close stubborn ingest gaps for IMB.L (chain 2/3: 0/0 bodies, run igc-20260921-07)",
            ).to_dict()
            | {
                "source": "ingest_gap_closure",
                "parked_policy": "preflight_clash",
                "parked_reason": "preflight blocked PR open — preflight failed",
                "evidence": {"ticker": "IMB.L", "chain_root_id": "igc-20260921-07"},
            },
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.ingest_gap_closure.gap_closure_ticker_has_gaps",
        lambda ticker, **kwargs: True,
    )

    result = housekeep_parked_tasks(
        tasks_path=tasks_path,
        apply=True,
        auto_cancel_resolved_gap_closure=True,
        auto_cancel_superseded_gap_closure=True,
        auto_unpark_healed_preflight=False,
    )
    assert any(row.action == "cancel_superseded_gap_closure" for row in result.cancelled)
    parked = next(
        row for row in load_engineering_tasks(tasks_path)["tasks"] if row["id"] == "eng-20260921-08"
    )
    assert parked["status"] == "cancelled"
    assert parked.get("duplicate_of") == "eng-20260921-07"


def test_housekeep_unparks_healed_preflight(tmp_path: Path, monkeypatch):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            _task(
                "eng-20260920-16",
                status="parked",
                title="Close library ingest filing gaps for DAX",
            ).to_dict()
            | {
                "parked_policy": "preflight_clash",
                "parked_reason": "preflight blocked PR open — preflight failed",
                "allowed_paths": [
                    "src/value_investor/research/filings.py",
                    "tests/test_research_filings.py",
                ],
            }
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(
        "value_investor.engineering_recovery.preflight_park_is_healed",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "value_investor.engineering_queue.refresh_engineering_queue_ui",
        lambda **kwargs: None,
    )

    result = housekeep_parked_tasks(
        tasks_path=tasks_path,
        apply=True,
        auto_unpark_healed_preflight=True,
        auto_cancel_resolved_gap_closure=False,
    )
    assert any(row.action == "unpark_healed_preflight" for row in result.unparked)
    row = load_engineering_tasks(tasks_path)["tasks"][0]
    assert row["status"] == "open"
    assert "parked_reason" not in row


def test_recover_self_heals_before_full_queue_warning(tmp_path: Path, monkeypatch):
    """Housekeep runs before pause evaluation so self-heal can avert the warning email."""
    monkeypatch.setattr(
        "value_investor.engineering_queue.refresh_engineering_queue_ui",
        lambda **kwargs: None,
    )
    tasks_path = tmp_path / "engineering_tasks.json"
    parked_rows = []
    for idx in range(8):
        parked_rows.append(
            _task(
                f"eng-20260922-{idx + 1:02d}",
                status="parked",
                title=f"Close stubborn ingest gaps for IMB.L park {idx}",
            ).to_dict()
            | {
                "source": "ingest_gap_closure",
                "parked_policy": "preflight_clash",
                "parked_reason": "preflight blocked PR open — preflight failed",
                "parked_at": datetime.now(UTC).isoformat(),
                "evidence": {"ticker": "IMB.L"},
            }
        )
    tasks_path.write_text(json.dumps({"tasks": parked_rows}), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.ingest_gap_closure.gap_closure_ticker_has_gaps",
        lambda ticker, **kwargs: False,
    )

    result = recover_engineering_queue(tasks_path=tasks_path, open_prs=[], apply=True)
    assert int(result.housekeep.get("action_count") or 0) >= 8
    clearing = result.queue_clearing
    assert int(clearing.get("attention_parked_count") or 0) == 0
    assert clearing.get("should_send_full_queue_warning") is False
    assert clearing.get("pause_active") is not True
