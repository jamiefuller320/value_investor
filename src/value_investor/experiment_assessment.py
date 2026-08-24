"""Unified evidence-gated experiment assessment ledger (observe-only)."""

from __future__ import annotations

from dataclasses import dataclass
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
from value_investor.storage import COMMITTED_HISTORY_DIR, read_json, write_json
from value_investor.trajectory_evidence import build_model_focus_candidates

ASSESSMENT_FILENAME = "experiment_assessment.json"
ASSESSMENT_STATUSES = frozenset({"proposed", "observing", "continue", "fail", "recommend"})
TASK_KINDS = frozenset({"analysis_task", "paper_learning_task", "learning_director_task"})
SCORING_CANDIDATE_MIN_COUNT = 20
EXIT_SHADOW_CONTINUE_CLOSED = 10

TASK_STORES: tuple[tuple[str, Path, str, str], ...] = (
    ("analysis_tasks.json", Path("analysis_tasks.json"), "analysis_task", "analysis_review"),
    (
        "paper_learning_tasks.json",
        Path("paper_learning_tasks.json"),
        "paper_learning_task",
        "paper_learning_review",
    ),
    (
        "learning_director_tasks.json",
        Path("learning_director_tasks.json"),
        "learning_director_task",
        "learning_director",
    ),
)


@dataclass
class AssessmentContext:
    data_dir: Path
    paper_root: Path
    min_marks: int
    min_excess_vs_market: float
    history_run_count: int
    backtest_run_count: int
    simulation_ready: bool
    trajectory_summary: dict[str, Any]
    model_focus_candidates: list[dict[str, Any]]
    loser_top_failed_families: list[tuple[str, int]]
    exit_shadow_closed_total: int
    exit_timing_ready: bool
    experimental_tracks: dict[str, dict[str, Any]]


def _safe_read(path: Path) -> dict[str, Any] | None:
    try:
        raw = read_json(path)
    except FileNotFoundError:
        return None
    return raw if isinstance(raw, dict) else None


def _history_run_count(data_dir: Path, output_dir: Path | None = None) -> int:
    count = 0
    bases = [data_dir / "history", COMMITTED_HISTORY_DIR]
    if output_dir is not None:
        bases.insert(0, output_dir / "history")
    for base in bases:
        if not base.exists():
            continue
        count = max(
            count,
            len(list(base.glob("run_*.json"))) + len(list(base.glob("run_*.json.gz"))),
        )
    return count


def _exit_shadow_closed_total(exit_shadow: dict[str, Any] | None) -> int:
    if not exit_shadow:
        return 0
    total = 0
    for row in (exit_shadow.get("tracks") or {}).values():
        if isinstance(row, dict):
            total += int(row.get("closed_count") or 0)
    return total


def _exit_timing_probability_ready(
    live_timing: dict[str, Any] | None,
    near_miss: dict[str, Any] | None,
) -> bool:
    for payload in (live_timing, near_miss):
        readiness = (payload or {}).get("readiness") or {}
        if readiness.get("ready_for_probability_analysis"):
            return True
    return False


def _load_experimental_tracks(paper_root: Path) -> dict[str, dict[str, Any]]:
    tracks: dict[str, dict[str, Any]] = {}
    root = Path(paper_root)
    if not root.exists():
        return tracks
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
        track_id = str(cfg.get("track_id") or config_path.parent.name)
        tracks[track_id] = {
            "track_id": track_id,
            "track_label": cfg.get("track_label"),
            "path": str(config_path.parent.relative_to(root)),
            "use_momentum_grace": bool(cfg.get("use_momentum_grace")),
            "use_graduated_allocation": bool(cfg.get("use_graduated_allocation")),
        }
    return tracks


def build_assessment_context(
    data_dir: Path,
    *,
    paper_root: Path | None = None,
    output_dir: Path | None = None,
    min_marks: int = DEFAULT_MIN_MARKS_FOR_SURVIVOR,
    min_excess_vs_market: float = DEFAULT_MIN_EXCESS_VS_MARKET,
) -> AssessmentContext:
    data_dir = Path(data_dir)
    paper_root = Path(paper_root or data_dir / "paper_automation")
    output_dir = Path(output_dir or Path("output"))

    latest = _safe_read(data_dir / "latest.json") or {}
    backtest = latest.get("backtest") if isinstance(latest.get("backtest"), dict) else {}
    if not backtest:
        backtest = _safe_read(output_dir / "backtest_summary.json") or {}

    trajectory_review = _safe_read(data_dir / "trajectory_evidence_review.json") or {}
    trajectory_summary = trajectory_review.get("outcome_summary") or {}
    if not isinstance(trajectory_summary, dict):
        trajectory_summary = {}
    candidates = trajectory_review.get("model_focus_candidates")
    if not isinstance(candidates, list):
        candidates = build_model_focus_candidates(trajectory_summary)

    loser_cards = _safe_read(data_dir / "loser_snapshot_cards.json") or {}
    family_counts: dict[str, int] = {}
    for card in (loser_cards.get("cards") or [])[:50]:
        if not isinstance(card, dict):
            continue
        for family in (card.get("screen") or {}).get("failed_families") or []:
            key = str(family)
            family_counts[key] = family_counts.get(key, 0) + 1
    top_failed = sorted(family_counts.items(), key=lambda item: item[1], reverse=True)[:6]

    simulation = latest.get("simulation") if isinstance(latest.get("simulation"), dict) else {}
    if not simulation:
        simulation = _safe_read(output_dir / "simulation_summary.json") or {}
    simulation_ready = any(
        isinstance(simulation.get(key), dict) and simulation[key].get("periods")
        for key in ("screen", "research_overlay", "momentum_grace")
    )

    return AssessmentContext(
        data_dir=data_dir,
        paper_root=paper_root,
        min_marks=min_marks,
        min_excess_vs_market=min_excess_vs_market,
        history_run_count=_history_run_count(data_dir, output_dir),
        backtest_run_count=int(backtest.get("run_count") or 0),
        simulation_ready=bool(simulation_ready),
        trajectory_summary=trajectory_summary,
        model_focus_candidates=[row for row in candidates if isinstance(row, dict)],
        loser_top_failed_families=top_failed,
        exit_shadow_closed_total=_exit_shadow_closed_total(
            _safe_read(paper_root / "learning_tracks_exit_shadow.json")
        ),
        exit_timing_ready=_exit_timing_probability_ready(
            _safe_read(paper_root / "learning_tracks_exit_timing.json"),
            _safe_read(data_dir / "exit_timing_near_miss_review.json"),
        ),
        experimental_tracks=_load_experimental_tracks(paper_root),
    )


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


def _experiments_from_experimental_tracks(
    ctx: AssessmentContext,
    *,
    fetch_benchmark: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    primary_dir = ctx.paper_root / AI_JUDGMENT_TRACK_ID
    primary_metrics = _fund_metrics_snapshot(primary_dir) if primary_dir.exists() else {}
    primary_excess = primary_metrics.get("excess_after_costs")

    for track_id, meta in ctx.experimental_tracks.items():
        track_dir = ctx.paper_root / str(meta.get("path") or track_id)
        metrics = _fund_metrics_snapshot(track_dir, fetch_benchmark=fetch_benchmark)
        gate_excess, gate_marks = _gate_fields(metrics)
        vs_primary = None
        if gate_excess is not None and primary_excess is not None:
            vs_primary = round(float(gate_excess) - float(primary_excess), 4)
        endurance_status = _classify_status(
            marks=gate_marks,
            excess=gate_excess,
            vs_primary=vs_primary,
            vs_rules=None,
            min_marks=ctx.min_marks,
            min_excess=ctx.min_excess_vs_market,
        )
        assessment = map_endurance_status_to_assessment(
            endurance_status,
            gate_marks=gate_marks,
            min_marks=ctx.min_marks,
        )
        area = "paper_churn" if meta.get("use_momentum_grace") else "paper_knobs"
        rows.append(
            {
                "experiment_id": track_id,
                "kind": "experimental_paper_track",
                "title": meta.get("track_label") or track_id,
                "area": area,
                "pipeline": "paper_automation",
                "status": assessment,
                "source_status": endurance_status,
                "human_ack_required": assessment == "recommend",
                "track_id": track_id,
                "gate_marks": gate_marks,
                "gate_excess_after_costs": gate_excess,
                "excess_vs_primary": vs_primary,
                "forward_evidence": {
                    "source": "learning_track_metrics",
                    "use_momentum_grace": meta.get("use_momentum_grace"),
                    "use_graduated_allocation": meta.get("use_graduated_allocation"),
                },
                "evidence_path": str(track_dir / CONFIG_FILENAME),
            }
        )
    return rows


def _task_text(task: dict[str, Any]) -> str:
    return " ".join(
        str(task.get(key) or "")
        for key in ("title", "summary", "area")
    ).lower()


def _assess_task_row(
    task: dict[str, Any],
    *,
    kind: str,
    pipeline: str,
    ctx: AssessmentContext,
    tasks_path: Path,
) -> dict[str, Any]:
    status = str(task.get("status") or "proposed").strip().lower()
    if status in {"promoted", "cancelled"}:
        return {}
    area = str(task.get("area") or "").strip().lower()
    text = _task_text(task)
    forward_evidence: dict[str, Any] = {}
    assessment = "proposed" if status == "proposed" else "observing"
    labeled = int(ctx.trajectory_summary.get("labeled_event_count") or 0)

    if area in {"scoring", "offline_sim"}:
        forward_evidence["trajectory"] = {
            "labeled_event_count": labeled,
            "model_focus_candidates": ctx.model_focus_candidates[:4],
        }
        if labeled >= 20:
            assessment = "observing"
        if ctx.model_focus_candidates:
            assessment = "continue"
        strong = next(
            (
                row
                for row in ctx.model_focus_candidates
                if int(row.get("count") or 0) >= SCORING_CANDIDATE_MIN_COUNT
            ),
            None,
        )
        if area == "scoring" and strong is not None:
            assessment = "recommend"
            forward_evidence["trajectory"]["recommend_candidate"] = {
                "key": strong.get("key"),
                "count": strong.get("count"),
            }
        if area == "offline_sim":
            if ctx.history_run_count >= 2 or ctx.backtest_run_count >= 2:
                assessment = "continue" if assessment == "proposed" else assessment
                forward_evidence["archive"] = {
                    "history_run_count": ctx.history_run_count,
                    "backtest_run_count": ctx.backtest_run_count,
                    "simulation_ready": ctx.simulation_ready,
                }
            elif "seed" in text or "run_count" in text:
                assessment = "proposed"
                forward_evidence["archive"] = {
                    "history_run_count": ctx.history_run_count,
                    "backtest_run_count": ctx.backtest_run_count,
                    "note": "Need >=2 archived runs before offline_sim is actionable",
                }

    elif area == "paper_knobs":
        linked_track = None
        for track_id in ctx.experimental_tracks:
            if track_id in text or track_id.replace("_", " ") in text:
                linked_track = track_id
                break
        if linked_track:
            track_dir = ctx.paper_root / linked_track
            if not track_dir.exists() and ctx.experimental_tracks[linked_track].get("path"):
                track_dir = ctx.paper_root / str(ctx.experimental_tracks[linked_track]["path"])
            metrics = _fund_metrics_snapshot(track_dir) if track_dir.exists() else {}
            gate_excess, gate_marks = _gate_fields(metrics)
            forward_evidence["paper_track"] = {
                "track_id": linked_track,
                "gate_marks": gate_marks,
                "gate_excess_after_costs": gate_excess,
            }
            if gate_marks is not None and int(gate_marks) >= 2:
                assessment = "observing"
            if gate_marks is not None and int(gate_marks) >= ctx.min_marks:
                assessment = "continue"

    elif area in {"paper_churn", "monitoring"}:
        forward_evidence["exit_shadow"] = {
            "closed_total": ctx.exit_shadow_closed_total,
            "exit_timing_ready": ctx.exit_timing_ready,
        }
        if ctx.exit_shadow_closed_total > 0:
            assessment = "observing"
        if ctx.exit_shadow_closed_total >= EXIT_SHADOW_CONTINUE_CLOSED:
            assessment = "continue"
        if ctx.exit_timing_ready:
            assessment = "recommend"

    elif area == "analysis":
        forward_evidence["archive"] = {
            "history_run_count": ctx.history_run_count,
            "backtest_run_count": ctx.backtest_run_count,
        }
        if ctx.history_run_count >= 2:
            assessment = "observing"

    if ctx.loser_top_failed_families and area in {"scoring", "offline_sim"}:
        forward_evidence["loser_cards"] = {
            "top_failed_families": ctx.loser_top_failed_families[:4],
        }

    return {
        "experiment_id": task.get("id"),
        "kind": kind,
        "title": task.get("title") or task.get("summary") or task.get("id"),
        "area": area,
        "pipeline": pipeline,
        "status": assessment,
        "source_status": status,
        "human_ack_required": assessment == "recommend",
        "task_status": status,
        "promote_to": task.get("promote_to"),
        "forward_evidence": forward_evidence or None,
        "evidence_path": str(tasks_path),
    }


def _experiments_from_task_queues(ctx: AssessmentContext) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for filename, _, kind, pipeline in TASK_STORES:
        tasks_path = ctx.data_dir / filename
        raw = _safe_read(tasks_path)
        if not raw:
            continue
        for task in raw.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            row = _assess_task_row(
                task,
                kind=kind,
                pipeline=pipeline,
                ctx=ctx,
                tasks_path=tasks_path,
            )
            if row:
                rows.append(row)
    return rows


def sync_task_assessment_status(
    experiments: list[dict[str, Any]],
    data_dir: Path,
) -> dict[str, Any]:
    """
    Mirror assessment into task JSON stores (observe-only).

    fail → cancelled; recommend → evidence flag only (never auto-promote).
    """
    data_dir = Path(data_dir)
    by_id = {
        str(row.get("experiment_id")): row
        for row in experiments
        if row.get("kind") in TASK_KINDS and row.get("experiment_id")
    }
    if not by_id:
        return {"updated": [], "skipped": []}

    updated: list[str] = []
    skipped: list[str] = []
    now = datetime.now(UTC).isoformat()

    for filename, _, kind, _ in TASK_STORES:
        path = data_dir / filename
        raw = _safe_read(path)
        if not raw:
            continue
        changed = False
        tasks = raw.get("tasks") or []
        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("id") or "")
            row = by_id.get(task_id)
            if not row:
                continue
            assessment = str(row.get("status") or "proposed")
            evidence = dict(task.get("evidence") or {})
            evidence["assessment_status"] = assessment
            evidence["assessment_at"] = now
            if row.get("forward_evidence"):
                evidence["forward_evidence"] = row["forward_evidence"]

            if assessment == "fail" and task.get("status") not in {"cancelled", "promoted"}:
                task["status"] = "cancelled"
                task["cancelled_at"] = now
                task["cancel_reason"] = "Experiment assessment gate failed (auto-sync)"
                task["evidence"] = evidence
                updated.append(task_id)
                changed = True
            elif assessment == "recommend":
                if not evidence.get("assessment_recommend"):
                    evidence["assessment_recommend"] = True
                    task["evidence"] = evidence
                    updated.append(task_id)
                    changed = True
                else:
                    skipped.append(task_id)
            else:
                if evidence != task.get("evidence"):
                    task["evidence"] = evidence
                    updated.append(task_id)
                    changed = True
        if changed:
            write_json(path, raw, compact=True)
    return {"updated": updated, "skipped": skipped}


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
    output_dir: Path | None = None,
    min_marks: int = DEFAULT_MIN_MARKS_FOR_SURVIVOR,
    min_excess_vs_market: float = DEFAULT_MIN_EXCESS_VS_MARKET,
    min_excess_vs_parent: float = 0.0,
    fetch_benchmark: bool = False,
    sync_task_status: bool = False,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """
    Build/update unified experiment assessment ledger.

    Shadow tracks and experimental paper tracks use evidence gates (marks + excess).
    Task-queue rows attach forward_evidence from trajectory, archive depth, and
    churn cohorts. ``recommend`` rows require human ack — never auto-apply (N42).
    """
    data_dir = Path(data_dir)
    paper_root = Path(paper_root or data_dir / "paper_automation")
    ctx = build_assessment_context(
        data_dir,
        paper_root=paper_root,
        output_dir=output_dir,
        min_marks=min_marks,
        min_excess_vs_market=min_excess_vs_market,
    )
    endurance = _safe_read(paper_root / ENDURANCE_FILENAME)

    experiments: list[dict[str, Any]] = []
    experiments.extend(_experiments_from_calibration_endurance(endurance, min_marks=min_marks))
    experiments.extend(
        _experiments_from_exclusion_shadows(
            paper_root,
            min_marks=min_marks,
            min_excess_vs_parent=min_excess_vs_parent,
            fetch_benchmark=fetch_benchmark,
        )
    )
    experiments.extend(_experiments_from_experimental_tracks(ctx, fetch_benchmark=fetch_benchmark))
    experiments.extend(_experiments_from_task_queues(ctx))

    sync_result: dict[str, Any] | None = None
    if sync_task_status:
        sync_result = sync_task_assessment_status(experiments, data_dir)

    recommendations = [
        {
            "experiment_id": row.get("experiment_id"),
            "kind": row.get("kind"),
            "title": row.get("title"),
            "pipeline": row.get("pipeline"),
            "track_id": row.get("track_id"),
            "gate_marks": row.get("gate_marks"),
            "gate_excess_after_costs": row.get("gate_excess_after_costs"),
            "area": row.get("area"),
        }
        for row in experiments
        if row.get("status") == "recommend"
    ]

    payload = {
        "schema_version": 2,
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
        "context": {
            "history_run_count": ctx.history_run_count,
            "backtest_run_count": ctx.backtest_run_count,
            "trajectory_labeled_events": ctx.trajectory_summary.get("labeled_event_count"),
            "exit_shadow_closed_total": ctx.exit_shadow_closed_total,
            "experimental_track_count": len(ctx.experimental_tracks),
        },
        "summary": _summary_counts(experiments),
        "experiments": experiments,
        "recommendations": recommendations,
        "task_sync": sync_result,
        "sources": {
            "calibration_shadow_endurance": str(paper_root / ENDURANCE_FILENAME),
            "analysis_tasks": str(data_dir / "analysis_tasks.json"),
            "paper_learning_tasks": str(data_dir / "paper_learning_tasks.json"),
            "learning_director_tasks": str(data_dir / "learning_director_tasks.json"),
            "trajectory_evidence_review": str(data_dir / "trajectory_evidence_review.json"),
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
        if row.get("forward_evidence"):
            slim["forward_evidence"] = row.get("forward_evidence")
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
    "AssessmentContext",
    "build_assessment_context",
    "map_endurance_status_to_assessment",
    "refresh_experiment_assessment",
    "slim_experiment_assessment_for_review",
    "sync_task_assessment_status",
]
