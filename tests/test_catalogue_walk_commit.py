"""Stream 1 screens until the job must commit. Stream 2 drains buys and exits."""

from __future__ import annotations

import os
import stat
import subprocess
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ingest_hunt_commit.sh"


def _bin(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "bin" / "ftse-library"
    path.parent.mkdir()
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    push = tmp_path / "bin" / "push.sh"
    push.write_text('#!/bin/bash\nprintf \'%s\\n\' "$1" >> "$PUSHES"\n', encoding="utf-8")
    push.chmod(push.stat().st_mode | stat.S_IEXEC)
    return path


def _env(tmp_path: Path) -> dict[str, str]:
    calls = tmp_path / "calls"
    pushes = tmp_path / "pushes"
    calls.write_text("", encoding="utf-8")
    pushes.write_text("", encoding="utf-8")
    return {
        "PATH": f"{tmp_path / 'bin'}{os.pathsep}/usr/bin:/bin",
        "CALLS": str(calls),
        "PUSHES": str(pushes),
        "PUSH_LIBRARY_SCRIPT": str(tmp_path / "bin" / "push.sh"),
        "JOB_START_EPOCH": str(int(time.time())),
    }


def _run(tmp_path: Path, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )


def test_screen_loop_commits_each_name_and_does_not_handoff(tmp_path: Path):
    _bin(
        tmp_path,
        """#!/bin/bash
printf '%s\\n' "$*" >> "$CALLS"
n=$(wc -l < "$CALLS" | tr -d ' ')
json=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "--json-path" ]; then json="$arg"; fi
  prev="$arg"
done
case "$n" in
  1) ticker="AAA_US_EQ"; action="ran" ;;
  2) ticker="BBB_US_EQ"; action="ran" ;;
  *) ticker=""; action="idle" ;;
esac
printf '{"action":"%s","t212_ticker":"%s"}\\n' "$action" "$ticker" > "$json"
""",
    )
    env = _env(tmp_path)
    proc = _run(
        tmp_path,
        "--catalogue",
        "screen",
        "--job-seconds",
        "6600",
        "--commit-reserve",
        "300",
        "--commit-message",
        "chore: catalogue explorer one name [skip ci]",
        env=env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    calls = (tmp_path / "calls").read_text(encoding="utf-8")
    assert calls.count("catalogue-explore") == 3
    assert "catalogue-handoff" not in calls
    pushes = (tmp_path / "pushes").read_text(encoding="utf-8").strip().splitlines()
    assert pushes == ["chore: catalogue explorer one name [skip ci]"] * 2


def test_empty_handoff_queue_exits_without_a_commit(tmp_path: Path):
    _bin(
        tmp_path,
        """#!/bin/bash
printf '%s\\n' "$*" >> "$CALLS"
json=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "--json-path" ]; then json="$arg"; fi
  prev="$arg"
done
printf '%s\\n' '{"action":"idle","reason":"no_handoff"}' > "$json"
""",
    )
    env = _env(tmp_path)
    proc = _run(
        tmp_path,
        "--catalogue",
        "handoff",
        "--job-seconds",
        "6600",
        "--commit-reserve",
        "300",
        "--commit-message",
        "chore: catalogue explorer handoff ingest [skip ci]",
        env=env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    calls = (tmp_path / "calls").read_text(encoding="utf-8")
    assert calls.strip() == "catalogue-handoff --one --json-path /tmp/catalogue_handoff.json"
    assert "catalogue-explore" not in calls
    assert (tmp_path / "pushes").read_text(encoding="utf-8") == ""
    assert "no_handoff" in proc.stdout


def test_catalogue_loop_stops_before_the_job_commit(tmp_path: Path):
    _bin(
        tmp_path,
        """#!/bin/bash
printf '%s\\n' "$*" >> "$CALLS"
exit 9
""",
    )
    env = _env(tmp_path)
    env["JOB_START_EPOCH"] = str(int(time.time()) - 100)
    proc = _run(
        tmp_path,
        "--catalogue",
        "screen",
        "--job-seconds",
        "50",
        "--commit-reserve",
        "0",
        "--commit-message",
        "chore: catalogue explorer one name [skip ci]",
        env=env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (tmp_path / "calls").read_text(encoding="utf-8") == ""
    assert "so the job can commit" in proc.stdout


def test_repeated_catalogue_name_stops_the_loop(tmp_path: Path):
    _bin(
        tmp_path,
        """#!/bin/bash
printf '%s\\n' "$*" >> "$CALLS"
json=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "--json-path" ]; then json="$arg"; fi
  prev="$arg"
done
printf '%s\\n' '{"action":"ran","t212_ticker":"AAA_US_EQ"}' > "$json"
""",
    )
    env = _env(tmp_path)
    proc = _run(
        tmp_path,
        "--catalogue",
        "handoff",
        "--job-seconds",
        "6600",
        "--commit-reserve",
        "0",
        "--commit-message",
        "chore: catalogue explorer handoff ingest [skip ci]",
        env=env,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "repeated AAA_US_EQ" in proc.stderr
    pushes = (tmp_path / "pushes").read_text(encoding="utf-8").strip().splitlines()
    assert len(pushes) == 1
