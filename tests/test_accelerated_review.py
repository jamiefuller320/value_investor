"""Tests for mid-week accelerated email_only chaining (L97)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from value_investor.accelerated_review import (
    evaluate_accelerated_email_only_dispatch,
    midweek_email_only_count,
    record_midweek_email_only_run,
)
from value_investor.engineering_queue import EngineeringQueueStatus


def _idle_status() -> EngineeringQueueStatus:
    return EngineeringQueueStatus(
        open_count=0,
        pr_open_count=0,
        parked_count=0,
        merged_count=5,
        failed_count=0,
        next_task=None,
        in_flight_branch=None,
        in_flight_pr=None,
        spend_since_checkpoint_usd=0.0,
        spend_checkpoint_usd=60.0,
        spend_blocked=False,
    )


def test_midweek_email_only_count_resets_each_iso_week(tmp_path: Path):
    log = tmp_path / "accelerated_review.json"
    record_midweek_email_only_run(source="manual", log_path=log)
    assert midweek_email_only_count(log_path=log) == 1


def test_evaluate_accelerated_email_blocks_when_queue_not_idle(tmp_path: Path):
    status = _idle_status()
    status.open_count = 2
    decision = evaluate_accelerated_email_only_dispatch(
        queue_status=status,
        log_path=tmp_path / "log.json",
    )
    assert not decision.should_dispatch
    assert "not idle" in decision.reason


def test_evaluate_accelerated_email_blocks_on_sunday(tmp_path: Path):
    sunday = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
    decision = evaluate_accelerated_email_only_dispatch(
        queue_status=_idle_status(),
        log_path=tmp_path / "log.json",
        now=sunday,
    )
    assert not decision.should_dispatch
    assert "Sunday" in decision.reason


@patch("value_investor.accelerated_review.weekly_ops_budget_status")
def test_evaluate_accelerated_email_dispatches_when_guards_pass(
    mock_budget,
    tmp_path: Path,
):
    mock_budget.return_value = {
        "remaining_weekly_ops_usd": 40.0,
        "weekly_ops_cap_usd": 50.0,
        "constraining": False,
    }
    tasks = tmp_path / "engineering_tasks.json"
    tasks.write_text(
        """
        {
          "tasks": [
            {
              "id": "eng-20260803-03",
              "area": "ingest",
              "title": "test",
              "summary": "s",
              "priority": "high",
              "priority_score": 90,
              "source": "post_run_review",
              "allowed_paths": ["src/value_investor/research/filings.py"],
              "status": "merged"
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    decision = evaluate_accelerated_email_only_dispatch(
        queue_status=_idle_status(),
        tasks_path=tasks,
        log_path=tmp_path / "log.json",
        merged_task_id="eng-20260803-03",
        now=datetime(2026, 8, 4, 10, 0, tzinfo=UTC),
    )
    assert decision.should_dispatch


def test_evaluate_accelerated_email_blocks_when_weekly_cap_hit(tmp_path: Path):
    log = tmp_path / "log.json"
    now = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)
    for _ in range(2):
        record_midweek_email_only_run(source="manual", log_path=log, now=now)
    with patch(
        "value_investor.accelerated_review.weekly_ops_budget_status",
        return_value={
            "remaining_weekly_ops_usd": 40.0,
            "weekly_ops_cap_usd": 50.0,
            "constraining": False,
        },
    ):
        decision = evaluate_accelerated_email_only_dispatch(
            queue_status=_idle_status(),
            log_path=log,
            now=now,
        )
    assert not decision.should_dispatch
    assert "cap reached" in decision.reason
