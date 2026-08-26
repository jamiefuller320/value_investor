"""Library ingest dispatch: filing-parity sprint vs daily maintenance (FTSE parity)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import DEFAULT_POLICY_PATH, load_policy
from value_investor.data_library import DEFAULT_LIBRARY_ROOT
from value_investor.library_ingest_escalation import (
    library_ingest_filing_gaps,
    snapshot_library_buy_tier_filing_health,
)
from value_investor.market_shard_phases import evaluate_market_phase
from value_investor.storage import read_json, write_json

logger = logging.getLogger(__name__)

DEFAULT_MARKET_ID = "euro_depth"
DEFAULT_DISPATCH_PATH = Path("docs/data/library/euro_ingest_dispatch.json")

MODE_SPRINT = "sprint"
MODE_MAINTENANCE = "maintenance"
# Deprecated alias — parity met maps to maintenance (daily scan+deepen), not zero ingest.
MODE_IDLE = MODE_MAINTENANCE

SPRINT_CONFIG: dict[str, Any] = {
    "max_daily_successes": 4,
    "max_targets": 24,
    "cron_morning": True,
    "cron_afternoon": True,
    "cron_midafternoon": True,
    "cron_evening": True,
    "cron_ladder_weekday": True,
    "cron_maintenance": False,
}

MAINTENANCE_CONFIG: dict[str, Any] = {
    "max_daily_successes": 1,
    "max_targets": 4,
    "cron_morning": False,
    "cron_afternoon": False,
    "cron_midafternoon": False,
    "cron_evening": False,
    "cron_ladder_weekday": True,
    "cron_maintenance": True,
}

EURO_INGEST_CRON_TITLES = {
    "morning": "Euro ingest loop (weekday morning)",
    "afternoon": "Euro ingest loop (weekday afternoon)",
    "midafternoon": "Euro ingest loop (weekday mid-afternoon)",
    "evening": "Euro ingest loop (weekday evening)",
    "ladder_weekday": "FTSE orchestrator (weekday ladder)",
    "maintenance": "Library ingest maintenance (parity markets)",
}


def ingest_parity_met(health: dict[str, Any]) -> bool:
    """True when buy-tier has no unmeasured or zero-body filing gaps."""
    return library_ingest_filing_gaps(health) == 0


def evaluate_library_ingest_dispatch(
    market_id: str,
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Decide ingest cadence from **filing parity** on the focus market.

    Sprint (high tempo) while ``unmeasured + zero_body > 0``; maintenance once parity
    is met. Phase 3 readiness is informational only — ladder/shard crons continue
    separately during maintenance.
    """
    library_root = Path(library_root)
    policy = policy if policy is not None else load_policy(policy_path)
    phase = evaluate_market_phase(
        market_id,
        library_root=library_root,
        policy=policy,
    )
    health = snapshot_library_buy_tier_filing_health(market_id, library_root=library_root)
    gaps = library_ingest_filing_gaps(health)
    parity = gaps == 0

    if parity:
        mode = MODE_MAINTENANCE
        reason = (
            "Ingest parity met — focus on daily maintenance; Phase 3 ladder continues separately"
        )
        config = MAINTENANCE_CONFIG
    else:
        mode = MODE_SPRINT
        reason = (
            f"Ingest sprint: {gaps} buy-tier filing gap(s) "
            f"(unmeasured={health.get('unmeasured_buy_tier')}, "
            f"zero_body={health.get('zero_body_buy_tier')})"
        )
        config = SPRINT_CONFIG

    return {
        "market_id": market_id,
        "focus_market": str(policy.get("focus_market") or market_id),
        "mode": mode,
        "reason": reason,
        "ingest_parity_met": parity,
        "phase3_ready": bool(phase.get("phase3_ready")),
        "phase_blockers": list(phase.get("blockers") or []),
        "filing_health": health,
        "filing_gaps": gaps,
        "max_daily_successes": int(config["max_daily_successes"]),
        "max_targets": int(config["max_targets"]),
        "cron_morning": bool(config["cron_morning"]),
        "cron_afternoon": bool(config["cron_afternoon"]),
        "cron_midafternoon": bool(config["cron_midafternoon"]),
        "cron_evening": bool(config["cron_evening"]),
        "cron_ladder_weekday": bool(config["cron_ladder_weekday"]),
        "cron_maintenance": bool(config.get("cron_maintenance")),
        "should_run_sprint_ingest": mode == MODE_SPRINT,
        "should_run_maintenance_ingest": mode == MODE_MAINTENANCE,
        # Back-compat for euro-ingest-loop gate (sprint workflow only).
        "should_run_ingest": mode == MODE_SPRINT,
        "evaluated_at": datetime.now(UTC).isoformat(),
    }


def evaluate_euro_ingest_dispatch(
    *,
    market_id: str = DEFAULT_MARKET_ID,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate dispatch for ``market_id`` (defaults to focus or euro_depth)."""
    policy = policy if policy is not None else load_policy(policy_path)
    focus = str(policy.get("focus_market") or market_id or DEFAULT_MARKET_ID)
    target = market_id if market_id else focus
    if target != focus and market_id == DEFAULT_MARKET_ID:
        target = focus
    return evaluate_library_ingest_dispatch(
        target,
        library_root=library_root,
        policy_path=policy_path,
        policy=policy,
    )


def list_library_ingest_parallel_sprint_markets(
    *,
    policy: dict[str, Any] | None = None,
    policy_path: Path = DEFAULT_POLICY_PATH,
) -> list[str]:
    """
    Markets in ``ingest_parallel_sprint`` that run sprint ingest alongside focus.

    Focus market sprint is handled by ``euro-ingest-loop.yml``; this list is for
    parallel queue head-start (e.g. sp500 while euro_depth finishes).
    """
    policy = policy if policy is not None else load_policy(policy_path)
    focus = str(policy.get("focus_market") or "").strip()
    parallel = [str(m).strip() for m in (policy.get("ingest_parallel_sprint") or []) if str(m).strip()]
    return sorted({m for m in parallel if m and m != focus})


def list_library_ingest_sprint_markets(
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    policy: dict[str, Any] | None = None,
) -> list[str]:
    """All markets that should run sprint ingest (focus + parallel with filing gaps)."""
    library_root = Path(library_root)
    policy = policy if policy is not None else load_policy(policy_path)
    focus = str(policy.get("focus_market") or "").strip()
    markets: list[str] = []
    if focus:
        health = snapshot_library_buy_tier_filing_health(focus, library_root=library_root)
        if not ingest_parity_met(health):
            markets.append(focus)
    for market_id in list_library_ingest_parallel_sprint_markets(policy=policy):
        if market_id in markets:
            continue
        health = snapshot_library_buy_tier_filing_health(market_id, library_root=library_root)
        if not ingest_parity_met(health):
            markets.append(market_id)
    return markets


def list_library_ingest_maintenance_markets(
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    policy: dict[str, Any] | None = None,
) -> list[str]:
    """Markets with ingest parity that should receive daily maintenance passes."""
    library_root = Path(library_root)
    policy = policy if policy is not None else load_policy(policy_path)
    markets: set[str] = set(policy.get("ingest_parity_markets") or [])
    focus = str(policy.get("focus_market") or "").strip()
    if focus:
        health = snapshot_library_buy_tier_filing_health(focus, library_root=library_root)
        if ingest_parity_met(health):
            markets.add(focus)
    return sorted(markets)


def write_euro_ingest_dispatch(
    evaluation: dict[str, Any],
    *,
    path: Path = DEFAULT_DISPATCH_PATH,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, evaluation, compact=False)
    return path


def refresh_euro_ingest_dispatch(
    *,
    market_id: str = DEFAULT_MARKET_ID,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    dispatch_path: Path = DEFAULT_DISPATCH_PATH,
    sync_cron: bool = False,
) -> dict[str, Any]:
    """Evaluate, persist dispatch state, and optionally sync cron-job.org toggles."""
    evaluation = evaluate_euro_ingest_dispatch(
        market_id=market_id,
        library_root=library_root,
        policy_path=policy_path,
    )
    evaluation["maintenance_markets"] = list_library_ingest_maintenance_markets(
        library_root=library_root,
        policy_path=policy_path,
    )
    parallel = list_library_ingest_parallel_sprint_markets(policy_path=policy_path)
    evaluation["parallel_sprint_markets"] = parallel
    evaluation["parallel_sprint_status"] = [
        evaluate_library_ingest_dispatch(
            market_id,
            library_root=library_root,
            policy_path=policy_path,
        )
        for market_id in parallel
    ]
    evaluation["sprint_markets"] = list_library_ingest_sprint_markets(
        library_root=library_root,
        policy_path=policy_path,
    )
    write_euro_ingest_dispatch(evaluation, path=dispatch_path)
    if sync_cron:
        try:
            from value_investor.euro_ingest_cron_sync import sync_euro_ingest_cron_jobs

            evaluation["cron_sync"] = sync_euro_ingest_cron_jobs(evaluation)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Euro ingest cron sync failed: %s", exc)
            evaluation["cron_sync"] = {"error": str(exc)}
    return evaluation


def load_euro_ingest_dispatch(*, path: Path = DEFAULT_DISPATCH_PATH) -> dict[str, Any] | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        return read_json(path)
    except (OSError, ValueError, TypeError):
        return None


def cron_enabled_for_dispatch(evaluation: dict[str, Any]) -> dict[str, bool]:
    return {
        "morning": bool(evaluation.get("cron_morning")),
        "afternoon": bool(evaluation.get("cron_afternoon")),
        "midafternoon": bool(evaluation.get("cron_midafternoon")),
        "evening": bool(evaluation.get("cron_evening")),
        "ladder_weekday": bool(evaluation.get("cron_ladder_weekday")),
        "maintenance": bool(evaluation.get("cron_maintenance")),
    }


__all__ = [
    "DEFAULT_DISPATCH_PATH",
    "EURO_INGEST_CRON_TITLES",
    "MAINTENANCE_CONFIG",
    "MODE_IDLE",
    "MODE_MAINTENANCE",
    "MODE_SPRINT",
    "SPRINT_CONFIG",
    "cron_enabled_for_dispatch",
    "evaluate_euro_ingest_dispatch",
    "evaluate_library_ingest_dispatch",
    "ingest_parity_met",
    "list_library_ingest_maintenance_markets",
    "list_library_ingest_parallel_sprint_markets",
    "list_library_ingest_sprint_markets",
    "load_euro_ingest_dispatch",
    "refresh_euro_ingest_dispatch",
    "snapshot_library_buy_tier_filing_health",
    "write_euro_ingest_dispatch",
]
