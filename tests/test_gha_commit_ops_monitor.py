"""Retry ops-monitor commits so ingest/queue races do not leave stale warnings."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path

SCRIPT = Path("scripts/gha_commit_ops_monitor.sh")
WORKFLOW = Path(".github/workflows/ops-monitor.yml")


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

    _write_json(work / "docs" / "data" / "ops_status.json", {"run_at": "old", "overall": "ok"})
    _write_json(work / "docs" / "data" / "ops_monitor_log.json", {"entries": []})
    _write_json(
        work / "docs" / "data" / "engineering_tasks.json",
        {"tasks": [{"id": "eng-1", "status": "open"}]},
    )
    script = work / "scripts" / "gha_commit_ops_monitor.sh"
    script.parent.mkdir()
    script.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    _git(work, "add", "docs", "scripts")
    _git(work, "commit", "-m", "seed")
    _git(work, "branch", "-M", "main")
    _git(work, "push", "-u", "origin", "main")
    return remote, work


def _install_pre_receive(remote: Path, *, reject_first_n: int) -> Path:
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
    return count


def _run_script(work: Path, *, attempts: str = "5") -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "GHA_COMMIT_ATTEMPTS": attempts,
        "GHA_COMMIT_SLEEP_BASE": "0",
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
    }
    return subprocess.run(
        ["bash", "scripts/gha_commit_ops_monitor.sh"],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_ops_monitor_commit_retries_after_main_race(tmp_path: Path):
    remote, work = _seed_repo(tmp_path)
    _install_pre_receive(remote, reject_first_n=1)
    _write_json(work / "docs" / "data" / "ops_status.json", {"run_at": "new", "overall": "warn"})

    result = _run_script(work)
    assert result.returncode == 0, textwrap.dedent(
        f"""
        ops monitor retry script failed
        stdout: {result.stdout}
        stderr: {result.stderr}
        """
    )
    assert "attempt 2/5" in result.stdout
    latest = tmp_path / "latest"
    _git(tmp_path, "clone", str(remote), str(latest))
    assert _read_json(latest / "docs" / "data" / "ops_status.json")["run_at"] == "new"


def test_ops_monitor_commit_skips_raced_engineering_tasks(tmp_path: Path):
    remote, work = _seed_repo(tmp_path)
    other = tmp_path / "other"
    _git(tmp_path, "clone", str(remote), str(other))
    _git(other, "config", "user.email", "other@example.com")
    _git(other, "config", "user.name", "other")
    _write_json(
        other / "docs" / "data" / "engineering_tasks.json",
        {"tasks": [{"id": "eng-1", "status": "merged"}]},
    )
    _git(other, "add", "docs/data/engineering_tasks.json")
    _git(other, "commit", "-m", "concurrent queue")
    _git(other, "push", "origin", "main")

    _write_json(work / "docs" / "data" / "ops_status.json", {"run_at": "fresh", "overall": "fail"})
    _write_json(
        work / "docs" / "data" / "engineering_tasks.json",
        {"tasks": [{"id": "eng-1", "status": "open"}, {"id": "eng-stale-draft", "status": "open"}]},
    )

    result = _run_script(work)
    assert result.returncode == 0, result.stderr
    assert "Skipping docs/data/engineering_tasks.json" in result.stderr
    latest = tmp_path / "latest"
    _git(tmp_path, "clone", str(remote), str(latest))
    assert _read_json(latest / "docs" / "data" / "ops_status.json")["run_at"] == "fresh"
    tasks = _read_json(latest / "docs" / "data" / "engineering_tasks.json")["tasks"]
    assert tasks == [{"id": "eng-1", "status": "merged"}]


def test_ops_monitor_commit_keeps_queue_edits_when_main_unchanged(tmp_path: Path):
    remote, work = _seed_repo(tmp_path)
    _write_json(work / "docs" / "data" / "ops_status.json", {"run_at": "fresh", "overall": "ok"})
    _write_json(
        work / "docs" / "data" / "engineering_tasks.json",
        {"tasks": [{"id": "eng-1", "status": "open"}, {"id": "eng-2", "status": "open"}]},
    )
    result = _run_script(work)
    assert result.returncode == 0, result.stderr
    latest = tmp_path / "latest"
    _git(tmp_path, "clone", str(remote), str(latest))
    ids = [row["id"] for row in _read_json(latest / "docs" / "data" / "engineering_tasks.json")["tasks"]]
    assert ids == ["eng-1", "eng-2"]


def test_ops_monitor_workflow_commits_after_monitor_exit() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/gha_commit_ops_monitor.sh" in text
    assert "stefanzweifel/git-auto-commit-action@v6" not in text
    monitor_idx = text.index("Run ops monitor")
    commit_idx = text.index("Commit ops monitor artifacts")
    fail_idx = text.index("Fail job if ops monitor exited non-zero")
    assert monitor_idx < commit_idx < fail_idx
    assert "tee /tmp/ops_monitor.json" in text
    assert "monitor_rc" in text
