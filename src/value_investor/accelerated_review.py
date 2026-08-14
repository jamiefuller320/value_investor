"""Mid-week accelerated review: chain email_only after engineering queue drains (L97)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import (
    DEFAULT_WEEKLY_OPS_CAP_USD,
    load_policy,
    weekly_ops_budget_status,
)
from value_investor.engineering_queue import EngineeringQueueStatus, summarize_queue
from value_investor.engineering_tasks import COMMITTED_TASKS_PATH, find_engineering_task
from value_investor.ops_monitor import _github_repo, _github_token, active_workflow_runs
from value_investor.storage import read_json, write_json

logger = logging.getLogger(__name__)

DEFAULT_LOG_PATH = Path("docs/data/accelerated_review.json")
DEFAULT_LATEST_PATH = Path("docs/data/latest.json")
DEFAULT_MIN_HEADROOM_USD = 18.0
DEFAULT_ESTIMATED_EMAIL_ONLY_USD = 18.0
DEFAULT_MAX_MIDWEEK_PER_WEEK = 2
DEFAULT_MAX_MIDWEEK_LADDER_PER_WEEK = 1
DEFAULT_MAX_WEDNESDAY_ANCHOR_PER_WEEK = 1
DEFAULT_SCREEN_STALE_HOURS = 48.0
DEFAULT_WEDNESDAY_ANCHOR_MIN_UTC_HOUR = 10
WEDNESDAY_ANCHOR_SOURCE = "wednesday_anchor"
MATERIAL_MERGE_AREAS = frozenset({"ingest", "scoring", "prompt", "coverage"})
LADDER_CHAIN_AREAS = frozenset({"coverage"})


@dataclass
class AcceleratedDispatchDecision:
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


AcceleratedEmailDecision = AcceleratedDispatchDecision


def _iso_week_key(moment: datetime) -> str:
    iso = moment.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def load_accelerated_review_log(path: Path = DEFAULT_LOG_PATH) -> dict[str, Any]:
    empty = {
        "schema_version": 1,
        "midweek_email_only_runs": [],
        "midweek_ladder_runs": [],
    }
    if not path.exists():
        return dict(empty)
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return dict(empty)
    if not isinstance(payload, dict):
        return dict(empty)
    payload.setdefault("schema_version", 1)
    payload.setdefault("midweek_email_only_runs", [])
    payload.setdefault("midweek_ladder_runs", [])
    return payload


def _runs_this_iso_week(
    rows: list[Any],
    *,
    now: datetime,
    source_filter: frozenset[str] | None = None,
) -> int:
    week_key = _iso_week_key(now)
    count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if source_filter is not None and str(row.get("source") or "") not in source_filter:
            continue
        at = str(row.get("at") or "")
        try:
            stamp = datetime.fromisoformat(at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if _iso_week_key(stamp) == week_key:
            count += 1
    return count


def midweek_email_only_count(
    *,
    log_path: Path = DEFAULT_LOG_PATH,
    now: datetime | None = None,
) -> int:
    """Eng-chain reactive dispatches this ISO week (excludes wednesday_anchor)."""
    now = now or datetime.now(UTC)
    rows = load_accelerated_review_log(log_path).get("midweek_email_only_runs") or []
    count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source") or "")
        if source == WEDNESDAY_ANCHOR_SOURCE:
            continue
        at = str(row.get("at") or "")
        try:
            stamp = datetime.fromisoformat(at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if _iso_week_key(stamp) == _iso_week_key(now):
            count += 1
    return count


def wednesday_anchor_count(
    *,
    log_path: Path = DEFAULT_LOG_PATH,
    now: datetime | None = None,
) -> int:
    now = now or datetime.now(UTC)
    rows = load_accelerated_review_log(log_path).get("midweek_email_only_runs") or []
    return _runs_this_iso_week(rows, now=now, source_filter=frozenset({WEDNESDAY_ANCHOR_SOURCE}))


def midweek_ladder_count(
    *,
    log_path: Path = DEFAULT_LOG_PATH,
    now: datetime | None = None,
) -> int:
    now = now or datetime.now(UTC)
    rows = load_accelerated_review_log(log_path).get("midweek_ladder_runs") or []
    return _runs_this_iso_week(rows, now=now)


def record_midweek_ladder_run(
    *,
    source: str,
    log_path: Path = DEFAULT_LOG_PATH,
    merged_task_id: str | None = None,
    note: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    payload = load_accelerated_review_log(log_path)
    stamp = (now or datetime.now(UTC)).isoformat()
    entry: dict[str, Any] = {
        "at": stamp,
        "source": source,
    }
    if merged_task_id:
        entry["merged_task_id"] = merged_task_id
    if note:
        entry["note"] = note
    rows = list(payload.get("midweek_ladder_runs") or [])
    rows.append(entry)
    payload["midweek_ladder_runs"] = rows[-50:]
    payload["last_midweek_ladder_at"] = entry["at"]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(log_path, payload, compact=False)
    return entry


def record_midweek_email_only_run(
    *,
    source: str,
    log_path: Path = DEFAULT_LOG_PATH,
    merged_task_id: str | None = None,
    note: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    payload = load_accelerated_review_log(log_path)
    stamp = (now or datetime.now(UTC)).isoformat()
    entry: dict[str, Any] = {
        "at": stamp,
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
    if source == WEDNESDAY_ANCHOR_SOURCE:
        payload["last_wednesday_anchor_at"] = entry["at"]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(log_path, payload, compact=False)
    return entry


def screen_run_age_hours(
    *,
    latest_path: Path = DEFAULT_LATEST_PATH,
    now: datetime | None = None,
) -> float | None:
    """Hours since latest.json screen run_at; None when unavailable."""
    now = now or datetime.now(UTC)
    if not latest_path.exists():
        return None
    try:
        payload = read_json(latest_path)
    except (OSError, ValueError, TypeError):
        return None
    run_at = str(payload.get("run_at") or "").strip()
    if not run_at:
        return None
    try:
        stamp = datetime.fromisoformat(run_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return (now - stamp).total_seconds() / 3600.0


def ingest_loop_materiality(
    ingest_loop: dict[str, Any] | None,
) -> tuple[bool, dict[str, Any]]:
    """Whether a weekday ingest-loop run materially changed filing coverage."""
    if not ingest_loop:
        return False, {"ingest_loop_present": False}

    before = ingest_loop.get("health_before") or {}
    after = ingest_loop.get("health_after") or {}
    delta_filings_with_body = int(after.get("filings_with_body") or 0) - int(
        before.get("filings_with_body") or 0
    )
    delta_indexed_without_body = int(before.get("indexed_without_body") or 0) - int(
        after.get("indexed_without_body") or 0
    )
    delta_zero_body = int(before.get("zero_body_buy_tier") or 0) - int(
        after.get("zero_body_buy_tier") or 0
    )
    summary = ingest_loop.get("ingest_summary") or {}
    improved_tickers = [
        str(row.get("ticker"))
        for row in (summary.get("results") or [])
        if row.get("improved") and row.get("ticker")
    ]
    checks = {
        "ingest_loop_present": True,
        "delta_filings_with_body": delta_filings_with_body,
        "delta_indexed_without_body": delta_indexed_without_body,
        "delta_zero_body_buy_tier": delta_zero_body,
        "improved_ticker_count": len(improved_tickers),
        "micro_compiled": bool(ingest_loop.get("micro_compiled")),
        "gap_closure_compiled": bool(ingest_loop.get("gap_closure_compiled")),
    }
    material = (
        delta_filings_with_body > 0
        or delta_indexed_without_body > 0
        or delta_zero_body > 0
        or len(improved_tickers) > 0
    )
    return material, checks


def _budget_guard(
    *,
    policy_path: Path | None,
    checks: dict[str, Any],
    min_headroom_usd: float,
    estimated_cost_usd: float,
) -> AcceleratedEmailDecision | None:
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
    return None


def _active_workflow_guard(
    *,
    repo: str | None,
    token: str | None,
    checks: dict[str, Any],
) -> AcceleratedEmailDecision | None:
    if not repo or not token:
        return None
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
    return None


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

    blocked = _budget_guard(
        policy_path=policy_path,
        checks=checks,
        min_headroom_usd=min_headroom_usd,
        estimated_cost_usd=estimated_cost_usd,
    )
    if blocked is not None:
        return blocked

    midweek_count = midweek_email_only_count(log_path=log_path, now=now)
    checks["midweek_email_only_this_week"] = midweek_count
    checks["max_midweek_per_week"] = max_midweek_per_week
    if midweek_count >= max_midweek_per_week:
        return AcceleratedEmailDecision(
            should_dispatch=False,
            reason=f"mid-week email_only cap reached ({midweek_count}/{max_midweek_per_week})",
            checks=checks,
        )

    blocked = _active_workflow_guard(repo=repo, token=token, checks=checks)
    if blocked is not None:
        return blocked

    return AcceleratedEmailDecision(
        should_dispatch=True,
        reason="queue idle after material merge — chain email_only refresh",
        checks=checks,
    )


def evaluate_wednesday_anchor_dispatch(
    *,
    queue_status: EngineeringQueueStatus | None = None,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    policy_path: Path | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
    latest_path: Path = DEFAULT_LATEST_PATH,
    ingest_loop: dict[str, Any] | None = None,
    repo: str | None = None,
    token: str | None = None,
    now: datetime | None = None,
    min_headroom_usd: float = DEFAULT_MIN_HEADROOM_USD,
    estimated_cost_usd: float = DEFAULT_ESTIMATED_EMAIL_ONLY_USD,
    max_per_week: int = DEFAULT_MAX_WEDNESDAY_ANCHOR_PER_WEEK,
    screen_stale_hours: float = DEFAULT_SCREEN_STALE_HOURS,
    min_utc_hour: int = DEFAULT_WEDNESDAY_ANCHOR_MIN_UTC_HOUR,
) -> AcceleratedEmailDecision:
    """
    Wednesday anchor: scheduled email_only after weekday ingest (does not count
    toward the eng-chain midweek cap).
    """
    now = now or datetime.now(UTC)
    repo = repo or _github_repo()
    token = token or _github_token()
    status = queue_status or summarize_queue(tasks_path=tasks_path)
    checks: dict[str, Any] = {
        "utc_weekday": now.weekday(),
        "utc_hour": now.hour,
        "iso_week": _iso_week_key(now),
        "open_count": status.open_count,
        "pr_open_count": status.pr_open_count,
    }

    if now.weekday() != 2:
        return AcceleratedEmailDecision(
            should_dispatch=False,
            reason="not Wednesday (anchor runs after Wed afternoon ingest)",
            checks=checks,
        )

    if now.hour < min_utc_hour:
        return AcceleratedEmailDecision(
            should_dispatch=False,
            reason=f"before Wed anchor window (UTC hour {now.hour} < {min_utc_hour})",
            checks=checks,
        )

    anchor_count = wednesday_anchor_count(log_path=log_path, now=now)
    checks["wednesday_anchor_this_week"] = anchor_count
    checks["max_wednesday_anchor_per_week"] = max_per_week
    if anchor_count >= max_per_week:
        return AcceleratedEmailDecision(
            should_dispatch=False,
            reason=f"Wednesday anchor already ran this week ({anchor_count}/{max_per_week})",
            checks=checks,
        )

    if status.open_count > 0 or status.pr_open_count > 0:
        return AcceleratedEmailDecision(
            should_dispatch=False,
            reason="engineering queue not idle",
            checks=checks,
        )

    material, material_checks = ingest_loop_materiality(ingest_loop)
    checks.update(material_checks)
    if ingest_loop and (
        ingest_loop.get("micro_compiled") or ingest_loop.get("gap_closure_compiled")
    ):
        return AcceleratedEmailDecision(
            should_dispatch=False,
            reason="ingest run compiled engineering tasks — defer refresh to eng-chain",
            checks=checks,
        )

    screen_age = screen_run_age_hours(latest_path=latest_path, now=now)
    checks["screen_run_age_hours"] = screen_age
    checks["screen_stale_hours_threshold"] = screen_stale_hours
    screen_stale = screen_age is None or screen_age >= screen_stale_hours
    checks["screen_stale"] = screen_stale
    if not screen_stale and not material:
        return AcceleratedEmailDecision(
            should_dispatch=False,
            reason="no material change (screen fresh and ingest unchanged)",
            checks=checks,
        )

    blocked = _budget_guard(
        policy_path=policy_path,
        checks=checks,
        min_headroom_usd=min_headroom_usd,
        estimated_cost_usd=estimated_cost_usd,
    )
    if blocked is not None:
        return blocked

    blocked = _active_workflow_guard(repo=repo, token=token, checks=checks)
    if blocked is not None:
        return blocked

    trigger = "screen_stale" if screen_stale else "ingest_material_change"
    checks["anchor_trigger"] = trigger
    return AcceleratedEmailDecision(
        should_dispatch=True,
        reason=f"Wednesday anchor — {trigger.replace('_', ' ')}",
        checks=checks,
    )


def evaluate_accelerated_ladder_dispatch(
    *,
    queue_status: EngineeringQueueStatus | None = None,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    policy_path: Path | None = None,
    log_path: Path = DEFAULT_LOG_PATH,
    merged_task_id: str | None = None,
    repo: str | None = None,
    token: str | None = None,
    now: datetime | None = None,
    max_midweek_per_week: int = DEFAULT_MAX_MIDWEEK_LADDER_PER_WEEK,
) -> AcceleratedDispatchDecision:
    """Chain orchestrator suite=ladder_only after a coverage fix merges and queue drains."""
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
        return AcceleratedDispatchDecision(
            should_dispatch=False,
            reason="engineering queue not idle",
            checks=checks,
        )

    if now.weekday() == 6:
        return AcceleratedDispatchDecision(
            should_dispatch=False,
            reason="Sunday — use scheduled SUITE=sunday instead",
            checks=checks,
        )

    if merged_task_id:
        task = find_engineering_task(merged_task_id, path=tasks_path)
        if task is None:
            return AcceleratedDispatchDecision(
                should_dispatch=False,
                reason=f"merged task {merged_task_id} not found",
                checks=checks,
            )
        area = str(task.area or "").lower()
        checks["merged_task_area"] = area
        if area not in LADDER_CHAIN_AREAS:
            return AcceleratedDispatchDecision(
                should_dispatch=False,
                reason=f"merged task area {area} does not require offline ladder verify",
                checks=checks,
            )

    from value_investor.library_progression import assess_offline_universe_progression

    progression = assess_offline_universe_progression(tasks_path=tasks_path)
    checks["offline_progression_status"] = progression.get("status")
    prog_status = str(progression.get("status") or "")
    if prog_status in {"blocked_by_engineering", "complete"}:
        return AcceleratedDispatchDecision(
            should_dispatch=False,
            reason=progression.get("reason") or prog_status,
            checks=checks,
        )

    midweek_count = midweek_ladder_count(log_path=log_path, now=now)
    checks["midweek_ladder_this_week"] = midweek_count
    checks["max_midweek_ladder_per_week"] = max_midweek_per_week
    if midweek_count >= max_midweek_per_week:
        return AcceleratedDispatchDecision(
            should_dispatch=False,
            reason=f"mid-week ladder_only cap reached ({midweek_count}/{max_midweek_per_week})",
            checks=checks,
        )

    if repo and token:
        for workflow in ("library-grow.yml", "automation-orchestrator.yml"):
            active = active_workflow_runs(workflow, repo=repo, token=token)
            if active:
                checks["blocking_workflow"] = workflow
                checks["blocking_run_id"] = active[0].get("id")
                return AcceleratedDispatchDecision(
                    should_dispatch=False,
                    reason=f"{workflow} already active",
                    checks=checks,
                )

    return AcceleratedDispatchDecision(
        should_dispatch=True,
        reason="queue idle after coverage merge — verify offline library fetch fix",
        checks=checks,
    )


__all__ = [
    "DEFAULT_LOG_PATH",
    "DEFAULT_MAX_MIDWEEK_PER_WEEK",
    "DEFAULT_MAX_MIDWEEK_LADDER_PER_WEEK",
    "DEFAULT_MAX_WEDNESDAY_ANCHOR_PER_WEEK",
    "DEFAULT_SCREEN_STALE_HOURS",
    "WEDNESDAY_ANCHOR_SOURCE",
    "AcceleratedDispatchDecision",
    "AcceleratedEmailDecision",
    "evaluate_accelerated_email_only_dispatch",
    "evaluate_accelerated_ladder_dispatch",
    "evaluate_wednesday_anchor_dispatch",
    "ingest_loop_materiality",
    "load_accelerated_review_log",
    "midweek_email_only_count",
    "midweek_ladder_count",
    "record_midweek_email_only_run",
    "record_midweek_ladder_run",
    "screen_run_age_hours",
    "wednesday_anchor_count",
]
