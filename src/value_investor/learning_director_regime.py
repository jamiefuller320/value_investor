"""Deterministic rollups for Learning Director payload (regime + inventory)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import read_json

VISION_PATH = Path("docs/data/learning_director_vision.json")

# Coverage overlays/tracks do not consume these. Generous early; agents manage overflow.
DEFAULT_MAX_DISCRETIONARY_TASKS = 12
DEFAULT_MAX_EXPENSIVE_SHADOWS = 8
DEFAULT_SOFT_WARN_FRACTION = 0.75


def _safe_read(path: Path) -> dict[str, Any] | None:
    try:
        raw = read_json(path)
    except FileNotFoundError:
        return None
    return raw if isinstance(raw, dict) else None


def _open_tasks(tasks_path: Path, *, source: str | None = None) -> list[dict[str, Any]]:
    raw = _safe_read(tasks_path)
    if not raw:
        return []
    rows = [row for row in (raw.get("tasks") or []) if isinstance(row, dict)]
    if source:
        rows = [row for row in rows if str(row.get("source") or "") == source]
    return [row for row in rows if str(row.get("status") or "proposed") == "proposed"]


def _experimental_track_inventory(paper_root: Path) -> list[dict[str, Any]]:
    """Non-shadow experimental paper tracks (momentum grace, graduated allocation, …)."""
    inventory: list[dict[str, Any]] = []
    root = Path(paper_root)
    if not root.exists():
        return inventory

    for config_path in sorted(root.glob("**/config.json")):
        try:
            cfg = read_json(config_path)
        except (OSError, ValueError):
            continue
        if not isinstance(cfg, dict):
            continue
        if cfg.get("is_calibration_shadow") or cfg.get("is_exclusion_shadow"):
            continue
        if not (cfg.get("use_momentum_grace") or cfg.get("use_graduated_allocation")):
            continue
        inventory.append(
            {
                "track_id": cfg.get("track_id"),
                "track_label": cfg.get("track_label"),
                "path": str(config_path.parent.relative_to(root)),
                "use_momentum_grace": bool(cfg.get("use_momentum_grace")),
                "use_graduated_allocation": bool(cfg.get("use_graduated_allocation")),
                "max_positions": cfg.get("max_positions"),
            }
        )
    return inventory


def _shadow_track_inventory(paper_root: Path) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    root = Path(paper_root)
    if not root.exists():
        return inventory

    for config_path in sorted(root.glob("**/config.json")):
        try:
            cfg = read_json(config_path)
        except (OSError, ValueError):
            continue
        if not isinstance(cfg, dict):
            continue
        if not (cfg.get("is_calibration_shadow") or cfg.get("is_exclusion_shadow")):
            continue
        inventory.append(
            {
                "track_id": cfg.get("track_id"),
                "track_label": cfg.get("track_label"),
                "path": str(config_path.parent.relative_to(root)),
                "is_calibration_shadow": bool(cfg.get("is_calibration_shadow")),
                "is_exclusion_shadow": bool(cfg.get("is_exclusion_shadow")),
                "min_conviction": cfg.get("min_conviction"),
                "max_positions": cfg.get("max_positions"),
            }
        )
    return inventory


def _lifecycle_overlay_inventory(paper_root: Path) -> dict[str, Any]:
    """Observe-only lifecycle overlays (DCA cadence, factor catalog coverage)."""
    from value_investor.position_lifecycle import catalog_coverage, lifecycle_catalog

    rollup = _safe_read(Path(paper_root) / "learning_tracks_entry_dca.json") or {}
    readiness = rollup.get("readiness") if isinstance(rollup, dict) else {}
    return {
        "entry_dca_overlay": {
            "scored_count": (rollup or {}).get("scored_count"),
            "tracks_with_closed": (rollup or {}).get("tracks_with_closed"),
            "ready_for_cadence_analysis": bool((readiness or {}).get("ready_for_cadence_analysis")),
            "leading_cadence": (rollup or {}).get("leading_cadence"),
            "model_independent_hint": bool((rollup or {}).get("model_independent_hint")),
        },
        "factor_coverage": catalog_coverage(lifecycle_catalog()),
    }


def resolve_complexity_budget(vision: dict[str, Any] | None = None) -> dict[str, Any]:
    """Split coverage (always on) from discretionary tasks and expensive shadows."""
    raw = (vision or {}).get("complexity_budget") if isinstance(vision, dict) else {}
    if not isinstance(raw, dict):
        raw = {}
    discretionary = raw.get("max_discretionary_tasks")
    if discretionary is None:
        discretionary = raw.get("max_parallel_open_experiments", DEFAULT_MAX_DISCRETIONARY_TASKS)
    shadows = raw.get("max_expensive_shadow_tracks")
    if shadows is None:
        shadows = raw.get("max_frozen_shadow_tracks", DEFAULT_MAX_EXPENSIVE_SHADOWS)
    warn = raw.get("soft_warn_fraction", DEFAULT_SOFT_WARN_FRACTION)
    return {
        "max_discretionary_tasks": int(discretionary),
        "max_expensive_shadow_tracks": int(shadows),
        "soft_warn_fraction": float(warn),
        "coverage_floor_required": bool(raw.get("coverage_floor_required", True)),
        "management": str(raw.get("management") or "agent_assessment"),
        "max_parallel_open_experiments": int(discretionary),
        "max_frozen_shadow_tracks": int(shadows),
        "note": str(
            raw.get("note")
            or (
                "Coverage overlays/tracks do not count. Discretionary tasks are generous "
                "early; expensive shadow books are the scarce slot. Agents park/merge "
                "overflow — do not retire coverage to meet a cap."
            )
        ),
    }


def assess_complexity_budget(
    *,
    discretionary_open: int,
    expensive_shadows: int,
    coverage_perpetual: bool,
    budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Soft budget: flags for agent management, never a hard reject."""
    cfg = budget or resolve_complexity_budget()
    max_tasks = int(cfg["max_discretionary_tasks"])
    max_shadows = int(cfg["max_expensive_shadow_tracks"])
    warn = float(cfg["soft_warn_fraction"])
    task_ratio = (discretionary_open / max_tasks) if max_tasks else 0.0
    shadow_ratio = (expensive_shadows / max_shadows) if max_shadows else 0.0
    over_tasks = discretionary_open > max_tasks
    over_shadows = expensive_shadows > max_shadows
    warn_tasks = (not over_tasks) and task_ratio >= warn
    warn_shadows = (not over_shadows) and shadow_ratio >= warn
    coverage_gap = bool(cfg.get("coverage_floor_required")) and not coverage_perpetual
    return {
        "budget": cfg,
        "discretionary_open": discretionary_open,
        "expensive_shadows": expensive_shadows,
        "coverage_perpetual": coverage_perpetual,
        "coverage_gap": coverage_gap,
        "over_discretionary_tasks": over_tasks,
        "over_expensive_shadows": over_shadows,
        "warn_discretionary_tasks": warn_tasks,
        "warn_expensive_shadows": warn_shadows,
        "over_budget": over_tasks or over_shadows,
        "needs_agent_triage": over_tasks
        or over_shadows
        or warn_tasks
        or warn_shadows
        or coverage_gap,
        "guidance": (
            "Do not retire lifecycle coverage or always-on overlays to meet a cap. "
            "Park losing discretionary tasks (keep cheap marks) or merge siblings. "
            "New paper books are the scarce slot."
            if (over_tasks or over_shadows or coverage_gap)
            else "Within budget. Prefer filling coverage gaps over new shadow books."
        ),
    }


def build_experiment_inventory(
    data_dir: Path,
    *,
    paper_root: Path | None = None,
) -> dict[str, Any]:
    """Count open proposed experiments across review task stores."""
    data_dir = Path(data_dir)
    paper_root = Path(paper_root or data_dir / "paper_automation")
    buckets = {
        "analysis_tasks": _open_tasks(data_dir / "analysis_tasks.json"),
        "paper_learning_tasks": _open_tasks(data_dir / "paper_learning_tasks.json"),
        "learning_director_tasks": _open_tasks(data_dir / "learning_director_tasks.json"),
        "horizon_tasks": _open_tasks(data_dir / "horizon_tasks.json"),
    }
    total_open = sum(len(rows) for rows in buckets.values())
    overlays = _lifecycle_overlay_inventory(paper_root)
    coverage = (overlays.get("factor_coverage") or {}) if isinstance(overlays, dict) else {}
    vision = _safe_read(data_dir / "learning_director_vision.json") or _safe_read(VISION_PATH)
    budget_view = assess_complexity_budget(
        discretionary_open=total_open,
        expensive_shadows=len(_shadow_track_inventory(paper_root)),
        coverage_perpetual=bool(coverage.get("perpetual")),
        budget=resolve_complexity_budget(vision if isinstance(vision, dict) else None),
    )
    return {
        "open_experiment_count": total_open,
        "buckets": {key: len(rows) for key, rows in buckets.items()},
        "open_experiments": {
            key: [
                {
                    "id": row.get("id"),
                    "area": row.get("area"),
                    "title": row.get("title"),
                    "status": row.get("status"),
                    "source": row.get("source"),
                }
                for row in rows[:8]
            ]
            for key, rows in buckets.items()
            if rows
        },
        "shadow_tracks": _shadow_track_inventory(paper_root),
        "shadow_track_count": len(_shadow_track_inventory(paper_root)),
        "experimental_paper_tracks": _experimental_track_inventory(paper_root),
        "experimental_paper_track_count": len(_experimental_track_inventory(paper_root)),
        "lifecycle_overlays": overlays,
        "complexity": budget_view,
    }


def build_regime_summary(
    data_dir: Path,
    *,
    paper_root: Path | None = None,
    history_run_count: int = 0,
) -> dict[str, Any]:
    """
      Regime-oriented snapshot from available artifacts.

    Full 8/16/24-week slices require persisted weekly series (planned phase
    `regime_slices_8_16_24`). Until then, report full-sample metrics and history depth.
    """
    data_dir = Path(data_dir)
    paper_root = Path(paper_root or data_dir / "paper_automation")

    exclusion = _safe_read(data_dir / "exclusion_universe_review.json") or {}
    ladder_replay = _safe_read(paper_root / "exclusion_ladder_replay_review.json") or {}
    learning = _safe_read(paper_root / "learning_tracks_review.json") or {}
    knob = _safe_read(paper_root / "knob_calibration_priors.json") or {}

    recommended = exclusion.get("recommended_step") or {}
    rec_step_id = recommended.get("step_id") if isinstance(recommended, dict) else recommended
    ladder_results = exclusion.get("ladder_results") or []
    rec_row = next(
        (row for row in ladder_results if row.get("step_id") == rec_step_id),
        None,
    )
    rec_summary = (rec_row or {}).get("summary") or {}
    rec_hindsight = (rec_row or {}).get("hindsight_summary") or {}

    primary_track = (ladder_replay.get("tracks") or {}).get("ai_judgment") or {}
    rec_replay = None
    for step in primary_track.get("ladder_steps") or []:
        if step.get("is_recommended"):
            rec_replay = step.get("replay")
            break

    windows = [
        {
            "window": "full_sample",
            "history_run_count": int(history_run_count),
            "exclusion_week_pairs": rec_summary.get("week_pairs"),
            "cumulative_exclusion_alpha": rec_summary.get("cumulative_exclusion_alpha"),
            "positive_alpha_rate": rec_summary.get("positive_alpha_rate"),
            "bottom_quartile_exclude_rate": rec_hindsight.get("mean_bottom_quartile_exclude_rate"),
            "top_quartile_retain_rate": rec_hindsight.get("mean_top_quartile_retain_rate"),
            "replay_return_delta_vs_actual": (
                (rec_replay or {}).get("return_delta_vs_actual") if rec_replay else None
            ),
            "primary_excess_after_costs": learning.get("primary_excess_after_costs"),
            "beat_market": learning.get("beat_market"),
            "beat_control": learning.get("beat_control"),
            "note": (
                "Rolling 8/16/24-week slices activate when phase "
                "`regime_slices_8_16_24` is enabled and weekly series persist."
            ),
        }
    ]

    readiness_flags: list[str] = []
    if int(history_run_count) < 8:
        readiness_flags.append("thin_history:<8_archive_runs")
    if not exclusion:
        readiness_flags.append("missing:exclusion_universe_review")
    if not ladder_replay:
        readiness_flags.append("missing:exclusion_ladder_replay")
    if (
        rec_summary.get("positive_alpha_rate") is not None
        and float(rec_summary.get("positive_alpha_rate") or 0) < 0.5
    ):
        readiness_flags.append("exclusion_alpha_inconsistent:<50%_positive_weeks")
    if learning.get("beat_market") is False:
        readiness_flags.append("primary_underperforming_market")

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "windows": windows,
        "recommended_exclusion_step": rec_step_id,
        "knob_calibration_ready": (knob.get("tracks") or {})
        .get("ai_judgment", {})
        .get("readiness", {})
        .get("ready_for_priors"),
        "ladder_replay_readiness": ladder_replay.get("readiness"),
        "flags": readiness_flags,
    }


def build_convergence_summary(
    data_dir: Path,
    *,
    paper_root: Path | None = None,
    vision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Deterministic winner-pick vs loser-filter strand comparison for the director.

    Surfaces knob-direction tensions (live primary, exclusion ladder, calibration
    priors, shadow tracks) so the CONVERGENCE section cites structured facts.
    """
    data_dir = Path(data_dir)
    paper_root = Path(paper_root or data_dir / "paper_automation")
    vision = vision or load_learning_director_vision()

    learning = _safe_read(paper_root / "learning_tracks_review.json") or {}
    knob = _safe_read(paper_root / "knob_calibration_priors.json") or {}
    ladder_replay = _safe_read(paper_root / "exclusion_ladder_replay_review.json") or {}
    exclusion = _safe_read(data_dir / "exclusion_universe_review.json") or {}
    inventory = build_experiment_inventory(data_dir, paper_root=paper_root)

    primary_id = str(learning.get("primary_learning_track") or "ai_judgment")
    primary_review = (learning.get("reviews") or {}).get(primary_id) or {}
    live_knobs = dict(primary_review.get("knobs_after") or {})

    rec_step_id = ladder_replay.get("recommended_step_id") or (
        exclusion.get("recommended_step") or {}
    ).get("step_id")
    ladder_step = next(
        (
            step
            for step in (ladder_replay.get("ladder") or [])
            if step.get("step_id") == rec_step_id
        ),
        None,
    )
    exclusion_knobs = {
        "min_conviction": (ladder_step or {}).get("min_conviction"),
        "max_positions": live_knobs.get("max_positions"),
        "step_id": rec_step_id,
    }

    priors_track = (knob.get("tracks") or {}).get(primary_id) or {}
    priors_readiness = priors_track.get("readiness") or {}
    recommended_prior = (priors_track.get("recommended_prior") or {}).get("knobs") or {}
    calibration_knobs = dict(recommended_prior)

    shadow_by_kind: dict[str, dict[str, Any]] = {}
    for row in inventory.get("shadow_tracks") or []:
        if row.get("is_calibration_shadow"):
            shadow_by_kind["calibration_shadow"] = row
        elif row.get("is_exclusion_shadow"):
            shadow_by_kind["exclusion_shadow"] = row

    strands: dict[str, Any] = {
        "live_primary": {
            "track_id": primary_id,
            "min_conviction": live_knobs.get("min_conviction"),
            "max_positions": live_knobs.get("max_positions"),
            "applied": primary_review.get("applied"),
            "epoch_equity_marks": ((primary_review.get("metrics") or {}).get("epoch") or {}).get(
                "equity_marks"
            ),
        },
        "exclusion_ladder": exclusion_knobs,
        "calibration_priors": {
            "min_conviction": calibration_knobs.get("min_conviction"),
            "max_positions": calibration_knobs.get("max_positions"),
            "ready_for_priors": priors_readiness.get("ready_for_priors"),
            "confidence": (priors_track.get("recommended_prior") or {}).get("confidence"),
        },
    }
    for kind, row in shadow_by_kind.items():
        strands[kind] = {
            "track_id": row.get("track_id"),
            "min_conviction": row.get("min_conviction"),
            "max_positions": row.get("max_positions"),
        }

    def _float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    live_mc = _float(live_knobs.get("min_conviction"))
    ladder_mc = _float(exclusion_knobs.get("min_conviction"))
    prior_mc = _float(calibration_knobs.get("min_conviction"))
    live_mp = _float(live_knobs.get("max_positions"))
    prior_mp = _float(calibration_knobs.get("max_positions"))

    tensions: list[str] = []
    look_now: list[str] = []

    if live_mc is not None and ladder_mc is not None and live_mc > ladder_mc + 1e-9:
        tensions.append(
            f"live_primary_min_conviction_above_ladder:{live_mc}>{ladder_mc}@{rec_step_id}"
        )
    if (
        live_mc is not None
        and prior_mc is not None
        and abs(live_mc - prior_mc) >= 0.15
        and priors_readiness.get("ready_for_priors") is not True
    ):
        tensions.append(
            f"calibration_priors_direction_opposes_live:{prior_mc}_vs_{live_mc}_not_ready"
        )
    elif live_mc is not None and prior_mc is not None and abs(live_mc - prior_mc) >= 0.15:
        tensions.append(f"calibration_priors_direction_opposes_live:{prior_mc}_vs_{live_mc}")
    if live_mp is not None and prior_mp is not None and live_mp != prior_mp:
        tensions.append(f"sleeve_count_conflict:live_{live_mp}_priors_{prior_mp}")
    if priors_readiness.get("ready_for_priors") is False:
        tensions.append("calibration_priors_not_ready_for_apply")
    for warning in priors_readiness.get("warnings") or []:
        text = str(warning)
        if "min_conviction" in text and "negligible" in text:
            tensions.append("min_conviction_axis_negligible_in_calibration")
            break
    if not shadow_by_kind.get("exclusion_shadow"):
        tensions.append("missing:exclusion_shadow_track")
    elif ladder_replay.get("readiness", {}).get("ready_for_shadow_spawn"):
        look_now.append(
            "Observe ai_judgment_exclusion_u4 shadow forward marks vs live primary "
            "(exclusion_ladder_replay.readiness.ready_for_shadow_spawn)."
        )
    if shadow_by_kind.get("calibration_shadow"):
        cal_shadow_mc = _float(shadow_by_kind["calibration_shadow"].get("min_conviction"))
        if (
            live_mc is not None
            and cal_shadow_mc is not None
            and abs(live_mc - cal_shadow_mc) >= 0.15
        ):
            tensions.append(f"calibration_shadow_frozen_at_{cal_shadow_mc}_live_at_{live_mc}")

    filtered_phase = next(
        (
            phase
            for phase in (vision.get("phases") or [])
            if phase.get("id") == "filtered_cohort_track"
        ),
        {},
    )
    cross_shard_phase = next(
        (
            phase
            for phase in (vision.get("phases") or [])
            if phase.get("id") == "cross_shard_winner_selection"
        ),
        {},
    )
    bet_gate_met = (
        filtered_phase.get("status") == "active"
        and (primary_review.get("metrics") or {}).get("equity_marks", 0) >= 8
    )
    if not bet_gate_met:
        tensions.append("bet_gate_unmet:filtered_cohort_track_not_active")

    if tensions:
        look_now.append(
            "Do not auto-apply knob_calibration_priors while convergence tensions "
            "include calibration_priors_not_ready or direction conflicts."
        )
    if "min_conviction_axis_negligible_in_calibration" in tensions:
        look_now.append(
            "Treat min_conviction as a churn guard, not a winner-rank axis, until "
            "dual_objective_calibration or filtered_cohort_track provides signal."
        )
    if ladder_replay.get("readiness", {}).get("ready_for_shadow_spawn"):
        look_now.append(
            "Count consecutive weeks of exclusion shadow forward differentiation "
            "toward filtered_cohort_track activation (≥4 weeks per vision)."
        )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "primary_track": primary_id,
        "strands": strands,
        "tensions": tensions,
        "look_now": look_now,
        "bet_gate_met": bet_gate_met,
        "cross_shard_phase_status": cross_shard_phase.get("status"),
        "convergence_thesis": vision.get("convergence_thesis"),
    }


def load_learning_director_vision(path: Path = VISION_PATH) -> dict[str, Any]:
    raw = _safe_read(path)
    if not raw:
        raise FileNotFoundError(f"Learning director vision missing at {path}")
    return raw


__all__ = [
    "DEFAULT_MAX_DISCRETIONARY_TASKS",
    "DEFAULT_MAX_EXPENSIVE_SHADOWS",
    "VISION_PATH",
    "assess_complexity_budget",
    "build_convergence_summary",
    "build_experiment_inventory",
    "build_regime_summary",
    "load_learning_director_vision",
    "resolve_complexity_budget",
]
