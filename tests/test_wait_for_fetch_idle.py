"""Stream 2 waits on a real fetch, not on a queued later wave."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

from value_investor.ingest_fetch_idle import (
    euro_jobs_fetching,
    jobs_are_fetching,
    sprint_jobs_fetching,
)

SCRIPT = Path("scripts/wait_for_fetch_idle.sh")
FETCH = "Run parallel library ingest sprint"


def test_euro_check_or_ingest_holds_stream_2():
    assert euro_jobs_fetching([{"name": "check", "status": "in_progress"}]) is True
    assert (
        euro_jobs_fetching(
            [
                {"name": "check", "status": "completed"},
                {"name": "euro-ingest-loop", "status": "queued"},
            ]
        )
        is True
    )
    assert (
        euro_jobs_fetching(
            [
                {"name": "check", "status": "completed"},
                {"name": "euro-ingest-loop", "status": "completed", "conclusion": "skipped"},
            ]
        )
        is False
    )


def test_stream_1_wait_step_is_not_a_fetch():
    waiting = {
        "name": "library-ingest-sprint",
        "status": "in_progress",
        "steps": [
            {"name": "Wait for euro_depth fat slot", "status": "in_progress"},
            {"name": FETCH, "status": "queued"},
        ],
    }
    fetching = {
        "name": "library-ingest-sprint",
        "status": "in_progress",
        "steps": [
            {"name": "Wait for euro_depth fat slot", "status": "completed"},
            {"name": FETCH, "status": "in_progress"},
        ],
    }
    finished = {
        "name": "library-ingest-sprint",
        "status": "in_progress",
        "steps": [
            {"name": "Wait for euro_depth fat slot", "status": "completed"},
            {"name": FETCH, "status": "completed"},
            {"name": "Commit and push library ingest artifacts", "status": "in_progress"},
        ],
    }
    assert sprint_jobs_fetching([waiting]) is False
    assert sprint_jobs_fetching([fetching]) is True
    assert sprint_jobs_fetching([finished]) is False
    assert jobs_are_fetching("library-ingest-sprint.yml", []) is True


def test_script_queries_in_progress_runs_only():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "status=in_progress" in text
    assert "status=queued" not in text
    assert "status=waiting" not in text
    assert "status=pending" not in text


def _stub(tmp_path: Path, body: str) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(body, encoding="utf-8")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    return {
        "PATH": f"{bin_dir}{os.pathsep}/usr/bin:/bin",
        "GITHUB_REPOSITORY": "jamiefuller320/value_investor",
        "GH_TOKEN": "test-token",
        "MAX_WAIT_SECONDS": "30",
        "POLL_SECONDS": "1",
    }


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), "euro-ingest-loop.yml", "library-ingest-sprint.yml"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_a_queued_later_wave_does_not_hold_the_wait(tmp_path: Path):
    env = _stub(
        tmp_path,
        """#!/bin/bash
for arg in "$@"; do
  case "$arg" in
    *status=queued*|*status=waiting*|*status=pending*)
      echo queued-was-queried >&2
      exit 9
      ;;
  esac
done
echo '{"workflow_runs":[]}'
""",
    )
    proc = _run(env)
    assert proc.returncode == 0, proc.stderr
    assert "not fetching" in proc.stdout


def test_an_in_progress_euro_ingest_waits_out_the_cap(tmp_path: Path):
    jobs = {
        "jobs": [
            {"name": "check", "status": "completed"},
            {"name": "euro-ingest-loop", "status": "in_progress", "steps": []},
        ]
    }
    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(json.dumps(jobs), encoding="utf-8")
    env = _stub(
        tmp_path,
        f"""#!/bin/bash
for arg in "$@"; do
  case "$arg" in
    *runs\\?status=in_progress*)
      echo '{{"workflow_runs":[{{"id":7}}]}}'
      exit 0
      ;;
    */runs/7/jobs*)
      cat {jobs_path}
      exit 0
      ;;
  esac
done
echo '{{"workflow_runs":[]}}'
""",
    )
    env["MAX_WAIT_SECONDS"] = "1"
    proc = _run(env)
    assert proc.returncode == 75, proc.stdout + proc.stderr
    assert "still fetching" in proc.stderr
