"""Tests for operational health monitor."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from value_investor.engineering_tasks import EngineeringTask, load_engineering_tasks
from value_investor.ops_monitor import (
    OpsFinding,
    OpsMonitorReport,
    apply_auto_fixes,
    check_committed_json,
    check_ingest_health_log,
    check_latest_bundle,
    check_workflow_freshness,
    draft_ops_engineering_tasks,
    format_ops_monitor_text,
    load_health_log_payload,
    run_ops_monitor,
)


def test_check_workflow_freshness_engineering_queue_idle_uses_relaxed_threshold():
    eight_hours_ago = (datetime.now(UTC) - timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
    idle_queue = {"open_count": 0, "pr_open_count": 0, "in_flight_branch": None, "in_flight_pr": None}
    with (
        patch("value_investor.ops_monitor._github_token", return_value="test-token"),
        patch(
            "value_investor.ops_monitor.latest_workflow_run",
            return_value={"id": 1, "created_at": eight_hours_ago},
        ),
        patch("value_investor.ops_monitor.recent_workflow_failures", return_value=[]),
    ):
        findings, checks = check_workflow_freshness(queue_status=idle_queue)
    eng_checks = [row for row in checks if row["workflow"] == "engineering-queue.yml"]
    assert eng_checks and eng_checks[0]["max_age_hours"] == 26
    assert eng_checks[0]["stale"] is False
    assert not [row for row in findings if "Engineering Queue" in row.title]


def test_check_workflow_freshness_engineering_queue_active_requires_hourly():
    eight_hours_ago = (datetime.now(UTC) - timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
    active_queue = {"open_count": 2, "pr_open_count": 0, "in_flight_branch": None, "in_flight_pr": None}
    with (
        patch("value_investor.ops_monitor._github_token", return_value="test-token"),
        patch(
            "value_investor.ops_monitor.latest_workflow_run",
            return_value={"id": 1, "created_at": eight_hours_ago},
        ),
        patch("value_investor.ops_monitor.recent_workflow_failures", return_value=[]),
    ):
        findings, checks = check_workflow_freshness(queue_status=active_queue)
    eng_checks = [row for row in checks if row["workflow"] == "engineering-queue.yml"]
    assert eng_checks and eng_checks[0]["max_age_hours"] == 3
    assert eng_checks[0]["stale"] is True
    assert any("Engineering Queue" in row.title for row in findings)


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
        json.dumps({"updated_at": datetime.now(UTC).isoformat(), "reports": [{"ticker": "BT-A.L"}]}),
        encoding="utf-8",
    )
    health = tmp_path / "ingest_health_log.json"
    health.write_text(json.dumps({"entries": [], "updated_at": datetime.now(UTC).isoformat()}), encoding="utf-8")
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
