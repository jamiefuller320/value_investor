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
from value_investor.emailer import EmailConfig, send_report_email
from value_investor.engineering_recovery import recover_engineering_queue, summarize_parked_tasks
from value_investor.engineering_queue import (
    evaluate_engineering_dispatch,
    summarize_queue,
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
from value_investor.storage import read_json, write_json

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
        "max_age_hours": 3,
    },
    {
        "key": "analysis_review",
        "workflow": "analysis-review.yml",
        "weekdays": {6},
        "max_age_hours": 36,
    },
)

COMMITTED_JSON_PATHS: tuple[Path, ...] = (
    DEFAULT_HEALTH_LOG_PATH,
    DEFAULT_LATEST_PATH,
    COMMITTED_TASKS_PATH,
    Path("docs/data/paper_automation/last_run.json"),
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
        }


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
    remote = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER")
    name = os.environ.get("GITHUB_REPOSITORY", "").split("/")[-1] if "/" in os.environ.get("GITHUB_REPOSITORY", "") else None
    if owner and name:
        return f"{owner}/{name}"
    return None


def github_api_get(path: str, *, token: str | None = None) -> Any:
    token = token or _github_token()
    if not token:
        raise RuntimeError("GitHub token not configured (GITHUB_TOKEN / GH_TOKEN / GH_PAT)")
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


def list_open_pull_requests(*, repo: str | None = None, token: str | None = None) -> list[dict[str, Any]]:
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
    return findings


def check_latest_bundle(path: Path = DEFAULT_LATEST_PATH, *, max_age_hours: int = 168) -> list[OpsFinding]:
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


def check_workflow_freshness(
  *,
  repo: str | None = None,
  token: str | None = None,
  now: datetime | None = None,
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
        max_age = timedelta(hours=int(spec.get("max_age_hours") or 24))
        last_success = latest_workflow_run(workflow, repo=repo, token=token, status="success")
        last_run_at = _parse_github_time(str((last_success or {}).get("created_at") or ""))
        age = (now - last_run_at) if last_run_at else None
        stale = expected_today and (last_run_at is None or age > max_age)
        failures = recent_workflow_failures(workflow, repo=repo, token=token, within_hours=24)

        row = {
            "workflow": workflow,
            "name": schedule.get("name") or workflow,
            "expected_today": expected_today,
            "last_success_at": last_run_at.isoformat() if last_run_at else None,
            "last_success_run_id": (last_success or {}).get("id"),
            "age_hours": round(age.total_seconds() / 3600, 1) if age else None,
            "stale": stale,
            "recent_failures_24h": len(failures),
        }
        checks.append(row)

        if failures:
            run_ids = ", ".join(str(item.get("id")) for item in failures[:3])
            findings.append(
                OpsFinding(
                    severity="warn",
                    category="workflows",
                    title=f"Recent workflow failure: {row['name']}",
                    summary=f"{len(failures)} failure(s) in last 24h (runs: {run_ids}).",
                )
            )
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

    parked = summarize_parked_tasks(tasks_path)
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
        row
        for row in findings
        if row.severity == "fail" and not row.fixed and not row.auto_fixable
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

    corrupt_health = any(row.title == "Ingest health log is corrupt" for row in findings)
    if corrupt_health and apply and health_log_path.exists():
        backup = health_log_path.with_name(
            f"{health_log_path.stem}.corrupt.{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}{health_log_path.suffix}"
        )
        backup.write_bytes(health_log_path.read_bytes())
        payload = load_health_log_payload(health_log_path, backup_corrupt=False)
        write_json(health_log_path, {"entries": payload.get("entries") or [], "updated_at": datetime.now(UTC).isoformat()})
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

    return results


def _overall_status(findings: list[OpsFinding]) -> str:
    if any(row.severity == "fail" and not row.fixed for row in findings):
        return "fail"
    if any(row.severity in {"fail", "warn"} for row in findings):
        return "warn"
    return "ok"


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
    run_at = datetime.now(UTC).isoformat()
    findings: list[OpsFinding] = []

    if open_prs is None and _github_token():
        open_prs = list_open_pull_requests(repo=repo, token=token)

    findings.extend(check_committed_json())
    findings.extend(check_ingest_health_log(health_log_path))
    findings.extend(check_latest_bundle(latest_path))
    findings.extend(check_ops_budget())

    workflow_findings, workflow_checks = check_workflow_freshness(repo=repo, token=token)
    findings.extend(workflow_findings)

    engineering_findings, queue_status = check_engineering_queue(
        open_prs=open_prs,
        tasks_path=tasks_path,
    )
    findings.extend(engineering_findings)

    auto_fixes = apply_auto_fixes(
        findings,
        tasks_path=tasks_path,
        health_log_path=health_log_path,
        open_prs=open_prs,
        apply=apply_fixes,
    )

    drafted_ids: list[str] = []
    if draft_tasks and apply_fixes:
        drafted_ids = draft_ops_engineering_tasks(findings, tasks_path=tasks_path)

    dispatch = evaluate_engineering_dispatch(tasks_path=tasks_path, open_prs=open_prs)

    report = OpsMonitorReport(
        run_at=run_at,
        overall=_overall_status(findings),
        findings=findings,
        auto_fixes=auto_fixes,
        drafted_task_ids=drafted_ids,
        workflow_checks=workflow_checks,
        queue_status=queue_status,
        should_dispatch_engineering=dispatch.should_dispatch,
    )

    status_path = Path(status_path)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(status_path, report.to_dict(), compact=False)
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
    if not report.findings:
        lines.append("No issues detected.")
    else:
        lines.append("FINDINGS")
        lines.append("-" * 40)
        for row in report.findings:
            status = "FIXED" if row.fixed else row.severity.upper()
            lines.append(f"[{status}] {row.title}")
            lines.append(f"  {row.summary}")
            if row.action_taken:
                lines.append(f"  Action: {row.action_taken}")
            lines.append("")
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
    rows = []
    for row in report.findings:
        color = severity_colors.get("ok" if row.fixed else row.severity, "#333")
        label = "FIXED" if row.fixed else row.severity.upper()
        action = f"<br><span style='color:#666;font-size:12px'>Action: {row.action_taken}</span>" if row.action_taken else ""
        rows.append(
            f"<li style='margin-bottom:10px'><strong style='color:{color}'>{label}</strong> "
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
    return f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;color:#222;max-width:720px">
  <h2>FTSE Ops Monitor</h2>
  <p style="color:#666">{report.run_at}</p>
  <p><strong>Overall:</strong> {report.overall.upper()}</p>
  <h3>Findings</h3>
  <ul>{''.join(rows) if rows else '<li>No issues detected.</li>'}</ul>
  {'<h3>Auto-fixes</h3><ul>' + fixes + '</ul>' if fixes else ''}
  {'<h3>Workflow freshness</h3><ul>' + workflows + '</ul>' if workflows else ''}
  {'<p><strong>Engineering queue ready</strong> for next supervised PR.</p>' if report.should_dispatch_engineering else ''}
</body></html>"""


def send_ops_monitor_email(
    report: OpsMonitorReport,
    *,
    config: EmailConfig | None = None,
    only_if_not_ok: bool = True,
) -> bool:
    if only_if_not_ok and report.overall == "ok" and not report.auto_fixes:
        logger.info("Ops monitor OK — skipping email")
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
