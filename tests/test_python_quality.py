"""Tests for scoped Python quality checks."""

from __future__ import annotations

import subprocess
from pathlib import Path

from value_investor.python_quality import git_changed_files, run_ruff_on_files


def test_git_changed_files_filters_prefix_and_extension(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src" / "value_investor").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "src" / "value_investor" / "foo.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "tests" / "test_foo.py").write_text("def test_x(): pass\n", encoding="utf-8")
    (repo / "docs" / "app.js").parent.mkdir(parents=True)
    (repo / "docs" / "app.js").write_text("", encoding="utf-8")

    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init", "--author", "test <test@example.com>"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "checkout", "-b", "feature"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "src" / "value_investor" / "bar.py").write_text("y = 2\n", encoding="utf-8")
    (repo / "docs" / "app.js").write_text("console.log(1)\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "feature", "--author", "test <test@example.com>"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    files = git_changed_files(
        base_ref="main",
        head_ref="HEAD",
        prefixes=("src/", "tests/"),
        repo_root=repo,
    )
    assert files == [Path("src/value_investor/bar.py")]


def test_run_ruff_on_files_skips_when_empty():
    code, logs = run_ruff_on_files([])
    assert code == 0
    assert any("skipping" in line.lower() for line in logs)


def test_run_ruff_on_files_passes_clean_file(tmp_path: Path):
    path = tmp_path / "clean.py"
    path.write_text("def tidy() -> int:\n    return 1\n", encoding="utf-8")
    code, logs = run_ruff_on_files([path])
    assert code == 0
    assert any("passed" in line for line in logs)
