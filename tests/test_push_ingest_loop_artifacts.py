"""Regression: ingest artifact push must not commit stale ops_status overlays."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def test_push_ingest_artifacts_does_not_commit_stale_ops_status(tmp_path: Path):
    """
    Simulate the race that clobbered ops_status.json on 2026-08-27:

    1. Job starts on main with ops_status=old
    2. Concurrent ops-monitor updates ops_status=new on origin/main
    3. Ingest restores docs/data from stash WIP tree (includes old ops_status)
    4. Commit must not include ops_status — only ingest allowlisted paths
    """
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "-C", str(remote), "symbolic-ref", "HEAD", "refs/heads/main")
    _git(tmp_path, "clone", str(remote), str(work))
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "test")

    data = work / "docs" / "data"
    data.mkdir(parents=True)
    (data / "ops_status.json").write_text('{"run_at":"old","overall":"ok"}\n', encoding="utf-8")
    (data / "ingest_health_log.json").write_text('{"entries":[]}\n', encoding="utf-8")
    (work / "scripts").mkdir()
    script_src = Path("scripts/push_ingest_loop_artifacts.sh").read_text(encoding="utf-8")
    (work / "scripts" / "push_ingest_loop_artifacts.sh").write_text(script_src, encoding="utf-8")
    os.chmod(work / "scripts" / "push_ingest_loop_artifacts.sh", 0o755)

    _git(work, "add", "docs/data/ops_status.json", "docs/data/ingest_health_log.json", "scripts")
    _git(work, "commit", "-m", "seed")
    _git(work, "branch", "-M", "main")
    _git(work, "push", "-u", "origin", "main")

    # Concurrent ops-monitor update on a second clone.
    other = tmp_path / "other"
    _git(tmp_path, "clone", str(remote), str(other))
    _git(other, "config", "user.email", "test@example.com")
    _git(other, "config", "user.name", "test")
    other_ops = other / "docs" / "data" / "ops_status.json"
    assert other_ops.exists(), _git(other, "ls-files").stdout
    other_ops.write_text(
        '{"run_at":"new","overall":"fail","findings":[1]}\n',
        encoding="utf-8",
    )
    _git(other, "add", "docs/data/ops_status.json")
    _git(other, "commit", "-m", "chore: ops monitor")
    _git(other, "push", "origin", "main")

    # Ingest job still on old tip: modify health log only.
    (data / "ingest_health_log.json").write_text(
        '{"entries":[{"ok":true}]}\n',
        encoding="utf-8",
    )

    env = {**os.environ, "MAX_ATTEMPTS": "2"}
    result = subprocess.run(
        ["bash", "scripts/push_ingest_loop_artifacts.sh", "chore: weekday ingest loop [skip ci]"],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, textwrap.dedent(
        f"""
        push script failed
        stdout: {result.stdout}
        stderr: {result.stderr}
        """
    )

    _git(work, "fetch", "origin")
    ops = _git(work, "show", "origin/main:docs/data/ops_status.json").stdout
    health = _git(work, "show", "origin/main:docs/data/ingest_health_log.json").stdout
    assert '"run_at":"new"' in ops, f"ops_status was clobbered:\n{ops}"
    assert '"ok": true' in health.replace(" ", "") or '"ok":true' in health.replace(" ", "")
