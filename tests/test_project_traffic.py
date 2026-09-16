"""Tests for project traffic controller."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from value_investor.engineering_queue import evaluate_engineering_dispatch
from value_investor.engineering_tasks import EngineeringTask
from value_investor.project_traffic import (
    QUEUE_MERGE_SYNC_FINDING_TITLE,
    RECTIFICATION_HUMAN_TRIAGE,
    RECTIFICATION_QUEUE_SYNC,
    build_daily_digest,
    classify_stuck_prs,
    evaluate_traffic_pause,
    format_daily_digest_markdown,
    handoff_ops_monitor_email_to_pm,
    is_traffic_pause_active,
    planned_rectification_for_ops_finding,
    preserve_queue_meta,
    remediate_queue_merge_sync,
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
    assert report.digest["merge_authority"]["status"] == "scoped_auto_merge"
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
    assert digest["merge_authority"]["status"] == "scoped_auto_merge"
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


def test_remediate_queue_merge_sync_marks_merged(tmp_path: Path, monkeypatch):
    from value_investor.engineering_recovery import RecoveryResult

    tasks_path = tmp_path / "engineering_tasks.json"
    write_json(
        tasks_path,
        {
            "tasks": [
                {
                    "id": "eng-20260915-04",
                    "status": "pr_open",
                    "branch_name": "cursor/eng-20260915-04-1de3",
                    "area": "ingest",
                    "title": "cashflow",
                    "summary": "x",
                    "priority": "high",
                    "priority_score": 50,
                    "source": "test",
                    "allowed_paths": ["src/value_investor/research/ingest.py"],
                    "blocked_paths": [],
                }
            ]
        },
        compact=False,
    )
    lag_payload = [
        {
            "task_id": "eng-20260915-04",
            "branch": "cursor/eng-20260915-04-1de3",
            "status": "pr_open",
            "pr_number": 652,
            "merged_at": "2026-09-15T13:49:04Z",
        }
    ]
    state = {"cleared": False}

    def fake_list(**kwargs):
        return [] if state["cleared"] else list(lag_payload)

    monkeypatch.setattr(
        "value_investor.engineering_recovery.list_merge_sync_lag_tasks",
        fake_list,
    )
    calls = {"n": 0}

    def fake_recover(**kwargs):
        calls["n"] += 1
        state["cleared"] = True
        return RecoveryResult(merged=["eng-20260915-04"])

    monkeypatch.setattr(
        "value_investor.engineering_recovery.recover_engineering_queue",
        fake_recover,
    )
    lag, fixed, remaining, actions = remediate_queue_merge_sync(
        tasks_path=tasks_path,
        apply=True,
        token="x",
    )
    assert lag == ["eng-20260915-04"]
    assert fixed == ["eng-20260915-04"]
    assert remaining == []
    assert calls["n"] == 1
    assert any(a.kind == "remediate_queue_merge_sync" for a in actions)


def test_planned_rectification_mapping():
    assert (
        planned_rectification_for_ops_finding(
            {
                "severity": "warn",
                "category": "engineering",
                "title": QUEUE_MERGE_SYNC_FINDING_TITLE,
                "summary": "lag",
            }
        )[0]
        == RECTIFICATION_QUEUE_SYNC
    )
    assert (
        planned_rectification_for_ops_finding(
            {
                "severity": "warn",
                "category": "ingest",
                "title": "Buy-tier filing ingest stalled",
                "summary": "x",
            }
        )[0]
        == RECTIFICATION_HUMAN_TRIAGE
    )
    assert (
        planned_rectification_for_ops_finding(
            {
                "severity": "fail",
                "category": "workflows",
                "title": "Workflow overdue: FTSE Ingest Loop",
                "summary": "stale",
            }
        )[0]
        == "rerun_or_dispatch_workflow"
    )


def test_handoff_ops_monitor_email_to_pm_writes_artifact(tmp_path: Path, monkeypatch):
    handoff_path = tmp_path / "handoff.json"
    digest_json = tmp_path / "digest.json"
    digest_md = tmp_path / "digest.md"

    monkeypatch.setattr(
        "value_investor.project_traffic.DEFAULT_DIGEST_PATH",
        digest_json,
    )
    monkeypatch.setattr(
        "value_investor.project_traffic.DEFAULT_DIGEST_MARKDOWN_PATH",
        digest_md,
    )
    monkeypatch.setattr(
        "value_investor.project_traffic.remediate_queue_merge_sync",
        lambda **kwargs: (["eng-1"], ["eng-1"], [], []),
    )

    findings = [
        {
            "severity": "warn",
            "category": "engineering",
            "title": QUEUE_MERGE_SYNC_FINDING_TITLE,
            "summary": "lag",
            "fixed": False,
        },
        {
            "severity": "warn",
            "category": "ingest",
            "title": "Buy-tier filing ingest stalled",
            "summary": "zero bodies",
            "fixed": False,
        },
    ]
    payload = handoff_ops_monitor_email_to_pm(
        findings=findings,
        email_subject="FTSE Ops Monitor — WARN",
        email_text="body",
        email_html="<p>body</p>",
        drafted_task_ids=[],
        apply=True,
        handoff_path=handoff_path,
        update_digest=True,
    )
    assert handoff_path.exists()
    assert payload["email_subject"] == "FTSE Ops Monitor — WARN"
    assert payload["resolved_count"] == 1
    assert payload["open_count"] == 1
    assert any(row["planned_rectification"] == RECTIFICATION_QUEUE_SYNC for row in payload["items"])
    assert any(row["status"] == "open" for row in payload["items"])
    assert digest_json.exists()
    digest = digest_json.read_text(encoding="utf-8")
    assert "ops_email_handoff" in digest
    md = digest_md.read_text(encoding="utf-8")
    assert "Ops-monitor email handoff" in md
