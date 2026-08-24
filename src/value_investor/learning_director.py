"""Weekly Learning Director — read-only orchestration synthesis."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions

from value_investor.analysis_review import (
    _EXPERIMENT_LINE,
    AnalysisTask,
    _experiment_type_for_area,
    _history_run_count,
    _promote_target_for_area,
)
from value_investor.deferred_ideas import DEFAULT_STORE as DEFAULT_DEFER_STORE
from value_investor.deferred_ideas import add_fragment, list_open_fragments, write_markdown
from value_investor.learning_director_regime import (
    VISION_PATH,
    build_experiment_inventory,
    build_regime_summary,
    load_learning_director_vision,
)
from value_investor.review_policy import (
    DEFAULT_REVIEW_POLICY_PATH,
    learning_director_enabled,
    load_review_policy,
)
from value_investor.storage import read_json, write_json
from value_investor.trajectory_evidence import slim_trajectory_evidence_for_review

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path("docs/data")
DEFAULT_OUTPUT_DIR = Path("output")
PAPER_ROOT = DEFAULT_DATA_DIR / "paper_automation"
COMMITTED_REVIEW_PATH = DEFAULT_DATA_DIR / "learning_director_review.json"
COMMITTED_REVIEW_MD_PATH = DEFAULT_DATA_DIR / "learning_director_review.md"
COMMITTED_TASKS_PATH = DEFAULT_DATA_DIR / "learning_director_tasks.json"
MAX_HORIZON_FRAGMENTS = 2

_FRAGMENT_LINE = re.compile(
    r"^\s*-\s*(?:\[(?P<tags>[^\]]+)\]\s*)?(?P<text>.+)$",
)

_LEARNING_DIRECTOR_AREAS = frozenset(
    {
        "analysis",
        "monitoring",
        "offline_sim",
        "paper_churn",
        "paper_knobs",
        "universe",
        "research",
        "ops",
    }
)


@dataclass
class LearningDirectorReview:
    regime_assumption_check: str
    convergence: str
    complexity_inventory: str
    vision_roadmap_review: str
    proposed_actions: str
    horizon_fragments: str
    defer: str

    @property
    def full_text(self) -> str:
        parts = [
            ("REGIME & ASSUMPTION CHECK", self.regime_assumption_check),
            ("CONVERGENCE", self.convergence),
            ("COMPLEXITY & EXPERIMENT INVENTORY", self.complexity_inventory),
            ("VISION ROADMAP REVIEW", self.vision_roadmap_review),
            ("PROPOSED ACTIONS", self.proposed_actions),
            ("HORIZON FRAGMENTS", self.horizon_fragments),
            ("DEFER", self.defer),
        ]
        return "\n\n".join(f"{heading}\n{body.strip()}" for heading, body in parts if body.strip())


def _normalize_heading(line: str) -> str:
    text = line.strip().lstrip("#").strip()
    if text.startswith("**") and text.endswith("**") and len(text) > 4:
        text = text[2:-2].strip()
    return text.rstrip(":").strip().upper()


def parse_learning_director_review(text: str) -> LearningDirectorReview:
    section_keys = {
        "REGIME & ASSUMPTION CHECK": "regime_assumption_check",
        "REGIME AND ASSUMPTION CHECK": "regime_assumption_check",
        "CONVERGENCE": "convergence",
        "COMPLEXITY & EXPERIMENT INVENTORY": "complexity_inventory",
        "COMPLEXITY AND EXPERIMENT INVENTORY": "complexity_inventory",
        "VISION ROADMAP REVIEW": "vision_roadmap_review",
        "PROPOSED ACTIONS": "proposed_actions",
        "HORIZON FRAGMENTS": "horizon_fragments",
        "DEFER": "defer",
    }
    buckets: dict[str, list[str]] = {value: [] for value in section_keys.values()}
    current: str | None = None
    for raw in text.splitlines():
        heading = _normalize_heading(raw)
        if heading in section_keys:
            current = section_keys[heading]
            continue
        if current is not None:
            buckets[current].append(raw)
    return LearningDirectorReview(
        regime_assumption_check="\n".join(buckets["regime_assumption_check"]).strip(),
        convergence="\n".join(buckets["convergence"]).strip(),
        complexity_inventory="\n".join(buckets["complexity_inventory"]).strip(),
        vision_roadmap_review="\n".join(buckets["vision_roadmap_review"]).strip(),
        proposed_actions="\n".join(buckets["proposed_actions"]).strip(),
        horizon_fragments="\n".join(buckets["horizon_fragments"]).strip(),
        defer="\n".join(buckets["defer"]).strip(),
    )


def parse_horizon_fragment_lines(text: str) -> list[dict[str, Any]]:
    """Parse HORIZON FRAGMENTS bullets into {text, tags} rows."""
    rows: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.upper() in {"NONE", "(NONE)", "N/A"}:
            continue
        match = _FRAGMENT_LINE.match(line)
        if not match:
            continue
        body = str(match.group("text") or "").strip()
        if not body or body.upper() in {"NONE", "N/A"}:
            continue
        tags_raw = str(match.group("tags") or "").strip()
        tags = [tag.strip() for tag in tags_raw.split(",") if tag.strip()] if tags_raw else []
        rows.append({"text": body, "tags": tags})
    return rows[:MAX_HORIZON_FRAGMENTS]


def compile_horizon_fragments(
    review: LearningDirectorReview,
    *,
    run_stamp: str | None = None,
    store_path: Path = DEFAULT_DEFER_STORE,
) -> dict[str, Any]:
    """Append HORIZON FRAGMENTS to deferred-ideas scratch pad (not task queue)."""
    stamp = run_stamp or datetime.now(UTC).strftime("%Y%m%d")
    source = f"learning_director:{stamp}"
    created: list[dict[str, Any]] = []
    skipped: list[str] = []
    for row in parse_horizon_fragment_lines(review.horizon_fragments):
        fragment, was_created = add_fragment(
            row["text"],
            tags=row.get("tags") or [],
            source=source,
            store_path=store_path,
        )
        if was_created:
            created.append(fragment)
        else:
            skipped.append(str(fragment.get("id") or row["text"][:80]))
    return {
        "compiled_at": datetime.now(UTC).isoformat(),
        "run_stamp": stamp,
        "created_count": len(created),
        "skipped_duplicates": skipped,
        "fragments": created,
    }


def _safe_read(path: Path) -> dict[str, Any] | None:
    try:
        raw = read_json(path)
    except FileNotFoundError:
        return None
    return raw if isinstance(raw, dict) else None


def build_learning_director_payload(
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    vision_path: Path = VISION_PATH,
    run_at: datetime | None = None,
) -> dict[str, Any]:
    """Assemble deterministic inputs for the Learning Director agent."""
    effective_run_at = run_at or datetime.now(UTC)
    data_dir = Path(data_dir)
    output_dir = Path(output_dir)
    paper_root = data_dir / "paper_automation"
    history_runs = _history_run_count(data_dir, output_dir)

    vision = load_learning_director_vision(vision_path)
    regime_summary = build_regime_summary(
        data_dir,
        paper_root=paper_root,
        history_run_count=history_runs,
    )
    experiment_inventory = build_experiment_inventory(data_dir, paper_root=paper_root)

    return {
        "run_at": effective_run_at.isoformat(),
        "history_run_count": history_runs,
        "vision": vision,
        "regime_summary": regime_summary,
        "experiment_inventory": experiment_inventory,
        "review_policy": load_review_policy(paper_root / "review_policy.json"),
        "analysis_review": _safe_read(data_dir / "analysis_review.json"),
        "paper_learning_review": _safe_read(data_dir / "paper_learning_review.json"),
        "prior_learning_director_review": _safe_read(COMMITTED_REVIEW_PATH),
        "exclusion_universe": _safe_read(data_dir / "exclusion_universe_review.json"),
        "exclusion_ladder_replay": _safe_read(paper_root / "exclusion_ladder_replay_review.json"),
        "loser_snapshot_cards": _safe_read(data_dir / "loser_snapshot_cards.json"),
        "trajectory_evidence": slim_trajectory_evidence_for_review(
            _safe_read(data_dir / "trajectory_evidence_review.json")
        ),
        "learning_tracks_review": _safe_read(paper_root / "learning_tracks_review.json"),
        "learning_tracks_summary": _safe_read(paper_root / "learning_tracks_summary.json"),
        "open_fragments": list_open_fragments(store_path=DEFAULT_DEFER_STORE),
        "guardrails": {
            **(vision.get("guardrails") or {}),
            "vision_activation_proposal_only": True,
            "no_engineering_auto_promote": True,
        },
    }


def has_enough_learning_director_inputs(payload: dict[str, Any]) -> tuple[bool, str]:
    if not payload.get("vision"):
        return False, "learning_director_vision.json missing"
    if payload.get("analysis_review") or payload.get("learning_tracks_review"):
        return True, "ok"
    if payload.get("exclusion_universe"):
        return True, "ok (exclusion_universe only; thin weekly context)"
    return False, "Need analysis_review.json and/or learning_tracks_review.json"


def compile_learning_director_tasks(
    review: LearningDirectorReview,
    *,
    run_stamp: str | None = None,
    tasks_path: Path = COMMITTED_TASKS_PATH,
) -> dict[str, Any]:
    """Parse proposed actions into learning_director_tasks.json (status=proposed)."""
    stamp = run_stamp or datetime.now(UTC).strftime("%Y%m%d")
    existing = read_json(tasks_path) if tasks_path.exists() else {}
    if not isinstance(existing, dict):
        existing = {}
    kept = [
        row
        for row in (existing.get("tasks") or [])
        if str(row.get("status") or "") not in {"promoted", "cancelled", "done"}
    ]
    new_tasks: list[AnalysisTask] = []
    seq = 1
    for line in review.proposed_actions.splitlines():
        match = _EXPERIMENT_LINE.match(line.strip())
        if not match:
            continue
        area = match.group("area").strip().lower()
        if area not in _LEARNING_DIRECTOR_AREAS:
            logger.info("Skipping non-director experiment area: %s", area)
            continue
        title = match.group("title").strip()
        task_id = f"ldr-{stamp}-{seq:02d}"
        new_tasks.append(
            AnalysisTask(
                id=task_id,
                area=area,
                title=title[:200],
                summary=title,
                experiment_type=_experiment_type_for_area(area),
                priority="medium",
                status="proposed",
                source="learning_director",
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


def _build_learning_director_prompt(payload_path: Path) -> str:
    return f"""You are the Learning Director for an automated FTSE value portfolio.

Read the structured JSON at: {payload_path}

You coordinate winner-pick vs loser-filter evidence across weekly reviews. This is
observe-only — do not propose auto-applying knobs, mutating screens, spawning tracks,
or opening engineering PRs. Vision phase activation is **proposal-only** (human ack).

Trajectory evidence exists to **highlight assessment-model weak spots** (scoring,
conviction, timing). Scoring experiments belong in analysis-review (promotable to
engineering). Your job is to check that analysis_review proposed those experiments
when trajectory_evidence.model_focus_candidates is non-empty — if it missed them,
propose an [analysis] follow-up, do not invent a parallel scoring loop.

Write SEVEN plain-text sections with headings exactly as shown:

REGIME & ASSUMPTION CHECK
3–4 sentences: does exclusion alpha, cohort quality, and primary track evidence still
hold as history extends? Cite regime_summary windows and flags. Note decay or reversal.
Prioritise **trajectory change** (opinion-flip signals) over static historical fit.
Cite trajectory_evidence prediction_hit_rate_by_horizon and weeks_to_realization when present.

CONVERGENCE
Reconcile top-pick (ai_judgment, conviction, sleeves) vs bottom-filter (exclusion ladder,
universe archive). State whether strands are converging toward a bettable filtered cohort.
Frame success as timely opinion updates (prediction_philosophy), not perfect backstory.
If model_focus_candidates exist, say which assessment-model gap they imply.

COMPLEXITY & EXPERIMENT INVENTORY
Open experiment count vs complexity_budget. List shadow tracks. Recommend merge/retire/defer
if over budget (max_parallel_open_experiments, max_frozen_shadow_tracks).
Note whether analysis_review already has a scoring experiment covering the top
trajectory focus candidate.

VISION ROADMAP REVIEW
Read vision.phases. For each planned/deferred phase recommend ACTIVATE, HOLD, or RETIRE.
Cite revisit_when triggers and current payload evidence. Never self-authorise builds.

PROPOSED ACTIONS
Numbered top 3–5 actions. Each line MUST use:
``N. [area] Action title — expected learning value``
Areas allowed: analysis, monitoring, offline_sim, paper_churn, paper_knobs, universe,
research, ops.
Do **not** use [scoring] here — that area is analysis-review + human promote.
If trajectory focus candidates were not turned into analysis_tasks, add
``N. [analysis] Ensure scoring experiment for <candidate.key> — …``

HORIZON FRAGMENTS
Up to {MAX_HORIZON_FRAGMENTS} speculative observations **not** tied to existing tasks or
vision phases — blue-sky pattern ideas, assumption challenges, or "what if we optimised
X instead?" thoughts for monthly horizon scan to cluster later. Format each line:
``- [comma,tags] One or two sentences``
Do **not** duplicate open_fragments already in the payload. Write ``NONE`` if nothing
worth capturing. These are **not** experiments — they feed ``ftse-defer fragment`` only.

DEFER
Ideas that must stay manual until revisit triggers or more history (cite vision phase ids).

Rules:
- Tactical sections (regime through proposed actions): cite JSON paths; do not invent metrics.
- HORIZON FRAGMENTS may speculate beyond current artifacts — label clearly as hypothesis.
- Be specific enough for a human operator to act next week.
"""


def run_learning_director(
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    vision_path: Path = VISION_PATH,
    api_key: str,
    model: str = "composer-2.5",
    cwd: str | None = None,
    run_at: datetime | None = None,
    compile_tasks: bool = True,
    compile_fragments: bool = True,
    policy_path: Path = DEFAULT_REVIEW_POLICY_PATH,
    defer_store_path: Path = DEFAULT_DEFER_STORE,
) -> LearningDirectorReview:
    """Run a single Learning Director agent pass."""
    if not learning_director_enabled(policy_path):
        raise RuntimeError("learning_director is disabled in review_policy.json")

    payload = build_learning_director_payload(
        data_dir=data_dir,
        output_dir=output_dir,
        vision_path=vision_path,
        run_at=run_at,
    )
    ok, note = has_enough_learning_director_inputs(payload)
    if not ok:
        raise RuntimeError(note)

    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    payload_path = output_dir / "learning_director_payload.json"
    write_json(payload_path, payload, compact=True)

    try:
        agent_result = Agent.prompt(
            _build_learning_director_prompt(payload_path.resolve()),
            AgentOptions(
                api_key=api_key,
                model=model,
                local=LocalAgentOptions(cwd=cwd or os.getcwd()),
            ),
        )
    except CursorAgentError as err:
        raise RuntimeError(f"Learning director agent startup failed: {err.message}") from err

    if agent_result.status == "error":
        raise RuntimeError(f"Learning director agent run failed: {agent_result.id}")

    text = (agent_result.result or "").strip()
    review = parse_learning_director_review(text)
    COMMITTED_REVIEW_MD_PATH.write_text(review.full_text + "\n", encoding="utf-8")
    fragment_result: dict[str, Any] | None = None
    if compile_fragments and review.horizon_fragments.strip():
        fragment_result = compile_horizon_fragments(
            review,
            store_path=defer_store_path,
        )
        if fragment_result.get("created_count"):
            write_markdown(store_path=defer_store_path)

    review_payload: dict[str, Any] = {
        "reviewed_at": datetime.now(UTC).isoformat(),
        "run_at": payload.get("run_at"),
        "enabled": True,
        "history_run_count": payload.get("history_run_count"),
        "sections": {
            "regime_assumption_check": review.regime_assumption_check,
            "convergence": review.convergence,
            "complexity_inventory": review.complexity_inventory,
            "vision_roadmap_review": review.vision_roadmap_review,
            "proposed_actions": review.proposed_actions,
            "horizon_fragments": review.horizon_fragments,
            "defer": review.defer,
        },
    }
    if fragment_result is not None:
        review_payload["fragments_compiled"] = fragment_result

    write_json(
        COMMITTED_REVIEW_PATH,
        review_payload,
        compact=True,
    )
    if compile_tasks and review.proposed_actions.strip():
        compile_learning_director_tasks(review, tasks_path=COMMITTED_TASKS_PATH)
    return review
