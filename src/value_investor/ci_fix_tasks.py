"""Draft scoped engineering tasks from CI pytest failures."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.engineering_tasks import (
    BLOCKED_PATHS,
    COMMITTED_TASKS_PATH,
    TERMINAL_TASK_STATUSES,
    EngineeringTask,
    _default_acceptance_criteria,
    _merge_task_rows,
    load_engineering_tasks,
    path_matches_blocked_pattern,
)
from value_investor.storage import write_json

_PYTEST_FAILED_RE = re.compile(
    r"^FAILED\s+(?P<path>tests/[^\s:]+\.py)::",
    re.MULTILINE,
)
_SHORT_SUMMARY_RE = re.compile(
    r"^FAILED\s+(?P<path>tests/[^\s:]+\.py)::(?P<name>[^\s]+)",
    re.MULTILINE,
)

AUTO_MERGE_MAX_PATHS = 8
AUTO_MERGE_SAFE_PREFIXES: tuple[str, ...] = (
    "tests/",
    "scripts/",
    ".github/workflows/ci.yml",
    ".github/workflows/ci-main-nightly.yml",
    "src/value_investor/",
)


def parse_pytest_failures_from_log(log_text: str) -> list[dict[str, str]]:
    """Extract unique failed pytest node ids from CI log text."""
    seen: set[str] = set()
    failures: list[dict[str, str]] = []
    for match in _SHORT_SUMMARY_RE.finditer(log_text or ""):
        test_path = match.group("path")
        if test_path in seen:
            continue
        seen.add(test_path)
        failures.append(
            {
                "test_path": test_path,
                "test_name": match.group("name"),
            }
        )
    if failures:
        return failures
    for match in _PYTEST_FAILED_RE.finditer(log_text or ""):
        test_path = match.group("path")
        if test_path in seen:
            continue
        seen.add(test_path)
        failures.append({"test_path": test_path, "test_name": ""})
    return failures


def _guess_source_module(test_path: str) -> str | None:
    """Map tests/test_foo.py → src/value_investor/foo.py when present."""
    if not test_path.startswith("tests/test_") or not test_path.endswith(".py"):
        return None
    stem = test_path.removeprefix("tests/test_").removesuffix(".py")
    candidate = Path("src/value_investor") / f"{stem}.py"
    if candidate.exists():
        return candidate.as_posix()
    return None


def build_allowed_paths_for_failures(failures: list[dict[str, str]]) -> list[str]:
    """Derive a tight allowlist from failing test modules."""
    paths: list[str] = []
    seen: set[str] = set()

    def add(path: str) -> None:
        normalized = path.strip().removeprefix("./")
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        paths.append(normalized)

    for row in failures:
        test_path = str(row.get("test_path") or "")
        add(test_path)
        source = _guess_source_module(test_path)
        if source:
            add(source)

    if any("committed_data_json" in row.get("test_path", "") for row in failures):
        add("scripts/check_committed_data_json.py")
    if any("ops_monitor" in row.get("test_path", "") for row in failures):
        add("src/value_investor/ops_monitor.py")
        add("src/value_investor/ops_monitor_cli.py")
    if failures:
        add("tests/conftest.py")
        add(".github/workflows/ci.yml")
        add(".github/workflows/ci-main-nightly.yml")
    return paths


def task_allowed_paths_eligible_for_auto_merge(allowed_paths: list[str]) -> bool:
    if not allowed_paths or len(allowed_paths) > AUTO_MERGE_MAX_PATHS:
        return False
    for path in allowed_paths:
        for blocked in BLOCKED_PATHS:
            if path_matches_blocked_pattern(path, blocked):
                return False
        if not any(path.startswith(prefix) for prefix in AUTO_MERGE_SAFE_PREFIXES):
            return False
    return True


def task_eligible_for_auto_merge(task: EngineeringTask) -> bool:
    return bool(task.auto_merge) and task_allowed_paths_eligible_for_auto_merge(task.allowed_paths)


def _next_engineering_seq(existing_rows: list[dict[str, Any]], run_stamp: str) -> int:
    prefix = f"eng-{run_stamp}-"
    used = [
        int(str(row.get("id") or "").removeprefix(prefix))
        for row in existing_rows
        if str(row.get("id") or "").startswith(prefix)
        and str(row.get("id") or "").removeprefix(prefix).isdigit()
    ]
    return max(used, default=0) + 1


def _failure_title(failures: list[dict[str, str]]) -> str:
    if not failures:
        return "CI fix: pytest failures on main"
    paths = sorted({row["test_path"] for row in failures})
    if len(paths) == 1:
        return f"CI fix: {paths[0]}"
    joined = ", ".join(Path(path).name for path in paths[:3])
    suffix = f" (+{len(paths) - 3} more)" if len(paths) > 3 else ""
    return f"CI fix: pytest failures ({joined}{suffix})"


def draft_ci_fix_task(
    failures: list[dict[str, str]],
    *,
    run_id: int | str | None = None,
    run_url: str | None = None,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    max_tasks: int = 1,
) -> list[str]:
    """Queue a scoped CI-fix engineering task when pytest fails on main."""
    if not failures:
        return []

    title = _failure_title(failures)
    title_key = title.strip().lower()
    allowed_paths = build_allowed_paths_for_failures(failures)
    auto_merge = task_allowed_paths_eligible_for_auto_merge(allowed_paths)

    payload = load_engineering_tasks(tasks_path)
    existing_rows = list(payload.get("tasks") or [])
    for row in existing_rows:
        if str(row.get("status") or "open") in TERMINAL_TASK_STATUSES:
            continue
        if str(row.get("title") or "").strip().lower() == title_key:
            return []
        if str(row.get("source") or "") == "ci_failure" and str(row.get("status") or "") == "open":
            return []

    run_stamp = datetime.now(UTC).strftime("%Y%m%d")
    seq = _next_engineering_seq(existing_rows, run_stamp)
    task_id = f"eng-{run_stamp}-{seq:02d}"
    summary_lines = [
        "Pytest failed on main CI. Fix the failing tests and any underlying code within allowed_paths.",
        f"Failed tests: {', '.join(row['test_path'] for row in failures[:8])}",
    ]
    if run_url:
        summary_lines.append(f"CI run: {run_url}")

    drafted = EngineeringTask(
        id=task_id,
        area="ci",
        title=title[:160],
        summary=" ".join(summary_lines)[:500],
        priority="high",
        priority_score=95.0,
        source="ci_failure",
        evidence={
            "failures": failures[:20],
            "run_id": str(run_id) if run_id is not None else None,
            "run_url": run_url,
        },
        acceptance_criteria=[
            *(_default_acceptance_criteria("ci", [])),
            "pytest passes for the failing test module(s)",
            "CI path guard passes on the engineering PR",
        ],
        allowed_paths=allowed_paths,
        blocked_paths=list(BLOCKED_PATHS),
        auto_merge=auto_merge,
    )

    merged_rows = _merge_task_rows(existing_rows, [drafted])
    payload = {
        **payload,
        "compiled_at": datetime.now(UTC).isoformat(),
        "task_count": len(merged_rows),
        "tasks": merged_rows,
        "ci_fix_compiled": True,
    }
    tasks_path = Path(tasks_path)
    tasks_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(tasks_path, payload, compact=False)
    return [task_id][: max(0, int(max_tasks))]
