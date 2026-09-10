"""Dashboard queue / hunter health snapshot — idle vs blocked vs running."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.engineering_queue import (
    COMMITTED_TASKS_PATH,
    DEFAULT_AUTOMATION_PATH,
    DEFAULT_LATEST_PATH,
    evaluate_engineering_dispatch,
    load_engineering_tasks,
    summarize_queue,
)
from value_investor.engineering_recovery import (
    count_attention_parked_tasks,
    get_queue_clearing_state,
    is_queue_clearing_pause_active,
)
from value_investor.storage import read_json, write_json

DEFAULT_QUEUE_HEALTH_PATH = Path("docs/data/queue_health.json")
DEFAULT_OPS_STATUS_PATH = Path("docs/data/ops_status.json")

SCHEMA_VERSION = 1


def _lane_state(*, idle: bool, running: bool, blocked: bool) -> str:
    if running:
        return "running"
    if blocked:
        return "blocked"
    if idle:
        return "idle"
    return "unknown"


def _read_ops_status(path: Path = DEFAULT_OPS_STATUS_PATH) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _merge_lane_snapshot(
    *,
    status: Any,
    open_prs: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    pr_open = int(getattr(status, "pr_open_count", 0) or 0)
    in_flight_pr = getattr(status, "in_flight_pr", None)
    eng_prs = []
    for row in open_prs or []:
        branch = str(row.get("headRefName") or row.get("head_branch") or "")
        if branch.startswith("cursor/eng-"):
            eng_prs.append(
                {
                    "number": row.get("number"),
                    "branch": branch,
                    "draft": bool(row.get("isDraft") or row.get("draft")),
                }
            )

    idle = pr_open == 0 and not eng_prs and in_flight_pr is None
    running = pr_open > 0 or bool(eng_prs) or in_flight_pr is not None
    blocked = False
    detail = "No open engineering PRs — auto-merge waits for green CI on a branch."
    if eng_prs:
        nums = ", ".join(f"#{row['number']}" for row in eng_prs if row.get("number"))
        detail = f"Open engineering PR(s) {nums or 'present'} — merge fires on CI success."
    elif in_flight_pr:
        detail = (
            f"In-flight PR #{in_flight_pr} — auto-merge is event-driven (not a background merger)."
        )

    return {
        "state": _lane_state(idle=idle, running=running and not blocked, blocked=blocked),
        "idle": idle,
        "running": running,
        "blocked": blocked,
        "pr_open_count": pr_open,
        "open_engineering_prs": eng_prs,
        "in_flight_pr": in_flight_pr,
        "detail": detail,
    }


def _agent_lane_snapshot(
    *,
    tasks_path: Path,
    open_prs: list[dict[str, Any]] | None,
    dispatch: Any,
    clash_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    status = dispatch.status
    open_count = int(getattr(status, "open_count", 0) or 0)
    pr_open_count = int(getattr(status, "pr_open_count", 0) or 0)
    pause_active = is_queue_clearing_pause_active(tasks_path=tasks_path)
    attention_parked = count_attention_parked_tasks(tasks_path=tasks_path)
    should_dispatch = bool(getattr(dispatch, "should_dispatch", False))
    reason = str(getattr(dispatch, "reason", "") or "")

    clash = clash_summary or {}
    blocked_count = int(clash.get("blocked_count") or 0)
    eligible_count = int(clash.get("dispatch_eligible_count") or 0)

    idle = open_count == 0 and pr_open_count == 0
    orphan_pr_open = pr_open_count > 0 and open_count == 0
    running = should_dispatch or (pr_open_count > 0 and open_count > 0)
    blocked = (
        pause_active
        or blocked_count > 0
        or (open_count > 0 and not should_dispatch)
        or orphan_pr_open
    )

    if orphan_pr_open:
        detail = (
            f"Orphan pr_open state ({pr_open_count} pr_open, 0 open) — "
            "recover-queue should reconcile or mark merged."
        )
    elif pause_active:
        detail = (
            f"Dispatch paused — {attention_parked} attention-parked task(s). "
            f"{reason or 'Clear backlog to resume.'}"
        )
    elif idle:
        detail = "No open engineering tasks — queue is idle."
    elif should_dispatch:
        detail = reason or "Queue ready — hourly dispatch or ops monitor may start the agent."
    elif blocked_count and open_count:
        detail = f"{blocked_count} open task(s) blocked by file clash or policy — {reason}"
    else:
        detail = reason or "Agent dispatch held."

    next_task = getattr(status, "next_task", None)
    next_task_id = getattr(next_task, "id", None) if next_task else None

    return {
        "state": _lane_state(idle=idle, running=running and not blocked, blocked=blocked),
        "idle": idle,
        "running": running,
        "blocked": blocked,
        "should_dispatch": should_dispatch,
        "pause_active": pause_active,
        "attention_parked_count": attention_parked,
        "open_count": open_count,
        "pr_open_count": pr_open_count,
        "dispatch_eligible_count": eligible_count,
        "blocked_task_count": blocked_count,
        "next_task_id": next_task_id,
        "reason": reason,
        "detail": detail,
    }


def build_queue_health_snapshot(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    ops_status_path: Path = DEFAULT_OPS_STATUS_PATH,
    open_prs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Roll up merge lane, agent lane, and ops monitor into one dashboard snapshot."""
    from value_investor.engineering_preflight import clash_report_for_queue
    from value_investor.engineering_queue import in_flight_allowed_paths

    data = load_engineering_tasks(tasks_path)
    status = summarize_queue(data, tasks_path=tasks_path, open_prs=open_prs)
    dispatch = evaluate_engineering_dispatch(tasks_path=tasks_path, open_prs=open_prs)
    in_flight_paths = in_flight_allowed_paths(data, open_prs=open_prs)
    clash_summary = clash_report_for_queue(
        data,
        blocked_paths=in_flight_paths,
        open_prs=open_prs,
    )

    merge_lane = _merge_lane_snapshot(status=status, open_prs=open_prs)
    agent_lane = _agent_lane_snapshot(
        tasks_path=tasks_path,
        open_prs=open_prs,
        dispatch=dispatch,
        clash_summary=clash_summary,
    )
    clearing = get_queue_clearing_state(tasks_path=tasks_path)
    ops_status = _read_ops_status(ops_status_path)

    overall = "ok"
    if agent_lane["blocked"] or merge_lane["blocked"]:
        overall = "blocked"
    elif agent_lane["idle"] and merge_lane["idle"]:
        overall = "idle"
    elif agent_lane["running"] or merge_lane["running"]:
        overall = "active"

    headline = "Queue and hunter idle."
    if overall == "blocked":
        headline = agent_lane["detail"] if agent_lane["blocked"] else merge_lane["detail"]
    elif overall == "active":
        parts = []
        if merge_lane["running"]:
            parts.append("merge lane active")
        if agent_lane["running"]:
            parts.append("agent lane active")
        headline = "; ".join(parts).capitalize() + "."

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "overall": overall,
        "headline": headline,
        "merge_lane": merge_lane,
        "agent_lane": agent_lane,
        "queue_clearing": {
            "pause_active": bool(clearing.get("pause_active")),
            "attention_parked_count": int(clearing.get("attention_parked_count") or 0),
            "evaluated_at": clearing.get("evaluated_at"),
        },
        "ops_monitor": {
            "run_at": (ops_status or {}).get("run_at"),
            "overall": (ops_status or {}).get("overall"),
            "should_dispatch_engineering": (ops_status or {}).get("should_dispatch_engineering"),
        },
    }


def refresh_queue_health_ui(
    *,
    automation_path: Path = DEFAULT_AUTOMATION_PATH,
    latest_path: Path = DEFAULT_LATEST_PATH,
    queue_health_path: Path = DEFAULT_QUEUE_HEALTH_PATH,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    ops_status_path: Path = DEFAULT_OPS_STATUS_PATH,
    open_prs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Write queue_health.json and embed in automation.json / latest.json."""
    snapshot = build_queue_health_snapshot(
        tasks_path=tasks_path,
        ops_status_path=ops_status_path,
        open_prs=open_prs,
    )
    now = snapshot["generated_at"]
    queue_health_path = Path(queue_health_path)
    queue_health_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(queue_health_path, snapshot, compact=False)

    automation_path = Path(automation_path)
    if automation_path.exists():
        try:
            auto = read_json(automation_path)
        except (OSError, ValueError, TypeError):
            auto = {}
        if not isinstance(auto, dict):
            auto = {}
    else:
        auto = {}
    auto["queue_health"] = snapshot
    auto["generated_at"] = now
    automation_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(automation_path, auto, compact=False)

    latest_path = Path(latest_path)
    if latest_path.exists():
        try:
            latest = read_json(latest_path)
        except (OSError, ValueError, TypeError):
            latest = None
        if isinstance(latest, dict):
            automation = latest.get("automation")
            if isinstance(automation, dict):
                automation["queue_health"] = snapshot
                automation["generated_at"] = now
            else:
                latest["automation"] = {"queue_health": snapshot, "generated_at": now}
            latest["generated_at"] = now
            write_json(latest_path, latest, compact=True, compress=False)

    return {
        "queue_health_path": str(queue_health_path),
        "overall": snapshot["overall"],
        "headline": snapshot["headline"],
        "merge_lane": snapshot["merge_lane"]["state"],
        "agent_lane": snapshot["agent_lane"]["state"],
    }
