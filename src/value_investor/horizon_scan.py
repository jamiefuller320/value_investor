"""Monthly strategic foresight synthesis (read-only, no live trading changes)."""

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
    _ENGINEERING_AREAS,
    _EXPERIMENT_LINE,
    AnalysisTask,
    _experiment_type_for_area,
    _promote_target_for_area,
    _safe_read,
    build_analysis_payload,
    has_enough_analysis_inputs,
)
from value_investor.deferred_ideas import (
    DEFAULT_STORE,
    add_idea,
    list_open_fragments,
    load_store,
    set_fragment_status,
)
from value_investor.storage import write_json

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path("docs/data")
DEFAULT_OUTPUT_DIR = Path("output")
PROJECT_OBJECTIVE_PATH = Path("docs/PROJECT_OBJECTIVE.md")
LIBRARY_POLICY_PATH = DEFAULT_DATA_DIR / "library" / "policy.json"
COMMITTED_REVIEW_PATH = DEFAULT_DATA_DIR / "horizon_scan.json"
COMMITTED_REVIEW_MD_PATH = DEFAULT_DATA_DIR / "horizon_scan.md"
COMMITTED_TASKS_PATH = DEFAULT_DATA_DIR / "horizon_tasks.json"

_PARK_LINE = re.compile(r"^[-*]\s+(?:\*\*(?P<title>[^*]+)\*\*\s*)?(?:[—–-]\s*)?(?P<body>.+)$")
_FRAGMENT_DROP = re.compile(r"^[-*]\s*DROP\s+(frag-[\w-]+)\s*$", re.IGNORECASE)
_FRAGMENT_PROMOTE = re.compile(
    r"^[-*]\s*PROMOTE\s+(frag-[\w-]+)\s*(?:→|->)\s*(.+)$",
    re.IGNORECASE,
)


@dataclass
class HorizonScanReview:
    stage_readiness: str
    evidence_strands: str
    automation_risks: str
    counterfactual_gaps: str
    fragment_clustering: str
    ingest_trials_review: str
    park: str
    accelerate: str

    @property
    def full_text(self) -> str:
        parts = [
            ("STAGE READINESS", self.stage_readiness),
            ("EVIDENCE STRANDS", self.evidence_strands),
            ("AUTOMATION RISKS", self.automation_risks),
            ("COUNTERFACTUAL GAPS", self.counterfactual_gaps),
            ("FRAGMENT CLUSTERING", self.fragment_clustering),
            ("INGEST TRIALS REVIEW", self.ingest_trials_review),
            ("PARK", self.park),
            ("ACCELERATE", self.accelerate),
        ]
        return "\n\n".join(f"{heading}\n{body.strip()}" for heading, body in parts if body.strip())


def _normalize_heading(line: str) -> str:
    text = line.strip().lstrip("#").strip()
    if text.startswith("**") and text.endswith("**") and len(text) > 4:
        text = text[2:-2].strip()
    return text.rstrip(":").strip().upper()


def parse_horizon_scan(text: str) -> HorizonScanReview:
    section_keys = {
        "STAGE READINESS": "stage_readiness",
        "EVIDENCE STRANDS": "evidence_strands",
        "AUTOMATION RISKS": "automation_risks",
        "COUNTERFACTUAL GAPS": "counterfactual_gaps",
        "FRAGMENT CLUSTERING": "fragment_clustering",
        "INGEST TRIALS REVIEW": "ingest_trials_review",
        "PARK": "park",
        "ACCELERATE": "accelerate",
    }
    sections: dict[str, str] = {key: "" for key in section_keys.values()}
    current = "stage_readiness"
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
        sections["stage_readiness"] = text.strip()

    return HorizonScanReview(**sections)


def _project_objective_excerpt(max_lines: int = 45) -> str:
    if not PROJECT_OBJECTIVE_PATH.exists():
        return ""
    lines = PROJECT_OBJECTIVE_PATH.read_text(encoding="utf-8").splitlines()
    start = next((i for i, line in enumerate(lines) if "North-star stages" in line), 0)
    chunk = lines[start : start + max_lines]
    return "\n".join(chunk).strip()


def _slim_open_deferred(store: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idea in store.get("ideas") or []:
        if str(idea.get("status") or "open") != "open":
            continue
        rows.append(
            {
                "id": idea.get("id"),
                "title": idea.get("title"),
                "summary": idea.get("summary"),
                "revisit_when": idea.get("revisit_when"),
                "tags": idea.get("tags"),
                "section": idea.get("section"),
            }
        )
    return rows


def _slim_open_engineering(path: Path) -> list[dict[str, Any]]:
    data = _safe_read(path)
    if not isinstance(data, dict):
        return []
    rows: list[dict[str, Any]] = []
    for row in data.get("tasks") or []:
        if str(row.get("status") or "open") in {"merged", "cancelled", "done"}:
            continue
        rows.append(
            {
                "id": row.get("id"),
                "area": row.get("area"),
                "title": row.get("title"),
                "status": row.get("status"),
                "priority_score": row.get("priority_score"),
            }
        )
    return rows[:30]


def _stage_signals(
    payload: dict[str, Any], deferred_count: int, fragment_count: int
) -> dict[str, Any]:
    history_runs = int(payload.get("history_run_count") or 0)
    learning = payload.get("learning_tracks_review")
    backtest_runs = int(((payload.get("backtest") or {}).get("run_count")) or 0)
    return {
        "history_run_count": history_runs,
        "backtest_run_count": backtest_runs,
        "has_learning_tracks_review": bool(learning),
        "open_deferred_ideas": deferred_count,
        "open_fragments": fragment_count,
        "stage_0_core": history_runs >= 2 and bool(learning),
        "richness_before_breadth": True,
    }


def build_horizon_payload(
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    deferred_path: Path = DEFAULT_STORE,
    run_at: datetime | None = None,
) -> dict[str, Any]:
    """Assemble strategic inputs for the monthly horizon scan agent."""
    effective_run_at = run_at or datetime.now(UTC)
    metrics = build_analysis_payload(
        data_dir=data_dir, output_dir=output_dir, run_at=effective_run_at
    )
    defer_store = load_store(deferred_path)
    open_deferred = _slim_open_deferred(defer_store)
    open_fragments = list_open_fragments(defer_store)

    analysis_review = _safe_read(data_dir / "analysis_review.json")
    analysis_sections = (analysis_review or {}).get("sections") or {}

    library_policy = _safe_read(LIBRARY_POLICY_PATH)

    from value_investor.ingest_gap_closure import list_gap_closure_runs_pending_review

    ingest_gap_closure_review = list_gap_closure_runs_pending_review(trigger="horizon_scan")

    payload = {
        **metrics,
        "scan_at": effective_run_at.isoformat(),
        "project_objective_excerpt": _project_objective_excerpt(),
        "open_deferred_ideas": open_deferred,
        "open_fragments": open_fragments,
        "ingest_gap_closure_pending_review": ingest_gap_closure_review,
        "ingest_trials_pending_review": ingest_gap_closure_review,
        "open_engineering_tasks": _slim_open_engineering(data_dir / "engineering_tasks.json"),
        "latest_analysis_review": {
            "reviewed_at": (analysis_review or {}).get("reviewed_at"),
            "executive_summary": analysis_sections.get("executive_summary"),
            "defer": analysis_sections.get("defer"),
        },
        "library_policy": {
            "focus_market": (library_policy or {}).get("focus_market"),
            "ladder": (library_policy or {}).get("ladder"),
        }
        if library_policy
        else None,
        "stage_signals": _stage_signals(metrics, len(open_deferred), len(open_fragments)),
        "guardrails": {
            **(metrics.get("guardrails") or {}),
            "horizon_scan_observe_only": True,
            "no_conversation_transcript_mining": True,
        },
    }
    return payload


def has_enough_horizon_inputs(payload: dict[str, Any]) -> tuple[bool, str]:
    ok, note = has_enough_analysis_inputs(payload)
    if ok:
        return True, note
    fragments = len(payload.get("open_fragments") or [])
    deferred = len(payload.get("open_deferred_ideas") or [])
    if fragments >= 1 or deferred >= 3:
        return True, "strategic inputs from open fragments/deferred ideas (metrics still thin)"
    return (
        False,
        "Need archived run history and/or learning tracks, or at least one fragment "
        "or several open deferred ideas for horizon scan.",
    )


def parse_park_proposals(text: str) -> list[dict[str, str]]:
    proposals: list[dict[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        match = _PARK_LINE.match(line)
        if not match:
            continue
        body = str(match.group("body") or "").strip()
        title = str(match.group("title") or "").strip()
        revisit = ""
        lower = body.lower()
        if "revisit when:" in lower:
            idx = lower.index("revisit when:")
            revisit = body[idx + len("revisit when:") :].strip()
            body = body[:idx].strip(" .—-")
        if not title:
            title = body[:120].strip() or "Parked horizon idea"
        summary = body or title
        if not title:
            continue
        proposals.append(
            {
                "title": title[:160],
                "summary": summary[:500],
                "revisit_when": revisit[:300],
            }
        )
    return proposals


def apply_park_proposals(
    proposals: list[dict[str, str]],
    *,
    store_path: Path = DEFAULT_STORE,
    category: str = "later",
    section: str = "learning",
    source: str = "horizon_scan",
) -> list[str]:
    added: list[str] = []
    for row in proposals:
        idea, created = add_idea(
            title=row["title"],
            summary=row["summary"],
            category=category,
            revisit_when=row.get("revisit_when") or "",
            section=section,
            source=source,
            store_path=store_path,
        )
        if created:
            added.append(str(idea.get("id")))
    return added


def parse_fragment_actions(text: str) -> tuple[list[str], list[dict[str, str]]]:
    drops: list[str] = []
    promotes: list[dict[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        drop_match = _FRAGMENT_DROP.match(line)
        if drop_match:
            drops.append(drop_match.group(1))
            continue
        promote_match = _FRAGMENT_PROMOTE.match(line)
        if promote_match:
            frag_id = promote_match.group(1)
            rest = promote_match.group(2).strip()
            proposals = parse_park_proposals(f"- {rest}")
            payload = (
                proposals[0]
                if proposals
                else {
                    "title": rest[:160],
                    "summary": rest[:500],
                    "revisit_when": "",
                }
            )
            promotes.append({"fragment_id": frag_id, **payload})
    return drops, promotes


def apply_fragment_actions(
    text: str,
    *,
    store_path: Path = DEFAULT_STORE,
    promote_to_defer: bool = True,
) -> dict[str, Any]:
    drops, promotes = parse_fragment_actions(text)
    dropped: list[str] = []
    promoted_fragments: list[str] = []
    deferred_ids: list[str] = []

    for frag_id in drops:
        try:
            set_fragment_status(frag_id, "drop", store_path=store_path)
            dropped.append(frag_id)
        except KeyError:
            logger.warning("Unknown fragment for DROP: %s", frag_id)

    for row in promotes:
        frag_id = str(row.get("fragment_id") or "")
        try:
            set_fragment_status(frag_id, "done", store_path=store_path)
            promoted_fragments.append(frag_id)
        except KeyError:
            logger.warning("Unknown fragment for PROMOTE: %s", frag_id)
            continue
        if promote_to_defer:
            idea, created = add_idea(
                title=str(row.get("title") or "Promoted fragment"),
                summary=str(row.get("summary") or ""),
                category="later",
                revisit_when=str(row.get("revisit_when") or ""),
                section="learning",
                source=f"horizon_scan:promote:{frag_id}",
                store_path=store_path,
            )
            if created:
                deferred_ids.append(str(idea.get("id")))

    return {
        "dropped_fragments": dropped,
        "promoted_fragments": promoted_fragments,
        "deferred_ids": deferred_ids,
    }


def compile_horizon_tasks(
    review: HorizonScanReview,
    *,
    run_stamp: str | None = None,
    tasks_path: Path = COMMITTED_TASKS_PATH,
) -> dict[str, Any]:
    """Parse ACCELERATE experiments into horizon_tasks.json (status=proposed)."""
    stamp = run_stamp or datetime.now(UTC).strftime("%Y%m%d")
    existing = _safe_read(tasks_path) or {}
    kept = [
        row
        for row in (existing.get("tasks") or [])
        if str(row.get("status") or "") not in {"promoted", "cancelled"}
    ]
    new_tasks: list[AnalysisTask] = []
    seq = 1
    for line in review.accelerate.splitlines():
        match = _EXPERIMENT_LINE.match(line.strip())
        if not match:
            continue
        area = match.group("area").strip().lower()
        title = match.group("title").strip()
        task_id = f"hor-{stamp}-{seq:02d}"
        new_tasks.append(
            AnalysisTask(
                id=task_id,
                area=area,
                title=title[:200],
                summary=title,
                experiment_type=_experiment_type_for_area(area),
                priority="high" if area in _ENGINEERING_AREAS else "medium",
                status="proposed",
                source="horizon_scan",
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


def load_horizon_tasks(path: Path = COMMITTED_TASKS_PATH) -> dict[str, Any]:
    data = _safe_read(path)
    return data if isinstance(data, dict) else {"tasks": []}


_HORIZON_ENGINEERING_AREAS = frozenset({"offline_sim", "monitoring", "paper_churn"})

_OFFLINE_SIM_PATHS = [
    "src/value_investor/rebalance_log.py",
    "src/value_investor/rebalance_log_cli.py",
    "src/value_investor/decision_review.py",
    "src/value_investor/exit_timing_archive_sim.py",
    "src/value_investor/exit_timing_archive_cli.py",
    "src/value_investor/index_stress_archive_sim.py",
    "src/value_investor/index_stress_archive_cli.py",
    "src/value_investor/index_stress.py",
    "src/value_investor/exit_timing_cohorts.py",
    "tests/test_rebalance_log.py",
    "tests/test_exit_timing_archive_sim.py",
    "tests/test_index_stress_archive_sim.py",
    "tests/test_exit_timing_cohorts.py",
    "docs/data/exit_timing_near_miss.json",
    "docs/data/index_stress_archive.json",
    "docs/data/index_stress_archive_review.json",
]

_MONITORING_PATHS = [
    "src/value_investor/automation_status.py",
    "src/value_investor/publish.py",
    "src/value_investor/paper_learning_review.py",
    "tests/test_automation_status.py",
]

_PAPER_CHURN_PATHS = [
    "src/value_investor/rebalance_log.py",
    "src/value_investor/rebalance_log_cli.py",
    "tests/test_rebalance_log.py",
]


def _allowed_paths_for_horizon_area(area: str) -> list[str]:
    normalized = str(area or "").strip().lower()
    if normalized == "offline_sim":
        return list(_OFFLINE_SIM_PATHS)
    if normalized == "monitoring":
        return list(_MONITORING_PATHS)
    if normalized == "paper_churn":
        return list(_PAPER_CHURN_PATHS)
    return []


def promote_horizon_engineering_tasks(
    task_ids: list[str] | None = None,
    *,
    horizon_tasks_path: Path = COMMITTED_TASKS_PATH,
    engineering_tasks_path: Path | None = None,
    promote_all_engineering: bool = False,
) -> dict[str, Any]:
    """
    Promote horizon ACCELERATE tasks into engineering_tasks.json.

    Only ``offline_sim``, ``monitoring``, and ``paper_churn`` areas with code
    paths are appended. ``paper_knobs`` experiments stay manual (process, not PR).
    """
    from value_investor.engineering_tasks import (
        BLOCKED_PATHS,
        EngineeringTask,
        _merge_task_rows,
        load_engineering_tasks,
    )
    from value_investor.engineering_tasks import (
        COMMITTED_TASKS_PATH as ENG_COMMITTED,
    )

    eng_path = engineering_tasks_path or ENG_COMMITTED
    horizon_payload = load_horizon_tasks(horizon_tasks_path)
    eng_payload = load_engineering_tasks(eng_path)
    eng_rows = list(eng_payload.get("tasks") or [])

    promoted: list[str] = []
    skipped: list[dict[str, str]] = []
    wanted = {tid.strip() for tid in (task_ids or []) if tid.strip()}
    new_engineering: list[EngineeringTask] = []

    updated_horizon: list[dict[str, Any]] = []
    for row in horizon_payload.get("tasks") or []:
        task = AnalysisTask.from_dict(row)
        should_promote = task.id in wanted or (
            promote_all_engineering and task.status == "proposed"
        )
        if not should_promote:
            updated_horizon.append(task.to_dict())
            continue
        if task.status == "promoted":
            skipped.append({"id": task.id, "reason": "already promoted"})
            updated_horizon.append(task.to_dict())
            continue
        if task.area not in _HORIZON_ENGINEERING_AREAS:
            skipped.append(
                {
                    "id": task.id,
                    "reason": f"area {task.area} is manual (not engineering_queue)",
                }
            )
            updated_horizon.append(task.to_dict())
            continue
        allowed = _allowed_paths_for_horizon_area(task.area)
        if not allowed:
            skipped.append({"id": task.id, "reason": "no allowed_paths for area"})
            updated_horizon.append(task.to_dict())
            continue
        eng_id = task.id.replace("hor-", "eng-", 1)
        priority_score = 92.0 - float(task.evidence.get("plan_index") or 0)
        new_engineering.append(
            EngineeringTask(
                id=eng_id,
                area="ops",
                title=task.title[:160],
                summary=task.summary,
                priority="high",
                priority_score=priority_score,
                source="horizon_scan",
                evidence={"horizon_task_id": task.id, **task.evidence},
                acceptance_criteria=[
                    "Behaviour covered by unit or integration tests",
                    "Observe-only / offline — no live knob auto-apply",
                    "Diff stays within allowed_paths and blocked_paths",
                ],
                allowed_paths=allowed,
                blocked_paths=list(BLOCKED_PATHS),
                status="open",
            )
        )
        task.status = "promoted"
        promoted.append(task.id)
        updated_horizon.append(task.to_dict())

    horizon_payload["tasks"] = updated_horizon
    horizon_payload["task_count"] = len(updated_horizon)
    merged_rows = _merge_task_rows(eng_rows, new_engineering)
    eng_payload["tasks"] = merged_rows
    eng_payload["task_count"] = len(merged_rows)
    eng_payload["compiled_at"] = datetime.now(UTC).isoformat()
    write_json(horizon_tasks_path, horizon_payload, compact=True)
    write_json(eng_path, eng_payload, compact=False)
    try:
        from value_investor.engineering_queue import refresh_engineering_queue_ui

        refresh_engineering_queue_ui(tasks_path=eng_path)
    except OSError:
        pass
    return {
        "promoted": promoted,
        "promoted_count": len(promoted),
        "skipped": skipped,
        "engineering_tasks_path": str(eng_path),
        "should_dispatch_queue": len(promoted) > 0,
    }


def _build_horizon_prompt(payload_path: Path) -> str:
    return f"""You are the strategic horizon analyst for an automated value portfolio project.

Read the structured JSON at: {payload_path}

It contains north-star stage context, open deferred ideas (L/N items), scratch fragments,
pending ingest trials (completed experiments awaiting review), open engineering tasks,
weekly analysis_review excerpts, paper learning metrics,
exit-timing cohort readiness, and library ladder state.

Write EIGHT plain-text sections with headings exactly as shown:

STAGE READINESS
Bullets on current stage (0–2b focus), exit criteria met vs thin, and richness-before-breadth
compliance. Cite payload fields only.

EVIDENCE STRANDS
What is instrumented (paper cohorts, archive sims, rebalance log replay) vs missing.
Reference readiness counts when present.

AUTOMATION RISKS
What breaks if knobs auto-apply, breadth expands early, or agent decisions scale without
more evidence. No live automation proposals.

COUNTERFACTUAL GAPS
What questions we cannot answer yet and which artifact type would answer them.

FRAGMENT CLUSTERING
Cluster open_fragments by theme. For each cluster: synthesize in 1–2 sentences.
Use action lines ONLY when confident:
  - DROP frag-YYYYMMDD-NN
  - PROMOTE frag-YYYYMMDD-NN → **Title** — summary. Revisit when: trigger
Mark stale duplicate fragments DROP. Do not PROMOTE without a clear revisit trigger.

INGEST GAP CLOSURE REVIEW
For each row in ingest_gap_closure_pending_review (alias ingest_trials_pending_review): summarize outcome deltas and recommend
PROMOTE (wire into ingest-loop / engineering policy), DEFER (park as deferred idea), or
DISMISS (run not worth repeating). Reference run id (igc-YYYYMMDD-NN or legacy trial-YYYYMMDD-NN). If none pending,
state "No ingest gap-closure runs pending review."

PARK
Bullets for NEW deferred ideas not already in open_deferred_ideas. Format each line:
- **Title** — one or two sentences. Revisit when: concrete trigger
Do not duplicate existing open deferred titles.

ACCELERATE
Numbered top 5 experiments for the next month. Each line MUST use:
N. [area] Experiment title — expected learning value
Areas: scoring, ingest, offline_sim, paper_knobs, paper_churn, attribution, monitoring, analysis.
Prefer offline_sim, paper_knobs, paper_churn for knob/counterfactual ideas (human gate required).

Rules:
- Do not invent metrics — only use the JSON.
- Never propose auto-applying paper-auto, decision-review --apply, or assign_signal changes.
- Do not recommend conversation transcript mining — fragments + defer are the capture path.
- Be specific enough that a human can promote experiments or run ftse-defer apply manually.
"""


def run_horizon_scan(
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    deferred_path: Path = DEFAULT_STORE,
    api_key: str,
    model: str = "composer-2.5",
    cwd: str | None = None,
    run_at: datetime | None = None,
    compile_tasks: bool = True,
    apply_park: bool = False,
    apply_fragments: bool = False,
) -> HorizonScanReview:
    """Run a single monthly strategic foresight agent pass."""
    payload = build_horizon_payload(
        data_dir=data_dir,
        output_dir=output_dir,
        deferred_path=deferred_path,
        run_at=run_at,
    )
    ok, note = has_enough_horizon_inputs(payload)
    if not ok:
        raise RuntimeError(note)

    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    payload_path = output_dir / "horizon_scan_payload.json"
    write_json(payload_path, payload, compact=True)

    try:
        agent_result = Agent.prompt(
            _build_horizon_prompt(payload_path.resolve()),
            AgentOptions(
                api_key=api_key,
                model=model,
                local=LocalAgentOptions(cwd=cwd or os.getcwd()),
            ),
        )
    except CursorAgentError as err:
        raise RuntimeError(f"Horizon scan agent startup failed: {err.message}") from err

    if agent_result.status == "error":
        raise RuntimeError(f"Horizon scan agent run failed: {agent_result.id}")

    text = (agent_result.result or "").strip()
    review = parse_horizon_scan(text)
    COMMITTED_REVIEW_MD_PATH.write_text(review.full_text + "\n", encoding="utf-8")
    write_json(
        COMMITTED_REVIEW_PATH,
        {
            "scanned_at": datetime.now(UTC).isoformat(),
            "scan_at": payload.get("scan_at"),
            "readiness_note": note,
            "sections": {
                "stage_readiness": review.stage_readiness,
                "evidence_strands": review.evidence_strands,
                "automation_risks": review.automation_risks,
                "counterfactual_gaps": review.counterfactual_gaps,
                "fragment_clustering": review.fragment_clustering,
                "park": review.park,
                "accelerate": review.accelerate,
            },
        },
        compact=True,
    )
    if compile_tasks and review.accelerate.strip():
        compile_horizon_tasks(review, tasks_path=COMMITTED_TASKS_PATH)
    if apply_park and review.park.strip():
        apply_park_proposals(parse_park_proposals(review.park), store_path=deferred_path)
    if apply_fragments and review.fragment_clustering.strip():
        apply_fragment_actions(
            review.fragment_clustering,
            store_path=deferred_path,
            promote_to_defer=True,
        )
    return review
