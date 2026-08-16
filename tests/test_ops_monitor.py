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
    apply_auto_fixes,
    check_backtest_history,
    check_committed_json,
    check_engineering_queue,
    check_ingest_health_log,
    check_latest_bundle,
    check_workflow_freshness,
    draft_ops_engineering_tasks,
    filter_unresolved_workflow_failures,
    format_ops_monitor_text,
    recovery_bundle_in_flight,
    run_ops_monitor,
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
        overall="warn",
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
    assert "FIXED" in text
    assert "micro_compile_ingest" in text


@patch("value_investor.ops_monitor.list_open_pull_requests", return_value=[])
@patch("value_investor.ops_monitor.check_workflow_freshness", return_value=([], []))
@patch("value_investor.ops_monitor.check_ops_budget", return_value=[])
def test_run_ops_monitor_writes_status(
    _budget,
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
