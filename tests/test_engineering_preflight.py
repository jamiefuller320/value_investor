"""Tests for engineering preflight and clash-aware dispatch."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from value_investor.engineering_preflight import (
    CLASH_KIND_ALLOWLIST,
    CLASH_KIND_FILE,
    CLASH_KIND_SHARED,
    build_open_pr_file_index,
    estimated_task_files,
    file_overlap,
    predict_task_clashes,
    run_local_preflight,
    select_clash_aware_dispatch_tasks,
)
from value_investor.engineering_queue import (
    build_engineering_queue_dashboard,
    evaluate_engineering_dispatch,
    select_path_disjoint_engineering_tasks,
)
from value_investor.engineering_tasks import EngineeringTask
from value_investor.engineering_verify import preflight_pytest_paths


def _task(
    task_id: str,
    *,
    status: str = "open",
    area: str = "ingest",
    allowed_paths: list[str] | None = None,
    branch_name: str | None = None,
) -> EngineeringTask:
    return EngineeringTask(
        id=task_id,
        area=area,
        title=f"Task {task_id}",
        summary=f"Task {task_id}",
        priority="high",
        priority_score=90.0,
        source="post_run_review",
        status=status,
        allowed_paths=allowed_paths or ["src/value_investor/research/ingest.py"],
        branch_name=branch_name,
    )


def test_file_overlap_and_shared_mutable():
    overlap = file_overlap(
        ["docs/data/engineering_tasks.json", "src/foo.py"],
        ["docs/data/engineering_tasks.json"],
    )
    assert overlap == ["docs/data/engineering_tasks.json"]


def test_predict_task_clashes_allowlist():
    task = _task("eng-20260726-01", allowed_paths=["src/value_investor/summary.py"])
    report = predict_task_clashes(
        task,
        occupied_paths=["src/value_investor/summary.py"],
        open_pr_index=[],
        candidate_files=["src/value_investor/summary.py"],
    )
    assert not report.dispatch_eligible
    assert report.blocked_by[0].kind == CLASH_KIND_ALLOWLIST


def test_predict_task_clashes_file_overlap_on_open_pr():
    task = _task("eng-20260726-01", allowed_paths=["src/value_investor/research/ingest.py"])
    pr_index = [
        {
            "number": 42,
            "branch": "cursor/eng-20260726-02-1de3",
            "title": "other",
            "task_id": "eng-20260726-02",
            "changed_files": ["src/value_investor/research/ingest.py"],
        }
    ]
    report = predict_task_clashes(
        task,
        occupied_paths=[],
        open_pr_index=pr_index,
        candidate_files=["src/value_investor/research/ingest.py"],
        skip_merge_tree=True,
    )
    assert not report.dispatch_eligible
    assert report.blocked_by[0].kind == CLASH_KIND_FILE
    assert report.blocked_by[0].pr_number == 42


def test_predict_task_clashes_shared_mutable():
    task = _task("eng-20260726-01")
    pr_index = [
        {
            "number": 7,
            "branch": "cursor/other-1de3",
            "title": "other",
            "task_id": None,
            "changed_files": ["docs/data/engineering_tasks.json"],
        }
    ]
    report = predict_task_clashes(
        task,
        occupied_paths=[],
        open_pr_index=pr_index,
        candidate_files=["docs/data/engineering_tasks.json", "src/foo.py"],
        skip_merge_tree=True,
    )
    assert not report.dispatch_eligible
    assert report.blocked_by[0].kind == CLASH_KIND_SHARED


def test_select_clash_aware_overtakes_blocked_task(monkeypatch):
    payload = {
        "tasks": [
            _task(
                "eng-20260726-01",
                allowed_paths=["src/value_investor/summary.py"],
            ).to_dict(),
            _task(
                "eng-20260726-02",
                status="pr_open",
                area="scoring",
                allowed_paths=["src/value_investor/summary.py"],
                branch_name="cursor/eng-20260726-02-1de3",
            ).to_dict(),
            _task(
                "eng-20260726-03",
                allowed_paths=["src/value_investor/research/ingest.py"],
            ).to_dict(),
        ]
    }
    pr_index = [
        {
            "number": 112,
            "branch": "cursor/eng-20260726-02-1de3",
            "title": "scoring",
            "task_id": "eng-20260726-02",
            "changed_files": ["src/value_investor/summary.py"],
        }
    ]
    monkeypatch.setattr(
        "value_investor.engineering_preflight.build_open_pr_file_index",
        lambda *args, **kwargs: pr_index,
    )
    selected, reports = select_clash_aware_dispatch_tasks(
        payload,
        max_tasks=1,
        blocked_paths=["src/value_investor/summary.py"],
        open_prs=[{"number": 112, "headRefName": "cursor/eng-20260726-02-1de3", "title": "x"}],
    )
    assert [task.id for task in selected] == ["eng-20260726-03"]
    blocked = next(row for row in reports if row.task.id == "eng-20260726-01")
    assert not blocked.dispatch_eligible


def test_select_path_disjoint_uses_open_prs(monkeypatch):
    payload = {
        "tasks": [
            _task("eng-20260726-01", allowed_paths=["src/value_investor/summary.py"]).to_dict(),
            _task(
                "eng-20260726-03",
                allowed_paths=["src/value_investor/research/ingest.py"],
            ).to_dict(),
        ]
    }

    def fake_index(open_prs, *, repo=None, cache=None):
        return [
            {
                "number": 9,
                "branch": "cursor/other-1de3",
                "title": "blocker",
                "task_id": None,
                "changed_files": ["src/value_investor/research/ingest.py"],
            }
        ]

    monkeypatch.setattr(
        "value_investor.engineering_preflight.build_open_pr_file_index",
        fake_index,
    )
    picked = select_path_disjoint_engineering_tasks(
        payload,
        max_tasks=1,
        open_prs=[{"number": 9, "headRefName": "cursor/other-1de3"}],
    )
    assert [task.id for task in picked] == ["eng-20260726-01"]


def test_evaluate_dispatch_blocks_on_shared_mutable_clash(tmp_path: Path, monkeypatch):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            _task("eng-20260726-01", allowed_paths=["src/value_investor/summary.py"]).to_dict(),
            _task(
                "eng-20260726-02",
                status="pr_open",
                allowed_paths=["src/value_investor/summary.py"],
                branch_name="cursor/eng-20260726-02-1de3",
            ).to_dict(),
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")

    def fake_index(open_prs, *, repo=None, cache=None):
        return [
            {
                "number": 112,
                "branch": "cursor/eng-20260726-02-1de3",
                "title": "scoring",
                "task_id": "eng-20260726-02",
                "changed_files": ["src/value_investor/summary.py"],
            }
        ]

    monkeypatch.setattr(
        "value_investor.engineering_preflight.build_open_pr_file_index",
        fake_index,
    )
    decision = evaluate_engineering_dispatch(
        tasks_path=tasks_path,
        open_prs=[{"number": 112, "headRefName": "cursor/eng-20260726-02-1de3"}],
        max_parallel=2,
    )
    assert decision.should_dispatch is False
    assert "dispatch-eligible" in decision.reason


def test_build_dashboard_includes_dispatch_metadata(tmp_path: Path, monkeypatch):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {"tasks": [_task("eng-20260726-01").to_dict()]}
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(
        "value_investor.engineering_preflight.build_open_pr_file_index",
        lambda *args, **kwargs: [],
    )
    dash = build_engineering_queue_dashboard(tasks_path=tasks_path, open_prs=[])
    row = dash["queued_tasks"][0]
    assert "dispatch_eligible" in row
    assert "clash_summary" in dash


def test_preflight_pytest_paths_prefers_changed_test_modules():
    task = _task(
        "eng-20260726-01",
        allowed_paths=[
            "src/value_investor/research/filings.py",
            "tests/test_research_filings.py",
            "tests/test_research_ingest.py",
        ],
    )
    scoped = preflight_pytest_paths(
        task,
        [
            "src/value_investor/research/filings.py",
            "tests/test_research_filings.py",
        ],
    )
    assert scoped == ["tests/test_research_filings.py"]


def test_run_local_preflight_path_guard(tmp_path: Path):
    task = _task(
        "eng-20260726-01",
        allowed_paths=["src/value_investor/research/ingest.py"],
    )
    report = run_local_preflight(
        task,
        changed_files=["src/value_investor/paper_fund.py"],
        skip_pytest=True,
        skip_clash=True,
    )
    assert not report.ok
    assert report.checks[0].name == "path_guard"
    assert not report.checks[0].ok


def test_estimated_task_files_include_shared_mutable():
    task = _task("eng-20260726-01", allowed_paths=["src/value_investor/research/ingest.py"])
    files = estimated_task_files(task)
    assert "docs/data/engineering_tasks.json" in files


def test_git_merge_tree_conflicts_in_repo():
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return
    head = proc.stdout.strip()
    from value_investor.engineering_preflight import git_merge_tree_conflicts

    assert git_merge_tree_conflicts(head, head) is False


def test_build_open_pr_file_index_uses_cache(monkeypatch):
    calls: list[int] = []

    def fake_changed_files(pr_number, *, repo=None):
        calls.append(pr_number)
        return [f"file{pr_number}.py"]

    monkeypatch.setattr(
        "value_investor.engineering_preflight.changed_files_for_pr",
        fake_changed_files,
    )
    rows = [{"number": 5, "headRefName": "cursor/eng-20260726-01-1de3", "title": "t"}]
    cache: dict[int, list[str]] = {}
    first = build_open_pr_file_index(rows, cache=cache)
    second = build_open_pr_file_index(rows, cache=cache)
    assert first[0]["changed_files"] == ["file5.py"]
    assert second[0]["changed_files"] == ["file5.py"]
    assert calls == [5]
