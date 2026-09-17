"""Append-only engineering queue lane monitor for idle/dispatch diagnosis."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.engineering_preflight import (
    annotate_dispatch_ranks,
    build_task_dispatch_reports,
)
from value_investor.engineering_queue import (
    COMMITTED_TASKS_PATH,
    evaluate_engineering_dispatch,
    load_engineering_tasks,
)
from value_investor.engineering_recovery import (
    count_attention_parked_tasks,
    is_queue_clearing_pause_active,
)
from value_investor.project_traffic import (
    get_traffic_control_state,
    is_traffic_pause_active,
)
from value_investor.storage import write_json

DEFAULT_MONITOR_JSONL = Path("docs/data/engineering_queue_monitor.jsonl")
DEFAULT_MONITOR_SUMMARY = Path("docs/data/engineering_queue_monitor_summary.json")
DEFAULT_MAX_JSONL_LINES = 192  # ~8 days at hourly + merge triggers

SCHEMA_VERSION = 1


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _eng_open_pr_numbers(open_prs: list[dict[str, Any]] | None) -> list[int]:
    out: list[int] = []
    for row in open_prs or []:
        branch = str(row.get("headRefName") or row.get("head_branch") or "")
        if not branch.startswith("cursor/eng-"):
            continue
        raw = row.get("number")
        try:
            out.append(int(raw))
        except (TypeError, ValueError):
            continue
    return sorted(out)


def _clash_summary(
    data: dict[str, Any], *, open_prs: list[dict[str, Any]] | None
) -> dict[str, Any]:
    reports = build_task_dispatch_reports(data, open_prs=open_prs or [], blocked_paths=[])
    annotate_dispatch_ranks(reports)
    open_reports = [r for r in reports if str(r.task.status) == "open"]
    eligible = sum(1 for r in open_reports if r.to_dict().get("dispatch_eligible"))
    blocked = sum(1 for r in open_reports if not r.to_dict().get("dispatch_eligible"))
    return {
        "open_task_count": len(open_reports),
        "dispatch_eligible_count": eligible,
        "blocked_count": blocked,
    }


def _open_task_rows(
    data: dict[str, Any], *, open_prs: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    reports = build_task_dispatch_reports(data, open_prs=open_prs or [], blocked_paths=[])
    annotate_dispatch_ranks(reports)
    rows: list[dict[str, Any]] = []
    for report in reports:
        status = str(report.task.status)
        if status not in {"open", "pr_open"}:
            continue
        meta = report.to_dict()
        rows.append(
            {
                "id": report.task.id,
                "status": status,
                "dispatch_eligible": bool(meta.get("dispatch_eligible")),
                "blocked_by": list(meta.get("blocked_by") or [])[:4],
                "pr_number": getattr(report.task, "pr_number", None),
            }
        )
    return rows


def build_queue_monitor_snapshot(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    open_prs: list[dict[str, Any]] | None = None,
    agent_running_count: int = 0,
    event_source: str = "unknown",
    gate_json: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """One point-in-time record of dispatch eligibility and blockers."""
    now = now or _utcnow()
    decision = evaluate_engineering_dispatch(
        tasks_path=tasks_path,
        open_prs=open_prs,
        agent_running_count=agent_running_count,
    )
    data = load_engineering_tasks(tasks_path)
    traffic = get_traffic_control_state(tasks_path=tasks_path)
    status = decision.status
    clash = _clash_summary(data, open_prs=open_prs)
    gate = gate_json or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "recorded_at": now.isoformat(),
        "event_source": event_source,
        "dispatch": {
            "should_dispatch": decision.should_dispatch,
            "reason": decision.reason,
            "next_task_ids": list(decision.next_task_ids or [])
            or ([decision.next_task_id] if decision.next_task_id else []),
        },
        "queue": {
            "open_count": status.open_count,
            "pr_open_count": status.pr_open_count,
            "parked_count": status.parked_count,
            "spend_blocked": status.spend_blocked,
            "spend_since_checkpoint_usd": status.spend_since_checkpoint_usd,
            "spend_checkpoint_usd": status.spend_checkpoint_usd,
        },
        "pauses": {
            "traffic_pause_active": is_traffic_pause_active(tasks_path=tasks_path),
            "stuck_pr_count": int(traffic.get("stuck_pr_count") or 0),
            "queue_clearing_pause_active": is_queue_clearing_pause_active(tasks_path=tasks_path),
            "attention_parked_count": count_attention_parked_tasks(tasks_path=tasks_path),
        },
        "clash": clash,
        "github": {
            "agent_running_count": int(agent_running_count),
            "open_engineering_pr_numbers": _eng_open_pr_numbers(open_prs),
        },
        "open_tasks": _open_task_rows(data, open_prs=open_prs),
        "gate_eval": {
            "should_dispatch": gate.get("should_dispatch"),
            "reason": gate.get("reason"),
        }
        if gate
        else None,
    }


def append_queue_monitor_snapshot(
    snapshot: dict[str, Any],
    *,
    path: Path = DEFAULT_MONITOR_JSONL,
    max_lines: int = DEFAULT_MAX_JSONL_LINES,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(snapshot, separators=(",", ":"), sort_keys=True)
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    existing.append(line)
    if len(existing) > max_lines:
        existing = existing[-max_lines:]
    path.write_text("\n".join(existing) + ("\n" if existing else ""), encoding="utf-8")
    return path


def load_monitor_snapshots(*, path: Path = DEFAULT_MONITOR_JSONL) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def summarize_monitor_window(
    snapshots: list[dict[str, Any]],
    *,
    hours: float = 24.0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Aggregate monitor JSONL for a recent window."""
    now = now or _utcnow()
    cutoff = now - timedelta(hours=hours)
    window: list[dict[str, Any]] = []
    for row in snapshots:
        raw = row.get("recorded_at")
        if not raw:
            continue
        try:
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts >= cutoff:
            window.append(row)

    def _count(pred) -> int:
        return sum(1 for r in window if pred(r))

    reasons: dict[str, int] = {}
    for row in window:
        reason = str((row.get("dispatch") or {}).get("reason") or "unknown")
        reasons[reason] = reasons.get(reason, 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "window_hours": hours,
        "snapshot_count": len(window),
        "should_dispatch_true_count": _count(
            lambda r: (r.get("dispatch") or {}).get("should_dispatch")
        ),
        "traffic_pause_snapshots": _count(
            lambda r: (r.get("pauses") or {}).get("traffic_pause_active")
        ),
        "eligible_zero_open_positive": _count(
            lambda r: (
                int((r.get("queue") or {}).get("open_count") or 0) > 0
                and int((r.get("clash") or {}).get("dispatch_eligible_count") or 0) == 0
            )
        ),
        "idle_open_zero_pr_zero": _count(
            lambda r: (
                int((r.get("queue") or {}).get("open_count") or 0) == 0
                and int((r.get("queue") or {}).get("pr_open_count") or 0) == 0
            )
        ),
        "median_open_eng_prs": _median(
            [len((r.get("github") or {}).get("open_engineering_pr_numbers") or []) for r in window]
        ),
        "dispatch_reason_counts": dict(sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))),
        "first_recorded_at": window[0].get("recorded_at") if window else None,
        "last_recorded_at": window[-1].get("recorded_at") if window else None,
    }


def _median(values: list[int]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def write_monitor_summary(
    summary: dict[str, Any],
    *,
    path: Path = DEFAULT_MONITOR_SUMMARY,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, summary, compact=False)
    return path


def _gh_json(argv: list[str]) -> Any:
    result = subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "gh failed").strip()
        raise RuntimeError(detail)
    return json.loads(result.stdout or "null")


def fetch_gha_workflow_runs(
    workflow_file: str,
    *,
    limit: int = 40,
) -> list[dict[str, Any]]:
    raw = _gh_json(
        [
            "gh",
            "run",
            "list",
            "--workflow",
            workflow_file,
            "--limit",
            str(limit),
            "--json",
            "databaseId,status,conclusion,createdAt,displayTitle,event",
        ]
    )
    return list(raw) if isinstance(raw, list) else []


def build_gha_activity_report(
    *, hours: float = 24.0, now: datetime | None = None
) -> dict[str, Any]:
    """Correlate engineering-queue and engineering-agent GitHub Actions runs."""
    now = now or _utcnow()
    cutoff = now - timedelta(hours=hours)
    queues = fetch_gha_workflow_runs("engineering-queue.yml", limit=60)
    agents = fetch_gha_workflow_runs("engineering-agent.yml", limit=60)

    def _filter(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        kept: list[dict[str, Any]] = []
        for row in rows:
            raw = row.get("createdAt")
            if not raw:
                continue
            try:
                ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except ValueError:
                continue
            if ts >= cutoff:
                kept.append(row)
        return kept

    q = _filter(queues)
    a = _filter(agents)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "window_hours": hours,
        "engineering_queue_runs": len(q),
        "engineering_agent_runs": len(a),
        "engineering_queue_events": _event_counts(q),
        "engineering_agent_events": _event_counts(a),
        "recent_engineering_agent_titles": [str(r.get("displayTitle") or "")[:120] for r in a[:8]],
    }


def _event_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows:
        key = str(row.get("event") or "unknown")
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))
