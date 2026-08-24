"""Unified evidence-gated experiment assessment ledger (observe-only)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.calibration_endurance import (
    DEFAULT_MIN_EXCESS_VS_MARKET,
    DEFAULT_MIN_MARKS_FOR_SURVIVOR,
    ENDURANCE_FILENAME,
    _classify_status,
    _fund_metrics_snapshot,
)
from value_investor.exclusion_ladder_replay import (
    discover_exclusion_shadow_step_ids,
    exclusion_shadow_subdir,
    exclusion_shadow_track_id,
)
from value_investor.paper_automation import AI_JUDGMENT_TRACK_ID, CONFIG_FILENAME, AutomationConfig
from value_investor.storage import read_json, write_json

ASSESSMENT_FILENAME = "experiment_assessment.json"
ASSESSMENT_STATUSES = frozenset({"proposed", "observing", "continue", "fail", "recommend"})


def _safe_read(path: Path) -> dict[str, Any] | None:
    try:
        raw = read_json(path)
    except FileNotFoundError:
        return None
    return raw if isinstance(raw, dict) else None


def map_endurance_status_to_assessment(
    endurance_status: str,
    *,
    gate_marks: int | None,
    min_marks: int,
) -> str:
    """Map calibration endurance observing/surviving/failed to unified assessment."""
    normalized = str(endurance_status or "observing").strip().lower()
    if normalized == "failed":
        return "fail"
    if normalized == "surviving":
        return "recommend"
    if gate_marks is not None and int(gate_marks) >= int(min_marks):
        return "continue"
    return "observing"


def _gate_fields(metrics: dict[str, Any]) -> tuple[float | None, int | None]:
    if metrics.get("gate_uses_post_seed"):
        excess = metrics.get("gate_excess_after_costs")
        marks = metrics.get("gate_equity_marks")
    else:
        excess = metrics.get("excess_after_costs")
        marks = metrics.get("equity_marks")
    return (
        float(excess) if excess is not None else None,
        int(marks) if marks is not None else None,
    )


def _experiments_from_calibration_endurance(
    endurance: dict[str, Any] | None,
    *,
    min_marks: int,
) -> list[dict[str, Any]]:
    if not endurance:
        return []
    rows: list[dict[str, Any]] = []
    for shadow in endurance.get("shadows") or []:
        metrics = shadow.get("metrics") or {}
        gate_excess, gate_marks = _gate_fields(metrics)
        endurance_status = str(shadow.get("status") or "observing")
        assessment = map_endurance_status_to_assessment(
            endurance_status,
            gate_marks=gate_marks,
            min_marks=min_marks,
        )
        rows.append(
            {
                "experiment_id": shadow.get("shadow_track_id"),
                "kind": "calibration_shadow",
                "title": f"Calibrated shadow rank {shadow.get('rank')}",
                "area": "paper_knobs",
                "pipeline": "knob_calibration",
                "status": assessment,
                "source_status": endurance_status,
                "human_ack_required": assessment == "recommend",
                "track_id": shadow.get("shadow_track_id"),
                "rank": shadow.get("rank"),
                "knobs": shadow.get("knobs"),
                "gate_marks": gate_marks,
                "gate_excess_after_costs": gate_excess,
                "excess_vs_primary": shadow.get("excess_vs_primary"),
                "excess_vs_rules": shadow.get("excess_vs_rules"),
                "gate_uses_post_seed": shadow.get("gate_uses_post_seed"),
                "evidence_path": shadow.get("provenance_path"),
            }
        )
    return rows


def _experiments_from_exclusion_shadows(
    paper_root: Path,
    *,
    min_marks: int,
    min_excess_vs_parent: float,
    fetch_benchmark: bool = False,
) -> list[dict[str, Any]]:
    paper_root = Path(paper_root)
    rows: list[dict[str, Any]] = []
    for step_id in discover_exclusion_shadow_step_ids(paper_root):
        track_id = exclusion_shadow_track_id(step_id)
        track_dir = paper_root / exclusion_shadow_subdir(step_id)
        parent_track = AI_JUDGMENT_TRACK_ID
        config_path = track_dir / CONFIG_FILENAME
        if config_path.exists():
            cfg = AutomationConfig.from_dict(read_json(config_path))
            parent_track = cfg.exclusion_parent_track or parent_track

        parent_dir = paper_root / parent_track
        parent_metrics = _fund_metrics_snapshot(parent_dir) if parent_dir.exists() else {}
        shadow_metrics = _fund_metrics_snapshot(
            track_dir,
            prefer_post_seed=True,
            fetch_benchmark=fetch_benchmark,
        )
        gate_excess, gate_marks = _gate_fields(shadow_metrics)
        parent_excess = parent_metrics.get("excess_after_costs")
        vs_parent = None
        if gate_excess is not None and parent_excess is not None:
            vs_parent = round(float(gate_excess) - float(parent_excess), 4)

        endurance_status = _classify_status(
            marks=gate_marks,
            excess=gate_excess,
            vs_primary=vs_parent,
            vs_rules=None,
            min_marks=min_marks,
            min_excess=min_excess_vs_parent,
        )
        assessment = map_endurance_status_to_assessment(
            endurance_status,
            gate_marks=gate_marks,
            min_marks=min_marks,
        )
        provenance_path = track_dir / "exclusion_provenance.json"
        rows.append(
            {
                "experiment_id": track_id,
                "kind": "exclusion_shadow",
                "title": f"Exclusion ladder shadow {step_id}",
                "area": "paper_knobs",
                "pipeline": "exclusion_ladder",
                "status": assessment,
                "source_status": endurance_status,
                "human_ack_required": assessment == "recommend",
                "track_id": track_id,
                "exclusion_ladder_step_id": step_id,
                "parent_track_id": parent_track,
                "gate_marks": gate_marks,
                "gate_excess_after_costs": gate_excess,
                "excess_vs_parent": vs_parent,
                "gate_uses_post_seed": bool(shadow_metrics.get("gate_uses_post_seed")),
                "evidence_path": str(provenance_path) if provenance_path.exists() else None,
            }
        )
    return rows


def _open_task_rows(tasks_path: Path, *, kind: str, pipeline: str) -> list[dict[str, Any]]:
    raw = _safe_read(tasks_path)
    if not raw:
        return []
    rows: list[dict[str, Any]] = []
    for task in raw.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        status = str(task.get("status") or "proposed").strip().lower()
        if status in {"promoted", "cancelled"}:
            continue
        area = str(task.get("area") or "").strip().lower()
        assessment = "proposed" if status == "proposed" else "observing"
        rows.append(
            {
                "experiment_id": task.get("id"),
                "kind": kind,
                "title": task.get("title") or task.get("summary") or task.get("id"),
                "area": area,
                "pipeline": pipeline,
                "status": assessment,
                "source_status": status,
                "human_ack_required": False,
                "task_status": status,
                "promote_to": task.get("promote_to"),
                "evidence_path": str(tasks_path),
            }
        )
    return rows


def _experiments_from_task_queues(data_dir: Path) -> list[dict[str, Any]]:
    data_dir = Path(data_dir)
    return [
        *_open_task_rows(
            data_dir / "analysis_tasks.json",
            kind="analysis_task",
            pipeline="analysis_review",
        ),
        *_open_task_rows(
            data_dir / "paper_learning_tasks.json",
            kind="paper_learning_task",
            pipeline="paper_learning_review",
        ),
        *_open_task_rows(
            data_dir / "learning_director_tasks.json",
            kind="learning_director_task",
            pipeline="learning_director",
        ),
    ]


def _summary_counts(experiments: list[dict[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in ASSESSMENT_STATUSES}
    for row in experiments:
        status = str(row.get("status") or "proposed")
        if status in counts:
            counts[status] += 1
    counts["human_ack_pending"] = counts.get("recommend", 0)
    counts["total"] = len(experiments)
    return counts


def refresh_experiment_assessment(
    data_dir: Path,
    *,
    paper_root: Path | None = None,
    min_marks: int = DEFAULT_MIN_MARKS_FOR_SURVIVOR,
    min_excess_vs_market: float = DEFAULT_MIN_EXCESS_VS_MARKET,
    min_excess_vs_parent: float = 0.0,
    fetch_benchmark: bool = False,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """
    Build/update unified experiment assessment ledger.

    Shadow tracks use evidence gates (marks + excess). Task-queue rows stay
    ``proposed`` until specialist pipelines attach forward evidence.
    ``recommend`` rows require human ack — never auto-apply (N42).
    """
    data_dir = Path(data_dir)
    paper_root = Path(paper_root or data_dir / "paper_automation")
    endurance = _safe_read(paper_root / ENDURANCE_FILENAME)

    experiments: list[dict[str, Any]] = []
    experiments.extend(
        _experiments_from_calibration_endurance(endurance, min_marks=min_marks)
    )
    experiments.extend(
        _experiments_from_exclusion_shadows(
            paper_root,
            min_marks=min_marks,
            min_excess_vs_parent=min_excess_vs_parent,
            fetch_benchmark=fetch_benchmark,
        )
    )
    experiments.extend(_experiments_from_task_queues(data_dir))

    recommendations = [
        {
            "experiment_id": row.get("experiment_id"),
            "kind": row.get("kind"),
            "title": row.get("title"),
            "pipeline": row.get("pipeline"),
            "track_id": row.get("track_id"),
            "gate_marks": row.get("gate_marks"),
            "gate_excess_after_costs": row.get("gate_excess_after_costs"),
        }
        for row in experiments
        if row.get("status") == "recommend"
    ]

    payload = {
        "schema_version": 1,
        "observe_only": True,
        "updated_at": datetime.now(UTC).isoformat(),
        "data_dir": str(data_dir),
        "paper_root": str(paper_root),
        "gates": {
            "min_marks_for_evidence": min_marks,
            "min_excess_vs_market": min_excess_vs_market,
            "min_excess_vs_parent": min_excess_vs_parent,
            "states": sorted(ASSESSMENT_STATUSES),
            "promotion": (
                "recommend rows are human-gate only — never auto-apply knobs, "
                "config, or engineering tasks"
            ),
        },
        "summary": _summary_counts(experiments),
        "experiments": experiments,
        "recommendations": recommendations,
        "sources": {
            "calibration_shadow_endurance": str(paper_root / ENDURANCE_FILENAME),
            "analysis_tasks": str(data_dir / "analysis_tasks.json"),
            "paper_learning_tasks": str(data_dir / "paper_learning_tasks.json"),
            "learning_director_tasks": str(data_dir / "learning_director_tasks.json"),
        },
    }
    dest = output_path or (data_dir / ASSESSMENT_FILENAME)
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_json(dest, payload, compact=False)
    payload["path"] = str(dest)
    return payload


def slim_experiment_assessment_for_review(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Compact view for analysis-review / learning-director payloads."""
    if not payload:
        return None
    experiments = payload.get("experiments") or []
    by_status: dict[str, list[dict[str, Any]]] = {status: [] for status in ASSESSMENT_STATUSES}
    for row in experiments:
        status = str(row.get("status") or "proposed")
        if status not in by_status:
            continue
        slim = {
            "experiment_id": row.get("experiment_id"),
            "kind": row.get("kind"),
            "title": row.get("title"),
            "area": row.get("area"),
            "pipeline": row.get("pipeline"),
            "status": status,
            "human_ack_required": bool(row.get("human_ack_required")),
        }
        if row.get("track_id"):
            slim["track_id"] = row.get("track_id")
        if row.get("gate_marks") is not None:
            slim["gate_marks"] = row.get("gate_marks")
        if row.get("gate_excess_after_costs") is not None:
            slim["gate_excess_after_costs"] = row.get("gate_excess_after_costs")
        by_status[status].append(slim)

    return {
        "updated_at": payload.get("updated_at"),
        "summary": payload.get("summary"),
        "recommendations": payload.get("recommendations") or [],
        "by_status": {key: rows for key, rows in by_status.items() if rows},
        "note": (
            "Unified assessment loop: proposed → observing → continue | fail | recommend. "
            "Only recommend requires human ack; never auto-apply."
        ),
    }


__all__ = [
    "ASSESSMENT_FILENAME",
    "ASSESSMENT_STATUSES",
    "map_endurance_status_to_assessment",
    "refresh_experiment_assessment",
    "slim_experiment_assessment_for_review",
]
