"""Evaluate whether to auto-dispatch the next supervised engineering task."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import (
    load_policy,
    spend_checkpoint_usd,
    spend_since_checkpoint_usd,
)
from value_investor.engineering_tasks import (
    COMMITTED_TASKS_PATH,
    EngineeringTask,
    load_engineering_tasks,
    select_engineering_tasks,
    task_title_key,
)

ENGINEERING_BRANCH_RE = re.compile(r"^cursor/eng-\d{8}-\d{2}-1de3$")
ENGINEERING_PR_TITLE_PREFIX = "feat(engineering):"

TERMINAL_STATUSES = frozenset({"merged", "completed", "failed", "cancelled"})
DISPATCHABLE_STATUS = "open"
IN_FLIGHT_STATUS = "pr_open"


@dataclass
class EngineeringQueueStatus:
    open_count: int
    pr_open_count: int
    merged_count: int
    failed_count: int
    next_task: EngineeringTask | None
    in_flight_branch: str | None
    in_flight_pr: int | None
    spend_since_checkpoint_usd: float
    spend_checkpoint_usd: float
    spend_blocked: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "open_count": self.open_count,
            "pr_open_count": self.pr_open_count,
            "merged_count": self.merged_count,
            "failed_count": self.failed_count,
            "next_task_id": self.next_task.id if self.next_task else None,
            "in_flight_branch": self.in_flight_branch,
            "in_flight_pr": self.in_flight_pr,
            "spend_since_checkpoint_usd": self.spend_since_checkpoint_usd,
            "spend_checkpoint_usd": self.spend_checkpoint_usd,
            "spend_blocked": self.spend_blocked,
        }


@dataclass
class EngineeringDispatchDecision:
    should_dispatch: bool
    reason: str
    status: EngineeringQueueStatus
    next_task_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "should_dispatch": self.should_dispatch,
            "reason": self.reason,
            "next_task_id": self.next_task_id,
            "status": self.status.to_dict(),
            "evaluated_at": datetime.now(UTC).isoformat(),
        }
        return payload


def is_engineering_branch(branch: str | None) -> bool:
    return bool(branch and ENGINEERING_BRANCH_RE.match(branch.strip()))


def is_engineering_pr_title(title: str | None) -> bool:
    return bool(title and title.strip().lower().startswith(ENGINEERING_PR_TITLE_PREFIX))


def find_in_flight_pr(open_prs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the newest open engineering PR, if any."""
    candidates: list[dict[str, Any]] = []
    for row in open_prs:
        branch = str(row.get("headRefName") or row.get("head_branch") or "")
        title = str(row.get("title") or "")
        if is_engineering_branch(branch) or is_engineering_pr_title(title):
            candidates.append(row)
    if not candidates:
        return None
    candidates.sort(key=lambda row: str(row.get("createdAt") or row.get("created_at") or ""), reverse=True)
    return candidates[0]


def task_id_from_branch(branch: str) -> str | None:
    match = re.match(r"^cursor/(eng-\d{8}-\d{2})-1de3$", branch.strip())
    return match.group(1) if match else None


def summarize_queue(
    payload: dict[str, Any] | None = None,
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    policy_path: Path | None = None,
    open_prs: list[dict[str, Any]] | None = None,
) -> EngineeringQueueStatus:
    data = payload or load_engineering_tasks(tasks_path)
    rows = list(data.get("tasks") or [])
    open_count = sum(1 for row in rows if str(row.get("status") or "open") == DISPATCHABLE_STATUS)
    pr_open_count = sum(1 for row in rows if str(row.get("status") or "") == IN_FLIGHT_STATUS)
    merged_count = sum(
        1 for row in rows if str(row.get("status") or "") in {"merged", "completed"}
    )
    failed_count = sum(1 for row in rows if str(row.get("status") or "") == "failed")

    next_tasks = select_engineering_tasks(data, max_tasks=1)
    next_task = next_tasks[0] if next_tasks else None

    in_flight = find_in_flight_pr(open_prs or [])
    in_flight_branch = None
    in_flight_pr = None
    if in_flight is not None:
        in_flight_branch = str(in_flight.get("headRefName") or in_flight.get("head_branch") or "") or None
        in_flight_pr = int(in_flight["number"]) if in_flight.get("number") is not None else None

    policy = load_policy(policy_path)
    since = spend_since_checkpoint_usd(policy)
    limit = spend_checkpoint_usd(policy)

    return EngineeringQueueStatus(
        open_count=open_count,
        pr_open_count=pr_open_count,
        merged_count=merged_count,
        failed_count=failed_count,
        next_task=next_task,
        in_flight_branch=in_flight_branch,
        in_flight_pr=in_flight_pr,
        spend_since_checkpoint_usd=since,
        spend_checkpoint_usd=limit,
        spend_blocked=since >= limit,
    )


def evaluate_engineering_dispatch(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    policy_path: Path | None = None,
    open_prs: list[dict[str, Any]] | None = None,
    engineering_agent_running: bool = False,
    force: bool = False,
) -> EngineeringDispatchDecision:
    """Decide whether the queue processor should dispatch engineering-agent."""
    status = summarize_queue(
        tasks_path=tasks_path,
        policy_path=policy_path,
        open_prs=open_prs,
    )

    if engineering_agent_running:
        return EngineeringDispatchDecision(
            should_dispatch=False,
            reason="engineering-agent workflow already running",
            status=status,
        )

    if status.in_flight_pr is not None:
        return EngineeringDispatchDecision(
            should_dispatch=False,
            reason=f"open engineering PR #{status.in_flight_pr} ({status.in_flight_branch})",
            status=status,
        )

    if status.next_task is None:
        return EngineeringDispatchDecision(
            should_dispatch=False,
            reason="no open engineering tasks in queue",
            status=status,
        )

    if status.spend_blocked and not force:
        return EngineeringDispatchDecision(
            should_dispatch=False,
            reason=(
                f"ad-hoc spend checkpoint reached "
                f"(${status.spend_since_checkpoint_usd:.2f} / ${status.spend_checkpoint_usd:.2f})"
            ),
            status=status,
        )

    return EngineeringDispatchDecision(
        should_dispatch=True,
        reason="queue ready — dispatch next open task",
        status=status,
        next_task_id=status.next_task.id,
    )
