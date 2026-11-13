"""Predecessor-idle recording for spare library ingest slots."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

SCRIPT = Path("scripts/record_predecessor_idle.sh")
SPARE_WORKFLOWS = (
    Path(".github/workflows/library-ingest-sprint.yml"),
    Path(".github/workflows/library-ingest-sprint-2.yml"),
    Path(".github/workflows/library-ingest-maintenance.yml"),
)
INGEST_DEPENDENT_STEPS = (
    "Evaluate library gap-closure follow-up",
    "Commit and push library ingest artifacts",
)


def _run(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _gh_env(tmp_path: Path, *, max_wait: str) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text("#!/bin/bash\necho 0\n", encoding="utf-8")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    out = tmp_path / "github_output"
    return {
        "PATH": f"{bin_dir}{os.pathsep}/usr/bin:/bin",
        "GITHUB_REPOSITORY": "jamiefuller320/value_investor",
        "GH_TOKEN": "test-token",
        "GITHUB_OUTPUT": str(out),
        "MAX_WAIT_SECONDS": max_wait,
        "POLL_SECONDS": "1",
    }


def test_records_idle_when_predecessors_are_idle(tmp_path: Path):
    env = _gh_env(tmp_path, max_wait="60")
    proc = _run(["slot yielded", "euro-ingest-loop.yml"], env)
    assert proc.returncode == 0, proc.stderr
    assert Path(env["GITHUB_OUTPUT"]).read_text(encoding="utf-8") == "idle=true\n"
    assert "slot yielded" not in proc.stdout
    assert "predecessors idle after" in proc.stdout


def test_records_not_idle_when_wait_expires(tmp_path: Path):
    env = _gh_env(tmp_path, max_wait="0")
    proc = _run(
        [
            "Predecessor still queued or running after wait — skip spare stream 2",
            "library-ingest-sprint.yml",
        ],
        env,
    )
    assert proc.returncode == 0, proc.stderr
    assert Path(env["GITHUB_OUTPUT"]).read_text(encoding="utf-8") == "idle=false\n"
    assert "skip spare stream 2" in proc.stdout


def test_propagates_other_wait_failures(tmp_path: Path):
    stub = tmp_path / "wait.sh"
    stub.write_text("#!/bin/bash\necho stub-failed >&2\nexit 9\n", encoding="utf-8")
    out = tmp_path / "github_output"
    env = {
        "PATH": "/usr/bin:/bin",
        "GITHUB_OUTPUT": str(out),
        "PREDECESSOR_WAIT_SCRIPT": str(stub),
    }
    proc = _run(["should not skip", "euro-ingest-loop.yml"], env)
    assert proc.returncode == 9
    assert "stub-failed" in proc.stderr
    assert not out.exists()


def test_requires_message_workflow_and_output(tmp_path: Path):
    missing = _run(
        ["only-a-message"], {"PATH": "/usr/bin:/bin", "GITHUB_OUTPUT": str(tmp_path / "out")}
    )
    assert missing.returncode == 2
    no_output = _run(["msg", "euro-ingest-loop.yml"], {"PATH": "/usr/bin:/bin"})
    assert no_output.returncode == 2
    assert "GITHUB_OUTPUT" in no_output.stderr


def _step_block(text: str, name: str) -> str:
    marker = f"- name: {name}\n"
    start = text.index(marker)
    rest = text[start + len(marker) :]
    nxt = rest.find("\n      - name:")
    if nxt < 0:
        return text[start:]
    return text[start : start + len(marker) + nxt]


def test_spare_workflows_skip_followup_when_predecessor_stays_busy():
    for path in SPARE_WORKFLOWS:
        text = path.read_text(encoding="utf-8")
        assert "scripts/record_predecessor_idle.sh" in text, path
        assert "if bash scripts/wait_for_workflow_idle.sh" not in text, path
        for step in INGEST_DEPENDENT_STEPS:
            block = _step_block(text, step)
            assert "if: steps.wait_head.outputs.idle == 'true'" in block, (path, step)
    sprint_2 = Path(".github/workflows/library-ingest-sprint-2.yml").read_text(encoding="utf-8")
    assert "euro-ingest-loop.yml library-ingest-sprint.yml" in sprint_2
    maintenance = Path(".github/workflows/library-ingest-maintenance.yml").read_text(
        encoding="utf-8"
    )
    refresh = _step_block(maintenance, "Refresh completion gate and sync crons")
    assert "if: steps.wait_head.outputs.idle == 'true'" in refresh
