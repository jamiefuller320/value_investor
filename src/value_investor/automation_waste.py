"""Detect repetitive automation that burns Cursor spend without landing work.

Findings feed ops-monitor → project-traffic (PM) so dispatch can pause and
burning tasks can be parked. Patterns are registry-driven so new workflows can
be added without inventing a parallel monitor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from value_investor.engineering_queue import (
    COMMITTED_TASKS_PATH,
    summarize_queue,
)
from value_investor.engineering_sync import ENGINEERING_AGENT_WORKFLOW

SCHEMA_VERSION = 1

FINDING_TITLE_ENG_AGENT_REBURN = "Automation waste: engineering agent reburn"
FINDING_TITLE_CURSOR_WORKFLOW_LOOP = "Automation waste: Cursor workflow fail loop"

DEFAULT_ENG_AGENT_FAIL_THRESHOLD = 3
DEFAULT_ENG_AGENT_WINDOW_HOURS = 6
DEFAULT_CURSOR_WORKFLOW_FAIL_THRESHOLD = 3
DEFAULT_CURSOR_WORKFLOW_WINDOW_HOURS = 12

# Workflows that call CURSOR_API_KEY / composer and are safe to flag on
# unresolved fail loops (no success after the failures). Extensible.
CURSOR_SPEND_WORKFLOWS: tuple[tuple[str, str], ...] = (
    (ENGINEERING_AGENT_WORKFLOW, "FTSE Engineering Agent"),
    ("analysis-review.yml", "Analysis Review"),
    ("paper-learning-review.yml", "Paper Learning Review"),
    ("learning-director-review.yml", "Learning Director Review"),
    ("horizon-scan.yml", "Horizon Scan"),
    ("library-model-review.yml", "Library Model Review"),
    ("memo-backfill.yml", "Memo Backfill"),
)


@dataclass
class WasteSignal:
    """One detected waste pattern for PM handoff."""

    kind: str
    title: str
    severity: str
    summary: str
    workflow: str | None = None
    task_ids: list[str] = field(default_factory=list)
    failure_count: int = 0
    window_hours: float = 0.0
    auto_remediable: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "severity": self.severity,
            "summary": self.summary,
            "workflow": self.workflow,
            "task_ids": list(self.task_ids),
            "failure_count": self.failure_count,
            "window_hours": self.window_hours,
            "auto_remediable": self.auto_remediable,
            "evidence": dict(self.evidence),
        }


def _utcnow() -> datetime:
    return datetime.now(UTC)


def detect_engineering_agent_reburn(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    open_prs: list[dict[str, Any]] | None = None,
    recent_agent_failures: list[dict[str, Any]] | None = None,
    fail_threshold: int = DEFAULT_ENG_AGENT_FAIL_THRESHOLD,
    window_hours: float = DEFAULT_ENG_AGENT_WINDOW_HOURS,
) -> WasteSignal | None:
    """Same open eng task keeps burning Composer without an in-flight PR."""
    failures = list(recent_agent_failures or [])
    if len(failures) < max(1, int(fail_threshold)):
        return None

    status = summarize_queue(tasks_path=tasks_path, open_prs=open_prs)
    if status.open_count <= 0 or status.in_flight_pr is not None:
        return None

    from value_investor.engineering_tasks import load_engineering_tasks

    data = load_engineering_tasks(tasks_path)
    open_ids = [
        str(row.get("id") or "")
        for row in list(data.get("tasks") or [])
        if str(row.get("status") or "") == "open" and row.get("id")
    ]
    next_ids = [status.next_task.id] if status.next_task else []
    # Prefer dispatch order: next task first, then remaining open ids.
    ordered: list[str] = []
    for task_id in next_ids + open_ids:
        if task_id and task_id not in ordered:
            ordered.append(task_id)

    task_txt = ", ".join(ordered[:5]) if ordered else "(open queue)"
    return WasteSignal(
        kind="eng_agent_reburn",
        title=FINDING_TITLE_ENG_AGENT_REBURN,
        severity="fail",
        summary=(
            f"{len(failures)} engineering-agent failure(s) in {window_hours:g}h while "
            f"open task(s) remain ({task_txt}) and no engineering PR is in flight. "
            "Likely park-not-committed / preflight reburn — pause dispatch and park."
        ),
        workflow=ENGINEERING_AGENT_WORKFLOW,
        task_ids=ordered,
        failure_count=len(failures),
        window_hours=float(window_hours),
        auto_remediable=True,
        evidence={
            "open_count": status.open_count,
            "in_flight_pr": status.in_flight_pr,
            "fail_threshold": int(fail_threshold),
        },
    )


def detect_cursor_workflow_fail_loops(
    *,
    failure_counts: dict[str, int],
    latest_success_at: dict[str, datetime | None] | None = None,
    fail_threshold: int = DEFAULT_CURSOR_WORKFLOW_FAIL_THRESHOLD,
    window_hours: float = DEFAULT_CURSOR_WORKFLOW_WINDOW_HOURS,
    now: datetime | None = None,
) -> list[WasteSignal]:
    """Unresolved Cursor-spend workflow failures repeating in a window.

    ``failure_counts`` maps workflow file → failure count in the window.
    ``latest_success_at`` maps workflow file → last success timestamp (or None).
    Failures after the last success count as unresolved; when success is unknown,
    the raw failure count is used.
    """
    now = now or _utcnow()
    latest_success_at = latest_success_at or {}
    signals: list[WasteSignal] = []
    labels = {wf: label for wf, label in CURSOR_SPEND_WORKFLOWS}

    for workflow, count in sorted(failure_counts.items()):
        if workflow == ENGINEERING_AGENT_WORKFLOW:
            # Covered by eng_agent_reburn (needs open-task context).
            continue
        if workflow not in labels:
            continue
        if int(count) < max(1, int(fail_threshold)):
            continue
        success_at = latest_success_at.get(workflow)
        # If we know of a success inside the window after failures started, skip.
        if success_at is not None and success_at >= now - timedelta(hours=window_hours):
            # Still flag when failures continue *after* that success — caller should
            # pass unresolved counts. Treat provided count as already unresolved.
            pass
        signals.append(
            WasteSignal(
                kind="cursor_workflow_fail_loop",
                title=FINDING_TITLE_CURSOR_WORKFLOW_LOOP,
                severity="warn",
                summary=(
                    f"{labels[workflow]} (`{workflow}`) failed {int(count)} time(s) "
                    f"in {window_hours:g}h without a lasting recovery — Cursor spend "
                    "may be looping. PM records for digest; auto-rerun stays with "
                    "workflow responders."
                ),
                workflow=workflow,
                failure_count=int(count),
                window_hours=float(window_hours),
                auto_remediable=False,
                evidence={"label": labels[workflow]},
            )
        )
    return signals


def collect_automation_waste_signals(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    open_prs: list[dict[str, Any]] | None = None,
    recent_agent_failures: list[dict[str, Any]] | None = None,
    cursor_workflow_failure_counts: dict[str, int] | None = None,
    eng_fail_threshold: int = DEFAULT_ENG_AGENT_FAIL_THRESHOLD,
    eng_window_hours: float = DEFAULT_ENG_AGENT_WINDOW_HOURS,
    workflow_fail_threshold: int = DEFAULT_CURSOR_WORKFLOW_FAIL_THRESHOLD,
    workflow_window_hours: float = DEFAULT_CURSOR_WORKFLOW_WINDOW_HOURS,
    now: datetime | None = None,
) -> list[WasteSignal]:
    """Run the waste registry and return all active signals."""
    signals: list[WasteSignal] = []
    eng = detect_engineering_agent_reburn(
        tasks_path=tasks_path,
        open_prs=open_prs,
        recent_agent_failures=recent_agent_failures,
        fail_threshold=eng_fail_threshold,
        window_hours=eng_window_hours,
    )
    if eng is not None:
        signals.append(eng)
    if cursor_workflow_failure_counts:
        signals.extend(
            detect_cursor_workflow_fail_loops(
                failure_counts=cursor_workflow_failure_counts,
                fail_threshold=workflow_fail_threshold,
                window_hours=workflow_window_hours,
                now=now,
            )
        )
    return signals


def count_failures_by_workflow(
    fetch_failures: Callable[[str, float], list[dict[str, Any]]],
    *,
    workflows: tuple[tuple[str, str], ...] = CURSOR_SPEND_WORKFLOWS,
    window_hours: float = DEFAULT_CURSOR_WORKFLOW_WINDOW_HOURS,
) -> dict[str, int]:
    """Helper: map workflow → failure count using a fetch callback."""
    out: dict[str, int] = {}
    for workflow, _label in workflows:
        rows = fetch_failures(workflow, window_hours) or []
        if rows:
            out[workflow] = len(rows)
    return out
