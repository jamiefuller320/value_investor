"""Retry engineering-queue commits so concurrent main writers do not fail the workflow."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path

SCRIPT = Path("scripts/gha_commit_engineering_queue.sh")
WORKFLOW = Path(".github/workflows/engineering-queue.yml")


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _seed_repo(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "-C", str(remote), "symbolic-ref", "HEAD", "refs/heads/main")
    _git(tmp_path, "clone", str(remote), str(work))
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "test")

    _write_json(work / "docs" / "data" / "engineering_tasks.json", {"tasks": []})
    _write_json(work / "docs" / "data" / "automation.json", {"engineering_queue": {}})
    _write_json(work / "docs" / "data" / "latest.json", {})
    scripts_dir = work / "scripts"
    scripts_dir.mkdir()
    for name in ("gha_commit_engineering_queue.sh", "gha_commit_artifacts.sh"):
        script = scripts_dir / name
        script.write_text(Path("scripts", name).read_text(encoding="utf-8"), encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)

    _git(work, "add", "docs", "scripts")
    _git(work, "commit", "-m", "seed")
    _git(work, "branch", "-M", "main")
    _git(work, "push", "-u", "origin", "main")
    return remote, work


def _install_pre_receive(remote: Path, *, reject_first_n: int) -> None:
    hook = remote / "hooks" / "pre-receive"
    count = remote / "reject_count"
    count.write_text("0\n", encoding="utf-8")
    hook.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            count_file="{count}"
            n=$(cat "$count_file")
            n=$((n + 1))
            echo "$n" > "$count_file"
            if [ "$n" -le {int(reject_first_n)} ]; then
              echo "test race: reject push $n" >&2
              exit 1
            fi
            exit 0
            """
        ),
        encoding="utf-8",
    )
    hook.chmod(hook.stat().st_mode | stat.S_IEXEC)


def _run_script(work: Path, *, attempts: str = "5") -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "GHA_COMMIT_ATTEMPTS": attempts,
        "GHA_COMMIT_SLEEP_BASE": "0",
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
    }
    return subprocess.run(
        ["bash", "scripts/gha_commit_engineering_queue.sh"],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_engineering_queue_commit_retries_after_push_race(tmp_path: Path):
    remote, work = _seed_repo(tmp_path)
    _install_pre_receive(remote, reject_first_n=1)
    _write_json(
        work / "docs" / "data" / "engineering_tasks.json",
        {"tasks": [{"id": "eng-1", "status": "open"}]},
    )

    result = _run_script(work)
    assert result.returncode == 0, result.stderr
    assert "attempt 2/5" in result.stdout

    latest = tmp_path / "latest"
    _git(tmp_path, "clone", str(remote), str(latest))
    tasks = _read_json(latest / "docs" / "data" / "engineering_tasks.json")["tasks"]
    assert tasks[0]["id"] == "eng-1"


def test_engineering_queue_workflow_uses_retry_commit_helper() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/gha_commit_engineering_queue.sh" in text
    assert text.count("stefanzweifel/git-auto-commit-action@v6") == 0
    assert "Sync main before queue file commit" not in text
