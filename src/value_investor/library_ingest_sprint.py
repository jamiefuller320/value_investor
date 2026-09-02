"""Parallel library ingest sprint runner (non-focus markets with filing gaps)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import DEFAULT_POLICY_PATH, load_policy
from value_investor.data_library import DEFAULT_LIBRARY_ROOT
from value_investor.library_ingest_dispatch import (
    ingest_parity_met,
    list_library_ingest_parallel_sprint_markets,
    should_run_parallel_sprint_ingest,
)
from value_investor.library_ingest_escalation import snapshot_library_buy_tier_filing_health
from value_investor.library_ingest_loop import (
    LibraryIngestLoopResult,
    run_library_ingest_loop,
)

logger = logging.getLogger(__name__)

DEFAULT_PARALLEL_SPRINT_MAX_TARGETS = 24


@dataclass
class LibraryIngestSprintResult:
    markets: list[str] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_at": datetime.now(UTC).isoformat(),
            "markets": self.markets,
            "results": self.results,
            "skipped": self.skipped,
            "errors": self.errors,
        }


def parallel_sprint_markets_needing_ingest(
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    policy: dict[str, Any] | None = None,
    parallel_stream: int = 1,
) -> list[str]:
    """Parallel sprint markets that should receive ingest this run."""
    library_root = Path(library_root)
    policy = policy if policy is not None else load_policy(policy_path)
    needing: list[str] = []
    for market_id in list_library_ingest_parallel_sprint_markets(
        policy=policy,
        parallel_stream=parallel_stream,
    ):
        health = snapshot_library_buy_tier_filing_health(market_id, library_root=library_root)
        if should_run_parallel_sprint_ingest(
            market_id,
            health,
            policy=policy,
            parallel_stream=parallel_stream,
        ):
            needing.append(market_id)
    return needing


def run_library_ingest_sprint(
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    markets: list[str] | None = None,
    max_targets: int = DEFAULT_PARALLEL_SPRINT_MAX_TARGETS,
    max_runtime_seconds: float = 2100.0,
    max_bodies: int = 20,
    parallel_stream: int = 1,
) -> LibraryIngestSprintResult:
    """Run high-tempo sprint ingest for parallel queue markets (not focus)."""
    library_root = Path(library_root)
    policy_path = Path(policy_path)
    try:
        from value_investor.library_ingest_maintenance import reconcile_parallel_sprint_queues

        reconcile_parallel_sprint_queues(
            library_root=library_root,
            policy_path=policy_path,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Parallel sprint queue reconcile failed: %s", exc)

    policy = load_policy(policy_path)
    market_list = markets or parallel_sprint_markets_needing_ingest(
        library_root=library_root,
        policy=policy,
        parallel_stream=parallel_stream,
    )
    outcome = LibraryIngestSprintResult(markets=market_list)
    if not market_list:
        outcome.skipped.append({"reason": "no_parallel_sprint_markets_with_gaps"})
        return outcome

    for market_id in market_list:
        health = snapshot_library_buy_tier_filing_health(market_id, library_root=library_root)
        if not should_run_parallel_sprint_ingest(
            market_id,
            health,
            policy=policy,
            parallel_stream=parallel_stream,
        ):
            outcome.skipped.append(
                {
                    "market_id": market_id,
                    "reason": "parallel_ingest_not_needed",
                }
            )
            continue
        at_parity = ingest_parity_met(health)
        max_for_run = 4 if at_parity else max_targets
        try:
            loop_result: LibraryIngestLoopResult = run_library_ingest_loop(
                market_id,
                library_root=library_root,
                max_targets=max_for_run,
                max_runtime_seconds=max_runtime_seconds,
                max_bodies=max_bodies,
                discovery_scan=at_parity,
                maintenance_mode=at_parity,
            )
            outcome.results.append(loop_result.to_dict())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Library sprint ingest failed for %s: %s", market_id, exc)
            outcome.errors.append(f"{market_id}: {exc}")

    try:
        from value_investor.library_ingest_dispatch import refresh_euro_ingest_dispatch

        refresh_euro_ingest_dispatch(library_root=library_root, policy_path=policy_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dispatch refresh after parallel sprint failed: %s", exc)

    return outcome


__all__ = [
    "DEFAULT_PARALLEL_SPRINT_MAX_TARGETS",
    "LibraryIngestSprintResult",
    "parallel_sprint_markets_needing_ingest",
    "run_library_ingest_sprint",
]
