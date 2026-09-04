"""Retry wrapper for transient pip / empty-index flakes."""

from __future__ import annotations

import os
import stat
import subprocess
import textwrap
from pathlib import Path

SCRIPT = Path("scripts/gha_pip_install.sh")


def _run(tmp_path: Path, pip_script: str, attempts: str = "4") -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pip = bin_dir / "pip"
    pip.write_text(pip_script, encoding="utf-8")
    pip.chmod(pip.stat().st_mode | stat.S_IEXEC)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "PIP_BIN": str(pip),
        "PIP_INSTALL_ATTEMPTS": attempts,
        "PIP_INSTALL_SLEEP_BASE": "0",
        "PIP_STATE": str(tmp_path / "state"),
    }
    return subprocess.run(
        ["bash", str(SCRIPT), "-e", "."],
        cwd=Path.cwd(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_gha_pip_install_retries_empty_index_then_succeeds(tmp_path: Path):
    pip_script = textwrap.dedent(
        """\
        #!/usr/bin/env bash
        set -euo pipefail
        n=$(cat "${PIP_STATE}" 2>/dev/null || echo 0)
        n=$((n + 1))
        echo "$n" > "${PIP_STATE}"
        if [ "$n" -lt 3 ]; then
          echo "ERROR: Could not find a version that satisfies the requirement pandas>=2.2 (from versions: none)" >&2
          echo "ERROR: No matching distribution found for pandas>=2.2" >&2
          exit 1
        fi
        echo "Successfully installed pandas"
        exit 0
        """
    )
    result = _run(tmp_path, pip_script)
    assert result.returncode == 0, textwrap.dedent(
        f"""
        retry script failed
        stdout: {result.stdout}
        stderr: {result.stderr}
        """
    )
    assert (tmp_path / "state").read_text(encoding="utf-8").strip() == "3"
    assert "succeeded on attempt 3" in result.stdout


def test_gha_pip_install_gives_up_after_attempts(tmp_path: Path):
    pip_script = textwrap.dedent(
        """\
        #!/usr/bin/env bash
        n=$(cat "${PIP_STATE}" 2>/dev/null || echo 0)
        n=$((n + 1))
        echo "$n" > "${PIP_STATE}"
        echo "ERROR: No matching distribution found for pandas>=2.2" >&2
        exit 1
        """
    )
    result = _run(tmp_path, pip_script, attempts="3")
    assert result.returncode == 1
    assert (tmp_path / "state").read_text(encoding="utf-8").strip() == "3"
    assert "failed after 3 attempts" in result.stderr


def test_gha_pip_install_requires_args():
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "usage:" in result.stderr


def test_library_ingest_workflows_use_pip_retry():
    workflows = (
        Path(".github/workflows/euro-ingest-loop.yml"),
        Path(".github/workflows/library-ingest-sprint.yml"),
        Path(".github/workflows/library-ingest-sprint-2.yml"),
        Path(".github/workflows/library-ingest-maintenance.yml"),
    )
    for path in workflows:
        text = path.read_text(encoding="utf-8")
        assert "scripts/gha_pip_install.sh" in text, path
        assert "run: pip install -e ." not in text, path


def test_library_ingest_workflows_wire_gap_closure_followup():
    workflows = (
        Path(".github/workflows/euro-ingest-loop.yml"),
        Path(".github/workflows/library-ingest-sprint.yml"),
        Path(".github/workflows/library-ingest-sprint-2.yml"),
        Path(".github/workflows/library-ingest-maintenance.yml"),
    )
    for path in workflows:
        text = path.read_text(encoding="utf-8")
        assert "ingest-gap-closure-followup" in text, path
        assert "scripts/dispatch_library_gap_closure_followups.sh" in text, path
    euro = Path(".github/workflows/euro-ingest-loop.yml").read_text(encoding="utf-8")
    assert "steps.loop.outputs.recorded_gap_closure != 'true'" in euro
    assert "steps.loop.outputs.partial != 'true'" not in euro
