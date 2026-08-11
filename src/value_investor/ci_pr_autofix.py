"""Autofix scoped ruff failures on cursor PR branches after CI fails."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from value_investor.python_quality import (
    apply_ruff_autofix,
    check_changed_python,
    git_changed_files,
    run_ruff_on_files,
)

AUTOFIX_COMMIT_PREFIX = "chore(ci): autofix"
RUFF_FORMAT_MARKERS = ("ruff format failed", "would be reformatted")
RUFF_CHECK_MARKERS = ("ruff check failed",)


@dataclass
class AutofixResult:
    fixed: bool
    kinds: list[str]
    reason: str
    logs: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixed": self.fixed,
            "kinds": self.kinds,
            "reason": self.reason,
            "logs": self.logs,
        }


def classify_ci_log_failures(log_text: str) -> list[str]:
    """Return autofix-relevant failure kinds detected in CI log text."""
    text = log_text or ""
    kinds: list[str] = []
    if any(marker in text for marker in RUFF_FORMAT_MARKERS):
        kinds.append("ruff_format")
    if any(marker in text for marker in RUFF_CHECK_MARKERS):
        kinds.append("ruff_check")
    if "FAILED tests/" in text or "short test summary info" in text:
        kinds.append("pytest")
    if "check_committed_data_json" in text:
        kinds.append("data_json")
    return kinds


def last_commit_message(head_ref: str = "HEAD") -> str:
    proc = subprocess.run(
        ["git", "log", "-1", "--pretty=%s", head_ref],
        check=False,
        capture_output=True,
        text=True,
    )
    return (proc.stdout or "").strip()


def autofix_already_attempted(head_ref: str = "HEAD") -> bool:
    return AUTOFIX_COMMIT_PREFIX in last_commit_message(head_ref)


def attempt_pr_ci_autofix(
    *,
    base_ref: str,
    head_ref: str = "HEAD",
    log_text: str | None = None,
) -> AutofixResult:
    """
    Apply deterministic CI fixes (scoped ruff) when log text indicates ruff failure.

    Does not attempt pytest or data-json fixes — those need human or engineering-agent work.
    """
    logs: list[str] = []
    kinds = classify_ci_log_failures(log_text or "")

    if autofix_already_attempted(head_ref):
        return AutofixResult(
            fixed=False,
            kinds=kinds,
            reason="autofix already attempted on latest commit",
            logs=logs,
        )

    ruff_kinds = [k for k in kinds if k in {"ruff_format", "ruff_check"}]
    if not ruff_kinds:
        reason = "no autofixable ruff failure in CI log"
        if "pytest" in kinds:
            reason = "pytest failure — not autofixable (needs code/test fix)"
        elif "data_json" in kinds:
            reason = "committed data JSON check failed — not autofixable"
        elif not kinds:
            reason = "could not classify CI failure from log"
        return AutofixResult(fixed=False, kinds=kinds, reason=reason, logs=logs)

    try:
        files = git_changed_files(base_ref=base_ref, head_ref=head_ref)
    except RuntimeError as exc:
        return AutofixResult(
            fixed=False,
            kinds=kinds,
            reason=f"git diff failed: {exc}",
            logs=logs,
        )

    before_code, before_logs = run_ruff_on_files(files)
    logs.extend(before_logs)
    if before_code == 0:
        return AutofixResult(
            fixed=False,
            kinds=kinds,
            reason="ruff already passes locally on changed files",
            logs=logs,
        )

    fix_code, fix_logs = apply_ruff_autofix(files)
    logs.extend(fix_logs)
    if fix_code != 0:
        return AutofixResult(
            fixed=False,
            kinds=kinds,
            reason="ruff autofix command failed",
            logs=logs,
        )

    verify_code, verify_logs = check_changed_python(base_ref=base_ref, head_ref=head_ref)
    logs.extend(verify_logs)
    if verify_code != 0:
        return AutofixResult(
            fixed=False,
            kinds=kinds,
            reason="ruff still failing after autofix",
            logs=logs,
        )

    return AutofixResult(
        fixed=True,
        kinds=ruff_kinds,
        reason="ruff autofix applied and verified",
        logs=logs,
    )


def write_autofix_result(path: Path, result: AutofixResult) -> None:
    path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
