"""Runtime P2 ingest scheduler: wait on the head, spend leftover, fill down.

Complements the static cascade fractions. Spare streams pass live workflow
busyness in from GHA; leftover minutes are persisted after the head run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.data_library import DEFAULT_LIBRARY_ROOT
from value_investor.library_ingest_cascade import (
    IngestCascadeConfig,
    evaluate_ingest_cascade,
    head_market_id,
    load_cascade_config,
    scale_spare_budget,
    should_skip_spare_stream,
)
from value_investor.library_ingest_dispatch import (
    PARALLEL_SPRINT_POLICY_KEYS,
    list_library_ingest_parallel_sprint_markets,
)
from value_investor.storage import read_json, write_json

DEFAULT_RUNTIME_STATE_PATH = Path("docs/data/library/ingest_cascade_runtime.json")
FULL_STREAM_TARGETS = 24
FULL_STREAM_RUNTIME = 2100.0


def _parse_dt(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_runtime_state(path: Path | None = None) -> dict[str, Any]:
    path = Path(path or DEFAULT_RUNTIME_STATE_PATH)
    if not path.exists():
        return {"schema_version": 1, "allocations": []}
    try:
        data = read_json(path)
    except (OSError, ValueError):
        return {"schema_version": 1, "allocations": []}
    return data if isinstance(data, dict) else {"schema_version": 1, "allocations": []}


def leftover_seconds(
    state: dict[str, Any] | None,
    *,
    config: IngestCascadeConfig,
    now: datetime | None = None,
) -> float:
    """Remaining leftover seconds from the last head run, or 0 if stale/empty."""
    row = dict((state or {}).get("head_run") or {})
    leftover = float(row.get("leftover_seconds") or 0.0)
    if leftover < config.min_leftover_seconds:
        return 0.0
    finished = _parse_dt(row.get("finished_at"))
    if finished is None:
        return 0.0
    when = now or datetime.now(UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=UTC)
    age = (when - finished.astimezone(UTC)).total_seconds()
    if age < 0 or age > config.leftover_max_age_seconds:
        return 0.0
    claimed = 0.0
    for alloc in list((state or {}).get("allocations") or []):
        if not isinstance(alloc, dict):
            continue
        claimed += float(alloc.get("granted_seconds") or 0.0)
    return max(0.0, leftover - claimed)


def record_head_run(
    *,
    used_seconds: float,
    budget_seconds: float,
    runtime_cutoff: bool,
    head_market: str,
    head_at_parity: bool,
    now: datetime | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Persist leftover minutes after a focus-market ingest run."""
    when = now or datetime.now(UTC)
    used = max(0.0, float(used_seconds))
    budget = max(0.0, float(budget_seconds))
    leftover = 0.0 if runtime_cutoff else max(0.0, budget - used)
    state = {
        "schema_version": 1,
        "updated_at": when.isoformat(),
        "head_market": head_market,
        "head_at_parity": bool(head_at_parity),
        "head_run": {
            "finished_at": when.isoformat(),
            "budget_seconds": budget,
            "used_seconds": used,
            "leftover_seconds": leftover,
            "runtime_cutoff": bool(runtime_cutoff),
        },
        "allocations": [],
    }
    dest = Path(path or DEFAULT_RUNTIME_STATE_PATH)
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_json(dest, state, compact=False)
    return state


def claim_leftover(
    state: dict[str, Any],
    *,
    stream: int,
    granted_seconds: float,
    now: datetime | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Record that a spare stream spent leftover seconds."""
    when = now or datetime.now(UTC)
    allocations = list(state.get("allocations") or [])
    allocations.append(
        {
            "stream": int(stream),
            "at": when.isoformat(),
            "granted_seconds": max(0.0, float(granted_seconds)),
        }
    )
    state["allocations"] = allocations
    state["updated_at"] = when.isoformat()
    dest = Path(path or DEFAULT_RUNTIME_STATE_PATH)
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_json(dest, state, compact=False)
    return state


def fill_down_markets(
    stream: int,
    *,
    policy: dict[str, Any],
    needing: list[str],
) -> list[str]:
    """Assigned stream markets first; if none need work, next queue names with gaps."""
    needing_set = {str(m).strip() for m in needing if str(m).strip()}
    focus = head_market_id(policy)
    assigned = [
        mid
        for mid in list_library_ingest_parallel_sprint_markets(
            policy=policy,
            parallel_stream=stream,
        )
        if mid in needing_set
    ]
    if assigned:
        return assigned
    reserved: set[str] = {focus}
    for other in PARALLEL_SPRINT_POLICY_KEYS:
        if other == stream:
            continue
        reserved.update(
            list_library_ingest_parallel_sprint_markets(
                policy=policy,
                parallel_stream=other,
            )
        )
    filled: list[str] = []
    for mid in list(policy.get("market_queue") or []):
        name = str(mid or "").strip()
        if not name or name in reserved or name not in needing_set:
            continue
        filled.append(name)
    return filled


@dataclass
class IngestSchedulerDecision:
    action: str
    stream: int
    markets: list[str] = field(default_factory=list)
    max_targets: int = FULL_STREAM_TARGETS
    max_runtime_seconds: float = FULL_STREAM_RUNTIME
    leftover_granted: float = 0.0
    wait_seconds: float = 0.0
    reason: str = ""
    code: str = ""
    cascade: dict[str, Any] = field(default_factory=dict)
    budget_mode: str = "full"

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "stream": self.stream,
            "markets": self.markets,
            "max_targets": self.max_targets,
            "max_runtime_seconds": self.max_runtime_seconds,
            "leftover_granted": self.leftover_granted,
            "wait_seconds": self.wait_seconds,
            "reason": self.reason,
            "code": self.code,
            "cascade": self.cascade,
            "budget_mode": self.budget_mode,
        }


def evaluate_scheduler(
    stream: int,
    *,
    policy: dict[str, Any],
    head_at_parity: bool,
    needing_markets: list[str],
    requested_targets: int = FULL_STREAM_TARGETS,
    requested_runtime: float = FULL_STREAM_RUNTIME,
    head_in_progress: bool | None = None,
    higher_spare_in_progress: bool = False,
    phase2_ready: bool = False,
    leftover_state: dict[str, Any] | None = None,
    now: datetime | None = None,
    waited_seconds: float = 0.0,
) -> IngestSchedulerDecision:
    """Decide whether a spare stream should wait, skip, or run — and on what budget."""
    when = now or datetime.now(UTC)
    config = load_cascade_config(policy)
    cascade = evaluate_ingest_cascade(
        policy,
        head_at_parity=head_at_parity,
        now=when,
        phase2_ready=phase2_ready,
    )
    markets = fill_down_markets(stream, policy=policy, needing=needing_markets)
    if not config.enabled or not cascade.head_needs_fat_slot:
        targets, runtime, mode = scale_spare_budget(
            stream,
            requested_targets,
            requested_runtime,
            config=config,
            head_needs_fat=False,
        )
        action = "run" if markets else "skip"
        if not cascade.enabled:
            code = "cascade_off"
            reason = (
                "No markets with filing gaps."
                if action == "skip"
                else "Cascade off — peer budgets."
            )
        elif action == "skip":
            code = "no_gaps"
            reason = "No markets with filing gaps."
        else:
            code = "head_released"
            reason = "Head released the fat slot — spare streams run at full caps."
        return IngestSchedulerDecision(
            action=action,
            stream=stream,
            markets=markets,
            max_targets=targets,
            max_runtime_seconds=runtime,
            budget_mode=mode,
            reason=reason,
            code=code,
            cascade=cascade.to_dict(),
        )

    if config.scheduler_enabled:
        blockers = bool(higher_spare_in_progress) or head_in_progress is True
        if blockers:
            remaining_wait = max(0.0, config.spare_wait_seconds - float(waited_seconds or 0.0))
            if remaining_wait > 0:
                return IngestSchedulerDecision(
                    action="wait",
                    stream=stream,
                    wait_seconds=remaining_wait,
                    reason=(
                        "Head or higher spare stream is still running — "
                        "wait before claiming leftover."
                    ),
                    code="wait_predecessor",
                    cascade=cascade.to_dict(),
                )
            return IngestSchedulerDecision(
                action="skip",
                stream=stream,
                reason="Head or higher spare stream still running after wait — yield the slot.",
                code="yield_after_wait",
                cascade=cascade.to_dict(),
            )

        leftover = leftover_seconds(leftover_state, config=config, now=when)
        spare_targets, spare_runtime, _spare_mode = scale_spare_budget(
            stream,
            requested_targets,
            requested_runtime,
            config=config,
            head_needs_fat=True,
        )
        # Leftover must not shrink the spare slot; it only boosts when larger.
        if leftover >= config.min_leftover_seconds and leftover > spare_runtime:
            runtime = min(float(requested_runtime), leftover)
            frac = runtime / float(requested_runtime) if requested_runtime else 1.0
            targets = max(1, int(round(int(requested_targets) * frac)))
            action = "run" if markets else "skip"
            return IngestSchedulerDecision(
                action=action,
                stream=stream,
                markets=markets,
                max_targets=targets if action == "run" else spare_targets,
                max_runtime_seconds=runtime if action == "run" else spare_runtime,
                leftover_granted=runtime if action == "run" else 0.0,
                budget_mode="leftover",
                reason=(
                    f"Work-conserving leftover {runtime:.0f}s from the head run."
                    if action == "run"
                    else "Leftover exists but no queue market needs ingest."
                ),
                code="leftover" if action == "run" else "no_gaps",
                cascade=cascade.to_dict(),
            )

    # Static fractions. Hour skip is only a fallback when we could not observe
    # whether the head workflow is running (local CLI / no GHA wait).
    if head_in_progress is None and should_skip_spare_stream(
        stream,
        hour_utc=when.astimezone(UTC).hour if when.tzinfo else when.replace(tzinfo=UTC).hour,
        config=config,
        head_needs_fat=True,
    ):
        skip_targets, skip_runtime, _skip_mode = scale_spare_budget(
            stream,
            requested_targets,
            requested_runtime,
            config=config,
            head_needs_fat=True,
        )
        return IngestSchedulerDecision(
            action="skip",
            stream=stream,
            max_targets=skip_targets,
            max_runtime_seconds=skip_runtime,
            reason="Head busyness unknown; stream 2 yields the peak hour as a fallback.",
            code="peak_hour_fallback",
            cascade=cascade.to_dict(),
            budget_mode="spare",
        )

    targets, runtime, mode = scale_spare_budget(
        stream,
        requested_targets,
        requested_runtime,
        config=config,
        head_needs_fat=True,
    )
    action = "run" if markets else "skip"
    return IngestSchedulerDecision(
        action=action,
        stream=stream,
        markets=markets,
        max_targets=targets,
        max_runtime_seconds=runtime,
        budget_mode=mode,
        reason=(
            f"No fresh leftover; spare fraction ({mode})."
            if action == "run"
            else "No markets with filing gaps."
        ),
        code="spare_fraction" if action == "run" else "no_gaps",
        cascade=cascade.to_dict(),
    )


def persist_head_runtime_from_loop(
    *,
    market_id: str,
    used_seconds: float,
    budget_seconds: float,
    runtime_cutoff: bool,
    head_at_parity: bool,
    policy: dict[str, Any] | None,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Write leftover state when this loop was the cascade head market."""
    if market_id != head_market_id(policy):
        return None
    path = Path(library_root) / "ingest_cascade_runtime.json"
    return record_head_run(
        used_seconds=used_seconds,
        budget_seconds=budget_seconds,
        runtime_cutoff=runtime_cutoff,
        head_market=market_id,
        head_at_parity=head_at_parity,
        now=now,
        path=path,
    )


__all__ = [
    "DEFAULT_RUNTIME_STATE_PATH",
    "IngestSchedulerDecision",
    "claim_leftover",
    "evaluate_scheduler",
    "fill_down_markets",
    "leftover_seconds",
    "load_runtime_state",
    "persist_head_runtime_from_loop",
    "record_head_run",
]
