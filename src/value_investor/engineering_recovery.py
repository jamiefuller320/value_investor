"""Self-repair and parking policies for the supervised engineering queue."""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.engineering_queue import (
    DISPATCHABLE_STATUS,
    IN_FLIGHT_STATUS,
    engineering_branch_for_task_id,
    reconcile_orphaned_pr_open_tasks,
)
from value_investor.engineering_tasks import (
    COMMITTED_TASKS_PATH,
    load_engineering_tasks,
    mark_task_merged_for_branch,
    mark_task_status,
)
from value_investor.workflow_pat import is_integration_token, resolve_workflow_dispatch_pat

logger = logging.getLogger(__name__)

PARKED_STATUS = "parked"
PARKED_POLICY_DUPLICATE = "duplicate"
PARKED_POLICY_NO_DIFF = "no_diff_cap"
PARKED_POLICY_CI_BLOCKED = "ci_blocked"
PARKED_POLICY_MANUAL = "manual"
INFORMATIONAL_PARKED_POLICIES = frozenset({PARKED_POLICY_DUPLICATE, PARKED_POLICY_NO_DIFF})
DUPLICATE_PARKED_REASON_RE = re.compile(r"duplicate|dup of|superseded", re.IGNORECASE)
NO_DIFF_PARKED_REASON_RE = re.compile(r"no code changes", re.IGNORECASE)
DEFAULT_MAX_AGENT_RETRIES = 2
DEFAULT_MAX_NO_DIFF_RUNS = 2
DEFAULT_RETRY_COOLDOWN_HOURS = 24
DEFAULT_CI_RED_PARK_HOURS = 48
GITHUB_API_VERSION = "2022-11-28"


def _github_token() -> str | None:
    pat = resolve_workflow_dispatch_pat()
    if pat:
        return pat
    for key in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(key)
        if value and not is_integration_token(value):
            return value
        if value and key == "GITHUB_TOKEN":
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
    merged: list[str] = field(default_factory=list)
    reconciled: list[str] = field(default_factory=list)
    reopened: list[str] = field(default_factory=list)
    parked: list[RecoveryAction] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "merged": self.merged,
            "reconciled": self.reconciled,
            "reopened": self.reopened,
            "parked": [row.to_dict() for row in self.parked],
            "skipped": self.skipped,
            "action_count": len(self.merged)
            + len(self.reconciled)
            + len(self.reopened)
            + len(self.parked),
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

    failures = [
        row
        for row in relevant
        if str(row.get("conclusion") or "").lower() in {"failure", "cancelled", "timed_out"}
    ]
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
            parked_policy=(
                PARKED_POLICY_CI_BLOCKED
                if ("checks still failing" in reason.lower() or "ci blocked" in reason.lower())
                else PARKED_POLICY_MANUAL
            ),
        )
    return action


def record_agent_no_diff_run(
    task_id: str,
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    max_runs: int = DEFAULT_MAX_NO_DIFF_RUNS,
    apply: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Increment no-diff counter; park when the cap is reached."""
    now = now or datetime.now(UTC)
    data = load_engineering_tasks(tasks_path)
    row = next(
        (item for item in data.get("tasks") or [] if str(item.get("id") or "") == task_id),
        None,
    )
    if row is None:
        return {"recorded": False, "skipped": True, "reason": f"task {task_id} not found"}
    if str(row.get("status") or "open") != "open":
        return {
            "recorded": False,
            "skipped": True,
            "reason": f"task {task_id} is {row.get('status')} (expected open)",
        }

    count = int(row.get("no_diff_count") or 0) + 1
    stamp = now.isoformat()
    if count >= max(1, int(max_runs)):
        reason = f"agent produced no code changes {count} time(s) (cap {max_runs}) — manual review"
        if apply:
            mark_task_status(
                task_id,
                PARKED_STATUS,
                path=tasks_path,
                committed_path=tasks_path,
                parked_reason=reason,
                parked_at=stamp,
                no_diff_count=count,
                last_no_diff_at=stamp,
                parked_policy=PARKED_POLICY_NO_DIFF,
            )
        return {
            "recorded": True,
            "task_id": task_id,
            "no_diff_count": count,
            "parked": True,
            "parked_reason": reason,
        }

    if apply:
        mark_task_status(
            task_id,
            "open",
            path=tasks_path,
            committed_path=tasks_path,
            no_diff_count=count,
            last_no_diff_at=stamp,
        )
    return {
        "recorded": True,
        "task_id": task_id,
        "no_diff_count": count,
        "parked": False,
        "remaining_before_park": max(1, int(max_runs)) - count,
    }


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


def find_merged_pull_for_branch(
    branch: str,
    *,
    repo: str | None = None,
    token: str | None = None,
) -> dict[str, Any] | None:
    """Return the most recently merged closed PR for a head branch, if any."""
    branch = str(branch or "").strip()
    repo = repo or _github_repo()
    if not branch or not repo:
        return None
    token = token or _github_token()
    if not token:
        return None
    owner, name = repo.split("/", 1)
    head = f"{owner}:{branch}"
    try:
        pulls = _github_api_get(
            f"/repos/{owner}/{name}/pulls?state=closed&head={head}&per_page=10",
            token=token,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        logger.warning("Merged PR lookup failed for %s: %s", branch, exc)
        return None
    if not isinstance(pulls, list):
        return None
    merged = [row for row in pulls if row.get("merged_at")]
    if not merged:
        return None
    merged.sort(key=lambda row: str(row.get("merged_at") or ""), reverse=True)
    return dict(merged[0])


def reconcile_merged_pr_open_tasks(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    repo: str | None = None,
    token: str | None = None,
    apply: bool = True,
) -> list[str]:
    """
    Mark pr_open/open tasks merged when their engineering PR merged on GitHub.

    Runs before orphan reconcile so merged tasks are not reset to open.
    """
    merged_ids: list[str] = []
    data = load_engineering_tasks(tasks_path)
    for row in data.get("tasks") or []:
        if row.get("merged_at"):
            continue
        status = str(row.get("status") or "")
        if status not in {IN_FLIGHT_STATUS, DISPATCHABLE_STATUS}:
            continue
        task_id = str(row.get("id") or "")
        branch = str(row.get("branch_name") or "").strip()
        if not branch:
            branch = engineering_branch_for_task_id(task_id) or ""
        if not branch:
            continue
        pr = find_merged_pull_for_branch(branch, repo=repo, token=token)
        if not pr or not pr.get("merged_at"):
            continue
        if apply:
            mark_task_merged_for_branch(
                branch,
                path=tasks_path,
                committed_path=tasks_path,
                pr_url=str(pr.get("html_url") or ""),
                pr_number=int(pr["number"]) if pr.get("number") is not None else None,
            )
        merged_ids.append(task_id)
    return merged_ids


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

    result.merged = reconcile_merged_pr_open_tasks(
        tasks_path=tasks_path,
        repo=repo,
        token=token,
        apply=apply,
    )

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


def _merged_task_ids(tasks: list[dict[str, Any]]) -> set[str]:
    return {
        str(row.get("id") or "")
        for row in tasks
        if str(row.get("status") or "") == "merged" and str(row.get("id") or "")
    }


def classify_parked_task(
    row: dict[str, Any],
    *,
    merged_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Grade a parked task for ops attention and housekeeping actions."""
    reason = str(row.get("parked_reason") or "")
    policy = str(row.get("parked_policy") or "").strip().lower()
    duplicate_of = str(row.get("duplicate_of") or "").strip()

    if not policy:
        if duplicate_of or DUPLICATE_PARKED_REASON_RE.search(reason):
            policy = PARKED_POLICY_DUPLICATE
        elif NO_DIFF_PARKED_REASON_RE.search(reason):
            policy = PARKED_POLICY_NO_DIFF
        elif "checks still failing" in reason.lower() or "ci blocked" in reason.lower():
            policy = PARKED_POLICY_CI_BLOCKED
        else:
            policy = PARKED_POLICY_MANUAL

    needs_attention = policy not in INFORMATIONAL_PARKED_POLICIES
    if policy == PARKED_POLICY_DUPLICATE and duplicate_of and merged_ids is not None:
        needs_attention = duplicate_of not in merged_ids

    return {
        "id": row.get("id"),
        "parked_policy": policy,
        "duplicate_of": duplicate_of or None,
        "needs_attention": needs_attention,
        "parked_reason": reason or None,
    }


def summarize_parked_tasks(tasks_path: Path = COMMITTED_TASKS_PATH) -> list[dict[str, Any]]:
    rows = []
    data = load_engineering_tasks(tasks_path)
    tasks = list(data.get("tasks") or [])
    merged_ids = _merged_task_ids(tasks)
    for row in tasks:
        if str(row.get("status") or "") != PARKED_STATUS:
            continue
        grade = classify_parked_task(row, merged_ids=merged_ids)
        rows.append(
            {
                "id": row.get("id"),
                "title": row.get("title"),
                "parked_at": row.get("parked_at"),
                "parked_reason": row.get("parked_reason"),
                "parked_policy": grade["parked_policy"],
                "duplicate_of": grade["duplicate_of"],
                "needs_attention": grade["needs_attention"],
                "pr_url": row.get("pr_url"),
                "branch_name": row.get("branch_name"),
            }
        )
    return rows


def summarize_parked_tasks_needing_attention(
    tasks_path: Path = COMMITTED_TASKS_PATH,
) -> list[dict[str, Any]]:
    return [row for row in summarize_parked_tasks(tasks_path) if row.get("needs_attention")]


@dataclass
class ParkedHousekeepAction:
    task_id: str
    action: str
    reason: str
    duplicate_of: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "action": self.action,
            "reason": self.reason,
            "duplicate_of": self.duplicate_of,
        }


@dataclass
class ParkedHousekeepResult:
    cancelled: list[ParkedHousekeepAction] = field(default_factory=list)
    annotated: list[ParkedHousekeepAction] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cancelled": [row.to_dict() for row in self.cancelled],
            "annotated": [row.to_dict() for row in self.annotated],
            "skipped": self.skipped,
            "action_count": len(self.cancelled) + len(self.annotated),
        }


def housekeep_parked_tasks(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    apply: bool = True,
    now: datetime | None = None,
) -> ParkedHousekeepResult:
    """
      Grade parked tasks and take safe automatic actions.

      - Cancel duplicates of already-merged tasks (``duplicate_of`` + merged target).
      - Backfill ``parked_policy`` on informational parks (no-diff cap, duplicate).
    Does not reopen or merge tasks — run from daily ops monitor recovery.
    """
    now = now or datetime.now(UTC)
    result = ParkedHousekeepResult()
    data = load_engineering_tasks(tasks_path)
    tasks = list(data.get("tasks") or [])
    merged_ids = _merged_task_ids(tasks)

    for row in tasks:
        if str(row.get("status") or "") != PARKED_STATUS:
            continue
        task_id = str(row.get("id") or "")
        if not task_id:
            continue

        grade = classify_parked_task(row, merged_ids=merged_ids)
        policy = str(grade["parked_policy"])
        duplicate_of = str(grade.get("duplicate_of") or "").strip()
        reason = str(row.get("parked_reason") or "")

        if policy == PARKED_POLICY_DUPLICATE and duplicate_of in merged_ids:
            cancel_reason = reason or f"duplicate of merged {duplicate_of}"
            if apply:
                mark_task_status(
                    task_id,
                    "cancelled",
                    path=tasks_path,
                    committed_path=tasks_path,
                    parked_policy=policy,
                    duplicate_of=duplicate_of,
                    cancelled_at=now.isoformat(),
                    cancelled_reason=cancel_reason,
                )
            result.cancelled.append(
                ParkedHousekeepAction(
                    task_id=task_id,
                    action="cancel_duplicate",
                    reason=cancel_reason,
                    duplicate_of=duplicate_of,
                )
            )
            continue

        needs_policy = not str(row.get("parked_policy") or "").strip()
        if needs_policy and policy in INFORMATIONAL_PARKED_POLICIES:
            if apply:
                mark_task_status(
                    task_id,
                    PARKED_STATUS,
                    path=tasks_path,
                    committed_path=tasks_path,
                    parked_policy=policy,
                )
            result.annotated.append(
                ParkedHousekeepAction(
                    task_id=task_id,
                    action="annotate_policy",
                    reason=f"parked_policy={policy}",
                )
            )

    return result
