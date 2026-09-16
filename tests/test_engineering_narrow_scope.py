"""Tests for upstream narrow-scope drafting + cohesion bypass."""

from __future__ import annotations

from value_investor.ci_fix_tasks import AUTO_MERGE_MAX_PATHS
from value_investor.engineering_narrow_merge import evaluate_narrow_verify
from value_investor.engineering_narrow_scope import (
    apply_narrow_scope_to_task,
    plan_narrow_draft_scopes,
    split_suggestion_clauses,
    task_has_narrow_cohesion_bypass,
)
from value_investor.engineering_tasks import AREA_ALLOWED_PATHS, BLOCKED_PATHS, EngineeringTask


def _scoring_task(title: str, **overrides) -> EngineeringTask:
    payload = dict(
        id="eng-20260916-01",
        area="scoring",
        title=title,
        summary=title,
        priority="high",
        priority_score=88.0,
        source="compile_cap_drain",
        allowed_paths=list(AREA_ALLOWED_PATHS["scoring"]),
        blocked_paths=list(BLOCKED_PATHS),
        auto_merge=False,
        status="open",
    )
    payload.update(overrides)
    return EngineeringTask(**payload)


def test_split_compound_fcf_and_healthcare_suggestion():
    title = (
        "Fail-closed or flag when screen FCF (1,059m) disagrees with Yahoo/filing "
        "FCF (852m) while TTM is suppressed and cashflow. Turn on healthcare price "
        "erosion overlay for buy-tier names."
    )
    clauses = split_suggestion_clauses(title)
    assert len(clauses) == 2
    plan = plan_narrow_draft_scopes(area="scoring", title=title)
    assert plan.mode == "split"
    assert len(plan.slices) == 2
    assert all(not s.cohesion_bypass for s in plan.slices)
    assert all(len(s.allowed_paths) <= AUTO_MERGE_MAX_PATHS for s in plan.slices)
    assert any("fcf" in s.topics for s in plan.slices)
    assert any("healthcare" in s.topics for s in plan.slices)

    tasks = apply_narrow_scope_to_task(_scoring_task(title))
    assert len(tasks) == 2
    assert tasks[0].id == "eng-20260916-01"
    assert tasks[1].id.startswith("eng-20260916-01")
    assert not any(p.endswith("/") for t in tasks for p in t.allowed_paths)


def test_cohesion_bypass_when_no_topic_map():
    title = "Refactor scoring snapshot serialization for dashboard export quirks"
    plan = plan_narrow_draft_scopes(area="scoring", title=title)
    assert plan.mode == "cohesion_bypass"
    assert plan.slices[0].cohesion_bypass
    assert plan.slices[0].allowed_paths == list(AREA_ALLOWED_PATHS["scoring"])

    task = apply_narrow_scope_to_task(_scoring_task(title))[0]
    assert task_has_narrow_cohesion_bypass(task)
    assert task.auto_merge is False

    # Drain-sourced scoring tasks resolve to merge_class compile_cap_drain, not
    # scoring_narrow — cohesion bypass still skips scoped auto-merge.
    gate = evaluate_narrow_verify(
        task=task,
        changed_files=[
            "src/value_investor/scoring/snapshot.py",
            "src/value_investor/pipeline.py",
            "src/value_investor/summary.py",
            "src/value_investor/scoring/fcf.py",
            "src/value_investor/scoring/fcf_basis_overlay.py",
            "src/value_investor/scoring/healthcare_overlay.py",
            "src/value_investor/scoring/healthcare_price_erosion_overlay.py",
            "src/value_investor/scoring/screening_export_guard.py",
            "tests/test_pipeline.py",
            "tests/test_summary.py",
            "src/value_investor/models/foo.py",
        ],
        policy="merge",
    )
    assert gate.ok
    assert gate.verdict == "skipped"
    assert gate.merge_class == "compile_cap_drain"
    assert "narrow_cohesion_bypass" in gate.reason


def test_single_fcf_topic_stays_narrow():
    title = "Fail-closed when screen FCF disagrees with Yahoo/filing FCF"
    plan = plan_narrow_draft_scopes(area="scoring", title=title)
    assert plan.mode == "single"
    assert not plan.slices[0].cohesion_bypass
    assert len(plan.slices[0].allowed_paths) <= AUTO_MERGE_MAX_PATHS
