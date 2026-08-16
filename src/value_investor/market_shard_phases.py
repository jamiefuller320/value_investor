"""Phase gates and advancement triggers for market-sharded learning stacks."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.library_sim import (
    MARKET_BENCHMARKS,
    benchmark_for_market,
    iter_library_screen_runs,
)
from value_investor.library_screen import screen_dir_for
from value_investor.storage import read_json, write_json

PHASE_OBSERVE = 1
PHASE_WEEKLY_PAPER = 2
PHASE_WEEKDAY_PAPER = 3
PHASE_LIVE_SCREEN = 4

PHASE1_MIN_SCREEN_ARCHIVES = 12
PHASE2_MIN_WEEKLY_BATCHES = 8
PHASE2_AI_BEAT_RULES_SNAPSHOTS = 8

DEFAULT_SHARD_ROOT = Path("docs/data/paper_automation/markets")
DEFAULT_LIBRARY_ROOT = Path("docs/data/library")
COMMITTED_PHASES_PATH = Path("docs/data/library/shard_phases.json")


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


def weekly_paper_shard_markets_for_policy(policy: dict[str, Any]) -> list[str]:
    ladder = policy.get("ladder") or {}
    if not ladder.get("weekly_paper_shard_after_screen", True):
        return []
    configured = ladder.get("weekly_paper_shard_markets")
    if not configured:
        return []
    return [str(mid) for mid in configured if str(mid).strip()]


def phase1_gate_met(
    library_root: Path,
    market_id: str,
    *,
    min_archives: int = PHASE1_MIN_SCREEN_ARCHIVES,
) -> tuple[bool, dict[str, Any]]:
    archives = count_screen_archives(library_root, market_id)
    snapshots = observe_snapshot_count(library_root, market_id)
    ai_beat_rules = ai_beat_rules_on_observe_sim(library_root, market_id)
    ok = archives >= min_archives and snapshots >= min_archives
    if ai_beat_rules is False:
        ok = False
    return ok, {
        "screen_archives": archives,
        "observe_snapshot_count": snapshots,
        "min_archives": min_archives,
        "ai_beat_rules_observe_sim": ai_beat_rules,
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


def phase2_gate_met(shard_root: Path) -> tuple[bool, dict[str, Any]]:
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
    ok = count >= PHASE2_MIN_WEEKLY_BATCHES and beat_control is True
    return ok, {
        "weekly_batch_count": count,
        "min_weekly_batches": PHASE2_MIN_WEEKLY_BATCHES,
        "beat_control_latest": beat_control,
    }


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

    p1_ok, p1_detail = phase1_gate_met(library_root, market_id)
    p2_ok, p2_detail = phase2_gate_met(shard_root)
    in_weekly_policy = market_id in weekly_paper_shard_markets_for_policy(policy)

    if market_id not in MARKET_BENCHMARKS:
        current = 0
        blockers = [f"no benchmark configured for {market_id}"]
    elif not p1_ok:
        current = PHASE_OBSERVE
        blockers = []
        if p1_detail["screen_archives"] < PHASE1_MIN_SCREEN_ARCHIVES:
            blockers.append(
                f"need {PHASE1_MIN_SCREEN_ARCHIVES} screen archives "
                f"(have {p1_detail['screen_archives']})"
            )
        if p1_detail["observe_snapshot_count"] < PHASE1_MIN_SCREEN_ARCHIVES:
            blockers.append(
                f"need {PHASE1_MIN_SCREEN_ARCHIVES} observe snapshots "
                f"(have {p1_detail['observe_snapshot_count']})"
            )
        if p1_detail.get("ai_beat_rules_observe_sim") is False:
            blockers.append("AI-judgment must beat rules on observe sim before Phase 2")
    elif not in_weekly_policy:
        current = PHASE_OBSERVE
        blockers = [f"{market_id} not in ladder.weekly_paper_shard_markets"]
        p2_ok = False
    elif not p2_ok:
        current = PHASE_WEEKLY_PAPER
        blockers = []
        if p2_detail["weekly_batch_count"] < PHASE2_MIN_WEEKLY_BATCHES:
            blockers.append(
                f"need {PHASE2_MIN_WEEKLY_BATCHES} weekly batch marks "
                f"(have {p2_detail['weekly_batch_count']})"
            )
        if p2_detail.get("beat_control_latest") is False:
            blockers.append("primary track must beat rules control on latest review")
        elif p2_detail.get("beat_control_latest") is None:
            blockers.append("learning_tracks_review missing or inconclusive")
    else:
        current = PHASE_WEEKDAY_PAPER
        blockers = ["Phase 3 weekday shard not wired — manual promotion only"]

    if current >= PHASE_WEEKDAY_PAPER:
        next_phase = PHASE_LIVE_SCREEN
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
        "weekly_paper_enabled": in_weekly_policy,
        "phase1": p1_detail,
        "phase2": p2_detail,
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
        ready, _ = phase1_gate_met(library_root, market_id)
        if ready:
            eligible.append(market_id)
    return eligible
