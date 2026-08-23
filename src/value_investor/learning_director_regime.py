"""Deterministic rollups for Learning Director payload (regime + inventory)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import read_json

VISION_PATH = Path("docs/data/learning_director_vision.json")


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


def load_learning_director_vision(path: Path = VISION_PATH) -> dict[str, Any]:
    raw = _safe_read(path)
    if not raw:
        raise FileNotFoundError(f"Learning director vision missing at {path}")
    return raw


__all__ = [
    "VISION_PATH",
    "build_experiment_inventory",
    "build_regime_summary",
    "load_learning_director_vision",
]
