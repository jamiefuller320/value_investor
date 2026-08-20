"""Tests for post-merge acceptance verify + capped rework."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.engineering_verify import (
    MAX_VERIFY_REWORK_ROUNDS,
    VERIFY_SOURCE,
    acceptance_test_paths,
    count_verify_chain_rounds,
    is_pytest_infra_failure,
    should_run_acceptance_verify,
    verify_merged_task,
)


def _write_tasks(path: Path, tasks: list[dict]) -> None:
    path.write_text(
        json.dumps({"tasks": tasks, "task_count": len(tasks)}, indent=2),
        encoding="utf-8",
    )


def _merged_scoring_task(**overrides) -> dict:
    row = {
        "id": "eng-20260819-03",
        "area": "scoring",
        "title": "Implement fcf_values_diverge overlay",
        "summary": "Suppress divergent screen TTM FCF",
        "priority": "high",
        "priority_score": 99.0,
        "source": "post_run_review",
        "status": "merged",
        "merged_at": "2026-08-19T13:21:14+00:00",
        "pr_number": 301,
        "pr_url": "https://example.test/pr/301",
        "branch_name": "cursor/eng-20260819-03-1de3",
        "acceptance_criteria": ["Export or overlay behaviour is covered by a unit test"],
        "allowed_paths": [
            "src/value_investor/scoring/",
            "tests/test_pipeline.py",
            "tests/test_summary.py",
        ],
        "blocked_paths": [],
        "evidence": {"tickers": ["FCF", "TTM"]},
        "auto_merge": False,
    }
    row.update(overrides)
    return row


def test_acceptance_test_paths_filters_tests_only():
    assert acceptance_test_paths(_merged_scoring_task()) == [
        "tests/test_pipeline.py",
        "tests/test_summary.py",
    ]


def test_should_skip_gap_closure_owned_tasks():
    task = _merged_scoring_task(
        evidence={"rerun_ingest_gap_closure": True, "ticker": "ITV.L"},
    )
    ok, reason = should_run_acceptance_verify(task)
    assert ok is False
    assert reason == "ingest_gap_closure_owns_verification"


def test_verify_merged_passes_and_stamps_evidence(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    _write_tasks(tasks_path, [_merged_scoring_task()])

    def runner(paths, cwd):
        assert paths == ["tests/test_pipeline.py", "tests/test_summary.py"]
        return {
            "ok": True,
            "returncode": 0,
            "paths": paths,
            "existing_paths": paths,
            "output": "2 passed",
        }

    result = verify_merged_task(
        "eng-20260819-03",
        tasks_path=tasks_path,
        cwd=tmp_path,
        pytest_runner=runner,
    )
    assert result["action"] == "passed"
    assert result["should_rework"] is False
    updated = json.loads(tasks_path.read_text(encoding="utf-8"))["tasks"][0]
    assert updated["evidence"]["verify_status"] == "passed"
    assert updated["evidence"]["verify_chain_root_id"] == "eng-20260819-03"


def test_verify_merged_queues_rework_on_failure(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    _write_tasks(tasks_path, [_merged_scoring_task()])

    def runner(paths, cwd):
        return {
            "ok": False,
            "returncode": 1,
            "paths": paths,
            "existing_paths": paths,
            "output": "FAILED tests/test_pipeline.py::test_fcf",
        }

    result = verify_merged_task(
        "eng-20260819-03",
        tasks_path=tasks_path,
        cwd=tmp_path,
        pytest_runner=runner,
    )
    assert result["action"] == "rework_queued"
    assert result["should_rework"] is True
    assert result["verify_round"] == 2
    assert result["rework_task_id"]
    payload = json.loads(tasks_path.read_text(encoding="utf-8"))
    parent = next(t for t in payload["tasks"] if t["id"] == "eng-20260819-03")
    rework = next(t for t in payload["tasks"] if t["id"] == result["rework_task_id"])
    assert parent["evidence"]["verify_status"] == "rework_queued"
    assert rework["status"] == "open"
    assert rework["source"] == VERIFY_SOURCE
    assert rework["evidence"]["verify_chain_root_id"] == "eng-20260819-03"
    assert rework["evidence"]["parent_task_id"] == "eng-20260819-03"
    assert rework["evidence"]["verify_round"] == 2
    assert rework["allowed_paths"] == parent["allowed_paths"]


def test_verify_merged_exhausts_at_max_rounds(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    root = _merged_scoring_task()
    # Simulate chain already at max rounds (root + 2 prior reworks).
    prior = []
    for i in range(2, MAX_VERIFY_REWORK_ROUNDS + 1):
        prior.append(
            {
                "id": f"eng-20260819-{10 + i:02d}",
                "area": "scoring",
                "title": f"Rework verify round {i}",
                "summary": "prior",
                "priority": "high",
                "priority_score": 100.0,
                "source": VERIFY_SOURCE,
                "status": "merged",
                "allowed_paths": root["allowed_paths"],
                "acceptance_criteria": root["acceptance_criteria"],
                "blocked_paths": [],
                "evidence": {
                    "verify_chain_root_id": "eng-20260819-03",
                    "parent_task_id": "eng-20260819-03",
                    "verify_round": i,
                },
            }
        )
    # Latest merged attempt is the last rework; verify that one.
    latest = prior[-1]
    latest["status"] = "merged"
    latest["allowed_paths"] = root["allowed_paths"]
    _write_tasks(tasks_path, [root, *prior])

    assert count_verify_chain_rounds("eng-20260819-03", tasks_path=tasks_path) == 3

    def runner(paths, cwd):
        return {
            "ok": False,
            "returncode": 1,
            "paths": paths,
            "existing_paths": paths,
            "output": "still failing",
        }

    result = verify_merged_task(
        latest["id"],
        tasks_path=tasks_path,
        cwd=tmp_path,
        pytest_runner=runner,
    )
    assert result["action"] == "exhausted"
    assert result["should_rework"] is False
    updated = next(
        t
        for t in json.loads(tasks_path.read_text(encoding="utf-8"))["tasks"]
        if t["id"] == latest["id"]
    )
    assert updated["evidence"]["verify_status"] == "exhausted"


def test_is_pytest_infra_failure_detects_missing_module():
    assert is_pytest_infra_failure(
        {
            "ok": False,
            "returncode": 1,
            "output": "/opt/hostedtoolcache/Python/3.12.14/x64/bin/python3: No module named pytest",
        }
    )
    assert not is_pytest_infra_failure(
        {
            "ok": False,
            "returncode": 1,
            "output": "FAILED tests/test_pipeline.py::test_fcf - AssertionError",
        }
    )


def test_verify_merged_skips_rework_on_pytest_infra_failure(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    _write_tasks(tasks_path, [_merged_scoring_task()])

    def runner(paths, cwd):
        return {
            "ok": False,
            "returncode": 1,
            "paths": paths,
            "existing_paths": paths,
            "output": "python3: No module named pytest",
        }

    result = verify_merged_task(
        "eng-20260819-03",
        tasks_path=tasks_path,
        cwd=tmp_path,
        pytest_runner=runner,
    )
    assert result["action"] == "infra_error"
    assert result["should_rework"] is False
    assert result["reason"] == "pytest_not_installed"
    payload = json.loads(tasks_path.read_text(encoding="utf-8"))
    assert len(payload["tasks"]) == 1
    assert "verify_status" not in (payload["tasks"][0].get("evidence") or {})


def test_verify_merged_dry_run_does_not_write(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    original = [_merged_scoring_task()]
    _write_tasks(tasks_path, original)

    def runner(paths, cwd):
        return {
            "ok": False,
            "returncode": 1,
            "paths": paths,
            "existing_paths": paths,
            "output": "fail",
        }

    result = verify_merged_task(
        "eng-20260819-03",
        tasks_path=tasks_path,
        cwd=tmp_path,
        pytest_runner=runner,
        apply=False,
    )
    assert result["action"] == "rework_queued"
    assert result["rework_task_id"] is None
    payload = json.loads(tasks_path.read_text(encoding="utf-8"))
    assert len(payload["tasks"]) == 1
    assert "verify_status" not in (payload["tasks"][0].get("evidence") or {})
