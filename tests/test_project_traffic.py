"""Tests for project traffic controller."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from value_investor.engineering_queue import evaluate_engineering_dispatch
from value_investor.engineering_tasks import EngineeringTask
from value_investor.project_traffic import (
    ACTION_DISPATCH_ESCALATION,
    build_daily_digest,
    classify_stuck_prs,
    escalation_unstick_prompt,
    evaluate_escalation,
    evaluate_traffic_pause,
    format_daily_digest_markdown,
    get_traffic_control_state,
    is_traffic_pause_active,
    preserve_queue_meta,
    run_project_traffic,
)
from value_investor.storage import write_json


def _task(task_id: str = "eng-20260915-01") -> EngineeringTask:
    return EngineeringTask(
        id=task_id,
        area="ci",
        title="test task",
        summary="x",
        priority="high",
        priority_score=50.0,
        source="test",
        evidence={},
        acceptance_criteria=["ok"],
        allowed_paths=["src/value_investor/project_traffic.py"],
        blocked_paths=[],
    )


def _policy(**overrides) -> dict:
    base = {
        "enabled": True,
        "stuck_pr_threshold": 2,
        "min_fail_age_minutes": 0,
        "resume_idle_minutes": 15,
        "max_fix_requests_per_pr": 2,
        "comment_cooldown_hours": 6,
        "pause_on_stuck": True,
        "monitor_cursor_prs": True,
        "request_ci_fix_comments": False,
        "request_conflict_resolve": False,
        "digest_enabled": False,
        "escalation_enabled": True,
        "escalation_min_pause_minutes": 180,
        "escalation_cooldown_hours": 12,
        "max_escalations_per_pause": 1,
        "escalation_engineering_only": True,
    }
    base.update(overrides)
    return base


def _write_tasks(path: Path, payload: dict) -> None:
    write_json(path, payload, compact=False)


def test_preserve_queue_meta_keeps_traffic_and_clearing():
    existing = {
        "queue_clearing": {"pause_active": True},
        "traffic_control": {"pause_active": True, "stuck_pr_count": 2},
        "tasks": [],
    }
    payload = preserve_queue_meta(existing, {"tasks": [], "task_count": 0})
    assert payload["queue_clearing"]["pause_active"] is True
    assert payload["traffic_control"]["stuck_pr_count"] == 2


def test_classify_stuck_prs_ci_and_conflict(monkeypatch, tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    _write_tasks(tasks_path, {"tasks": []})

    def fake_checks(pr_number, *, repo=None, token=None):
        if pr_number == 10:
            return {
                "available": True,
                "all_failed": True,
                "any_success": False,
                "completed_checks": 2,
                "latest_check_at": datetime.now(UTC) - timedelta(hours=1),
            }
        return {"available": True, "all_failed": False, "any_success": True, "completed_checks": 1}

    monkeypatch.setattr(
        "value_investor.project_traffic._checks_failed_for_pr",
        fake_checks,
    )
    monkeypatch.setattr(
        "value_investor.project_traffic._enrich_pr_merge_state",
        lambda row, **kwargs: row,
    )

    open_prs = [
        {
            "number": 10,
            "title": "ci red",
            "headRefName": "cursor/eng-20260915-01-1de3",
            "html_url": "https://example/10",
            "mergeable": True,
            "isDraft": True,
        },
        {
            "number": 11,
            "title": "conflict",
            "headRefName": "cursor/eng-20260915-02-1de3",
            "html_url": "https://example/11",
            "mergeable": "CONFLICTING",
            "isDraft": True,
        },
        {
            "number": 12,
            "title": "ok",
            "headRefName": "cursor/eng-20260915-03-1de3",
            "html_url": "https://example/12",
            "mergeable": True,
            "isDraft": True,
        },
    ]
    stuck = classify_stuck_prs(
        open_prs,
        tasks_path=tasks_path,
        now=datetime.now(UTC),
        policy={
            "monitor_cursor_prs": True,
            "min_fail_age_minutes": 0,
            "stuck_pr_threshold": 2,
        },
    )
    assert {row.number for row in stuck} == {10, 11}
    by_num = {row.number: row for row in stuck}
    assert "ci_failing" in by_num[10].reasons
    assert "merge_conflict" in by_num[11].reasons


def test_evaluate_traffic_pause_and_resume(tmp_path: Path, monkeypatch):
    tasks_path = tmp_path / "engineering_tasks.json"
    _write_tasks(tasks_path, {"tasks": []})
    monkeypatch.setattr(
        "value_investor.project_traffic._traffic_policy",
        lambda: {
            "enabled": True,
            "stuck_pr_threshold": 2,
            "min_fail_age_minutes": 0,
            "resume_idle_minutes": 15,
            "max_fix_requests_per_pr": 2,
            "comment_cooldown_hours": 6,
            "pause_on_stuck": True,
            "monitor_cursor_prs": True,
            "request_ci_fix_comments": False,
            "request_conflict_resolve": False,
            "digest_enabled": False,
        },
    )
    from value_investor.project_traffic import StuckPr

    now = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
    stuck = [
        StuckPr(10, "cursor/eng-20260915-01-1de3", "a", "u", True, ["ci_failing"]),
        StuckPr(11, "cursor/eng-20260915-02-1de3", "b", "u", True, ["merge_conflict"]),
    ]
    state = evaluate_traffic_pause(stuck_prs=stuck, tasks_path=tasks_path, apply=True, now=now)
    assert state["pause_active"] is True
    assert is_traffic_pause_active(tasks_path=tasks_path)

    later = now + timedelta(minutes=20)
    resumed = evaluate_traffic_pause(stuck_prs=[], tasks_path=tasks_path, apply=True, now=later)
    assert resumed["pause_active"] is False
    assert resumed.get("escalation_count_this_pause") == 0


def test_dispatch_blocked_by_traffic_pause(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [_task().to_dict()],
        "traffic_control": {
            "pause_active": True,
            "stuck_pr_count": 2,
            "pause_reasons": ["ci_failing"],
        },
    }
    _write_tasks(tasks_path, payload)
    decision = evaluate_engineering_dispatch(tasks_path=tasks_path, open_prs=[])
    assert decision.should_dispatch is False
    assert "traffic pause" in decision.reason.lower()


def test_run_project_traffic_dry_run(tmp_path: Path, monkeypatch):
    tasks_path = tmp_path / "engineering_tasks.json"
    _write_tasks(tasks_path, {"tasks": []})
    monkeypatch.setattr(
        "value_investor.project_traffic._traffic_policy",
        lambda: {
            "enabled": True,
            "stuck_pr_threshold": 1,
            "min_fail_age_minutes": 0,
            "resume_idle_minutes": 15,
            "max_fix_requests_per_pr": 2,
            "comment_cooldown_hours": 6,
            "pause_on_stuck": True,
            "monitor_cursor_prs": True,
            "request_ci_fix_comments": True,
            "request_conflict_resolve": True,
            "digest_enabled": True,
        },
    )
    monkeypatch.setattr(
        "value_investor.project_traffic._checks_failed_for_pr",
        lambda *a, **k: {
            "available": True,
            "all_failed": True,
            "any_success": False,
            "completed_checks": 1,
            "latest_check_at": datetime.now(UTC) - timedelta(hours=2),
        },
    )
    monkeypatch.setattr(
        "value_investor.project_traffic._enrich_pr_merge_state",
        lambda row, **kwargs: row,
    )
    monkeypatch.setattr(
        "value_investor.project_traffic.post_pr_comment",
        lambda **kwargs: (True, "comment posted"),
    )

    report = run_project_traffic(
        tasks_path=tasks_path,
        open_prs=[
            {
                "number": 42,
                "title": "red",
                "headRefName": "cursor/eng-20260915-01-1de3",
                "html_url": "https://example/42",
                "mergeable": True,
                "head_sha": "abc",
            }
        ],
        apply=False,
        write_digest=True,
        now=datetime.now(UTC),
    )
    assert report.pause_active is True or len(report.stuck_prs) == 1
    assert report.digest is not None
    assert report.digest["merge_authority"]["status"] == "restricted"
    # dry-run must not persist pause
    assert is_traffic_pause_active(tasks_path=tasks_path) is False


def test_daily_digest_marks_ungrounded_without_progress(tmp_path: Path):
    digest = build_daily_digest(
        stuck_prs=[],
        traffic_state={"pause_active": False, "stuck_pr_count": 0},
        actions=[],
        progress_report_path=tmp_path / "missing_progress.json",
        project_progress_path=tmp_path / "missing_project.json",
        queue_health_path=tmp_path / "missing_qh.json",
        ops_status_path=tmp_path / "missing_ops.json",
    )
    md = format_daily_digest_markdown(digest)
    assert "Trajectory" in md or "trajectory" in digest
    assert digest["merge_authority"]["status"] == "restricted"
    assert "end_of_day_project_traffic" == digest["role"]


def test_daily_digest_reads_appraisal_strengths(tmp_path: Path):
    progress = tmp_path / "project_progress.json"
    write_json(
        progress,
        {
            "headline": "Focus on stage 2b",
            "appraisal": {
                "strengths": ["Library graduated"],
                "gaps": ["AI excess negative"],
                "next_actions": ["Accumulate marks"],
            },
            "stages": [{"id": "0", "name": "UK", "status": "complete"}],
        },
        compact=False,
    )
    digest = build_daily_digest(
        stuck_prs=[],
        traffic_state={"pause_active": False},
        actions=[],
        project_progress_path=progress,
        progress_report_path=tmp_path / "missing.json",
        queue_health_path=tmp_path / "missing_qh.json",
        ops_status_path=tmp_path / "missing_ops.json",
    )
    assert any("Library graduated" in row for row in digest["achieved"])
    assert digest["gaps"] == ["AI excess negative"]
    assert digest["next_actions"] == ["Accumulate marks"]


def _stuck(*args, **kwargs):
    from value_investor.project_traffic import StuckPr

    return StuckPr(*args, **kwargs)


def test_evaluate_escalation_requires_min_pause():
    now = datetime(2026, 9, 15, 16, 0, tzinfo=UTC)
    pr = _stuck(
        10,
        "cursor/eng-20260915-01-1de3",
        "a",
        "u",
        True,
        ["ci_failing"],
        checks_failed=True,
    )
    state = {
        "pause_active": True,
        "pause_started_at": (now - timedelta(minutes=30)).isoformat(),
        "fix_requests": {"10": {"count": 1, "last_at": (now - timedelta(hours=4)).isoformat()}},
    }
    actions, rows, out = evaluate_escalation(
        [pr],
        state=state,
        policy=_policy(),
        now=now,
        conflict_dispatches=[],
        apply=False,
    )
    assert rows == []
    assert any(a.detail == "pause_too_young" for a in actions)
    assert out.get("should_dispatch_escalation_agent") == []


def test_evaluate_escalation_fires_after_first_line_exhausted():
    now = datetime(2026, 9, 15, 16, 0, tzinfo=UTC)
    pr = _stuck(
        10,
        "cursor/eng-20260915-01-1de3",
        "a",
        "u",
        True,
        ["ci_failing"],
        checks_failed=True,
    )
    started = now - timedelta(hours=4)
    state = {
        "pause_active": True,
        "pause_started_at": started.isoformat(),
        "last_action_at": (now - timedelta(hours=4)).isoformat(),
        "fix_requests": {
            "10": {
                "count": 1,
                "last_kind": "request_ci_fix",
                "last_at": (now - timedelta(hours=4)).isoformat(),
                "last_head_sha": "abc",
            }
        },
    }
    actions, rows, out = evaluate_escalation(
        [pr],
        state=state,
        policy=_policy(),
        now=now,
        conflict_dispatches=[],
        first_line_commits={10: ["chore(ci): autofix ruff on changed Python files"]},
        apply=False,
    )
    assert len(rows) == 1
    assert rows[0]["pr_number"] == 10
    assert rows[0]["kind"] == "escalation"
    assert any(a.kind == ACTION_DISPATCH_ESCALATION for a in actions)
    assert out.get("should_dispatch_escalation_agent")


def test_evaluate_escalation_skips_non_engineering_and_in_flight_conflict():
    now = datetime(2026, 9, 15, 16, 0, tzinfo=UTC)
    hunter = _stuck(
        11,
        "cursor/parked-hunter-compile-bb45",
        "h",
        "u",
        True,
        ["ci_failing"],
        checks_failed=True,
    )
    state = {
        "pause_active": True,
        "pause_started_at": (now - timedelta(hours=5)).isoformat(),
        "fix_requests": {"11": {"count": 2}},
    }
    _, rows, out_h = evaluate_escalation(
        [hunter],
        state=state,
        policy=_policy(),
        now=now,
        conflict_dispatches=[],
        apply=False,
    )
    assert rows == []
    assert out_h.get("escalation_skip_reason") == "no_eligible_engineering_prs"

    eng = _stuck(
        12,
        "cursor/eng-20260915-02-1de3",
        "c",
        "u",
        True,
        ["merge_conflict"],
        conflict=True,
    )
    _, rows2, out = evaluate_escalation(
        [eng],
        state={
            **state,
            "fix_requests": {"12": {"count": 1}},
        },
        policy=_policy(),
        now=now,
        conflict_dispatches=[{"pr_number": 12, "branch": eng.branch}],
        apply=False,
    )
    assert rows2 == []
    assert out.get("escalation_skip_reason") == "first_line_conflict_resolve_in_flight"


def test_evaluate_escalation_cooldown_and_cap(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "value_investor.project_traffic.post_pr_comment",
        lambda **kwargs: (True, "comment posted"),
    )
    now = datetime(2026, 9, 15, 16, 0, tzinfo=UTC)
    pr = _stuck(
        10,
        "cursor/eng-20260915-01-1de3",
        "a",
        "u",
        True,
        ["ci_failing"],
        checks_failed=True,
    )
    state = {
        "pause_active": True,
        "pause_started_at": (now - timedelta(hours=5)).isoformat(),
        "last_action_at": (now - timedelta(hours=4)).isoformat(),
        "fix_requests": {"10": {"count": 1, "last_at": (now - timedelta(hours=4)).isoformat()}},
    }
    _, rows, out = evaluate_escalation(
        [pr],
        state=state,
        policy=_policy(),
        now=now,
        conflict_dispatches=[],
        apply=True,
    )
    assert len(rows) == 1
    assert out["escalation_count_this_pause"] == 1
    _, rows2, out2 = evaluate_escalation(
        [pr],
        state=out,
        policy=_policy(),
        now=now + timedelta(minutes=10),
        conflict_dispatches=[],
        apply=True,
    )
    assert rows2 == []
    assert out2.get("escalation_skip_reason") in {
        "max_escalations_this_pause",
        "escalation_cooldown",
    }


def test_run_project_traffic_escalates_when_pause_stale(tmp_path: Path, monkeypatch):
    tasks_path = tmp_path / "engineering_tasks.json"
    now = datetime(2026, 9, 15, 16, 0, tzinfo=UTC)
    started = now - timedelta(hours=4)
    _write_tasks(
        tasks_path,
        {
            "tasks": [],
            "traffic_control": {
                "pause_active": True,
                "pause_started_at": started.isoformat(),
                "stuck_pr_count": 1,
                "last_action_at": started.isoformat(),
                "fix_requests": {
                    "42": {
                        "count": 1,
                        "last_kind": "request_ci_fix",
                        "last_at": started.isoformat(),
                        "last_head_sha": "abc",
                    }
                },
            },
        },
    )
    monkeypatch.setattr("value_investor.project_traffic._traffic_policy", lambda: _policy(
        stuck_pr_threshold=1,
        request_ci_fix_comments=True,
        comment_cooldown_hours=6,
        digest_enabled=True,
    ))
    monkeypatch.setattr(
        "value_investor.project_traffic._checks_failed_for_pr",
        lambda *a, **k: {
            "available": True,
            "all_failed": True,
            "any_success": False,
            "completed_checks": 1,
            "latest_check_at": now - timedelta(hours=2),
        },
    )
    monkeypatch.setattr(
        "value_investor.project_traffic._enrich_pr_merge_state",
        lambda row, **kwargs: row,
    )
    monkeypatch.setattr(
        "value_investor.project_traffic.post_pr_comment",
        lambda **kwargs: (True, "comment posted"),
    )
    report = run_project_traffic(
        tasks_path=tasks_path,
        open_prs=[
            {
                "number": 42,
                "title": "red",
                "headRefName": "cursor/eng-20260915-01-1de3",
                "html_url": "https://example/42",
                "mergeable": True,
                "head_sha": "abc",
            }
        ],
        apply=True,
        write_digest=False,
        now=now,
    )
    assert report.pause_active is True
    assert len(report.should_dispatch_escalation_agent) == 1
    assert report.should_dispatch_escalation_agent[0]["pr_number"] == 42
    persisted = is_traffic_pause_active(tasks_path=tasks_path)
    assert persisted is True
    state = get_traffic_control_state(tasks_path=tasks_path)
    assert state.get("escalation_count_this_pause") == 1
    assert state.get("last_escalation_at")


def test_escalation_unstick_prompt_is_not_a_listener():
    text = escalation_unstick_prompt(branch="cursor/eng-20260915-01-1de3", pr_number=9, task_id=None)
    assert "not a standing GitHub event listener" in text
    assert "Do NOT merge" in text or "do NOT merge" in text
