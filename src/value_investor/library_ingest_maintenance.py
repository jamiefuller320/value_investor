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
    INGEST_EXHAUSTED_MARKETS_KEY,
    ensure_market_queue_membership,
    ingest_parity_met,
    list_library_ingest_maintenance_markets,
    list_library_ingest_parallel_sprint_markets,
    next_parallel_sprint_queue_market,
    parallel_sprint_stream_for_market,
    replace_parallel_sprint_market,
    should_keep_on_library_maintenance,
    sprint_ingest_complete,
)
from value_investor.library_ingest_escalation import (
    is_ftse_equivalent_market,
    snapshot_library_buy_tier_filing_health,
)
from value_investor.library_ingest_loop import (
    LibraryIngestLoopResult,
    run_library_ingest_loop,
)
from value_investor.library_maintenance_stagger import (
    plan_maintenance_slot,
    write_maintenance_slot_cursor,
)

logger = logging.getLogger(__name__)

DEFAULT_MAINTENANCE_MAX_TARGETS = FTSE_MAINTENANCE_MAX_TARGETS
# Match Overview sprint-tile stale-screen threshold (market_status.STALE_SCREEN_AFTER_DAYS).
BUY_TIER_SCREEN_MAX_AGE_DAYS = 8


def _parse_screen_run_at(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def refresh_buy_tier_screen_for_sprint_entry(
    library_root: Path,
    market_id: str,
    *,
    force: bool = False,
    max_age_days: int = BUY_TIER_SCREEN_MAX_AGE_DAYS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Refresh screen-lite so sprint ingest deepens a current buy-tier shortlist.

    Called when a market enters a parallel sprint slot (advance / reseed) and again
    at the start of a sprint ingest run when the archive clock is already stale.
    Failures are non-fatal — ingest still proceeds on the last shortlist.
    """
    mid = str(market_id or "").strip()
    if not mid:
        return {"skipped": True, "reason": "empty_market_id"}
    library_root = Path(library_root)
    as_of = now if now is not None else datetime.now(UTC)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)

    from value_investor.library_screen import run_library_screen, screen_dir_for
    from value_investor.storage import read_json

    summary_path = screen_dir_for(library_root, mid) / "latest_summary.json"
    last_screen_at: datetime | None = None
    if summary_path.exists():
        try:
            payload = read_json(summary_path)
        except Exception:  # noqa: BLE001 — treat unreadable summary as missing
            payload = {}
        if isinstance(payload, dict):
            last_screen_at = _parse_screen_run_at(payload.get("run_at"))

    age_days: int | None = None
    if last_screen_at is not None:
        age_days = (as_of.date() - last_screen_at.date()).days
    stale = last_screen_at is None or age_days is None or age_days > max_age_days
    if not force and not stale:
        return {
            "skipped": True,
            "reason": "screen_fresh",
            "market_id": mid,
            "last_screen_at": last_screen_at.isoformat() if last_screen_at else None,
            "age_days": age_days,
        }

    try:
        result = run_library_screen(library_root, mid, run_at=as_of)
    except Exception as exc:  # noqa: BLE001 — entry must not fail on screen errors
        logger.warning("Sprint-entry screen-lite for %s failed: %s", mid, exc)
        return {
            "refreshed": False,
            "market_id": mid,
            "error": str(exc),
            "last_screen_at": last_screen_at.isoformat() if last_screen_at else None,
            "age_days": age_days,
        }

    summary = result.summary if isinstance(result.summary, dict) else {}
    return {
        "refreshed": True,
        "market_id": mid,
        "forced": force,
        "prior_screen_at": last_screen_at.isoformat() if last_screen_at else None,
        "prior_age_days": age_days,
        "run_at": summary.get("run_at") or as_of.isoformat(),
        "shortlist_count": summary.get("shortlist_count"),
        "ticker_count": summary.get("ticker_count"),
    }


@dataclass
class LibraryIngestMaintenanceResult:
    markets: list[str] = field(default_factory=list)
    configured_markets: list[str] = field(default_factory=list)
    deferred_markets: list[str] = field(default_factory=list)
    stagger: dict[str, Any] = field(default_factory=dict)
    results: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_at": datetime.now(UTC).isoformat(),
            "markets": self.markets,
            "configured_markets": self.configured_markets,
            "deferred_markets": self.deferred_markets,
            "stagger": self.stagger,
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


def record_ingest_exhausted_market(
    policy: dict[str, Any],
    market_id: str,
) -> dict[str, Any]:
    """Add ``market_id`` to ``ingest_exhausted_markets`` for leftover-gap maintenance."""
    markets = list(policy.get(INGEST_EXHAUSTED_MARKETS_KEY) or [])
    if market_id not in markets:
        markets.append(market_id)
        policy[INGEST_EXHAUSTED_MARKETS_KEY] = sorted(set(markets))
    return policy


def maybe_record_exhausted_maintenance(
    *,
    market_id: str,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record an exhausted market for FTSE-volume maintenance on unparked names.

    Does **not** add the market to ``ingest_parity_markets`` (raw all-four-zero
    plus, for FTSE-equivalent markets, ``learning_ready``).
    """
    library_root = Path(library_root)
    policy = load_policy(policy_path)
    health = health or snapshot_library_buy_tier_filing_health(
        market_id,
        library_root=library_root,
        policy=policy,
    )
    if ingest_parity_met(health):
        return {"skipped": True, "reason": "true_parity", "market_id": market_id}
    if not health.get("ingest_exhausted"):
        return {"skipped": True, "reason": "not_exhausted", "market_id": market_id}

    before = list(policy.get(INGEST_EXHAUSTED_MARKETS_KEY) or [])
    policy = record_ingest_exhausted_market(policy, market_id)
    after = list(policy.get(INGEST_EXHAUSTED_MARKETS_KEY) or [])
    first_time = market_id not in before
    from value_investor.market_shard_admission import admit_market_to_learning

    admitted_changed = admit_market_to_learning(policy, market_id)
    if after != before or admitted_changed:
        save_policy(policy, policy_path)
    return {
        "recorded": True,
        "first_time": first_time,
        "market_id": market_id,
        "ingest_exhausted_markets": after,
        "learning_admitted": True,
        "learning_admitted_changed": admitted_changed,
    }


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
    """Run scan-then-target maintenance for parity and exhausted leftover markets."""
    library_root = Path(library_root)
    policy = load_policy(policy_path)
    configured = markets or list_library_ingest_maintenance_markets(
        library_root=library_root,
        policy=policy,
    )
    explicit = markets is not None
    stagger = (
        {
            "staggered": False,
            "reason": "explicit_markets",
            "configured": list(configured),
            "selected": list(configured),
            "deferred": [],
        }
        if explicit
        else plan_maintenance_slot(configured, library_root=library_root)
    )
    market_list = list(stagger.get("selected") or [])
    outcome = LibraryIngestMaintenanceResult(
        markets=market_list,
        configured_markets=list(stagger.get("configured") or configured),
        deferred_markets=list(stagger.get("deferred") or []),
        stagger=stagger,
    )
    if not market_list:
        outcome.errors.append("no maintenance markets configured")
        return outcome

    for market_id in market_list:
        health = snapshot_library_buy_tier_filing_health(market_id, library_root=library_root)
        if not should_keep_on_library_maintenance(market_id, health, policy=policy):
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

    if stagger.get("staggered") and market_list:
        try:
            write_maintenance_slot_cursor(
                library_root,
                last_head=market_list[-1],
                selected=market_list,
                deferred=list(stagger.get("deferred") or []),
            )
        except OSError as exc:
            logger.warning("Maintenance slot cursor write failed: %s", exc)

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


def _parallel_sprint_advance_enabled(policy: dict[str, Any]) -> bool:
    fg = policy.get("focus_graduation") or {}
    return bool(fg.get("advance_parallel_sprint_on_ingest_parity", True))


def _record_parallel_parity_for_maintenance(
    policy: dict[str, Any],
    market_id: str,
    *,
    library_root: Path,
    health: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Record parity for maintenance; FTSE-equivalent markets wait for learning_ready."""
    from value_investor.library_graduation import maybe_record_ingest_parity
    from value_investor.library_learning_depth import assess_library_learning_depth

    if is_ftse_equivalent_market(market_id, policy):
        depth = assess_library_learning_depth(
            market_id,
            library_root=library_root,
            policy=policy,
        )
        if not depth.get("learning_ready"):
            return policy, {
                "recorded": False,
                "reason": "learning_depth_not_ready",
                "market_id": market_id,
                "learning_ready": False,
                "filing_ready": depth.get("filing_ready"),
            }
    return maybe_record_ingest_parity(
        policy,
        market_id,
        library_root=library_root,
        health=health,
    )


def maybe_advance_parallel_sprint_on_parity(
    *,
    market_id: str,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    When a parallel sprint market reaches filing parity **or** leftover thin/IWB
    names are parked as exhausted, record ``ingest_parity_markets`` only on true
    parity (exhausted leftovers go to ``ingest_exhausted_markets`` for unparked
    maintenance) and promote the next ``market_queue`` market into the same slot.
    """
    library_root = Path(library_root)
    policy = load_policy(policy_path)
    parallel_stream = parallel_sprint_stream_for_market(market_id, policy=policy)
    if parallel_stream is None:
        return {"skipped": True, "reason": "not_parallel_sprint_market", "market_id": market_id}

    health = health or snapshot_library_buy_tier_filing_health(market_id, library_root=library_root)
    if not sprint_ingest_complete(health):
        return {"skipped": True, "reason": "parity_not_met", "market_id": market_id}

    if not _parallel_sprint_advance_enabled(policy):
        return {
            "skipped": True,
            "reason": "advance_parallel_sprint_on_ingest_parity_disabled",
            "market_id": market_id,
        }

    from value_investor.market_shard_admission import admit_market_to_learning

    if ingest_parity_met(health):
        policy, parity_event = _record_parallel_parity_for_maintenance(
            policy,
            market_id,
            library_root=library_root,
            health=health,
        )
    else:
        policy = record_ingest_exhausted_market(policy, market_id)
        parity_event = {
            "recorded": False,
            "reason": "ingest_exhausted_leftover_gaps",
            "market_id": market_id,
            "ingest_exhausted": True,
            "exhausted_maintenance_recorded": True,
            "parked_tickers": list(health.get("parked_tickers") or []),
        }
    # L322: vacating the sprint at maintenance threshold flips learning resource.
    parity_event["learning_admitted_changed"] = admit_market_to_learning(policy, market_id)
    parity_event["learning_admitted"] = True
    nxt = next_parallel_sprint_queue_market(
        policy,
        library_root=library_root,
        vacating=market_id,
    )
    if nxt:
        ensure_market_queue_membership(policy, nxt)
    policy, stream_after = replace_parallel_sprint_market(
        policy,
        parallel_stream=parallel_stream,
        from_market=market_id,
        to_market=nxt,
    )
    history = list((policy.get("parallel_sprint_graduation") or {}).get("history") or [])
    event_row = {
        "at": datetime.now(UTC).isoformat(),
        "parallel_stream": parallel_stream,
        "from_market": market_id,
        "to_market": nxt,
        "stream_markets_after": list(stream_after),
        "ingest_parity_recorded": bool(parity_event.get("recorded")),
    }
    history.append(event_row)
    policy["parallel_sprint_graduation"] = {
        **(policy.get("parallel_sprint_graduation") or {}),
        "history": history[-50:],
    }
    save_policy(policy, policy_path)

    try:
        from value_investor.library_ingest_dispatch import refresh_euro_ingest_dispatch

        refresh_euro_ingest_dispatch(library_root=library_root, policy_path=policy_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dispatch refresh after parallel sprint handoff failed: %s", exc)

    screen_refresh: dict[str, Any] | None = None
    if nxt:
        screen_refresh = refresh_buy_tier_screen_for_sprint_entry(
            library_root,
            nxt,
            force=True,
        )

    return {
        "advanced": True,
        "parallel_stream": parallel_stream,
        "from_market": market_id,
        "to_market": nxt,
        "stream_markets_after": stream_after,
        "parity_event": parity_event,
        "screen_refresh": screen_refresh,
        **event_row,
    }


def reseed_empty_parallel_sprint_slots(
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
) -> list[dict[str, Any]]:
    """Assign ``market_queue`` names into empty parallel sprint streams in order.

    When handoffs clear ``ingest_parallel_sprint`` / ``_2`` and a queue market
    later regaps (or was skipped), fill-down alone does not update policy.
    Reseed restores visible cascade rotation so auto-advance can run again.
    """
    library_root = Path(library_root)
    policy = load_policy(policy_path)
    if not _parallel_sprint_advance_enabled(policy):
        return []

    events: list[dict[str, Any]] = []
    changed = False
    for parallel_stream in (1, 2):
        if list_library_ingest_parallel_sprint_markets(
            policy=policy,
            parallel_stream=parallel_stream,
        ):
            continue
        nxt = next_parallel_sprint_queue_market(
            policy,
            library_root=library_root,
        )
        if not nxt:
            continue
        queue_appended = ensure_market_queue_membership(policy, nxt)
        policy, stream_after = replace_parallel_sprint_market(
            policy,
            parallel_stream=parallel_stream,
            from_market=nxt,
            to_market=nxt,
        )
        changed = True
        event_row: dict[str, Any] = {
            "reseeded": True,
            "market_queue_appended": queue_appended,
            "at": datetime.now(UTC).isoformat(),
            "parallel_stream": parallel_stream,
            "from_market": None,
            "to_market": nxt,
            "stream_markets_after": list(stream_after),
            "ingest_parity_recorded": False,
        }
        history = list((policy.get("parallel_sprint_graduation") or {}).get("history") or [])
        history.append(event_row)
        policy["parallel_sprint_graduation"] = {
            **(policy.get("parallel_sprint_graduation") or {}),
            "history": history[-50:],
        }
        event_row["screen_refresh"] = refresh_buy_tier_screen_for_sprint_entry(
            library_root,
            nxt,
            force=True,
        )
        events.append(event_row)

    if not changed:
        return events

    save_policy(policy, policy_path)
    try:
        from value_investor.library_ingest_dispatch import refresh_euro_ingest_dispatch

        refresh_euro_ingest_dispatch(
            library_root=library_root,
            policy_path=policy_path,
            reconcile_parallel=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dispatch refresh after parallel sprint reseed failed: %s", exc)
    return events


def reconcile_parallel_sprint_queues(
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
) -> list[dict[str, Any]]:
    """Advance any parallel sprint markets already at parity before a sprint run."""
    library_root = Path(library_root)
    policy = load_policy(policy_path)
    if not _parallel_sprint_advance_enabled(policy):
        return []

    events: list[dict[str, Any]] = []
    for parallel_stream in (1, 2):
        for market_id in list_library_ingest_parallel_sprint_markets(
            policy=policy,
            parallel_stream=parallel_stream,
        ):
            health = snapshot_library_buy_tier_filing_health(
                market_id,
                library_root=library_root,
            )
            if not sprint_ingest_complete(health):
                continue
            event = maybe_advance_parallel_sprint_on_parity(
                market_id=market_id,
                library_root=library_root,
                policy_path=policy_path,
                health=health,
            )
            if event.get("advanced"):
                events.append(event)
                policy = load_policy(policy_path)
    events.extend(
        reseed_empty_parallel_sprint_slots(
            library_root=library_root,
            policy_path=policy_path,
        )
    )
    return events


__all__ = [
    "BUY_TIER_SCREEN_MAX_AGE_DAYS",
    "DEFAULT_MAINTENANCE_MAX_TARGETS",
    "LibraryIngestMaintenanceResult",
    "maybe_advance_parallel_sprint_on_parity",
    "maybe_handoff_focus_on_ingest_parity",
    "maybe_record_exhausted_maintenance",
    "reconcile_parallel_sprint_queues",
    "refresh_buy_tier_screen_for_sprint_entry",
    "reseed_empty_parallel_sprint_slots",
    "record_ingest_exhausted_market",
    "record_ingest_parity_market",
    "run_library_ingest_maintenance",
]
