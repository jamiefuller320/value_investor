"""Tests for engineering PR path guard."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.engineering_tasks import (
    BLOCKED_PATHS,
    EngineeringTask,
    find_engineering_task,
    normalize_repo_path,
    path_matches_allowed_pattern,
    path_matches_blocked_pattern,
    validate_engineering_pr_paths,
    validate_engineering_pr_paths_for_task_id,
)


def _ingest_task() -> EngineeringTask:
    return EngineeringTask(
        id="eng-20260726-01",
        area="ingest",
        title="Fetch IR PDFs",
        summary="Fetch IR PDFs",
        priority="high",
        priority_score=99.0,
        source="post_run_review",
        allowed_paths=[
            "src/value_investor/research/filings.py",
            "tests/test_research_filings.py",
        ],
        blocked_paths=list(BLOCKED_PATHS),
    )


def test_normalize_repo_path():
    assert normalize_repo_path("./src/foo.py") == "src/foo.py"
    assert normalize_repo_path("src\\foo.py") == "src/foo.py"


def test_path_matches_allowed_pattern_directory_and_file():
    assert path_matches_allowed_pattern(
        "src/value_investor/models/piotroski.py",
        "src/value_investor/models/",
    )
    assert path_matches_allowed_pattern(
        "tests/test_pipeline.py",
        "tests/test_pipeline.py",
    )
    assert not path_matches_allowed_pattern(
        "src/value_investor/pipeline.py",
        "tests/test_pipeline.py",
    )


def test_path_matches_blocked_pattern_exact_only():
    assert path_matches_blocked_pattern(
        "src/value_investor/paper_fund.py",
        "src/value_investor/paper_fund.py",
    )
    assert not path_matches_blocked_pattern(
        "src/value_investor/paper_fund_extra.py",
        "src/value_investor/paper_fund.py",
    )


def test_validate_engineering_pr_paths_allows_listed_files():
    task = _ingest_task()
    result = validate_engineering_pr_paths(
        task=task,
        changed_files=[
            "src/value_investor/research/filings.py",
            "tests/test_research_filings.py",
        ],
    )
    assert result.ok
    assert result.violations == []


def test_validate_engineering_pr_paths_rejects_outside_allowed():
    task = _ingest_task()
    result = validate_engineering_pr_paths(
        task=task,
        changed_files=["src/value_investor/pipeline.py"],
    )
    assert not result.ok
    assert any("outside allowed_paths" in item for item in result.violations)


def test_validate_engineering_pr_paths_rejects_blocked_paths():
    task = _ingest_task()
    result = validate_engineering_pr_paths(
        task=task,
        changed_files=["src/value_investor/paper_fund.py"],
    )
    assert not result.ok
    assert any("blocked path touched" in item for item in result.violations)


def test_validate_engineering_pr_paths_for_task_id_from_queue_file(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(
        json.dumps({"tasks": [_ingest_task().to_dict()]}),
        encoding="utf-8",
    )
    result = validate_engineering_pr_paths_for_task_id(
        "eng-20260726-01",
        ["src/value_investor/research/filings.py"],
        tasks_path=tasks_path,
    )
    assert result.ok
    assert find_engineering_task("eng-20260726-01", path=tasks_path) is not None
