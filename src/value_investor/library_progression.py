"""Offline universe progression: grow caps, status, and eng-idle dispatch."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import (
    DEFAULT_POLICY_PATH,
    load_policy,
)
from value_investor.data_library import (
    DEFAULT_LIBRARY_ROOT,
    load_manifest,
)
from value_investor.library_grow_health import (
    DEFAULT_GROW_HEALTH_LOG,
    has_open_library_coverage_tasks,
    library_grow_stalled,
    snapshot_focus_market_health,
)

logger = logging.getLogger(__name__)

DEFAULT_MIN_COVERAGE_PCT = 0.95
DEFAULT_MIN_METRICS_FOR_SCREEN = 25


def effective_focus_grow_tickers(
    *,
    root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    market_id: str | None = None,
    plan_max_tickers: int,
) -> int:
    """
    Grow the full focus market in one pass when it fits the Sunday cap.

    Tail markets (omxs30=30, iseq20=20) should not need multiple weeks of
    partial grows when the plan budget allows a full sweep.
    """
    policy = load_policy(policy_path)
    market = market_id or str(policy.get("focus_market") or "").strip()
    if not market:
        return max(1, int(plan_max_tickers))
    manifest = load_manifest(root, market)
    ticker_count = int(manifest.get("ticker_count") or len(manifest.get("tickers") or []))
    if ticker_count <= 0:
        return max(1, int(plan_max_tickers))
    cap = max(1, int(plan_max_tickers))
    return min(cap, ticker_count) if ticker_count <= cap else cap


def assess_offline_universe_progression(
    *,
    root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    log_path: Path = DEFAULT_GROW_HEALTH_LOG,
    tasks_path: Path = Path("docs/data/engineering_tasks.json"),
    last_ladder_path: Path | None = None,
) -> dict[str, Any]:
    """
    Classify offline ladder progression for automation hooks.

    Status values:
    - complete: focus meets coverage floors and screen-lite threshold
    - progressing: metrics usable for screen; graduation may advance
    - growing: grow still filling honest coverage (not yet stalled)
    - stalled_needs_engineering: no progress across runs; fetch fix required
    - blocked_by_engineering: open coverage task already queued
    """
    policy = load_policy(policy_path)
    market = str(policy.get("focus_market") or "").strip()
    ladder_cfg = policy.get("ladder") or {}
    grad_cfg = policy.get("focus_graduation") or {}
    min_metrics = int(ladder_cfg.get("min_metrics_for_screen") or DEFAULT_MIN_METRICS_FOR_SCREEN)
    min_coverage = float(grad_cfg.get("min_coverage_pct") or DEFAULT_MIN_COVERAGE_PCT)

    if not market:
        return {"status": "unknown", "reason": "no focus_market", "market": ""}

    health = snapshot_focus_market_health(root=root, policy_path=policy_path, market_id=market)
    usable = int(health.get("usable_metrics_rows") or 0)
    honest_pct = float(health.get("honest_coverage_pct") or 0.0)

    if has_open_library_coverage_tasks(tasks_path, market_id=market):
        return {
            "status": "blocked_by_engineering",
            "market": market,
            "health": health,
            "reason": "open library coverage engineering task",
        }

    stalled = library_grow_stalled(log_path=log_path, market_id=market)
    if stalled:
        return {
            "status": "stalled_needs_engineering",
            "market": market,
            "health": health,
            "reason": "library grow stalled — coverage task should draft on next ladder",
        }

    if usable >= min_metrics and honest_pct >= min_coverage:
        return {
            "status": "complete",
            "market": market,
            "health": health,
            "reason": "focus market ready for screen-lite and graduation floors",
        }

    if usable >= min_metrics:
        return {
            "status": "progressing",
            "market": market,
            "health": health,
            "reason": "screen-lite threshold met; graduation may advance on coverage",
        }

    if honest_pct > 0 or int(health.get("ok_fetch_count") or 0) > 0:
        return {
            "status": "growing",
            "market": market,
            "health": health,
            "reason": "honest fetch coverage improving",
        }

    return {
        "status": "growing",
        "market": market,
        "health": health,
        "reason": "initial grow pass or fetch recovery in progress",
    }


def _last_ladder_run_at(
    *,
    root: Path,
    policy_path: Path,
    last_ladder_path: Path | None,
) -> datetime | None:
    path = last_ladder_path or (root / "last_ladder.json")
    if path.exists():
        try:
            from value_investor.storage import read_json

            payload = read_json(path)
            raw = str(payload.get("run_at") or "")
            if raw:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (OSError, ValueError, TypeError):
            pass
    policy = load_policy(policy_path)
    raw = str((policy.get("ladder") or {}).get("last_run", {}).get("run_at") or "")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def evaluate_eng_idle_offline_dispatch(
    *,
    open_count: int,
    pr_open_count: int,
    agent_running_count: int = 0,
    root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    tasks_path: Path = Path("docs/data/engineering_tasks.json"),
    log_path: Path = DEFAULT_GROW_HEALTH_LOG,
    last_ladder_path: Path | None = None,
    min_hours_between_ladder: float = 24.0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    When the engineering queue is idle, dispatch ladder_only to progress offline.

    Runs after live ingest gap-closure is not needed. Skips when fetch is
    stalled (engineering should own the fix) or a coverage task is open.
    """
    now = now or datetime.now(UTC)
    if int(open_count) > 0 or int(pr_open_count) > 0:
        return {"should_dispatch": False, "reason": "engineering queue not idle"}
    if int(agent_running_count) > 0:
        return {"should_dispatch": False, "reason": "engineering agent still running"}
    if now.weekday() == 6:
        return {
            "should_dispatch": False,
            "reason": "Sunday — scheduled library ladder handles offline",
        }

    progression = assess_offline_universe_progression(
        root=root,
        policy_path=policy_path,
        log_path=log_path,
        tasks_path=tasks_path,
        last_ladder_path=last_ladder_path,
    )
    status = str(progression.get("status") or "")
    if status in {"blocked_by_engineering", "stalled_needs_engineering", "complete"}:
        return {
            "should_dispatch": False,
            "reason": progression.get("reason") or status,
            "progression": progression,
        }

    last_run = _last_ladder_run_at(
        root=root, policy_path=policy_path, last_ladder_path=last_ladder_path
    )
    if last_run is not None:
        hours = (now - last_run).total_seconds() / 3600.0
        if hours < min_hours_between_ladder:
            return {
                "should_dispatch": False,
                "reason": f"library ladder ran {hours:.1f}h ago (min {min_hours_between_ladder}h)",
                "progression": progression,
            }

    market = str(progression.get("market") or "")
    return {
        "should_dispatch": True,
        "reason": f"eng-idle offline progression for {market} ({status})",
        "trigger": "eng_idle_offline",
        "suite": "ladder_only",
        "focus_market": market,
        "progression": progression,
    }


__all__ = [
    "assess_offline_universe_progression",
    "effective_focus_grow_tickers",
    "evaluate_eng_idle_offline_dispatch",
]
