"""Upstream narrow-scope drafting for ingest/scoring engineering tasks.

Splits compound suggestions into first-principle builds with tightened
``allowed_paths``. When several topics in one clause union above the path cap,
split **per topic** (each topic map stays ≤ cap when possible) instead of one
wide bypassed allowlist.

``narrow_cohesion_bypass`` is reserved for a *single* unsplittable objective
(no topic map, or one topic's paths alone exceed the cap). Bypass widens the
coding sandbox; scoped auto-merge still keys off the **actual PR diff** (see
``engineering_narrow_merge.evaluate_narrow_verify``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Literal
from uuid import uuid4

from value_investor.ci_fix_tasks import AUTO_MERGE_MAX_PATHS
from value_investor.engineering_tasks import AREA_ALLOWED_PATHS, EngineeringTask

NarrowScopeMode = Literal["split", "single", "cohesion_bypass"]

EVIDENCE_BYPASS_KEY = "narrow_cohesion_bypass"
EVIDENCE_MODE_KEY = "narrow_scope_mode"
EVIDENCE_SPLIT_GROUP_KEY = "narrow_split_group_id"
EVIDENCE_SPLIT_INDEX_KEY = "narrow_split_index"
EVIDENCE_SPLIT_COUNT_KEY = "narrow_split_count"
EVIDENCE_PARENT_TITLE_KEY = "narrow_parent_title"
EVIDENCE_SCOPE_REASON_KEY = "narrow_scope_reason"

# Topic → concrete paths (no directory prefixes). Keep each topic ≤ path cap when
# possible so first-principle builds stay auto-merge eligible.
_SCORING_TOPIC_PATHS: dict[str, tuple[str, ...]] = {
    "fcf": (
        "src/value_investor/scoring/fcf.py",
        "src/value_investor/scoring/fcf_basis_overlay.py",
        "src/value_investor/scoring/fcf_three_way_conviction_overlay.py",
        "src/value_investor/scoring/screening_export_guard.py",
        "src/value_investor/scoring/snapshot.py",
        "src/value_investor/pipeline.py",
        "tests/test_pipeline.py",
        "tests/test_summary.py",
    ),
    "healthcare": (
        "src/value_investor/scoring/healthcare_overlay.py",
        "src/value_investor/scoring/healthcare_price_erosion_overlay.py",
        "src/value_investor/scoring/snapshot.py",
        "src/value_investor/pipeline.py",
        "tests/test_pipeline.py",
        "tests/test_summary.py",
    ),
    "peer": (
        "src/value_investor/scoring/peer_model_pass_table.py",
        "src/value_investor/summary.py",
        "src/value_investor/pipeline.py",
        "tests/test_summary.py",
        "tests/test_pipeline.py",
    ),
    "dividend": (
        "src/value_investor/scoring/dividend_sustainability_overlay.py",
        "src/value_investor/scoring/dividend_yield_overlay.py",
        "src/value_investor/scoring/snapshot.py",
        "tests/test_pipeline.py",
    ),
    "leverage": (
        "src/value_investor/scoring/leverage_overlay.py",
        "src/value_investor/scoring/snapshot.py",
        "tests/test_pipeline.py",
    ),
    "contractor": (
        "src/value_investor/scoring/uk_contractor_overlay.py",
        "src/value_investor/scoring/snapshot.py",
        "tests/test_pipeline.py",
    ),
    "earnings": (
        "src/value_investor/scoring/earnings_basis_overlay.py",
        "src/value_investor/scoring/earnings_growth_overlay.py",
        "src/value_investor/scoring/snapshot.py",
        "tests/test_pipeline.py",
    ),
    "quality": (
        "src/value_investor/scoring/quality_family_avoid_gate_overlay.py",
        "src/value_investor/scoring/quality_garp_roe_gate.py",
        "src/value_investor/scoring/snapshot.py",
        "tests/test_pipeline.py",
    ),
}

_SCORING_TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "fcf": ("fcf", "free cash", "cashflow_metrics", "cash flow"),
    "healthcare": ("healthcare", "reimbursement", "price erosion", "pharma"),
    "peer": ("peer model", "peer-pass", "peer pass", "pass table"),
    "dividend": ("dividend",),
    "leverage": ("leverage", "net debt"),
    "contractor": ("contractor", "uk contractor"),
    "earnings": ("earnings basis", "earnings growth"),
    "quality": ("quality family", "garp", "roe gate"),
}

_INGEST_TOPIC_PATHS: dict[str, tuple[str, ...]] = {
    "filings": (
        "src/value_investor/research/filings.py",
        "tests/test_research_filings.py",
    ),
    "gap_fill": (
        "src/value_investor/research/gap_fill_sources.py",
        "tests/test_gap_fill_deepen.py",
    ),
    "ingest_core": (
        "src/value_investor/research/ingest.py",
        "src/value_investor/research/ingest_improvement.py",
        "tests/test_research_ingest.py",
        "tests/test_ingest_improvement.py",
    ),
    "companies_house": (
        "src/value_investor/research/companies_house.py",
        "src/value_investor/companies_house.py",
        "tests/test_companies_house.py",
    ),
}

_INGEST_TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "filings": ("filing", "investegate", "rns", "sedar"),
    "gap_fill": ("gap fill", "gap-fill", "deepen"),
    "ingest_core": ("ingest improvement", "ingest loop", "fetch body"),
    "companies_house": ("companies house", "companies_house"),
}

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_NARROW_AREAS = frozenset({"scoring", "ingest"})


@dataclass(frozen=True)
class NarrowScopeSlice:
    title: str
    allowed_paths: list[str]
    cohesion_bypass: bool = False
    reason: str = ""
    topics: tuple[str, ...] = ()


@dataclass(frozen=True)
class NarrowScopePlan:
    mode: NarrowScopeMode
    slices: list[NarrowScopeSlice] = field(default_factory=list)
    reason: str = ""


def task_has_narrow_cohesion_bypass(task: EngineeringTask | dict[str, Any]) -> bool:
    if isinstance(task, EngineeringTask):
        evidence = task.evidence or {}
    else:
        evidence = dict(task.get("evidence") or {})
    return bool(evidence.get(EVIDENCE_BYPASS_KEY))


def split_suggestion_clauses(title: str) -> list[str]:
    """Split a compound engineering suggestion into first-principle clauses."""
    text = " ".join(str(title or "").split()).strip()
    if not text:
        return []
    parts = [part.strip(" .-") for part in _SENTENCE_SPLIT_RE.split(text) if part.strip()]
    if len(parts) >= 2:
        return [part for part in parts if part]
    # Fallback: "X. Y" already handled; keep single clause.
    return [text]


def _topic_tables(area: str) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    if area == "scoring":
        return _SCORING_TOPIC_PATHS, _SCORING_TOPIC_KEYWORDS
    if area == "ingest":
        return _INGEST_TOPIC_PATHS, _INGEST_TOPIC_KEYWORDS
    return {}, {}


def match_topics_for_clause(area: str, clause: str) -> list[str]:
    text = str(clause or "").lower()
    _paths, keywords = _topic_tables(area)
    matched: list[str] = []
    for topic, needles in keywords.items():
        if any(needle in text for needle in needles):
            matched.append(topic)
    return matched


def concrete_paths_for_topics(area: str, topics: list[str]) -> list[str]:
    path_table, _ = _topic_tables(area)
    paths: list[str] = []
    seen: set[str] = set()
    for topic in topics:
        for path in path_table.get(topic, ()):
            if path in seen:
                continue
            seen.add(path)
            paths.append(path)
    return paths


def _default_area_paths(area: str) -> list[str]:
    return list(AREA_ALLOWED_PATHS.get(area) or [])


def _ensure_tests_path(paths: list[str], area: str) -> list[str]:
    if any(path.startswith("tests/") for path in paths):
        return paths
    defaults = _default_area_paths(area)
    extras = [path for path in defaults if path.startswith("tests/")]
    out = list(paths)
    for path in extras:
        if path not in out:
            out.append(path)
        if any(p.startswith("tests/") for p in out):
            break
    return out


def _slice_for_single_topic(
    *,
    area: str,
    clause: str,
    topic: str,
    max_paths: int,
) -> NarrowScopeSlice:
    """Build one topic slice; bypass only if that topic alone exceeds the cap."""
    paths = _ensure_tests_path(concrete_paths_for_topics(area, [topic]), area)
    title = f"{topic}: {clause}"[:160]
    if len(paths) > max_paths:
        return NarrowScopeSlice(
            title=title,
            allowed_paths=paths,
            cohesion_bypass=True,
            reason=(
                f"topic {topic!r} paths {len(paths)} > {max_paths} — "
                "cohesion bypass (single topic cannot fit cap)"
            ),
            topics=(topic,),
        )
    return NarrowScopeSlice(
        title=title,
        allowed_paths=paths,
        cohesion_bypass=False,
        reason=f"topics={topic} paths={len(paths)}",
        topics=(topic,),
    )


def _slices_for_clause(
    *,
    area: str,
    clause: str,
    max_paths: int,
) -> list[NarrowScopeSlice]:
    """Scope one suggestion clause: union fit, else per-topic split, else bypass."""
    topics = match_topics_for_clause(area, clause)
    if not topics:
        return [
            NarrowScopeSlice(
                title=clause[:160],
                allowed_paths=_default_area_paths(area),
                cohesion_bypass=True,
                reason="no topic map — cohesion bypass keeps full area allowlist",
            )
        ]

    paths = _ensure_tests_path(concrete_paths_for_topics(area, topics), area)
    if len(paths) <= max_paths:
        return [
            NarrowScopeSlice(
                title=clause[:160],
                allowed_paths=paths,
                cohesion_bypass=False,
                reason=f"topics={','.join(topics)} paths={len(paths)}",
                topics=tuple(topics),
            )
        ]

    # Topic-union exceeds cap: split into one first-principle build per topic
    # when each topic alone fits (e.g. FCF + dividend → two siblings, not bypass).
    if len(topics) >= 2:
        # Topic-union exceeds cap: split into one first-principle build per topic
        # when each topic alone fits (e.g. FCF + dividend → two siblings, not bypass).
        return [
            _slice_for_single_topic(area=area, clause=clause, topic=topic, max_paths=max_paths)
            for topic in topics
        ]

    # Single topic already over cap — true cohesion bypass.
    return [_slice_for_single_topic(area=area, clause=clause, topic=topics[0], max_paths=max_paths)]


def plan_narrow_draft_scopes(
    *,
    area: str,
    title: str,
    max_paths: int = AUTO_MERGE_MAX_PATHS,
) -> NarrowScopePlan:
    """Plan first-principle drafts (or a cohesion bypass) for a suggestion."""
    normalized = str(area or "").strip().lower()
    if normalized not in _NARROW_AREAS:
        return NarrowScopePlan(
            mode="single",
            slices=[
                NarrowScopeSlice(
                    title=str(title or "").strip(),
                    allowed_paths=_default_area_paths(normalized),
                    reason="non-narrow area — unchanged",
                )
            ],
            reason="non-narrow area",
        )

    clauses = split_suggestion_clauses(title)
    if not clauses:
        return NarrowScopePlan(mode="single", slices=[], reason="empty title")

    slices: list[NarrowScopeSlice] = []
    for clause in clauses:
        slices.extend(_slices_for_clause(area=normalized, clause=clause, max_paths=max_paths))

    if len(slices) == 1:
        only = slices[0]
        mode: NarrowScopeMode = "cohesion_bypass" if only.cohesion_bypass else "single"
        return NarrowScopePlan(mode=mode, slices=slices, reason=only.reason)
    return NarrowScopePlan(
        mode="split",
        slices=slices,
        reason=f"split into {len(slices)} first-principle builds",
    )


def _stamp_slice_evidence(
    *,
    base: dict[str, Any],
    plan: NarrowScopePlan,
    slice_: NarrowScopeSlice,
    index: int,
    parent_title: str,
    group_id: str,
) -> dict[str, Any]:
    evidence = dict(base)
    evidence[EVIDENCE_MODE_KEY] = plan.mode
    evidence[EVIDENCE_SCOPE_REASON_KEY] = slice_.reason or plan.reason
    evidence[EVIDENCE_PARENT_TITLE_KEY] = parent_title
    evidence[EVIDENCE_BYPASS_KEY] = bool(slice_.cohesion_bypass)
    if plan.mode == "split":
        evidence[EVIDENCE_SPLIT_GROUP_KEY] = group_id
        evidence[EVIDENCE_SPLIT_INDEX_KEY] = index
        evidence[EVIDENCE_SPLIT_COUNT_KEY] = len(plan.slices)
    if slice_.topics:
        evidence["narrow_topics"] = list(slice_.topics)
    return evidence


def apply_narrow_scope_to_task(task: EngineeringTask) -> list[EngineeringTask]:
    """Expand one drafted task into scoped first-principle task(s)."""
    if task_has_narrow_cohesion_bypass(task):
        return [task]
    if str(task.area or "").strip().lower() not in _NARROW_AREAS:
        return [task]
    # Already tightened to concrete files and within cap — leave alone.
    paths = [str(p) for p in (task.allowed_paths or []) if str(p).strip()]
    if (
        paths
        and len(paths) <= AUTO_MERGE_MAX_PATHS
        and not any(p.endswith("/") for p in paths)
        and EVIDENCE_MODE_KEY in (task.evidence or {})
    ):
        return [task]

    plan = plan_narrow_draft_scopes(area=task.area, title=task.title or task.summary)
    if not plan.slices:
        return [task]

    group_id = str((task.evidence or {}).get(EVIDENCE_SPLIT_GROUP_KEY) or uuid4().hex[:12])
    parent_title = task.title
    out: list[EngineeringTask] = []
    for index, slice_ in enumerate(plan.slices, start=1):
        evidence = _stamp_slice_evidence(
            base=dict(task.evidence or {}),
            plan=plan,
            slice_=slice_,
            index=index,
            parent_title=parent_title,
            group_id=group_id,
        )
        title = slice_.title[:160]
        if plan.mode == "split" and len(plan.slices) > 1:
            title = f"{title} [{index}/{len(plan.slices)}]"[:160]
        summary = slice_.title
        if plan.mode == "split":
            summary = (
                f"First-principle slice {index}/{len(plan.slices)} of: {parent_title}. "
                f"{slice_.reason}"
            )[:500]
        elif slice_.cohesion_bypass:
            summary = (f"{task.summary or parent_title} (narrow_cohesion_bypass: {slice_.reason})")[
                :500
            ]
        # Keep the original id on the first slice; callers renumber siblings.
        task_id = task.id if index == 1 else f"{task.id}-s{index}"
        out.append(
            replace(
                task,
                id=task_id,
                title=title,
                summary=summary,
                allowed_paths=list(slice_.allowed_paths),
                evidence=evidence,
                auto_merge=False if slice_.cohesion_bypass else task.auto_merge,
            )
        )
    return out


def expand_engineering_tasks_for_narrow_scope(
    tasks: list[EngineeringTask],
) -> list[EngineeringTask]:
    """Apply narrow-scope drafting across a candidate list (preserves order)."""
    expanded: list[EngineeringTask] = []
    for task in tasks:
        expanded.extend(apply_narrow_scope_to_task(task))
    return expanded
