"""Tests for PR fix-request occasion log."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from value_investor.pr_fix_occasions import (
    KIND_CI,
    KIND_MERGE,
    SOURCE_HUMAN,
    SOURCE_TRAFFIC,
    format_common_issues_markdown,
    load_pr_fix_occasions,
    normalize_failure_reason,
    record_pr_fix_occasion,
    summarize_common_failure_reasons,
)
from value_investor.project_traffic_cli import main as traffic_main


def test_normalize_failure_reason_buckets():
    assert normalize_failure_reason(kind=KIND_CI, reason="pytest: boom") == "pytest: boom"
    assert (
        normalize_failure_reason(
            kind=KIND_CI,
            failed_check_names=["CI / test", "lint"],
        )
        == "ci_failing:CI / test,lint"
    )
    assert (
        normalize_failure_reason(kind=KIND_MERGE, mergeable_state="dirty") == "merge_conflict:dirty"
    )


def test_record_and_summarize_common_issues(tmp_path: Path):
    path = tmp_path / "pr_fix_occasions.json"
    now = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    record_pr_fix_occasion(
        source=SOURCE_HUMAN,
        kind=KIND_CI,
        failure_reason="pytest: test_foo failed",
        pr_number=101,
        branch="cursor/demo-5bee",
        path=path,
        now=now,
    )
    record_pr_fix_occasion(
        source=SOURCE_TRAFFIC,
        kind=KIND_CI,
        failure_reason="pytest: test_foo failed",
        pr_number=102,
        path=path,
        now=now,
    )
    record_pr_fix_occasion(
        source=SOURCE_HUMAN,
        kind=KIND_MERGE,
        failure_reason="merge_conflict:dirty",
        pr_number=103,
        path=path,
        now=now,
    )
    payload = load_pr_fix_occasions(path)
    assert payload["occasion_count"] == 3
    assert len(payload["occasions"]) == 3
    summary = summarize_common_failure_reasons(list(payload["occasions"]))
    assert summary["occasion_count"] == 3
    by_reason = {row["failure_reason"]: row for row in summary["by_reason"]}
    assert by_reason["pytest: test_foo failed"]["count"] == 2
    assert by_reason["pytest: test_foo failed"]["sources"]["human_request"] == 1
    assert by_reason["pytest: test_foo failed"]["sources"]["traffic_controller"] == 1
    md = format_common_issues_markdown(summary)
    assert "pytest: test_foo failed" in md
    assert "Occasion count: **3**" in md


def test_cli_record_fix_and_common_issues(tmp_path: Path, monkeypatch, capsys):
    path = tmp_path / "pr_fix_occasions.json"
    monkeypatch.chdir(tmp_path)
    rc = traffic_main(
        [
            "record-fix",
            "--pr",
            "55",
            "--kind",
            "ci_check",
            "--reason",
            "ruff_format",
            "--failed-checks",
            "CI / lint",
            "--log-path",
            str(path),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "recorded" in out
    assert "ruff_format" in out

    rc = traffic_main(["common-issues", "--log-path", str(path), "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ruff_format" in out
    assert '"count": 1' in out
