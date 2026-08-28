"""Weekly paper shard runner for Phase 2 market-sharded learning stacks."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.decision_review import compare_learning_tracks
from value_investor.library_sim import benchmark_for_market
from value_investor.market_paper_adapter import write_market_screen_bundle
from value_investor.market_shard_phases import (
    DEFAULT_LIBRARY_ROOT,
    append_weekday_batch_log,
    append_weekly_batch_log,
    evaluate_market_phase,
    markets_eligible_for_weekly_paper,
    phase2_gate_met,
    shard_root_for_market,
    weekday_paper_shard_enabled_for_policy,
    weekly_paper_shard_markets_for_policy,
    write_market_phase_status,
)
from value_investor.market_trading_costs import cost_fields_for_config, costs_for_market
from value_investor.paper_automation import (
    CONFIG_FILENAME,
    ensure_learning_track_configs,
    learning_track_dirs,
    run_learning_tracks,
)
from value_investor.storage import read_json, write_json

logger = logging.getLogger(__name__)

SHARD_META_FILENAME = "shard_meta.json"

MARKET_SESSION_DEFAULTS: dict[str, dict[str, Any]] = {
    "sp500": {
        "timezone": "America/New_York",
        "market_open": "09:30",
        "settle_minutes_after_open": 30,
        "weekdays_only": False,
    },
    "euro_stoxx50": {
        "timezone": "Europe/Paris",
        "market_open": "09:00",
        "settle_minutes_after_open": 30,
        "weekdays_only": False,
    },
    "euro_depth": {
        "timezone": "Europe/Paris",
        "market_open": "09:00",
        "settle_minutes_after_open": 30,
        "weekdays_only": False,
    },
}

DEFAULT_SESSION: dict[str, Any] = {
    "timezone": "Europe/London",
    "market_open": "08:00",
    "settle_minutes_after_open": 75,
    "weekdays_only": False,
}


def session_defaults_for_market(market_id: str) -> dict[str, Any]:
    return dict(MARKET_SESSION_DEFAULTS.get(market_id) or DEFAULT_SESSION)


def ensure_shard_meta(
    market_id: str,
    shard_root: Path,
    *,
    phase: int = 2,
) -> dict[str, Any]:
    """Write or refresh shard_meta.json with benchmark and session defaults."""
    shard_root = Path(shard_root)
    shard_root.mkdir(parents=True, exist_ok=True)
    path = shard_root / SHARD_META_FILENAME
    session = session_defaults_for_market(market_id)
    payload: dict[str, Any] = {
        "market_id": market_id,
        "benchmark_ticker": benchmark_for_market(market_id),
        "phase": phase,
        "timezone": session["timezone"],
        "market_open": session["market_open"],
        "settle_minutes_after_open": session["settle_minutes_after_open"],
        "weekdays_only": session["weekdays_only"],
        "trading_costs": costs_for_market(market_id).to_dict(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    if path.exists():
        try:
            existing = read_json(path)
            if isinstance(existing, dict):
                payload = {**existing, **payload}
        except (OSError, ValueError, TypeError):
            pass
    write_json(path, payload, compact=False)
    return payload


def apply_shard_session_to_configs(shard_root: Path, session: dict[str, Any]) -> None:
    """Stamp timezone / open / settle / fair trading costs onto shard learning-track configs."""
    shard_root = Path(shard_root)
    configs = ensure_learning_track_configs(shard_root)
    dirs = learning_track_dirs(shard_root)
    market_id = str(session.get("market_id") or "").strip()
    cost_fields = cost_fields_for_config(market_id) if market_id else None
    for track_id, cfg in configs.items():
        cfg.timezone = str(session.get("timezone") or cfg.timezone)
        cfg.market_open = str(session.get("market_open") or cfg.market_open)
        cfg.settle_minutes_after_open = int(
            session.get("settle_minutes_after_open") or cfg.settle_minutes_after_open
        )
        if "weekdays_only" in session:
            cfg.weekdays_only = bool(session["weekdays_only"])
        if cost_fields is not None:
            # Fair T212-shaped costs for non-FTSE shards (not the live 3% stress case).
            cfg.trade_cost_pct = float(cost_fields["trade_cost_pct"])
            cfg.buy_cost_pct = float(cost_fields["buy_cost_pct"])
            cfg.sell_cost_pct = float(cost_fields["sell_cost_pct"])
        track_dir = dirs[track_id]
        track_dir.mkdir(parents=True, exist_ok=True)
        (track_dir / CONFIG_FILENAME).write_text(
            json.dumps(cfg.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )


def run_weekly_market_paper_shard(
    market_id: str,
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    shard_root: Path | None = None,
    force: bool = True,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Phase 2 weekly batch: screen adapter → learning tracks → decision review (no apply).

    Appends a mark to weekly_batch_log.json and refreshes shard_phase.json.
    """
    library_root = Path(library_root)
    shard_root = Path(shard_root or shard_root_for_market(market_id))
    meta = ensure_shard_meta(market_id, shard_root)
    apply_shard_session_to_configs(shard_root, meta)

    bundle_path = write_market_screen_bundle(library_root, market_id, shard_root)
    track_summary = run_learning_tracks(
        base_dir=shard_root,
        reports_path=bundle_path,
        force=force,
    )
    review = compare_learning_tracks(
        base_dir=shard_root,
        apply=False,
        force=force,
    )
    batch_entry = {
        "run_at": datetime.now(UTC).isoformat(),
        "screen_bundle": bundle_path.name,
        "primary_excess_after_costs": review.get("primary_excess_after_costs"),
        "beat_control": review.get("beat_control"),
        "beat_market": review.get("beat_market"),
        "verdict": review.get("verdict"),
        "tracks_acted": {
            track_id: row.get("acted")
            for track_id, row in (track_summary.get("tracks") or {}).items()
        },
    }
    append_weekly_batch_log(shard_root, batch_entry)
    evaluation = evaluate_market_phase(
        market_id,
        library_root=library_root,
        shard_root=shard_root,
        policy=policy or {},
    )
    write_market_phase_status(evaluation, shard_root=shard_root)
    return {
        "market_id": market_id,
        "shard_root": str(shard_root),
        "screen_bundle": str(bundle_path),
        "learning_tracks": track_summary,
        "review": review,
        "phase": evaluation,
    }


def run_weekly_paper_shards_for_screened_markets(
    root: Path,
    policy: dict[str, Any],
    screened_markets: set[str] | list[str],
) -> dict[str, Any]:
    """Refresh Phase 2 weekly paper shards for eligible markets screened this run."""
    eligible = markets_eligible_for_weekly_paper(
        policy,
        library_root=root,
        screened_markets=screened_markets,
    )
    if not eligible:
        return {
            "skipped": True,
            "reason": "no Phase-2-eligible markets screened this run",
            "configured": markets_eligible_for_weekly_paper(policy, library_root=root),
        }
    markets_out: dict[str, Any] = {}
    for market_id in eligible:
        try:
            result = run_weekly_market_paper_shard(
                market_id,
                library_root=root,
                policy=policy,
                force=True,
            )
            review = result.get("review") or {}
            phase = result.get("phase") or {}
            markets_out[market_id] = {
                "verdict": review.get("verdict"),
                "beat_control": review.get("beat_control"),
                "primary_excess_after_costs": review.get("primary_excess_after_costs"),
                "current_phase": phase.get("current_phase"),
                "phase2_ready": phase.get("phase2_ready"),
                "blockers": phase.get("blockers"),
                "path": f"markets/{market_id}/",
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("Weekly paper shard for %s failed: %s", market_id, exc)
            markets_out[market_id] = {"error": str(exc)}
    return {"skipped": False, "markets": markets_out}


def markets_eligible_for_weekday_paper(
    policy: dict[str, Any],
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
) -> list[str]:
    """Markets configured for Phase 3 that passed Phase 2."""
    if not weekday_paper_shard_enabled_for_policy(policy):
        return []
    configured = weekly_paper_shard_markets_for_policy(policy)
    eligible: list[str] = []
    for market_id in configured:
        shard_root = shard_root_for_market(market_id)
        ready, _ = phase2_gate_met(shard_root, policy=policy)
        if ready:
            eligible.append(market_id)
    return eligible


def run_weekday_market_paper_shard(
    market_id: str,
    *,
    library_root: Path = DEFAULT_LIBRARY_ROOT,
    shard_root: Path | None = None,
    force: bool = True,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase 3 weekday batch: same track set as weekly, weekday cadence mark."""
    library_root = Path(library_root)
    shard_root = Path(shard_root or shard_root_for_market(market_id))
    meta = ensure_shard_meta(market_id, shard_root, phase=3)
    apply_shard_session_to_configs(shard_root, meta)

    bundle_path = write_market_screen_bundle(library_root, market_id, shard_root)
    track_summary = run_learning_tracks(
        base_dir=shard_root,
        reports_path=bundle_path,
        force=force,
    )
    review = compare_learning_tracks(
        base_dir=shard_root,
        apply=False,
        force=force,
    )
    batch_entry = {
        "run_at": datetime.now(UTC).isoformat(),
        "cadence": "weekday",
        "screen_bundle": bundle_path.name,
        "primary_excess_after_costs": review.get("primary_excess_after_costs"),
        "beat_control": review.get("beat_control"),
        "beat_market": review.get("beat_market"),
        "verdict": review.get("verdict"),
        "tracks_acted": {
            track_id: row.get("acted")
            for track_id, row in (track_summary.get("tracks") or {}).items()
        },
    }
    append_weekday_batch_log(shard_root, batch_entry)
    evaluation = evaluate_market_phase(
        market_id,
        library_root=library_root,
        shard_root=shard_root,
        policy=policy or {},
    )
    write_market_phase_status(evaluation, shard_root=shard_root)
    return {
        "market_id": market_id,
        "shard_root": str(shard_root),
        "screen_bundle": str(bundle_path),
        "learning_tracks": track_summary,
        "review": review,
        "phase": evaluation,
    }


def run_weekday_paper_shards_for_markets(
    root: Path,
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Refresh Phase 3 weekday paper shards for markets that cleared Phase 2."""
    eligible = markets_eligible_for_weekday_paper(policy, library_root=root)
    if not eligible:
        return {
            "skipped": True,
            "reason": "no Phase-3-eligible markets (Phase 2 gate or policy off)",
            "configured": markets_eligible_for_weekday_paper(policy, library_root=root),
        }
    markets_out: dict[str, Any] = {}
    for market_id in eligible:
        try:
            result = run_weekday_market_paper_shard(
                market_id,
                library_root=root,
                policy=policy,
                force=True,
            )
            review = result.get("review") or {}
            phase = result.get("phase") or {}
            markets_out[market_id] = {
                "verdict": review.get("verdict"),
                "beat_control": review.get("beat_control"),
                "current_phase": phase.get("current_phase"),
                "phase3_ready": phase.get("phase3_ready"),
                "blockers": phase.get("blockers"),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("Weekday paper shard for %s failed: %s", market_id, exc)
            markets_out[market_id] = {"error": str(exc)}
    return {"skipped": False, "markets": markets_out}
