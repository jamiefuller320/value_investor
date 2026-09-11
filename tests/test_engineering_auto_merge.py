"""Tests for scoped engineering PR auto-merge."""

from __future__ import annotations

import json
from unittest.mock import patch

from value_investor.engineering_auto_merge import evaluate_auto_merge, pr_checks_successful
from value_investor.engineering_tasks import BLOCKED_PATHS, EngineeringTask


def _write_task(tmp_path, task: EngineeringTask, **extra: object) -> None:
    path = tmp_path / "engineering_tasks.json"
    row = task.to_dict()
    row.update(extra)
    path.write_text(json.dumps({"tasks": [row]}), encoding="utf-8")


def test_evaluate_auto_merge_rejects_non_engineering_branch(tmp_path):
    decision = evaluate_auto_merge(branch="cursor/foo-485f", tasks_path=tmp_path / "missing.json")
    assert not decision.should_merge
    assert "not an engineering task branch" in decision.reason


def test_evaluate_auto_merge_ready_when_scope_and_checks_ok(tmp_path):
    task = EngineeringTask(
        id="eng-20260802-01",
        area="ci",
        title="CI fix",
        summary="x",
        priority="high",
        priority_score=95.0,
        source="ci_failure",
        allowed_paths=["tests/test_ops_monitor.py", "src/value_investor/ops_monitor.py"],
        blocked_paths=list(BLOCKED_PATHS),
        auto_merge=True,
        status="pr_open",
    )
    _write_task(tmp_path, task, branch_name="cursor/eng-20260802-01-1de3")
    branch = "cursor/eng-20260802-01-1de3"
    with (
        patch(
            "value_investor.engineering_auto_merge.find_open_pr_for_branch",
            return_value={"number": 42, "isDraft": False},
        ),
        patch(
            "value_investor.engineering_auto_merge.pr_checks_successful",
            return_value=(True, "all checks green"),
        ),
        patch(
            "value_investor.engineering_auto_merge.changed_files_for_pr",
            return_value=["tests/test_ops_monitor.py", "src/value_investor/ops_monitor.py"],
        ),
    ):
        decision = evaluate_auto_merge(
            branch=branch, tasks_path=tmp_path / "engineering_tasks.json"
        )
    assert decision.should_merge
    assert decision.pr_number == 42


def test_evaluate_auto_merge_rejects_when_auto_merge_disabled(tmp_path):
    task = EngineeringTask(
        id="eng-20260802-02",
        area="ingest",
        title="Fetch PDFs",
        summary="x",
        priority="high",
        priority_score=90.0,
        source="post_run_review",
        allowed_paths=["src/value_investor/research/filings.py"],
        blocked_paths=list(BLOCKED_PATHS),
        auto_merge=False,
        status="pr_open",
    )
    _write_task(tmp_path, task, branch_name="cursor/eng-20260802-02-1de3")
    decision = evaluate_auto_merge(
        branch="cursor/eng-20260802-02-1de3",
        tasks_path=tmp_path / "engineering_tasks.json",
    )
    assert not decision.should_merge
    assert "not eligible" in decision.reason


def test_pr_checks_successful_uses_modern_gh_json_fields():
    """Regression: requesting removed 'conclusion' made every auto-merge skip."""

    class _Result:
        returncode = 0
        stdout = json.dumps(
            [
                {"name": "test", "state": "SUCCESS", "bucket": "pass"},
                {"name": "hunter-merge-gate", "state": "SUCCESS", "bucket": "pass"},
                {"name": "verify-observer", "state": "SKIPPED", "bucket": "skipping"},
            ]
        )
        stderr = ""

    with (
        patch("value_investor.engineering_auto_merge._github_repo", return_value="o/r"),
        patch("value_investor.engineering_auto_merge._run_gh", return_value=_Result()) as run_gh,
    ):
        ok, reason = pr_checks_successful(564)
    assert ok
    assert reason == "all checks green"
    assert run_gh.call_args.args[0] == ["pr", "checks", "564", "--json", "name,state,bucket"]


def test_pr_checks_successful_waits_on_pending_bucket():
    class _Result:
        returncode = 0
        stdout = json.dumps(
            [
                {"name": "test", "state": "IN_PROGRESS", "bucket": "pending"},
                {"name": "hunter-merge-gate", "state": "SUCCESS", "bucket": "pass"},
            ]
        )
        stderr = ""

    with (
        patch("value_investor.engineering_auto_merge._github_repo", return_value="o/r"),
        patch("value_investor.engineering_auto_merge._run_gh", return_value=_Result()),
    ):
        ok, reason = pr_checks_successful(564)
    assert not ok
    assert "pending" in reason
    assert "test" in reason


def test_pr_checks_successful_rejects_fail_bucket():
    class _Result:
        returncode = 0
        stdout = json.dumps(
            [
                {"name": "test", "state": "FAILURE", "bucket": "fail"},
                {"name": "path-guard", "state": "SUCCESS", "bucket": "pass"},
            ]
        )
        stderr = ""

    with (
        patch("value_investor.engineering_auto_merge._github_repo", return_value="o/r"),
        patch("value_investor.engineering_auto_merge._run_gh", return_value=_Result()),
    ):
        ok, reason = pr_checks_successful(564)
    assert not ok
    assert "not green" in reason
    assert "test" in reason


def test_pr_checks_successful_surfaces_unknown_json_field_errors():
    class _Result:
        returncode = 1
        stdout = ""
        stderr = 'Unknown JSON field: "conclusion"\nAvailable fields:\n  bucket\n  state\n'

    with (
        patch("value_investor.engineering_auto_merge._github_repo", return_value="o/r"),
        patch("value_investor.engineering_auto_merge._run_gh", return_value=_Result()),
    ):
        ok, reason = pr_checks_successful(564)
    assert not ok
    assert "conclusion" in reason
