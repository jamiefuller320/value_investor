"""Tests for engineering queue auto-dispatch."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.engineering_queue import (
    build_engineering_queue_dashboard,
    evaluate_engineering_dispatch,
    find_in_flight_pr,
    is_engineering_branch,
    is_safe_to_clear_stale_branch,
    reconcile_orphaned_pr_open_tasks,
    reprioritize_queue_after_ingest_merge,
    snapshot_ingest_health,
    task_id_from_branch,
)
from value_investor.engineering_tasks import (
    EngineeringTask,
    _merge_task_rows,
    mark_task_status,
    task_title_key,
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


def test_is_engineering_branch_and_task_id():
    assert is_engineering_branch("cursor/eng-20260726-01-1de3")
    assert not is_engineering_branch("cursor/post-run-review-1de3")
    assert task_id_from_branch("cursor/eng-20260726-01-1de3") == "eng-20260726-01"


def test_is_safe_to_clear_stale_branch():
    branch = "cursor/eng-20260726-02-1de3"
    assert is_safe_to_clear_stale_branch(branch, open_prs=[]) is True
    assert (
        is_safe_to_clear_stale_branch(
            branch,
            open_prs=[{"headRefName": "cursor/eng-20260726-02-1de3"}],
        )
        is False
    )
    assert is_safe_to_clear_stale_branch("cursor/post-run-review-1de3", open_prs=[]) is False


def test_find_in_flight_pr_matches_engineering_branch():
    prs = [
        {"number": 10, "headRefName": "cursor/weekly-ops-budget-1de3", "title": "feat: budget"},
        {
            "number": 11,
            "headRefName": "cursor/eng-20260726-02-1de3",
            "title": "feat(engineering): ingest",
        },
    ]
    found = find_in_flight_pr(prs)
    assert found is not None
    assert found["number"] == 11


def test_evaluate_dispatch_allows_parallel_when_pr_open_below_cap(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            _task("eng-20260726-01", status="open").to_dict(),
            _task("eng-20260726-02", status="pr_open").to_dict(),
            _task("eng-20260726-03", status="open", title="Third task").to_dict(),
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")
    decision = evaluate_engineering_dispatch(
        tasks_path=tasks_path,
        open_prs=[
            {
                "number": 112,
                "headRefName": "cursor/eng-20260726-02-1de3",
                "title": "feat(engineering): x",
            }
        ],
        max_parallel=2,
    )
    assert decision.should_dispatch is True
    assert decision.next_task_id == "eng-20260726-01"
    assert decision.next_task_ids == ["eng-20260726-01"]


def test_evaluate_dispatch_parallel_two_slots(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            _task("eng-20260726-01").to_dict(),
            _task("eng-20260726-02", title="Second task").to_dict(),
            _task("eng-20260726-03", title="Third task").to_dict(),
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")
    decision = evaluate_engineering_dispatch(
        tasks_path=tasks_path,
        open_prs=[],
        max_parallel=2,
    )
    assert decision.should_dispatch is True
    assert decision.next_task_ids == ["eng-20260726-01", "eng-20260726-02"]


def test_evaluate_dispatch_blocks_at_parallel_cap(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            _task("eng-20260726-01", status="open").to_dict(),
            _task("eng-20260726-02", status="pr_open").to_dict(),
            _task("eng-20260726-03", status="pr_open").to_dict(),
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")
    decision = evaluate_engineering_dispatch(
        tasks_path=tasks_path,
        open_prs=[
            {
                "number": 1,
                "headRefName": "cursor/eng-20260726-02-1de3",
                "title": "feat(engineering): a",
            },
            {
                "number": 2,
                "headRefName": "cursor/eng-20260726-03-1de3",
                "title": "feat(engineering): b",
            },
        ],
        max_parallel=2,
    )
    assert decision.should_dispatch is False
    assert "parallel cap" in decision.reason


def test_refresh_engineering_queue_ui_updates_automation(tmp_path: Path):
    from value_investor.engineering_queue import refresh_engineering_queue_ui

    tasks_path = tmp_path / "engineering_tasks.json"
    automation_path = tmp_path / "automation.json"
    latest_path = tmp_path / "latest.json"
    payload = {"tasks": [_task("eng-20260726-01").to_dict()]}
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")
    automation_path.write_text(
        json.dumps({"schema_version": 1, "settings": {}}),
        encoding="utf-8",
    )
    latest_path.write_text(json.dumps({"reports": []}), encoding="utf-8")

    result = refresh_engineering_queue_ui(
        automation_path=automation_path,
        latest_path=latest_path,
        tasks_path=tasks_path,
    )
    auto = json.loads(automation_path.read_text(encoding="utf-8"))
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    assert auto["engineering_queue"]["status"]["open_count"] == 1
    assert latest["automation"]["engineering_queue"]["status"]["open_count"] == 1
    assert result["open_count"] == 1


def test_evaluate_dispatch_ready_when_queue_open_and_no_pr(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {"tasks": [_task("eng-20260726-01").to_dict()]}
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")
    decision = evaluate_engineering_dispatch(tasks_path=tasks_path, open_prs=[])
    assert decision.should_dispatch is True
    assert decision.next_task_id == "eng-20260726-01"


def test_reconcile_orphaned_pr_open_resets_without_matching_pr(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            _task("eng-20260726-02", status="pr_open").to_dict()
            | {"branch_name": "cursor/eng-20260726-02-1de3", "completed_at": "x"},
            _task("eng-20260726-01").to_dict(),
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")
    result = reconcile_orphaned_pr_open_tasks(tasks_path=tasks_path, open_prs=[])
    assert result["count"] == 1
    updated = json.loads(tasks_path.read_text(encoding="utf-8"))
    assert updated["tasks"][0]["status"] == "open"
    assert "branch_name" not in updated["tasks"][0]
    decision = evaluate_engineering_dispatch(tasks_path=tasks_path, open_prs=[])
    assert decision.should_dispatch is True
    assert decision.next_task_id == "eng-20260726-02"


def test_reconcile_orphaned_pr_open_keeps_matching_open_pr(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            _task("eng-20260726-02", status="pr_open").to_dict()
            | {"branch_name": "cursor/eng-20260726-02-1de3"},
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")
    result = reconcile_orphaned_pr_open_tasks(
        tasks_path=tasks_path,
        open_prs=[{"number": 115, "headRefName": "cursor/eng-20260726-02-1de3"}],
    )
    assert result["count"] == 0
    updated = json.loads(tasks_path.read_text(encoding="utf-8"))
    assert updated["tasks"][0]["status"] == "pr_open"


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


def test_merge_task_rows_preserves_unmatched_open_tasks():
    existing = [
        _task("eng-20260802-02", title="Reconcile canonical FCF field").to_dict(),
    ]
    compiled = [
        _task("eng-20260803-29", title="Cap Strong Buy when trailing FCF is negative"),
    ]
    merged = _merge_task_rows(existing, compiled)
    ids = {row["id"] for row in merged}
    assert "eng-20260802-02" in ids
    assert "eng-20260803-29" in ids


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


def test_reprioritize_boosts_scoring_when_ingest_improves(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    latest_path = tmp_path / "latest.json"
    latest_path.write_text(
        json.dumps({"reports": [{"ticker": "BT-A.L", "signal": "buy"}]}),
        encoding="utf-8",
    )
    payload = {
        "ingest_health": {"zero_body_buy_tier": 3, "indexed_without_body": 10},
        "tasks": [
            {
                **_task(
                    "eng-20260726-01",
                    status="merged",
                    title="Companies House filed-accounts PDF fetch",
                ).to_dict(),
            },
            {
                **_task(
                    "eng-20260726-02", title="Replace Google News wrapper URLs with Investegate"
                ).to_dict(),
            },
            {
                "id": "eng-20260726-05",
                "area": "scoring",
                "title": "Add commodity overlay",
                "summary": "x",
                "priority": "high",
                "priority_score": 90.0,
                "source": "post_run_review",
                "status": "open",
                "evidence": {},
                "acceptance_criteria": [],
                "allowed_paths": [],
                "blocked_paths": [],
            },
        ],
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")

    research_root = tmp_path / "research"
    index_path = research_root / "BT-A.L" / "sources" / "filings" / "filings_index.json"
    index_path.parent.mkdir(parents=True)
    index_path.write_text(
        json.dumps(
            {
                "summary": {"total": 2, "with_body": 2},
                "filings": [{"has_body": True}, {"has_body": True}],
            }
        ),
        encoding="utf-8",
    )

    result = reprioritize_queue_after_ingest_merge(
        merged_task_id="eng-20260726-01",
        tasks_path=tasks_path,
        latest_path=latest_path,
    )
    assert result["skipped"] is False
    assert result["improved"] is True
    updated = json.loads(tasks_path.read_text(encoding="utf-8"))
    scoring = next(row for row in updated["tasks"] if row["id"] == "eng-20260726-05")
    assert scoring["priority_score"] > 90.0


def test_snapshot_ingest_health_counts_zero_body(tmp_path: Path):
    latest_path = tmp_path / "latest.json"
    latest_path.write_text(
        json.dumps(
            {
                "reports": [
                    {"ticker": "BT-A.L", "signal": "buy"},
                    {"ticker": "RIO.L", "signal": "strong_buy"},
                ]
            }
        ),
        encoding="utf-8",
    )
    root = tmp_path / "research"
    for ticker, with_body in (("BT-A.L", 0), ("RIO.L", 2)):
        index_path = root / ticker / "sources" / "filings" / "filings_index.json"
        index_path.parent.mkdir(parents=True)
        index_path.write_text(
            json.dumps(
                {
                    "summary": {"total": 2, "with_body": with_body},
                    "filings": [{"has_body": bool(with_body)}, {"has_body": False}],
                }
            ),
            encoding="utf-8",
        )
    health = snapshot_ingest_health(latest_path=latest_path, research_roots=[root])
    assert health["buy_tier_count"] == 2
    assert health["zero_body_buy_tier"] == 1


def test_build_engineering_queue_dashboard_lists_open_and_pr_open(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(
        json.dumps(
            {
                "compiled_at": "2026-08-04T10:00:00+00:00",
                "tasks": [
                    _task("eng-20260804-01", status="open", title="Open task").to_dict(),
                    _task("eng-20260804-02", status="pr_open", title="PR open task").to_dict(),
                    _task("eng-20260804-03", status="parked", title="Parked task").to_dict(),
                    _task("eng-20260804-04", status="merged", title="Merged task").to_dict(),
                ],
            }
        ),
        encoding="utf-8",
    )
    payload = build_engineering_queue_dashboard(tasks_path=tasks_path)
    assert payload["status"]["open_count"] == 1
    assert payload["status"]["pr_open_count"] == 1
    assert [row["id"] for row in payload["queued_tasks"]] == [
        "eng-20260804-01",
        "eng-20260804-02",
    ]
    assert payload["attention_tasks"][0]["id"] == "eng-20260804-03"
