"""Shared GHA artifact commit helper (L348) for email-report + library-grow."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path

SCRIPT = Path("scripts/gha_commit_artifacts.sh")
EMAIL_WORKFLOW = Path(".github/workflows/email-report.yml")
LIBRARY_WORKFLOW = Path(".github/workflows/library-grow.yml")


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _seed_repo(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "-C", str(remote), "symbolic-ref", "HEAD", "refs/heads/main")
    _git(tmp_path, "clone", str(remote), str(work))
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "test")

    _write(work / "docs" / "data" / "latest.json", "{}\n")
    scripts_dir = work / "scripts"
    scripts_dir.mkdir()
    script = scripts_dir / "gha_commit_artifacts.sh"
    script.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
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


def _run_script(
    work: Path,
    *,
    owned: str,
    message: str = "chore: test artifacts [skip ci]",
    attempts: str = "5",
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "GHA_COMMIT_OWNED": owned,
        "COMMIT_MESSAGE": message,
        "GHA_COMMIT_LABEL": "Test artifacts",
        "GHA_COMMIT_ATTEMPTS": attempts,
        "GHA_COMMIT_SLEEP_BASE": "0",
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
    }
    return subprocess.run(
        ["bash", "scripts/gha_commit_artifacts.sh"],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_artifact_commit_preserves_untracked_files_across_main_sync(tmp_path: Path):
    """Email-report Sep-8 mode: untracked research bodies must survive reset+push."""
    remote, work = _seed_repo(tmp_path)
    body = work / "docs" / "research" / "ITV.L" / "sources" / "filings" / "bodies" / "ir_deadbeef.txt"
    _write(body, "filing body from this run\n")
    _write(work / "docs" / "data" / "latest.json", json.dumps({"tickers": 1}) + "\n")

    # Concurrent main advance (as if another automation pushed mid-run).
    other = tmp_path / "other"
    _git(tmp_path, "clone", str(remote), str(other))
    _git(other, "config", "user.email", "other@example.com")
    _git(other, "config", "user.name", "other")
    _write(other / "docs" / "data" / "ops_status.json", '{"overall":"ok"}\n')
    _git(other, "add", "docs/data/ops_status.json")
    _git(other, "commit", "-m", "concurrent")
    _git(other, "push", "origin", "main")

    result = _run_script(work, owned="docs/data docs/research")
    assert result.returncode == 0, textwrap.dedent(
        f"""
        artifact commit failed
        stdout: {result.stdout}
        stderr: {result.stderr}
        """
    )
    latest = tmp_path / "latest"
    _git(tmp_path, "clone", str(remote), str(latest))
    committed_body = (
        latest / "docs" / "research" / "ITV.L" / "sources" / "filings" / "bodies" / "ir_deadbeef.txt"
    )
    assert committed_body.read_text(encoding="utf-8") == "filing body from this run\n"
    assert json.loads((latest / "docs" / "data" / "latest.json").read_text(encoding="utf-8")) == {
        "tickers": 1
    }
    assert (latest / "docs" / "data" / "ops_status.json").exists()


def test_artifact_commit_retries_after_push_race(tmp_path: Path):
    remote, work = _seed_repo(tmp_path)
    _install_pre_receive(remote, reject_first_n=1)
    _write(work / "docs" / "data" / "latest.json", '{"n": 2}\n')

    result = _run_script(work, owned="docs/data/latest.json")
    assert result.returncode == 0, result.stderr
    assert "attempt 2/5" in result.stdout
    latest = tmp_path / "latest"
    _git(tmp_path, "clone", str(remote), str(latest))
    assert json.loads((latest / "docs" / "data" / "latest.json").read_text(encoding="utf-8")) == {
        "n": 2
    }


def test_email_and_library_workflows_use_shared_commit_helper() -> None:
    email = EMAIL_WORKFLOW.read_text(encoding="utf-8")
    library = LIBRARY_WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/gha_commit_artifacts.sh" in email
    assert "scripts/gha_commit_artifacts.sh" in library
    assert "stefanzweifel/git-auto-commit-action@v6" not in email
    assert "stefanzweifel/git-auto-commit-action@v6" not in library
    assert "git pull --rebase --autostash" not in email
    assert "git pull --rebase --autostash" not in library
    assert "changes_detected" in email
