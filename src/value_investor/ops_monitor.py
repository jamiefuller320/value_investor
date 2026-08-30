"""Operational health monitor with safe auto-fixes and daily email summaries."""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import weekly_ops_budget_status
from value_investor.automation_status import WORKFLOW_SCHEDULES
from value_investor.backtest_health import (
    DEFAULT_STATUS_PATH as BACKTEST_HEALTH_STATUS_PATH,
)
from value_investor.backtest_health import (
    audit_history_dir,
    repair_history_dir,
)
from value_investor.emailer import EmailConfig, send_report_email
from value_investor.engineering_queue import (
    evaluate_engineering_dispatch,
    summarize_queue,
)
from value_investor.engineering_recovery import (
    housekeep_parked_tasks,
    recover_engineering_queue,
    summarize_parked_tasks_needing_attention,
)
from value_investor.engineering_sync import (
    ENGINEERING_AGENT_WORKFLOW,
    EngineeringSyncReport,
    run_engineering_sync,
    summarize_sync_findings,
)
from value_investor.engineering_tasks import (
    BLOCKED_PATHS,
    COMMITTED_TASKS_PATH,
    TERMINAL_TASK_STATUSES,
    EngineeringTask,
    _allowed_paths_for_area,
    _default_acceptance_criteria,
    _merge_task_rows,
    compile_ingest_engineering_tasks_micro,
    load_engineering_tasks,
)
from value_investor.ingest_loop import (
    DEFAULT_HEALTH_LOG_PATH,
    ingest_health_stalled,
    load_health_log_payload,
)
from value_investor.storage import COMMITTED_HISTORY_DIR, read_json, write_json
from value_investor.workflow_pat import is_integration_token, resolve_workflow_dispatch_pat

logger = logging.getLogger(__name__)

DEFAULT_STATUS_PATH = Path("docs/data/ops_status.json")
DEFAULT_MONITOR_LOG_PATH = Path("docs/data/ops_monitor_log.json")
DEFAULT_LATEST_PATH = Path("docs/data/latest.json")
MONITOR_LOG_KEEP = 90

GITHUB_API_VERSION = "2022-11-28"

MONITORED_WORKFLOWS: tuple[dict[str, Any], ...] = (
    {
        "key": "ingest_loop",
        "workflow": "ingest-loop.yml",
        "weekdays": {0, 2, 4},
        "max_age_hours": 30,
    },
    {
        "key": "orchestrator",
        "workflow": "automation-orchestrator.yml",
        "weekdays": set(range(7)),
        "max_age_hours": 28,
    },
    {
        "key": "engineering_queue",
        "workflow": "engineering-queue.yml",
        "weekdays": {0, 1, 2, 3, 4},
        # Hourly when the queue has work; daily is enough when fully idle.
        "max_age_hours": 3,
        "max_age_hours_idle": 26,
        "idle_when": "engineering_queue_idle",
    },
    {
        "key": "ci_main_nightly",
        "workflow": "ci-main-nightly.yml",
        "weekdays": set(range(7)),
        "max_age_hours": 28,
    },
    {
        "key": "analysis_review",
        "workflow": "analysis-review.yml",
        "weekdays": {6},
        "max_age_hours": 36,
    },
    {
        "key": "library_ladder",
        "workflow": "library-grow.yml",
        "weekdays": {6},
        "max_age_hours": 36,
    },
    {
        "key": "model_review",
        "workflow": "library-model-review.yml",
        "weekdays": {6},
        "max_age_hours": 36,
    },
    {
        "key": "email_report",
        "workflow": "email-report.yml",
        "weekdays": {6},
        "max_age_hours": 36,
    },
    {
        "key": "data_backup",
        "workflow": "data-backup.yml",
        "weekdays": {6},
        "max_age_hours": 36,
    },
    {
        "key": "paper_auto",
        "workflow": "paper-auto.yml",
        "weekdays": {0, 1, 2, 3, 4},
        "max_age_hours": 28,
    },
    {
        "key": "ops_monitor",
        "workflow": "ops-monitor.yml",
        "weekdays": set(range(7)),
        "max_age_hours": 28,
    },
)

# Sunday quiet bundle + orchestrator — soften overdue findings while a run is active.
RECOVERY_BUNDLE_WORKFLOWS: frozenset[str] = frozenset(
    {
        "automation-orchestrator.yml",
        "library-grow.yml",
        "library-model-review.yml",
        "email-report.yml",
    }
)
ACTIVE_RUN_STATUSES: tuple[str, ...] = ("in_progress", "queued", "waiting")

# Earliest UTC (hour, minute) when a workflow overdue finding is actionable on a
# scheduled day. Before this wall-clock time, morning ops email is deferred so
# the afternoon catch-up (13:15) can report after the day's slots complete.
WORKFLOW_EMAIL_READY_UTC: dict[str, tuple[int, int]] = {
    "ingest_loop": (8, 0),
    "orchestrator": (7, 30),
    "engineering_queue": (8, 0),
    "ci_main_nightly": (8, 30),
    "analysis_review": (11, 0),  # external primary ~10:35
    "library_ladder": (8, 0),
    "model_review": (8, 0),
    "email_report": (9, 0),  # quiet-bundle child; often ~70m from ~06:40
    "data_backup": (13, 0),  # external primary ~12:30
    "paper_auto": (10, 0),  # weekday ~08:20
    "ops_monitor": (8, 0),
}

COMMITTED_JSON_PATHS: tuple[Path, ...] = (
    DEFAULT_HEALTH_LOG_PATH,
    DEFAULT_LATEST_PATH,
    COMMITTED_TASKS_PATH,
    Path("docs/data/paper_automation/last_run.json"),
    Path("docs/data/library/policy.json"),
)


@dataclass
class OpsFinding:
    severity: str
    category: str
    title: str
    summary: str
    auto_fixable: bool = False
    fixed: bool = False
    action_taken: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "category": self.category,
            "title": self.title,
            "summary": self.summary,
            "auto_fixable": self.auto_fixable,
            "fixed": self.fixed,
            "action_taken": self.action_taken,
        }


@dataclass
class OpsMonitorReport:
    run_at: str
    overall: str
    findings: list[OpsFinding] = field(default_factory=list)
    auto_fixes: list[dict[str, Any]] = field(default_factory=list)
    drafted_task_ids: list[str] = field(default_factory=list)
    workflow_checks: list[dict[str, Any]] = field(default_factory=list)
    queue_status: dict[str, Any] = field(default_factory=dict)
    should_dispatch_engineering: bool = False
    email_deferred: bool = False
    email_defer_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_at": self.run_at,
            "overall": self.overall,
            "findings": [row.to_dict() for row in self.findings],
            "auto_fixes": self.auto_fixes,
            "drafted_task_ids": self.drafted_task_ids,
            "workflow_checks": self.workflow_checks,
            "queue_status": self.queue_status,
            "should_dispatch_engineering": self.should_dispatch_engineering,
            "email_deferred": self.email_deferred,
            "email_defer_reasons": self.email_defer_reasons,
        }


def _github_token() -> str | None:
    pat = resolve_workflow_dispatch_pat()
    if pat:
        return pat
    for key in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(key)
        if value and not is_integration_token(value):
            return value
        if value and key == "GITHUB_TOKEN":
            # In GitHub Actions the installation token is valid for repo API reads.
            return value
    return None


def _github_repo() -> str | None:
    value = os.environ.get("GITHUB_REPOSITORY")
    if value and "/" in value:
        return value
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER")
    name = (
        os.environ.get("GITHUB_REPOSITORY", "").split("/")[-1]
        if "/" in os.environ.get("GITHUB_REPOSITORY", "")
        else None
    )
    if owner and name:
        return f"{owner}/{name}"
    return None


def github_api_get(path: str, *, token: str | None = None) -> Any:
    token = token or _github_token()
    if not token:
        raise RuntimeError(
            "GitHub token not configured (WORKFLOW_DISPATCH_PAT / GITHUB_TOKEN / GH_TOKEN)"
        )
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


def list_open_pull_requests(
    *, repo: str | None = None, token: str | None = None
) -> list[dict[str, Any]]:
    repo = repo or _github_repo()
    if not repo:
        return []
    token = token or _github_token()
    if not token:
        return []
    owner, name = repo.split("/", 1)
    payload = github_api_get(f"/repos/{owner}/{name}/pulls?state=open&per_page=100", token=token)
    return list(payload) if isinstance(payload, list) else []


def latest_workflow_run(
    workflow_file: str,
    *,
    repo: str | None = None,
    token: str | None = None,
    status: str | None = "success",
) -> dict[str, Any] | None:
    repo = repo or _github_repo()
    token = token or _github_token()
    if not repo or not token:
        return None
    owner, name = repo.split("/", 1)
    query = f"/repos/{owner}/{name}/actions/workflows/{workflow_file}/runs?per_page=1"
    if status:
        query += f"&status={status}"
    payload = github_api_get(query, token=token)
    rows = list((payload or {}).get("workflow_runs") or [])
    return rows[0] if rows else None


def active_workflow_runs(
    workflow_file: str,
    *,
    repo: str | None = None,
    token: str | None = None,
) -> list[dict[str, Any]]:
    """Return in-flight runs (in_progress / queued / waiting) for a workflow file."""
    repo = repo or _github_repo()
    token = token or _github_token()
    if not repo or not token:
        return []
    owner, name = repo.split("/", 1)
    seen: set[int] = set()
    active: list[dict[str, Any]] = []
    for status in ACTIVE_RUN_STATUSES:
        payload = github_api_get(
            f"/repos/{owner}/{name}/actions/workflows/{workflow_file}/runs"
            f"?per_page=5&status={status}",
            token=token,
        )
        for row in list((payload or {}).get("workflow_runs") or []):
            run_id = row.get("id")
            if run_id is None or run_id in seen:
                continue
            seen.add(int(run_id))
            active.append(row)
    return active


def recovery_bundle_in_flight(
    *,
    repo: str | None = None,
    token: str | None = None,
) -> tuple[bool, list[str]]:
    """True when orchestrator or a Sunday bundle child workflow is actively running."""
    active_labels: list[str] = []
    for workflow in sorted(RECOVERY_BUNDLE_WORKFLOWS):
        runs = active_workflow_runs(workflow, repo=repo, token=token)
        if runs:
            active_labels.append(f"{workflow}#{runs[0].get('id')}")
    return bool(active_labels), active_labels


def filter_unresolved_workflow_failures(
    failures: list[dict[str, Any]],
    last_success_at: datetime | None,
) -> list[dict[str, Any]]:
    """Keep only failures newer than the latest successful run (actionable regressions)."""
    if last_success_at is None:
        return list(failures)
    unresolved: list[dict[str, Any]] = []
    for row in failures:
        run_at = _parse_github_time(str(row.get("created_at") or ""))
        if run_at is None:
            unresolved.append(row)
            continue
        if run_at > last_success_at:
            unresolved.append(row)
    return unresolved


def recent_workflow_failures(
    workflow_file: str,
    *,
    repo: str | None = None,
    token: str | None = None,
    within_hours: int = 24,
) -> list[dict[str, Any]]:
    repo = repo or _github_repo()
    token = token or _github_token()
    if not repo or not token:
        return []
    owner, name = repo.split("/", 1)
    payload = github_api_get(
        f"/repos/{owner}/{name}/actions/workflows/{workflow_file}/runs?per_page=10&status=failure",
        token=token,
    )
    cutoff = datetime.now(UTC) - timedelta(hours=within_hours)
    failures: list[dict[str, Any]] = []
    for row in list((payload or {}).get("workflow_runs") or []):
        created = str(row.get("created_at") or "")
        try:
            run_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            continue
        if run_at >= cutoff:
            failures.append(row)
    return failures


def _parse_github_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def check_committed_json(paths: Iterable[Path] = COMMITTED_JSON_PATHS) -> list[OpsFinding]:
    findings: list[OpsFinding] = []
    for path in paths:
        path = Path(path)
        if not path.exists():
            continue
        try:
            read_json(path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            findings.append(
                OpsFinding(
                    severity="fail",
                    category="artifacts",
                    title=f"Corrupt committed JSON: {path.as_posix()}",
                    summary=str(exc),
                    auto_fixable=path == DEFAULT_HEALTH_LOG_PATH,
                )
            )
    return findings


def check_ingest_health_log(path: Path = DEFAULT_HEALTH_LOG_PATH) -> list[OpsFinding]:
    findings: list[OpsFinding] = []
    if not path.exists():
        findings.append(
            OpsFinding(
                severity="warn",
                category="ingest",
                title="Ingest health log missing",
                summary=f"Expected {path.as_posix()} — weekday ingest loop may not have run yet.",
            )
        )
        return findings

    raw = path.read_bytes()
    try:
        json.loads(raw.decode("utf-8"))
        corrupt = False
    except json.JSONDecodeError:
        corrupt = True

    if corrupt:
        findings.append(
            OpsFinding(
                severity="fail",
                category="ingest",
                title="Ingest health log is corrupt",
                summary="JSON parse failed — stall detection and micro-compile history may reset.",
                auto_fixable=True,
            )
        )
        return findings

    payload = load_health_log_payload(path, backup_corrupt=False)
    entries = list(payload.get("entries") or [])
    if len(entries) < 2:
        findings.append(
            OpsFinding(
                severity="warn",
                category="ingest",
                title="Ingest health log has thin history",
                summary=f"Only {len(entries)} run(s) recorded — stall detection needs ≥2 weekday entries.",
            )
        )
    if ingest_health_stalled(path):
        findings.append(
            OpsFinding(
                severity="warn",
                category="ingest",
                title="Buy-tier filing ingest stalled",
                summary="zero_body_buy_tier unchanged across recent runs — micro-compile or engineering may be needed.",
                auto_fixable=True,
            )
        )
    latest = entries[-1] if entries else {}
    if latest.get("runtime_cutoff") and int(latest.get("targets_deferred") or 0) > 0:
        deferred = int(latest.get("targets_deferred") or 0)
        completed = int(latest.get("targets_completed") or 0)
        reason = str(latest.get("cutoff_reason") or "runtime_cutoff")
        findings.append(
            OpsFinding(
                severity="warn",
                category="ingest",
                title="Ingest loop hit runtime cutoff",
                summary=(
                    f"Last run deferred {deferred} ticker(s) after completing {completed} "
                    f"({reason}) — backlog resume or chained chunk should drain remainder."
                ),
            )
        )
    return findings


def check_latest_bundle(
    path: Path = DEFAULT_LATEST_PATH, *, max_age_hours: int = 168
) -> list[OpsFinding]:
    if not path.exists():
        return [
            OpsFinding(
                severity="fail",
                category="dashboard",
                title="Published dashboard bundle missing",
                summary=f"{path.as_posix()} not found — run ftse-publish or Sunday orchestrator.",
            )
        ]
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError) as exc:
        return [
            OpsFinding(
                severity="fail",
                category="dashboard",
                title="Published dashboard bundle corrupt",
                summary=str(exc),
            )
        ]
    updated_at = _parse_github_time(str(payload.get("updated_at") or payload.get("run_at") or ""))
    if updated_at is None:
        return [
            OpsFinding(
                severity="warn",
                category="dashboard",
                title="Dashboard bundle has no updated_at",
                summary="Cannot assess freshness of docs/data/latest.json.",
            )
        ]
    age = datetime.now(UTC) - updated_at
    if age > timedelta(hours=max_age_hours):
        return [
            OpsFinding(
                severity="warn",
                category="dashboard",
                title="Dashboard bundle is stale",
                summary=(
                    f"latest.json updated {updated_at.isoformat()} "
                    f"({int(age.total_seconds() // 3600)}h ago; threshold {max_age_hours}h)."
                ),
            )
        ]
    return []


def _engineering_queue_needs_hourly(queue_status: dict[str, Any] | None) -> bool:
    """True when open/pr_open tasks or an in-flight agent need the hourly processor."""
    if not queue_status:
        return False
    if int(queue_status.get("open_count") or 0) > 0:
        return True
    if int(queue_status.get("pr_open_count") or 0) > 0:
        return True
    if queue_status.get("in_flight_branch") or queue_status.get("in_flight_pr"):
        return True
    return False


def _workflow_max_age_hours(spec: dict[str, Any], *, queue_status: dict[str, Any] | None) -> int:
    default = int(spec.get("max_age_hours") or 24)
    if spec.get("idle_when") == "engineering_queue_idle":
        if not _engineering_queue_needs_hourly(queue_status):
            return int(spec.get("max_age_hours_idle") or default)
    return default


def check_workflow_freshness(
    *,
    repo: str | None = None,
    token: str | None = None,
    now: datetime | None = None,
    queue_status: dict[str, Any] | None = None,
) -> tuple[list[OpsFinding], list[dict[str, Any]]]:
    findings: list[OpsFinding] = []
    checks: list[dict[str, Any]] = []
    token = token or _github_token()
    if not token:
        findings.append(
            OpsFinding(
                severity="warn",
                category="workflows",
                title="GitHub workflow checks skipped",
                summary="No GITHUB_TOKEN/GH_TOKEN — workflow freshness not evaluated.",
            )
        )
        return findings, checks

    now = now or datetime.now(UTC)
    weekday = now.weekday()

    for spec in MONITORED_WORKFLOWS:
        workflow = str(spec["workflow"])
        key = str(spec["key"])
        schedule = WORKFLOW_SCHEDULES.get(key, {})
        expected_today = weekday in set(spec.get("weekdays") or set())
        max_age_hours = _workflow_max_age_hours(spec, queue_status=queue_status)
        max_age = timedelta(hours=max_age_hours)
        last_success = latest_workflow_run(workflow, repo=repo, token=token, status="success")
        last_run_at = _parse_github_time(str((last_success or {}).get("created_at") or ""))
        age = (now - last_run_at) if last_run_at else None
        stale = expected_today and (last_run_at is None or age > max_age)
        failures = recent_workflow_failures(workflow, repo=repo, token=token, within_hours=12)
        unresolved = filter_unresolved_workflow_failures(failures, last_run_at)

        row = {
            "workflow": workflow,
            "name": schedule.get("name") or workflow,
            "expected_today": expected_today,
            "max_age_hours": max_age_hours,
            "last_success_at": last_run_at.isoformat() if last_run_at else None,
            "last_success_run_id": (last_success or {}).get("id"),
            "age_hours": round(age.total_seconds() / 3600, 1) if age else None,
            "stale": stale,
            "recent_failures_24h": len(failures),
            "unresolved_failures_12h": len(unresolved),
        }
        checks.append(row)

        if unresolved:
            run_ids = ", ".join(str(item.get("id")) for item in unresolved[:3])
            failure_finding = OpsFinding(
                severity="warn",
                category="workflows",
                title=f"Recent workflow failure: {row['name']}",
                summary=(
                    f"{len(unresolved)} unresolved failure(s) since last success (runs: {run_ids})."
                ),
            )
            active = active_workflow_runs(workflow, repo=repo, token=token)
            if active:
                # Dedicated responders (ladder / workflow-failure) may already be
                # re-running — suppress from email until the recovery settles.
                active_id = active[0].get("id")
                failure_finding.fixed = True
                failure_finding.action_taken = (
                    f"Recovery run in flight (#{active_id}); suppressed from alert"
                )
            findings.append(failure_finding)
        if stale:
            findings.append(
                OpsFinding(
                    severity="fail" if expected_today else "warn",
                    category="workflows",
                    title=f"Workflow overdue: {row['name']}",
                    summary=(
                        f"No successful run within {int(max_age.total_seconds() // 3600)}h "
                        f"(last: {last_run_at.isoformat() if last_run_at else 'never'})."
                    ),
                )
            )

    recovery_active, recovery_detail = recovery_bundle_in_flight(repo=repo, token=token)
    if recovery_active:
        detail = ", ".join(recovery_detail)
        name_to_workflow = {
            str(row.get("name") or ""): str(row.get("workflow") or "") for row in checks
        }
        for finding in findings:
            if finding.category != "workflows" or not finding.title.startswith("Workflow overdue:"):
                continue
            schedule_name = finding.title.removeprefix("Workflow overdue:").strip()
            workflow_file = name_to_workflow.get(schedule_name, "")
            if workflow_file not in RECOVERY_BUNDLE_WORKFLOWS:
                continue
            if finding.severity == "fail":
                finding.severity = "warn"
            finding.summary = f"{finding.summary} Recovery bundle in flight ({detail})."

    return findings, checks


def check_engineering_queue(
    *,
    open_prs: list[dict[str, Any]] | None = None,
    tasks_path: Path = COMMITTED_TASKS_PATH,
) -> tuple[list[OpsFinding], dict[str, Any]]:
    findings: list[OpsFinding] = []
    status = summarize_queue(tasks_path=tasks_path, open_prs=open_prs)
    queue_dict = status.to_dict()

    orphaned = [
        row
        for row in load_engineering_tasks(tasks_path).get("tasks") or []
        if str(row.get("status") or "") == "pr_open"
        and not any(
            str(pr.get("headRefName") or pr.get("head_branch") or "").strip()
            == str(row.get("branch_name") or "").strip()
            for pr in (open_prs or [])
        )
    ]
    if orphaned:
        ids = ", ".join(str(row.get("id")) for row in orphaned)
        findings.append(
            OpsFinding(
                severity="warn",
                category="engineering",
                title="Orphaned pr_open engineering tasks",
                summary=f"Tasks without matching open PR: {ids}",
                auto_fixable=True,
            )
        )

    if status.failed_count:
        findings.append(
            OpsFinding(
                severity="warn",
                category="engineering",
                title="Failed engineering tasks in queue",
                summary=f"{status.failed_count} task(s) marked failed — recovery may retry or park.",
                auto_fixable=True,
            )
        )

    parked = summarize_parked_tasks_needing_attention(tasks_path)
    if parked:
        ids = ", ".join(str(row.get("id")) for row in parked[:5])
        findings.append(
            OpsFinding(
                severity="warn",
                category="engineering",
                title="Parked engineering tasks need manual review",
                summary=f"{len(parked)} parked task(s): {ids}",
            )
        )

    if status.spend_blocked:
        findings.append(
            OpsFinding(
                severity="warn",
                category="engineering",
                title="Engineering spend checkpoint reached",
                summary=(
                    f"${status.spend_since_checkpoint_usd:.2f} / "
                    f"${status.spend_checkpoint_usd:.2f} — agent dispatch paused."
                ),
            )
        )
    return findings, queue_dict


def check_engineering_sync(
    *,
    open_prs: list[dict[str, Any]] | None = None,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    repo: str | None = None,
    token: str | None = None,
    recent_agent_failures: list[dict[str, Any]] | None = None,
) -> tuple[list[OpsFinding], EngineeringSyncReport]:
    failures = (
        list(recent_agent_failures)
        if recent_agent_failures is not None
        else recent_workflow_failures(
            ENGINEERING_AGENT_WORKFLOW,
            repo=repo,
            token=token,
            within_hours=6,
        )
    )
    report = run_engineering_sync(
        tasks_path=tasks_path,
        open_prs=open_prs,
        recent_agent_failures=failures,
        apply=False,
    )
    status = summarize_queue(tasks_path=tasks_path, open_prs=open_prs)
    findings: list[OpsFinding] = []
    for row in summarize_sync_findings(
        report,
        status_open_count=status.open_count,
        in_flight_pr=status.in_flight_pr,
    ):
        findings.append(
            OpsFinding(
                severity=row["severity"],
                category="engineering",
                title=row["title"],
                summary=row["summary"],
                auto_fixable=True,
            )
        )
    return findings, report


def check_ops_budget() -> list[OpsFinding]:
    status = weekly_ops_budget_status()
    if not status:
        return []
    findings: list[OpsFinding] = []
    used = float(status.get("estimated_spend_weekly_ops_usd_this_week") or 0)
    cap = float(status.get("weekly_ops_cap_usd") or 0)
    if cap > 0 and used / cap >= 0.9:
        findings.append(
            OpsFinding(
                severity="warn",
                category="budget",
                title="Weekly ops budget nearly exhausted",
                summary=f"${used:.2f} / ${cap:.2f} weekly ops spend used.",
            )
        )
    return findings


def check_backtest_history(
    history_dir: Path = COMMITTED_HISTORY_DIR,
) -> list[OpsFinding]:
    findings: list[OpsFinding] = []
    issues, stats = audit_history_dir(history_dir)
    for row in issues:
        findings.append(
            OpsFinding(
                severity=row.severity,
                category="backtest",
                title=f"Backtest history: {row.code}",
                summary=row.summary,
                auto_fixable=row.auto_fixable,
            )
        )
    if int(stats.get("valid_runs") or 0) < 2:
        findings.append(
            OpsFinding(
                severity="warn",
                category="backtest",
                title="Backtest history still seeding",
                summary=(
                    f"{stats.get('valid_runs', 0)} valid run snapshot(s) in {history_dir.as_posix()} — "
                    "need ≥2 weekly archives before forward-return backtest populates."
                ),
            )
        )
    return findings


def _next_engineering_seq(existing_rows: list[dict[str, Any]], run_stamp: str) -> int:
    prefix = f"eng-{run_stamp}-"
    used = [
        int(str(row.get("id") or "").removeprefix(prefix))
        for row in existing_rows
        if str(row.get("id") or "").startswith(prefix)
        and str(row.get("id") or "").removeprefix(prefix).isdigit()
    ]
    return max(used, default=0) + 1


def draft_ops_engineering_tasks(
    findings: list[OpsFinding],
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    max_tasks: int = 3,
) -> list[str]:
    """Queue ops-area engineering tasks for findings that need a supervised PR."""
    actionable = [
        row for row in findings if row.severity == "fail" and not row.fixed and not row.auto_fixable
    ]
    if not actionable:
        return []

    run_stamp = datetime.now(UTC).strftime("%Y%m%d")
    payload = load_engineering_tasks(tasks_path)
    existing_rows = list(payload.get("tasks") or [])
    existing_titles = {
        re.sub(r"\s+", " ", str(row.get("title") or "").strip().lower())
        for row in existing_rows
        if str(row.get("status") or "open") not in TERMINAL_TASK_STATUSES
    }

    drafted: list[EngineeringTask] = []
    seq = _next_engineering_seq(existing_rows, run_stamp)
    for finding in actionable[:max_tasks]:
        title_key = re.sub(r"\s+", " ", finding.title.strip().lower())
        if title_key in existing_titles:
            continue
        drafted.append(
            EngineeringTask(
                id=f"eng-{run_stamp}-{seq:02d}",
                area="ops",
                title=finding.title[:160],
                summary=f"{finding.summary} (category: {finding.category})",
                priority="medium",
                priority_score=45.0,
                source="ops_monitor",
                evidence={"category": finding.category, "severity": finding.severity},
                acceptance_criteria=_default_acceptance_criteria("ops", []),
                allowed_paths=_allowed_paths_for_area("ops"),
                blocked_paths=list(BLOCKED_PATHS),
            )
        )
        existing_titles.add(title_key)
        seq += 1

    if not drafted:
        return []

    merged_rows = _merge_task_rows(existing_rows, drafted)
    payload = {
        **payload,
        "compiled_at": datetime.now(UTC).isoformat(),
        "task_count": len(merged_rows),
        "tasks": merged_rows,
        "ops_monitor_compiled": True,
    }
    tasks_path = Path(tasks_path)
    tasks_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(tasks_path, payload, compact=False)
    return [task.id for task in drafted]


def apply_auto_fixes(
    findings: list[OpsFinding],
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    health_log_path: Path = DEFAULT_HEALTH_LOG_PATH,
    open_prs: list[dict[str, Any]] | None = None,
    apply: bool = True,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    if apply:
        recovery = recover_engineering_queue(
            tasks_path=tasks_path,
            open_prs=open_prs,
            apply=True,
        )
        if recovery.reconciled:
            action = f"reconciled pr_open → open: {', '.join(recovery.reconciled)}"
            results.append({"action": "recover_engineering_queue", "detail": action})
            for finding in findings:
                if finding.title.startswith("Orphaned pr_open"):
                    finding.fixed = True
                    finding.action_taken = action
        if recovery.reopened:
            action = f"reopened failed tasks: {', '.join(recovery.reopened)}"
            results.append({"action": "retry_failed_tasks", "detail": action})
            for finding in findings:
                if finding.title == "Failed engineering tasks in queue":
                    finding.fixed = True
                    finding.action_taken = action
        for parked_action in recovery.parked:
            detail = f"parked {parked_action.task_id}: {parked_action.reason}"
            results.append({"action": "park_engineering_task", "detail": detail})

        housekeep = housekeep_parked_tasks(tasks_path=tasks_path, apply=True)
        for action in housekeep.cancelled:
            detail = f"cancelled duplicate {action.task_id}" + (
                f" (of {action.duplicate_of})" if action.duplicate_of else ""
            )
            results.append({"action": "housekeep_parked_task", "detail": detail})
            for finding in findings:
                if finding.title == "Parked engineering tasks need manual review":
                    finding.fixed = True
                    finding.action_taken = detail
        for action in housekeep.annotated:
            results.append(
                {
                    "action": "annotate_parked_task",
                    "detail": f"{action.task_id}: {action.reason}",
                }
            )

    corrupt_health = any(row.title == "Ingest health log is corrupt" for row in findings)
    if corrupt_health and apply and health_log_path.exists():
        backup = health_log_path.with_name(
            f"{health_log_path.stem}.corrupt.{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}{health_log_path.suffix}"
        )
        backup.write_bytes(health_log_path.read_bytes())
        payload = load_health_log_payload(health_log_path, backup_corrupt=False)
        write_json(
            health_log_path,
            {"entries": payload.get("entries") or [], "updated_at": datetime.now(UTC).isoformat()},
        )
        action = f"normalized corrupt health log; backup at {backup.name}"
        results.append({"action": "repair_health_log", "detail": action})
        for finding in findings:
            if finding.title == "Ingest health log is corrupt":
                finding.fixed = True
                finding.action_taken = action

    stalled = any(row.title == "Buy-tier filing ingest stalled" for row in findings)
    if stalled and apply:
        micro = compile_ingest_engineering_tasks_micro(committed_path=tasks_path)
        if micro.get("compiled_count"):
            ids = ", ".join(micro.get("task_ids") or [])
            action = f"micro-compiled ingest tasks: {ids}"
            results.append({"action": "micro_compile_ingest", "detail": action})
            for finding in findings:
                if finding.title == "Buy-tier filing ingest stalled":
                    finding.fixed = True
                    finding.action_taken = action

    backtest_fixable = any(
        row.category == "backtest" and row.auto_fixable and not row.fixed for row in findings
    )
    if backtest_fixable and apply:
        issues, _ = audit_history_dir(COMMITTED_HISTORY_DIR)
        repairs = repair_history_dir(COMMITTED_HISTORY_DIR, issues, apply=True)
        for repair in repairs:
            results.append({"action": repair.action, "detail": repair.detail})
        if repairs:
            for finding in findings:
                if finding.category == "backtest" and finding.auto_fixable:
                    finding.fixed = True
                    finding.action_taken = "; ".join(row.detail for row in repairs[:3])

    return results


def _overall_status(findings: list[OpsFinding]) -> str:
    """Grade from unfixed findings only — healed rows do not keep the report red."""
    if any(row.severity == "fail" and not row.fixed for row in findings):
        return "fail"
    if any(row.severity in {"fail", "warn"} and not row.fixed for row in findings):
        return "warn"
    return "ok"


def findings_needing_investigation(findings: list[OpsFinding]) -> list[OpsFinding]:
    """Unfixed warn/fail rows that should reach email / drafting."""
    return [row for row in findings if row.severity in {"fail", "warn"} and not row.fixed]


def _workflow_key_for_name(schedule_name: str) -> str | None:
    name = schedule_name.strip()
    for spec in MONITORED_WORKFLOWS:
        key = str(spec["key"])
        schedule = WORKFLOW_SCHEDULES.get(key, {})
        if str(schedule.get("name") or spec["workflow"]) == name:
            return key
    return None


def _workflow_check_by_name(
    workflow_checks: list[dict[str, Any]], schedule_name: str
) -> dict[str, Any] | None:
    name = schedule_name.strip()
    for row in workflow_checks:
        if str(row.get("name") or "") == name:
            return row
    return None


def _email_report_pending_today(
    workflow_checks: list[dict[str, Any]],
    *,
    now: datetime,
) -> bool:
    """True when today's email-report success is still outstanding or in flight."""
    email_row = next(
        (row for row in workflow_checks if row.get("workflow") == "email-report.yml"),
        None,
    )
    if not email_row:
        return False
    if not email_row.get("expected_today"):
        return False
    last = _parse_github_time(str(email_row.get("last_success_at") or ""))
    if last is not None and last.date() == now.date():
        return False
    ready_h, ready_m = WORKFLOW_EMAIL_READY_UTC.get("email_report", (9, 0))
    if (now.hour, now.minute) < (ready_h, ready_m):
        return True
    # Past ready time but still no today success — not "pending", actionable.
    return False


def finding_email_defer_reason(
    finding: OpsFinding,
    *,
    workflow_checks: list[dict[str, Any]],
    now: datetime | None = None,
) -> str | None:
    """Return a deferral reason when this finding should wait for later-day catch-up."""
    now = now or datetime.now(UTC)
    summary = finding.summary or ""
    action = finding.action_taken or ""

    if "Recovery bundle in flight" in summary or "Recovery run in flight" in action:
        return "recovery run still in flight"

    if finding.title.startswith("Workflow overdue:"):
        schedule_name = finding.title.removeprefix("Workflow overdue:").strip()
        key = _workflow_key_for_name(schedule_name)
        check = _workflow_check_by_name(workflow_checks, schedule_name)
        if check and not check.get("expected_today"):
            return None
        if key and key in WORKFLOW_EMAIL_READY_UTC:
            ready_h, ready_m = WORKFLOW_EMAIL_READY_UTC[key]
            if (now.hour, now.minute) < (ready_h, ready_m):
                return (
                    f"{schedule_name} scheduled slot not reached yet "
                    f"(email-ready after {ready_h:02d}:{ready_m:02d} UTC)"
                )
        return None

    if finding.title == "Dashboard bundle is stale":
        if _email_report_pending_today(workflow_checks, now=now):
            return "dashboard refresh waits on today's email-report"
        overdue_email = next(
            (
                c
                for c in workflow_checks
                if c.get("workflow") == "email-report.yml" and c.get("stale")
            ),
            None,
        )
        if overdue_email:
            ready_h, ready_m = WORKFLOW_EMAIL_READY_UTC.get("email_report", (9, 0))
            if (now.hour, now.minute) < (ready_h, ready_m):
                return "dashboard refresh waits on today's email-report"
        return None

    return None


def evaluate_email_deferral(
    findings: list[OpsFinding],
    workflow_checks: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> tuple[bool, list[str]]:
    """Defer alert email when every unfixed issue is still expected to clear today."""
    now = now or datetime.now(UTC)
    needs = findings_needing_investigation(findings)
    if not needs:
        return False, []
    reasons: list[str] = []
    for row in needs:
        reason = finding_email_defer_reason(row, workflow_checks=workflow_checks, now=now)
        if not reason:
            return False, []
        label = f"{row.title}: {reason}"
        if label not in reasons:
            reasons.append(label)
    return True, reasons


def workflow_stale_only_failures(findings: list[OpsFinding]) -> bool:
    """True when every unfixed fail finding is a workflow-overdue stale check."""
    unfixed_fails = [row for row in findings if row.severity == "fail" and not row.fixed]
    if not unfixed_fails:
        return False
    return all(
        row.category == "workflows" and row.title.startswith("Workflow overdue:")
        for row in unfixed_fails
    )


def _finding_key(finding: OpsFinding) -> tuple[str, str]:
    return (finding.category, finding.title)


def merge_healed_findings(
    before: list[OpsFinding],
    after: list[OpsFinding],
) -> list[OpsFinding]:
    """Keep fixed findings that no longer reproduce after re-verify (audit trail)."""
    after_keys = {_finding_key(row) for row in after}
    healed = [row for row in before if row.fixed and _finding_key(row) not in after_keys]
    return list(after) + healed


def collect_ops_findings(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    health_log_path: Path = DEFAULT_HEALTH_LOG_PATH,
    latest_path: Path = DEFAULT_LATEST_PATH,
    open_prs: list[dict[str, Any]] | None = None,
    repo: str | None = None,
    token: str | None = None,
    eng_failures: list[dict[str, Any]] | None = None,
) -> tuple[list[OpsFinding], dict[str, Any], list[dict[str, Any]]]:
    """Run all detection checks without applying fixes."""
    findings: list[OpsFinding] = []
    findings.extend(check_committed_json())
    findings.extend(check_ingest_health_log(health_log_path))
    findings.extend(check_latest_bundle(latest_path))
    findings.extend(check_ops_budget())
    findings.extend(check_backtest_history())

    engineering_findings, queue_status = check_engineering_queue(
        open_prs=open_prs,
        tasks_path=tasks_path,
    )
    if eng_failures is None:
        eng_failures = recent_workflow_failures(
            ENGINEERING_AGENT_WORKFLOW,
            repo=repo,
            token=token,
            within_hours=6,
        )
    sync_findings, _sync_preview = check_engineering_sync(
        open_prs=open_prs,
        tasks_path=tasks_path,
        repo=repo,
        token=token,
        recent_agent_failures=eng_failures,
    )
    workflow_findings, workflow_checks = check_workflow_freshness(
        repo=repo,
        token=token,
        queue_status=queue_status,
    )
    findings.extend(workflow_findings)
    findings.extend(engineering_findings)
    findings.extend(sync_findings)
    return findings, queue_status, workflow_checks


def run_ops_monitor(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    health_log_path: Path = DEFAULT_HEALTH_LOG_PATH,
    latest_path: Path = DEFAULT_LATEST_PATH,
    status_path: Path = DEFAULT_STATUS_PATH,
    apply_fixes: bool = True,
    draft_tasks: bool = True,
    open_prs: list[dict[str, Any]] | None = None,
    repo: str | None = None,
    token: str | None = None,
) -> OpsMonitorReport:
    """Detect → safe auto-fix → re-verify → draft/email only remaining issues."""
    run_at = datetime.now(UTC).isoformat()

    if open_prs is None and _github_token():
        open_prs = list_open_pull_requests(repo=repo, token=token)

    eng_failures = recent_workflow_failures(
        ENGINEERING_AGENT_WORKFLOW,
        repo=repo,
        token=token,
        within_hours=6,
    )
    findings, queue_status, workflow_checks = collect_ops_findings(
        tasks_path=tasks_path,
        health_log_path=health_log_path,
        latest_path=latest_path,
        open_prs=open_prs,
        repo=repo,
        token=token,
        eng_failures=eng_failures,
    )

    auto_fixes = apply_auto_fixes(
        findings,
        tasks_path=tasks_path,
        health_log_path=health_log_path,
        open_prs=open_prs,
        apply=apply_fixes,
    )

    sync_report = run_engineering_sync(
        tasks_path=tasks_path,
        open_prs=open_prs,
        recent_agent_failures=eng_failures,
        apply=apply_fixes,
        repo=repo,
        token=token,
    )
    for repair in sync_report.repairs:
        auto_fixes.append(repair)
    if sync_report.repairs:
        for finding in findings:
            if (
                finding.category == "engineering"
                and finding.auto_fixable
                and finding.title.startswith(
                    ("Engineering agent sync", "Engineering compile would")
                )
            ):
                finding.fixed = True
                finding.action_taken = "; ".join(
                    f"{row['action']}: {row['detail']}" for row in sync_report.repairs[:2]
                )

    # Heal → re-verify: re-run detection so overall/email reflect post-fix truth.
    if apply_fixes and auto_fixes:
        verified, queue_status, workflow_checks = collect_ops_findings(
            tasks_path=tasks_path,
            health_log_path=health_log_path,
            latest_path=latest_path,
            open_prs=open_prs,
            repo=repo,
            token=token,
            eng_failures=eng_failures,
        )
        findings = merge_healed_findings(findings, verified)

    email_deferred, email_defer_reasons = evaluate_email_deferral(findings, workflow_checks)

    drafted_ids: list[str] = []
    if draft_tasks and apply_fixes:
        # Do not mint ops tasks for findings that are still expected to clear today.
        draftable = [
            row
            for row in findings
            if finding_email_defer_reason(row, workflow_checks=workflow_checks) is None
        ]
        drafted_ids = draft_ops_engineering_tasks(draftable, tasks_path=tasks_path)

    dispatch = evaluate_engineering_dispatch(tasks_path=tasks_path, open_prs=open_prs)
    should_dispatch = dispatch.should_dispatch or sync_report.should_redispatch

    report = OpsMonitorReport(
        run_at=run_at,
        overall=_overall_status(findings),
        findings=findings,
        auto_fixes=auto_fixes,
        drafted_task_ids=drafted_ids,
        workflow_checks=workflow_checks,
        queue_status=queue_status,
        should_dispatch_engineering=should_dispatch,
        email_deferred=email_deferred,
        email_defer_reasons=email_defer_reasons,
    )

    status_path = Path(status_path)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(status_path, report.to_dict(), compact=False)

    from value_investor.backtest_health import run_backtest_health

    run_backtest_health(apply_repairs=False, status_path=BACKTEST_HEALTH_STATUS_PATH)

    return report


def append_monitor_log_entry(
    report: OpsMonitorReport,
    *,
    path: Path = DEFAULT_MONITOR_LOG_PATH,
    keep: int = MONITOR_LOG_KEEP,
) -> dict[str, Any]:
    path = Path(path)
    payload: dict[str, Any]
    if path.exists():
        try:
            payload = read_json(path)
        except (OSError, ValueError, TypeError):
            payload = {"entries": []}
    else:
        payload = {"entries": []}
    entries = list(payload.get("entries") or [])
    entries.append(
        {
            "run_at": report.run_at,
            "overall": report.overall,
            "finding_count": len(report.findings),
            "auto_fix_count": len(report.auto_fixes),
            "drafted_task_ids": report.drafted_task_ids,
            "should_dispatch_engineering": report.should_dispatch_engineering,
            "email_deferred": report.email_deferred,
            "email_defer_reasons": report.email_defer_reasons,
        }
    )
    payload["entries"] = entries[-max(1, int(keep)) :]
    payload["updated_at"] = datetime.now(UTC).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, payload, compact=False)
    return payload


def format_ops_monitor_text(report: OpsMonitorReport) -> str:
    lines = [
        f"FTSE Ops Monitor — {report.run_at}",
        f"Overall: {report.overall.upper()}",
        "",
    ]
    if report.email_deferred:
        lines.append("EMAIL DEFERRED — waiting on today's remaining slots / recovery")
        lines.append("-" * 40)
        for reason in report.email_defer_reasons:
            lines.append(f"  • {reason}")
        lines.append("")
    needs = findings_needing_investigation(report.findings)
    healed = [row for row in report.findings if row.fixed]
    if not report.findings:
        lines.append("No issues detected.")
    else:
        if needs:
            section = (
                "PENDING TODAY (email deferred)" if report.email_deferred else "NEEDS INVESTIGATION"
            )
            lines.append(section)
            lines.append("-" * 40)
            for row in needs:
                lines.append(f"[{row.severity.upper()}] {row.title}")
                lines.append(f"  {row.summary}")
                if row.action_taken:
                    lines.append(f"  Action: {row.action_taken}")
                lines.append("")
        if healed:
            lines.append("HEALED (auto-fixed / recovery in flight)")
            lines.append("-" * 40)
            for row in healed:
                lines.append(f"[FIXED] {row.title}")
                lines.append(f"  {row.summary}")
                if row.action_taken:
                    lines.append(f"  Action: {row.action_taken}")
                lines.append("")
        if not needs and not healed:
            lines.append("No issues detected.")
    if report.auto_fixes:
        lines.append("AUTO-FIXES APPLIED")
        lines.append("-" * 40)
        for row in report.auto_fixes:
            lines.append(f"  • {row.get('action')}: {row.get('detail')}")
        lines.append("")
    if report.drafted_task_ids:
        lines.append("DRAFTED ENGINEERING TASKS")
        lines.append("-" * 40)
        lines.append("  " + ", ".join(report.drafted_task_ids))
        lines.append("")
    if report.workflow_checks:
        lines.append("WORKFLOW FRESHNESS")
        lines.append("-" * 40)
        for row in report.workflow_checks:
            flag = "STALE" if row.get("stale") else "ok"
            lines.append(
                f"  [{flag}] {row.get('name')}: last success {row.get('last_success_at') or 'never'}"
            )
        lines.append("")
    if report.should_dispatch_engineering:
        lines.append("Engineering queue ready to dispatch the next supervised PR.")
    return "\n".join(lines).strip() + "\n"


def format_ops_monitor_html(report: OpsMonitorReport) -> str:
    severity_colors = {"fail": "#b33a3a", "warn": "#b8860b", "ok": "#1b7f3a"}
    needs = findings_needing_investigation(report.findings)
    healed = [row for row in report.findings if row.fixed]
    needs_rows = []
    for row in needs:
        color = severity_colors.get(row.severity, "#333")
        action = (
            f"<br><span style='color:#666;font-size:12px'>Action: {row.action_taken}</span>"
            if row.action_taken
            else ""
        )
        needs_rows.append(
            f"<li style='margin-bottom:10px'><strong style='color:{color}'>{row.severity.upper()}</strong> "
            f"{row.title}<br><span style='color:#555'>{row.summary}</span>{action}</li>"
        )
    healed_rows = []
    for row in healed:
        action = (
            f"<br><span style='color:#666;font-size:12px'>Action: {row.action_taken}</span>"
            if row.action_taken
            else ""
        )
        healed_rows.append(
            f"<li style='margin-bottom:10px'><strong style='color:{severity_colors['ok']}'>FIXED</strong> "
            f"{row.title}<br><span style='color:#555'>{row.summary}</span>{action}</li>"
        )
    fixes = "".join(
        f"<li>{item.get('action')}: {item.get('detail')}</li>" for item in report.auto_fixes
    )
    workflows = "".join(
        f"<li>{row.get('name')}: {row.get('last_success_at') or 'never'} "
        f"{'(stale)' if row.get('stale') else ''}</li>"
        for row in report.workflow_checks
    )
    needs_heading = (
        "Pending today (email deferred)" if report.email_deferred else "Needs investigation"
    )
    needs_block = (
        f"<h3>{needs_heading}</h3><ul>{''.join(needs_rows)}</ul>"
        if needs_rows
        else "<h3>Needs investigation</h3><ul><li>None — all detected issues were healed or suppressed.</li></ul>"
    )
    healed_block = f"<h3>Healed</h3><ul>{''.join(healed_rows)}</ul>" if healed_rows else ""
    defer_block = ""
    if report.email_deferred:
        defer_items = "".join(f"<li>{reason}</li>" for reason in report.email_defer_reasons)
        defer_block = (
            "<h3>Email deferred</h3>"
            "<p>Waiting on today's remaining scheduled slots / in-flight recovery. "
            "Afternoon catch-up will email only if issues remain.</p>"
            f"<ul>{defer_items}</ul>"
        )
    return f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;color:#222;max-width:720px">
  <h2>FTSE Ops Monitor</h2>
  <p style="color:#666">{report.run_at}</p>
  <p><strong>Overall:</strong> {report.overall.upper()}</p>
  {defer_block}
  {needs_block}
  {healed_block}
  {"<h3>Auto-fixes</h3><ul>" + fixes + "</ul>" if fixes else ""}
  {"<h3>Workflow freshness</h3><ul>" + workflows + "</ul>" if workflows else ""}
  {"<p><strong>Engineering queue ready</strong> for next supervised PR.</p>" if report.should_dispatch_engineering else ""}
</body></html>"""


def send_ops_monitor_email(
    report: OpsMonitorReport,
    *,
    config: EmailConfig | None = None,
    only_if_not_ok: bool = True,
) -> bool:
    """Email only when unfixed warn/fail remain after heal/re-verify.

    Skips when overall is ok, or when every remaining finding is still expected to
    clear later today (pre-slot Sunday workflows, recovery in flight, etc.).
    Auto-fixes alone do not trigger email — healed issues stay in ops_status.json.
    """
    if only_if_not_ok and report.email_deferred:
        logger.info(
            "Ops monitor email deferred (%s reason(s)) — afternoon catch-up will re-check",
            len(report.email_defer_reasons),
        )
        return False
    if only_if_not_ok and report.overall == "ok":
        logger.info("Ops monitor OK after heal/re-verify — skipping email")
        return False
    config = config or EmailConfig.from_env()
    subject = f"FTSE Ops Monitor — {report.overall.upper()}"
    send_report_email(
        subject=subject,
        text_body=format_ops_monitor_text(report),
        html_body=format_ops_monitor_html(report),
        config=config,
    )
    return True
