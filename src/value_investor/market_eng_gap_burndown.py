"""Market-rotating library ingest engineering escalation (L448).

Uses the maintenance slot cursor to fair-rotate offline markets when the shared
ingest engineering slot is free.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import DEFAULT_POLICY_PATH, load_policy
from value_investor.data_library import DEFAULT_LIBRARY_ROOT
from value_investor.engineering_queue import summarize_queue
from value_investor.engineering_tasks import COMMITTED_TASKS_PATH
from value_investor.ingest_loop import has_open_ingest_engineering_tasks
from value_investor.library_ingest_dispatch import list_library_ingest_maintenance_markets
from value_investor.library_ingest_escalation import (
    compile_library_ingest_engineering_tasks_micro,
    compile_parked_source_hunter_task,
    has_open_library_ingest_task_for_market,
    library_ingest_filing_gaps,
    library_ingest_health_stalled,
    resolve_library_ingest_health_log_path,
    snapshot_library_buy_tier_filing_health,
)
from value_investor.library_maintenance_stagger import load_maintenance_slot_cursor, rotate_after


def burndown_market_universe(
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy: dict[str, Any] | None = None,
) -> list[str]:
    policy = policy if policy is not None else load_policy()
    markets = list_library_ingest_maintenance_markets(
        library_root=library_root,
        policy=policy,
    )
    return sorted({str(m).strip() for m in markets if str(m).strip()})


def rotate_burndown_markets(
    markets: list[str],
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
) -> list[str]:
    cursor = load_maintenance_slot_cursor(library_root)
    last_head = str(cursor.get("last_head") or "").strip() or None
    return rotate_after(list(markets), last_head)


def assess_market_eng_gap_burndown(
    market_id: str,
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy: dict[str, Any] | None = None,
    tasks_path: Path = COMMITTED_TASKS_PATH,
) -> dict[str, Any]:
    """Whether a library market still needs Lane B escalation."""
    market_id = str(market_id or "").strip()
    policy = policy if policy is not None else load_policy()
    health = snapshot_library_buy_tier_filing_health(
        market_id,
        library_root=library_root,
        policy=policy,
    )
    filing_gaps = library_ingest_filing_gaps(health)
    thin = int(health.get("thin_body_buy_tier") or 0)
    iwb = int(health.get("indexed_without_body") or 0)
    log_path = resolve_library_ingest_health_log_path(library_root, market_id)
    stalled = library_ingest_health_stalled(log_path, market_id=market_id)
    open_for_market = has_open_library_ingest_task_for_market(
        market_id,
        tasks_path=tasks_path,
    )
    needs_work = filing_gaps > 0 or thin > 0 or iwb > 0
    needs_eng = needs_work and not open_for_market
    return {
        "market_id": market_id,
        "filing_gaps": filing_gaps,
        "thin_body_buy_tier": thin,
        "indexed_without_body": iwb,
        "stalled": stalled,
        "open_eng_for_market": open_for_market,
        "needs_work": needs_work,
        "needs_eng": needs_eng,
        "health": health,
    }


def try_market_rotating_eng_gap_burndown(
    *,
    apply: bool = False,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    tasks_path: Path = COMMITTED_TASKS_PATH,
    data_dir: Path = Path("docs/data"),
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate or compile one library ingest eng task using maintenance rotation."""
    now = now or datetime.now(UTC)
    policy = load_policy(policy_path)
    tasks_path = Path(tasks_path)
    result: dict[str, Any] = {
        "evaluated_at": now.isoformat(),
        "applied": bool(apply),
        "compiled_count": 0,
        "action": None,
        "market_id": None,
        "cursor_last_head": None,
        "markets_considered": [],
    }

    from value_investor.engineering_recovery import is_queue_clearing_pause_active

    if is_queue_clearing_pause_active(tasks_path=tasks_path):
        result["reason"] = "queue_clearing_pause_active"
        return result

    if has_open_ingest_engineering_tasks(tasks_path):
        result["reason"] = "open ingest engineering task in flight"
        return result

    status = summarize_queue(tasks_path=tasks_path)
    if int(status.pr_open_count or 0) > 0:
        result["reason"] = "engineering pr_open in flight"
        return result

    universe = burndown_market_universe(library_root=library_root, policy=policy)
    if not universe:
        result["reason"] = "no maintenance-eligible library markets"
        return result

    cursor = load_maintenance_slot_cursor(library_root)
    result["cursor_last_head"] = cursor.get("last_head")
    rotated = rotate_burndown_markets(universe, library_root=library_root)
    result["markets_considered"] = rotated

    for market_id in rotated:
        assessment = assess_market_eng_gap_burndown(
            market_id,
            library_root=library_root,
            policy=policy,
            tasks_path=tasks_path,
        )
        if not assessment.get("needs_eng"):
            continue

        result["market_id"] = market_id
        result["assessment"] = {
            k: assessment[k]
            for k in (
                "filing_gaps",
                "thin_body_buy_tier",
                "indexed_without_body",
                "stalled",
                "open_eng_for_market",
            )
        }

        if not apply:
            result["reason"] = "would compile for rotated market (dry-run)"
            result["would_try"] = ["gap_closure_compile", "stall_micro_compile", "parked_hunter"]
            return result

        from value_investor.ingest_gap_closure import compile_pending_gap_closure_engineering

        gap_out = compile_pending_gap_closure_engineering(
            market_id=market_id,
            limit=1,
            tasks_path=tasks_path,
            data_dir=data_dir,
        )
        if int(gap_out.get("compiled_count") or 0) > 0:
            compiled = gap_out.get("compiled") or []
            result["compiled_count"] = 1
            result["action"] = "gap_closure_compile"
            result["gap_closure"] = gap_out
            result["task_id"] = (compiled[0] or {}).get("task_id") if compiled else None
            result["reason"] = "compiled from pending gap-closure run"
            return result

        health = assessment.get("health") or {}
        if assessment.get("stalled") and library_ingest_filing_gaps(health) > 0:
            micro = compile_library_ingest_engineering_tasks_micro(
                market_id=market_id,
                health_after=health,
                library_root=library_root,
                tasks_path=tasks_path,
                committed_path=tasks_path,
                max_tasks=1,
            )
            if int(micro.get("compiled_count") or 0) > 0:
                result["compiled_count"] = 1
                result["action"] = "stall_micro_compile"
                result["micro_compile"] = micro
                result["task_id"] = (micro.get("task_ids") or [None])[0]
                result["reason"] = "library ingest stall micro-compile"
                return result

        hunter = compile_parked_source_hunter_task(
            library_root=library_root,
            policy=policy,
            tasks_path=tasks_path,
            committed_path=tasks_path,
            prefer_market_id=market_id,
        )
        if int(hunter.get("compiled_count") or 0) > 0:
            result["compiled_count"] = 1
            result["action"] = "parked_hunter"
            result["parked_hunter"] = hunter
            result["task_id"] = hunter.get("task_id")
            result["reason"] = "parked leftover source hunter"
            return result

        result.setdefault("attempts", []).append(
            {
                "market_id": market_id,
                "reason": "needs work but no compile path fired",
                "gap_closure_skipped": gap_out.get("skipped"),
            }
        )
        continue

    result["reason"] = "no market needs eng escalation"
    if result.get("attempts"):
        result["reason"] = "no compile path fired for markets needing work"
    return result


__all__ = [
    "assess_market_eng_gap_burndown",
    "burndown_market_universe",
    "rotate_burndown_markets",
    "try_market_rotating_eng_gap_burndown",
]
