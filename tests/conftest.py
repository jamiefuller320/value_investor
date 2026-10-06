"""Shared pytest fixtures, plus a guard against tests writing committed docs/ data."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from pinned_time import weekday_noon_utc

REPO_ROOT = Path(__file__).resolve().parent.parent
_DOCS_STATUS_KEY = pytest.StashKey[set[str] | None]()


def _docs_status() -> set[str] | None:
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all", "--", "docs"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return {line for line in out.splitlines() if line.strip()}


def _guard_active(config: pytest.Config) -> bool:
    return not hasattr(config, "workerinput") and not os.environ.get("FTSE_SKIP_DOCS_WRITE_GUARD")


def pytest_sessionstart(session: pytest.Session) -> None:
    if _guard_active(session.config):
        session.stash[_DOCS_STATUS_KEY] = _docs_status()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not _guard_active(session.config):
        return
    before = session.stash.get(_DOCS_STATUS_KEY, None)
    after = _docs_status()
    if before is None or after is None:
        return
    new = sorted(after - before)
    if not new:
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    lines = [
        "Tests wrote to committed docs/ paths (run them from tmp_path, e.g. the "
        "isolated_cwd fixture, or pass explicit paths):",
        *(f"  {row}" for row in new),
    ]
    if reporter is not None:
        reporter.write_sep("=", "docs/ write guard", red=True)
        for line in lines:
            reporter.write_line(line)
    session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.fixture
def pinned_weekday_noon_utc() -> datetime:
    return weekday_noon_utc()


@pytest.fixture
def isolated_cwd(tmp_path, monkeypatch):
    """Run from tmp_path so code using repo-relative docs/data defaults writes there."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def board_not_written(monkeypatch):
    """Dashboard bundle builds write the human-tasks board to docs/data; build it only."""
    from value_investor import human_task_cards

    monkeypatch.setattr(
        human_task_cards,
        "write_human_tasks_board",
        lambda *, data_dir=None, checklist_path=None: human_task_cards.build_human_tasks_board(
            data_dir=data_dir, checklist_path=checklist_path
        ),
    )
