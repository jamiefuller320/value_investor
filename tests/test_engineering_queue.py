"""Tests for engineering queue auto-dispatch."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.engineering_queue import (
    evaluate_engineering_dispatch,
    find_in_flight_pr,
    is_engineering_branch,
    task_id_from_branch,
)
from value_investor.engineering_tasks import (
    EngineeringTask,
    _merge_task_rows,
    mark_task_status,
    task_title_key,
)


def _task(task_id: str, *, status: str = "open", title: str = "Build CH PDF fetch") -> EngineeringTask:
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


def test_is_engineering_branch_and_task_id():
    assert is_engineering_branch("cursor/eng-20260726-01-1de3")
    assert not is_engineering_branch("cursor/post-run-review-1de3")
    assert task_id_from_branch("cursor/eng-20260726-01-1de3") == "eng-20260726-01"


def test_find_in_flight_pr_matches_engineering_branch():
    prs = [
        {"number": 10, "headRefName": "cursor/weekly-ops-budget-1de3", "title": "feat: budget"},
        {"number": 11, "headRefName": "cursor/eng-20260726-02-1de3", "title": "feat(engineering): ingest"},
    ]
    found = find_in_flight_pr(prs)
    assert found is not None
    assert found["number"] == 11


def test_evaluate_dispatch_blocks_when_pr_open(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            _task("eng-20260726-01", status="open").to_dict(),
            _task("eng-20260726-02", status="pr_open").to_dict(),
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")
    decision = evaluate_engineering_dispatch(
        tasks_path=tasks_path,
        open_prs=[{"number": 112, "headRefName": "cursor/eng-20260726-02-1de3", "title": "feat(engineering): x"}],
    )
    assert decision.should_dispatch is False
    assert "open engineering PR" in decision.reason


def test_evaluate_dispatch_ready_when_queue_open_and_no_pr(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {"tasks": [_task("eng-20260726-01").to_dict()]}
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")
    decision = evaluate_engineering_dispatch(tasks_path=tasks_path, open_prs=[])
    assert decision.should_dispatch is True
    assert decision.next_task_id == "eng-20260726-01"


def test_merge_task_rows_preserves_merged_status():
    existing = [
        {
            "id": "eng-20260726-01",
            "area": "ingest",
            "title": "Build universal Companies House filed-accounts PDF fetch",
            "summary": "x",
            "priority": "high",
            "priority_score": 99.0,
            "source": "post_run_review",
            "status": "merged",
            "evidence": {},
            "acceptance_criteria": [],
            "allowed_paths": [],
            "blocked_paths": [],
        }
    ]
    compiled = [
        _task(
            "eng-20260727-01",
            title="Build universal Companies House filed-accounts PDF fetch + text extract",
        )
    ]
    merged = _merge_task_rows(existing, compiled)
    assert len(merged) == 1
    assert merged[0]["status"] == "merged"
    assert merged[0]["id"] == "eng-20260726-01"


def test_mark_task_status_writes_committed_copy(tmp_path: Path):
    tasks_path = tmp_path / "output" / "engineering_tasks.json"
    committed_path = tmp_path / "docs" / "data" / "engineering_tasks.json"
    payload = {"tasks": [_task("eng-20260726-01").to_dict()]}
    tasks_path.parent.mkdir(parents=True)
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")
    mark_task_status(
        "eng-20260726-01",
        "pr_open",
        path=tasks_path,
        committed_path=committed_path,
        branch_name="cursor/eng-20260726-01-1de3",
    )
    committed = json.loads(committed_path.read_text(encoding="utf-8"))
    assert committed["tasks"][0]["status"] == "pr_open"
    assert committed["tasks"][0]["branch_name"] == "cursor/eng-20260726-01-1de3"


def test_task_title_key_normalizes_whitespace():
    assert task_title_key("  Build   CH  PDF ") == "build ch pdf"
