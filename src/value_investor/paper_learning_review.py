"""Optional observe-only paper churn / cost learning review (agent synthesis)."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions

from value_investor.analysis_review import AnalysisTask, _EXPERIMENT_LINE
from value_investor.churn_health import CHURN_HEALTH_FILENAME, build_churn_health
from value_investor.review_policy import (
    DEFAULT_REVIEW_POLICY_PATH,
    load_review_policy,
    paper_learning_review_enabled,
)
from value_investor.storage import read_json, write_json

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path("docs/data")
DEFAULT_OUTPUT_DIR = Path("output")
PAPER_ROOT = DEFAULT_DATA_DIR / "paper_automation"
COMMITTED_REVIEW_PATH = DEFAULT_DATA_DIR / "paper_learning_review.json"
COMMITTED_REVIEW_MD_PATH = DEFAULT_DATA_DIR / "paper_learning_review.md"
COMMITTED_TASKS_PATH = DEFAULT_DATA_DIR / "paper_learning_tasks.json"

_PAPER_CHURN_AREAS = frozenset({"paper_churn", "paper_knobs", "offline_sim", "monitoring", "analysis"})


@dataclass
class PaperLearningReview:
    churn_summary: str
    per_track_diagnosis: str
    proposed_experiments: str
    defer: str

    @property
    def full_text(self) -> str:
        parts = [
            ("CHURN SUMMARY", self.churn_summary),
            ("PER-TRACK DIAGNOSIS", self.per_track_diagnosis),
            ("PROPOSED EXPERIMENTS", self.proposed_experiments),
            ("DEFER", self.defer),
        ]
        return "\n\n".join(
            f"{heading}\n{body.strip()}"
            for heading, body in parts
            if body.strip()
        )


def _normalize_heading(line: str) -> str:
    text = line.strip().lstrip("#").strip()
    if text.startswith("**") and text.endswith("**") and len(text) > 4:
        text = text[2:-2].strip()
    return text.rstrip(":").strip().upper()


def parse_paper_learning_review(text: str) -> PaperLearningReview:
    section_keys = {
        "CHURN SUMMARY": "churn_summary",
        "PER-TRACK DIAGNOSIS": "per_track_diagnosis",
        "PROPOSED EXPERIMENTS": "proposed_experiments",
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
    return PaperLearningReview(
        churn_summary="\n".join(buckets["churn_summary"]).strip(),
        per_track_diagnosis="\n".join(buckets["per_track_diagnosis"]).strip(),
        proposed_experiments="\n".join(buckets["proposed_experiments"]).strip(),
        defer="\n".join(buckets["defer"]).strip(),
    )


def _safe_read(path: Path) -> dict[str, Any] | None:
    try:
        raw = read_json(path)
    except FileNotFoundError:
        return None
    return raw if isinstance(raw, dict) else None


def build_paper_learning_payload(
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    run_at: datetime | None = None,
) -> dict[str, Any]:
    """Assemble deterministic inputs for the paper-learning review agent."""
    effective_run_at = run_at or datetime.now(UTC)
    paper_root = Path(data_dir) / "paper_automation"
    churn_health = _safe_read(paper_root / CHURN_HEALTH_FILENAME)
    if not churn_health:
        churn_health = build_churn_health(paper_root, as_of=effective_run_at)
    return {
        "run_at": effective_run_at.isoformat(),
        "review_policy": load_review_policy(paper_root / "review_policy.json"),
        "churn_health": churn_health,
        "learning_tracks_review": _safe_read(paper_root / "learning_tracks_review.json"),
        "learning_tracks_summary": _safe_read(paper_root / "learning_tracks_summary.json"),
        "exit_shadow": _safe_read(paper_root / "learning_tracks_exit_shadow.json"),
        "guardrails": {
            "observe_only": True,
            "no_decision_review_apply": True,
            "no_paper_book_writes": True,
            "no_engineering_auto_promote": True,
        },
    }


def has_enough_paper_learning_inputs(payload: dict[str, Any]) -> tuple[bool, str]:
    churn = payload.get("churn_health") or {}
    tracks = churn.get("tracks") or {}
    if tracks:
        return True, "ok"
    learning = payload.get("learning_tracks_review")
    if learning:
        return True, "ok (learning_tracks_review present; churn_health thin)"
    return False, "Need learning_tracks_churn_health.json or learning_tracks_review.json"


def compile_paper_learning_tasks(
    review: PaperLearningReview,
    *,
    run_stamp: str | None = None,
    tasks_path: Path = COMMITTED_TASKS_PATH,
) -> dict[str, Any]:
    """Parse proposed experiments into paper_learning_tasks.json (status=proposed)."""
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
    for line in review.proposed_experiments.splitlines():
        match = _EXPERIMENT_LINE.match(line.strip())
        if not match:
            continue
        area = match.group("area").strip().lower()
        if area not in _PAPER_CHURN_AREAS:
            logger.info("Skipping non-paper experiment area: %s", area)
            continue
        title = match.group("title").strip()
        task_id = f"plr-{stamp}-{seq:02d}"
        experiment_type = "churn_probe" if area == "paper_churn" else (
            "decision_review_probe" if area == "paper_knobs" else area
        )
        promote_to = "manual" if area != "paper_knobs" else "decision_review_manual"
        new_tasks.append(
            AnalysisTask(
                id=task_id,
                area=area,
                title=title[:200],
                summary=title,
                experiment_type=experiment_type,
                priority="medium",
                status="proposed",
                source="paper_learning_review",
                promote_to=promote_to,
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


def _build_paper_learning_prompt(payload_path: Path) -> str:
    return f"""You are the paper-learning churn analyst for an automated FTSE value portfolio.

Read the structured JSON at: {payload_path}

Focus on churn_health (cost drag, trade counts, hold-buffer state, duplicate-day skips,
adjacent buy/sell flips) and learning_tracks_review. This is observe-only — do not propose
auto-applying decision-review knobs or changing live execution.

Write FOUR plain-text sections with headings exactly as shown:

CHURN SUMMARY
3–4 sentences on whether churn/cost drag is improving after hold-buffer guards, and the
single biggest operational learning gap.

PER-TRACK DIAGNOSIS
Bullets per track (rules, ai_judgment, momentum_grace): cost_drag, trade_count,
exit_streak / reentry_cooldown, adjacent flips, duplicate-day skip notes. Cite JSON only.

PROPOSED EXPERIMENTS
Numbered top 3 experiments. Each line MUST use:
``N. [area] Experiment title — expected learning value``
Areas allowed: paper_churn, paper_knobs, offline_sim, monitoring, analysis.
Prefer paper_churn for guard tuning (exit_confirm_screens, min_rebalance_notional_gbp).

DEFER
Ideas that must stay manual / observe-only until more marks (live capital, auto knob apply).

Rules:
- Do not invent metrics.
- Never propose engineering PRs, decision-review --apply, or paper-auto code changes here.
- Be specific enough for a human to run a counterfactual or edit track config.json.
"""


def run_paper_learning_review(
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    api_key: str,
    model: str = "composer-2.5",
    cwd: str | None = None,
    run_at: datetime | None = None,
    compile_tasks: bool = True,
    policy_path: Path = DEFAULT_REVIEW_POLICY_PATH,
) -> PaperLearningReview:
    """Run a single agent pass over churn/cost learning artifacts."""
    if not paper_learning_review_enabled(policy_path):
        raise RuntimeError("paper_learning_review is disabled in review_policy.json")

    payload = build_paper_learning_payload(
        data_dir=data_dir,
        output_dir=output_dir,
        run_at=run_at,
    )
    ok, note = has_enough_paper_learning_inputs(payload)
    if not ok:
        raise RuntimeError(note)

    output_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    payload_path = output_dir / "paper_learning_review_payload.json"
    write_json(payload_path, payload, compact=True)

    try:
        agent_result = Agent.prompt(
            _build_paper_learning_prompt(payload_path.resolve()),
            AgentOptions(
                api_key=api_key,
                model=model,
                local=LocalAgentOptions(cwd=cwd or os.getcwd()),
            ),
        )
    except CursorAgentError as err:
        raise RuntimeError(f"Paper learning review agent startup failed: {err.message}") from err

    if agent_result.status == "error":
        raise RuntimeError(f"Paper learning review agent run failed: {agent_result.id}")

    text = (agent_result.result or "").strip()
    review = parse_paper_learning_review(text)
    COMMITTED_REVIEW_MD_PATH.write_text(review.full_text + "\n", encoding="utf-8")
    write_json(
        COMMITTED_REVIEW_PATH,
        {
            "reviewed_at": datetime.now(UTC).isoformat(),
            "run_at": payload.get("run_at"),
            "enabled": True,
            "sections": {
                "churn_summary": review.churn_summary,
                "per_track_diagnosis": review.per_track_diagnosis,
                "proposed_experiments": review.proposed_experiments,
                "defer": review.defer,
            },
        },
        compact=True,
    )
    if compile_tasks and review.proposed_experiments.strip():
        compile_paper_learning_tasks(review, tasks_path=COMMITTED_TASKS_PATH)
    return review
