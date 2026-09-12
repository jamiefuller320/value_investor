"""Idle-queue compile backstop when post-run plan lacks open engineering tasks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.engineering_queue import summarize_queue
from value_investor.engineering_sync import audit_compile_drop_risk
from value_investor.engineering_tasks import (
    COMMITTED_TASKS_PATH,
    DEFAULT_MAX_COMPILE_TASKS,
    DEFAULT_SUGGESTIONS_PATH,
    TERMINAL_TASK_STATUSES,
    compile_engineering_tasks,
    ensure_post_run_review_artifact,
    load_engineering_tasks,
    post_run_plan_titles_from_text,
    preview_compile_new_open_count,
)
from value_investor.ops_monitor import DEFAULT_LATEST_PATH
from value_investor.storage import read_json

DEFAULT_OUTPUT_DIR = Path("output")
DEFAULT_STALE_HOURS = 6


@dataclass
class IdleCompileBackstopDecision:
    should_compile: bool
    reason: str
    checks: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_compile": self.should_compile,
            "reason": self.reason,
            "checks": self.checks,
        }


def _parse_run_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def post_run_plan_titles_without_open_match(
    *,
    latest_path: Path = DEFAULT_LATEST_PATH,
    tasks_path: Path = COMMITTED_TASKS_PATH,
) -> list[str]:
    """Plan action titles with no fuzzy match among open engineering tasks."""
    if not latest_path.exists():
        return []
    latest = read_json(latest_path)
    if not isinstance(latest, dict):
        return []
    post_run = latest.get("post_run_review")
    if not isinstance(post_run, dict):
        return []
    plan_text = str(post_run.get("improvement_plan") or "")
    plan_titles = post_run_plan_titles_from_text(plan_text)
    if not plan_titles:
        return []

    open_titles = [
        str(row.get("title") or "")
        for row in (load_engineering_tasks(tasks_path).get("tasks") or [])
        if isinstance(row, dict) and str(row.get("status") or "open") == "open"
    ]
    from value_investor.progress_report import _title_linked

    return [title for title in plan_titles if not _title_linked(title, open_titles)]


def post_run_artifact_fresh_enough(
    *,
    artifact_path: Path,
    latest_path: Path = DEFAULT_LATEST_PATH,
    stale_hours: int = DEFAULT_STALE_HOURS,
) -> tuple[bool, str]:
    """True when output post_run_review.md is not older than the published screen bundle."""
    if not artifact_path.exists():
        return False, "post_run_review.md missing"
    latest_run = None
    if latest_path.exists():
        latest = read_json(latest_path)
        if isinstance(latest, dict):
            latest_run = _parse_run_at(str(latest.get("run_at") or latest.get("updated_at") or ""))
    if latest_run is None:
        return True, "latest run_at unknown — allow compile"
    mtime = datetime.fromtimestamp(artifact_path.stat().st_mtime, tz=UTC)
    if mtime < latest_run - timedelta(hours=stale_hours):
        return (
            False,
            f"post_run artifact mtime {mtime.isoformat()} older than latest screen "
            f"{latest_run.isoformat()} (>{stale_hours}h)",
        )
    return True, "ok"


def evaluate_idle_compile_backstop(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    latest_path: Path = DEFAULT_LATEST_PATH,
    suggestions_path: Path = DEFAULT_SUGGESTIONS_PATH,
    max_tasks: int = DEFAULT_MAX_COMPILE_TASKS,
    stale_hours: int = DEFAULT_STALE_HOURS,
) -> IdleCompileBackstopDecision:
    """Decide whether to compile from output/latest post-run when the queue is idle."""
    status = summarize_queue(tasks_path=tasks_path)
    checks: dict[str, Any] = {
        "open_count": status.open_count,
        "pr_open_count": status.pr_open_count,
    }

    if status.open_count > 0 or status.pr_open_count > 0:
        return IdleCompileBackstopDecision(
            should_compile=False,
            reason="engineering queue not idle",
            checks=checks,
        )

    unlinked = post_run_plan_titles_without_open_match(
        latest_path=latest_path,
        tasks_path=tasks_path,
    )
    checks["unlinked_plan_titles"] = unlinked
    checks["unlinked_plan_count"] = len(unlinked)
    if not unlinked:
        return IdleCompileBackstopDecision(
            should_compile=False,
            reason="post-run plan aligned with open queue (or no plan lines)",
            checks=checks,
        )

    artifact = ensure_post_run_review_artifact(output_dir=output_dir, latest_path=latest_path)
    if artifact is None:
        return IdleCompileBackstopDecision(
            should_compile=False,
            reason="no post-run plan in latest.json or output/",
            checks=checks,
        )
    checks["post_run_artifact"] = str(artifact)
    fresh, fresh_reason = post_run_artifact_fresh_enough(
        artifact_path=artifact,
        latest_path=latest_path,
        stale_hours=stale_hours,
    )
    checks["artifact_fresh"] = fresh
    checks["artifact_fresh_reason"] = fresh_reason
    if not fresh:
        return IdleCompileBackstopDecision(
            should_compile=False,
            reason=fresh_reason,
            checks=checks,
        )

    dropped = audit_compile_drop_risk(tasks_path=tasks_path, output_dir=output_dir)
    checks["compile_drop_risk_ids"] = dropped
    if dropped:
        return IdleCompileBackstopDecision(
            should_compile=False,
            reason=f"compile would drop open tasks: {', '.join(dropped[:5])}",
            checks=checks,
        )

    would_add = preview_compile_new_open_count(
        output_dir=output_dir,
        tasks_path=tasks_path,
        suggestions_path=suggestions_path,
        max_tasks=max_tasks,
    )
    checks["preview_new_open_count"] = would_add
    if would_add <= 0:
        return IdleCompileBackstopDecision(
            should_compile=False,
            reason=(
                "compile would not add open tasks (likely already merged/parked) — "
                "run email_only for a fresh post-run plan"
            ),
            checks=checks,
        )

    return IdleCompileBackstopDecision(
        should_compile=True,
        reason=f"idle queue with {len(unlinked)} unlinked plan line(s); compile adds {would_add} open task(s)",
        checks=checks,
    )


def run_idle_compile_backstop(
    *,
    apply: bool = False,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    latest_path: Path = DEFAULT_LATEST_PATH,
    suggestions_path: Path = DEFAULT_SUGGESTIONS_PATH,
    max_tasks: int = DEFAULT_MAX_COMPILE_TASKS,
    stale_hours: int = DEFAULT_STALE_HOURS,
) -> dict[str, Any]:
    """Evaluate and optionally run compile_engineering_tasks for the idle backstop."""
    decision = evaluate_idle_compile_backstop(
        tasks_path=tasks_path,
        output_dir=output_dir,
        latest_path=latest_path,
        suggestions_path=suggestions_path,
        max_tasks=max_tasks,
        stale_hours=stale_hours,
    )
    result: dict[str, Any] = {"decision": decision.to_dict(), "applied": False}
    if not apply or not decision.should_compile:
        return result

    ensure_post_run_review_artifact(output_dir=output_dir, latest_path=latest_path)
    payload = compile_engineering_tasks(
        output_dir=output_dir,
        suggestions_path=suggestions_path,
        max_tasks=max_tasks,
        committed_path=tasks_path,
        tasks_path=tasks_path,
    )
    result["applied"] = True
    result["compile"] = {
        "added_open_count": payload.get("added_open_count"),
        "added_open_task_ids": payload.get("added_open_task_ids"),
        "task_count": payload.get("task_count"),
    }
    return result


def plan_titles_only_in_terminal_queue(
    *,
    latest_path: Path = DEFAULT_LATEST_PATH,
    tasks_path: Path = COMMITTED_TASKS_PATH,
) -> list[str]:
    """Plan lines that match only merged/parked tasks (Analysis ahead of actionable queue)."""
    unlinked = post_run_plan_titles_without_open_match(
        latest_path=latest_path,
        tasks_path=tasks_path,
    )
    if not unlinked:
        return []

    rows = load_engineering_tasks(tasks_path).get("tasks") or []
    terminal_titles = [
        str(row.get("title") or "")
        for row in rows
        if isinstance(row, dict) and str(row.get("status") or "open") in TERMINAL_TASK_STATUSES
    ]
    from value_investor.progress_report import _title_linked

    return [title for title in unlinked if _title_linked(title, terminal_titles)]


__all__ = [
    "IdleCompileBackstopDecision",
    "evaluate_idle_compile_backstop",
    "post_run_plan_titles_without_open_match",
    "run_idle_compile_backstop",
    "plan_titles_only_in_terminal_queue",
]
