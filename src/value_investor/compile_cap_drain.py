"""Idle-queue drain for compile-cap / role-coherence backlog.

Sunday ``ftse-engineering compile`` keeps at most ``max_tasks`` (default 8) open
candidates. Role-coherence flags the remainder as ``compile_cap_truncated_candidates``.
When the **priority** engineering queue is empty (no open/pr_open work except
background sources), queue leftover candidates the same way parked-source hunter
tasks are chained.

Throughput (default):

* Up to ``DEFAULT_MAX_OPEN_DRAIN_TASKS`` (2) open/pr_open drain tasks at once when
  idle — matches ``max_parallel_engineering_agents``.
* Near-duplicate suggestion titles are coalesced before queueing.
* After narrow-scope, ``auto_merge`` is set when the allowlist fits the CI-fix
  safe-prefix / path-cap gate; ``compile_cap_drain`` is also an independently
  verified merge class for any area.

Priority relative to hunter: **higher**. Drain score floor sits above
``PARKED_SOURCE_HUNTER_PRIORITY_SCORE`` so live-path suggestion backlog runs
before offline library leftover hunts. Still well below post-run / CI / so-what
scores (~70–100).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.ci_fix_tasks import task_allowed_paths_eligible_for_auto_merge
from value_investor.engineering_tasks import (
    COMMITTED_TASKS_PATH,
    COMPILE_CAP_DRAIN_PRIORITY_FLOOR,
    COMPILE_CAP_DRAIN_SOURCE,
    DEFAULT_MAX_COMPILE_TASKS,
    DEFAULT_SUGGESTIONS_PATH,
    HUNTER_URL_REPAIR_SOURCE,
    PARKED_SOURCE_HUNTER_SOURCE,
    TERMINAL_TASK_STATUSES,
    EngineeringTask,
    _merge_task_rows,
    _next_engineering_seq_from_rows,
    _title_keys_match,
    build_compiled_task_candidates,
    ensure_post_run_review_artifact,
    load_engineering_tasks,
)
from value_investor.ops_monitor import DEFAULT_LATEST_PATH
from value_investor.storage import write_json

BACKGROUND_QUEUE_SOURCES = frozenset(
    {
        PARKED_SOURCE_HUNTER_SOURCE,
        HUNTER_URL_REPAIR_SOURCE,
        COMPILE_CAP_DRAIN_SOURCE,
    }
)

DEFAULT_OUTPUT_DIR = Path("output")
DEFAULT_MAX_OPEN_DRAIN_TASKS = 2
_COALESCE_TOKEN_RE = re.compile(r"[^a-z0-9]+")


@dataclass
class CompileCapDrainDecision:
    should_compile: bool
    reason: str
    checks: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_compile": self.should_compile,
            "reason": self.reason,
            "checks": self.checks,
        }


def is_background_queue_source(source: str | None) -> bool:
    return str(source or "") in BACKGROUND_QUEUE_SOURCES


def is_priority_open_task(row: dict[str, Any]) -> bool:
    """True for open/pr_open work that should block compile-cap drain."""
    status = str(row.get("status") or "open")
    if status not in {"open", "pr_open"}:
        return False
    return not is_background_queue_source(str(row.get("source") or ""))


def has_priority_open_work(
    rows: list[dict[str, Any]] | None = None,
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
) -> bool:
    if rows is None:
        rows = list(load_engineering_tasks(tasks_path).get("tasks") or [])
    return any(is_priority_open_task(row) for row in rows if isinstance(row, dict))


def _open_compile_cap_drain_tasks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    open_rows: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("source") or "") != COMPILE_CAP_DRAIN_SOURCE:
            continue
        if str(row.get("status") or "open") in {"open", "pr_open"}:
            open_rows.append(row)
    return open_rows


def _open_compile_cap_drain_task(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    open_rows = _open_compile_cap_drain_tasks(rows)
    return open_rows[0] if open_rows else None


def _title_matches_queue(title: str, rows: list[dict[str, Any]]) -> bool:
    for row in rows:
        status = str(row.get("status") or "open")
        if status not in TERMINAL_TASK_STATUSES and status not in {"open", "pr_open"}:
            continue
        if _title_keys_match(title, str(row.get("title") or "")):
            return True
    return False


def drain_coalesce_key(title: str) -> str:
    """Normalize a suggestion title for near-duplicate coalescing.

    Drops short tokens and any token that still carries digits (``200m``,
    ``100.6m`` fragments, years) so magnitude-only variants share a key.
    """
    tokens = [tok for tok in _COALESCE_TOKEN_RE.sub(" ", title.lower()).split() if tok]
    keep: list[str] = []
    for tok in tokens:
        if len(tok) <= 2 or any(ch.isdigit() for ch in tok):
            continue
        keep.append(tok)
        if len(keep) >= 8:
            break
    return " ".join(keep)


def coalesce_compile_cap_drain_candidates(
    candidates: list[EngineeringTask],
) -> list[EngineeringTask]:
    """Keep the first (highest-priority) row per near-dup title key."""
    pending: list[EngineeringTask] = []
    seen: set[str] = set()
    for task in candidates:
        key = drain_coalesce_key(task.title) or task.title.strip().lower()[:120]
        if not key or key in seen:
            continue
        seen.add(key)
        pending.append(task)
    return pending


def iter_compile_cap_drain_candidates(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    latest_path: Path = DEFAULT_LATEST_PATH,
    suggestions_path: Path = DEFAULT_SUGGESTIONS_PATH,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    max_tasks: int = DEFAULT_MAX_COMPILE_TASKS,
) -> list[EngineeringTask]:
    """Return compile candidates not yet open/terminal, preferring beyond-cap rows.

    Beyond-cap (role-coherence backlog) comes first; then any still-unworked
    in-cap candidates that Sunday compile never landed. Near-duplicate titles
    are coalesced so serial agent cycles are not wasted on the same theme.
    """
    output_dir = Path(output_dir)
    ensure_post_run_review_artifact(output_dir=output_dir, latest_path=latest_path)
    candidates = build_compiled_task_candidates(
        output_dir=output_dir,
        suggestions_path=suggestions_path,
        scope="full",
        tasks_path=tasks_path,
    )
    existing_rows = list(load_engineering_tasks(tasks_path).get("tasks") or [])
    cap = max(0, int(max_tasks))
    beyond = candidates[cap:]
    within = candidates[:cap]
    ordered = list(beyond) + list(within)
    pending: list[EngineeringTask] = []
    seen: set[str] = set()
    for task in ordered:
        key = task.title.strip().lower()[:120]
        if key in seen:
            continue
        seen.add(key)
        if _title_matches_queue(task.title, existing_rows):
            continue
        pending.append(task)
    return coalesce_compile_cap_drain_candidates(pending)


def evaluate_compile_cap_drain(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    latest_path: Path = DEFAULT_LATEST_PATH,
    suggestions_path: Path = DEFAULT_SUGGESTIONS_PATH,
    max_tasks: int = DEFAULT_MAX_COMPILE_TASKS,
    max_open_drain_tasks: int = DEFAULT_MAX_OPEN_DRAIN_TASKS,
) -> CompileCapDrainDecision:
    """Decide whether to queue the next compile-cap / role-coherence backlog item."""
    existing_rows = list(load_engineering_tasks(tasks_path).get("tasks") or [])
    open_drain = _open_compile_cap_drain_tasks(existing_rows)
    max_open = max(1, int(max_open_drain_tasks))
    slots = max(0, max_open - len(open_drain))
    checks: dict[str, Any] = {
        "priority_open": has_priority_open_work(existing_rows),
        "max_tasks": int(max_tasks),
        "max_open_drain_tasks": max_open,
        "open_drain_count": len(open_drain),
        "slots_available": slots,
    }
    if open_drain:
        checks["open_drain_task_ids"] = [str(row.get("id") or "") for row in open_drain]
        checks["open_drain_task_id"] = str(open_drain[0].get("id") or "")

    if has_priority_open_work(existing_rows):
        return CompileCapDrainDecision(
            should_compile=False,
            reason="priority engineering queue not empty",
            checks=checks,
        )

    if slots <= 0:
        return CompileCapDrainDecision(
            should_compile=False,
            reason=(
                f"compile-cap drain already at max open "
                f"({len(open_drain)}/{max_open})"
            ),
            checks=checks,
        )

    pending = iter_compile_cap_drain_candidates(
        output_dir=output_dir,
        latest_path=latest_path,
        suggestions_path=suggestions_path,
        tasks_path=tasks_path,
        max_tasks=max_tasks,
    )
    checks["pending_count"] = len(pending)
    if pending:
        checks["next_title"] = pending[0].title[:160]
        checks["next_source"] = pending[0].source
        checks["next_area"] = pending[0].area
    if not pending:
        return CompileCapDrainDecision(
            should_compile=False,
            reason="no compile-cap / role-coherence backlog candidates remaining",
            checks=checks,
        )

    return CompileCapDrainDecision(
        should_compile=True,
        reason=(
            f"idle priority queue; drain next of {len(pending)} backlog candidate(s) "
            f"({slots} open slot(s))"
        ),
        checks=checks,
    )


def _drain_auto_merge_eligible(task: EngineeringTask) -> bool:
    from value_investor.engineering_narrow_scope import task_has_narrow_cohesion_bypass

    if task_has_narrow_cohesion_bypass(task):
        return False
    return task_allowed_paths_eligible_for_auto_merge(list(task.allowed_paths or []))


def _draft_drain_task_from_seed(
    seed: EngineeringTask,
    *,
    run_stamp: str,
    seq: int,
    score: float,
) -> list[EngineeringTask]:
    from value_investor.engineering_narrow_scope import apply_narrow_scope_to_task

    evidence = dict(seed.evidence or {})
    evidence.update(
        {
            "compile_cap_drain": True,
            "origin_source": seed.source,
            "origin_priority_score": seed.priority_score,
            "preferred_merge_class": "compile_cap_drain",
            "doc": "docs/ops/engineering-sync.md",
        }
    )
    scoped_seed = EngineeringTask(
        id=f"eng-{run_stamp}-{seq:02d}",
        area=seed.area,
        title=seed.title[:160],
        summary=(seed.summary or seed.title)[:500],
        priority="medium" if score >= 20 else "low",
        priority_score=score,
        source=COMPILE_CAP_DRAIN_SOURCE,
        auto_merge=False,
        evidence=evidence,
        acceptance_criteria=list(seed.acceptance_criteria or []),
        allowed_paths=list(seed.allowed_paths or []),
        blocked_paths=list(seed.blocked_paths or []),
    )
    scoped_tasks = apply_narrow_scope_to_task(scoped_seed)
    drafted: list[EngineeringTask] = []
    for offset, scoped in enumerate(scoped_tasks):
        auto_merge = _drain_auto_merge_eligible(scoped)
        scoped_evidence = dict(scoped.evidence or {})
        scoped_evidence["preferred_merge_class"] = "compile_cap_drain"
        if auto_merge:
            scoped_evidence["auto_merge_reason"] = "allowlist fits CI-fix safe path cap"
        drafted.append(
            EngineeringTask(
                id=f"eng-{run_stamp}-{seq + offset:02d}",
                area=scoped.area,
                title=scoped.title[:160],
                summary=(scoped.summary or scoped.title)[:500],
                priority=scoped.priority,
                priority_score=score,
                source=COMPILE_CAP_DRAIN_SOURCE,
                auto_merge=auto_merge,
                evidence=scoped_evidence,
                acceptance_criteria=list(scoped.acceptance_criteria or []),
                allowed_paths=list(scoped.allowed_paths or []),
                blocked_paths=list(scoped.blocked_paths or []),
            )
        )
    return drafted


def compile_next_compile_cap_drain_task(
    *,
    apply: bool = True,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    committed_path: Path | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    latest_path: Path = DEFAULT_LATEST_PATH,
    suggestions_path: Path = DEFAULT_SUGGESTIONS_PATH,
    max_tasks: int = DEFAULT_MAX_COMPILE_TASKS,
    max_open_drain_tasks: int = DEFAULT_MAX_OPEN_DRAIN_TASKS,
) -> dict[str, Any]:
    """Queue compile-cap backlog task(s) when the priority queue is empty.

    Fills available open slots up to ``max_open_drain_tasks`` (default 2).
    """
    committed_path = Path(committed_path or tasks_path)
    tasks_path = Path(tasks_path)
    decision = evaluate_compile_cap_drain(
        tasks_path=tasks_path,
        output_dir=output_dir,
        latest_path=latest_path,
        suggestions_path=suggestions_path,
        max_tasks=max_tasks,
        max_open_drain_tasks=max_open_drain_tasks,
    )
    payload: dict[str, Any] = {
        "compiled_count": 0,
        "decision": decision.to_dict(),
        "reason": decision.reason,
    }
    if not decision.should_compile:
        return payload
    if not apply:
        payload["would_compile"] = True
        payload["slots_available"] = int(decision.checks.get("slots_available") or 0)
        return payload

    pending = iter_compile_cap_drain_candidates(
        output_dir=output_dir,
        latest_path=latest_path,
        suggestions_path=suggestions_path,
        tasks_path=tasks_path,
        max_tasks=max_tasks,
    )
    if not pending:
        payload["reason"] = "no compile-cap / role-coherence backlog candidates remaining"
        return payload

    existing_payload = load_engineering_tasks(committed_path)
    existing_rows = list(existing_payload.get("tasks") or [])
    open_before = {
        str(row.get("id") or "")
        for row in existing_rows
        if str(row.get("status") or "open") == "open"
    }
    slots = max(1, int(decision.checks.get("slots_available") or 1))
    run_stamp = datetime.now(UTC).strftime("%Y%m%d")
    all_drafted: list[EngineeringTask] = []
    queued_titles: list[str] = []

    for seed in pending:
        open_drain_now = len(_open_compile_cap_drain_tasks(existing_rows)) + len(all_drafted)
        if open_drain_now >= max(1, int(max_open_drain_tasks)):
            break
        if any(_title_keys_match(seed.title, title) for title in queued_titles):
            continue
        seq = _next_engineering_seq_from_rows(
            existing_rows + [task.to_dict() for task in all_drafted],
            run_stamp,
        )
        score = max(float(seed.priority_score or 0.0), COMPILE_CAP_DRAIN_PRIORITY_FLOOR)
        drafted = _draft_drain_task_from_seed(
            seed,
            run_stamp=run_stamp,
            seq=seq,
            score=score,
        )
        # Skip this suggestion if siblings alone would blow the open-task cap hard.
        if open_drain_now + len(drafted) > max(1, int(max_open_drain_tasks)) and all_drafted:
            break
        all_drafted.extend(drafted)
        queued_titles.append(seed.title)

    if not all_drafted:
        payload["reason"] = "no compile-cap / role-coherence backlog candidates remaining"
        return payload

    merged_rows = _merge_task_rows(existing_rows, all_drafted)
    newly_open = [
        row
        for row in merged_rows
        if str(row.get("status") or "open") == "open"
        and str(row.get("id") or "") not in open_before
    ]
    out = {
        **existing_payload,
        "compiled_at": datetime.now(UTC).isoformat(),
        "task_count": len(merged_rows),
        "tasks": merged_rows,
        "micro_compile_source": COMPILE_CAP_DRAIN_SOURCE,
    }
    committed_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(committed_path, out, compact=False)
    if tasks_path != committed_path:
        write_json(tasks_path, out, compact=False)

    primary = all_drafted[0]
    return {
        "compiled_count": len(newly_open),
        "task_ids": [str(row.get("id") or "") for row in newly_open],
        "task_count": len(merged_rows),
        "priority_score": primary.priority_score,
        "title": primary.title,
        "titles": [row.title for row in all_drafted],
        "area": primary.area,
        "origin_source": str((primary.evidence or {}).get("origin_source") or ""),
        "pending_remaining": max(0, len(pending) - len(queued_titles)),
        "decision": decision.to_dict(),
        "reason": "compiled",
        "narrow_scope_siblings": len(all_drafted),
        "queued_suggestion_count": len(queued_titles),
        "auto_merge_count": sum(1 for row in all_drafted if row.auto_merge),
    }


def should_defer_parked_hunter_for_compile_cap_drain(
    *,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    latest_path: Path = DEFAULT_LATEST_PATH,
    suggestions_path: Path = DEFAULT_SUGGESTIONS_PATH,
    max_tasks: int = DEFAULT_MAX_COMPILE_TASKS,
) -> tuple[bool, str]:
    """Hunter yields while compile-cap drain still has idle-queue work."""
    existing_rows = list(load_engineering_tasks(tasks_path).get("tasks") or [])
    if has_priority_open_work(existing_rows):
        return False, "priority queue busy — hunter may still sit at back"
    if _open_compile_cap_drain_tasks(existing_rows):
        return True, "open compile-cap drain outranks hunter"
    pending = iter_compile_cap_drain_candidates(
        output_dir=output_dir,
        latest_path=latest_path,
        suggestions_path=suggestions_path,
        tasks_path=tasks_path,
        max_tasks=max_tasks,
    )
    if pending:
        return True, f"compile-cap drain backlog ({len(pending)}) outranks hunter"
    return False, "no compile-cap drain backlog"


__all__ = [
    "BACKGROUND_QUEUE_SOURCES",
    "COMPILE_CAP_DRAIN_PRIORITY_FLOOR",
    "COMPILE_CAP_DRAIN_SOURCE",
    "DEFAULT_MAX_OPEN_DRAIN_TASKS",
    "CompileCapDrainDecision",
    "coalesce_compile_cap_drain_candidates",
    "compile_next_compile_cap_drain_task",
    "drain_coalesce_key",
    "evaluate_compile_cap_drain",
    "has_priority_open_work",
    "is_background_queue_source",
    "is_priority_open_task",
    "iter_compile_cap_drain_candidates",
    "should_defer_parked_hunter_for_compile_cap_drain",
]
