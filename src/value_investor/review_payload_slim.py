"""Shared slim payload helpers for analysis-review and learning-director."""

from __future__ import annotations

from typing import Any


def slim_backtest(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    horizons = payload.get("horizons") or []
    top = sorted(
        horizons,
        key=lambda row: abs(float(row.get("excess_return") or 0)),
        reverse=True,
    )[:8]
    return {
        "run_count": payload.get("run_count"),
        "note": payload.get("note"),
        "top_horizons": top,
    }


def slim_simulation(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    tracks = {}
    for key in ("screen", "research_overlay", "static_levels", "trailing_levels", "momentum_grace"):
        row = payload.get(key)
        if not isinstance(row, dict):
            continue
        tracks[key] = {
            "periods": row.get("periods"),
            "total_return": row.get("total_return"),
            "benchmark_return": row.get("benchmark_return"),
            "excess_return": row.get("excess_return"),
            "trade_count": row.get("trade_count"),
            "total_costs": row.get("total_costs"),
            "note": row.get("note"),
        }
    return {
        "comparison_note": payload.get("comparison_note"),
        "tracks": tracks,
        "note": payload.get("note"),
    }


def slim_historical(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    strategies = payload.get("strategy_horizons") or []
    top = sorted(
        strategies,
        key=lambda row: float(row.get("smoothed_excess") or row.get("raw_excess") or 0),
        reverse=True,
    )[:6]
    return {
        "run_count": payload.get("run_count"),
        "window_start": payload.get("window_start"),
        "window_end": payload.get("window_end"),
        "note": payload.get("note"),
        "top_strategies": top,
        "overlay_comparison": (payload.get("overlay_comparison") or [])[:4],
    }


def slim_loser_snapshot_cards(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Compact loser cards for scoring/filter hypotheses — not the full card dump."""
    if not isinstance(payload, dict):
        return None
    cards = payload.get("cards") or []
    if not isinstance(cards, list):
        cards = []
    family_counts: dict[str, int] = {}
    sample: list[dict[str, Any]] = []
    for card in cards[:12]:
        if not isinstance(card, dict):
            continue
        screen = card.get("screen") or {}
        for family in screen.get("failed_families") or []:
            key = str(family)
            family_counts[key] = family_counts.get(key, 0) + 1
        sample.append(
            {
                "ticker": card.get("ticker"),
                "cohorts": card.get("cohorts"),
                "signal": screen.get("signal"),
                "failed_families": screen.get("failed_families"),
                "opinion_flip_triggers": card.get("opinion_flip_triggers"),
                "summary_lines": (card.get("summary_lines") or [])[:2],
            }
        )
    top_failed_families = sorted(family_counts.items(), key=lambda item: item[1], reverse=True)[:6]
    return {
        "purpose": (
            "Tier-1 loser forensics — failed families / opinion-flip patterns that should "
            "feed [scoring] or [offline_sim] filter hypotheses in PROPOSED EXPERIMENTS"
        ),
        "observe_only": True,
        "card_count": payload.get("card_count"),
        "cohort_counts": payload.get("cohort_counts"),
        "top_failed_families": top_failed_families,
        "sample_cards": sample,
        "scope_note": payload.get("scope_note"),
    }


def slim_exclusion_universe(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    ladder_slim: list[dict[str, Any]] = []
    for row in (payload.get("ladder_results") or [])[:8]:
        if not isinstance(row, dict):
            continue
        summary = row.get("summary") or {}
        hindsight = row.get("hindsight_summary") or {}
        ladder_slim.append(
            {
                "step_id": row.get("step_id"),
                "label": row.get("label"),
                "cumulative_exclusion_alpha": summary.get("cumulative_exclusion_alpha"),
                "week_pairs": summary.get("week_pairs"),
                "mean_filtered_pool": summary.get("mean_filtered_pool"),
                "mean_bottom_quartile_exclude_rate": hindsight.get(
                    "mean_bottom_quartile_exclude_rate"
                ),
            }
        )
    return {
        "purpose": (
            "Loser-filter ladder priors — positive exclusion_alpha / recommended_step should "
            "drive [offline_sim] or [paper_knobs] experiments (not auto-apply)"
        ),
        "observe_only": True,
        "recommended_step": payload.get("recommended_step"),
        "readiness": payload.get("readiness"),
        "ladder_results_slim": ladder_slim,
        "note": payload.get("note"),
    }


def slim_exclusion_ladder_replay(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    tracks_slim: dict[str, Any] = {}
    for track_id, track in (payload.get("tracks") or {}).items():
        if not isinstance(track, dict):
            continue
        steps = track.get("ladder_steps") or []
        recommended_id = payload.get("recommended_step_id")
        recommended = next(
            (
                row
                for row in steps
                if isinstance(row, dict) and row.get("step_id") == recommended_id
            ),
            None,
        )
        replay = (recommended or {}).get("replay") or {}
        tracks_slim[str(track_id)] = {
            "best_replay_step_id": track.get("best_replay_step_id"),
            "recommended_return_delta_vs_actual": replay.get("return_delta_vs_actual"),
            "log_entries_replayed": replay.get("log_entries_replayed"),
        }
    return {
        "purpose": (
            "Cost-aware exclusion ladder replay — when readiness.ready_for_shadow_spawn, "
            "propose human spawn gate (not auto-spawn) via [paper_knobs] or [ops]"
        ),
        "observe_only": True,
        "recommended_step_id": payload.get("recommended_step_id"),
        "readiness": payload.get("readiness"),
        "tracks_slim": tracks_slim,
        "note": payload.get("note"),
    }


def slim_exit_timing(payload: dict[str, Any] | None, *, label: str) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    readiness = payload.get("readiness") or {}
    hold = (payload.get("hold_recovery") or {}).get("closed") or {}
    swap = (payload.get("swap_rotation") or {}).get("closed") or {}
    slim: dict[str, Any] = {
        "purpose": (
            f"{label} — when readiness.ready_for_probability_analysis (or closed counts near "
            "targets), propose [paper_churn] / [offline_sim] hold-vs-swap experiments"
        ),
        "observe_only": True,
        "readiness": readiness,
        "hold_recovery_closed": hold,
        "swap_rotation_closed": swap,
        "note": payload.get("note"),
    }
    if payload.get("snapshot_count") is not None:
        slim["snapshot_count"] = payload.get("snapshot_count")
    if payload.get("episodes_opened") is not None:
        slim["episodes_opened"] = payload.get("episodes_opened")
    if payload.get("by_conviction_band") is not None:
        slim["by_conviction_band"] = payload.get("by_conviction_band")
    return slim


def slim_hypothesis_integrity(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Compact in-portfolio hypothesis + loser-tolerance rollup for director/review."""
    if not isinstance(payload, dict):
        return None
    tracks_raw = payload.get("tracks") or {}
    if not isinstance(tracks_raw, dict):
        return None
    tracks: dict[str, Any] = {}
    for track_id, row in tracks_raw.items():
        if not isinstance(row, dict):
            continue
        tracks[str(track_id)] = {
            "holding_count": row.get("holding_count"),
            "underwater_count": row.get("underwater_count"),
            "loser_share": row.get("loser_share"),
            "within_tolerance": row.get("within_tolerance"),
            "balancing_hint": row.get("balancing_hint"),
            "broken_loser_count": row.get("broken_loser_count"),
            "intact_loser_count": row.get("intact_loser_count"),
            "selection_feedback_flags": (row.get("selection_feedback_flags") or [])[:4],
            "thesis_status_counts": row.get("thesis_status_counts"),
        }
    return {
        "purpose": (
            "Hypothesis-first underwater review — tolerate intact losers within band; "
            "rotate broken theses; feed selection_feedback_flags into scoring/balancing"
        ),
        "observe_only": True,
        "tracks": tracks,
        "note": payload.get("note"),
    }


__all__ = [
    "slim_backtest",
    "slim_exclusion_ladder_replay",
    "slim_exclusion_universe",
    "slim_exit_timing",
    "slim_historical",
    "slim_hypothesis_integrity",
    "slim_loser_snapshot_cards",
    "slim_simulation",
]
