"""Regression: weekday rememo push allowlists latest.json + research, not ops_status."""

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


def test_push_weekday_rememo_commits_latest_not_ops_status(tmp_path: Path):
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "-C", str(remote), "symbolic-ref", "HEAD", "refs/heads/main")
    _git(tmp_path, "clone", str(remote), str(work))
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "test")

    data = work / "docs" / "data"
    research_md = work / "docs" / "research"
    data.mkdir(parents=True)
    research_md.mkdir(parents=True)
    (data / "ops_status.json").write_text('{"run_at":"old"}\n', encoding="utf-8")
    (data / "latest.json").write_text('{"research":[]}\n', encoding="utf-8")
    (research_md / "AAA.L.md").write_text("# AAA\n", encoding="utf-8")
    (work / "scripts").mkdir()
    script_src = Path("scripts/push_weekday_rememo_artifacts.sh").read_text(encoding="utf-8")
    (work / "scripts" / "push_weekday_rememo_artifacts.sh").write_text(script_src, encoding="utf-8")
    os.chmod(work / "scripts" / "push_weekday_rememo_artifacts.sh", 0o755)

    _git(
        work,
        "add",
        "docs/data/ops_status.json",
        "docs/data/latest.json",
        "docs/research/AAA.L.md",
        "scripts",
    )
    _git(work, "commit", "-m", "seed")
    _git(work, "branch", "-M", "main")
    _git(work, "push", "-u", "origin", "main")

    other = tmp_path / "other"
    _git(tmp_path, "clone", str(remote), str(other))
    _git(other, "config", "user.email", "test@example.com")
    _git(other, "config", "user.name", "test")
    (other / "docs" / "data" / "ops_status.json").write_text(
        '{"run_at":"new"}\n',
        encoding="utf-8",
    )
    _git(other, "add", "docs/data/ops_status.json")
    _git(other, "commit", "-m", "chore: ops monitor")
    _git(other, "push", "origin", "main")

    (data / "latest.json").write_text('{"research":[{"ticker":"AAA.L"}]}\n', encoding="utf-8")
    (data / "weekday_memo_rememo_summary.json").write_text(
        '{"rememoed":["AAA.L"]}\n',
        encoding="utf-8",
    )
    (research_md / "AAA.L.md").write_text("# AAA rememoed\n", encoding="utf-8")

    env = {**os.environ, "MAX_ATTEMPTS": "2"}
    result = subprocess.run(
        ["bash", "scripts/push_weekday_rememo_artifacts.sh", "chore: weekday memo rememo [skip ci]"],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
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
    latest = _git(work, "show", "origin/main:docs/data/latest.json").stdout
    summary = _git(work, "show", "origin/main:docs/data/weekday_memo_rememo_summary.json").stdout
    memo = _git(work, "show", "origin/main:docs/research/AAA.L.md").stdout
    assert '"run_at":"new"' in ops, f"ops_status was clobbered:\n{ops}"
    assert "AAA.L" in latest
    assert "AAA.L" in summary
    assert "rememoed" in memo
