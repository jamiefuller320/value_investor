"""Unified daily maintenance ingest for library markets at filing parity."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import DEFAULT_POLICY_PATH, load_policy, save_policy
from value_investor.data_library import DEFAULT_LIBRARY_ROOT
from value_investor.library_ingest_dispatch import (
    FTSE_MAINTENANCE_MAX_BODIES,
    FTSE_MAINTENANCE_MAX_RUNTIME_SECONDS,
    FTSE_MAINTENANCE_MAX_TARGETS,
    ingest_parity_met,
    list_library_ingest_maintenance_markets,
)
from value_investor.library_ingest_escalation import snapshot_library_buy_tier_filing_health
from value_investor.library_ingest_loop import (
    LibraryIngestLoopResult,
    run_library_ingest_loop,
)

logger = logging.getLogger(__name__)

DEFAULT_MAINTENANCE_MAX_TARGETS = FTSE_MAINTENANCE_MAX_TARGETS


@dataclass
class LibraryIngestMaintenanceResult:
    markets: list[str] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_at": datetime.now(UTC).isoformat(),
            "markets": self.markets,
            "results": self.results,
            "errors": self.errors,
        }


def record_ingest_parity_market(
    policy: dict[str, Any],
    market_id: str,
) -> dict[str, Any]:
    """Add ``market_id`` to ``ingest_parity_markets`` when parity is met."""
    markets = list(policy.get("ingest_parity_markets") or [])
    if market_id not in markets:
        markets.append(market_id)
        policy["ingest_parity_markets"] = sorted(set(markets))
    return policy


def run_library_ingest_maintenance(
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    markets: list[str] | None = None,
    max_targets: int = DEFAULT_MAINTENANCE_MAX_TARGETS,
    max_runtime_seconds: float = FTSE_MAINTENANCE_MAX_RUNTIME_SECONDS,
    max_bodies: int = FTSE_MAINTENANCE_MAX_BODIES,
    discovery_scan: bool = True,
) -> LibraryIngestMaintenanceResult:
    """Run scan-then-target maintenance for all parity library markets."""
    library_root = Path(library_root)
    policy = load_policy(policy_path)
    market_list = markets or list_library_ingest_maintenance_markets(
        library_root=library_root,
        policy=policy,
    )
    outcome = LibraryIngestMaintenanceResult(markets=market_list)
    if not market_list:
        outcome.errors.append("no parity markets configured for maintenance")
        return outcome

    for market_id in market_list:
        health = snapshot_library_buy_tier_filing_health(market_id, library_root=library_root)
        if not ingest_parity_met(health):
            outcome.errors.append(f"{market_id}: parity lost — skipped maintenance")
            continue
        try:
            loop_result: LibraryIngestLoopResult = run_library_ingest_loop(
                market_id,
                library_root=library_root,
                max_targets=max_targets,
                max_runtime_seconds=max_runtime_seconds,
                max_bodies=max_bodies,
                discovery_scan=discovery_scan,
                maintenance_mode=True,
            )
            outcome.results.append(loop_result.to_dict())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Library maintenance failed for %s: %s", market_id, exc)
            outcome.errors.append(f"{market_id}: {exc}")

    return outcome


def maybe_handoff_focus_on_ingest_parity(
    *,
    market_id: str,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    When focus market reaches ingest parity, record it and optionally advance focus.

    Returns event dict (parity_recorded, focus_advanced, ...).
    """
    from value_investor.library_graduation import (
        apply_graduation,
        evaluate_ingest_parity_handoff,
        maybe_record_ingest_parity,
    )

    library_root = Path(library_root)
    policy = load_policy(policy_path)
    focus = str(policy.get("focus_market") or "")
    if market_id != focus:
        return {"skipped": True, "reason": "not_focus_market", "market_id": market_id}

    health = health or snapshot_library_buy_tier_filing_health(market_id, library_root=library_root)
    if not ingest_parity_met(health):
        return {"skipped": True, "reason": "parity_not_met", "market_id": market_id}

    policy, parity_event = maybe_record_ingest_parity(
        policy,
        market_id,
        library_root=library_root,
        health=health,
    )
    save_policy(policy, policy_path)

    fg = policy.get("focus_graduation") or {}
    if not fg.get("advance_focus_on_ingest_parity", True):
        return {
            "parity_recorded": True,
            "focus_advanced": False,
            "reason": "advance_focus_on_ingest_parity_disabled",
            **parity_event,
        }

    evaluation = evaluate_ingest_parity_handoff(library_root, policy, market_id=market_id)
    if not evaluation.get("can_advance"):
        return {
            "parity_recorded": True,
            "focus_advanced": False,
            "handoff": evaluation,
            **parity_event,
        }

    handoff_eval = {
        "focus_market": evaluation.get("focus_market"),
        "meets_floors": True,
        "auto_advance": evaluation.get("advance_focus_on_ingest_parity", True),
        "can_advance": True,
        "next_focus": evaluation.get("next_focus"),
        "coverage_pct": None,
        "stale_pct": None,
        "ingest_parity_met": True,
    }
    policy, grad_event = apply_graduation(policy, handoff_eval)
    save_policy(policy, policy_path)
    try:
        from value_investor.euro_depth_ingest_dispatch import refresh_euro_ingest_dispatch

        refresh_euro_ingest_dispatch(library_root=library_root, policy_path=policy_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dispatch refresh after parity handoff failed: %s", exc)

    return {
        "parity_recorded": True,
        "focus_advanced": bool(grad_event.get("graduated")),
        "graduation_event": grad_event,
        **parity_event,
    }


__all__ = [
    "DEFAULT_MAINTENANCE_MAX_TARGETS",
    "LibraryIngestMaintenanceResult",
    "maybe_handoff_focus_on_ingest_parity",
    "record_ingest_parity_market",
    "run_library_ingest_maintenance",
]
