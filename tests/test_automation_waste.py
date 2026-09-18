"""Tests for automation waste detection and traffic remediation."""

from __future__ import annotations

from pathlib import Path

from value_investor.automation_waste import (
    FINDING_TITLE_ENG_AGENT_REBURN,
    collect_automation_waste_signals,
    detect_cursor_workflow_fail_loops,
    detect_engineering_agent_reburn,
)
from value_investor.engineering_queue import evaluate_engineering_dispatch
from value_investor.engineering_tasks import EngineeringTask
from value_investor.project_traffic import (
    AUTOMATION_WASTE_REBURN_TITLE,
    PAUSE_REASON_AUTOMATION_WASTE,
    RECTIFICATION_STOP_AUTOMATION_WASTE,
    is_traffic_pause_active,
    planned_rectification_for_ops_finding,
    remediate_automation_waste,
)
from value_investor.storage import write_json


def _task(task_id: str = "eng-20260918-01") -> EngineeringTask:
    return EngineeringTask(
        id=task_id,
        area="scoring",
        title="dividend overlay",
        summary="x",
        priority="medium",
        priority_score=43.0,
        source="test",
        evidence={},
        acceptance_criteria=["ok"],
        allowed_paths=["src/value_investor/scoring/dividend_yield_overlay.py"],
        blocked_paths=[],
    )


def _write_open_tasks(path: Path, *task_ids: str) -> None:
    rows = []
    for task_id in task_ids:
        t = _task(task_id)
        rows.append(
            {
                **t.to_dict(),
                "status": "open",
            }
        )
    write_json(path, {"tasks": rows, "task_count": len(rows)}, compact=False)


def test_detect_eng_agent_reburn_requires_failures_and_open_queue(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    _write_open_tasks(tasks_path, "eng-20260918-01")
    failures = [{"id": i, "conclusion": "failure"} for i in range(3)]
    signal = detect_engineering_agent_reburn(
        tasks_path=tasks_path,
        open_prs=[],
        recent_agent_failures=failures,
        fail_threshold=3,
    )
    assert signal is not None
    assert signal.title == FINDING_TITLE_ENG_AGENT_REBURN
    assert signal.auto_remediable is True
    assert "eng-20260918-01" in signal.task_ids

    assert (
        detect_engineering_agent_reburn(
            tasks_path=tasks_path,
            open_prs=[],
            recent_agent_failures=failures[:2],
            fail_threshold=3,
        )
        is None
    )


def test_detect_eng_agent_reburn_skips_when_pr_in_flight(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    t = _task()
    write_json(
        tasks_path,
        {
            "tasks": [
                {**t.to_dict(), "status": "pr_open", "pr_number": 42},
            ],
            "task_count": 1,
        },
        compact=False,
    )
    failures = [{"id": i} for i in range(5)]
    assert (
        detect_engineering_agent_reburn(
            tasks_path=tasks_path,
            open_prs=[{"number": 42, "headRefName": "cursor/eng-20260918-01-1de3"}],
            recent_agent_failures=failures,
        )
        is None
    )


def test_cursor_workflow_fail_loop_skips_engineering_agent():
    signals = detect_cursor_workflow_fail_loops(
        failure_counts={
            "engineering-agent.yml": 9,
            "analysis-review.yml": 3,
        },
        fail_threshold=3,
    )
    assert len(signals) == 1
    assert signals[0].workflow == "analysis-review.yml"
    assert signals[0].auto_remediable is False


def test_remediate_automation_waste_parks_and_pauses(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    _write_open_tasks(tasks_path, "eng-20260918-01", "eng-20260917-01")
    failures = [{"id": i} for i in range(4)]

    signals, actions, state = remediate_automation_waste(
        tasks_path=tasks_path,
        open_prs=[],
        recent_agent_failures=failures,
        apply=True,
    )
    assert signals
    assert any(a.kind == "stop_automation_waste" for a in actions)
    assert state.get("pause_active") is True
    assert PAUSE_REASON_AUTOMATION_WASTE in (state.get("pause_reasons") or [])
    assert is_traffic_pause_active(tasks_path=tasks_path)

    data = __import__("json").loads(tasks_path.read_text(encoding="utf-8"))
    parked = [row for row in data["tasks"] if row.get("status") == "parked"]
    assert {row["id"] for row in parked} == {"eng-20260918-01", "eng-20260917-01"}
    assert all(row.get("parked_policy") == "reburn_loop" for row in parked)

    decision = evaluate_engineering_dispatch(tasks_path=tasks_path, open_prs=[])
    assert decision.should_dispatch is False
    assert "automation waste" in decision.reason.lower() or "automation_waste" in decision.reason


def test_remediate_clears_waste_hold_when_queue_empty(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    write_json(tasks_path, {"tasks": [], "task_count": 0}, compact=False)
    # Seed an active waste hold with no open tasks / failures.
    write_json(
        tasks_path,
        {
            "tasks": [],
            "task_count": 0,
            "traffic_control": {
                "pause_active": True,
                "pause_reasons": [PAUSE_REASON_AUTOMATION_WASTE],
                "automation_waste_active": True,
            },
        },
        compact=False,
    )
    signals, actions, state = remediate_automation_waste(
        tasks_path=tasks_path,
        open_prs=[],
        recent_agent_failures=[],
        apply=True,
    )
    assert signals == []
    assert state.get("automation_waste_active") is False
    assert PAUSE_REASON_AUTOMATION_WASTE not in (state.get("pause_reasons") or [])
    assert any("cleared" in a.detail for a in actions)


def test_planned_rectification_maps_waste_finding():
    action, detail = planned_rectification_for_ops_finding(
        {"title": AUTOMATION_WASTE_REBURN_TITLE, "severity": "fail", "category": "automation_waste"}
    )
    assert action == RECTIFICATION_STOP_AUTOMATION_WASTE
    assert "park" in detail.lower()


def test_collect_registry_combines_signals(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    _write_open_tasks(tasks_path, "eng-20260918-01")
    signals = collect_automation_waste_signals(
        tasks_path=tasks_path,
        open_prs=[],
        recent_agent_failures=[{"id": 1}, {"id": 2}, {"id": 3}],
        cursor_workflow_failure_counts={"horizon-scan.yml": 4},
    )
    kinds = {s.kind for s in signals}
    assert "eng_agent_reburn" in kinds
    assert "cursor_workflow_fail_loop" in kinds
