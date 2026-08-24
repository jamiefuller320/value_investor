"""Sunday review dashboard payload: weekly tables, history persistence, experiment sync."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import read_json, write_json

logger = logging.getLogger(__name__)

REVIEW_HISTORY_FILENAME = "review_history.json"
DEFAULT_HISTORY_KEEP_WEEKS = 52


def _safe_read(path: Path) -> dict[str, Any] | None:
    try:
        raw = read_json(path)
    except FileNotFoundError:
        return None
    return raw if isinstance(raw, dict) else None


def _week_key(iso_timestamp: str | None) -> str | None:
    if not iso_timestamp:
        return None
    return str(iso_timestamp)[:10]


def _pct(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value) * 100, digits)


def slim_exclusion_weekly_rows(
    archive: dict[str, Any] | None,
    *,
    step_id: str | None = None,
) -> list[dict[str, Any]]:
    """Extract week-pair rows for the recommended (or chosen) ladder step."""
    if not archive:
        return []
    recommended = archive.get("recommended_step") or {}
    target_step = step_id or (
        recommended.get("step_id") if isinstance(recommended, dict) else recommended
    )
    if not target_step:
        target_step = "u4"

    ladder_results = archive.get("ladder_results") or []
    step_row = next((row for row in ladder_results if row.get("step_id") == target_step), None)
    if not step_row:
        return []

    weekly: list[dict[str, Any]] = []
    for row in step_row.get("weekly") or []:
        if not isinstance(row, dict):
            continue
        baseline = row.get("baseline_ew_return")
        filtered = row.get("filtered_ew_return")
        benchmark = row.get("benchmark_return")
        exclusion_alpha = row.get("exclusion_alpha")
        filtered_vs_benchmark = None
        if filtered is not None and benchmark is not None:
            filtered_vs_benchmark = round(float(filtered) - float(benchmark), 6)
        hindsight = row.get("hindsight") or {}
        weekly.append(
            {
                "week_start": row.get("run_at"),
                "week_end": row.get("exit_run_at"),
                "baseline_ew_return": baseline,
                "filtered_ew_return": filtered,
                "benchmark_return": benchmark,
                "exclusion_alpha": exclusion_alpha,
                "filtered_vs_benchmark": filtered_vs_benchmark,
                "baseline_pool_size": row.get("baseline_pool_size"),
                "filtered_pool_size": row.get("filtered_pool_size"),
                "excluded_count": row.get("excluded_count"),
                "bottom_quartile_exclude_rate": hindsight.get("bottom_quartile_exclude_rate"),
                "top_quartile_retain_rate": hindsight.get("top_quartile_retain_rate"),
            }
        )
    return weekly


def slim_paper_track_rows(learning_review: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not learning_review:
        return []
    rows: list[dict[str, Any]] = []
    reviews = learning_review.get("reviews") or {}
    if not isinstance(reviews, dict):
        return rows

    for track_id, review in reviews.items():
        if not isinstance(review, dict):
            continue
        metrics = review.get("metrics") or {}
        epoch = metrics.get("epoch") or {}
        rows.append(
            {
                "track_id": track_id,
                "track_label": review.get("track_label") or track_id,
                "excess_after_costs": metrics.get("excess_after_costs"),
                "benchmark_return": metrics.get("benchmark_return"),
                "total_return": metrics.get("total_return"),
                "cost_drag": metrics.get("cost_drag"),
                "trade_count": metrics.get("trade_count"),
                "equity_marks": metrics.get("equity_marks"),
                "positions": metrics.get("positions"),
                "epoch_excess_after_costs": epoch.get("excess_after_costs"),
                "epoch_marks": epoch.get("equity_marks"),
                "min_conviction": (review.get("knobs_after") or {}).get("min_conviction"),
                "is_primary": bool(review.get("is_primary_learning_track")),
            }
        )

    primary = learning_review.get("primary_learning_track")
    rows.sort(
        key=lambda row: (
            0 if row.get("track_id") == primary else 1,
            0 if row.get("is_primary") else 1,
            str(row.get("track_id") or ""),
        )
    )
    return rows


def slim_regime_row(regime: dict[str, Any] | None) -> dict[str, Any] | None:
    if not regime:
        return None
    window = (regime.get("windows") or [{}])[0] if regime.get("windows") else {}
    if not isinstance(window, dict):
        window = {}
    ladder_readiness = regime.get("ladder_replay_readiness") or {}
    return {
        "recommended_exclusion_step": regime.get("recommended_exclusion_step"),
        "cumulative_exclusion_alpha": window.get("cumulative_exclusion_alpha"),
        "positive_alpha_rate": window.get("positive_alpha_rate"),
        "exclusion_week_pairs": window.get("exclusion_week_pairs"),
        "bottom_quartile_exclude_rate": window.get("bottom_quartile_exclude_rate"),
        "top_quartile_retain_rate": window.get("top_quartile_retain_rate"),
        "replay_return_delta_vs_actual": window.get("replay_return_delta_vs_actual"),
        "primary_excess_after_costs": window.get("primary_excess_after_costs"),
        "beat_market": window.get("beat_market"),
        "beat_control": window.get("beat_control"),
        "ready_for_shadow_spawn": ladder_readiness.get("ready_for_shadow_spawn"),
        "knob_calibration_ready": regime.get("knob_calibration_ready"),
        "flags": regime.get("flags") or [],
        "history_run_count": window.get("history_run_count"),
    }


def slim_experiment_rows(experiment_assessment: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not experiment_assessment:
        return []
    rows: list[dict[str, Any]] = []
    for exp in experiment_assessment.get("experiments") or []:
        if not isinstance(exp, dict):
            continue
        rows.append(
            {
                "experiment_id": exp.get("experiment_id"),
                "kind": exp.get("kind"),
                "title": exp.get("title"),
                "area": exp.get("area"),
                "pipeline": exp.get("pipeline"),
                "status": exp.get("status"),
                "track_id": exp.get("track_id"),
                "gate_marks": exp.get("gate_marks"),
                "gate_excess_after_costs": exp.get("gate_excess_after_costs"),
                "excess_vs_primary": exp.get("excess_vs_parent") or exp.get("excess_vs_primary"),
                "human_ack_required": bool(exp.get("human_ack_required")),
                "initiated_at": exp.get("initiated_at"),
            }
        )
    status_order = {
        "recommend": 0,
        "continue": 1,
        "observing": 2,
        "proposed": 3,
        "fail": 4,
    }
    rows.sort(
        key=lambda row: (
            status_order.get(str(row.get("status") or ""), 9),
            str(row.get("kind") or ""),
            str(row.get("experiment_id") or ""),
        )
    )
    return rows


def build_week_snapshot(
    *,
    week_ending: str,
    reviewed_at: str | None = None,
    exclusion_archive: dict[str, Any] | None = None,
    exclusion_review: dict[str, Any] | None = None,
    learning_tracks_review: dict[str, Any] | None = None,
    regime_summary: dict[str, Any] | None = None,
    experiment_assessment: dict[str, Any] | None = None,
    analysis_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One dated Sunday review snapshot for history persistence."""
    archive = exclusion_archive or exclusion_review
    recommended = (exclusion_review or {}).get("recommended_step") or (
        (archive or {}).get("recommended_step")
    )
    rec_step_id = (
        recommended.get("step_id") if isinstance(recommended, dict) else recommended
    ) or "u4"

    ladder_results = (archive or {}).get("ladder_results") or []
    rec_summary = {}
    for row in ladder_results:
        if row.get("step_id") == rec_step_id:
            rec_summary = row.get("summary") or {}
            break

    return {
        "week_ending": week_ending,
        "reviewed_at": reviewed_at or datetime.now(UTC).isoformat(),
        "exclusion": {
            "recommended_step_id": rec_step_id,
            "summary": {
                "cumulative_exclusion_alpha": rec_summary.get("cumulative_exclusion_alpha"),
                "positive_alpha_rate": rec_summary.get("positive_alpha_rate"),
                "week_pairs": rec_summary.get("week_pairs"),
                "avg_filtered_pool_size": rec_summary.get("avg_filtered_pool_size"),
            },
            "weekly": slim_exclusion_weekly_rows(archive, step_id=rec_step_id),
        },
        "paper_tracks": slim_paper_track_rows(learning_tracks_review),
        "regime": slim_regime_row(regime_summary),
        "experiments": slim_experiment_rows(experiment_assessment),
        "analysis_headline": (
            ((analysis_review or {}).get("sections") or {}).get("executive_summary") or ""
        )[:400]
        or None,
    }


def load_review_history(path: Path) -> dict[str, Any]:
    raw = _safe_read(path)
    if not raw:
        return {
            "schema_version": 1,
            "updated_at": None,
            "keep_weeks": DEFAULT_HISTORY_KEEP_WEEKS,
            "weeks": [],
        }
    weeks = [row for row in (raw.get("weeks") or []) if isinstance(row, dict)]
    return {
        "schema_version": int(raw.get("schema_version") or 1),
        "updated_at": raw.get("updated_at"),
        "keep_weeks": int(raw.get("keep_weeks") or DEFAULT_HISTORY_KEEP_WEEKS),
        "weeks": weeks,
    }


def upsert_review_history(
    history: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    keep_weeks: int | None = None,
) -> dict[str, Any]:
    """Insert or replace snapshot by week_ending; prune to keep_weeks."""
    week_key = snapshot.get("week_ending")
    if not week_key:
        return history

    weeks = [row for row in (history.get("weeks") or []) if row.get("week_ending") != week_key]
    weeks.append(snapshot)
    weeks.sort(key=lambda row: str(row.get("week_ending") or ""), reverse=True)

    limit = keep_weeks if keep_weeks is not None else int(history.get("keep_weeks") or DEFAULT_HISTORY_KEEP_WEEKS)
    weeks = weeks[: max(1, limit)]

    return {
        "schema_version": 1,
        "updated_at": datetime.now(UTC).isoformat(),
        "keep_weeks": limit,
        "weeks": weeks,
    }


def backfill_history_from_archives(
    archive_dir: Path,
    *,
    existing_weeks: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Build snapshots from dated dashboard archives (learning_tracks_review only)."""
    if not archive_dir.exists():
        return []
    existing = existing_weeks or set()
    snapshots: list[dict[str, Any]] = []

    for path in sorted(archive_dir.glob("*.json")):
        week_ending = path.stem
        if week_ending in existing:
            continue
        try:
            bundle = read_json(path)
        except (OSError, ValueError):
            continue
        if not isinstance(bundle, dict):
            continue
        learning = bundle.get("learning_tracks_review")
        if not learning:
            continue
        snapshots.append(
            build_week_snapshot(
                week_ending=week_ending,
                reviewed_at=bundle.get("generated_at"),
                learning_tracks_review=learning,
            )
        )
    return snapshots


def persist_review_history(
    data_dir: Path,
    snapshot: dict[str, Any],
    *,
    archive_dir: Path | None = None,
    backfill: bool = True,
    keep_weeks: int = DEFAULT_HISTORY_KEEP_WEEKS,
) -> dict[str, Any]:
    """Write review_history.json with upsert + optional archive backfill."""
    data_dir = Path(data_dir)
    history_path = data_dir / REVIEW_HISTORY_FILENAME
    history = load_review_history(history_path)
    existing_keys = {str(row.get("week_ending")) for row in history.get("weeks") or []}

    if backfill and archive_dir:
        archive_dir = Path(archive_dir)
        for row in backfill_history_from_archives(archive_dir, existing_weeks=existing_keys):
            history = upsert_review_history(history, row, keep_weeks=keep_weeks)
            existing_keys.add(str(row.get("week_ending")))

    history = upsert_review_history(history, snapshot, keep_weeks=keep_weeks)
    write_json(history_path, history, compact=False)
    return history


def ensure_experiment_assessment_fresh(
    data_dir: Path,
    *,
    paper_root: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Refresh experiment ledger so new shadows/tracks appear immediately."""
    try:
        from value_investor.experiment_assessment import refresh_experiment_assessment

        return refresh_experiment_assessment(
            data_dir,
            paper_root=paper_root,
            output_dir=output_dir,
            fetch_benchmark=False,
            sync_task_status=False,
        )
    except Exception as exc:  # noqa: BLE001 — publish must not fail
        logger.warning("Experiment assessment refresh skipped: %s", exc)
        return _safe_read(data_dir / "experiment_assessment.json")


def build_sunday_review_dashboard(
    data_dir: Path,
    *,
    paper_root: Path | None = None,
    output_dir: Path | None = None,
    archive_dir: Path | None = None,
    run_at: str | None = None,
    persist_history: bool = True,
    refresh_experiments: bool = True,
) -> dict[str, Any]:
    """
    Assemble Sunday review tables for the dashboard bundle.

    When ``persist_history`` is true, upserts the current week into
    ``review_history.json`` under ``data_dir``.
    """
    data_dir = Path(data_dir)
    paper_root = Path(paper_root or data_dir / "paper_automation")
    output_dir = Path(output_dir or Path("output"))

    experiment_assessment = None
    if refresh_experiments:
        experiment_assessment = ensure_experiment_assessment_fresh(
            data_dir, paper_root=paper_root, output_dir=output_dir
        )
    if experiment_assessment is None:
        experiment_assessment = _safe_read(data_dir / "experiment_assessment.json")

    exclusion_archive = _safe_read(data_dir / "exclusion_universe_archive.json")
    exclusion_review = _safe_read(data_dir / "exclusion_universe_review.json")
    learning_tracks_review = _safe_read(paper_root / "learning_tracks_review.json")
    analysis_review = _safe_read(data_dir / "analysis_review.json")

    from value_investor.learning_director_regime import build_regime_summary

    history_run_count = 0
    history_dir = data_dir / "history"
    if history_dir.exists():
        history_run_count = len(list(history_dir.glob("run_*.json"))) + len(
            list(history_dir.glob("run_*.json.gz"))
        )
    regime_summary = build_regime_summary(
        data_dir, paper_root=paper_root, history_run_count=history_run_count
    )

    week_ending = _week_key(run_at) or _week_key(datetime.now(UTC).isoformat())
    assert week_ending is not None

    current = build_week_snapshot(
        week_ending=week_ending,
        reviewed_at=datetime.now(UTC).isoformat(),
        exclusion_archive=exclusion_archive,
        exclusion_review=exclusion_review,
        learning_tracks_review=learning_tracks_review,
        regime_summary=regime_summary,
        experiment_assessment=experiment_assessment,
        analysis_review=analysis_review,
    )

    history = load_review_history(data_dir / REVIEW_HISTORY_FILENAME)
    if persist_history:
        resolved_archive = archive_dir or (data_dir / "archive")
        history = persist_review_history(
            data_dir,
            current,
            archive_dir=resolved_archive,
            backfill=True,
        )

    recommended_step = (exclusion_review or {}).get("recommended_step") or {}
    readiness = (exclusion_review or {}).get("readiness") or {}

    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "week_ending": week_ending,
        "recommended_exclusion_step": (
            recommended_step.get("step_id")
            if isinstance(recommended_step, dict)
            else recommended_step
        ),
        "readiness": {
            "ready_for_priors": readiness.get("ready_for_priors"),
            "ready_for_shadow_spawn": (regime_summary.get("ladder_replay_readiness") or {}).get(
                "ready_for_shadow_spawn"
            ),
            "week_pairs": readiness.get("week_pairs"),
        },
        "current": current,
        "history": history.get("weeks") or [],
        "experiment_summary": (experiment_assessment or {}).get("summary"),
        "note": (
            "Sunday review tables — exclusion week-pairs, paper track snapshots, regime flags, "
            "and unified experiments. History persists on each ftse-publish."
        ),
    }


__all__ = [
    "REVIEW_HISTORY_FILENAME",
    "DEFAULT_HISTORY_KEEP_WEEKS",
    "backfill_history_from_archives",
    "build_sunday_review_dashboard",
    "build_week_snapshot",
    "ensure_experiment_assessment_fresh",
    "load_review_history",
    "persist_review_history",
    "slim_exclusion_weekly_rows",
    "slim_experiment_rows",
    "slim_paper_track_rows",
    "slim_regime_row",
    "upsert_review_history",
]
