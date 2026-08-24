"""Rebalance-log replay for exclusion ladder priors (with costs).

Bridges archive exclusion-universe alpha to deployable portfolio outcomes by
replaying paper rebalance_log passes under each ladder rung's knob mapping.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.decision_review import (
    LearningKnobs,
    _compute_epoch_metrics,
    save_knob_epoch,
    start_knob_epoch,
)
from value_investor.exclusion_universe_archive_sim import (
    REVIEW_FILENAME as EXCLUSION_ARCHIVE_REVIEW_FILENAME,
)
from value_investor.exclusion_universe_archive_sim import (
    ExclusionStep,
    default_exclusion_ladder,
    exclusion_step_from_dict,
)
from value_investor.paper_automation import (
    AI_JUDGMENT_TRACK_ID,
    CONFIG_FILENAME,
    FUND_FILENAME,
    AutomationConfig,
    default_ai_judgment_config,
    ensure_automated_fund,
    save_automated_fund,
    sync_fund_from_automation_config,
)
from value_investor.rebalance_log import (
    build_replay_fund_from_log,
    compare_rebalance_counterfactual_previews,
    load_rebalance_log,
    replay_counterfactual_from_log,
    resolve_track_dir,
)
from value_investor.storage import read_json, write_json

REPLAY_FILENAME = "exclusion_ladder_replay.json"
REVIEW_FILENAME = "exclusion_ladder_replay_review.json"
EXCLUSION_PROVENANCE_FILENAME = "exclusion_provenance.json"
DEFAULT_PARENT_TRACK = AI_JUDGMENT_TRACK_ID
DEFAULT_TRACKS = (AI_JUDGMENT_TRACK_ID, "rules")


def exclusion_shadow_subdir(step_id: str) -> str:
    return f"ai_judgment_exclusion_{step_id}"


def exclusion_shadow_track_id(step_id: str) -> str:
    return exclusion_shadow_subdir(step_id)


def discover_exclusion_shadow_step_ids(paper_root: Path) -> list[str]:
    root = Path(paper_root)
    step_ids: list[str] = []
    prefix = "ai_judgment_exclusion_"
    for config_path in sorted(root.glob(f"{prefix}*/{CONFIG_FILENAME}")):
        parent_name = config_path.parent.name
        if parent_name.startswith(prefix):
            step_ids.append(parent_name[len(prefix) :])
    return step_ids


def load_exclusion_archive_review(data_dir: Path) -> dict[str, Any] | None:
    path = Path(data_dir) / EXCLUSION_ARCHIVE_REVIEW_FILENAME
    if not path.exists():
        return None
    try:
        raw = read_json(path)
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def load_ladder_from_archive_review(
    data_dir: Path,
) -> tuple[tuple[ExclusionStep, ...], dict[str, Any] | None]:
    review = load_exclusion_archive_review(data_dir)
    if not review:
        return default_exclusion_ladder(include_ai_overlay_steps=False), None
    ladder_raw = review.get("ladder") or []
    ladder = tuple(exclusion_step_from_dict(row) for row in ladder_raw if isinstance(row, dict))
    if not ladder:
        ladder = default_exclusion_ladder(include_ai_overlay_steps=False)
    return ladder, review.get("recommended_step")


def replay_knobs_for_step(
    step: ExclusionStep,
    track_config: AutomationConfig,
) -> dict[str, Any]:
    """Map archive exclusion ladder rung to rebalance-log replay knobs."""
    use_adjusted = track_config.use_adjusted_signal
    if step.require_effective_buy_tier:
        use_adjusted = True
    require_accumulate = track_config.require_research_accumulate
    if step.require_research_accumulate:
        require_accumulate = True
    return {
        "max_positions": int(track_config.max_positions),
        "sector_cap": float(track_config.sector_cap),
        "skip_timing_wait": bool(step.exclude_timing_wait),
        "min_conviction": float(step.min_conviction),
        "use_adjusted_signal": use_adjusted,
        "require_research_accumulate": require_accumulate,
        "exit_confirm_screens": int(track_config.exit_confirm_screens),
        "candidate_source": "auto",
    }


def _load_track_config(track_dir: Path) -> AutomationConfig | None:
    config_path = Path(track_dir) / CONFIG_FILENAME
    if not config_path.exists():
        return None
    return AutomationConfig.from_dict(read_json(config_path))


def replay_track_exclusion_ladder(
    track_dir: Path,
    *,
    ladder: tuple[ExclusionStep, ...],
    archive_dir: Path | None = None,
    recommended_step_id: str | None = None,
) -> dict[str, Any] | None:
    """Replay each ladder rung on a track's rebalance_log with costs."""
    track_dir = Path(track_dir)
    config = _load_track_config(track_dir)
    if config is None:
        return None

    entries = load_rebalance_log(track_dir)
    fund_path = track_dir / FUND_FILENAME
    actual_fund = ensure_automated_fund(fund_path, config) if fund_path.exists() else None

    step_rows: list[dict[str, Any]] = []
    for step in ladder:
        knobs = replay_knobs_for_step(step, config)
        replay = replay_counterfactual_from_log(
            entries,
            **knobs,
            actual_fund=actual_fund,
        )
        if replay is None:
            step_rows.append(
                {
                    "step_id": step.step_id,
                    "label": step.label,
                    "step": step.to_dict(),
                    "knobs": knobs,
                    "replay": None,
                    "note": "No acted log entries",
                }
            )
            continue
        step_rows.append(
            {
                "step_id": step.step_id,
                "label": step.label,
                "step": step.to_dict(),
                "knobs": knobs,
                "replay": {
                    key: replay.get(key)
                    for key in (
                        "simulated_return",
                        "simulated_nav",
                        "simulated_cost_drag",
                        "simulated_trade_count",
                        "return_delta_vs_actual",
                        "cost_drag_delta_vs_actual",
                        "actual_return_over_window",
                        "log_entries_replayed",
                        "replay_from",
                        "replay_to",
                    )
                },
                "is_recommended": step.step_id == recommended_step_id,
            }
        )

    archive_comparison = None
    if recommended_step_id:
        recommended = next((s for s in ladder if s.step_id == recommended_step_id), None)
        if recommended is not None:
            knobs = replay_knobs_for_step(recommended, config)
            archive_comparison = compare_rebalance_counterfactual_previews(
                track_dir,
                max_positions=knobs["max_positions"],
                skip_timing_wait=knobs["skip_timing_wait"],
                min_conviction=knobs["min_conviction"],
                sector_cap=knobs["sector_cap"],
                use_adjusted_signal=knobs["use_adjusted_signal"],
                require_research_accumulate=knobs["require_research_accumulate"],
                candidate_source=knobs["candidate_source"],
                archive_dir=archive_dir,
                actual_fund=actual_fund,
            )

    best = None
    scored = [
        row
        for row in step_rows
        if row.get("replay") and row["replay"].get("simulated_return") is not None
    ]
    if scored:
        best = max(
            scored,
            key=lambda row: float((row.get("replay") or {}).get("simulated_return") or 0),
        )

    return {
        "track_id": config.track_id,
        "track_label": config.track_label,
        "track_dir": str(track_dir),
        "ladder_steps": step_rows,
        "recommended_step_id": recommended_step_id,
        "best_replay_step_id": best.get("step_id") if best else None,
        "archive_comparison": archive_comparison,
    }


def _promotion_readiness(
    track_results: dict[str, Any],
    *,
    recommended_step_id: str | None,
) -> dict[str, Any]:
    primary = track_results.get(DEFAULT_PARENT_TRACK) or {}
    steps = primary.get("ladder_steps") or []
    recommended = next(
        (row for row in steps if row.get("step_id") == recommended_step_id),
        None,
    )
    replay = (recommended or {}).get("replay") or {}
    log_entries = int(replay.get("log_entries_replayed") or 0)
    delta = replay.get("return_delta_vs_actual")
    ready = (
        recommended_step_id is not None
        and log_entries >= 2
        and delta is not None
        and float(delta) > 0
    )
    return {
        "ready_for_shadow_spawn": ready,
        "recommended_step_id": recommended_step_id,
        "primary_log_entries_replayed": log_entries,
        "primary_return_delta_vs_actual": delta,
        "note": (
            "Spawn exclusion shadow when primary replay beats actual on the monitoring "
            "window with ≥2 acted log entries — then observe forward vs parent."
        ),
    }


def run_exclusion_ladder_replay(
    paper_root: Path,
    *,
    data_dir: Path | None = None,
    tracks: tuple[str, ...] = DEFAULT_TRACKS,
    archive_dir: Path | None = None,
    ladder: tuple[ExclusionStep, ...] | None = None,
    recommended_step_id: str | None = None,
) -> dict[str, Any]:
    """Replay exclusion ladder across paper tracks; write observe-only artifacts."""
    paper_root = Path(paper_root)
    data_dir = Path(data_dir or paper_root.parent)
    archive_dir = Path(archive_dir or data_dir)

    loaded_ladder, recommended_from_review = load_ladder_from_archive_review(data_dir)
    ladder = ladder or loaded_ladder
    if recommended_step_id is None and isinstance(recommended_from_review, dict):
        recommended_step_id = str(recommended_from_review.get("step_id") or "") or None
    if recommended_step_id is None:
        recommended_step_id = "u4"

    track_results: dict[str, Any] = {}
    for track_id in tracks:
        track_dir = resolve_track_dir(paper_root, track_id)
        result = replay_track_exclusion_ladder(
            track_dir,
            ladder=ladder,
            archive_dir=archive_dir,
            recommended_step_id=recommended_step_id,
        )
        if result is not None:
            track_results[track_id] = result

    readiness = _promotion_readiness(track_results, recommended_step_id=recommended_step_id)
    review = {
        "schema_version": 1,
        "scope": "exclusion_ladder_replay",
        "observe_only": True,
        "generated_at": datetime.now(UTC).isoformat(),
        "paper_root": str(paper_root),
        "data_dir": str(data_dir),
        "recommended_step_id": recommended_step_id,
        "ladder": [step.to_dict() for step in ladder],
        "tracks": track_results,
        "readiness": readiness,
        "note": (
            "Portfolio replay with trade costs on rebalance_log. Compare "
            "recommended_step return_delta_vs_actual before spawning exclusion shadow."
        ),
    }
    _write_artifacts(paper_root, review)
    return review


def _apply_step_to_config(
    config: AutomationConfig,
    step: ExclusionStep,
) -> dict[str, Any]:
    changed: dict[str, Any] = {}
    if config.skip_timing_wait != bool(step.exclude_timing_wait):
        config.skip_timing_wait = bool(step.exclude_timing_wait)
        changed["skip_timing_wait"] = config.skip_timing_wait
    if float(config.min_conviction) != float(step.min_conviction):
        config.min_conviction = float(step.min_conviction)
        changed["min_conviction"] = round(config.min_conviction, 4)
    if step.require_effective_buy_tier and not config.use_adjusted_signal:
        config.use_adjusted_signal = True
        changed["use_adjusted_signal"] = True
    if step.require_research_accumulate and not config.require_research_accumulate:
        config.require_research_accumulate = True
        changed["require_research_accumulate"] = True
    return changed


def spawn_exclusion_shadow(
    paper_root: Path,
    *,
    data_dir: Path | None = None,
    parent_track_id: str = DEFAULT_PARENT_TRACK,
    step_id: str | None = None,
    warm_start: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Create observe-only exclusion shadow track from archive recommended step."""
    paper_root = Path(paper_root)
    data_dir = Path(data_dir or paper_root.parent)
    _, recommended = load_ladder_from_archive_review(data_dir)
    if step_id is None:
        if isinstance(recommended, dict):
            step_id = str(recommended.get("step_id") or "u4")
        else:
            step_id = "u4"

    ladder, _ = load_ladder_from_archive_review(data_dir)
    step = next((s for s in ladder if s.step_id == step_id), None)
    if step is None:
        return {
            "spawned": False,
            "reason": f"Ladder step {step_id!r} not found in archive review",
        }

    parent_dir = resolve_track_dir(paper_root, parent_track_id)
    parent_config = _load_track_config(parent_dir)
    if parent_config is None:
        return {"spawned": False, "reason": f"Parent config missing at {parent_dir}"}

    track_id = exclusion_shadow_track_id(step_id)
    shadow_dir = paper_root / exclusion_shadow_subdir(step_id)
    shadow_dir.mkdir(parents=True, exist_ok=True)
    config_path = shadow_dir / CONFIG_FILENAME
    fund_path = shadow_dir / FUND_FILENAME
    provenance_path = shadow_dir / EXCLUSION_PROVENANCE_FILENAME

    existed = config_path.exists()
    if existed and not force:
        shadow = AutomationConfig.from_dict(read_json(config_path))
        respawned_fund = False
    else:
        shadow = default_ai_judgment_config(parent_config)
        shadow.track_id = track_id
        shadow.track_label = f"AI judgment exclusion ladder {step_id} (frozen priors)"
        shadow.is_primary_learning_track = False
        shadow.is_exclusion_shadow = True
        shadow.exclusion_parent_track = parent_track_id
        shadow.exclusion_ladder_step_id = step_id
        shadow.is_calibration_shadow = False
        shadow.calibration_parent_track = None
        if fund_path.exists():
            fund_path.unlink()
        ensure_automated_fund(fund_path, shadow)
        respawned_fund = True

    changed = _apply_step_to_config(shadow, step)
    shadow.track_id = track_id
    shadow.is_exclusion_shadow = True
    shadow.exclusion_parent_track = parent_track_id
    shadow.exclusion_ladder_step_id = step_id
    shadow.is_primary_learning_track = False
    config_path.write_text(json.dumps(shadow.to_dict(), indent=2) + "\n", encoding="utf-8")
    ensure_automated_fund(fund_path, shadow)

    provenance = {
        "schema_version": 1,
        "spawned_at": datetime.now(UTC).isoformat(),
        "parent_track_id": parent_track_id,
        "exclusion_ladder_step_id": step_id,
        "exclusion_step": step.to_dict(),
        "knobs_changed_vs_parent": changed,
        "archive_review": str(data_dir / EXCLUSION_ARCHIVE_REVIEW_FILENAME),
        "observe_only": True,
    }
    write_json(provenance_path, provenance, compact=False)

    warm_start_result = None
    if warm_start:
        warm_start_result = warm_start_exclusion_shadow(
            paper_root,
            step_id=step_id,
            parent_track_id=parent_track_id,
            force=force,
        )

    try:
        from value_investor.sunday_review_dashboard import ensure_experiment_assessment_fresh

        ensure_experiment_assessment_fresh(data_dir, paper_root=paper_root)
    except Exception:  # noqa: BLE001 — spawn must succeed
        pass

    return {
        "spawned": True,
        "track_id": track_id,
        "shadow_dir": str(shadow_dir),
        "step_id": step_id,
        "knobs_changed_vs_parent": changed,
        "respawned_fund": respawned_fund,
        "warm_start": warm_start_result,
    }


def warm_start_exclusion_shadow(
    paper_root: Path,
    *,
    step_id: str,
    parent_track_id: str = DEFAULT_PARENT_TRACK,
    force: bool = False,
) -> dict[str, Any]:
    """Replay parent rebalance_log into exclusion shadow with frozen ladder knobs."""
    paper_root = Path(paper_root)
    track_id = exclusion_shadow_track_id(step_id)
    shadow_dir = paper_root / exclusion_shadow_subdir(step_id)
    config_path = shadow_dir / CONFIG_FILENAME
    fund_path = shadow_dir / FUND_FILENAME
    provenance_path = shadow_dir / EXCLUSION_PROVENANCE_FILENAME

    if not config_path.exists():
        return {
            "warm_started": False,
            "track_id": track_id,
            "reason": "Shadow config missing — spawn first",
        }

    provenance = read_json(provenance_path) if provenance_path.exists() else {}
    if provenance.get("warm_started_at") and not force:
        return {
            "warm_started": False,
            "track_id": track_id,
            "skipped": True,
            "reason": "Already warm-started (pass force=True to re-seed)",
        }

    cfg = AutomationConfig.from_dict(read_json(config_path))
    parent_dir = resolve_track_dir(paper_root, parent_track_id)
    entries = load_rebalance_log(parent_dir)
    if not entries:
        return {
            "warm_started": False,
            "track_id": track_id,
            "reason": f"No rebalance_log under parent {parent_dir}",
        }

    built = build_replay_fund_from_log(
        entries,
        max_positions=int(cfg.max_positions),
        skip_timing_wait=bool(cfg.skip_timing_wait),
        min_conviction=float(cfg.min_conviction),
        sector_cap=float(cfg.sector_cap),
        use_adjusted_signal=bool(cfg.use_adjusted_signal),
        require_research_accumulate=bool(cfg.require_research_accumulate),
        exit_confirm_screens=int(cfg.exit_confirm_screens),
        candidate_source="auto",
        fund_name=cfg.track_label or track_id,
    )
    if built is None:
        return {
            "warm_started": False,
            "track_id": track_id,
            "reason": "No acted parent log entries to replay",
        }

    fund, stats = built
    sync_fund_from_automation_config(fund, cfg)
    save_automated_fund(fund_path, fund)

    knobs = LearningKnobs.from_config(cfg)
    seed_end = datetime.now(UTC).isoformat()
    if fund.equity_curve:
        seed_end = str((fund.equity_curve[-1] or {}).get("at") or seed_end)
    epoch = start_knob_epoch(shadow_dir, fund, knobs, reviewed_at=seed_end)
    epoch.seeded_from_history = True
    save_knob_epoch(shadow_dir, epoch)

    provenance = dict(provenance) if isinstance(provenance, dict) else {}
    provenance["warm_started_at"] = datetime.now(UTC).isoformat()
    provenance["seed_stats"] = stats
    provenance["knob_epoch"] = epoch.to_dict()
    write_json(provenance_path, provenance, compact=False)

    return {
        "warm_started": True,
        "track_id": track_id,
        "shadow_dir": str(shadow_dir),
        "seed_stats": stats,
        "post_seed_metrics": _compute_epoch_metrics(fund, epoch, fetch_benchmark=False),
        "positions": len(fund.holdings),
    }


def _write_artifacts(paper_root: Path, review: dict[str, Any]) -> None:
    store = {
        key: review.get(key)
        for key in (
            "schema_version",
            "scope",
            "observe_only",
            "generated_at",
            "paper_root",
            "data_dir",
            "recommended_step_id",
            "ladder",
            "tracks",
            "readiness",
            "note",
        )
    }
    write_json(Path(paper_root) / REPLAY_FILENAME, store, compact=False)
    write_json(Path(paper_root) / REVIEW_FILENAME, review, compact=False)


def format_exclusion_ladder_replay_text(review: dict[str, Any]) -> str:
    lines = [
        "Exclusion ladder replay (rebalance_log, with costs)",
        f"  Recommended step: {review.get('recommended_step_id', '—')}",
    ]
    readiness = review.get("readiness") or {}
    lines.append(
        f"  Ready for shadow spawn: {readiness.get('ready_for_shadow_spawn')} "
        f"(Δ vs actual {readiness.get('primary_return_delta_vs_actual')})"
    )
    for track_id, payload in (review.get("tracks") or {}).items():
        lines.append(f"  Track {track_id}:")
        for row in payload.get("ladder_steps") or []:
            replay = row.get("replay") or {}
            sim = replay.get("simulated_return")
            delta = replay.get("return_delta_vs_actual")
            marker = "*" if row.get("is_recommended") else " "
            sim_s = f"{sim:+.1%}" if sim is not None else "n/a"
            delta_s = f"{delta:+.1%}" if delta is not None else "n/a"
            lines.append(f"    {marker}{row.get('step_id')}: sim {sim_s} | Δ vs actual {delta_s}")
    note = review.get("note")
    if note:
        lines.append(f"  Note: {note}")
    return "\n".join(lines)


__all__ = [
    "REPLAY_FILENAME",
    "REVIEW_FILENAME",
    "discover_exclusion_shadow_step_ids",
    "exclusion_shadow_subdir",
    "exclusion_shadow_track_id",
    "format_exclusion_ladder_replay_text",
    "load_ladder_from_archive_review",
    "replay_knobs_for_step",
    "run_exclusion_ladder_replay",
    "spawn_exclusion_shadow",
    "warm_start_exclusion_shadow",
]
