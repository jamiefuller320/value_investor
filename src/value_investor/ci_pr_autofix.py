"""Autofix scoped CI failures on cursor PR branches after CI fails."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from value_investor.ci_fix_tasks import parse_pytest_failures_from_log
from value_investor.engineering_queue import is_engineering_branch, task_id_from_branch
from value_investor.engineering_tasks import (
    COMMITTED_TASKS_PATH,
    expand_task_allowed_paths,
    normalize_repo_path,
    validate_engineering_pr_paths_for_task_id,
)
from value_investor.python_quality import (
    apply_ruff_autofix,
    check_changed_python,
    git_changed_files,
    run_ruff_on_files,
)

CI_BOT_COMMIT_PREFIX = "chore(ci):"
AUTOFIX_COMMIT_PREFIX = "chore(ci): autofix"
PATH_EXPAND_COMMIT_PREFIX = "chore(ci): expand engineering allowed_paths"
RUFF_FORMAT_MARKERS = ("ruff format failed", "would be reformatted")
RUFF_CHECK_MARKERS = ("ruff check failed",)
PATH_GUARD_MARKERS = (
    "Engineering path guard failed",
    "outside allowed_paths:",
    "engineering-path-guard",
)
_OUTSIDE_ALLOWED_RE = re.compile(r"outside allowed_paths:\s+([^\s(]+)")


@dataclass
class AutofixResult:
    fixed: bool
    kinds: list[str]
    reason: str
    logs: list[str]
    actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixed": self.fixed,
            "kinds": self.kinds,
            "reason": self.reason,
            "logs": self.logs,
            "actions": list(self.actions),
        }


@dataclass
class PrCiDiagnosis:
    kinds: list[str]
    branch: str
    engineering_task_id: str | None = None
    path_guard_violations: list[str] = field(default_factory=list)
    pytest_failures: list[dict[str, str]] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kinds": list(self.kinds),
            "branch": self.branch,
            "engineering_task_id": self.engineering_task_id,
            "path_guard_violations": list(self.path_guard_violations),
            "pytest_failures": list(self.pytest_failures),
            "hints": list(self.hints),
        }


def classify_ci_log_failures(log_text: str) -> list[str]:
    """Return failure kinds detected in CI log text."""
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
    if any(marker in text for marker in PATH_GUARD_MARKERS):
        kinds.append("path_guard")
    return kinds


def parse_path_guard_violations(log_text: str) -> list[str]:
    """Extract repo paths from engineering path-guard CI log lines."""
    paths: list[str] = []
    seen: set[str] = set()
    for match in _OUTSIDE_ALLOWED_RE.finditer(log_text or ""):
        normalized = normalize_repo_path(match.group(1))
        if normalized and normalized not in seen:
            seen.add(normalized)
            paths.append(normalized)
    return paths


def last_commit_message(head_ref: str = "HEAD") -> str:
    proc = subprocess.run(
        ["git", "log", "-1", "--pretty=%s", head_ref],
        check=False,
        capture_output=True,
        text=True,
    )
    return (proc.stdout or "").strip()


def ci_bot_already_attempted(head_ref: str = "HEAD") -> bool:
    """True when the latest commit is already a CI bot fix (avoid autofix loops)."""
    return last_commit_message(head_ref).startswith(CI_BOT_COMMIT_PREFIX)


def autofix_already_attempted(head_ref: str = "HEAD") -> bool:
    return ci_bot_already_attempted(head_ref)


def diagnose_pr_ci_failure(
    *,
    branch: str,
    log_text: str,
) -> PrCiDiagnosis:
    kinds = classify_ci_log_failures(log_text)
    task_id = task_id_from_branch(branch) if is_engineering_branch(branch) else None
    path_violations = parse_path_guard_violations(log_text) if "path_guard" in kinds else []
    pytest_failures = parse_pytest_failures_from_log(log_text) if "pytest" in kinds else []
    hints: list[str] = []
    if "path_guard" in kinds and task_id:
        hints.append(
            f"Path guard: add missing paths to `{task_id}` allowed_paths "
            "(CI may auto-expand on engineering branches)."
        )
    if "pytest" in kinds and task_id:
        hints.append(
            "Pytest failure on an engineering PR is not auto-fixed — patch the code/tests "
            "or push an isolated fixture if the test depends on live `docs/data`."
        )
    if "pytest" in kinds and not task_id:
        hints.append(
            "Pytest failure: fix tests/code on this branch or wait for main ci-fix-responder "
            "if the failure is on main."
        )
    if "data_json" in kinds:
        hints.append("Committed data JSON check failed — regenerate or repair docs/data JSON.")
    if not kinds:
        hints.append("Could not classify CI failure from logs — inspect the failed job manually.")
    return PrCiDiagnosis(
        kinds=kinds,
        branch=branch,
        engineering_task_id=task_id,
        path_guard_violations=path_violations,
        pytest_failures=pytest_failures,
        hints=hints,
    )


def format_pr_ci_comment(
    *,
    diagnosis: PrCiDiagnosis,
    failed_run_id: str,
    failed_run_url: str,
    fixed: bool,
    actions: list[str],
    commit_sha: str | None = None,
    docs_url: str | None = None,
) -> str:
    lines = ["## CI monitoring"]
    lines.append("")
    if fixed:
        lines.append(
            "Automated CI fix(es) were applied and pushed. CI should re-run on the new commit."
        )
    else:
        lines.append("CI failed and **no automatic fix** was applied for this push.")
    lines.append("")
    lines.append("| | |")
    lines.append("|--|--|")
    lines.append(f"| Failed run | [{failed_run_id}]({failed_run_url}) |")
    if commit_sha:
        lines.append(f"| Fix commit | `{commit_sha}` |")
    if diagnosis.engineering_task_id:
        lines.append(f"| Engineering task | `{diagnosis.engineering_task_id}` |")
    if diagnosis.kinds:
        lines.append(f"| Failure kinds | {', '.join(diagnosis.kinds)} |")
    if actions:
        lines.append(f"| Actions taken | {', '.join(actions)} |")
    lines.append("")
    if diagnosis.path_guard_violations:
        lines.append("**Path guard violations**")
        for violation in diagnosis.path_guard_violations:
            lines.append(f"- `{violation}`")
        lines.append("")
    if diagnosis.pytest_failures:
        lines.append("**Pytest failures**")
        for row in diagnosis.pytest_failures[:8]:
            name = row.get("test_name") or ""
            path = row.get("test_path") or ""
            lines.append(f"- `{path}::{name}`" if name else f"- `{path}`")
        if len(diagnosis.pytest_failures) > 8:
            lines.append(f"- … and {len(diagnosis.pytest_failures) - 8} more")
        lines.append("")
    if diagnosis.hints:
        lines.append("**Hints**")
        for hint in diagnosis.hints:
            lines.append(f"- {hint}")
        lines.append("")
    if docs_url:
        lines.append(f"Details: [ci-fix-automation]({docs_url})")
    return "\n".join(lines).strip() + "\n"


def _suggest_companion_paths(paths: list[str]) -> list[str]:
    """When a test or src path is added, suggest the paired module if it exists."""
    extras: list[str] = []
    for path in paths:
        if path.startswith("tests/test_") and path.endswith(".py"):
            stem = path.removeprefix("tests/test_").removesuffix(".py")
            candidate = Path("src/value_investor") / f"{stem}.py"
            if candidate.exists():
                extras.append(candidate.as_posix())
        elif path.startswith("src/value_investor/") and path.endswith(".py"):
            stem = path.removeprefix("src/value_investor/").removesuffix(".py")
            candidate = Path("tests") / f"test_{stem}.py"
            if candidate.exists():
                extras.append(candidate.as_posix())
    return extras


def attempt_engineering_path_guard_autofix(
    *,
    branch: str,
    base_ref: str,
    head_ref: str = "HEAD",
    log_text: str | None = None,
    tasks_path: Path = COMMITTED_TASKS_PATH,
) -> AutofixResult:
    logs: list[str] = []
    kinds = classify_ci_log_failures(log_text or "")
    if "path_guard" not in kinds:
        return AutofixResult(
            fixed=False,
            kinds=kinds,
            reason="no path guard failure in CI log",
            logs=logs,
        )

    task_id = task_id_from_branch(branch)
    if not task_id:
        return AutofixResult(
            fixed=False,
            kinds=kinds,
            reason="not an engineering task branch",
            logs=logs,
        )

    violation_paths = parse_path_guard_violations(log_text or "")
    if not violation_paths:
        try:
            changed = [
                p.as_posix() for p in git_changed_files(base_ref=base_ref, head_ref=head_ref)
            ]
        except RuntimeError as exc:
            return AutofixResult(
                fixed=False,
                kinds=kinds,
                reason=f"git diff failed: {exc}",
                logs=logs,
            )
        guard = validate_engineering_pr_paths_for_task_id(
            task_id,
            changed,
            tasks_path=tasks_path,
        )
        violation_paths = [
            normalize_repo_path(line.split("outside allowed_paths: ", 1)[1])
            for line in guard.violations
            if "outside allowed_paths:" in line
        ]

    expand_paths = list(
        dict.fromkeys([*violation_paths, *_suggest_companion_paths(violation_paths)])
    )
    if not expand_paths:
        return AutofixResult(
            fixed=False,
            kinds=kinds,
            reason="path guard failed but no expandable paths found",
            logs=logs,
        )

    _, added = expand_task_allowed_paths(
        task_id,
        expand_paths,
        path=tasks_path,
        committed_path=tasks_path,
    )
    if not added:
        return AutofixResult(
            fixed=False,
            kinds=kinds,
            reason="no new allowed_paths to add (blocked or already listed)",
            logs=logs,
        )

    try:
        changed = [p.as_posix() for p in git_changed_files(base_ref=base_ref, head_ref=head_ref)]
    except RuntimeError as exc:
        return AutofixResult(
            fixed=False,
            kinds=kinds,
            reason=f"git diff failed: {exc}",
            logs=logs,
        )
    guard = validate_engineering_pr_paths_for_task_id(
        task_id,
        changed,
        tasks_path=tasks_path,
    )
    if not guard.ok:
        return AutofixResult(
            fixed=False,
            kinds=kinds,
            reason=f"path guard still failing after expand: {guard.violations[:3]}",
            logs=logs,
        )

    logs.append(f"expanded allowed_paths for {task_id}: {added}")
    return AutofixResult(
        fixed=True,
        kinds=["path_guard"],
        reason="expanded engineering allowed_paths for path guard",
        logs=logs,
        actions=["path_guard_expand"],
    )


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

    if ci_bot_already_attempted(head_ref):
        return AutofixResult(
            fixed=False,
            kinds=kinds,
            reason="CI bot fix already attempted on latest commit",
            logs=logs,
        )

    ruff_kinds = [k for k in kinds if k in {"ruff_format", "ruff_check"}]
    if not ruff_kinds:
        reason = "no autofixable ruff failure in CI log"
        if "pytest" in kinds:
            reason = "pytest failure — not autofixable via ruff"
        elif "path_guard" in kinds:
            reason = "path guard failure — use engineering path expand autofix"
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
        actions=["ruff"],
    )


def run_pr_ci_autofix_pipeline(
    *,
    branch: str,
    base_ref: str,
    head_ref: str = "HEAD",
    log_text: str | None = None,
    tasks_path: Path = COMMITTED_TASKS_PATH,
) -> tuple[AutofixResult, PrCiDiagnosis]:
    """Try ruff then engineering path-guard expand; always return diagnosis."""
    diagnosis = diagnose_pr_ci_failure(branch=branch, log_text=log_text or "")

    if ci_bot_already_attempted(head_ref):
        return AutofixResult(
            fixed=False,
            kinds=diagnosis.kinds,
            reason="CI bot fix already attempted on latest commit",
            logs=[],
        ), diagnosis

    ruff_result = attempt_pr_ci_autofix(
        base_ref=base_ref,
        head_ref=head_ref,
        log_text=log_text,
    )
    if ruff_result.fixed:
        return ruff_result, diagnosis

    if is_engineering_branch(branch) and "path_guard" in diagnosis.kinds:
        path_result = attempt_engineering_path_guard_autofix(
            branch=branch,
            base_ref=base_ref,
            head_ref=head_ref,
            log_text=log_text,
            tasks_path=tasks_path,
        )
        if path_result.fixed:
            return path_result, diagnosis
        return path_result, diagnosis

    return ruff_result, diagnosis


def write_autofix_result(path: Path, result: AutofixResult) -> None:
    path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
