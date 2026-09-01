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

# Parallel sprint streams (non-focus): stream 1 at +30 min, stream 2 at +60 min vs focus.
PARALLEL_SPRINT_POLICY_KEYS: dict[int, str] = {
    1: "ingest_parallel_sprint",
    2: "ingest_parallel_sprint_2",
}

MODE_SPRINT = "sprint"
MODE_MAINTENANCE = "maintenance"
# Deprecated alias — parity met maps to maintenance (daily scan+deepen), not zero ingest.
MODE_IDLE = MODE_MAINTENANCE

# Same learning-phase numbers as live FTSE ingest-loop.yml / ingest-scan-then-target.md.
FTSE_MAINTENANCE_MAX_TARGETS = 62
FTSE_MAINTENANCE_MAX_BODIES = 40
FTSE_MAINTENANCE_MAX_RUNTIME_SECONDS = 3600.0
FTSE_MAINTENANCE_MAX_DAILY_SUCCESSES = 8

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
    "max_daily_successes": FTSE_MAINTENANCE_MAX_DAILY_SUCCESSES,
    "max_targets": FTSE_MAINTENANCE_MAX_TARGETS,
    "cron_morning": False,
    "cron_afternoon": False,
    "cron_midafternoon": False,
    "cron_evening": False,
    "cron_ladder_weekday": True,
    "cron_maintenance": True,
}

EURO_INGEST_CRON_TITLES = {
    # Peak slots: Mon–Sat (skip Sunday quiet-bundle morning). Off-peak: daily.
    "morning": "Euro ingest loop (Mon-Sat morning)",
    "afternoon": "Euro ingest loop (Mon-Sat afternoon)",
    "midafternoon": "Euro ingest loop (daily mid-afternoon)",
    "evening": "Euro ingest loop (daily evening)",
    "ladder_weekday": "FTSE orchestrator (weekday ladder)",
    "maintenance": "Library ingest maintenance (Mon-Sat morning)",
    "maintenance_afternoon": "Library ingest maintenance (Mon-Sat afternoon)",
    "maintenance_midafternoon": "Library ingest maintenance (daily mid-afternoon)",
    "maintenance_evening": "Library ingest maintenance (daily evening)",
}


def ingest_parity_met(health: dict[str, Any]) -> bool:
    """True when buy-tier filing quality matches the live FTSE maintenance bar.

    Every library market uses the same gate: unmeasured, zero-body, thin-body,
    and ``indexed_without_body`` must all be zero. ``ftse_equivalent`` only
    changes *measurement* (canonical-only coverage), not the quality bar.
    """
    if library_ingest_filing_gaps(health) != 0:
        return False
    return (
        int(health.get("thin_body_buy_tier") or 0) == 0
        and int(health.get("indexed_without_body") or 0) == 0
    )


def should_run_parallel_sprint_ingest(
    market_id: str,
    health: dict[str, Any],
    *,
    policy: dict[str, Any],
    parallel_stream: int = 1,
) -> bool:
    """Whether a parallel sprint market should run automated ingest."""
    if market_id not in list_library_ingest_parallel_sprint_markets(
        policy=policy,
        parallel_stream=parallel_stream,
    ):
        return False
    return not ingest_parity_met(health)


def evaluate_library_ingest_dispatch(
    market_id: str,
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Decide ingest cadence from **filing parity** on the focus market.

    Sprint (high tempo) while FTSE-standard filing gaps remain; maintenance once
    unmeasured, zero-body, thin-body, and ``indexed_without_body`` are all zero.
    Phase 3 readiness is informational only — ladder/shard crons continue
    separately during maintenance.
    """
    library_root = Path(library_root)
    policy = policy if policy is not None else load_policy(policy_path)
    phase = evaluate_market_phase(
        market_id,
        library_root=library_root,
        policy=policy,
    )
    health = snapshot_library_buy_tier_filing_health(
        market_id,
        library_root=library_root,
        policy=policy,
    )
    gaps = library_ingest_filing_gaps(health)
    parity = ingest_parity_met(health)

    if parity:
        mode = MODE_MAINTENANCE
        reason = (
            "Ingest parity met — focus on daily maintenance; Phase 3 ladder continues separately"
        )
        config = MAINTENANCE_CONFIG
    else:
        mode = MODE_SPRINT
        reason = (
            f"Ingest sprint: FTSE-standard depth gaps "
            f"(unmeasured={health.get('unmeasured_buy_tier')}, "
            f"zero_body={health.get('zero_body_buy_tier')}, "
            f"thin={health.get('thin_body_buy_tier')}, "
            f"indexed_without_body={health.get('indexed_without_body')})"
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


def enrich_library_ingest_dispatch(
    evaluation: dict[str, Any],
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach maintenance + parallel sprint rollup fields to a focus dispatch row."""
    library_root = Path(library_root)
    policy = policy if policy is not None else load_policy(policy_path)
    evaluation["maintenance_markets"] = list_library_ingest_maintenance_markets(
        library_root=library_root,
        policy_path=policy_path,
        policy=policy,
    )
    for parallel_stream in sorted(PARALLEL_SPRINT_POLICY_KEYS):
        suffix = "" if parallel_stream == 1 else f"_{parallel_stream}"
        parallel = list_library_ingest_parallel_sprint_markets(
            policy=policy,
            parallel_stream=parallel_stream,
        )
        evaluation[f"parallel_sprint{suffix}_markets"] = parallel
        parallel_status: list[dict[str, Any]] = []
        for market_id in parallel:
            row = evaluate_library_ingest_dispatch(
                market_id,
                library_root=library_root,
                policy_path=policy_path,
                policy=policy,
            )
            health = row.get("filing_health") or snapshot_library_buy_tier_filing_health(
                market_id,
                library_root=library_root,
            )
            row["should_run_parallel_ingest"] = should_run_parallel_sprint_ingest(
                market_id,
                health,
                policy=policy,
                parallel_stream=parallel_stream,
            )
            parallel_status.append(row)
        evaluation[f"parallel_sprint{suffix}_status"] = parallel_status
    evaluation["sprint_markets"] = list_library_ingest_sprint_markets(
        library_root=library_root,
        policy_path=policy_path,
        policy=policy,
    )
    evaluation["market_queue"] = list(policy.get("market_queue") or [])
    return evaluation


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
    evaluation = evaluate_library_ingest_dispatch(
        target,
        library_root=library_root,
        policy_path=policy_path,
        policy=policy,
    )
    return enrich_library_ingest_dispatch(
        evaluation,
        library_root=library_root,
        policy_path=policy_path,
        policy=policy,
    )


def list_library_ingest_parallel_sprint_markets(
    *,
    policy: dict[str, Any] | None = None,
    policy_path: Path = DEFAULT_POLICY_PATH,
    parallel_stream: int = 1,
) -> list[str]:
    """
    Markets in a parallel sprint stream that run ingest alongside focus.

    Focus market sprint is handled by ``euro-ingest-loop.yml``; stream 1/2 lists
    front-start queue markets (e.g. sp500, asx200 while euro_depth finishes).
    """
    policy = policy if policy is not None else load_policy(policy_path)
    focus = str(policy.get("focus_market") or "").strip()
    policy_key = PARALLEL_SPRINT_POLICY_KEYS.get(parallel_stream, "ingest_parallel_sprint")
    parallel = [str(m).strip() for m in (policy.get(policy_key) or []) if str(m).strip()]
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
        health = snapshot_library_buy_tier_filing_health(
            focus,
            library_root=library_root,
            policy=policy,
        )
        if not ingest_parity_met(health):
            markets.append(focus)
    for parallel_stream in sorted(PARALLEL_SPRINT_POLICY_KEYS):
        for market_id in list_library_ingest_parallel_sprint_markets(
            policy=policy,
            parallel_stream=parallel_stream,
        ):
            if market_id in markets:
                continue
            health = snapshot_library_buy_tier_filing_health(
                market_id,
                library_root=library_root,
                policy=policy,
            )
            if not ingest_parity_met(health):
                markets.append(market_id)
    return markets


def list_library_ingest_maintenance_markets(
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    policy: dict[str, Any] | None = None,
) -> list[str]:
    """Markets that currently meet the FTSE filing-quality bar."""
    library_root = Path(library_root)
    policy = policy if policy is not None else load_policy(policy_path)
    candidates: set[str] = {
        str(m).strip() for m in (policy.get("ingest_parity_markets") or []) if str(m).strip()
    }
    focus = str(policy.get("focus_market") or "").strip()
    if focus:
        candidates.add(focus)
    markets: list[str] = []
    for market_id in sorted(candidates):
        health = snapshot_library_buy_tier_filing_health(
            market_id,
            library_root=library_root,
            policy=policy,
        )
        if ingest_parity_met(health):
            markets.append(market_id)
    return markets


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
    maintenance = bool(evaluation.get("cron_maintenance"))
    return {
        "morning": bool(evaluation.get("cron_morning")),
        "afternoon": bool(evaluation.get("cron_afternoon")),
        "midafternoon": bool(evaluation.get("cron_midafternoon")),
        "evening": bool(evaluation.get("cron_evening")),
        "ladder_weekday": bool(evaluation.get("cron_ladder_weekday")),
        "maintenance": maintenance,
        "maintenance_afternoon": maintenance,
        "maintenance_midafternoon": maintenance,
        "maintenance_evening": maintenance,
    }


__all__ = [
    "DEFAULT_DISPATCH_PATH",
    "PARALLEL_SPRINT_POLICY_KEYS",
    "EURO_INGEST_CRON_TITLES",
    "FTSE_MAINTENANCE_MAX_BODIES",
    "FTSE_MAINTENANCE_MAX_DAILY_SUCCESSES",
    "FTSE_MAINTENANCE_MAX_RUNTIME_SECONDS",
    "FTSE_MAINTENANCE_MAX_TARGETS",
    "MAINTENANCE_CONFIG",
    "MODE_IDLE",
    "MODE_MAINTENANCE",
    "MODE_SPRINT",
    "SPRINT_CONFIG",
    "cron_enabled_for_dispatch",
    "evaluate_euro_ingest_dispatch",
    "evaluate_library_ingest_dispatch",
    "enrich_library_ingest_dispatch",
    "ingest_parity_met",
    "list_library_ingest_maintenance_markets",
    "list_library_ingest_parallel_sprint_markets",
    "list_library_ingest_sprint_markets",
    "load_euro_ingest_dispatch",
    "refresh_euro_ingest_dispatch",
    "should_run_parallel_sprint_ingest",
    "snapshot_library_buy_tier_filing_health",
    "write_euro_ingest_dispatch",
]
