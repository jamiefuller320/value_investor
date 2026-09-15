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
from value_investor.so_what_closure import apply_so_what_auto_queue
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
# Safe to workflow_dispatch when overdue past email-ready and no run is active.
# Keep this narrow: weekday live-path recoveries only (not Sunday quiet-bundle children).
AUTO_DISPATCH_OVERDUE_WORKFLOWS: frozenset[str] = frozenset(
    {
        "ingest-loop.yml",
        "paper-auto.yml",
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

DEFAULT_PAPER_DATA_ROOT = Path("docs/data/paper_automation")
LEARNING_TRACKS_SUMMARY_FILENAME = "learning_tracks_summary.json"
LEARNING_TRACKS_REVIEW_FILENAME = "learning_tracks_review.json"

COMMITTED_JSON_PATHS: tuple[Path, ...] = (
    DEFAULT_HEALTH_LOG_PATH,
    DEFAULT_LATEST_PATH,
    COMMITTED_TASKS_PATH,
    Path("docs/data/paper_automation/last_run.json"),
    Path("docs/data/paper_automation") / LEARNING_TRACKS_SUMMARY_FILENAME,
    Path("docs/data/paper_automation") / LEARNING_TRACKS_REVIEW_FILENAME,
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


def github_api_post(
    path: str,
    *,
    body: dict[str, Any],
    token: str | None = None,
) -> Any:
    token = token or _github_token()
    if not token:
        raise RuntimeError(
            "GitHub token not configured (WORKFLOW_DISPATCH_PAT / GITHUB_TOKEN / GH_TOKEN)"
        )
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8")
        if not raw.strip():
            return None
        return json.loads(raw)


def dispatch_workflow(
    workflow_file: str,
    *,
    ref: str = "main",
    inputs: dict[str, Any] | None = None,
    repo: str | None = None,
    token: str | None = None,
) -> None:
    """Trigger workflow_dispatch for a workflow file (204 on success)."""
    repo = repo or _github_repo() or "jamiefuller320/value_investor"
    token = resolve_workflow_dispatch_pat() or token or _github_token()
    if not token:
        raise RuntimeError(
            "GitHub token not configured (WORKFLOW_DISPATCH_PAT / GITHUB_TOKEN / GH_TOKEN)"
        )
    owner, name = repo.split("/", 1)
    github_api_post(
        f"/repos/{owner}/{name}/actions/workflows/{workflow_file}/dispatches",
        body={"ref": ref, "inputs": inputs or {}},
        token=token,
    )


def _workflow_file_for_overdue_title(title: str) -> str | None:
    if not title.startswith("Workflow overdue:"):
        return None
    schedule_name = title.removeprefix("Workflow overdue:").strip()
    for spec in MONITORED_WORKFLOWS:
        key = str(spec["key"])
        schedule = WORKFLOW_SCHEDULES.get(key, {})
        name = str(schedule.get("name") or spec["workflow"])
        if name == schedule_name:
            return str(spec["workflow"])
    return None


def _soften_overdue_finding(
    overdue: OpsFinding,
    *,
    workflow: str,
    key: str,
    now: datetime,
    repo: str | None,
    token: str | None,
) -> OpsFinding:
    """Suppress pending/in-flight overdue; mark safe workflows auto-fixable past ready."""
    if workflow == "ops-monitor.yml" and _running_inside_ops_monitor_workflow():
        overdue.fixed = True
        overdue.action_taken = "Current ops monitor run in progress; self-check suppressed"
        return overdue

    active = active_workflow_runs(workflow, repo=repo, token=token)
    if active:
        active_id = active[0].get("id")
        overdue.fixed = True
        overdue.action_taken = f"Recovery run in flight (#{active_id}); suppressed from alert"
        return overdue

    ready = WORKFLOW_EMAIL_READY_UTC.get(key)
    if ready is not None and (now.hour, now.minute) < ready:
        ready_h, ready_m = ready
        overdue.fixed = True
        overdue.action_taken = (
            f"Scheduled slot not reached yet "
            f"(email-ready after {ready_h:02d}:{ready_m:02d} UTC); suppressed"
        )
        return overdue

    if workflow in AUTO_DISPATCH_OVERDUE_WORKFLOWS:
        overdue.auto_fixable = True
    return overdue


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
    try:
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
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        logger.warning("active_workflow_runs(%s) failed: %s", workflow_file, exc)
        return []
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


def _running_inside_ops_monitor_workflow() -> bool:
    """True when this process is the FTSE Ops Monitor GitHub Actions job."""
    ref = os.environ.get("GITHUB_WORKFLOW_REF") or ""
    if "ops-monitor.yml" in ref:
        return True
    return os.environ.get("GITHUB_WORKFLOW") == "FTSE Ops Monitor"


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


def _paper_json_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def check_paper_learning_tracks(
    paper_root: Path = DEFAULT_PAPER_DATA_ROOT,
) -> list[OpsFinding]:
    """
    Structural weekday spot-check formerly done on the Automation tab.

    Confirms post-settle paper-auto artifacts and that decision-review covered
    the primary AI book, rules control, competing calibrated shadows, and the
    Suite B buy_tier_level cohort. Does **not** interpret excess vs ^FTSE —
    that stays the Sunday analysis-review / promotion gates.
    """
    from value_investor.knob_calibration import (
        calibrated_shadow_track_id,
        discover_calibration_shadow_ranks,
    )
    from value_investor.paper_auto_scheduling import (
        LAST_RUN_FILENAME,
        last_run_after_settle,
        load_last_run,
    )
    from value_investor.paper_automation import (
        AI_JUDGMENT_TRACK_ID,
        BUY_TIER_LEVEL_SUBDIR,
        BUY_TIER_LEVEL_TRACK_ID,
        FUND_FILENAME,
        RULES_TRACK_ID,
    )

    root = Path(paper_root)
    findings: list[OpsFinding] = []
    core_track_ids = (RULES_TRACK_ID, AI_JUDGMENT_TRACK_ID, BUY_TIER_LEVEL_TRACK_ID)

    if not root.exists():
        findings.append(
            OpsFinding(
                severity="warn",
                category="paper",
                title="Paper automation root missing",
                summary=f"{root.as_posix()} not found — weekday paper-auto has not published yet.",
            )
        )
        return findings

    last_run = load_last_run(root / LAST_RUN_FILENAME)
    if last_run is None:
        findings.append(
            OpsFinding(
                severity="warn",
                category="paper",
                title="Paper-auto last_run.json missing",
                summary=f"Expected {(root / LAST_RUN_FILENAME).as_posix()} after weekday paper-auto.",
            )
        )
    elif not last_run_after_settle(last_run):
        findings.append(
            OpsFinding(
                severity="warn",
                category="paper",
                title="Paper-auto last_run is pre-settle only",
                summary=(
                    "Committed last_run.json has gate.after_settle=false — orchestrator "
                    "should re-dispatch a post-settle pass."
                ),
            )
        )

    summary = _paper_json_payload(root / LEARNING_TRACKS_SUMMARY_FILENAME)
    if summary is None:
        findings.append(
            OpsFinding(
                severity="fail",
                category="paper",
                title="Learning-tracks summary missing",
                summary=(
                    f"{(root / LEARNING_TRACKS_SUMMARY_FILENAME).as_posix()} missing or unreadable "
                    "— weekday paper-auto did not publish a track rollup."
                ),
            )
        )
        summary_tracks: dict[str, Any] = {}
    else:
        summary_tracks = summary.get("tracks") if isinstance(summary.get("tracks"), dict) else {}
        missing_summary = [
            track_id for track_id in core_track_ids if track_id not in summary_tracks
        ]
        if missing_summary:
            findings.append(
                OpsFinding(
                    severity="fail",
                    category="paper",
                    title="Learning-tracks summary missing core tracks",
                    summary=(
                        "paper-auto rollup omitted "
                        + ", ".join(missing_summary)
                        + " (need rules, ai_judgment, buy_tier_level)."
                    ),
                )
            )
        if last_run is not None and last_run_after_settle(last_run):
            skipped = [
                track_id
                for track_id in core_track_ids
                if track_id in summary_tracks
                and not bool((summary_tracks.get(track_id) or {}).get("acted"))
            ]
            if skipped:
                findings.append(
                    OpsFinding(
                        severity="warn",
                        category="paper",
                        title="Core learning tracks did not act",
                        summary=(
                            "Post-settle paper-auto left acted=false for "
                            + ", ".join(skipped)
                            + "."
                        ),
                    )
                )

    review = _paper_json_payload(root / LEARNING_TRACKS_REVIEW_FILENAME)
    if review is None:
        findings.append(
            OpsFinding(
                severity="fail",
                category="paper",
                title="Learning-tracks review missing",
                summary=(
                    f"{(root / LEARNING_TRACKS_REVIEW_FILENAME).as_posix()} missing or unreadable "
                    "— decision-review did not publish the Automation-tab comparison."
                ),
            )
        )
        reviews: dict[str, Any] = {}
    else:
        reviews = review.get("reviews") if isinstance(review.get("reviews"), dict) else {}
        missing_review = [track_id for track_id in core_track_ids if track_id not in reviews]
        if missing_review:
            findings.append(
                OpsFinding(
                    severity="fail",
                    category="paper",
                    title="Learning-tracks review missing core tracks",
                    summary=(
                        "decision-review omitted "
                        + ", ".join(missing_review)
                        + " (need AI judgment, rules control, Suite B buy_tier_level)."
                    ),
                )
            )

    shadow_ids = [
        calibrated_shadow_track_id(rank) for rank in discover_calibration_shadow_ranks(root)
    ]
    missing_shadows = [
        track_id
        for track_id in shadow_ids
        if track_id in summary_tracks and track_id not in reviews
    ]
    if review is not None and missing_shadows:
        findings.append(
            OpsFinding(
                severity="fail",
                category="paper",
                title="Calibrated shadows missing from decision-review",
                summary=(
                    "Competing calibrated shadows ran in paper-auto but were omitted from "
                    "learning_tracks_review: " + ", ".join(missing_shadows) + "."
                ),
            )
        )

    buy_tier_row = summary_tracks.get(BUY_TIER_LEVEL_TRACK_ID) or {}
    if isinstance(buy_tier_row, dict) and buy_tier_row.get("acted"):
        fund = _paper_json_payload(root / BUY_TIER_LEVEL_SUBDIR / FUND_FILENAME)
        holdings = fund.get("holdings") if isinstance(fund, dict) else None
        if not isinstance(holdings, dict) or not holdings:
            findings.append(
                OpsFinding(
                    severity="fail",
                    category="paper",
                    title="Buy-tier level cohort empty after acted pass",
                    summary=(
                        "buy_tier_level acted but automated_fund.json has no holdings — "
                        "Monday cold start should fill the wide raw-screen Suite B book. "
                        "Do not treat first-fill NAV as promotion truth."
                    ),
                )
            )

    return findings


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
            overdue = OpsFinding(
                severity="fail" if expected_today else "warn",
                category="workflows",
                title=f"Workflow overdue: {row['name']}",
                summary=(
                    f"No successful run within {int(max_age.total_seconds() // 3600)}h "
                    f"(last: {last_run_at.isoformat() if last_run_at else 'never'})."
                ),
            )
            overdue = _soften_overdue_finding(
                overdue,
                workflow=workflow,
                key=key,
                now=now,
                repo=repo,
                token=token,
            )
            findings.append(overdue)

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


def _is_orphaned_pr_open_task(row: dict[str, Any], open_prs: list[dict[str, Any]] | None) -> bool:
    """True when pr_open has no matching open GitHub PR (or no recorded PR when PR list omitted)."""
    if str(row.get("status") or "") != "pr_open":
        return False
    branch = str(row.get("branch_name") or "").strip()
    if open_prs is not None:
        if branch and any(
            str(pr.get("headRefName") or pr.get("head_branch") or "").strip() == branch
            for pr in open_prs
        ):
            return False
        return True
    if row.get("pr_url") or row.get("pr_number"):
        return False
    return True


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
        if _is_orphaned_pr_open_task(row, open_prs)
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


def check_memo_rememo_backlog() -> list[OpsFinding]:
    """Flag when body-lag rememo backlog exceeds in-week maintenance capacity."""
    from value_investor.research.weekday_rememo import assess_rememo_backlog

    try:
        assessment = assess_rememo_backlog()
    except (OSError, ValueError, TypeError) as exc:
        return [
            OpsFinding(
                severity="warn",
                category="research",
                title="Memo rememo backlog assessment failed",
                summary=str(exc),
            )
        ]

    count = int(assessment.get("backlog_count") or 0)
    capacity = int(assessment.get("weekly_maintenance_capacity") or 0)
    action = str(assessment.get("action") or "none")
    if count <= 0 or not assessment.get("over_weekly_capacity"):
        return []

    weeks = assessment.get("weeks_to_clear_at_maintenance")
    summary = (
        f"{count} memo(s) need rememo vs in-week capacity {capacity} "
        f"(~{weeks} week(s) at weekday maintenance). action={action}."
    )
    if action == "escalate":
        return [
            OpsFinding(
                severity="fail",
                category="research",
                title="Memo rememo backlog exceeds in-week capacity (budget blocked)",
                summary=summary,
                auto_fixable=False,
            )
        ]
    return [
        OpsFinding(
            severity="fail",
            category="research",
            title="Memo rememo backlog exceeds in-week capacity",
            summary=summary,
            auto_fixable=True,
        )
    ]


def check_phase_b_producer_progress(
    research_root: Path = Path("docs/data/research"),
    *,
    min_structured: int = 3,
) -> list[OpsFinding]:
    """Flag when Phase C readiness is blocked because structured-verdict modes never land.

    Does not widen weekday rememo_reason (Phase B lock). Surfaces the stall so
    ops/eng can fix Sunday seed→persist or run a bounded rememo catch-up.
    """
    from value_investor.phase_c_readiness import (
        MIN_STRUCTURED_DOCS,
        STRUCTURED_VERDICT_MODES,
        check_phase_b_slim,
    )

    threshold = max(int(min_structured), int(MIN_STRUCTURED_DOCS))
    try:
        check = check_phase_b_slim(research_root)
    except (OSError, ValueError, TypeError) as exc:
        return [
            OpsFinding(
                severity="warn",
                category="research",
                title="Phase B producer progress check failed",
                summary=str(exc),
            )
        ]

    if check.status == "pass":
        return []

    evidence = check.evidence or {}
    structured = int(evidence.get("structured_docs") or 0)
    sampled = int(evidence.get("sampled_docs") or 0)
    modes = ", ".join(sorted(STRUCTURED_VERDICT_MODES))
    severity = "fail" if structured == 0 else "warn"
    return [
        OpsFinding(
            severity=severity,
            category="research",
            title="Phase B structured-verdict producer stalled",
            summary=(
                f"{check.detail} "
                f"({structured} structured / need ≥{threshold}; sampled={sampled}; "
                f"modes={modes}). Sunday research-docs must seed committed memos into "
                f"output/, write structured_verdict* updates, and persist back to "
                f"docs/data/research — do not widen rememo_reason for mode migration."
            ),
            auto_fixable=structured == 0,
        )
    ]


def check_indicator_integrity(
    *,
    research_root: Path = Path("docs/data/research"),
    receipt_path: Path = Path("docs/data/research_docs_receipt.json"),
) -> list[OpsFinding]:
    """L389: claimed-vs-landed checks for false-green indicators."""
    from value_investor.indicator_integrity import evaluate_indicator_integrity

    try:
        raw = evaluate_indicator_integrity(
            research_root=research_root,
            receipt_path=receipt_path,
        )
    except (OSError, ValueError, TypeError) as exc:
        return [
            OpsFinding(
                severity="warn",
                category="research",
                title="Indicator integrity check failed",
                summary=str(exc),
            )
        ]

    findings: list[OpsFinding] = []
    for row in raw:
        severity = "fail" if row.severity == "fail" else "warn"
        findings.append(
            OpsFinding(
                severity=severity,
                category="research",
                title=row.title,
                summary=f"[{row.check_id}] {row.summary}",
                auto_fixable=False,
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
    repo: str | None = None,
    token: str | None = None,
    apply: bool = True,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    if apply:
        recovery = recover_engineering_queue(
            tasks_path=tasks_path,
            open_prs=open_prs,
            apply=True,
        )
        if recovery.merged:
            action = f"marked merged from GitHub PR: {', '.join(recovery.merged)}"
            results.append({"action": "recover_engineering_queue", "detail": action})
            for finding in findings:
                if finding.title.startswith("Orphaned pr_open"):
                    finding.fixed = True
                    finding.action_taken = action
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

    phase_b_stalled = any(
        row.title == "Phase B structured-verdict producer stalled" and not row.fixed
        for row in findings
    )
    if phase_b_stalled and apply:
        from value_investor.email_agent import repair_published_structured_verdict_to_committed
        from value_investor.phase_c_readiness import MIN_STRUCTURED_DOCS

        repaired = repair_published_structured_verdict_to_committed()
        if repaired:
            action = (
                f"landed {repaired} published Phase B memo(s) into docs/data/research "
                "(docs/research → committed store)"
            )
            results.append({"action": "repair_phase_b_published_memos", "detail": action})
            for finding in findings:
                if finding.title != "Phase B structured-verdict producer stalled":
                    continue
                if repaired >= MIN_STRUCTURED_DOCS:
                    finding.fixed = True
                    finding.action_taken = action
                else:
                    finding.action_taken = (
                        f"{action}; still below ≥{MIN_STRUCTURED_DOCS} structured modes"
                    )

    rememo_over = any(
        row.title == "Memo rememo backlog exceeds in-week capacity" and not row.fixed
        for row in findings
    )
    if rememo_over and apply:
        from value_investor.research.weekday_rememo import write_rememo_backlog_status

        status = write_rememo_backlog_status()
        request = status.get("catchup_request") or {}
        elevated = request.get("elevated_cap")
        action = (
            f"wrote memo rememo catch-up request "
            f"(backlog={status.get('backlog_count')}, elevated_cap={elevated})"
        )
        results.append({"action": "activate_memo_rememo_catchup", "detail": action})
        for finding in findings:
            if finding.title == "Memo rememo backlog exceeds in-week capacity":
                finding.fixed = True
                finding.action_taken = action

    if apply:
        for finding in findings:
            if finding.fixed or not finding.auto_fixable:
                continue
            if not finding.title.startswith("Workflow overdue:"):
                continue
            workflow_file = _workflow_file_for_overdue_title(finding.title)
            if not workflow_file or workflow_file not in AUTO_DISPATCH_OVERDUE_WORKFLOWS:
                finding.auto_fixable = False
                continue
            active = active_workflow_runs(workflow_file, repo=repo, token=token)
            if active:
                active_id = active[0].get("id")
                finding.fixed = True
                finding.action_taken = (
                    f"Recovery run in flight (#{active_id}); suppressed from alert"
                )
                continue
            try:
                dispatch_workflow(workflow_file, repo=repo, token=token)
            except Exception as exc:  # noqa: BLE001 — leave supervised on dispatch failure
                logger.warning("Failed to dispatch overdue %s: %s", workflow_file, exc)
                finding.auto_fixable = False
                finding.action_taken = f"auto-dispatch failed: {exc}"
                continue
            action = f"dispatched {workflow_file} recovery run"
            results.append(
                {
                    "action": "dispatch_overdue_workflow",
                    "workflow": workflow_file,
                    "detail": action,
                }
            )
            finding.fixed = True
            finding.action_taken = action

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

    if finding.category == "paper" and now.weekday() < 5:
        ready_h, ready_m = WORKFLOW_EMAIL_READY_UTC["paper_auto"]
        if (now.hour, now.minute) < (ready_h, ready_m):
            return (
                "paper-auto scheduled slot not reached yet "
                f"(email-ready after {ready_h:02d}:{ready_m:02d} UTC)"
            )

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
    findings.extend(check_memo_rememo_backlog())
    findings.extend(check_phase_b_producer_progress())
    findings.extend(check_indicator_integrity())
    findings.extend(check_backtest_history())
    findings.extend(check_paper_learning_tracks())

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
        repo=repo,
        token=token,
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
        # Immediate re-verify may still see age-based overdue before GitHub shows
        # the dispatched run as active — keep those findings healed.
        dispatched = {
            str(row.get("workflow") or "")
            for row in auto_fixes
            if row.get("action") == "dispatch_overdue_workflow" and row.get("workflow")
        }
        if dispatched:
            for finding in findings:
                if finding.fixed or not finding.title.startswith("Workflow overdue:"):
                    continue
                workflow_file = _workflow_file_for_overdue_title(finding.title)
                if workflow_file and workflow_file in dispatched:
                    finding.fixed = True
                    finding.auto_fixable = True
                    finding.action_taken = f"dispatched {workflow_file} recovery run"

    try:
        from value_investor.project_traffic import run_project_traffic

        traffic_report = run_project_traffic(
            tasks_path=tasks_path,
            open_prs=open_prs,
            repo=repo,
            token=token,
            apply=apply_fixes,
            write_digest=True,
        )
        if traffic_report.pause_active:
            findings.append(
                OpsFinding(
                    severity="warn",
                    category="engineering",
                    title="Project traffic pause active",
                    summary=(
                        f"{len(traffic_report.stuck_prs)} stuck PR(s); "
                        f"reasons={traffic_report.pause_reasons or ['stuck_prs']}. "
                        "New engineering-agent dispatch is held until CI/conflicts clear."
                        + (
                            " Escalation agent queued after first-line exhaustion."
                            if traffic_report.should_dispatch_escalation_agent
                            else ""
                        )
                    ),
                    auto_fixable=False,
                )
            )
        for action in traffic_report.actions:
            if action.applied or action.kind in {
                "pause_dispatch",
                "resume_dispatch",
                "dispatch_unstick_escalation",
            }:
                auto_fixes.append(
                    {
                        "action": f"traffic_{action.kind}",
                        "detail": action.detail,
                        "pr_number": action.pr_number,
                        "branch": action.branch,
                    }
                )
    except Exception:  # noqa: BLE001 — traffic controller must not fail ops monitor
        logger.exception("project traffic controller failed")

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

    if draft_tasks and apply_fixes:
        so_what_snapshot = apply_so_what_auto_queue(
            dry_run=False,
            tasks_path=tasks_path,
            latest_path=latest_path,
            artifacts_dir=Path("docs/data"),
            snapshot_path=Path("docs/data/so_what_closure.json"),
        )
        created = so_what_snapshot.get("created_tasks") or []
        if created:
            drafted_ids = list(drafted_ids) + [
                str(row.get("task_id") or "") for row in created if row.get("task_id")
            ]
            auto_fixes.append(
                {
                    "action": "so_what_auto_queue",
                    "detail": (
                        f"queued {len(created)} enforcement gap(s); "
                        f"human_gate="
                        f"{((so_what_snapshot.get('counts') or {}).get('human_gate') or 0)}"
                    ),
                }
            )

        from value_investor.idle_compile_backstop import run_idle_compile_backstop

        backstop = run_idle_compile_backstop(
            apply=True,
            tasks_path=tasks_path,
            output_dir=Path("output"),
            latest_path=latest_path,
        )
        compile_result = backstop.get("compile") or {}
        if backstop.get("applied") and int(compile_result.get("added_open_count") or 0) > 0:
            auto_fixes.append(
                {
                    "action": "idle_compile_backstop",
                    "detail": (
                        f"compiled {compile_result.get('added_open_count')} open task(s) from "
                        f"post-run plan: {', '.join(compile_result.get('added_open_task_ids') or [])}"
                    ),
                }
            )
            drafted_ids = list(drafted_ids) + list(compile_result.get("added_open_task_ids") or [])

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

    try:
        from value_investor.queue_health import refresh_queue_health_ui

        refresh_queue_health_ui(open_prs=open_prs)
    except Exception:  # noqa: BLE001 — dashboard slice must not fail ops monitor
        pass

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


def _workflow_freshness_visual(row: dict[str, Any]) -> dict[str, str]:
    """Email-safe colours for one workflow freshness row."""
    stale = bool(row.get("stale"))
    expected = bool(row.get("expected_today"))
    unresolved = int(row.get("unresolved_failures_12h") or 0)
    if stale and expected:
        return {"label": "STALE", "fg": "#9b2c2c", "bg": "#fde8e8", "border": "#e8b4b4"}
    if stale:
        return {"label": "STALE", "fg": "#8a6d00", "bg": "#fff8e6", "border": "#e6d18a"}
    if unresolved:
        return {"label": "FAILURES", "fg": "#8a6d00", "bg": "#fff8e6", "border": "#e6d18a"}
    if expected:
        return {"label": "OK", "fg": "#1b7f3a", "bg": "#e8f5ec", "border": "#b8dfc4"}
    return {"label": "OK", "fg": "#555555", "bg": "#f4f4f4", "border": "#dddddd"}


def _workflow_freshness_notes(row: dict[str, Any]) -> str:
    parts: list[str] = []
    if row.get("stale"):
        parts.append("overdue")
    unresolved = int(row.get("unresolved_failures_12h") or 0)
    if unresolved:
        parts.append(f"{unresolved} unresolved failure(s)")
    if not row.get("expected_today"):
        parts.append("not scheduled today")
    return "; ".join(parts)


def format_workflow_freshness_html(rows: list[dict[str, Any]]) -> str:
    """Colour-coded workflow freshness table for ops-monitor email."""
    if not rows:
        return ""
    header = (
        "<table style='border-collapse:collapse;width:100%;font-size:13px;margin-top:8px'>"
        "<thead><tr style='background:#f0f0f0;text-align:left'>"
        "<th style='padding:6px 8px;border:1px solid #ddd'>Status</th>"
        "<th style='padding:6px 8px;border:1px solid #ddd'>Workflow</th>"
        "<th style='padding:6px 8px;border:1px solid #ddd'>Last success</th>"
        "<th style='padding:6px 8px;border:1px solid #ddd'>Age</th>"
        "<th style='padding:6px 8px;border:1px solid #ddd'>Limit</th>"
        "<th style='padding:6px 8px;border:1px solid #ddd'>Notes</th>"
        "</tr></thead><tbody>"
    )
    body_rows: list[str] = []
    for row in rows:
        visual = _workflow_freshness_visual(row)
        age = row.get("age_hours")
        age_text = f"{age}h" if age is not None else "—"
        if row.get("expected_today"):
            limit_text = f"{row.get('max_age_hours')}h"
        else:
            limit_text = "—"
        notes = _workflow_freshness_notes(row)
        notes_cell = notes or "—"
        last_at = row.get("last_success_at") or "never"
        body_rows.append(
            f"<tr style='background:{visual['bg']};color:#222'>"
            f"<td style='padding:6px 8px;border:1px solid {visual['border']};"
            f"font-weight:bold;color:{visual['fg']};white-space:nowrap'>{visual['label']}</td>"
            f"<td style='padding:6px 8px;border:1px solid {visual['border']}'>{row.get('name')}</td>"
            f"<td style='padding:6px 8px;border:1px solid {visual['border']};"
            f"font-family:monospace;font-size:12px'>{last_at}</td>"
            f"<td style='padding:6px 8px;border:1px solid {visual['border']}'>{age_text}</td>"
            f"<td style='padding:6px 8px;border:1px solid {visual['border']}'>{limit_text}</td>"
            f"<td style='padding:6px 8px;border:1px solid {visual['border']};color:#555'>"
            f"{notes_cell}</td></tr>"
        )
    return header + "".join(body_rows) + "</tbody></table>"


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
    try:
        from value_investor.engineering_narrow_merge import list_todays_engineering_merges

        merges_today = list_todays_engineering_merges()
    except Exception:  # noqa: BLE001 — email formatting must not crash the monitor
        merges_today = []
    if merges_today:
        lines.append("ENGINEERING MERGES TODAY (independent verify monitor)")
        lines.append("-" * 40)
        for row in merges_today:
            pr = row.get("pr_number")
            pr_bit = f"PR #{pr} " if pr else ""
            verified = "verified" if row.get("independently_verified") else "human"
            lines.append(
                f"  • [{row.get('merge_class')}/{verified}] {pr_bit}"
                f"{row.get('task_id')}: {row.get('title')}"
            )
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
            visual = _workflow_freshness_visual(row)
            flag = visual["label"]
            notes = _workflow_freshness_notes(row)
            age = row.get("age_hours")
            age_part = f", age {age}h" if age is not None else ""
            note_part = f" ({notes})" if notes else ""
            lines.append(
                f"  [{flag}] {row.get('name')}: last success "
                f"{row.get('last_success_at') or 'never'}{age_part}{note_part}"
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
    workflows = format_workflow_freshness_html(report.workflow_checks)
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
    try:
        from value_investor.engineering_narrow_merge import list_todays_engineering_merges

        merges_today = list_todays_engineering_merges()
    except Exception:  # noqa: BLE001
        merges_today = []
    if merges_today:
        merge_items = []
        for row in merges_today:
            pr = row.get("pr_number")
            pr_bit = f"PR #{pr} — " if pr else ""
            verified = "verified" if row.get("independently_verified") else "human"
            merge_items.append(
                "<li><code>"
                f"{row.get('merge_class')}/{verified}</code> {pr_bit}"
                f"{row.get('task_id')}: {row.get('title')}</li>"
            )
        merges_html = (
            "<h3>Engineering merges today (independent verify monitor)</h3>"
            f"<ul>{''.join(merge_items)}</ul>"
        )
    else:
        merges_html = ""
    return f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;color:#222;max-width:720px">
  <h2>FTSE Ops Monitor</h2>
  <p style="color:#666">{report.run_at}</p>
  <p><strong>Overall:</strong> {report.overall.upper()}</p>
  {defer_block}
  {needs_block}
  {healed_block}
  {"<h3>Auto-fixes</h3><ul>" + fixes + "</ul>" if fixes else ""}
  {merges_html}
  {"<h3>Workflow freshness</h3>" + workflows if workflows else ""}
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
