"""Automatic post-run improvement clearance (lanes A/B/C bootstrap).

Runs after each new post-run improvement review to apply so-what batching,
compile-cap drain, optional idle backstop, and engineering dispatch signals —
see ``docs/ops/post-run-improvement-clearance.md``.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.engineering_queue import evaluate_engineering_dispatch, summarize_queue
from value_investor.engineering_tasks import (
    COMMITTED_TASKS_PATH,
    DEFAULT_MAX_COMPILE_TASKS,
    DEFAULT_SUGGESTIONS_PATH,
    compile_capacity_audit,
)
from value_investor.idle_compile_backstop import (
    plan_titles_only_in_terminal_queue,
    post_run_plan_titles_without_open_match,
    run_idle_compile_backstop,
)
from value_investor.ops_monitor import DEFAULT_LATEST_PATH
from value_investor.post_run_review import PostRunReview, _parse_post_run_review
from value_investor.storage import read_json, write_json

logger = logging.getLogger(__name__)

DEFAULT_LOG_PATH = Path("docs/data/post_run_clearance.json")
DEFAULT_OUTPUT_DIR = Path("output")
SCHEMA_VERSION = 1

TRIGGER_POST_RUN_EMAIL = "post_run_review_email"
TRIGGER_ANALYSIS_REVIEW = "analysis_review_follow_up"


def post_run_review_fingerprint(review: PostRunReview | dict[str, Any]) -> str:
    """Stable id for deduping clearance runs per review text."""
    if isinstance(review, PostRunReview):
        plan = review.improvement_plan.strip()
        weaknesses = review.persistent_weaknesses.strip()[:4000]
    else:
        plan = str(review.get("improvement_plan") or "").strip()
        weaknesses = str(review.get("persistent_weaknesses") or "").strip()[:4000]
    blob = f"{plan}\n---\n{weaknesses}".encode()
    return hashlib.sha256(blob).hexdigest()[:20]


def _load_review(
    *,
    output_dir: Path,
    latest_path: Path,
) -> tuple[PostRunReview | None, str, str]:
    """Return (review, fingerprint, source_label)."""
    md_path = output_dir / "post_run_review.md"
    if md_path.exists():
        review = _parse_post_run_review(md_path.read_text(encoding="utf-8"))
        if review.improvement_plan.strip() or review.persistent_weaknesses.strip():
            return review, post_run_review_fingerprint(review), "output/post_run_review.md"

    if latest_path.exists():
        latest = read_json(latest_path)
        if isinstance(latest, dict):
            block = latest.get("post_run_review")
            if isinstance(block, dict) and (
                str(block.get("improvement_plan") or "").strip()
                or str(block.get("persistent_weaknesses") or "").strip()
            ):
                review = PostRunReview(
                    executive_summary=str(block.get("executive_summary") or ""),
                    persistent_weaknesses=str(block.get("persistent_weaknesses") or ""),
                    this_week_findings=str(block.get("this_week_findings") or ""),
                    improvement_plan=str(block.get("improvement_plan") or ""),
                    defer=str(block.get("defer") or ""),
                )
                return review, post_run_review_fingerprint(review), "latest.json"

    return None, "", "missing"


def load_post_run_clearance_log(path: Path = DEFAULT_LOG_PATH) -> dict[str, Any]:
    empty: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "last_run": None,
        "runs": [],
    }
    if not path.exists():
        return dict(empty)
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return dict(empty)
    if not isinstance(payload, dict):
        return dict(empty)
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("runs", [])
    return payload


def _already_ran(*, log: dict[str, Any], fingerprint: str, trigger: str) -> bool:
    for row in reversed(log.get("runs") or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("fingerprint") or "") != fingerprint:
            continue
        if str(row.get("trigger") or "") == trigger:
            return True
    return False


def run_post_run_clearance_cycle(
    *,
    apply: bool = False,
    force: bool = False,
    trigger: str = TRIGGER_POST_RUN_EMAIL,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    latest_path: Path = DEFAULT_LATEST_PATH,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    suggestions_path: Path = DEFAULT_SUGGESTIONS_PATH,
    log_path: Path = DEFAULT_LOG_PATH,
    max_tasks: int = DEFAULT_MAX_COMPILE_TASKS,
    skip_idle_backstop: bool = False,
) -> dict[str, Any]:
    """
    Evaluate and optionally apply lane B bootstrap after a post-run improvement review.

    Dedupes on (fingerprint, trigger) unless ``force`` is true.
    """
    now = datetime.now(UTC)
    review, fingerprint, review_source = _load_review(
        output_dir=output_dir,
        latest_path=latest_path,
    )
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "trigger": trigger,
        "evaluated_at": now.isoformat(),
        "review_source": review_source,
        "fingerprint": fingerprint,
        "skipped": False,
        "skip_reason": None,
        "applied": False,
        "lanes": {"a_note": "ingest factory unchanged — weekday ingest-loop owns Lane A"},
        "should_dispatch_engineering": False,
        "lane_c_recommended": False,
        "actions": [],
    }

    if review is None or not fingerprint:
        result["skipped"] = True
        result["skip_reason"] = "no post-run improvement review artifact"
        _persist_run(log_path, result)
        return result

    log = load_post_run_clearance_log(log_path)
    if not force and _already_ran(log=log, fingerprint=fingerprint, trigger=trigger):
        result["skipped"] = True
        result["skip_reason"] = f"clearance already ran for fingerprint+trigger ({trigger})"
        result["last_duplicate_of"] = fingerprint
        _persist_run(log_path, result)
        return result

    status_before = summarize_queue(tasks_path=tasks_path)
    result["queue_before"] = {
        "open_count": status_before.open_count,
        "pr_open_count": status_before.pr_open_count,
    }

    cap_audit = compile_capacity_audit(
        output_dir=output_dir,
        latest_path=latest_path,
        suggestions_path=suggestions_path,
        max_tasks=max_tasks,
    )
    result["compile_cap_audit"] = {
        "candidate_count": cap_audit.get("candidate_count"),
        "truncated_count": cap_audit.get("truncated_count"),
        "post_run_plan_beyond_cap": cap_audit.get("post_run_plan_beyond_cap") or [],
    }

    unlinked = post_run_plan_titles_without_open_match(
        latest_path=latest_path,
        tasks_path=tasks_path,
    )
    terminal_only = plan_titles_only_in_terminal_queue(
        latest_path=latest_path,
        tasks_path=tasks_path,
    )
    result["plan_alignment"] = {
        "unlinked_plan_titles": unlinked,
        "terminal_only_titles": terminal_only,
    }
    queue_idle = status_before.open_count == 0 and status_before.pr_open_count == 0
    result["lane_c_recommended"] = bool(queue_idle and (unlinked or terminal_only))

    if not apply:
        dispatch = evaluate_engineering_dispatch(tasks_path=tasks_path)
        result["should_dispatch_engineering"] = bool(
            dispatch.should_dispatch and status_before.open_count > 0
        )
        result["dispatch_reason"] = dispatch.reason
        _persist_run(log_path, result)
        return result

    result["applied"] = True
    tasks_added = 0

    from value_investor.so_what_closure import apply_so_what_auto_queue

    so_what = apply_so_what_auto_queue(
        dry_run=False,
        tasks_path=tasks_path,
        latest_path=latest_path,
        artifacts_dir=Path("docs/data"),
        snapshot_path=Path("docs/data/so_what_closure.json"),
    )
    created = so_what.get("created_tasks") or []
    if created:
        tasks_added += len(created)
        result["actions"].append(
            {
                "kind": "so_what_auto_queue",
                "created_count": len(created),
                "task_ids": [str(r.get("task_id") or "") for r in created if r.get("task_id")],
            }
        )

    from value_investor.compile_cap_drain import compile_next_compile_cap_drain_task
    from value_investor.engineering_recovery import is_queue_clearing_pause_active

    if not is_queue_clearing_pause_active(tasks_path=tasks_path):
        drain = compile_next_compile_cap_drain_task(
            apply=True,
            tasks_path=tasks_path,
            committed_path=tasks_path,
            output_dir=output_dir,
            latest_path=latest_path,
            suggestions_path=suggestions_path,
            max_tasks=max_tasks,
        )
        compiled = int(drain.get("compiled_count") or 0)
        if compiled:
            tasks_added += compiled
            result["actions"].append(
                {
                    "kind": "compile_cap_drain",
                    "compiled_count": compiled,
                    "task_ids": drain.get("task_ids") or [],
                    "reason": drain.get("reason"),
                }
            )
        else:
            result["compile_cap_drain_skipped"] = str(drain.get("reason") or "no task")
    else:
        result["compile_cap_drain_skipped"] = "queue_clearing_pause_active"

    if not skip_idle_backstop:
        backstop = run_idle_compile_backstop(
            apply=True,
            tasks_path=tasks_path,
            output_dir=output_dir,
            latest_path=latest_path,
            suggestions_path=suggestions_path,
            max_tasks=max_tasks,
        )
        if backstop.get("applied"):
            added = int((backstop.get("compile") or {}).get("added_open_count") or 0)
            tasks_added += added
            result["actions"].append(
                {
                    "kind": "idle_compile_backstop",
                    "added_open_count": added,
                    "task_ids": (backstop.get("compile") or {}).get("added_open_task_ids") or [],
                }
            )
        else:
            decision = backstop.get("decision") or {}
            result["idle_backstop_skipped"] = str(decision.get("reason") or "not applied")
    else:
        result["idle_backstop_skipped"] = "skip_idle_backstop (fresh post-run compile)"

    status_after = summarize_queue(tasks_path=tasks_path)
    result["queue_after"] = {
        "open_count": status_after.open_count,
        "pr_open_count": status_after.pr_open_count,
    }
    result["tasks_added_estimate"] = tasks_added

    dispatch = evaluate_engineering_dispatch(tasks_path=tasks_path)
    result["should_dispatch_engineering"] = bool(
        dispatch.should_dispatch and (status_after.open_count > 0 or tasks_added > 0)
    )
    result["dispatch_reason"] = dispatch.reason

    if result["lane_c_recommended"]:
        result["actions"].append(
            {
                "kind": "lane_c_note",
                "detail": (
                    "Post-run plan lines lack open queue matches — after eng merges idle, "
                    "run accelerated email_only (Lane C); do not re-compile verbatim plan"
                ),
            }
        )

    _persist_run(log_path, result)
    return result


def _persist_run(log_path: Path, result: dict[str, Any]) -> None:
    log = load_post_run_clearance_log(log_path)
    log["last_run"] = dict(result)
    rows = list(log.get("runs") or [])
    rows.append(dict(result))
    log["runs"] = rows[-40:]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(log_path, log, compact=False)


__all__ = [
    "DEFAULT_LOG_PATH",
    "TRIGGER_ANALYSIS_REVIEW",
    "TRIGGER_POST_RUN_EMAIL",
    "load_post_run_clearance_log",
    "post_run_review_fingerprint",
    "run_post_run_clearance_cycle",
]
