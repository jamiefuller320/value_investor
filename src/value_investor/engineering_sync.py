"""Detect and repair engineering queue / agent synchronisation issues."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from value_investor.engineering_queue import (
    evaluate_engineering_dispatch,
    summarize_queue,
)
from value_investor.engineering_recovery import recover_engineering_queue
from value_investor.engineering_tasks import (
    COMMITTED_TASKS_PATH,
    build_compiled_task_list,
    load_engineering_tasks,
    open_task_ids_dropped_by_merge,
    select_engineering_tasks,
)

ENGINEERING_AGENT_WORKFLOW = "engineering-agent.yml"


@dataclass
class EngineeringSyncReport:
    dropped_open_task_ids: list[str]
    recent_agent_failures: int
    stale_dispatch_task_id: str | None
    should_redispatch: bool
    repairs: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dropped_open_task_ids": self.dropped_open_task_ids,
            "recent_agent_failures": self.recent_agent_failures,
            "stale_dispatch_task_id": self.stale_dispatch_task_id,
            "should_redispatch": self.should_redispatch,
            "repairs": self.repairs,
        }


def resolve_dispatch_task_id(
    task_id: str | None,
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
) -> str | None:
    """Return task_id when still open, otherwise the current top open task."""
    wanted = str(task_id or "").strip()
    if wanted and select_engineering_tasks(path=tasks_path, task_id=wanted):
        return wanted
    tasks = select_engineering_tasks(path=tasks_path, max_tasks=1)
    return tasks[0].id if tasks else None


def task_id_still_open(
    task_id: str | None,
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
) -> bool:
    wanted = str(task_id or "").strip()
    if not wanted:
        return False
    return bool(select_engineering_tasks(path=tasks_path, task_id=wanted))


def audit_compile_drop_risk(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    output_dir: Path = Path("output"),
) -> list[str]:
    """Open task ids that would be dropped if compile ran against output artifacts."""
    output_dir = Path(output_dir)
    if not (output_dir / "post_run_review.md").exists():
        return []
    existing_rows = list(load_engineering_tasks(tasks_path).get("tasks") or [])
    compiled = build_compiled_task_list(output_dir=output_dir)
    return open_task_ids_dropped_by_merge(existing_rows, compiled)


def run_engineering_sync(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    output_dir: Path = Path("output"),
    open_prs: list[dict[str, Any]] | None = None,
    recent_agent_failures: list[dict[str, Any]] | None = None,
    apply: bool = False,
    repo: str | None = None,
    token: str | None = None,
    latest_success_by_workflow: dict[str, dict] | None = None,
) -> EngineeringSyncReport:
    """
    Detect queue/agent desync and optionally reconcile queue state.

    Repairs are limited to queue reconciliation — they never rewrite task payloads.
    """
    dropped = audit_compile_drop_risk(tasks_path=tasks_path, output_dir=output_dir)
    failures = list(recent_agent_failures or [])
    status = summarize_queue(tasks_path=tasks_path, open_prs=open_prs)
    repairs: list[dict[str, str]] = []

    stale_dispatch: str | None = None
    if failures and status.open_count > 0 and status.in_flight_pr is None:
        stale_dispatch = status.next_task.id if status.next_task else None

    needs_repair = bool(dropped) or (
        bool(failures) and status.open_count > 0 and status.in_flight_pr is None
    )

    if apply and needs_repair:
        recovery = recover_engineering_queue(
            tasks_path=tasks_path,
            open_prs=open_prs,
            repo=repo,
            token=token,
            recent_agent_failures=failures,
            latest_success_by_workflow=latest_success_by_workflow,
            apply=True,
        )
        if recovery.merged:
            repairs.append(
                {
                    "action": "mark_merged_pr",
                    "detail": ", ".join(recovery.merged),
                }
            )
        if recovery.cancelled:
            repairs.append(
                {
                    "action": "cancel_resolved_workflow_failure",
                    "detail": ", ".join(row.task_id for row in recovery.cancelled),
                }
            )
        if recovery.reconciled:
            repairs.append(
                {
                    "action": "reconcile_pr_open",
                    "detail": ", ".join(recovery.reconciled),
                }
            )
        if recovery.reopened:
            repairs.append(
                {
                    "action": "reopen_failed_tasks",
                    "detail": ", ".join(recovery.reopened),
                }
            )
        if recovery.parked:
            repairs.append(
                {
                    "action": "park_blocked_tasks",
                    "detail": ", ".join(row.task_id for row in recovery.parked),
                }
            )

    dispatch = evaluate_engineering_dispatch(tasks_path=tasks_path, open_prs=open_prs)
    should_redispatch = dispatch.should_dispatch and (
        needs_repair or bool(repairs) or (bool(failures) and status.open_count > 0)
    )

    return EngineeringSyncReport(
        dropped_open_task_ids=dropped,
        recent_agent_failures=len(failures),
        stale_dispatch_task_id=stale_dispatch,
        should_redispatch=should_redispatch,
        repairs=repairs,
    )


def summarize_sync_findings(
    report: EngineeringSyncReport,
    *,
    status_open_count: int,
    in_flight_pr: int | None,
) -> list[dict[str, str]]:
    """Human-readable finding summaries for ops monitor."""
    rows: list[dict[str, str]] = []
    if report.dropped_open_task_ids:
        rows.append(
            {
                "severity": "fail",
                "title": "Engineering compile would drop open tasks",
                "summary": (
                    f"{len(report.dropped_open_task_ids)} open task(s) would be removed by compile: "
                    f"{', '.join(report.dropped_open_task_ids[:5])}"
                ),
            }
        )
    if report.recent_agent_failures and status_open_count > 0 and in_flight_pr is None:
        rows.append(
            {
                "severity": "fail",
                "title": "Engineering agent sync failures",
                "summary": (
                    f"{report.recent_agent_failures} engineering-agent failure(s) in the last 6h "
                    "while open tasks remain and no engineering PR is in flight."
                ),
            }
        )
    return rows
