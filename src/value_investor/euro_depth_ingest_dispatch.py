"""Completion-gate dispatch for euro_depth weekday ingest and ladder crons."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import DEFAULT_POLICY_PATH, load_policy
from value_investor.data_library import DEFAULT_LIBRARY_ROOT
from value_investor.library_ingest_escalation import snapshot_library_buy_tier_filing_health
from value_investor.market_shard_phases import evaluate_market_phase
from value_investor.storage import read_json, write_json

logger = logging.getLogger(__name__)

DEFAULT_MARKET_ID = "euro_depth"
DEFAULT_DISPATCH_PATH = Path("docs/data/library/euro_ingest_dispatch.json")

MODE_SPRINT = "sprint"
MODE_MAINTENANCE = "maintenance"
MODE_IDLE = "idle"

MODE_CONFIG: dict[str, dict[str, Any]] = {
    MODE_SPRINT: {
        "max_daily_successes": 2,
        "max_targets": 12,
        "cron_morning": True,
        "cron_afternoon": True,
        "cron_ladder_weekday": True,
    },
    MODE_MAINTENANCE: {
        "max_daily_successes": 1,
        "max_targets": 4,
        "cron_morning": True,
        "cron_afternoon": False,
        "cron_ladder_weekday": False,
    },
    MODE_IDLE: {
        "max_daily_successes": 0,
        "max_targets": 0,
        "cron_morning": False,
        "cron_afternoon": False,
        "cron_ladder_weekday": False,
    },
}

EURO_INGEST_CRON_TITLES = {
    "morning": "Euro ingest loop (weekday morning)",
    "afternoon": "Euro ingest loop (weekday afternoon)",
    "ladder_weekday": "FTSE orchestrator (weekday ladder)",
}


def evaluate_euro_ingest_dispatch(
    *,
    market_id: str = DEFAULT_MARKET_ID,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Decide euro_depth ingest cadence from Phase 3 completion + filing parity.

    Modes:
    - sprint: Phase 3 not ready — 2×/day ingest, weekday ladder cron
    - maintenance: Phase 3 ready but filing gaps — 1×/day ingest
    - idle: Phase 3 ready and no unmeasured/zero-body buy-tier gaps — skip ingest
    """
    library_root = Path(library_root)
    policy = policy if policy is not None else load_policy(policy_path)
    phase = evaluate_market_phase(
        market_id,
        library_root=library_root,
        policy=policy,
    )
    health = snapshot_library_buy_tier_filing_health(market_id, library_root=library_root)
    phase3_ready = bool(phase.get("phase3_ready"))
    filing_gaps = int(health.get("unmeasured_buy_tier") or 0) + int(
        health.get("zero_body_buy_tier") or 0
    )

    if phase3_ready and filing_gaps == 0:
        mode = MODE_IDLE
        reason = "Phase 3 complete and buy-tier filing parity met"
    elif phase3_ready:
        mode = MODE_MAINTENANCE
        reason = (
            "Phase 3 complete; filing gaps remain "
            f"(unmeasured={health.get('unmeasured_buy_tier')}, "
            f"zero_body={health.get('zero_body_buy_tier')})"
        )
    else:
        mode = MODE_SPRINT
        blockers = phase.get("blockers") or []
        reason = f"Phase 3 in progress ({len(blockers)} blocker(s))"

    config = dict(MODE_CONFIG[mode])
    return {
        "market_id": market_id,
        "mode": mode,
        "reason": reason,
        "phase3_ready": phase3_ready,
        "phase_blockers": list(phase.get("blockers") or []),
        "filing_health": health,
        "filing_gaps": filing_gaps,
        "max_daily_successes": int(config["max_daily_successes"]),
        "max_targets": int(config["max_targets"]),
        "cron_morning": bool(config["cron_morning"]),
        "cron_afternoon": bool(config["cron_afternoon"]),
        "cron_ladder_weekday": bool(config["cron_ladder_weekday"]),
        "should_run_ingest": mode != MODE_IDLE,
        "evaluated_at": datetime.now(UTC).isoformat(),
    }


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
        "ladder_weekday": bool(evaluation.get("cron_ladder_weekday")),
    }


__all__ = [
    "DEFAULT_DISPATCH_PATH",
    "EURO_INGEST_CRON_TITLES",
    "MODE_CONFIG",
    "MODE_IDLE",
    "MODE_MAINTENANCE",
    "MODE_SPRINT",
    "cron_enabled_for_dispatch",
    "evaluate_euro_ingest_dispatch",
    "load_euro_ingest_dispatch",
    "refresh_euro_ingest_dispatch",
    "snapshot_library_buy_tier_filing_health",
    "write_euro_ingest_dispatch",
]
