"""Mid-week accelerated review: chain email_only after engineering queue drains (L97)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import (
    DEFAULT_WEEKLY_OPS_CAP_USD,
    load_policy,
    weekly_ops_budget_status,
)
from value_investor.engineering_queue import EngineeringQueueStatus, summarize_queue
from value_investor.engineering_tasks import COMMITTED_TASKS_PATH, find_engineering_task
from value_investor.ops_monitor import active_workflow_runs, _github_repo, _github_token
from value_investor.storage import read_json, write_json

logger = logging.getLogger(__name__)

DEFAULT_LOG_PATH = Path("docs/data/accelerated_review.json")
DEFAULT_MIN_HEADROOM_USD = 18.0
DEFAULT_ESTIMATED_EMAIL_ONLY_USD = 18.0
DEFAULT_MAX_MIDWEEK_PER_WEEK = 2
MATERIAL_MERGE_AREAS = frozenset({"ingest", "scoring", "prompt", "coverage"})


@dataclass
class AcceleratedEmailDecision:
    should_dispatch: bool
    reason: str
    checks: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_dispatch": self.should_dispatch,
            "reason": self.reason,
            "checks": dict(self.checks),
            "evaluated_at": datetime.now(UTC).isoformat(),
        }


def _iso_week_key(moment: datetime) -> str:
    iso = moment.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def load_accelerated_review_log(path: Path = DEFAULT_LOG_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "midweek_email_only_runs": []}
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return {"schema_version": 1, "midweek_email_only_runs": []}
    if not isinstance(payload, dict):
        return {"schema_version": 1, "midweek_email_only_runs": []}
    payload.setdefault("schema_version", 1)
    payload.setdefault("midweek_email_only_runs", [])
    return payload


def midweek_email_only_count(
    *,
    log_path: Path = DEFAULT_LOG_PATH,
    now: datetime | None = None,
) -> int:
    now = now or datetime.now(UTC)
    week_key = _iso_week_key(now)
    rows = load_accelerated_review_log(log_path).get("midweek_email_only_runs") or []
    count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        at = str(row.get("at") or "")
        try:
            stamp = datetime.fromisoformat(at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if _iso_week_key(stamp) == week_key:
            count += 1
    return count


def record_midweek_email_only_run(
    *,
    source: str,
    log_path: Path = DEFAULT_LOG_PATH,
    merged_task_id: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    payload = load_accelerated_review_log(log_path)
    entry: dict[str, Any] = {
        "at": datetime.now(UTC).isoformat(),
        "source": source,
    }
    if merged_task_id:
        entry["merged_task_id"] = merged_task_id
    if note:
        entry["note"] = note
    rows = list(payload.get("midweek_email_only_runs") or [])
    rows.append(entry)
    payload["midweek_email_only_runs"] = rows[-50:]
    payload["last_midweek_email_only_at"] = entry["at"]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(log_path, payload, compact=False)
    return entry


def evaluate_accelerated_email_only_dispatch(
    *,
    queue_status: EngineeringQueueStatus | None = None,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    policy_path: Path | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
    merged_task_id: str | None = None,
    repo: str | None = None,
    token: str | None = None,
    now: datetime | None = None,
    min_headroom_usd: float = DEFAULT_MIN_HEADROOM_USD,
    estimated_cost_usd: float = DEFAULT_ESTIMATED_EMAIL_ONLY_USD,
    max_midweek_per_week: int = DEFAULT_MAX_MIDWEEK_PER_WEEK,
) -> AcceleratedEmailDecision:
    """Decide whether to dispatch orchestrator suite=email_only after queue drain."""
    now = now or datetime.now(UTC)
    repo = repo or _github_repo()
    token = token or _github_token()
    status = queue_status or summarize_queue(tasks_path=tasks_path)
    checks: dict[str, Any] = {
        "open_count": status.open_count,
        "pr_open_count": status.pr_open_count,
        "merged_task_id": merged_task_id,
        "utc_weekday": now.weekday(),
        "iso_week": _iso_week_key(now),
    }

    if status.open_count > 0 or status.pr_open_count > 0:
        return AcceleratedEmailDecision(
            should_dispatch=False,
            reason="engineering queue not idle",
            checks=checks,
        )

    if now.weekday() == 6:
        return AcceleratedEmailDecision(
            should_dispatch=False,
            reason="Sunday — use scheduled SUITE=sunday instead",
            checks=checks,
        )

    if merged_task_id:
        task = find_engineering_task(merged_task_id, path=tasks_path)
        if task is None:
            return AcceleratedEmailDecision(
                should_dispatch=False,
                reason=f"merged task {merged_task_id} not found",
                checks=checks,
            )
        area = str(task.area or "").lower()
        checks["merged_task_area"] = area
        if area not in MATERIAL_MERGE_AREAS:
            return AcceleratedEmailDecision(
                should_dispatch=False,
                reason=f"merged task area {area} unlikely to need Analysis refresh",
                checks=checks,
            )

    policy = load_policy(policy_path)
    budget = weekly_ops_budget_status(policy, estimated_memo_usd=estimated_cost_usd)
    remaining = float(budget.get("remaining_weekly_ops_usd") or 0.0)
    checks["remaining_weekly_ops_usd"] = remaining
    checks["weekly_ops_cap_usd"] = float(
        budget.get("weekly_ops_cap_usd") or DEFAULT_WEEKLY_OPS_CAP_USD
    )
    if bool(budget.get("constraining")) or remaining < min_headroom_usd:
        return AcceleratedEmailDecision(
            should_dispatch=False,
            reason=(
                f"weekly_ops headroom insufficient "
                f"(${remaining:.2f} remaining, need ≥${min_headroom_usd:.2f})"
            ),
            checks=checks,
        )

    midweek_count = midweek_email_only_count(log_path=log_path, now=now)
    checks["midweek_email_only_this_week"] = midweek_count
    checks["max_midweek_per_week"] = max_midweek_per_week
    if midweek_count >= max_midweek_per_week:
        return AcceleratedEmailDecision(
            should_dispatch=False,
            reason=f"mid-week email_only cap reached ({midweek_count}/{max_midweek_per_week})",
            checks=checks,
        )

    if repo and token:
        for workflow in ("email-report.yml", "automation-orchestrator.yml"):
            active = active_workflow_runs(workflow, repo=repo, token=token)
            if active:
                checks["blocking_workflow"] = workflow
                checks["blocking_run_id"] = active[0].get("id")
                return AcceleratedEmailDecision(
                    should_dispatch=False,
                    reason=f"{workflow} already active",
                    checks=checks,
                )

    return AcceleratedEmailDecision(
        should_dispatch=True,
        reason="queue idle after material merge — chain email_only refresh",
        checks=checks,
    )
