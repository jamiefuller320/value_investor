"""Project traffic controller — pause / unstick PR queue + daily grounded digest.

This is the bounded first slice of a project-management agent:

* Monitor open ``cursor/*`` PRs for CI failure and merge conflicts.
* Pause new engineering-agent dispatch while the queue is stuck.
* Request scoped fix follow-ups (CI autofix / conflict-resolve agent).
* Auto-resume when stuck PRs clear.
* Emit an end-of-day digest that cites committed artifacts (progress report,
  north-star stages, queue health) rather than free-form claims.

Merge authority is scoped auto-merge (ci_fix / ingest_narrow / scoring_narrow / parked_hunter) with independent deterministic verify; traffic itself still does not merge.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json

logger = logging.getLogger(__name__)

COMMITTED_TASKS_PATH = Path("docs/data/engineering_tasks.json")
DEFAULT_DIGEST_PATH = Path("docs/data/project_traffic_digest.json")
DEFAULT_DIGEST_MARKDOWN_PATH = Path("docs/data/project_traffic_digest.md")
DEFAULT_PROGRESS_REPORT_PATH = Path("docs/data/progress_report.json")
DEFAULT_PROJECT_PROGRESS_PATH = Path("docs/data/project_progress.json")
DEFAULT_QUEUE_HEALTH_PATH = Path("docs/data/queue_health.json")
DEFAULT_OPS_STATUS_PATH = Path("docs/data/ops_status.json")

TRAFFIC_STATE_KEY = "traffic_control"
SCHEMA_VERSION = 1

PAUSE_REASON_CI_FAIL = "ci_failing"
PAUSE_REASON_CONFLICT = "merge_conflict"
PAUSE_REASON_STUCK_THRESHOLD = "stuck_pr_threshold"

ACTION_COMMENT_CI = "request_ci_fix"
ACTION_COMMENT_CONFLICT = "request_conflict_resolve"
ACTION_DISPATCH_CI_AUTOFIX = "dispatch_ci_autofix_hint"
ACTION_DISPATCH_CONFLICT = "dispatch_conflict_resolve"
ACTION_PAUSE = "pause_dispatch"
ACTION_RESUME = "resume_dispatch"
ACTION_QUEUE_SYNC = "remediate_queue_merge_sync"

QUEUE_MERGE_SYNC_FINDING_TITLE = "Engineering queue merge sync lag"

ACTION_OPS_EMAIL_HANDOFF = "ops_email_handoff"
DEFAULT_OPS_EMAIL_HANDOFF_PATH = Path("docs/data/project_traffic_ops_email_handoff.json")

RECTIFICATION_QUEUE_SYNC = "remediate_queue_merge_sync"
RECTIFICATION_UNSTICK_PRS = "request_unstick_stuck_prs"
RECTIFICATION_DRAFT_ENG_TASK = "draft_ops_engineering_task"
RECTIFICATION_RERUN_WORKFLOW = "rerun_or_dispatch_workflow"
RECTIFICATION_HUMAN_TRIAGE = "human_triage"

DEFAULT_STUCK_PR_THRESHOLD = 2
DEFAULT_MIN_FAIL_AGE_MINUTES = 20
DEFAULT_RESUME_IDLE_MINUTES = 15
DEFAULT_MAX_FIX_REQUESTS_PER_PR = 2
DEFAULT_COMMENT_COOLDOWN_HOURS = 6

CURSOR_BRANCH_RE = re.compile(r"^cursor/[A-Za-z0-9][A-Za-z0-9._/-]*$")
ENG_BRANCH_RE = re.compile(r"^cursor/eng-\d{8}-\d{2}-1de3$")


@dataclass
class StuckPr:
    number: int
    branch: str
    title: str
    url: str
    draft: bool
    reasons: list[str] = field(default_factory=list)
    task_id: str | None = None
    head_sha: str | None = None
    mergeable_state: str | None = None
    checks_failed: bool = False
    conflict: bool = False
    updated_at: str | None = None
    failed_check_names: list[str] = field(default_factory=list)
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "branch": self.branch,
            "title": self.title,
            "url": self.url,
            "draft": self.draft,
            "reasons": list(self.reasons),
            "task_id": self.task_id,
            "head_sha": self.head_sha,
            "mergeable_state": self.mergeable_state,
            "checks_failed": self.checks_failed,
            "conflict": self.conflict,
            "updated_at": self.updated_at,
            "failed_check_names": list(self.failed_check_names),
            "failure_reason": self.failure_reason,
        }


@dataclass
class TrafficAction:
    kind: str
    detail: str
    pr_number: int | None = None
    branch: str | None = None
    applied: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "detail": self.detail,
            "pr_number": self.pr_number,
            "branch": self.branch,
            "applied": self.applied,
        }


@dataclass
class TrafficControllerReport:
    run_at: str
    pause_active: bool
    pause_reasons: list[str]
    stuck_prs: list[StuckPr]
    actions: list[TrafficAction]
    should_dispatch_conflict_agent: list[dict[str, Any]]
    digest: dict[str, Any] | None = None
    state: dict[str, Any] = field(default_factory=dict)
    queue_sync_lag_ids: list[str] = field(default_factory=list)
    queue_sync_fixed_ids: list[str] = field(default_factory=list)
    queue_sync_remaining_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "run_at": self.run_at,
            "pause_active": self.pause_active,
            "pause_reasons": list(self.pause_reasons),
            "stuck_pr_count": len(self.stuck_prs),
            "stuck_prs": [row.to_dict() for row in self.stuck_prs],
            "actions": [row.to_dict() for row in self.actions],
            "should_dispatch_conflict_agent": list(self.should_dispatch_conflict_agent),
            "digest": self.digest,
            "state": self.state,
            "queue_sync_lag_ids": list(self.queue_sync_lag_ids),
            "queue_sync_fixed_ids": list(self.queue_sync_fixed_ids),
            "queue_sync_remaining_ids": list(self.queue_sync_remaining_ids),
        }


def remediate_queue_merge_sync(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    open_prs: list[dict[str, Any]] | None = None,
    repo: str | None = None,
    token: str | None = None,
    apply: bool = True,
) -> tuple[list[str], list[str], list[str], list[TrafficAction]]:
    """PM-owned repair for queue rows still open/pr_open after GitHub merge.

    Returns ``(lag_ids, fixed_ids, remaining_ids, actions)``. Ops monitor should
    email only when ``remaining_ids`` is non-empty after this runs.
    """
    from value_investor import engineering_recovery as er

    lag_rows = er.list_merge_sync_lag_tasks(
        tasks_path=tasks_path,
        repo=repo,
        token=token,
    )
    lag_ids = [str(row.get("task_id") or "") for row in lag_rows if row.get("task_id")]
    if not lag_ids:
        return [], [], [], []

    actions: list[TrafficAction] = [
        TrafficAction(
            kind=ACTION_QUEUE_SYNC,
            detail=(
                f"detected merge sync lag for {len(lag_ids)} task(s): " + ", ".join(lag_ids[:8])
            ),
            applied=False,
        )
    ]
    if not apply:
        return lag_ids, [], list(lag_ids), actions

    recovery = er.recover_engineering_queue(
        tasks_path=tasks_path,
        open_prs=open_prs,
        repo=repo,
        token=token,
        apply=True,
    )
    fixed_from_recover = [str(task_id) for task_id in (recovery.merged or []) if task_id]
    remaining_rows = er.list_merge_sync_lag_tasks(
        tasks_path=tasks_path,
        repo=repo,
        token=token,
    )
    remaining_ids = [str(row.get("task_id") or "") for row in remaining_rows if row.get("task_id")]
    fixed_ids = [task_id for task_id in lag_ids if task_id not in set(remaining_ids)]
    if not fixed_ids and fixed_from_recover:
        fixed_ids = [task_id for task_id in fixed_from_recover if task_id in set(lag_ids)]

    detail = (
        f"PM remediated queue merge sync: fixed={fixed_ids or ['none']}; "
        f"remaining={remaining_ids or ['none']}"
    )
    actions.append(
        TrafficAction(
            kind=ACTION_QUEUE_SYNC,
            detail=detail,
            applied=bool(fixed_ids) and not remaining_ids,
        )
    )
    return lag_ids, fixed_ids, remaining_ids, actions


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _safe_read(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _traffic_policy() -> dict[str, Any]:
    from value_investor.agent_model_policy import load_policy

    engineering = load_policy().get("engineering") or {}
    block = dict(engineering.get("traffic_control") or {})
    try:
        stuck_threshold = max(1, int(block.get("stuck_pr_threshold") or DEFAULT_STUCK_PR_THRESHOLD))
    except (TypeError, ValueError):
        stuck_threshold = DEFAULT_STUCK_PR_THRESHOLD
    try:
        min_fail_age = max(
            0, int(block.get("min_fail_age_minutes") or DEFAULT_MIN_FAIL_AGE_MINUTES)
        )
    except (TypeError, ValueError):
        min_fail_age = DEFAULT_MIN_FAIL_AGE_MINUTES
    try:
        resume_idle = max(1, int(block.get("resume_idle_minutes") or DEFAULT_RESUME_IDLE_MINUTES))
    except (TypeError, ValueError):
        resume_idle = DEFAULT_RESUME_IDLE_MINUTES
    try:
        max_fix_requests = max(
            1, int(block.get("max_fix_requests_per_pr") or DEFAULT_MAX_FIX_REQUESTS_PER_PR)
        )
    except (TypeError, ValueError):
        max_fix_requests = DEFAULT_MAX_FIX_REQUESTS_PER_PR
    try:
        comment_cooldown = max(
            1, int(block.get("comment_cooldown_hours") or DEFAULT_COMMENT_COOLDOWN_HOURS)
        )
    except (TypeError, ValueError):
        comment_cooldown = DEFAULT_COMMENT_COOLDOWN_HOURS
    enabled = block.get("enabled")
    if enabled is None:
        enabled = True
    return {
        "enabled": bool(enabled),
        "stuck_pr_threshold": stuck_threshold,
        "min_fail_age_minutes": min_fail_age,
        "resume_idle_minutes": resume_idle,
        "max_fix_requests_per_pr": max_fix_requests,
        "comment_cooldown_hours": comment_cooldown,
        "monitor_cursor_prs": bool(block.get("monitor_cursor_prs", True)),
        "pause_on_stuck": bool(block.get("pause_on_stuck", True)),
        "request_ci_fix_comments": bool(block.get("request_ci_fix_comments", True)),
        "request_conflict_resolve": bool(block.get("request_conflict_resolve", True)),
        "digest_enabled": bool(block.get("digest_enabled", True)),
    }


def get_traffic_control_state(*, tasks_path: Path = COMMITTED_TASKS_PATH) -> dict[str, Any]:
    data = _safe_read(Path(tasks_path)) or {}
    return dict(data.get(TRAFFIC_STATE_KEY) or {})


def is_traffic_pause_active(*, tasks_path: Path = COMMITTED_TASKS_PATH) -> bool:
    return bool(get_traffic_control_state(tasks_path=tasks_path).get("pause_active"))


def _save_traffic_control_state(
    state: dict[str, Any],
    *,
    tasks_path: Path,
    apply: bool,
) -> None:
    if not apply:
        return
    from value_investor.engineering_tasks import load_engineering_tasks

    tasks_path = Path(tasks_path)
    data = load_engineering_tasks(tasks_path)
    data[TRAFFIC_STATE_KEY] = state
    tasks_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(tasks_path, data, compact=False)


def preserve_queue_meta(existing: dict[str, Any] | None, payload: dict[str, Any]) -> dict[str, Any]:
    """Keep traffic/queue-clearing meta when compilers rebuild the task list."""
    out = dict(payload)
    existing = existing or {}
    for key in (TRAFFIC_STATE_KEY, "queue_clearing"):
        if key in existing and key not in out:
            out[key] = existing[key]
    return out


def _pr_branch(row: dict[str, Any]) -> str:
    return str(
        row.get("headRefName")
        or row.get("head_branch")
        or ((row.get("head") or {}).get("ref") if isinstance(row.get("head"), dict) else "")
        or ""
    ).strip()


def _pr_number(row: dict[str, Any]) -> int | None:
    raw = row.get("number")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _is_monitored_branch(branch: str, *, monitor_cursor: bool) -> bool:
    if not branch:
        return False
    if ENG_BRANCH_RE.match(branch):
        return True
    if monitor_cursor and CURSOR_BRANCH_RE.match(branch):
        return True
    return False


def _task_id_for_branch(branch: str, *, tasks_path: Path) -> str | None:
    from value_investor.engineering_queue import task_id_from_branch
    from value_investor.engineering_tasks import load_engineering_tasks

    task_id = task_id_from_branch(branch)
    if task_id:
        return task_id
    data = load_engineering_tasks(tasks_path)
    for row in data.get("tasks") or []:
        if str(row.get("branch_name") or "").strip() == branch:
            return str(row.get("id") or "") or None
    return None


def _enrich_pr_merge_state(
    row: dict[str, Any],
    *,
    repo: str | None,
    token: str | None,
) -> dict[str, Any]:
    """Ensure mergeable / mergeable_state fields exist (GitHub list omits them)."""
    if row.get("mergeable") is not None or row.get("mergeable_state"):
        return row
    number = _pr_number(row)
    if number is None or not repo or not token:
        return row
    from value_investor.ops_monitor import github_api_get

    owner, name = repo.split("/", 1)
    try:
        detail = github_api_get(f"/repos/{owner}/{name}/pulls/{number}", token=token)
    except (OSError, ValueError, RuntimeError) as exc:
        logger.warning("PR detail lookup failed for #%s: %s", number, exc)
        return row
    if not isinstance(detail, dict):
        return row
    enriched = dict(row)
    enriched["mergeable"] = detail.get("mergeable")
    enriched["mergeable_state"] = detail.get("mergeable_state")
    enriched["draft"] = detail.get("draft", row.get("draft") or row.get("isDraft"))
    enriched["html_url"] = detail.get("html_url") or row.get("html_url") or row.get("url")
    head = detail.get("head") or {}
    if isinstance(head, dict):
        enriched["head"] = head
        if head.get("sha"):
            enriched["head_sha"] = head.get("sha")
    return enriched


def _checks_failed_for_pr(
    pr_number: int,
    *,
    repo: str | None,
    token: str | None,
) -> dict[str, Any]:
    from value_investor.engineering_recovery import _pr_check_state

    return _pr_check_state(pr_number, repo=repo, token=token)


def classify_stuck_prs(
    open_prs: list[dict[str, Any]] | None,
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    repo: str | None = None,
    token: str | None = None,
    now: datetime | None = None,
    policy: dict[str, Any] | None = None,
) -> list[StuckPr]:
    """Return monitored PRs that are CI-red and/or merge-conflicting."""
    now = now or _utcnow()
    policy = policy or _traffic_policy()
    min_age = timedelta(minutes=int(policy["min_fail_age_minutes"]))
    stuck: list[StuckPr] = []

    for raw in open_prs or []:
        branch = _pr_branch(raw)
        if not _is_monitored_branch(branch, monitor_cursor=bool(policy["monitor_cursor_prs"])):
            continue
        number = _pr_number(raw)
        if number is None:
            continue
        row = _enrich_pr_merge_state(raw, repo=repo, token=token)
        mergeable_state = str(row.get("mergeable_state") or "").lower()
        mergeable = row.get("mergeable")
        # gh pr list may return MERGEABLE / CONFLICTING / UNKNOWN strings.
        if isinstance(mergeable, str):
            token_m = mergeable.strip().upper()
            if token_m == "CONFLICTING":
                mergeable = False
                mergeable_state = mergeable_state or "dirty"
            elif token_m == "MERGEABLE":
                mergeable = True
            elif token_m == "UNKNOWN":
                mergeable = None
        conflict = mergeable is False or mergeable_state in {"dirty"}
        # "unstable" alone is not a conflict signal — rely on check-runs for CI.

        check_state = _checks_failed_for_pr(number, repo=repo, token=token)
        checks_failed = bool(check_state.get("available") and check_state.get("all_failed"))
        if checks_failed:
            latest = check_state.get("latest_check_at")
            if isinstance(latest, datetime) and (now - latest) < min_age:
                checks_failed = False

        if not checks_failed and not conflict:
            continue

        reasons: list[str] = []
        if checks_failed:
            reasons.append(PAUSE_REASON_CI_FAIL)
        if conflict:
            reasons.append(PAUSE_REASON_CONFLICT)

        head = row.get("head") if isinstance(row.get("head"), dict) else {}
        head_sha = str(
            row.get("head_sha") or (head.get("sha") if isinstance(head, dict) else "") or ""
        )
        failed_check_names = [
            str(name).strip()
            for name in list(check_state.get("failed_check_names") or [])
            if str(name).strip()
        ]
        from value_investor.pr_fix_occasions import (
            KIND_BOTH,
            KIND_CI,
            KIND_MERGE,
            normalize_failure_reason,
        )

        if checks_failed and conflict:
            occasion_kind = KIND_BOTH
        elif conflict:
            occasion_kind = KIND_MERGE
        else:
            occasion_kind = KIND_CI
        failure_reason = normalize_failure_reason(
            kind=occasion_kind,
            failed_check_names=failed_check_names,
            mergeable_state=mergeable_state or None,
        )
        stuck.append(
            StuckPr(
                number=number,
                branch=branch,
                title=str(row.get("title") or ""),
                url=str(row.get("html_url") or row.get("url") or ""),
                draft=bool(row.get("draft") or row.get("isDraft")),
                reasons=reasons,
                task_id=_task_id_for_branch(branch, tasks_path=tasks_path),
                head_sha=head_sha or None,
                mergeable_state=mergeable_state or None,
                checks_failed=checks_failed,
                conflict=conflict,
                updated_at=str(row.get("updated_at") or row.get("updatedAt") or "") or None,
                failed_check_names=failed_check_names,
                failure_reason=failure_reason,
            )
        )
    return stuck


def _fix_request_history(state: dict[str, Any]) -> dict[str, Any]:
    history = state.get("fix_requests")
    return dict(history) if isinstance(history, dict) else {}


def _record_fix_request(
    state: dict[str, Any],
    *,
    pr_number: int,
    kind: str,
    head_sha: str | None,
    now: datetime,
) -> None:
    history = _fix_request_history(state)
    key = str(pr_number)
    entry = dict(history.get(key) or {})
    entry["count"] = int(entry.get("count") or 0) + 1
    entry["last_kind"] = kind
    entry["last_at"] = now.isoformat()
    entry["last_head_sha"] = head_sha
    history[key] = entry
    state["fix_requests"] = history


def _occasion_kind_for_action(action_kind: str, pr: StuckPr) -> str:
    from value_investor.pr_fix_occasions import KIND_BOTH, KIND_CI, KIND_MERGE

    if action_kind == ACTION_COMMENT_CI:
        return KIND_CI
    if action_kind == ACTION_COMMENT_CONFLICT:
        return KIND_MERGE
    if pr.checks_failed and pr.conflict:
        return KIND_BOTH
    if pr.conflict:
        return KIND_MERGE
    return KIND_CI


def _append_pr_fix_occasion(
    pr: StuckPr,
    *,
    action_kind: str,
    apply: bool,
    now: datetime,
    log_path: Path | None = None,
) -> dict[str, Any] | None:
    """Persist a durable fix-request occasion with failure reason."""
    from value_investor.pr_fix_occasions import (
        SOURCE_TRAFFIC,
        record_pr_fix_occasion,
    )

    occasion_kind = _occasion_kind_for_action(action_kind, pr)
    try:
        result = record_pr_fix_occasion(
            source=SOURCE_TRAFFIC,
            kind=occasion_kind,
            failure_reason=pr.failure_reason,
            pr_number=pr.number,
            branch=pr.branch,
            title=pr.title,
            url=pr.url,
            task_id=pr.task_id,
            head_sha=pr.head_sha,
            mergeable_state=pr.mergeable_state,
            failed_check_names=list(pr.failed_check_names),
            notes=f"traffic action={action_kind}",
            details={"reasons": list(pr.reasons), "action_kind": action_kind},
            path=log_path,
            apply=apply,
            now=now,
        )
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("PR fix occasion log failed for #%s: %s", pr.number, exc)
        return None
    return result.get("entry") if isinstance(result, dict) else None


def _can_request_fix(
    state: dict[str, Any],
    *,
    pr_number: int,
    head_sha: str | None,
    now: datetime,
    policy: dict[str, Any],
) -> tuple[bool, str]:
    history = _fix_request_history(state)
    entry = dict(history.get(str(pr_number)) or {})
    count = int(entry.get("count") or 0)
    if count >= int(policy["max_fix_requests_per_pr"]):
        last_sha = entry.get("last_head_sha")
        if head_sha and last_sha and head_sha != last_sha:
            # New commits reset the per-SHA attempt budget partially.
            pass
        else:
            return False, "max_fix_requests_reached"
    last_at = _parse_iso(str(entry.get("last_at") or ""))
    if last_at and (now - last_at) < timedelta(hours=int(policy["comment_cooldown_hours"])):
        if head_sha and entry.get("last_head_sha") == head_sha:
            return False, "comment_cooldown"
    return True, "ok"


def format_ci_fix_comment(pr: StuckPr) -> str:
    task_bit = f" (task `{pr.task_id}`)" if pr.task_id else ""
    reason = pr.failure_reason or "ci_failing"
    check_bit = ""
    if pr.failed_check_names:
        check_bit = " Failed checks: " + ", ".join(f"`{n}`" for n in pr.failed_check_names[:8]) + "."
    return "\n".join(
        [
            "## Project traffic controller — CI failure",
            "",
            f"PR #{pr.number}{task_bit} on `{pr.branch}` has **failing checks** "
            f"(reason: `{reason}`).{check_bit}",
            "",
            "Please push a scoped fix (or wait for `ci-pr-autofix` / hunter-fix when eligible).",
            "New engineering-agent dispatch is **paused** while monitored PRs remain stuck,",
            "so conflicts do not compound on top of red CI.",
            "",
            "_Automated note from `ftse-project-traffic`. Merge authority remains human/scoped auto-merge only._",
        ]
    )


def format_conflict_resolve_comment(pr: StuckPr) -> str:
    task_bit = f" (task `{pr.task_id}`)" if pr.task_id else ""
    reason = pr.failure_reason or "merge_conflict"
    return "\n".join(
        [
            "## Project traffic controller — merge conflict",
            "",
            f"PR #{pr.number}{task_bit} on `{pr.branch}` is **not mergeable** "
            f"(state: `{pr.mergeable_state or 'dirty'}`; reason: `{reason}`).",
            "",
            "Please rebase/merge `main` and resolve conflicts on this branch only.",
            "A conflict-resolve agent may be dispatched for engineering branches.",
            "New engineering-agent dispatch stays **paused** until the stuck queue clears.",
            "",
            "_Automated note from `ftse-project-traffic`. Does not merge the PR._",
        ]
    )


def post_pr_comment(*, pr_number: int, body: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["gh", "pr", "comment", str(pr_number), "--body", body],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "gh pr comment failed").strip()
        return False, detail
    return True, "comment posted"


def evaluate_traffic_pause(
    *,
    stuck_prs: list[StuckPr],
    tasks_path: Path = COMMITTED_TASKS_PATH,
    apply: bool = True,
    now: datetime | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pause dispatch when enough stuck PRs accumulate; resume when clear + idle."""
    now = now or _utcnow()
    policy = policy or _traffic_policy()
    state = dict(get_traffic_control_state(tasks_path=tasks_path))
    changes: dict[str, Any] = {}
    pause_active = bool(state.get("pause_active"))
    threshold = int(policy["stuck_pr_threshold"])
    stuck_count = len(stuck_prs)
    reasons = sorted({reason for pr in stuck_prs for reason in pr.reasons})

    if not policy.get("pause_on_stuck", True):
        state["stuck_pr_count"] = stuck_count
        state["stuck_reasons"] = reasons
        state["evaluated_at"] = now.isoformat()
        _save_traffic_control_state(state, tasks_path=tasks_path, apply=apply)
        return state

    if not pause_active and stuck_count >= threshold:
        state["pause_active"] = True
        state["pause_started_at"] = now.isoformat()
        state["pause_reasons"] = reasons or [PAUSE_REASON_STUCK_THRESHOLD]
        state.pop("resumed_at", None)
        changes["activated"] = True
    elif pause_active:
        if stuck_count == 0:
            pause_started = _parse_iso(str(state.get("pause_started_at") or ""))
            last_action = _parse_iso(str(state.get("last_action_at") or ""))
            effective_last = last_action
            if pause_started and last_action and last_action < pause_started:
                effective_last = None
            # If never stamped an action, allow resume after pause age >= idle.
            if effective_last is None and pause_started is not None:
                effective_last = pause_started
            idle_ok = effective_last is not None and (now - effective_last) >= timedelta(
                minutes=int(policy["resume_idle_minutes"])
            )
            if idle_ok:
                state["pause_active"] = False
                state["resumed_at"] = now.isoformat()
                state.pop("pause_started_at", None)
                state.pop("pause_reasons", None)
                state.pop("last_action_at", None)
                changes["resumed"] = True
            else:
                state["resume_pending"] = True
                changes["resume_pending"] = True
        else:
            state["pause_reasons"] = reasons
            state.pop("resume_pending", None)

    state["stuck_pr_count"] = stuck_count
    state["stuck_reasons"] = reasons
    state["evaluated_at"] = now.isoformat()
    if changes:
        state["last_change"] = changes
    _save_traffic_control_state(state, tasks_path=tasks_path, apply=apply)
    return state


def request_unstick_actions(
    stuck_prs: list[StuckPr],
    *,
    state: dict[str, Any],
    apply: bool,
    now: datetime | None = None,
    policy: dict[str, Any] | None = None,
) -> tuple[list[TrafficAction], list[dict[str, Any]], dict[str, Any]]:
    """Comment / schedule conflict-resolve dispatches for stuck PRs."""
    now = now or _utcnow()
    policy = policy or _traffic_policy()
    actions: list[TrafficAction] = []
    conflict_dispatches: list[dict[str, Any]] = []
    state = dict(state)

    for pr in stuck_prs:
        can_request, reason = _can_request_fix(
            state,
            pr_number=pr.number,
            head_sha=pr.head_sha,
            now=now,
            policy=policy,
        )
        if not can_request:
            actions.append(
                TrafficAction(
                    kind="skip_fix_request",
                    detail=reason,
                    pr_number=pr.number,
                    branch=pr.branch,
                    applied=False,
                )
            )
            continue

        if pr.checks_failed and policy.get("request_ci_fix_comments", True):
            body = format_ci_fix_comment(pr)
            applied = False
            detail = "dry-run"
            if apply:
                ok, detail = post_pr_comment(pr_number=pr.number, body=body)
                applied = ok
            actions.append(
                TrafficAction(
                    kind=ACTION_COMMENT_CI,
                    detail=detail,
                    pr_number=pr.number,
                    branch=pr.branch,
                    applied=applied,
                )
            )
            if applied or not apply:
                _record_fix_request(
                    state,
                    pr_number=pr.number,
                    kind=ACTION_COMMENT_CI,
                    head_sha=pr.head_sha,
                    now=now,
                )
                _append_pr_fix_occasion(
                    pr,
                    action_kind=ACTION_COMMENT_CI,
                    apply=apply,
                    now=now,
                )
                state["last_action_at"] = now.isoformat()
            actions.append(
                TrafficAction(
                    kind=ACTION_DISPATCH_CI_AUTOFIX,
                    detail=(
                        "ci-pr-autofix / hunter-fix workflows fire on CI failure; "
                        "traffic controller does not re-dispatch them."
                    ),
                    pr_number=pr.number,
                    branch=pr.branch,
                    applied=False,
                )
            )

        if pr.conflict and policy.get("request_conflict_resolve", True):
            body = format_conflict_resolve_comment(pr)
            applied = False
            detail = "dry-run"
            if apply:
                ok, detail = post_pr_comment(pr_number=pr.number, body=body)
                applied = ok
            actions.append(
                TrafficAction(
                    kind=ACTION_COMMENT_CONFLICT,
                    detail=detail,
                    pr_number=pr.number,
                    branch=pr.branch,
                    applied=applied,
                )
            )
            if applied or not apply:
                _record_fix_request(
                    state,
                    pr_number=pr.number,
                    kind=ACTION_COMMENT_CONFLICT,
                    head_sha=pr.head_sha,
                    now=now,
                )
                _append_pr_fix_occasion(
                    pr,
                    action_kind=ACTION_COMMENT_CONFLICT,
                    apply=apply,
                    now=now,
                )
                state["last_action_at"] = now.isoformat()
            if ENG_BRANCH_RE.match(pr.branch):
                conflict_dispatches.append(
                    {
                        "pr_number": pr.number,
                        "branch": pr.branch,
                        "task_id": pr.task_id,
                        "head_sha": pr.head_sha,
                    }
                )
                actions.append(
                    TrafficAction(
                        kind=ACTION_DISPATCH_CONFLICT,
                        detail="eligible for engineering-conflict-resolve workflow",
                        pr_number=pr.number,
                        branch=pr.branch,
                        applied=False,
                    )
                )

    return actions, conflict_dispatches, state


def _claim_evidence_rows(
    *,
    progress_report: dict[str, Any] | None,
    project_progress: dict[str, Any] | None,
    queue_health: dict[str, Any] | None,
    ops_status: dict[str, Any] | None,
    stuck_prs: list[StuckPr],
    traffic_state: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    stages = list((project_progress or {}).get("stages") or [])
    for stage in stages:
        rows.append(
            {
                "claim": f"Stage {stage.get('id')} ({stage.get('name')}): {stage.get('status')}",
                "source": "docs/data/project_progress.json",
                "grounded": stage.get("status") in {"complete", "in_progress", "not_started"},
                "probe": "status must be one of complete|in_progress|not_started",
            }
        )

    if progress_report:
        generated = progress_report.get("generated_at") or progress_report.get("built_at")
        rows.append(
            {
                "claim": f"Progress report present (generated_at={generated})",
                "source": "docs/data/progress_report.json",
                "grounded": bool(generated),
                "probe": "progress_report.json must exist with a timestamp",
            }
        )
        so_what = progress_report.get("so_what") or progress_report.get("human_gate") or {}
        if isinstance(so_what, dict) and so_what:
            rows.append(
                {
                    "claim": f"So-what / human_gate keys present: {sorted(so_what.keys())[:8]}",
                    "source": "docs/data/progress_report.json",
                    "grounded": True,
                    "probe": "human_gate block is structural, not free text",
                }
            )

    if queue_health:
        rows.append(
            {
                "claim": (
                    f"Queue health overall={queue_health.get('overall')}; "
                    f"headline={queue_health.get('headline')}"
                ),
                "source": "docs/data/queue_health.json",
                "grounded": bool(queue_health.get("overall")),
                "probe": "queue_health.overall must be set by refresh_queue_health_ui",
            }
        )

    if ops_status:
        rows.append(
            {
                "claim": (
                    f"Ops monitor overall={ops_status.get('overall')} at {ops_status.get('run_at')}"
                ),
                "source": "docs/data/ops_status.json",
                "grounded": bool(ops_status.get("run_at")),
                "probe": "ops_status.run_at required for same-day claims",
            }
        )

    rows.append(
        {
            "claim": (
                f"Traffic pause_active={bool(traffic_state.get('pause_active'))}; "
                f"stuck_pr_count={len(stuck_prs)}"
            ),
            "source": "docs/data/engineering_tasks.json#traffic_control",
            "grounded": True,
            "probe": "pause state must match stuck PR classification on this run",
        }
    )
    for pr in stuck_prs[:10]:
        rows.append(
            {
                "claim": (
                    f"Stuck PR #{pr.number} `{pr.branch}` reasons={pr.reasons} "
                    f"mergeable_state={pr.mergeable_state}"
                ),
                "source": "github.pulls + check-runs",
                "grounded": True,
                "probe": "reasons must be ci_failing and/or merge_conflict",
            }
        )
    return rows


def planned_rectification_for_ops_finding(finding: Any) -> tuple[str, str]:
    """Deterministic PM rectification plan for an ops-monitor email finding.

    Returns ``(action_id, detail)``. Auto-execution is limited to PM v1 authority
    (queue merge-sync + stuck-PR unstick already owned by traffic); other actions
    are recorded for digest / human / eng-task follow-up.
    """
    if hasattr(finding, "title"):
        title = str(finding.title or "")
        category = str(finding.category or "")
        severity = str(finding.severity or "")
        summary = str(finding.summary or "")
    else:
        row = finding or {}
        title = str(row.get("title") or "")
        category = str(row.get("category") or "")
        severity = str(row.get("severity") or "")
        summary = str(row.get("summary") or "")

    if title == QUEUE_MERGE_SYNC_FINDING_TITLE or title.startswith("Orphaned pr_open"):
        return (
            RECTIFICATION_QUEUE_SYNC,
            "PM v1: recover/mark-merged engineering queue reconciliation",
        )
    if title == "Project traffic pause active" or "stuck PR" in summary.lower():
        return (
            RECTIFICATION_UNSTICK_PRS,
            "PM v1: traffic pause/unstick path (CI comment / conflict-resolve)",
        )
    if (
        category in {"workflows", "workflow"}
        or title.startswith("Workflow overdue:")
        or title.startswith("Recent workflow failure:")
        or title.startswith("Workflow failure")
    ):
        return (
            RECTIFICATION_RERUN_WORKFLOW,
            "Rerun/dispatch via existing ops auto-fix or workflow responders; else human",
        )
    if severity == "fail":
        return (
            RECTIFICATION_DRAFT_ENG_TASK,
            "Draft supervised ops engineering task (ops-monitor draft path)",
        )
    return (
        RECTIFICATION_HUMAN_TRIAGE,
        "Surface in PM digest for human / eng follow-up",
    )


def handoff_ops_monitor_email_to_pm(
    *,
    findings: list[Any],
    email_subject: str,
    email_text: str,
    email_html: str | None = None,
    drafted_task_ids: list[str] | None = None,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    open_prs: list[dict[str, Any]] | None = None,
    repo: str | None = None,
    token: str | None = None,
    apply: bool = True,
    handoff_path: Path = DEFAULT_OPS_EMAIL_HANDOFF_PATH,
    update_digest: bool = True,
) -> dict[str, Any]:
    """Hand email-worthy ops findings to PM with planned rectification.

    Keeps SMTP with the caller. Auto-remediates only queue merge-sync (existing
    PM v1 authority); other items stay open on the handoff artifact + digest.
    """
    drafted_task_ids = [str(x) for x in (drafted_task_ids or []) if x]
    items: list[dict[str, Any]] = []
    actions: list[TrafficAction] = []
    needs_queue_sync = False

    for finding in findings:
        if hasattr(finding, "to_dict"):
            payload = finding.to_dict()
        elif isinstance(finding, dict):
            payload = dict(finding)
        else:
            payload = {
                "severity": str(getattr(finding, "severity", "")),
                "category": str(getattr(finding, "category", "")),
                "title": str(getattr(finding, "title", "")),
                "summary": str(getattr(finding, "summary", "")),
            }
        if payload.get("fixed"):
            continue
        severity = str(payload.get("severity") or "")
        if severity not in {"fail", "warn"}:
            continue
        action_id, detail = planned_rectification_for_ops_finding(payload)
        if action_id == RECTIFICATION_DRAFT_ENG_TASK and drafted_task_ids:
            detail = f"{detail}; drafted={', '.join(drafted_task_ids)}"
        item = {
            "severity": severity,
            "category": str(payload.get("category") or ""),
            "title": str(payload.get("title") or ""),
            "summary": str(payload.get("summary") or ""),
            "planned_rectification": action_id,
            "rectification_detail": detail,
            "auto_attempted": False,
            "auto_resolved": False,
            "status": "open",
        }
        if action_id == RECTIFICATION_QUEUE_SYNC:
            needs_queue_sync = True
        items.append(item)

    if needs_queue_sync:
        lag_ids, fixed_ids, remaining_ids, sync_actions = remediate_queue_merge_sync(
            tasks_path=tasks_path,
            open_prs=open_prs,
            repo=repo,
            token=token,
            apply=apply,
        )
        actions.extend(sync_actions)
        remaining_set = set(remaining_ids)
        for item in items:
            if item["planned_rectification"] != RECTIFICATION_QUEUE_SYNC:
                continue
            item["auto_attempted"] = True
            if apply and not remaining_set:
                item["auto_resolved"] = True
                item["status"] = "resolved"
                item["rectification_detail"] = (
                    f"{item['rectification_detail']}; cleared lag={fixed_ids or ['none']}"
                )
            else:
                item["status"] = "open"
                item["rectification_detail"] = (
                    f"{item['rectification_detail']}; remaining={remaining_ids or lag_ids or ['unknown']}"
                )

    handoff = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utcnow().isoformat(),
        "email_subject": email_subject,
        "email_text": email_text,
        "email_html": email_html,
        "drafted_task_ids": drafted_task_ids,
        "items": items,
        "actions": [row.to_dict() for row in actions],
        "open_count": sum(1 for row in items if row.get("status") == "open"),
        "resolved_count": sum(1 for row in items if row.get("status") == "resolved"),
    }

    handoff_path = Path(handoff_path)
    if apply:
        handoff_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(handoff_path, handoff, compact=False)
        actions.append(
            TrafficAction(
                kind=ACTION_OPS_EMAIL_HANDOFF,
                detail=(
                    f"handed {len(items)} ops email finding(s) to PM "
                    f"(open={handoff['open_count']}, resolved={handoff['resolved_count']})"
                ),
                applied=True,
            )
        )
        handoff["actions"] = [row.to_dict() for row in actions]
        write_json(handoff_path, handoff, compact=False)

        if update_digest:
            digest_json = DEFAULT_DIGEST_PATH
            digest_md = DEFAULT_DIGEST_MARKDOWN_PATH
            existing = _safe_read(digest_json) or {}
            # Refresh digest slice when a prior digest exists; otherwise write a
            # minimal handoff-focused digest so catch-up still has a grounded row.
            if existing:
                existing["ops_email_handoff"] = handoff
                existing["generated_at"] = handoff["generated_at"]
                write_daily_digest(
                    existing,
                    json_path=digest_json,
                    markdown_path=digest_md,
                )
            else:
                digest = build_daily_digest(
                    stuck_prs=[],
                    traffic_state={},
                    actions=actions,
                    ops_email_handoff=handoff,
                )
                write_daily_digest(
                    digest,
                    json_path=digest_json,
                    markdown_path=digest_md,
                )

    handoff["actions"] = [row.to_dict() for row in actions]
    return handoff


def build_daily_digest(
    *,
    stuck_prs: list[StuckPr],
    traffic_state: dict[str, Any],
    actions: list[TrafficAction],
    progress_report_path: Path = DEFAULT_PROGRESS_REPORT_PATH,
    project_progress_path: Path = DEFAULT_PROJECT_PROGRESS_PATH,
    queue_health_path: Path = DEFAULT_QUEUE_HEALTH_PATH,
    ops_status_path: Path = DEFAULT_OPS_STATUS_PATH,
    ops_email_handoff: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Grounded EOD summary — cites artifacts; flags ungrounded gaps."""
    now = now or _utcnow()
    progress_report = _safe_read(progress_report_path)
    project_progress = _safe_read(project_progress_path)
    queue_health = _safe_read(queue_health_path)
    ops_status = _safe_read(ops_status_path)
    if ops_email_handoff is None:
        ops_email_handoff = _safe_read(DEFAULT_OPS_EMAIL_HANDOFF_PATH)

    evidence = _claim_evidence_rows(
        progress_report=progress_report,
        project_progress=project_progress,
        queue_health=queue_health,
        ops_status=ops_status,
        stuck_prs=stuck_prs,
        traffic_state=traffic_state,
    )
    ungrounded = [row for row in evidence if not row.get("grounded")]
    strengths = list((project_progress or {}).get("strengths") or [])[:5]
    gaps = list((project_progress or {}).get("gaps") or [])[:5]
    next_actions = list((project_progress or {}).get("next_actions") or [])[:5]
    appraisal = (project_progress or {}).get("appraisal") or {}
    if isinstance(appraisal, dict):
        if not strengths:
            strengths = list(appraisal.get("strengths") or [])[:5]
        if not gaps:
            gaps = list(appraisal.get("gaps") or [])[:5]
        if not next_actions:
            next_actions = list(appraisal.get("next_actions") or [])[:5]
    headline = (project_progress or {}).get("headline")
    if headline:
        strengths = [str(headline), *[str(s) for s in strengths]][:5]

    achieved: list[str] = []
    if strengths:
        achieved.extend(str(item) for item in strengths)
    merged_hint = None
    if progress_report and isinstance(progress_report.get("engineering"), dict):
        merged_hint = progress_report["engineering"].get("merged_count")
    if merged_hint is not None:
        achieved.append(f"Engineering merged_count from progress report: {merged_hint}")

    trajectory = "on_track"
    if traffic_state.get("pause_active") or stuck_prs:
        trajectory = "blocked_by_pr_queue"
    elif gaps and any("stuck" in str(g).lower() or "stall" in str(g).lower() for g in gaps):
        trajectory = "watch_stalls"
    elif ungrounded:
        trajectory = "needs_evidence"

    from value_investor.engineering_narrow_merge import list_todays_engineering_merges
    from value_investor.pr_fix_occasions import summarize_common_failure_reasons

    merges_today = list_todays_engineering_merges(tasks_path=COMMITTED_TASKS_PATH, now=now)
    verified = [row for row in merges_today if row.get("independently_verified")]
    common_issues = summarize_common_failure_reasons(limit=10)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "role": "end_of_day_project_traffic",
        "trajectory": trajectory,
        "pause_active": bool(traffic_state.get("pause_active")),
        "stuck_pr_count": len(stuck_prs),
        "achieved": achieved,
        "gaps": [str(item) for item in gaps],
        "next_actions": [str(item) for item in next_actions],
        "actions_taken": [row.to_dict() for row in actions],
        "checkpoint_probe": {
            "evidence_rows": evidence,
            "ungrounded_count": len(ungrounded),
            "grounded_count": len(evidence) - len(ungrounded),
        },
        "merges_today": merges_today,
        "verified_merges_today": verified,
        "pr_fix_common_issues": common_issues,
        "merge_authority": {
            "status": "scoped_auto_merge",
            "note": (
                "Traffic controller does not merge. Scoped auto-merge may merge "
                "ci_fix, ingest_narrow / scoring_narrow (independent deterministic "
                "verify), and parked_hunter PRs. EOD lists today's merges for monitoring."
            ),
        },
        "ops_email_handoff": ops_email_handoff,
        "sources": {
            "progress_report": str(progress_report_path) if progress_report else None,
            "project_progress": str(project_progress_path) if project_progress else None,
            "queue_health": str(queue_health_path) if queue_health else None,
            "ops_status": str(ops_status_path) if ops_status else None,
            "ops_email_handoff": (
                str(DEFAULT_OPS_EMAIL_HANDOFF_PATH) if ops_email_handoff else None
            ),
            "pr_fix_occasions": "docs/data/pr_fix_occasions.json",
        },
    }


def format_daily_digest_markdown(digest: dict[str, Any]) -> str:
    lines = [
        "# Project traffic — end-of-day digest",
        "",
        f"Generated: `{digest.get('generated_at')}`",
        f"Trajectory: **{digest.get('trajectory')}**",
        f"Dispatch pause: **{'active' if digest.get('pause_active') else 'inactive'}** "
        f"(stuck PRs: {digest.get('stuck_pr_count', 0)})",
        "",
        "## Achieved (grounded)",
    ]
    achieved = list(digest.get("achieved") or [])
    if achieved:
        lines.extend(f"- {item}" for item in achieved)
    else:
        lines.append("- _(no project_progress strengths available)_")

    lines.extend(["", "## Gaps / watch"])
    gaps = list(digest.get("gaps") or [])
    if gaps:
        lines.extend(f"- {item}" for item in gaps)
    else:
        lines.append("- _(none listed)_")

    lines.extend(["", "## Checkpoint probe"])
    probe = digest.get("checkpoint_probe") or {}
    lines.append(
        f"- Grounded rows: {probe.get('grounded_count', 0)}; "
        f"ungrounded: {probe.get('ungrounded_count', 0)}"
    )
    for row in list(probe.get("evidence_rows") or [])[:12]:
        mark = "ok" if row.get("grounded") else "UNGROUNDED"
        lines.append(f"- [{mark}] {row.get('claim')} _(source: {row.get('source')})_")

    lines.extend(["", "## Traffic actions"])
    actions = list(digest.get("actions_taken") or [])
    if actions:
        for row in actions:
            lines.append(
                f"- `{row.get('kind')}`"
                + (f" PR #{row.get('pr_number')}" if row.get("pr_number") else "")
                + f" — {row.get('detail')} "
                + ("(applied)" if row.get("applied") else "(not applied)")
            )
    else:
        lines.append("- _(none)_")

    lines.extend(["", "## Merges today (monitor independent verify)"])
    merges = list(digest.get("merges_today") or [])
    if merges:
        for row in merges:
            pr = row.get("pr_number")
            pr_bit = f" PR #{pr}" if pr else ""
            verified_label = "verified" if row.get("independently_verified") else "human"
            lines.append(
                f"- `{row.get('merge_class')}`/{verified_label}{pr_bit} "
                f"`{row.get('task_id')}` — {row.get('title')}"
            )
    else:
        lines.append("- _(none merged today)_")

    common = digest.get("pr_fix_common_issues") or {}
    lines.extend(
        [
            "",
            "## PR fix occasions — common failure reasons",
            f"- Occasion count: {common.get('occasion_count', 0)}",
        ]
    )
    by_reason = list(common.get("by_reason") or [])
    if by_reason:
        for row in by_reason[:8]:
            lines.append(
                f"- `{row.get('failure_reason')}` — {row.get('count')}×"
            )
    else:
        lines.append("- _(none recorded yet)_")

    handoff = digest.get("ops_email_handoff") or {}
    handoff_items = list(handoff.get("items") or [])
    if handoff_items or handoff.get("email_subject"):
        lines.extend(["", "## Ops-monitor email handoff"])
        if handoff.get("email_subject"):
            lines.append(f"- Email subject: `{handoff.get('email_subject')}`")
        open_count = sum(1 for row in handoff_items if row.get("status") == "open")
        resolved_count = sum(1 for row in handoff_items if row.get("status") == "resolved")
        lines.append(
            f"- Findings: {len(handoff_items)} (open={open_count}, resolved={resolved_count})"
        )
        for row in handoff_items[:12]:
            lines.append(
                f"- [{row.get('status', 'open')}] {row.get('severity', '?').upper()} "
                f"{row.get('title')} — planned: `{row.get('planned_rectification')}`"
                + (
                    f" ({row.get('rectification_detail')})"
                    if row.get("rectification_detail")
                    else ""
                )
            )

    merge = digest.get("merge_authority") or {}
    lines.extend(
        [
            "",
            "## Merge authority",
            f"- Status: **{merge.get('status', 'restricted')}**",
            f"- {merge.get('note', '')}",
            "",
            "Regenerate: `ftse-project-traffic run --write-digest`",
        ]
    )
    return "\n".join(lines) + "\n"


def write_daily_digest(
    digest: dict[str, Any],
    *,
    json_path: Path = DEFAULT_DIGEST_PATH,
    markdown_path: Path = DEFAULT_DIGEST_MARKDOWN_PATH,
) -> dict[str, Any]:
    json_path = Path(json_path)
    markdown_path = Path(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(json_path, digest, compact=False)
    markdown_path.write_text(format_daily_digest_markdown(digest), encoding="utf-8")
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def run_project_traffic(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    open_prs: list[dict[str, Any]] | None = None,
    repo: str | None = None,
    token: str | None = None,
    apply: bool = True,
    write_digest: bool = True,
    now: datetime | None = None,
) -> TrafficControllerReport:
    """Classify stuck PRs, pause/resume dispatch, request fixes, optional digest."""
    now = now or _utcnow()
    policy = _traffic_policy()
    run_at = now.isoformat()

    if not policy.get("enabled", True):
        state = get_traffic_control_state(tasks_path=tasks_path)
        return TrafficControllerReport(
            run_at=run_at,
            pause_active=bool(state.get("pause_active")),
            pause_reasons=list(state.get("pause_reasons") or []),
            stuck_prs=[],
            actions=[
                TrafficAction(
                    kind="disabled",
                    detail="engineering.traffic_control.enabled is false",
                    applied=False,
                )
            ],
            should_dispatch_conflict_agent=[],
            state=state,
        )

    if open_prs is None:
        from value_investor.ops_monitor import _github_token, list_open_pull_requests

        token = token or _github_token()
        open_prs = list_open_pull_requests(repo=repo, token=token) if token else []

    stuck = classify_stuck_prs(
        open_prs,
        tasks_path=tasks_path,
        repo=repo,
        token=token,
        now=now,
        policy=policy,
    )
    prior_pause = is_traffic_pause_active(tasks_path=tasks_path)
    state = evaluate_traffic_pause(
        stuck_prs=stuck,
        tasks_path=tasks_path,
        apply=apply,
        now=now,
        policy=policy,
    )
    actions: list[TrafficAction] = []
    if bool(state.get("pause_active")) and not prior_pause:
        actions.append(
            TrafficAction(
                kind=ACTION_PAUSE,
                detail=(
                    f"paused — {len(stuck)} stuck PR(s); reasons="
                    f"{state.get('pause_reasons') or state.get('stuck_reasons')}"
                ),
                applied=apply,
            )
        )
    if prior_pause and not bool(state.get("pause_active")):
        actions.append(
            TrafficAction(
                kind=ACTION_RESUME,
                detail="resumed — no stuck monitored PRs and idle window elapsed",
                applied=apply,
            )
        )

    unstick_actions, conflict_dispatches, state = request_unstick_actions(
        stuck,
        state=state,
        apply=apply,
        now=now,
        policy=policy,
    )
    actions.extend(unstick_actions)
    if apply and state != get_traffic_control_state(tasks_path=tasks_path):
        _save_traffic_control_state(state, tasks_path=tasks_path, apply=True)

    lag_ids, fixed_ids, remaining_ids, sync_actions = remediate_queue_merge_sync(
        tasks_path=tasks_path,
        open_prs=open_prs,
        repo=repo,
        token=token,
        apply=apply,
    )
    actions.extend(sync_actions)

    digest = None
    if write_digest and policy.get("digest_enabled", True):
        digest = build_daily_digest(
            stuck_prs=stuck,
            traffic_state=state,
            actions=actions,
            now=now,
        )
        if apply:
            write_daily_digest(digest)

    return TrafficControllerReport(
        run_at=run_at,
        pause_active=bool(state.get("pause_active")),
        pause_reasons=list(state.get("pause_reasons") or state.get("stuck_reasons") or []),
        stuck_prs=stuck,
        actions=actions,
        should_dispatch_conflict_agent=conflict_dispatches,
        digest=digest,
        state=state,
        queue_sync_lag_ids=lag_ids,
        queue_sync_fixed_ids=fixed_ids,
        queue_sync_remaining_ids=remaining_ids,
    )


def conflict_resolve_prompt(*, branch: str, pr_number: int, task_id: str | None) -> str:
    task_line = f"Engineering task id: {task_id}" if task_id else "No engineering task id."
    return f"""You are a scoped merge-conflict resolver for the FTSE Value Investor repo.

PR number: #{pr_number}
Branch: {branch}
{task_line}

Rules:
1. Rebase or merge origin/main into `{branch}` and resolve conflicts ONLY.
2. Do not expand scope, refactor, or edit blocked paths
   (paper fund, simulator, policy thresholds) unless required to resolve a conflict marker.
3. Prefer keeping the PR's intentional changes; take main for accidental drift.
4. After resolving, run the most relevant pytest subset and ruff on touched Python files.
5. Do NOT merge the PR and do NOT open additional PRs.
6. Push the resolved branch.

When finished, write a short markdown report covering: conflicts touched, tests run, risks.
"""
