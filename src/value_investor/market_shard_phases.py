"""Phase gates and advancement triggers for market-sharded learning stacks."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.library_screen import screen_dir_for
from value_investor.library_sim import (
    MARKET_BENCHMARKS,
    benchmark_for_market,
    iter_library_screen_runs,
)
from value_investor.storage import read_json, write_json

PHASE_OBSERVE = 1
PHASE_WEEKLY_PAPER = 2
PHASE_WEEKDAY_PAPER = 3
PHASE_LIVE_SCREEN = 4

PHASE1_MIN_SCREEN_ARCHIVES = 12
PHASE2_MIN_WEEKLY_BATCHES = 8
PHASE3_MIN_WEEKDAY_BATCHES = 8
PHASE3_MIN_EXIT_SHADOW_CLOSED = 15
PHASE2_AI_BEAT_RULES_SNAPSHOTS = 8
DEFAULT_WEEKLY_PAPER_SHARD_CAPACITY = 2

DEFAULT_SHARD_ROOT = Path("docs/data/paper_automation/markets")
DEFAULT_LIBRARY_ROOT = Path("docs/data/library")
COMMITTED_PHASES_PATH = Path("docs/data/library/shard_phases.json")


def _ladder_cfg(policy: dict[str, Any] | None) -> dict[str, Any]:
    return (policy or {}).get("ladder") or {}


def phase1_min_archives_for_policy(policy: dict[str, Any] | None = None) -> int:
    raw = _ladder_cfg(policy).get("phase1_min_screen_archives", PHASE1_MIN_SCREEN_ARCHIVES)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return PHASE1_MIN_SCREEN_ARCHIVES


def phase2_min_weekly_batches_for_policy(policy: dict[str, Any] | None = None) -> int:
    raw = _ladder_cfg(policy).get("phase2_min_weekly_batches", PHASE2_MIN_WEEKLY_BATCHES)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return PHASE2_MIN_WEEKLY_BATCHES


def phase3_min_weekday_batches_for_policy(policy: dict[str, Any] | None = None) -> int:
    raw = _ladder_cfg(policy).get("phase3_min_weekday_batches", PHASE3_MIN_WEEKDAY_BATCHES)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return PHASE3_MIN_WEEKDAY_BATCHES


def phase3_min_exit_shadow_closed_for_policy(policy: dict[str, Any] | None = None) -> int:
    raw = _ladder_cfg(policy).get("phase3_min_exit_shadow_closed", PHASE3_MIN_EXIT_SHADOW_CLOSED)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return PHASE3_MIN_EXIT_SHADOW_CLOSED


def weekday_paper_shard_enabled_for_policy(policy: dict[str, Any] | None = None) -> bool:
    return bool(_ladder_cfg(policy).get("weekday_paper_shard_after_weekly", False))


def shard_root_for_market(
    market_id: str,
    *,
    base: Path = DEFAULT_SHARD_ROOT,
) -> Path:
    return Path(base) / str(market_id)


def count_screen_archives(library_root: Path, market_id: str) -> int:
    screen_dir = screen_dir_for(library_root, market_id)
    return len(iter_library_screen_runs(screen_dir))


def observe_snapshot_count(library_root: Path, market_id: str) -> int:
    path = screen_dir_for(library_root, market_id) / "sim" / "observe_summary.json"
    if not path.exists():
        return 0
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return 0
    return int(payload.get("snapshot_count") or 0)


def ai_beat_rules_on_observe_sim(library_root: Path, market_id: str) -> bool | None:
    """True when AI-judgment excess beats rules on the latest observe sim (if comparable)."""
    path = screen_dir_for(library_root, market_id) / "sim" / "observe_summary.json"
    if not path.exists():
        return None
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return None
    tracks = payload.get("tracks") or {}
    ai = tracks.get("ai_judgment") or {}
    rules = tracks.get("screen_rules") or {}
    ai_excess = ai.get("excess_return")
    rules_excess = rules.get("excess_return")
    if ai_excess is None or rules_excess is None:
        return None
    return float(ai_excess) > float(rules_excess)


def weekly_paper_shard_capacity_for_policy(policy: dict[str, Any]) -> int:
    ladder = policy.get("ladder") or {}
    raw = ladder.get("weekly_paper_shard_capacity")
    if raw is None:
        return DEFAULT_WEEKLY_PAPER_SHARD_CAPACITY
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_WEEKLY_PAPER_SHARD_CAPACITY


def weekly_paper_shard_markets_for_policy(policy: dict[str, Any]) -> list[str]:
    ladder = policy.get("ladder") or {}
    if not ladder.get("weekly_paper_shard_after_screen", True):
        return []
    configured = ladder.get("weekly_paper_shard_markets")
    if not configured:
        return []
    markets = [str(mid) for mid in configured if str(mid).strip()]
    capacity = weekly_paper_shard_capacity_for_policy(policy)
    if capacity > 0:
        markets = markets[:capacity]
    return markets


def phase1_gate_met(
    library_root: Path,
    market_id: str,
    *,
    min_archives: int | None = None,
    policy: dict[str, Any] | None = None,
    require_ai_beat_rules: bool | None = None,
) -> tuple[bool, dict[str, Any]]:
    min_required = (
        min_archives if min_archives is not None else phase1_min_archives_for_policy(policy)
    )
    archives = count_screen_archives(library_root, market_id)
    snapshots = observe_snapshot_count(library_root, market_id)
    ai_beat_rules = ai_beat_rules_on_observe_sim(library_root, market_id)
    if require_ai_beat_rules is None:
        ladder = (policy or {}).get("ladder") or {}
        require_ai_beat_rules = bool(ladder.get("phase1_require_ai_beat_rules", True))
    ok = archives >= min_required and snapshots >= min_required
    if require_ai_beat_rules and ai_beat_rules is False:
        ok = False
    return ok, {
        "screen_archives": archives,
        "observe_snapshot_count": snapshots,
        "min_archives": min_required,
        "ai_beat_rules_observe_sim": ai_beat_rules,
        "phase1_require_ai_beat_rules": require_ai_beat_rules,
    }


def load_weekly_batch_log(shard_root: Path) -> list[dict[str, Any]]:
    path = Path(shard_root) / "weekly_batch_log.json"
    if not path.exists():
        return []
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return []
    return list(payload.get("entries") or [])


def phase2_gate_met(
    shard_root: Path,
    *,
    policy: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any]]:
    min_batches = phase2_min_weekly_batches_for_policy(policy)
    entries = load_weekly_batch_log(shard_root)
    count = len(entries)
    review_path = Path(shard_root) / "learning_tracks_review.json"
    beat_control = None
    if review_path.exists():
        try:
            review = read_json(review_path)
            beat_control = review.get("beat_control")
        except (OSError, ValueError, TypeError):
            beat_control = None
    ok = count >= min_batches and beat_control is True
    return ok, {
        "weekly_batch_count": count,
        "min_weekly_batches": min_batches,
        "beat_control_latest": beat_control,
    }


def load_weekday_batch_log(shard_root: Path) -> list[dict[str, Any]]:
    path = Path(shard_root) / "weekday_batch_log.json"
    if not path.exists():
        return []
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return []
    return list(payload.get("entries") or [])


def exit_shadow_closed_count(shard_root: Path, *, track_id: str = "ai_judgment") -> int:
    from value_investor.exit_shadow import load_exit_shadow

    shadow_path = Path(shard_root) / track_id / "exit_shadow.json"
    store = load_exit_shadow(shadow_path)
    return sum(1 for row in store.get("records") or [] if str(row.get("status") or "") == "closed")


def phase3_gate_met(
    shard_root: Path,
    *,
    policy: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any]]:
    min_batches = phase3_min_weekday_batches_for_policy(policy)
    min_exit_shadow = phase3_min_exit_shadow_closed_for_policy(policy)
    entries = load_weekday_batch_log(shard_root)
    count = len(entries)
    closed = exit_shadow_closed_count(shard_root)
    ok = count >= min_batches
    if min_exit_shadow > 0:
        ok = ok and closed >= min_exit_shadow
    return ok, {
        "weekday_batch_count": count,
        "min_weekday_batches": min_batches,
        "exit_shadow_closed": closed,
        "min_exit_shadow_closed": min_exit_shadow,
    }


def append_weekday_batch_log(
    shard_root: Path,
    entry: dict[str, Any],
    *,
    keep: int = 52,
) -> dict[str, Any]:
    shard_root = Path(shard_root)
    path = shard_root / "weekday_batch_log.json"
    payload: dict[str, Any]
    if path.exists():
        try:
            payload = read_json(path)
        except (OSError, ValueError, TypeError):
            payload = {"entries": []}
    else:
        payload = {"entries": []}
    entries = list(payload.get("entries") or [])
    entries.append(entry)
    payload["entries"] = entries[-max(1, int(keep)) :]
    payload["updated_at"] = datetime.now(UTC).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, payload, compact=False)
    return payload


def evaluate_market_phase(
    market_id: str,
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    shard_root: Path | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate current phase, gates, blockers, and recommended next phase."""
    library_root = Path(library_root)
    shard_root = Path(shard_root or shard_root_for_market(market_id))
    policy = policy or {}

    p1_ok, p1_detail = phase1_gate_met(library_root, market_id, policy=policy)
    p2_ok, p2_detail = phase2_gate_met(shard_root, policy=policy)
    p3_ok, p3_detail = phase3_gate_met(shard_root, policy=policy)
    in_weekly_policy = market_id in weekly_paper_shard_markets_for_policy(policy)
    weekday_enabled = weekday_paper_shard_enabled_for_policy(policy)

    if market_id not in MARKET_BENCHMARKS:
        current = 0
        blockers = [f"no benchmark configured for {market_id}"]
    elif not p1_ok:
        current = PHASE_OBSERVE
        blockers = []
        min_archives = p1_detail["min_archives"]
        if p1_detail["screen_archives"] < min_archives:
            blockers.append(
                f"need {min_archives} screen archives (have {p1_detail['screen_archives']})"
            )
        if p1_detail["observe_snapshot_count"] < min_archives:
            blockers.append(
                f"need {min_archives} observe snapshots "
                f"(have {p1_detail['observe_snapshot_count']})"
            )
        if (
            p1_detail.get("phase1_require_ai_beat_rules", True)
            and p1_detail.get("ai_beat_rules_observe_sim") is False
        ):
            blockers.append("AI-judgment must beat rules on observe sim before Phase 2")
    elif not in_weekly_policy:
        current = PHASE_OBSERVE
        blockers = [f"{market_id} not in ladder.weekly_paper_shard_markets"]
        p2_ok = False
    elif not p2_ok:
        current = PHASE_WEEKLY_PAPER
        blockers = []
        if p2_detail["weekly_batch_count"] < p2_detail["min_weekly_batches"]:
            blockers.append(
                f"need {p2_detail['min_weekly_batches']} weekly batch marks "
                f"(have {p2_detail['weekly_batch_count']})"
            )
        if p2_detail.get("beat_control_latest") is False:
            blockers.append("primary track must beat rules control on latest review")
        elif p2_detail.get("beat_control_latest") is None:
            blockers.append("learning_tracks_review missing or inconclusive")
    elif weekday_enabled and not p3_ok:
        current = PHASE_WEEKDAY_PAPER
        blockers = []
        if p3_detail["weekday_batch_count"] < p3_detail["min_weekday_batches"]:
            blockers.append(
                f"need {p3_detail['min_weekday_batches']} weekday batch marks "
                f"(have {p3_detail['weekday_batch_count']})"
            )
        min_exit = int(p3_detail.get("min_exit_shadow_closed") or 0)
        closed = int(p3_detail.get("exit_shadow_closed") or 0)
        if min_exit > 0 and closed < min_exit:
            blockers.append(f"need {min_exit} closed exit-shadow episodes (have {closed})")
    elif weekday_enabled and p3_ok:
        current = PHASE_WEEKDAY_PAPER
        blockers = []
    else:
        current = PHASE_WEEKDAY_PAPER
        blockers = [
            "Phase 3 weekday shard not wired — enable ladder.weekday_paper_shard_after_weekly"
        ]

    if current >= PHASE_WEEKDAY_PAPER and p3_ok:
        next_phase = PHASE_LIVE_SCREEN
    elif current >= PHASE_WEEKDAY_PAPER and p2_ok:
        next_phase = PHASE_LIVE_SCREEN if p3_ok else PHASE_WEEKDAY_PAPER
    elif current >= PHASE_WEEKLY_PAPER and p2_ok:
        next_phase = PHASE_WEEKDAY_PAPER
    elif p1_ok and in_weekly_policy:
        next_phase = PHASE_WEEKLY_PAPER
    else:
        next_phase = PHASE_OBSERVE if current <= PHASE_OBSERVE else current + 1

    return {
        "market_id": market_id,
        "benchmark_ticker": benchmark_for_market(market_id),
        "current_phase": current,
        "next_phase": next_phase,
        "phase1_ready": p1_ok,
        "phase2_ready": p2_ok,
        "phase3_ready": p3_ok,
        "weekly_paper_enabled": in_weekly_policy,
        "weekday_paper_enabled": weekday_enabled,
        "phase1": p1_detail,
        "phase2": p2_detail,
        "phase3": p3_detail,
        "blockers": blockers,
        "evaluated_at": datetime.now(UTC).isoformat(),
    }


def append_weekly_batch_log(
    shard_root: Path,
    entry: dict[str, Any],
    *,
    keep: int = 52,
) -> dict[str, Any]:
    shard_root = Path(shard_root)
    path = shard_root / "weekly_batch_log.json"
    payload: dict[str, Any]
    if path.exists():
        try:
            payload = read_json(path)
        except (OSError, ValueError, TypeError):
            payload = {"entries": []}
    else:
        payload = {"entries": []}
    entries = list(payload.get("entries") or [])
    entries.append(entry)
    payload["entries"] = entries[-max(1, int(keep)) :]
    payload["updated_at"] = datetime.now(UTC).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, payload, compact=False)
    return payload


def write_market_phase_status(
    evaluation: dict[str, Any],
    *,
    shard_root: Path | None = None,
) -> Path:
    shard_root = Path(shard_root or shard_root_for_market(str(evaluation.get("market_id") or "")))
    shard_root.mkdir(parents=True, exist_ok=True)
    path = shard_root / "shard_phase.json"
    write_json(path, evaluation, compact=False)
    return path


def refresh_committed_phase_rollup(
    market_ids: list[str],
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    policy: dict[str, Any] | None = None,
    path: Path = COMMITTED_PHASES_PATH,
) -> dict[str, Any]:
    policy = policy or {}
    markets: dict[str, Any] = {}
    for market_id in market_ids:
        evaluation = evaluate_market_phase(
            market_id,
            library_root=library_root,
            policy=policy,
        )
        write_market_phase_status(evaluation)
        markets[market_id] = evaluation
    payload = {
        "updated_at": datetime.now(UTC).isoformat(),
        "markets": markets,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, payload, compact=False)
    return payload


def markets_eligible_for_weekly_paper(
    policy: dict[str, Any],
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    screened_markets: set[str] | list[str] | None = None,
) -> list[str]:
    """Markets configured for Phase 2 that passed Phase 1 and were screened this run."""
    configured = weekly_paper_shard_markets_for_policy(policy)
    screened = set(screened_markets or [])
    eligible: list[str] = []
    for market_id in configured:
        if screened and market_id not in screened:
            continue
        ready, _ = phase1_gate_met(library_root, market_id, policy=policy)
        if ready:
            eligible.append(market_id)
    return eligible
