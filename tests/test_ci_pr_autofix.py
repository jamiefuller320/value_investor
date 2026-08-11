"""Tests for PR CI ruff autofix."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from value_investor.ci_pr_autofix import (
    AUTOFIX_COMMIT_PREFIX,
    attempt_pr_ci_autofix,
    autofix_already_attempted,
    classify_ci_log_failures,
)

RUFF_FORMAT_LOG = """
Ruff scope (1 file(s)): src/bad.py
unformatted: File would be reformatted
ruff format failed (exit 1)
"""

PYTEST_LOG = """
FAILED tests/test_ops_monitor.py::test_run - AssertionError
8 failed, 519 passed
"""


def test_classify_ci_log_failures_ruff():
    kinds = classify_ci_log_failures(RUFF_FORMAT_LOG)
    assert "ruff_format" in kinds


def test_classify_ci_log_failures_pytest():
    kinds = classify_ci_log_failures(PYTEST_LOG)
    assert "pytest" in kinds
    assert "ruff_format" not in kinds


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


def test_autofix_already_attempted_detects_prefix(tmp_path: Path):
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
        assert autofix_already_attempted("HEAD")
    finally:
        os.chdir(prev)
