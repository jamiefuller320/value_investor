"""Modelling and learning-track analysis synthesis (read-only, no live trading changes)."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions

from value_investor.experiment_assessment import slim_experiment_assessment_for_review
from value_investor.knob_calibration import KNOB_CALIBRATION_PRIORS_FILENAME
from value_investor.review_payload_slim import (
    slim_backtest as _slim_backtest,
)
from value_investor.review_payload_slim import (
    slim_exclusion_ladder_replay as _slim_exclusion_ladder_replay,
)
from value_investor.review_payload_slim import (
    slim_exclusion_universe as _slim_exclusion_universe,
)
from value_investor.review_payload_slim import (
    slim_exit_timing as _slim_exit_timing,
)
from value_investor.review_payload_slim import (
    slim_historical as _slim_historical,
)
from value_investor.review_payload_slim import (
    slim_hypothesis_integrity as _slim_hypothesis_integrity,
)
from value_investor.review_payload_slim import (
    slim_loser_snapshot_cards as _slim_loser_snapshot_cards,
)
from value_investor.review_payload_slim import (
    slim_hypothesis_outcomes as _slim_hypothesis_outcomes,
)
from value_investor.review_payload_slim import (
    slim_simulation as _slim_simulation,
)
from value_investor.storage import COMMITTED_HISTORY_DIR, read_json, write_json
from value_investor.trajectory_evidence import slim_trajectory_evidence_for_review

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path("docs/data")
DEFAULT_OUTPUT_DIR = Path("output")
COMMITTED_REVIEW_PATH = DEFAULT_DATA_DIR / "analysis_review.json"
COMMITTED_REVIEW_MD_PATH = DEFAULT_DATA_DIR / "analysis_review.md"
COMMITTED_TASKS_PATH = DEFAULT_DATA_DIR / "analysis_tasks.json"
PAPER_AUTOMATION_DIR = DEFAULT_DATA_DIR / "paper_automation"

_EXPERIMENT_LINE = re.compile(
    r"^\s*(?P<index>\d+)\.\s*(?:\*\*)?\[(?P<area>[^\]]+)\](?:\*\*)?\s*(?P<title>.+)$",
    re.IGNORECASE,
)
_ENGINEERING_AREAS = frozenset({"scoring", "ingest", "prompt", "coverage", "ops"})
_ANALYSIS_ONLY_AREAS = frozenset(
    {"offline_sim", "paper_knobs", "paper_churn", "attribution", "monitoring", "analysis"}
)


@dataclass
class AnalysisReview:
    executive_summary: str
    performance_diagnosis: str
    signal_backtest_findings: str
    paper_track_comparison: str
    proposed_experiments: str
    defer: str

    @property
    def full_text(self) -> str:
        parts = [
            ("EXECUTIVE SUMMARY", self.executive_summary),
            ("PERFORMANCE DIAGNOSIS", self.performance_diagnosis),
            ("SIGNAL & BACKTEST FINDINGS", self.signal_backtest_findings),
            ("PAPER TRACK COMPARISON", self.paper_track_comparison),
            ("PROPOSED EXPERIMENTS", self.proposed_experiments),
            ("DEFER", self.defer),
        ]
        return "\n\n".join(f"{heading}\n{body.strip()}" for heading, body in parts if body.strip())


@dataclass
class AnalysisTask:
    id: str
    area: str
    title: str
    summary: str
    experiment_type: str
    priority: str = "medium"
    status: str = "proposed"
    source: str = "analysis_review"
    promote_to: str = "manual"
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "area": self.area,
            "title": self.title,
            "summary": self.summary,
            "experiment_type": self.experiment_type,
            "priority": self.priority,
            "status": self.status,
            "source": self.source,
            "promote_to": self.promote_to,
            "evidence": self.evidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnalysisTask:
        return cls(
            id=str(data.get("id") or ""),
            area=str(data.get("area") or "analysis"),
            title=str(data.get("title") or ""),
            summary=str(data.get("summary") or ""),
            experiment_type=str(data.get("experiment_type") or "observe"),
            priority=str(data.get("priority") or "medium"),
            status=str(data.get("status") or "proposed"),
            source=str(data.get("source") or "analysis_review"),
            promote_to=str(data.get("promote_to") or "manual"),
            evidence=dict(data.get("evidence") or {}),
        )


def _normalize_heading(line: str) -> str:
    text = line.strip().lstrip("#").strip()
    if text.startswith("**") and text.endswith("**") and len(text) > 4:
        text = text[2:-2].strip()
    return text.rstrip(":").strip().upper()


def parse_analysis_review(text: str) -> AnalysisReview:
    section_keys = {
        "EXECUTIVE SUMMARY": "executive_summary",
        "PERFORMANCE DIAGNOSIS": "performance_diagnosis",
        "SIGNAL & BACKTEST FINDINGS": "signal_backtest_findings",
        "SIGNAL AND BACKTEST FINDINGS": "signal_backtest_findings",
        "PAPER TRACK COMPARISON": "paper_track_comparison",
        "PROPOSED EXPERIMENTS": "proposed_experiments",
        "DEFER": "defer",
        "DO NOT BUILD YET": "defer",
    }
    sections = {key: "" for key in section_keys.values()}
    current = "executive_summary"
    lines: list[str] = []

    for line in text.splitlines():
        upper = _normalize_heading(line)
        if upper in section_keys:
            if lines:
                sections[current] = "\n".join(lines).strip()
                lines = []
            current = section_keys[upper]
            continue
        lines.append(line)

    if lines:
        sections[current] = "\n".join(lines).strip()

    if not any(sections.values()):
        sections["executive_summary"] = text.strip()

    return AnalysisReview(**sections)


def _safe_read(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    try:
        return read_json(path)
    except (OSError, ValueError, TypeError):
        return None


def _history_run_count(data_dir: Path, output_dir: Path) -> int:
    count = 0
    for base in (data_dir / "history", output_dir / "history", COMMITTED_HISTORY_DIR):
        if not base.exists():
            continue
        count = max(
            count,
            len(list(base.glob("run_*.json"))) + len(list(base.glob("run_*.json.gz"))),
        )
    return count


def build_analysis_payload(
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    run_at: datetime | None = None,
) -> dict[str, Any]:
    """Assemble deterministic inputs for the modelling/analysis synthesis agent."""
    effective_run_at = run_at or datetime.now(UTC)

    latest = _safe_read(data_dir / "latest.json") or {}
    backtest = _slim_backtest(
        _safe_read(output_dir / "backtest_summary.json") or latest.get("backtest")
    )
    simulation = _slim_simulation(
        _safe_read(output_dir / "simulation_summary.json") or latest.get("simulation")
    )
    historical = _slim_historical(
        _safe_read(output_dir / "historical_analysis_summary.json")
        or latest.get("historical_analysis")
    )

    paper_root = data_dir / "paper_automation"
    learning_review = _safe_read(paper_root / "learning_tracks_review.json")
    learning_summary = _safe_read(paper_root / "learning_tracks_summary.json")
    exit_shadow = _safe_read(paper_root / "learning_tracks_exit_shadow.json")
    exit_timing = _slim_exit_timing(
        _safe_read(paper_root / "learning_tracks_exit_timing.json"),
        label="Live exit-timing cohorts",
    )
    exit_timing_near_miss = _slim_exit_timing(
        _safe_read(data_dir / "exit_timing_near_miss_review.json"),
        label="Archive near-miss exit-timing",
    )
    exclusion_universe = _slim_exclusion_universe(
        _safe_read(data_dir / "exclusion_universe_review.json")
    )
    exclusion_ladder_replay = _slim_exclusion_ladder_replay(
        _safe_read(paper_root / "exclusion_ladder_replay_review.json")
    )
    trajectory_review = _safe_read(data_dir / "trajectory_evidence_review.json")
    trajectory_evidence = slim_trajectory_evidence_for_review(
        trajectory_review if isinstance(trajectory_review, dict) else None
    )
    loser_snapshot_cards = _slim_loser_snapshot_cards(
        _safe_read(data_dir / "loser_snapshot_cards.json")
    )
    hypothesis_integrity = _slim_hypothesis_integrity(
        _safe_read(paper_root / "learning_tracks_hypothesis_integrity.json")
    )
    hypothesis_outcomes = _slim_hypothesis_outcomes(
        _safe_read(paper_root / "learning_tracks_hypothesis_outcomes.json")
    )
    churn_health = _safe_read(paper_root / "learning_tracks_churn_health.json")
    knob_calibration = _safe_read(paper_root / KNOB_CALIBRATION_PRIORS_FILENAME)
    experiment_assessment = slim_experiment_assessment_for_review(
        _safe_read(data_dir / "experiment_assessment.json")
    )

    model_weights = _safe_read(output_dir / "model_weights.json") or _safe_read(
        data_dir / "model_weights.json"
    )

    from value_investor.ingest_gap_closure import list_gap_closure_runs_pending_review

    ingest_trials_pending_review = list_gap_closure_runs_pending_review(
        trigger="analysis_review",
        path=data_dir / "ingest_gap_closure_runs.json",
    )
    if not ingest_trials_pending_review:
        ingest_trials_pending_review = list_gap_closure_runs_pending_review(
            trigger="analysis_review",
            path=data_dir / "ingest_trials.json",
        )

    return {
        "run_at": effective_run_at.isoformat(),
        "history_run_count": _history_run_count(data_dir, output_dir),
        "screen_meta": latest.get("meta"),
        "backtest": backtest,
        "simulation": simulation,
        "historical_analysis": historical,
        "learning_tracks_review": learning_review,
        "learning_tracks_summary": learning_summary,
        "exit_shadow": exit_shadow,
        "exit_timing_cohorts": exit_timing,
        "exit_timing_near_miss": exit_timing_near_miss,
        "exclusion_universe": exclusion_universe,
        "exclusion_ladder_replay": exclusion_ladder_replay,
        "trajectory_evidence": trajectory_evidence,
        "loser_snapshot_cards": loser_snapshot_cards,
        "hypothesis_integrity": hypothesis_integrity,
        "hypothesis_outcomes": hypothesis_outcomes,
        "churn_health": churn_health,
        "knob_calibration_priors": knob_calibration,
        "experiment_assessment": experiment_assessment,
        "model_weights": {
            "sample_count": (model_weights or {}).get("sample_count"),
            "updated_at": (model_weights or {}).get("updated_at"),
            "note": (model_weights or {}).get("note"),
            "top_weights": sorted(
                ((model_weights or {}).get("weights") or {}).items(),
                key=lambda item: item[1],
                reverse=True,
            )[:8],
        }
        if model_weights
        else None,
        "ingest_trials_pending_review": ingest_trials_pending_review,
        "guardrails": {
            "no_live_paper_changes": True,
            "no_base_signal_mutation": True,
            "engineering_promotion_manual": True,
        },
    }


def has_enough_analysis_inputs(payload: dict[str, Any]) -> tuple[bool, str]:
    history_runs = int(payload.get("history_run_count") or 0)
    backtest_runs = int(((payload.get("backtest") or {}).get("run_count")) or 0)
    learning = payload.get("learning_tracks_review")
    historical_runs = int(((payload.get("historical_analysis") or {}).get("run_count")) or 0)

    if learning or backtest_runs >= 2 or historical_runs >= 2 or history_runs >= 2:
        return True, "ok"
    if history_runs == 1 or backtest_runs == 1:
        return (
            False,
            "Need at least 2 archived weekly runs before modelling/analysis synthesis "
            "(history persistence seeds after the next Sunday screen).",
        )
    if learning:
        return True, "ok"
    return (
        False,
        "Need archived run history and/or learning_tracks_review.json for analysis synthesis.",
    )


def _experiment_type_for_area(area: str) -> str:
    normalized = area.strip().lower()
    if normalized in _ENGINEERING_AREAS:
        return "engineering_candidate"
    if normalized == "paper_knobs":
        return "decision_review_probe"
    if normalized == "paper_churn":
        return "churn_probe"
    if normalized == "offline_sim":
        return "offline_sim"
    return "observe"


def _promote_target_for_area(area: str) -> str:
    normalized = area.strip().lower()
    if normalized in _ENGINEERING_AREAS:
        return "engineering_queue"
    if normalized == "paper_knobs":
        return "decision_review_manual"
    if normalized == "paper_churn":
        return "manual"
    return "manual"


def compile_analysis_tasks(
    review: AnalysisReview,
    *,
    run_stamp: str | None = None,
    tasks_path: Path = COMMITTED_TASKS_PATH,
) -> dict[str, Any]:
    """Parse proposed experiments into analysis_tasks.json (status=proposed)."""
    stamp = run_stamp or datetime.now(UTC).strftime("%Y%m%d")
    existing = _safe_read(tasks_path) or {}
    kept = [
        row
        for row in (existing.get("tasks") or [])
        if str(row.get("status") or "") not in {"promoted", "cancelled"}
    ]
    new_tasks: list[AnalysisTask] = []
    seq = 1
    for line in review.proposed_experiments.splitlines():
        match = _EXPERIMENT_LINE.match(line.strip())
        if not match:
            continue
        area = match.group("area").strip().lower()
        title = match.group("title").strip()
        task_id = f"ana-{stamp}-{seq:02d}"
        new_tasks.append(
            AnalysisTask(
                id=task_id,
                area=area,
                title=title[:200],
                summary=title,
                experiment_type=_experiment_type_for_area(area),
                priority="high" if area in _ENGINEERING_AREAS else "medium",
                status="proposed",
                promote_to=_promote_target_for_area(area),
                evidence={"plan_index": int(match.group("index"))},
            )
        )
        seq += 1

    payload = {
        "compiled_at": datetime.now(UTC).isoformat(),
        "run_stamp": stamp,
        "task_count": len(kept) + len(new_tasks),
        "tasks": kept + [task.to_dict() for task in new_tasks],
    }
    tasks_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(tasks_path, payload, compact=True)
    return payload


def load_analysis_tasks(path: Path = COMMITTED_TASKS_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"tasks": []}
    data = _safe_read(path)
    return data if isinstance(data, dict) else {"tasks": []}


def promote_analysis_tasks(
    task_ids: list[str],
    *,
    analysis_tasks_path: Path = COMMITTED_TASKS_PATH,
    engineering_tasks_path: Path | None = None,
) -> dict[str, Any]:
    """
    Promote approved analysis tasks into engineering_tasks.json.

    Only ``engineering_candidate`` tasks in engineering areas are appended.
    Marks analysis tasks as ``promoted``; does not dispatch agents.
    """
    from value_investor.engineering_tasks import (
        BLOCKED_PATHS,
        _allowed_paths_for_area,
        load_engineering_tasks,
    )
    from value_investor.engineering_tasks import (
        COMMITTED_TASKS_PATH as ENG_COMMITTED,
    )

    eng_path = engineering_tasks_path or ENG_COMMITTED
    analysis_payload = load_analysis_tasks(analysis_tasks_path)
    eng_payload = load_engineering_tasks(eng_path)
    eng_rows = list(eng_payload.get("tasks") or [])

    promoted: list[str] = []
    skipped: list[dict[str, str]] = []
    wanted = {tid.strip() for tid in task_ids if tid.strip()}

    updated_tasks: list[dict[str, Any]] = []
    for row in analysis_payload.get("tasks") or []:
        task = AnalysisTask.from_dict(row)
        if task.id not in wanted:
            updated_tasks.append(task.to_dict())
            continue
        if task.status == "promoted":
            skipped.append({"id": task.id, "reason": "already promoted"})
            updated_tasks.append(task.to_dict())
            continue
        if task.promote_to != "engineering_queue" or task.area not in _ENGINEERING_AREAS:
            skipped.append(
                {
                    "id": task.id,
                    "reason": f"not promotable to engineering (promote_to={task.promote_to})",
                }
            )
            updated_tasks.append(task.to_dict())
            continue
        eng_id = task.id.replace("ana-", "eng-", 1)
        eng_rows.append(
            {
                "id": eng_id,
                "area": task.area,
                "title": task.title,
                "summary": task.summary,
                "priority": "medium",
                "priority_score": 70.0,
                "source": "analysis_review",
                "evidence": {"analysis_task_id": task.id, **task.evidence},
                "acceptance_criteria": [
                    "Change is covered by unit tests where behaviour shifts",
                    "No edits under blocked paper/sim automation paths",
                ],
                "allowed_paths": _allowed_paths_for_area(task.area),
                "blocked_paths": list(BLOCKED_PATHS),
                "status": "open",
            }
        )
        task.status = "promoted"
        promoted.append(task.id)
        updated_tasks.append(task.to_dict())

    analysis_payload["tasks"] = updated_tasks
    analysis_payload["task_count"] = len(updated_tasks)
    eng_payload["tasks"] = eng_rows
    eng_payload["task_count"] = len(eng_rows)
    write_json(analysis_tasks_path, analysis_payload, compact=True)
    write_json(eng_path, eng_payload, compact=True)
    return {"promoted": promoted, "skipped": skipped, "engineering_tasks_path": str(eng_path)}


def _build_analysis_prompt(payload_path: Path) -> str:
    return f"""You are the modelling and learning analyst for an automated FTSE value portfolio.

Read the structured JSON at: {payload_path}

The **purpose of this review** is to turn evidence into **focus areas that refine
assessment models and portfolio filters** — not to archive metrics for their own sake.
Primary diagnostics for assessment models: trajectory_evidence + loser_snapshot_cards.
Primary diagnostics for loser filters / churn: exclusion_universe, exclusion_ladder_replay,
exit_timing_cohorts, exit_shadow, hypothesis_integrity, hypothesis_outcomes. Paper-track P&L and backtests are context.

Write SIX plain-text sections with headings exactly as shown:

EXECUTIVE SUMMARY
3–5 sentences on whether the quant stack and paper tracks are improving, and the single
biggest modelling/analysis gap this week. Prefer naming a concrete focus from
trajectory_evidence.model_focus_candidates, loser_snapshot_cards.top_failed_families,
or exclusion readiness when present.

PERFORMANCE DIAGNOSIS
Bullets on primary vs control vs market excess after costs, cost drag, and whether marks
are thick enough to trust. Do NOT recommend auto-applying decision-review knobs.

SIGNAL & BACKTEST FINDINGS
What archived signal backtest / historical analysis / offline sim tracks show — cite
horizons, excess returns, and run_count. If run_count < 2, say history is still seeding.
When trajectory_evidence is present, cite labeled_event_count, prediction_hit_rate_by_horizon,
weeks_to_realization, and each model_focus_candidate.why. Treat weak transition keys
as assessment-model hypotheses, not live-screen mutation (N3).
When loser_snapshot_cards is present, cite card_count, cohort_counts, and
top_failed_families — these are Tier-1 forensics for scoring/filter hypotheses.
When exclusion_universe is present, cite recommended_step and readiness.ready_for_priors
plus cumulative_exclusion_alpha on the recommended rung.

PAPER TRACK COMPARISON
Compare ai_judgment, rules, and momentum_grace using learning_tracks_review,
knob_calibration_priors (recommended_prior per track, confidence, changed_vs_current),
and exit_shadow when present. Cite exit_timing_cohorts.readiness (hold/swap closed counts)
and exclusion_ladder_replay.readiness.ready_for_shadow_spawn when present.
When hypothesis_integrity is present, cite per-track loser_share, within_tolerance,
balancing_hint, and any selection_feedback_flags (intact losers are expected in a value book).
Note unrealized vs realized marks only if present in JSON.

PROPOSED EXPERIMENTS
Numbered top 5 experiments for the next sprint. Each line MUST use this format:
``N. [area] Experiment title — expected learning value``
Areas: scoring, ingest, offline_sim, paper_knobs, paper_churn, attribution, monitoring, analysis.
Use scoring/ingest only when a code change is the right next step; prefer offline_sim,
paper_knobs, or paper_churn for knob/counterfactual ideas (human gate required).

Action contracts (include a line when the trigger fires — do not invent metrics):
1. If trajectory_evidence.model_focus_candidates is non-empty → ≥1 [scoring] or [offline_sim]
   citing a candidate key (conviction/timing/family weight/overlay — never assign_signal
   threshold search / N3).
2. If loser_snapshot_cards.top_failed_families is non-empty → ≥1 [scoring] or [offline_sim]
   citing a failed family / opinion-flip pattern from sample_cards.
3. If exclusion_universe.readiness.ready_for_priors is true OR recommended_step shows
   positive cumulative_exclusion_alpha → ≥1 [offline_sim] or [paper_knobs] citing the
   recommended step_id (human gate; not auto-apply).
4. If exclusion_ladder_replay.readiness.ready_for_shadow_spawn is true → ≥1 [monitoring] or
   [paper_knobs] line: human should run ftse-exclusion-ladder-replay spawn-shadow
   (never auto-spawn; do not open an engineering PR for the spawn itself).
5. If exit_timing_cohorts.readiness.ready_for_probability_analysis is true OR
   exit_timing_near_miss.readiness.ready_for_probability_analysis is true → ≥1
   [paper_churn] or [offline_sim] hold-vs-swap experiment citing closed counts.
6. If ingest_trials_pending_review is non-empty → ≥1 [ingest] line with trial id(s) and
   PROMOTE / DEFER / DISMISS.
7. If experiment_assessment.recommendations is non-empty → ≥1 [monitoring] line listing
   experiment_id(s) with status recommend and human_ack_required (never auto-apply;
   cite gate_marks / gate_excess_after_costs when present).
8. If hypothesis_integrity shows within_tolerance false OR broken_loser_count > 0 OR
   selection_feedback_flags non-empty → ≥1 [paper_churn] or [scoring] citing balancing_hint
   / failed family (do not propose crude mark stops; prefer thesis-broken rotation).
9. If hypothesis_outcomes.readiness.ready_for_thesis_outcome_analysis is true → ≥1
   [paper_churn] or [offline_sim] citing intact vs broken recovery_rate or learning_hints
   (observe-only; no auto-apply thesis thresholds).

Cap at 5 lines — prioritise the strongest triggers; mention deferred triggers under DEFER.

DEFER
Bullets for ideas that must NOT be automated yet (evolution, live knob apply, base signal
changes, auto-spawn shadows), each with a one-line revisit trigger.

Rules:
- Do not invent metrics — only use the JSON.
- Never propose auto-merging paper-auto, decision-review --apply, or assign_signal changes.
- Distinguish forward paper evidence from archived backtest evidence.
- Be specific enough that a human can promote an experiment to the engineering queue.
"""


def run_analysis_review(
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    api_key: str,
    model: str = "composer-2.5",
    cwd: str | None = None,
    run_at: datetime | None = None,
    compile_tasks: bool = True,
) -> AnalysisReview:
    """Run a single agent pass over modelling/analysis artifacts."""
    payload = build_analysis_payload(
        data_dir=data_dir,
        output_dir=output_dir,
        run_at=run_at,
    )
    ok, note = has_enough_analysis_inputs(payload)
    if not ok:
        raise RuntimeError(note)

    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    payload_path = output_dir / "analysis_review_payload.json"
    write_json(payload_path, payload, compact=True)

    try:
        agent_result = Agent.prompt(
            _build_analysis_prompt(payload_path.resolve()),
            AgentOptions(
                api_key=api_key,
                model=model,
                local=LocalAgentOptions(cwd=cwd or os.getcwd()),
            ),
        )
    except CursorAgentError as err:
        raise RuntimeError(f"Analysis review agent startup failed: {err.message}") from err

    if agent_result.status == "error":
        raise RuntimeError(f"Analysis review agent run failed: {agent_result.id}")

    text = (agent_result.result or "").strip()
    review = parse_analysis_review(text)
    COMMITTED_REVIEW_MD_PATH.write_text(review.full_text + "\n", encoding="utf-8")
    write_json(
        COMMITTED_REVIEW_PATH,
        {
            "reviewed_at": datetime.now(UTC).isoformat(),
            "run_at": payload.get("run_at"),
            "history_run_count": payload.get("history_run_count"),
            "sections": {
                "executive_summary": review.executive_summary,
                "performance_diagnosis": review.performance_diagnosis,
                "signal_backtest_findings": review.signal_backtest_findings,
                "paper_track_comparison": review.paper_track_comparison,
                "proposed_experiments": review.proposed_experiments,
                "defer": review.defer,
            },
        },
        compact=True,
    )
    if compile_tasks and review.proposed_experiments.strip():
        compile_analysis_tasks(review, tasks_path=COMMITTED_TASKS_PATH)
    return review
