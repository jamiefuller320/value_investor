"""Regression: library ingest push must stash engineering_tasks and not clobber it."""

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


def _seed_library_repo(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "-C", str(remote), "symbolic-ref", "HEAD", "refs/heads/main")
    _git(tmp_path, "clone", str(remote), str(work))
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "test")

    library = work / "docs" / "data" / "library"
    library.mkdir(parents=True)
    (library / "euro_ingest_dispatch.json").write_text('{"mode":"sprint"}\n', encoding="utf-8")
    (work / "docs" / "data" / "engineering_tasks.json").write_text(
        '{"compiled_at":"old","tasks":[]}\n',
        encoding="utf-8",
    )
    (work / "docs" / "data" / "ops_status.json").write_text(
        '{"run_at":"old","overall":"ok"}\n',
        encoding="utf-8",
    )
    (work / "scripts").mkdir()
    script_src = Path("scripts/push_library_ingest_artifacts.sh").read_text(encoding="utf-8")
    script = work / "scripts" / "push_library_ingest_artifacts.sh"
    script.write_text(script_src, encoding="utf-8")
    os.chmod(script, 0o755)

    _git(
        work,
        "add",
        "docs/data/library/euro_ingest_dispatch.json",
        "docs/data/engineering_tasks.json",
        "docs/data/ops_status.json",
        "scripts",
    )
    _git(work, "commit", "-m", "seed")
    _git(work, "branch", "-M", "main")
    _git(work, "push", "-u", "origin", "main")
    return remote, work


def _run_push(work: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "MAX_ATTEMPTS": "2"}
    return subprocess.run(
        ["bash", "scripts/push_library_ingest_artifacts.sh", "chore: euro_depth ingest loop [skip ci]"],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_push_survives_dirty_engineering_tasks_when_origin_moved(tmp_path: Path):
    """
    Reproduce the 2026-09-03 13:15 UTC euro-ingest-loop failure:

    1. Job dirty-writes engineering_tasks.json (micro-compile / compiled_at)
    2. Concurrent automation updates the same file on origin/main
    3. Push script must stash that file before checkout, then succeed
    """
    _remote, work = _seed_library_repo(tmp_path)

    other = tmp_path / "other"
    _git(tmp_path, "clone", str(_remote), str(other))
    _git(other, "config", "user.email", "test@example.com")
    _git(other, "config", "user.name", "test")
    (other / "docs" / "data" / "engineering_tasks.json").write_text(
        '{"compiled_at":"concurrent","tasks":[1]}\n',
        encoding="utf-8",
    )
    _git(other, "add", "docs/data/engineering_tasks.json")
    _git(other, "commit", "-m", "chore: engineering queue")
    _git(other, "push", "origin", "main")

    (work / "docs" / "data" / "library" / "euro_ingest_dispatch.json").write_text(
        '{"mode":"sprint","run":"job"}\n',
        encoding="utf-8",
    )
    (work / "docs" / "data" / "engineering_tasks.json").write_text(
        '{"compiled_at":"job","tasks":[{"id":"eng-job"}]}\n',
        encoding="utf-8",
    )

    result = _run_push(work)
    assert result.returncode == 0, textwrap.dedent(
        f"""
        push script failed
        stdout: {result.stdout}
        stderr: {result.stderr}
        """
    )

    _git(work, "fetch", "origin")
    dispatch = _git(work, "show", "origin/main:docs/data/library/euro_ingest_dispatch.json").stdout
    tasks = _git(work, "show", "origin/main:docs/data/engineering_tasks.json").stdout
    assert '"run":"job"' in dispatch.replace(" ", ""), dispatch
    assert '"compiled_at":"job"' in tasks.replace(" ", ""), tasks


def test_push_preserves_untouched_engineering_tasks(tmp_path: Path):
    """If ingest did not touch engineering_tasks.json, keep origin's concurrent update."""
    _remote, work = _seed_library_repo(tmp_path)

    other = tmp_path / "other"
    _git(tmp_path, "clone", str(_remote), str(other))
    _git(other, "config", "user.email", "test@example.com")
    _git(other, "config", "user.name", "test")
    (other / "docs" / "data" / "engineering_tasks.json").write_text(
        '{"compiled_at":"concurrent","tasks":[1]}\n',
        encoding="utf-8",
    )
    _git(other, "add", "docs/data/engineering_tasks.json")
    _git(other, "commit", "-m", "chore: engineering queue")
    _git(other, "push", "origin", "main")

    (work / "docs" / "data" / "library" / "euro_ingest_dispatch.json").write_text(
        '{"mode":"sprint","run":"job"}\n',
        encoding="utf-8",
    )

    result = _run_push(work)
    assert result.returncode == 0, textwrap.dedent(
        f"""
        push script failed
        stdout: {result.stdout}
        stderr: {result.stderr}
        """
    )

    _git(work, "fetch", "origin")
    dispatch = _git(work, "show", "origin/main:docs/data/library/euro_ingest_dispatch.json").stdout
    tasks = _git(work, "show", "origin/main:docs/data/engineering_tasks.json").stdout
    assert '"run":"job"' in dispatch.replace(" ", ""), dispatch
    assert '"compiled_at":"concurrent"' in tasks.replace(" ", ""), tasks


def test_push_does_not_commit_stale_ops_status(tmp_path: Path):
    _remote, work = _seed_library_repo(tmp_path)

    other = tmp_path / "other"
    _git(tmp_path, "clone", str(_remote), str(other))
    _git(other, "config", "user.email", "test@example.com")
    _git(other, "config", "user.name", "test")
    (other / "docs" / "data" / "ops_status.json").write_text(
        '{"run_at":"new","overall":"fail"}\n',
        encoding="utf-8",
    )
    _git(other, "add", "docs/data/ops_status.json")
    _git(other, "commit", "-m", "chore: ops monitor")
    _git(other, "push", "origin", "main")

    (work / "docs" / "data" / "library" / "euro_ingest_dispatch.json").write_text(
        '{"mode":"sprint","run":"job"}\n',
        encoding="utf-8",
    )
    (work / "docs" / "data" / "ops_status.json").write_text(
        '{"run_at":"stale-job","overall":"ok"}\n',
        encoding="utf-8",
    )

    result = _run_push(work)
    assert result.returncode == 0, textwrap.dedent(
        f"""
        push script failed
        stdout: {result.stdout}
        stderr: {result.stderr}
        """
    )

    _git(work, "fetch", "origin")
    ops = _git(work, "show", "origin/main:docs/data/ops_status.json").stdout
    dispatch = _git(work, "show", "origin/main:docs/data/library/euro_ingest_dispatch.json").stdout
    assert '"run_at":"new"' in ops.replace(" ", ""), f"ops_status was clobbered:\n{ops}"
    assert '"run":"job"' in dispatch.replace(" ", ""), dispatch
