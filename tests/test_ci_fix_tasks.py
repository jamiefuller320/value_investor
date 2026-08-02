"""Tests for CI failure → engineering task drafting."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.ci_fix_tasks import (
    build_allowed_paths_for_failures,
    draft_ci_fix_task,
    parse_pytest_failures_from_log,
    task_allowed_paths_eligible_for_auto_merge,
    task_eligible_for_auto_merge,
)
from value_investor.engineering_tasks import BLOCKED_PATHS, EngineeringTask, load_engineering_tasks


SAMPLE_LOG = """
tests/test_ops_monitor.py:275: AssertionError
=========================== short test summary info ============================
FAILED tests/test_ops_monitor.py::test_run_ops_monitor_writes_status - json.decoder.JSONDecodeError
FAILED tests/test_data_library.py::test_cli_list_and_status - json.decoder.JSONDecodeError
8 failed, 519 passed in 71.88s
"""


def test_parse_pytest_failures_from_log_extracts_unique_tests():
    failures = parse_pytest_failures_from_log(SAMPLE_LOG)
    paths = {row["test_path"] for row in failures}
    assert "tests/test_ops_monitor.py" in paths
    assert "tests/test_data_library.py" in paths


def test_build_allowed_paths_for_failures_includes_tests_and_sources():
    failures = parse_pytest_failures_from_log(SAMPLE_LOG)
    paths = build_allowed_paths_for_failures(failures)
    assert "tests/test_ops_monitor.py" in paths
    assert "src/value_investor/ops_monitor.py" in paths
    assert "tests/conftest.py" in paths
    assert ".github/workflows/ci.yml" in paths


def test_task_allowed_paths_eligible_for_auto_merge_rejects_blocked_paths():
    assert not task_allowed_paths_eligible_for_auto_merge(["docs/data/library/policy.json"])
    assert task_allowed_paths_eligible_for_auto_merge(
        ["tests/test_ops_monitor.py", "src/value_investor/ops_monitor.py"]
    )


def test_draft_ci_fix_task_appends_open_task(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(json.dumps({"tasks": []}), encoding="utf-8")
    failures = parse_pytest_failures_from_log(SAMPLE_LOG)
    drafted = draft_ci_fix_task(failures, run_id=123, tasks_path=tasks_path)
    assert drafted
    payload = load_engineering_tasks(tasks_path)
    task = payload["tasks"][0]
    assert task["area"] == "ci"
    assert task["source"] == "ci_failure"
    assert task["auto_merge"] is True
    assert task["priority_score"] == 95.0


def test_task_eligible_for_auto_merge_requires_flag_and_scope():
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
    )
    assert task_eligible_for_auto_merge(task)
    task.auto_merge = False
    assert not task_eligible_for_auto_merge(task)
