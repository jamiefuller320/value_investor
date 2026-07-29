"""Tests for resolve_workflow_pat.sh helper."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _resolve(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    script = Path("scripts/resolve_workflow_pat.sh")
    bash = f'source "{script}"; resolve_workflow_pat'
    return subprocess.run(
        ["bash", "-c", bash],
        check=False,
        capture_output=True,
        text=True,
        env={**env, "PATH": env.get("PATH", "/usr/bin:/bin")},
    )


def test_shell_prefers_workflow_dispatch_pat():
    proc = _resolve(
        {
            "WORKFLOW_DISPATCH_PAT": "github_pat_preferred",
            "GH_PAT": "github_pat_other",
            "PATH": "/usr/bin:/bin",
        }
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == "github_pat_preferred"


def test_shell_rejects_integration_token():
    proc = _resolve(
        {
            "GH_PAT": "ghs_integration_only",
            "PATH": "/usr/bin:/bin",
        }
    )
    assert proc.returncode == 1
    assert "integration token" in proc.stderr
