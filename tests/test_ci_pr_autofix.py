"""Tests for PR CI autofix."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from value_investor.ci_pr_autofix import (
    AUTOFIX_COMMIT_PREFIX,
    _suggest_companion_paths,
    attempt_engineering_path_guard_autofix,
    attempt_pr_ci_autofix,
    autofix_skip_verify_pytest,
    ci_bot_already_attempted,
    classify_ci_log_failures,
    diagnose_pr_ci_failure,
    is_incidental_research_artifact,
    is_library_cache_json,
    is_timestamp_only_library_cache_change,
    parse_path_guard_violations,
    path_guard_actions_skip_verify_pytest,
    run_pr_ci_autofix_pipeline,
)
from value_investor.engineering_tasks import validate_engineering_pr_paths_for_task_id

RUFF_FORMAT_LOG = """
Ruff scope (1 file(s)): src/bad.py
unformatted: File would be reformatted
ruff format failed (exit 1)
"""

PYTEST_LOG = """
FAILED tests/test_ops_monitor.py::test_run - AssertionError
8 failed, 519 passed
"""

PATH_GUARD_LOG = """
Engineering path guard failed for eng-20260812-03:
  - outside allowed_paths: tests/test_trial_engineering_chain.py
"""


def test_classify_ci_log_failures_ruff():
    kinds = classify_ci_log_failures(RUFF_FORMAT_LOG)
    assert "ruff_format" in kinds


def test_classify_ci_log_failures_pytest():
    kinds = classify_ci_log_failures(PYTEST_LOG)
    assert "pytest" in kinds
    assert "ruff_format" not in kinds


def test_classify_ci_log_failures_path_guard():
    kinds = classify_ci_log_failures(PATH_GUARD_LOG)
    assert "path_guard" in kinds


def test_parse_path_guard_violations():
    paths = parse_path_guard_violations(PATH_GUARD_LOG)
    assert paths == ["tests/test_trial_engineering_chain.py"]


def test_is_incidental_research_artifact():
    assert is_incidental_research_artifact("docs/research/IMB.L/sources/screening_snapshot.json")
    assert is_incidental_research_artifact(
        "docs/data/research/DNLM.L/sources/peer_model_pass_table.json"
    )
    assert not is_incidental_research_artifact("tests/test_summary.py")
    assert not is_incidental_research_artifact("docs/research/IMB.L/memo.md")


def test_path_guard_actions_skip_verify_pytest():
    assert path_guard_actions_skip_verify_pytest(["path_guard_revert"])
    assert path_guard_actions_skip_verify_pytest(["path_guard_revert", "path_guard_expand"])
    assert not path_guard_actions_skip_verify_pytest(["ruff"])
    assert not path_guard_actions_skip_verify_pytest([])


def test_autofix_skip_verify_pytest_ruff_only_without_pytest_failure():
    assert autofix_skip_verify_pytest(["ruff"], ci_failure_kinds=["ruff_format"])
    assert not autofix_skip_verify_pytest(["ruff"], ci_failure_kinds=["ruff_format", "pytest"])
    assert autofix_skip_verify_pytest(
        ["path_guard_revert"],
        ci_failure_kinds=["path_guard"],
    )


def test_suggest_companion_paths_flattens_nested_research_modules():
    extras = _suggest_companion_paths(["src/value_investor/research/ingest.py"])
    assert "tests/test_research_ingest.py" in extras
    extras = _suggest_companion_paths(["tests/test_research_ingest.py"])
    assert "src/value_investor/research/ingest.py" in extras


def test_diagnose_pr_ci_failure_engineering_branch():
    diag = diagnose_pr_ci_failure(
        branch="cursor/eng-20260812-03-1de3",
        log_text=PATH_GUARD_LOG + PYTEST_LOG,
    )
    assert diag.engineering_task_id == "eng-20260812-03"
    assert "path_guard" in diag.kinds
    assert "pytest" in diag.kinds
    assert diag.path_guard_violations == ["tests/test_trial_engineering_chain.py"]


def _init_git_repo(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True)


def test_attempt_pr_ci_autofix_applies_ruff(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    src = repo / "src"
    src.mkdir()
    bad = src / "bad.py"
    bad.write_text("def f( x ):\n    return x\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)

    subprocess.run(["git", "checkout", "-b", "feature"], cwd=repo, check=True)
    bad.write_text("def f(  x  ):\n    return x\n", encoding="utf-8")
    subprocess.run(["git", "add", bad], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "feature"], cwd=repo, check=True)

    prev = os.getcwd()
    os.chdir(repo)
    try:
        result = attempt_pr_ci_autofix(
            base_ref="main",
            head_ref="HEAD",
            log_text=RUFF_FORMAT_LOG,
        )
    finally:
        os.chdir(prev)

    assert result.fixed is True
    assert "ruff_format" in result.kinds


def test_attempt_pr_ci_autofix_skips_pytest_only():
    result = attempt_pr_ci_autofix(
        base_ref="origin/main",
        head_ref="HEAD",
        log_text=PYTEST_LOG,
    )
    assert result.fixed is False
    assert "pytest" in result.reason or "pytest" in result.kinds


def test_attempt_engineering_path_guard_autofix_expands_allowlist(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    data_dir = repo / "docs" / "data"
    data_dir.mkdir(parents=True)
    eng_path = data_dir / "engineering_tasks.json"
    eng_path.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "eng-20260812-03",
                        "area": "ingest",
                        "title": "GSK gaps",
                        "summary": "test",
                        "priority": "high",
                        "priority_score": 88.0,
                        "source": "ingest_trial",
                        "allowed_paths": [
                            "src/value_investor/research/filings.py",
                            "tests/test_research_filings.py",
                        ],
                        "blocked_paths": [],
                        "status": "pr_open",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    test_file = repo / "tests" / "test_trial_engineering_chain.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_ok(): pass\n", encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-b", "cursor/eng-20260812-03-1de3"], cwd=repo, check=True)
    test_file.write_text("def test_ok(): pass\n\ndef test_more(): pass\n", encoding="utf-8")
    subprocess.run(["git", "add", test_file], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "eng change"], cwd=repo, check=True)

    prev = os.getcwd()
    os.chdir(repo)
    try:
        result = attempt_engineering_path_guard_autofix(
            branch="cursor/eng-20260812-03-1de3",
            base_ref="main",
            head_ref="HEAD",
            log_text=PATH_GUARD_LOG,
            tasks_path=eng_path,
        )
        guard = validate_engineering_pr_paths_for_task_id(
            "eng-20260812-03",
            ["tests/test_trial_engineering_chain.py"],
            tasks_path=eng_path,
        )
    finally:
        os.chdir(prev)

    assert result.fixed is True
    assert result.skip_verify_pytest is True
    assert guard.ok
    payload = json.loads(eng_path.read_text(encoding="utf-8"))
    allowed = payload["tasks"][0]["allowed_paths"]
    assert "tests/test_trial_engineering_chain.py" in allowed


def test_run_pr_ci_autofix_pipeline_path_guard_on_engineering_branch(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    data_dir = repo / "docs" / "data"
    data_dir.mkdir(parents=True)
    eng_path = data_dir / "engineering_tasks.json"
    eng_path.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "eng-20260812-03",
                        "area": "ingest",
                        "title": "GSK gaps",
                        "summary": "test",
                        "priority": "high",
                        "priority_score": 88.0,
                        "source": "ingest_trial",
                        "allowed_paths": ["src/value_investor/research/filings.py"],
                        "blocked_paths": [],
                        "status": "pr_open",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    test_file = repo / "tests" / "test_extra.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_x(): pass\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-b", "cursor/eng-20260812-03-1de3"], cwd=repo, check=True)
    test_file.write_text("def test_x(): pass\n\ndef test_y(): pass\n", encoding="utf-8")
    subprocess.run(["git", "add", test_file], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "eng"], cwd=repo, check=True)

    log = """
Engineering path guard failed for eng-20260812-03:
  - outside allowed_paths: tests/test_extra.py
"""
    prev = os.getcwd()
    os.chdir(repo)
    try:
        result, diagnosis = run_pr_ci_autofix_pipeline(
            branch="cursor/eng-20260812-03-1de3",
            base_ref="main",
            head_ref="HEAD",
            log_text=log,
            tasks_path=eng_path,
        )
    finally:
        os.chdir(prev)

    assert result.fixed is True
    assert "path_guard_expand" in result.actions
    assert result.skip_verify_pytest is True
    assert diagnosis.engineering_task_id == "eng-20260812-03"


def test_attempt_engineering_path_guard_autofix_reverts_incidental_snapshot(
    tmp_path: Path,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    data_dir = repo / "docs" / "data"
    data_dir.mkdir(parents=True)
    eng_path = data_dir / "engineering_tasks.json"
    eng_path.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "eng-20260908-09",
                        "area": "scoring",
                        "title": "Honour FCF action-note enforcement for IMB.L",
                        "summary": "test",
                        "priority": "medium",
                        "priority_score": 70.0,
                        "source": "so_what_closure",
                        "allowed_paths": [
                            "src/value_investor/summary.py",
                            "tests/test_summary.py",
                        ],
                        "blocked_paths": [],
                        "status": "pr_open",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    src = repo / "src" / "value_investor"
    src.mkdir(parents=True)
    summary = src / "summary.py"
    summary.write_text("VALUE = 1\n", encoding="utf-8")
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_summary.py"
    test_file.write_text("def test_ok(): pass\n", encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)
    subprocess.run(
        ["git", "checkout", "-b", "cursor/eng-20260908-09-1de3"],
        cwd=repo,
        check=True,
    )
    summary.write_text("VALUE = 2\n", encoding="utf-8")
    snapshot = repo / "docs" / "research" / "IMB.L" / "sources" / "screening_snapshot.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text('{"ticker":"IMB.L"}\n', encoding="utf-8")
    subprocess.run(["git", "add", summary, snapshot], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "eng change"], cwd=repo, check=True)

    log = """
Engineering path guard failed for eng-20260908-09:
  - outside allowed_paths: docs/research/IMB.L/sources/screening_snapshot.json
"""
    prev = os.getcwd()
    os.chdir(repo)
    try:
        result = attempt_engineering_path_guard_autofix(
            branch="cursor/eng-20260908-09-1de3",
            base_ref="main",
            head_ref="HEAD",
            log_text=log,
            tasks_path=eng_path,
        )
        guard = validate_engineering_pr_paths_for_task_id(
            "eng-20260908-09",
            ["src/value_investor/summary.py"],
            tasks_path=eng_path,
        )
    finally:
        os.chdir(prev)

    assert result.fixed is True
    assert result.actions == ["path_guard_revert"]
    assert result.skip_verify_pytest is True
    assert not snapshot.exists()
    payload = json.loads(eng_path.read_text(encoding="utf-8"))
    allowed = payload["tasks"][0]["allowed_paths"]
    assert "docs/research/IMB.L/sources/screening_snapshot.json" not in allowed
    assert guard.ok


def test_is_library_cache_json():
    assert is_library_cache_json("docs/data/library/issuer_identifiers.json")
    assert is_library_cache_json("docs/data/library/policy.json")
    assert not is_library_cache_json("docs/data/latest.json")


def test_is_timestamp_only_library_cache_change(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    cache_dir = repo / "docs" / "data" / "library"
    cache_dir.mkdir(parents=True)
    cache_path = cache_dir / "issuer_identifiers.json"
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "updated_at": "2026-09-08T17:24:35.542729+00:00",
                "issuers": {
                    "ABI.BR": {
                        "lei": "5493008H3828EMEXB082",
                        "resolved_at": "2026-09-08T17:24:35.542722+00:00",
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=repo, check=True)
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "updated_at": "2026-09-09T05:53:32.524800+00:00",
                "issuers": {
                    "ABI.BR": {
                        "lei": "5493008H3828EMEXB082",
                        "resolved_at": "2026-09-09T05:53:32.524785+00:00",
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", cache_path], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "timestamp refresh"], cwd=repo, check=True)

    prev = os.getcwd()
    os.chdir(repo)
    try:
        assert is_timestamp_only_library_cache_change(
            "docs/data/library/issuer_identifiers.json",
            base_ref="main",
            head_ref="HEAD",
        )
    finally:
        os.chdir(prev)


def test_attempt_engineering_path_guard_autofix_reverts_library_cache_timestamp(
    tmp_path: Path,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    data_dir = repo / "docs" / "data"
    data_dir.mkdir(parents=True)
    eng_path = data_dir / "engineering_tasks.json"
    eng_path.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "eng-20260909-01",
                        "area": "ingest",
                        "title": "Hunt fetchable IR source for ABI.BR",
                        "summary": "test",
                        "priority": "low",
                        "priority_score": 12.0,
                        "source": "parked_source_hunter",
                        "allowed_paths": ["tests/test_research_filings.py"],
                        "blocked_paths": [],
                        "status": "pr_open",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    cache_dir = data_dir / "library"
    cache_dir.mkdir(parents=True)
    cache_path = cache_dir / "issuer_identifiers.json"
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "updated_at": "2026-09-08T17:24:35.542729+00:00",
                "issuers": {
                    "ABI.BR": {
                        "lei": "5493008H3828EMEXB082",
                        "resolved_at": "2026-09-08T17:24:35.542722+00:00",
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_research_filings.py"
    test_file.write_text("def test_ok(): pass\n", encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)
    subprocess.run(
        ["git", "checkout", "-b", "cursor/eng-20260909-01-1de3"],
        cwd=repo,
        check=True,
    )
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "updated_at": "2026-09-09T05:53:32.524800+00:00",
                "issuers": {
                    "ABI.BR": {
                        "lei": "5493008H3828EMEXB082",
                        "resolved_at": "2026-09-09T05:53:32.524785+00:00",
                    }
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    test_file.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    subprocess.run(["git", "add", cache_path, test_file], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "eng change"], cwd=repo, check=True)

    log = """
Engineering path guard failed for eng-20260909-01:
  - outside allowed_paths: docs/data/library/issuer_identifiers.json
"""
    prev = os.getcwd()
    os.chdir(repo)
    try:
        result = attempt_engineering_path_guard_autofix(
            branch="cursor/eng-20260909-01-1de3",
            base_ref="main",
            head_ref="HEAD",
            log_text=log,
            tasks_path=eng_path,
        )
        guard = validate_engineering_pr_paths_for_task_id(
            "eng-20260909-01",
            ["tests/test_research_filings.py"],
            tasks_path=eng_path,
        )
    finally:
        os.chdir(prev)

    assert result.fixed is True
    assert result.actions == ["path_guard_revert"]
    assert result.skip_verify_pytest is True
    assert guard.ok
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert payload["updated_at"] == "2026-09-08T17:24:35.542729+00:00"


def test_ci_bot_already_attempted_detects_prefix(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", f"{AUTOFIX_COMMIT_PREFIX} ruff"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    prev = os.getcwd()
    os.chdir(repo)
    try:
        assert ci_bot_already_attempted("HEAD")
    finally:
        os.chdir(prev)
