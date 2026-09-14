"""Tests for operational health monitor."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from pinned_time import weekday_noon_utc

from value_investor.backtest import BENCHMARK_TICKER
from value_investor.engineering_tasks import load_engineering_tasks
from value_investor.ops_monitor import (
    MONITORED_WORKFLOWS,
    OpsFinding,
    OpsMonitorReport,
    _overall_status,
    apply_auto_fixes,
    check_backtest_history,
    check_committed_json,
    check_engineering_queue,
    check_ingest_health_log,
    check_latest_bundle,
    check_paper_learning_tracks,
    check_workflow_freshness,
    draft_ops_engineering_tasks,
    filter_unresolved_workflow_failures,
    findings_needing_investigation,
    format_ops_monitor_text,
    merge_healed_findings,
    recovery_bundle_in_flight,
    run_ops_monitor,
    send_ops_monitor_email,
    workflow_stale_only_failures,
)
from value_investor.storage import write_json


def test_check_workflow_freshness_engineering_queue_idle_uses_relaxed_threshold():
    eight_hours_ago = (weekday_noon_utc() - timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
    idle_queue = {
        "open_count": 0,
        "pr_open_count": 0,
        "in_flight_branch": None,
        "in_flight_pr": None,
    }
    with (
        patch("value_investor.ops_monitor._github_token", return_value="test-token"),
        patch(
            "value_investor.ops_monitor.latest_workflow_run",
            return_value={"id": 1, "created_at": eight_hours_ago},
        ),
        patch("value_investor.ops_monitor.active_workflow_runs", return_value=[]),
        patch("value_investor.ops_monitor.recent_workflow_failures", return_value=[]),
        patch("value_investor.ops_monitor.recovery_bundle_in_flight", return_value=(False, [])),
    ):
        findings, checks = check_workflow_freshness(queue_status=idle_queue, now=weekday_noon_utc())
    eng_checks = [row for row in checks if row["workflow"] == "engineering-queue.yml"]
    assert eng_checks and eng_checks[0]["max_age_hours"] == 26
    assert eng_checks[0]["stale"] is False
    assert not [row for row in findings if "Engineering Queue" in row.title]


def test_filter_unresolved_workflow_failures_ignores_pre_success_failures():
    success_at = weekday_noon_utc()
    older = (success_at - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    newer = (success_at + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    failures = [
        {"id": 1, "created_at": older},
        {"id": 2, "created_at": newer},
    ]
    unresolved = filter_unresolved_workflow_failures(failures, success_at)
    assert [row["id"] for row in unresolved] == [2]


def test_check_workflow_freshness_ignores_resolved_failures():
    success_at = weekday_noon_utc()
    one_hour_ago = (success_at - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    idle_queue = {
        "open_count": 0,
        "pr_open_count": 0,
        "in_flight_branch": None,
        "in_flight_pr": None,
    }
    with (
        patch("value_investor.ops_monitor._github_token", return_value="test-token"),
        patch(
            "value_investor.ops_monitor.latest_workflow_run",
            return_value={"id": 2, "created_at": success_at.strftime("%Y-%m-%dT%H:%M:%SZ")},
        ),
        patch(
            "value_investor.ops_monitor.recent_workflow_failures",
            return_value=[{"id": 1, "created_at": one_hour_ago}],
        ),
        patch("value_investor.ops_monitor.active_workflow_runs", return_value=[]),
        patch("value_investor.ops_monitor.recovery_bundle_in_flight", return_value=(False, [])),
    ):
        findings, checks = check_workflow_freshness(queue_status=idle_queue, now=success_at)
    assert not [row for row in findings if "workflow failure" in row.title.lower()]
    eng_checks = [row for row in checks if row["workflow"] == "engineering-queue.yml"]
    assert eng_checks[0]["unresolved_failures_12h"] == 0


def test_check_engineering_queue_skips_informational_parked(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "eng-20260726-05",
                        "area": "scoring",
                        "title": "Merged task",
                        "status": "merged",
                    },
                    {
                        "id": "eng-20260804-36",
                        "area": "scoring",
                        "title": "Duplicate task",
                        "status": "parked",
                        "parked_policy": "duplicate",
                        "duplicate_of": "eng-20260726-05",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    findings, _ = check_engineering_queue(tasks_path=tasks_path, open_prs=[])
    assert not [row for row in findings if row.title.startswith("Parked engineering")]


def test_check_workflow_freshness_engineering_queue_active_requires_hourly():
    eight_hours_ago = (weekday_noon_utc() - timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
    active_queue = {
        "open_count": 2,
        "pr_open_count": 0,
        "in_flight_branch": None,
        "in_flight_pr": None,
    }
    with (
        patch("value_investor.ops_monitor._github_token", return_value="test-token"),
        patch(
            "value_investor.ops_monitor.latest_workflow_run",
            return_value={"id": 1, "created_at": eight_hours_ago},
        ),
        patch("value_investor.ops_monitor.active_workflow_runs", return_value=[]),
        patch("value_investor.ops_monitor.recent_workflow_failures", return_value=[]),
        patch("value_investor.ops_monitor.recovery_bundle_in_flight", return_value=(False, [])),
    ):
        findings, checks = check_workflow_freshness(
            queue_status=active_queue, now=weekday_noon_utc()
        )
    eng_checks = [row for row in checks if row["workflow"] == "engineering-queue.yml"]
    assert eng_checks and eng_checks[0]["max_age_hours"] == 3
    assert eng_checks[0]["stale"] is True
    assert any("Engineering Queue" in row.title for row in findings)


def test_check_workflow_freshness_suppresses_ops_monitor_self_when_running_in_actions():
    thirty_hours_ago = (weekday_noon_utc() - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    idle_queue = {
        "open_count": 0,
        "pr_open_count": 0,
        "in_flight_branch": None,
        "in_flight_pr": None,
    }

    def fake_latest(workflow_file, **kwargs):
        if workflow_file == "ops-monitor.yml" and kwargs.get("status") == "success":
            return {"id": 1, "created_at": thirty_hours_ago}
        return {"id": 2, "created_at": weekday_noon_utc().strftime("%Y-%m-%dT%H:%M:%SZ")}

    with (
        patch("value_investor.ops_monitor._github_token", return_value="test-token"),
        patch("value_investor.ops_monitor.latest_workflow_run", side_effect=fake_latest),
        patch("value_investor.ops_monitor.recent_workflow_failures", return_value=[]),
        patch("value_investor.ops_monitor.recovery_bundle_in_flight", return_value=(False, [])),
        patch(
            "value_investor.ops_monitor._running_inside_ops_monitor_workflow",
            return_value=True,
        ),
    ):
        findings, checks = check_workflow_freshness(queue_status=idle_queue, now=weekday_noon_utc())

    ops_overdue = [row for row in findings if row.title == "Workflow overdue: FTSE Ops Monitor"]
    assert len(ops_overdue) == 1
    assert ops_overdue[0].fixed is True
    assert "self-check suppressed" in (ops_overdue[0].action_taken or "")
    assert _overall_status(findings) != "fail"
    ops_checks = [row for row in checks if row["workflow"] == "ops-monitor.yml"]
    assert ops_checks and ops_checks[0]["stale"] is True


def test_check_workflow_freshness_suppresses_ops_monitor_overdue_when_recovery_active():
    thirty_hours_ago = (weekday_noon_utc() - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    idle_queue = {
        "open_count": 0,
        "pr_open_count": 0,
        "in_flight_branch": None,
        "in_flight_pr": None,
    }

    def fake_latest(workflow_file, **kwargs):
        if workflow_file == "ops-monitor.yml" and kwargs.get("status") == "success":
            return {"id": 1, "created_at": thirty_hours_ago}
        return {"id": 2, "created_at": weekday_noon_utc().strftime("%Y-%m-%dT%H:%M:%SZ")}

    def fake_active(workflow_file, **kwargs):
        if workflow_file == "ops-monitor.yml":
            return [{"id": 34225171185, "status": "in_progress"}]
        return []

    with (
        patch("value_investor.ops_monitor._github_token", return_value="test-token"),
        patch("value_investor.ops_monitor.latest_workflow_run", side_effect=fake_latest),
        patch("value_investor.ops_monitor.active_workflow_runs", side_effect=fake_active),
        patch("value_investor.ops_monitor.recent_workflow_failures", return_value=[]),
        patch("value_investor.ops_monitor.recovery_bundle_in_flight", return_value=(False, [])),
        patch(
            "value_investor.ops_monitor._running_inside_ops_monitor_workflow",
            return_value=False,
        ),
    ):
        findings, _checks = check_workflow_freshness(
            queue_status=idle_queue, now=weekday_noon_utc()
        )

    ops_overdue = [row for row in findings if row.title == "Workflow overdue: FTSE Ops Monitor"]
    assert len(ops_overdue) == 1
    assert ops_overdue[0].fixed is True
    assert "Recovery run in flight" in (ops_overdue[0].action_taken or "")
    assert _overall_status(findings) != "fail"


def test_check_workflow_freshness_suppresses_ingest_overdue_when_run_in_flight():
    forty_hours_ago = (weekday_noon_utc() - timedelta(hours=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
    idle_queue = {
        "open_count": 0,
        "pr_open_count": 0,
        "in_flight_branch": None,
        "in_flight_pr": None,
    }

    def fake_latest(workflow_file, **kwargs):
        if workflow_file == "ingest-loop.yml" and kwargs.get("status") == "success":
            return {"id": 1, "created_at": forty_hours_ago}
        return {"id": 2, "created_at": weekday_noon_utc().strftime("%Y-%m-%dT%H:%M:%SZ")}

    def fake_active(workflow_file, **kwargs):
        if workflow_file == "ingest-loop.yml":
            return [{"id": 34816237004, "status": "in_progress"}]
        return []

    with (
        patch("value_investor.ops_monitor._github_token", return_value="test-token"),
        patch("value_investor.ops_monitor.latest_workflow_run", side_effect=fake_latest),
        patch("value_investor.ops_monitor.active_workflow_runs", side_effect=fake_active),
        patch("value_investor.ops_monitor.recent_workflow_failures", return_value=[]),
        patch("value_investor.ops_monitor.recovery_bundle_in_flight", return_value=(False, [])),
    ):
        findings, _checks = check_workflow_freshness(
            queue_status=idle_queue, now=weekday_noon_utc()
        )

    ingest_overdue = [row for row in findings if row.title == "Workflow overdue: FTSE Ingest Loop"]
    assert len(ingest_overdue) == 1
    assert ingest_overdue[0].fixed is True
    assert "Recovery run in flight" in (ingest_overdue[0].action_taken or "")
    assert _overall_status(findings) != "fail"


def test_check_workflow_freshness_suppresses_overdue_before_email_ready_slot():
    """Monday morning cliff: weekend age exceeds max_age before primary cron finishes."""
    monday_morning = datetime(2026, 9, 14, 7, 46, tzinfo=UTC)
    friday_success = datetime(2026, 9, 11, 8, 26, tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    idle_queue = {
        "open_count": 0,
        "pr_open_count": 0,
        "in_flight_branch": None,
        "in_flight_pr": None,
    }

    def fake_latest(workflow_file, **kwargs):
        if workflow_file in {"ingest-loop.yml", "paper-auto.yml"} and kwargs.get("status") == "success":
            return {"id": 1, "created_at": friday_success}
        return {"id": 2, "created_at": monday_morning.strftime("%Y-%m-%dT%H:%M:%SZ")}

    with (
        patch("value_investor.ops_monitor._github_token", return_value="test-token"),
        patch("value_investor.ops_monitor.latest_workflow_run", side_effect=fake_latest),
        patch("value_investor.ops_monitor.active_workflow_runs", return_value=[]),
        patch("value_investor.ops_monitor.recent_workflow_failures", return_value=[]),
        patch("value_investor.ops_monitor.recovery_bundle_in_flight", return_value=(False, [])),
    ):
        findings, _checks = check_workflow_freshness(queue_status=idle_queue, now=monday_morning)

    overdue = [
        row
        for row in findings
        if row.title
        in {
            "Workflow overdue: FTSE Ingest Loop",
            "Workflow overdue: FTSE Paper Automation",
        }
    ]
    assert len(overdue) == 2
    assert all(row.fixed for row in overdue)
    assert all("Scheduled slot not reached yet" in (row.action_taken or "") for row in overdue)
    assert _overall_status(findings) != "fail"


def test_check_workflow_freshness_marks_ingest_paper_overdue_auto_fixable_past_ready():
    forty_hours_ago = (weekday_noon_utc() - timedelta(hours=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
    idle_queue = {
        "open_count": 0,
        "pr_open_count": 0,
        "in_flight_branch": None,
        "in_flight_pr": None,
    }

    def fake_latest(workflow_file, **kwargs):
        if workflow_file in {"ingest-loop.yml", "paper-auto.yml"} and kwargs.get("status") == "success":
            return {"id": 1, "created_at": forty_hours_ago}
        return {"id": 2, "created_at": weekday_noon_utc().strftime("%Y-%m-%dT%H:%M:%SZ")}

    with (
        patch("value_investor.ops_monitor._github_token", return_value="test-token"),
        patch("value_investor.ops_monitor.latest_workflow_run", side_effect=fake_latest),
        patch("value_investor.ops_monitor.active_workflow_runs", return_value=[]),
        patch("value_investor.ops_monitor.recent_workflow_failures", return_value=[]),
        patch("value_investor.ops_monitor.recovery_bundle_in_flight", return_value=(False, [])),
    ):
        findings, _checks = check_workflow_freshness(
            queue_status=idle_queue, now=weekday_noon_utc()
        )

    ingest = next(row for row in findings if row.title == "Workflow overdue: FTSE Ingest Loop")
    paper = next(row for row in findings if row.title == "Workflow overdue: FTSE Paper Automation")
    assert ingest.auto_fixable is True and ingest.fixed is False
    assert paper.auto_fixable is True and paper.fixed is False


def test_apply_auto_fixes_dispatches_overdue_ingest_and_paper():
    findings = [
        OpsFinding(
            severity="fail",
            category="workflows",
            title="Workflow overdue: FTSE Ingest Loop",
            summary="No successful run within 30h.",
            auto_fixable=True,
        ),
        OpsFinding(
            severity="fail",
            category="workflows",
            title="Workflow overdue: FTSE Paper Automation",
            summary="No successful run within 28h.",
            auto_fixable=True,
        ),
    ]
    dispatched: list[str] = []

    def fake_dispatch(workflow_file, **kwargs):
        dispatched.append(workflow_file)

    with (
        patch("value_investor.ops_monitor.active_workflow_runs", return_value=[]),
        patch("value_investor.ops_monitor.dispatch_workflow", side_effect=fake_dispatch),
    ):
        fixes = apply_auto_fixes(findings, apply=True)

    assert dispatched == ["ingest-loop.yml", "paper-auto.yml"]
    assert {row["action"] for row in fixes} == {"dispatch_overdue_workflow"}
    assert all(row.fixed for row in findings)
    assert all("dispatched" in (row.action_taken or "") for row in findings)


def test_apply_auto_fixes_dispatch_failure_leaves_supervised():
    findings = [
        OpsFinding(
            severity="fail",
            category="workflows",
            title="Workflow overdue: FTSE Ingest Loop",
            summary="No successful run within 30h.",
            auto_fixable=True,
        )
    ]
    with (
        patch("value_investor.ops_monitor.active_workflow_runs", return_value=[]),
        patch(
            "value_investor.ops_monitor.dispatch_workflow",
            side_effect=RuntimeError("403 Workflows permission"),
        ),
    ):
        fixes = apply_auto_fixes(findings, apply=True)

    assert fixes == []
    assert findings[0].fixed is False
    assert findings[0].auto_fixable is False
    assert "auto-dispatch failed" in (findings[0].action_taken or "")


def test_ops_monitor_cli_email_failure_still_exits_zero_when_stale_only():
    from value_investor.ops_monitor_cli import main

    with patch("value_investor.ops_monitor_cli.run_ops_monitor") as mock_run:
        mock_run.return_value = OpsMonitorReport(
            run_at="2026-09-08T07:45:00+00:00",
            overall="fail",
            findings=[
                OpsFinding(
                    severity="fail",
                    category="workflows",
                    title="Workflow overdue: FTSE Ops Monitor",
                    summary="No successful run within 28h.",
                )
            ],
        )
        with patch("value_investor.ops_monitor_cli.append_monitor_log_entry"):
            with patch(
                "value_investor.ops_monitor_cli.send_ops_monitor_email",
                side_effect=ValueError("Missing required email env vars: SMTP_HOST"),
            ):
                rc = main(
                    [
                        "run",
                        "--json",
                        "--no-apply",
                        "--no-draft",
                        "--email",
                        "--allow-workflow-stale-exit-zero",
                    ]
                )
    assert rc == 0


def test_check_workflow_freshness_softens_orchestrator_when_recovery_bundle_active():
    thirty_hours_ago = (weekday_noon_utc() - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    idle_queue = {
        "open_count": 0,
        "pr_open_count": 0,
        "in_flight_branch": None,
        "in_flight_pr": None,
    }

    def fake_latest(workflow_file, **kwargs):
        if workflow_file == "automation-orchestrator.yml" and kwargs.get("status") == "success":
            return {"id": 99, "created_at": thirty_hours_ago}
        return None

    def fake_active(workflow_file, **kwargs):
        if workflow_file == "automation-orchestrator.yml":
            return [{"id": 100, "status": "in_progress"}]
        return []

    with (
        patch("value_investor.ops_monitor._github_token", return_value="test-token"),
        patch("value_investor.ops_monitor.latest_workflow_run", side_effect=fake_latest),
        patch("value_investor.ops_monitor.active_workflow_runs", side_effect=fake_active),
        patch("value_investor.ops_monitor.recent_workflow_failures", return_value=[]),
    ):
        findings, checks = check_workflow_freshness(queue_status=idle_queue, now=weekday_noon_utc())

    orch = [row for row in findings if "Automation Orchestrator" in row.title]
    assert orch and orch[0].severity == "warn"
    assert "Recovery bundle in flight" in orch[0].summary
    orch_checks = [row for row in checks if row["workflow"] == "automation-orchestrator.yml"]
    assert orch_checks and orch_checks[0]["stale"] is True


def test_recovery_bundle_in_flight_detects_active_orchestrator():
    with (
        patch("value_investor.ops_monitor._github_token", return_value="test-token"),
        patch(
            "value_investor.ops_monitor.active_workflow_runs",
            side_effect=lambda wf, **kw: [{"id": 1}] if wf == "automation-orchestrator.yml" else [],
        ),
    ):
        active, labels = recovery_bundle_in_flight()
    assert active is True
    assert any("automation-orchestrator.yml" in label for label in labels)


def test_workflow_stale_only_failures_true_for_overdue_only():
    findings = [
        OpsFinding(
            severity="fail",
            category="workflows",
            title="Workflow overdue: Automation Orchestrator",
            summary="No successful run within 28h.",
        )
    ]
    assert workflow_stale_only_failures(findings) is True


def test_workflow_stale_only_failures_false_when_other_failures_present():
    findings = [
        OpsFinding(
            severity="fail",
            category="workflows",
            title="Workflow overdue: Automation Orchestrator",
            summary="stale",
        ),
        OpsFinding(
            severity="fail",
            category="dashboard",
            title="Published dashboard bundle missing",
            summary="missing",
        ),
    ]
    assert workflow_stale_only_failures(findings) is False


def test_ops_monitor_cli_exit_zero_when_only_workflow_stale_fail():
    from value_investor.ops_monitor_cli import main

    with patch("value_investor.ops_monitor_cli.run_ops_monitor") as mock_run:
        mock_run.return_value = OpsMonitorReport(
            run_at="2026-07-29T00:00:00+00:00",
            overall="fail",
            findings=[
                OpsFinding(
                    severity="fail",
                    category="workflows",
                    title="Workflow overdue: Automation Orchestrator",
                    summary="stale",
                )
            ],
        )
        with patch("value_investor.ops_monitor_cli.append_monitor_log_entry"):
            rc = main(
                ["run", "--json", "--no-apply", "--no-draft", "--allow-workflow-stale-exit-zero"]
            )
    assert rc == 0


def test_check_committed_json_flags_corrupt_file(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text("{broken", encoding="utf-8")
    findings = check_committed_json([path])
    assert len(findings) == 1
    assert findings[0].severity == "fail"


def test_check_latest_bundle_warns_when_stale(tmp_path: Path):
    latest = tmp_path / "latest.json"
    old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    latest.write_text(json.dumps({"updated_at": old, "reports": []}), encoding="utf-8")
    findings = check_latest_bundle(latest, max_age_hours=24)
    assert findings and findings[0].title == "Dashboard bundle is stale"


def _history_snapshot() -> dict:
    signals = [
        {
            "ticker": f"AAA{i}.L",
            "signal": "buy",
            "conviction_score": 0.5,
            "data_quality_score": 0.9,
        }
        for i in range(60)
    ]
    prices = {row["ticker"]: 100.0 + i for i, row in enumerate(signals)}
    prices[BENCHMARK_TICKER] = 8000.0
    return {"run_at": "2026-08-02T12:34:17+00:00", "prices": prices, "signals": signals}


def test_check_backtest_history_warns_when_seeding(tmp_path: Path):
    history = tmp_path / "history"
    history.mkdir()
    write_json(history / "run_20260802_123417.json.gz", _history_snapshot(), compress=True)

    findings = check_backtest_history(history)

    seeding = [row for row in findings if row.title == "Backtest history still seeding"]
    assert len(seeding) == 1
    assert seeding[0].severity == "warn"
    assert seeding[0].category == "backtest"


def test_check_backtest_history_flags_corrupt_snapshot(tmp_path: Path):
    history = tmp_path / "history"
    history.mkdir()
    (history / "run_20260802_123417.json.gz").write_bytes(b"{broken")

    findings = check_backtest_history(history)

    corrupt = [row for row in findings if row.title.startswith("Backtest history: corrupt_json")]
    assert len(corrupt) == 1
    assert corrupt[0].severity == "fail"
    assert corrupt[0].auto_fixable is True


def test_apply_auto_fixes_quarantines_corrupt_backtest_history(tmp_path: Path):
    history = tmp_path / "history"
    history.mkdir()
    bad = history / "run_20260802_123417.json.gz"
    bad.write_bytes(b"{broken")
    findings = check_backtest_history(history)
    with patch("value_investor.ops_monitor.COMMITTED_HISTORY_DIR", history):
        fixes = apply_auto_fixes(findings, apply=True)
    assert fixes
    assert not bad.exists()
    assert list((history / "quarantine").glob("*run_20260802_123417.json.gz"))
    assert all(row.fixed for row in findings if row.category == "backtest" and row.auto_fixable)


def test_apply_auto_fixes_marks_orphan_fixed_when_pr_merged(tmp_path: Path):
    from value_investor.engineering_recovery import RecoveryResult

    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(json.dumps({"tasks": []}), encoding="utf-8")
    findings = [
        OpsFinding(
            severity="warn",
            category="engineering",
            title="Orphaned pr_open engineering tasks",
            summary="eng-20260912-08",
            auto_fixable=True,
        )
    ]
    with patch(
        "value_investor.ops_monitor.recover_engineering_queue",
        return_value=RecoveryResult(merged=["eng-20260912-08"]),
    ):
        fixes = apply_auto_fixes(findings, tasks_path=tasks_path, open_prs=[], apply=True)
    assert fixes
    assert findings[0].fixed
    assert "marked merged" in (findings[0].action_taken or "")


def test_apply_auto_fixes_reconciles_orphan_pr_open(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "id": "eng-20260729-01",
                        "area": "ingest",
                        "title": "Fix fetch",
                        "summary": "x",
                        "priority": "high",
                        "priority_score": 50.0,
                        "source": "ops_monitor",
                        "status": "pr_open",
                        "branch_name": "cursor/eng-20260729-01-1de3",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    findings = [
        OpsFinding(
            severity="warn",
            category="engineering",
            title="Orphaned pr_open engineering tasks",
            summary="eng-20260729-01",
            auto_fixable=True,
        )
    ]
    with (
        patch("value_investor.ops_monitor.active_workflow_runs", return_value=[]),
        patch("value_investor.engineering_recovery._github_token", return_value=None),
        patch("value_investor.engineering_recovery._github_repo", return_value=None),
    ):
        fixes = apply_auto_fixes(findings, tasks_path=tasks_path, open_prs=[], apply=True)
    assert fixes
    payload = load_engineering_tasks(tasks_path)
    assert payload["tasks"][0]["status"] == "open"


def test_draft_ops_engineering_tasks_appends_open_ops_task(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(json.dumps({"tasks": []}), encoding="utf-8")
    findings = [
        OpsFinding(
            severity="fail",
            category="workflows",
            title="Workflow overdue: FTSE Ingest Loop",
            summary="No successful run within 30h.",
        )
    ]
    ids = draft_ops_engineering_tasks(findings, tasks_path=tasks_path)
    assert len(ids) == 1
    payload = load_engineering_tasks(tasks_path)
    assert payload["tasks"][0]["area"] == "ops"
    assert payload["tasks"][0]["source"] == "ops_monitor"


def test_format_ops_monitor_text_includes_findings():
    report = OpsMonitorReport(
        run_at="2026-07-29T07:00:00+00:00",
        overall="ok",
        findings=[
            OpsFinding(
                severity="warn",
                category="ingest",
                title="Buy-tier filing ingest stalled",
                summary="zero_body unchanged",
                fixed=True,
                action_taken="micro-compiled ingest tasks: eng-20260729-02",
            )
        ],
        auto_fixes=[{"action": "micro_compile_ingest", "detail": "eng-20260729-02"}],
    )
    text = format_ops_monitor_text(report)
    assert "FTSE Ops Monitor" in text
    assert "HEALED" in text
    assert "FIXED" in text
    assert "micro_compile_ingest" in text
    assert "NEEDS INVESTIGATION" not in text


def test_overall_status_ignores_fixed_findings():
    findings = [
        OpsFinding(
            severity="fail",
            category="ingest",
            title="Ingest health log is corrupt",
            summary="bad json",
            fixed=True,
            action_taken="normalized",
        )
    ]
    assert _overall_status(findings) == "ok"
    assert findings_needing_investigation(findings) == []


def test_merge_healed_findings_keeps_audit_trail():
    before = [
        OpsFinding(
            severity="fail",
            category="ingest",
            title="Ingest health log is corrupt",
            summary="bad",
            fixed=True,
            action_taken="normalized",
        ),
        OpsFinding(
            severity="warn",
            category="dashboard",
            title="Dashboard bundle is stale",
            summary="old",
        ),
    ]
    after = [
        OpsFinding(
            severity="warn",
            category="dashboard",
            title="Dashboard bundle is stale",
            summary="old",
        )
    ]
    merged = merge_healed_findings(before, after)
    assert len(merged) == 2
    assert merged[0].title == "Dashboard bundle is stale"
    assert merged[1].fixed is True
    assert _overall_status(merged) == "warn"


def test_send_ops_monitor_email_skips_when_only_healed(monkeypatch):
    sent: list[str] = []

    def _fake_send(**kwargs):
        sent.append(kwargs["subject"])

    monkeypatch.setattr("value_investor.ops_monitor.send_report_email", _fake_send)
    monkeypatch.setattr(
        "value_investor.ops_monitor.EmailConfig.from_env",
        lambda: object(),
    )
    report = OpsMonitorReport(
        run_at="2026-07-29T07:00:00+00:00",
        overall="ok",
        findings=[
            OpsFinding(
                severity="fail",
                category="ingest",
                title="Ingest health log is corrupt",
                summary="bad",
                fixed=True,
            )
        ],
        auto_fixes=[{"action": "repair_health_log", "detail": "normalized"}],
    )
    assert send_ops_monitor_email(report, only_if_not_ok=True) is False
    assert sent == []


def test_send_ops_monitor_email_sends_for_unfixed(monkeypatch):
    sent: list[str] = []

    def _fake_send(**kwargs):
        sent.append(kwargs["subject"])

    monkeypatch.setattr("value_investor.ops_monitor.send_report_email", _fake_send)
    monkeypatch.setattr(
        "value_investor.ops_monitor.EmailConfig.from_env",
        lambda: object(),
    )
    report = OpsMonitorReport(
        run_at="2026-07-29T07:00:00+00:00",
        overall="fail",
        findings=[
            OpsFinding(
                severity="fail",
                category="workflows",
                title="Workflow overdue: FTSE Ingest Loop",
                summary="stale",
            )
        ],
    )
    assert send_ops_monitor_email(report, only_if_not_ok=True) is True
    assert sent == ["FTSE Ops Monitor — FAIL"]


def test_check_workflow_freshness_suppresses_failure_when_recovery_in_flight():
    success_at = weekday_noon_utc() - timedelta(hours=2)
    failure_at = (weekday_noon_utc() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    idle_queue = {
        "open_count": 0,
        "pr_open_count": 0,
        "in_flight_branch": None,
        "in_flight_pr": None,
    }

    def _latest(workflow, **_kwargs):
        return {
            "id": 10,
            "created_at": success_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def _failures(workflow, **_kwargs):
        return [{"id": 99, "created_at": failure_at}]

    def _active(workflow, **_kwargs):
        return [{"id": 100, "status": "in_progress"}]

    with (
        patch("value_investor.ops_monitor._github_token", return_value="test-token"),
        patch("value_investor.ops_monitor.latest_workflow_run", side_effect=_latest),
        patch("value_investor.ops_monitor.recent_workflow_failures", side_effect=_failures),
        patch("value_investor.ops_monitor.active_workflow_runs", side_effect=_active),
        patch("value_investor.ops_monitor.recovery_bundle_in_flight", return_value=(False, [])),
    ):
        findings, _checks = check_workflow_freshness(
            queue_status=idle_queue, now=weekday_noon_utc()
        )
    failure_rows = [row for row in findings if "workflow failure" in row.title.lower()]
    assert failure_rows
    assert all(row.fixed for row in failure_rows)
    assert _overall_status(findings) != "fail" or not any(
        row.severity == "fail" and not row.fixed for row in failure_rows
    )


@patch("value_investor.ops_monitor.list_open_pull_requests", return_value=[])
@patch("value_investor.ops_monitor.check_workflow_freshness", return_value=([], []))
@patch("value_investor.ops_monitor.check_memo_rememo_backlog", return_value=[])
@patch("value_investor.ops_monitor.check_ops_budget", return_value=[])
@patch("value_investor.ops_monitor.check_paper_learning_tracks", return_value=[])
def test_run_ops_monitor_reverifies_after_health_log_repair(
    _paper,
    _budget,
    _rememo,
    _workflows,
    _prs,
    tmp_path: Path,
):
    latest = tmp_path / "latest.json"
    latest.write_text(
        json.dumps(
            {"updated_at": datetime.now(UTC).isoformat(), "reports": [{"ticker": "BT-A.L"}]}
        ),
        encoding="utf-8",
    )
    health = tmp_path / "ingest_health_log.json"
    health.write_text("{not-json", encoding="utf-8")
    tasks = tmp_path / "engineering_tasks.json"
    tasks.write_text(json.dumps({"tasks": []}), encoding="utf-8")
    status_path = tmp_path / "ops_status.json"

    with (
        patch("value_investor.ops_monitor.COMMITTED_TASKS_PATH", tasks),
        patch("value_investor.ops_monitor.recent_workflow_failures", return_value=[]),
        patch(
            "value_investor.ops_monitor.check_engineering_sync",
            return_value=([], type("R", (), {"repairs": [], "should_redispatch": False})()),
        ),
        patch(
            "value_investor.ops_monitor.run_engineering_sync",
            return_value=type("R", (), {"repairs": [], "should_redispatch": False})(),
        ),
        patch(
            "value_investor.ops_monitor.evaluate_engineering_dispatch",
            return_value=type("D", (), {"should_dispatch": False})(),
        ),
        patch("value_investor.ops_monitor.check_committed_json", return_value=[]),
        patch("value_investor.ops_monitor.check_backtest_history", return_value=[]),
        patch("value_investor.ops_monitor.check_latest_bundle", return_value=[]),
        patch(
            "value_investor.ops_monitor.check_engineering_queue",
            return_value=([], {"open_count": 0, "pr_open_count": 0}),
        ),
        patch("value_investor.backtest_health.run_backtest_health", return_value=None),
    ):
        report = run_ops_monitor(
            latest_path=latest,
            health_log_path=health,
            tasks_path=tasks,
            status_path=status_path,
            apply_fixes=True,
            draft_tasks=False,
        )

    assert report.auto_fixes
    needs = findings_needing_investigation(report.findings)
    assert not any(row.severity == "fail" for row in needs)
    assert any(row.fixed and "corrupt" in row.title.lower() for row in report.findings)
    # Re-verify replaces the corrupt fail with post-repair truth (thin history warn).
    assert any("thin history" in row.title.lower() for row in needs) or report.overall == "ok"
    assert json.loads(health.read_text(encoding="utf-8")).get("entries") == []


@patch("value_investor.ops_monitor.list_open_pull_requests", return_value=[])
@patch("value_investor.ops_monitor.check_workflow_freshness", return_value=([], []))
@patch("value_investor.ops_monitor.check_memo_rememo_backlog", return_value=[])
@patch("value_investor.ops_monitor.check_ops_budget", return_value=[])
@patch("value_investor.ops_monitor.check_paper_learning_tracks", return_value=[])
def test_run_ops_monitor_writes_status(
    _paper,
    _budget,
    _rememo,
    _workflows,
    _prs,
    tmp_path: Path,
):
    latest = tmp_path / "latest.json"
    latest.write_text(
        json.dumps(
            {"updated_at": datetime.now(UTC).isoformat(), "reports": [{"ticker": "BT-A.L"}]}
        ),
        encoding="utf-8",
    )
    health = tmp_path / "ingest_health_log.json"
    health.write_text(
        json.dumps({"entries": [], "updated_at": datetime.now(UTC).isoformat()}), encoding="utf-8"
    )
    status_path = tmp_path / "ops_status.json"

    report = run_ops_monitor(
        latest_path=latest,
        health_log_path=health,
        status_path=status_path,
        apply_fixes=False,
        draft_tasks=False,
    )
    assert status_path.exists()
    assert report.overall in {"ok", "warn", "fail"}


def test_restored_health_log_passes_ingest_checks():
    findings = check_ingest_health_log(Path("docs/data/ingest_health_log.json"))
    corrupt = [row for row in findings if row.title == "Ingest health log is corrupt"]
    assert not corrupt


def test_check_ingest_health_log_warns_on_runtime_cutoff(tmp_path: Path):
    health = tmp_path / "ingest_health_log.json"
    health.write_text(
        json.dumps(
            {
                "entries": [
                    {"run_at": "2026-08-10T07:00:00+00:00", "targets_deferred": 0},
                    {
                        "run_at": "2026-08-11T07:34:00+00:00",
                        "runtime_cutoff": True,
                        "targets_deferred": 7,
                        "targets_completed": 5,
                        "cutoff_reason": "per_ticker_budget",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    findings = check_ingest_health_log(health)
    cutoff = [row for row in findings if row.title == "Ingest loop hit runtime cutoff"]
    assert len(cutoff) == 1
    assert "7 ticker" in cutoff[0].summary


def test_ops_monitor_cli_accepts_run_json_after_subcommand():
    from value_investor.ops_monitor_cli import main

    with patch("value_investor.ops_monitor_cli.run_ops_monitor") as mock_run:
        mock_run.return_value = OpsMonitorReport(
            run_at="2026-07-29T00:00:00+00:00",
            overall="ok",
        )
        with patch("value_investor.ops_monitor_cli.append_monitor_log_entry"):
            rc = main(["run", "--json", "--no-apply", "--no-draft"])
    assert rc == 0


def test_monitored_workflows_include_library_ladder():
    ladder = next(row for row in MONITORED_WORKFLOWS if row["key"] == "library_ladder")
    assert ladder["workflow"] == "library-grow.yml"
    assert ladder["weekdays"] == {6}
    assert ladder["max_age_hours"] == 36


def test_monitored_workflows_include_safe_extensions():
    keys = {row["key"] for row in MONITORED_WORKFLOWS}
    assert {
        "model_review",
        "email_report",
        "data_backup",
        "paper_auto",
        "ops_monitor",
    } <= keys
    sunday = {row["key"] for row in MONITORED_WORKFLOWS if row["weekdays"] == {6}}
    assert {"model_review", "email_report", "data_backup"} <= sunday
    paper = next(row for row in MONITORED_WORKFLOWS if row["key"] == "paper_auto")
    assert paper["weekdays"] == {0, 1, 2, 3, 4}
    assert paper["max_age_hours"] == 28


def _sunday_morning_checks() -> list[dict]:
    return [
        {
            "workflow": "analysis-review.yml",
            "name": "Modelling analysis review",
            "expected_today": True,
            "stale": True,
            "last_success_at": "2026-08-23T10:35:11+00:00",
        },
        {
            "workflow": "data-backup.yml",
            "name": "FTSE Data Backup",
            "expected_today": True,
            "stale": True,
            "last_success_at": "2026-08-23T13:06:48+00:00",
        },
        {
            "workflow": "email-report.yml",
            "name": "Email report",
            "expected_today": True,
            "stale": True,
            "last_success_at": "2026-08-23T06:21:15+00:00",
        },
    ]


def test_evaluate_email_deferral_sunday_morning_pre_slot():
    from value_investor.ops_monitor import evaluate_email_deferral

    now = datetime(2026, 8, 30, 7, 46, tzinfo=UTC)  # Sunday 07:46
    findings = [
        OpsFinding(
            severity="fail",
            category="workflows",
            title="Workflow overdue: Modelling analysis review",
            summary="No successful run within 36h.",
        ),
        OpsFinding(
            severity="fail",
            category="workflows",
            title="Workflow overdue: FTSE Data Backup",
            summary="No successful run within 36h.",
        ),
        OpsFinding(
            severity="warn",
            category="workflows",
            title="Workflow overdue: Email report",
            summary="No successful run within 36h. Recovery bundle in flight (email-report.yml#1).",
        ),
        OpsFinding(
            severity="warn",
            category="dashboard",
            title="Dashboard bundle is stale",
            summary="latest.json updated 2026-08-23T06:22:09+00:00",
        ),
    ]
    deferred, reasons = evaluate_email_deferral(findings, _sunday_morning_checks(), now=now)
    assert deferred is True
    assert len(reasons) >= 3


def test_evaluate_email_deferral_after_slots_is_actionable():
    from value_investor.ops_monitor import evaluate_email_deferral

    now = datetime(2026, 8, 30, 13, 30, tzinfo=UTC)  # after data-backup ready
    findings = [
        OpsFinding(
            severity="fail",
            category="workflows",
            title="Workflow overdue: FTSE Data Backup",
            summary="No successful run within 36h.",
        ),
    ]
    deferred, reasons = evaluate_email_deferral(findings, _sunday_morning_checks(), now=now)
    assert deferred is False
    assert reasons == []


def test_send_ops_monitor_email_skips_when_deferred(monkeypatch):
    sent: list[str] = []

    def _fake_send(**kwargs):
        sent.append(kwargs["subject"])

    monkeypatch.setattr("value_investor.ops_monitor.send_report_email", _fake_send)
    monkeypatch.setattr(
        "value_investor.ops_monitor.EmailConfig.from_env",
        lambda: object(),
    )
    report = OpsMonitorReport(
        run_at="2026-08-30T07:46:00+00:00",
        overall="fail",
        findings=[
            OpsFinding(
                severity="fail",
                category="workflows",
                title="Workflow overdue: Modelling analysis review",
                summary="stale",
            )
        ],
        email_deferred=True,
        email_defer_reasons=["Modelling analysis review: scheduled slot not reached yet"],
    )
    assert send_ops_monitor_email(report, only_if_not_ok=True) is False
    assert sent == []


def test_ops_monitor_cli_exit_zero_when_email_deferred():
    from value_investor.ops_monitor_cli import main

    with patch("value_investor.ops_monitor_cli.run_ops_monitor") as mock_run:
        mock_run.return_value = OpsMonitorReport(
            run_at="2026-08-30T07:46:00+00:00",
            overall="fail",
            findings=[
                OpsFinding(
                    severity="fail",
                    category="workflows",
                    title="Workflow overdue: Modelling analysis review",
                    summary="stale",
                )
            ],
            email_deferred=True,
            email_defer_reasons=["pre-slot"],
        )
        with patch("value_investor.ops_monitor_cli.append_monitor_log_entry"):
            with patch("value_investor.ops_monitor_cli.send_ops_monitor_email") as mock_email:
                mock_email.return_value = False
                rc = main(["run", "--json", "--email", "--allow-workflow-stale-exit-zero"])
    assert rc == 0


_CORE_TRACK_IDS = ("rules", "ai_judgment", "buy_tier_level")


def _track_row(*, acted: bool = True) -> dict:
    return {"acted": acted, "trades": 1, "note": "ok"}


def _write_paper_learning_root(
    tmp_path: Path,
    *,
    after_settle: bool = True,
    acted: bool = True,
    holdings: bool = True,
    include_shadow: bool = True,
    shadow_in_review: bool = True,
    omit_review_tracks: tuple[str, ...] = (),
    omit_summary_tracks: tuple[str, ...] = (),
    omit_review: bool = False,
) -> Path:
    paper = tmp_path / "paper_automation"
    paper.mkdir()
    (paper / "last_run.json").write_text(
        json.dumps(
            {
                "acted": acted,
                "gate": {"after_settle": after_settle, "can_act": after_settle},
                "generated_at": "2026-09-11T08:30:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    tracks = {track_id: _track_row(acted=acted) for track_id in _CORE_TRACK_IDS}
    for track_id in omit_summary_tracks:
        tracks.pop(track_id, None)
    if include_shadow:
        tracks["ai_judgment_calibrated"] = _track_row(acted=True)
        shadow_dir = paper / "ai_judgment_calibrated"
        shadow_dir.mkdir()
        (shadow_dir / "config.json").write_text("{}", encoding="utf-8")
    (paper / "learning_tracks_summary.json").write_text(
        json.dumps({"tracks": tracks}),
        encoding="utf-8",
    )
    if not omit_review:
        reviews = {track_id: {"metrics": {"excess_after_costs": -0.28}} for track_id in tracks}
        if include_shadow and not shadow_in_review:
            reviews.pop("ai_judgment_calibrated", None)
        for track_id in omit_review_tracks:
            reviews.pop(track_id, None)
        (paper / "learning_tracks_review.json").write_text(
            json.dumps(
                {
                    "reviews": reviews,
                    "beat_market": False,
                    "beat_control": True,
                    "verdict": "underperforming",
                }
            ),
            encoding="utf-8",
        )
    buy_dir = paper / "buy_tier_level"
    buy_dir.mkdir()
    fund_holdings = {"FOO.L": {"ticker": "FOO.L"}} if holdings else {}
    (buy_dir / "automated_fund.json").write_text(
        json.dumps({"cash": 0.0 if holdings else 1000.0, "holdings": fund_holdings}),
        encoding="utf-8",
    )
    return paper


def test_check_paper_learning_tracks_healthy_ignores_underperforming_excess(tmp_path: Path):
    paper = _write_paper_learning_root(tmp_path)
    assert check_paper_learning_tracks(paper) == []


def test_check_paper_learning_tracks_flags_missing_review(tmp_path: Path):
    paper = _write_paper_learning_root(tmp_path, omit_review=True)
    titles = [row.title for row in check_paper_learning_tracks(paper)]
    assert "Learning-tracks review missing" in titles


def test_check_paper_learning_tracks_flags_missing_core_review_track(tmp_path: Path):
    paper = _write_paper_learning_root(tmp_path, omit_review_tracks=("ai_judgment",))
    titles = [row.title for row in check_paper_learning_tracks(paper)]
    assert "Learning-tracks review missing core tracks" in titles


def test_check_paper_learning_tracks_flags_shadow_omitted_from_review(tmp_path: Path):
    paper = _write_paper_learning_root(tmp_path, shadow_in_review=False)
    titles = [row.title for row in check_paper_learning_tracks(paper)]
    assert "Calibrated shadows missing from decision-review" in titles


def test_check_paper_learning_tracks_flags_empty_buy_tier_level(tmp_path: Path):
    paper = _write_paper_learning_root(tmp_path, holdings=False)
    titles = [row.title for row in check_paper_learning_tracks(paper)]
    assert "Buy-tier level cohort empty after acted pass" in titles


def test_check_paper_learning_tracks_warns_on_pre_settle_last_run(tmp_path: Path):
    paper = _write_paper_learning_root(tmp_path, after_settle=False)
    findings = check_paper_learning_tracks(paper)
    assert any(row.title == "Paper-auto last_run is pre-settle only" for row in findings)


def test_check_paper_learning_tracks_warns_when_root_missing(tmp_path: Path):
    findings = check_paper_learning_tracks(tmp_path / "missing")
    assert findings[0].title == "Paper automation root missing"


def test_paper_learning_findings_defer_before_paper_auto_ready():
    from value_investor.ops_monitor import finding_email_defer_reason

    finding = OpsFinding(
        severity="fail",
        category="paper",
        title="Learning-tracks review missing",
        summary="missing",
    )
    morning = datetime(2026, 9, 11, 7, 45, tzinfo=UTC)  # Friday before 10:00
    reason = finding_email_defer_reason(finding, workflow_checks=[], now=morning)
    assert reason is not None
    assert "10:00" in reason
    afternoon = datetime(2026, 9, 11, 13, 15, tzinfo=UTC)
    assert finding_email_defer_reason(finding, workflow_checks=[], now=afternoon) is None


def test_committed_paper_learning_tracks_are_complete():
    assert check_paper_learning_tracks() == []
