"""Self-repair and parking policies for the supervised engineering queue."""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.engineering_queue import (
    IN_FLIGHT_STATUS,
    reconcile_orphaned_pr_open_tasks,
)
from value_investor.engineering_tasks import COMMITTED_TASKS_PATH, load_engineering_tasks, mark_task_status

logger = logging.getLogger(__name__)

PARKED_STATUS = "parked"
DEFAULT_MAX_AGENT_RETRIES = 2
DEFAULT_RETRY_COOLDOWN_HOURS = 24
DEFAULT_CI_RED_PARK_HOURS = 48
GITHUB_API_VERSION = "2022-11-28"


def _github_token() -> str | None:
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "GH_PAT"):
        value = os.environ.get(key)
        if value:
            return value
    return None


def _github_repo() -> str | None:
    value = os.environ.get("GITHUB_REPOSITORY")
    if value and "/" in value:
        return value
    return None


def _github_api_get(path: str, *, token: str | None = None) -> Any:
    token = token or _github_token()
    if not token:
        raise RuntimeError("GitHub token not configured")
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


@dataclass
class RecoveryAction:
    task_id: str
    action: str
    reason: str
    from_status: str
    to_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "action": self.action,
            "reason": self.reason,
            "from_status": self.from_status,
            "to_status": self.to_status,
        }


@dataclass
class RecoveryResult:
    reconciled: list[str] = field(default_factory=list)
    reopened: list[str] = field(default_factory=list)
    parked: list[RecoveryAction] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reconciled": self.reconciled,
            "reopened": self.reopened,
            "parked": [row.to_dict() for row in self.parked],
            "skipped": self.skipped,
            "action_count": len(self.reconciled) + len(self.reopened) + len(self.parked),
        }


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _open_pr_by_branch(open_prs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for row in open_prs:
        branch = str(row.get("headRefName") or row.get("head_branch") or "").strip()
        if branch:
            mapping[branch] = row
    return mapping


def _pr_check_state(
    pr_number: int,
    *,
    repo: str | None,
    token: str | None,
) -> dict[str, Any]:
    """Return combined check state for a PR head commit."""
    if not repo or not token:
        return {"available": False}
    owner, name = repo.split("/", 1)
    try:
        pr = _github_api_get(f"/repos/{owner}/{name}/pulls/{pr_number}", token=token)
        head_sha = str((pr.get("head") or {}).get("sha") or "")
        if not head_sha:
            return {"available": False}
        checks = _github_api_get(
            f"/repos/{owner}/{name}/commits/{head_sha}/check-runs?per_page=100",
            token=token,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        logger.warning("PR check lookup failed for #%s: %s", pr_number, exc)
        return {"available": False, "error": str(exc)}

    rows = list((checks or {}).get("check_runs") or [])
    relevant = [
        row
        for row in rows
        if str(row.get("name") or "").strip()
        and str(row.get("status") or "").lower() == "completed"
    ]
    if not relevant:
        return {
            "available": True,
            "head_sha": head_sha,
            "completed_checks": 0,
            "all_failed": False,
            "any_success": False,
        }

    failures = [row for row in relevant if str(row.get("conclusion") or "").lower() in {"failure", "cancelled", "timed_out"}]
    successes = [row for row in relevant if str(row.get("conclusion") or "").lower() == "success"]
    return {
        "available": True,
        "head_sha": head_sha,
        "completed_checks": len(relevant),
        "all_failed": bool(relevant) and len(successes) == 0 and len(failures) == len(relevant),
        "any_success": bool(successes),
        "latest_check_at": max(
            (_parse_iso(str(row.get("completed_at") or "")) for row in relevant),
            default=None,
        ),
    }


def _park_task(
    task_id: str,
    *,
    reason: str,
    tasks_path: Path,
    from_status: str,
    apply: bool,
) -> RecoveryAction:
    action = RecoveryAction(
        task_id=task_id,
        action="park",
        reason=reason,
        from_status=from_status,
        to_status=PARKED_STATUS,
    )
    if apply:
        mark_task_status(
            task_id,
            PARKED_STATUS,
            path=tasks_path,
            parked_reason=reason,
        )
    return action


def retry_failed_tasks(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    max_retries: int = DEFAULT_MAX_AGENT_RETRIES,
    cooldown_hours: int = DEFAULT_RETRY_COOLDOWN_HOURS,
    apply: bool = True,
    now: datetime | None = None,
) -> tuple[list[str], list[RecoveryAction]]:
    """Reopen failed tasks when retries remain and cooldown has elapsed."""
    now = now or datetime.now(UTC)
    cooldown = timedelta(hours=max(1, int(cooldown_hours)))
    reopened: list[str] = []
    parked: list[RecoveryAction] = []
    data = load_engineering_tasks(tasks_path)

    for row in data.get("tasks") or []:
        if str(row.get("status") or "") != "failed":
            continue
        task_id = str(row.get("id") or "")
        if not task_id:
            continue
        failures = int(row.get("failure_count") or 1)
        last_failed = _parse_iso(str(row.get("last_failed_at") or row.get("completed_at") or ""))

        if failures >= max_retries:
            parked.append(
                _park_task(
                    task_id,
                    reason=f"agent failed {failures} time(s) — manual review",
                    tasks_path=tasks_path,
                    from_status="failed",
                    apply=apply,
                )
            )
            continue

        if last_failed is not None and (now - last_failed) < cooldown:
            continue

        if apply:
            mark_task_status(
                task_id,
                "open",
                path=tasks_path,
                recovered_at=now.isoformat(),
                recovery_note=f"auto-retry {failures}/{max_retries} after agent failure",
            )
        reopened.append(task_id)

    return reopened, parked


def park_ci_blocked_pr_open_tasks(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    open_prs: list[dict[str, Any]] | None = None,
    repo: str | None = None,
    token: str | None = None,
    ci_red_hours: int = DEFAULT_CI_RED_PARK_HOURS,
    apply: bool = True,
    now: datetime | None = None,
) -> list[RecoveryAction]:
    """Park pr_open tasks whose draft PR has only failing checks for long enough."""
    now = now or datetime.now(UTC)
    threshold = timedelta(hours=max(1, int(ci_red_hours)))
    pr_by_branch = _open_pr_by_branch(open_prs or [])
    parked: list[RecoveryAction] = []
    data = load_engineering_tasks(tasks_path)

    for row in data.get("tasks") or []:
        if str(row.get("status") or "") != IN_FLIGHT_STATUS:
            continue
        task_id = str(row.get("id") or "")
        branch = str(row.get("branch_name") or "").strip()
        if not task_id or not branch:
            continue
        pr = pr_by_branch.get(branch)
        if pr is None:
            continue
        pr_number = pr.get("number")
        if pr_number is None:
            continue

        check_state = _pr_check_state(int(pr_number), repo=repo, token=token)
        if not check_state.get("available") or not check_state.get("all_failed"):
            continue

        latest = check_state.get("latest_check_at")
        if isinstance(latest, datetime) and (now - latest) < threshold:
            continue

        parked.append(
            _park_task(
                task_id,
                reason=(
                    f"draft PR #{pr_number} checks still failing — "
                    "queue unblocked for manual review"
                ),
                tasks_path=tasks_path,
                from_status=IN_FLIGHT_STATUS,
                apply=apply,
            )
        )

    return parked


def recover_engineering_queue(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    open_prs: list[dict[str, Any]] | None = None,
    repo: str | None = None,
    token: str | None = None,
    apply: bool = True,
    max_agent_retries: int = DEFAULT_MAX_AGENT_RETRIES,
    retry_cooldown_hours: int = DEFAULT_RETRY_COOLDOWN_HOURS,
    ci_red_park_hours: int = DEFAULT_CI_RED_PARK_HOURS,
) -> RecoveryResult:
    """
    Run queue self-repair in order:
    1. Reconcile orphaned pr_open → open
    2. Retry cooled-down failed tasks (or park when retries exhausted)
    3. Park pr_open tasks blocked on long-running red CI
    """
    result = RecoveryResult()

    if apply:
        reconcile = reconcile_orphaned_pr_open_tasks(
            tasks_path=tasks_path,
            open_prs=open_prs,
        )
    else:
        reconcile = {"reset": []}
    result.reconciled = list(reconcile.get("reset") or [])

    reopened, parked_failed = retry_failed_tasks(
        tasks_path=tasks_path,
        max_retries=max_agent_retries,
        cooldown_hours=retry_cooldown_hours,
        apply=apply,
    )
    result.reopened = reopened
    result.parked.extend(parked_failed)

    result.parked.extend(
        park_ci_blocked_pr_open_tasks(
            tasks_path=tasks_path,
            open_prs=open_prs,
            repo=repo,
            token=token,
            ci_red_hours=ci_red_park_hours,
            apply=apply,
        )
    )

    return result


def summarize_parked_tasks(tasks_path: Path = COMMITTED_TASKS_PATH) -> list[dict[str, Any]]:
    rows = []
    for row in load_engineering_tasks(tasks_path).get("tasks") or []:
        if str(row.get("status") or "") != PARKED_STATUS:
            continue
        rows.append(
            {
                "id": row.get("id"),
                "title": row.get("title"),
                "parked_at": row.get("parked_at"),
                "parked_reason": row.get("parked_reason"),
                "pr_url": row.get("pr_url"),
                "branch_name": row.get("branch_name"),
            }
        )
    return rows
