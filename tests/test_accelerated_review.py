"""Tests for mid-week accelerated email_only chaining (L97)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from value_investor.accelerated_review import (
    WEDNESDAY_ANCHOR_SOURCE,
    evaluate_accelerated_email_only_dispatch,
    evaluate_wednesday_anchor_dispatch,
    ingest_loop_materiality,
    midweek_email_only_count,
    record_midweek_email_only_run,
    screen_run_age_hours,
    wednesday_anchor_count,
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


def test_midweek_email_only_count_excludes_wednesday_anchor(tmp_path: Path):
    log = tmp_path / "accelerated_review.json"
    now = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)  # Thursday
    record_midweek_email_only_run(
        source=WEDNESDAY_ANCHOR_SOURCE, log_path=log, now=now - timedelta(days=1)
    )
    record_midweek_email_only_run(source="auto_queue_drain", log_path=log, now=now)
    assert midweek_email_only_count(log_path=log, now=now) == 1
    assert wednesday_anchor_count(log_path=log, now=now) == 1


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
        record_midweek_email_only_run(source="auto_queue_drain", log_path=log, now=now)
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


def test_eng_chain_cap_ignores_wednesday_anchor(tmp_path: Path):
    log = tmp_path / "log.json"
    wed = datetime(2026, 8, 5, 11, 0, tzinfo=UTC)
    record_midweek_email_only_run(source=WEDNESDAY_ANCHOR_SOURCE, log_path=log, now=wed)
    for offset in range(2):
        record_midweek_email_only_run(
            source="auto_queue_drain",
            log_path=log,
            now=wed + timedelta(hours=offset + 1),
        )
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
            now=wed + timedelta(hours=4),
        )
    assert not decision.should_dispatch
    assert "cap reached" in decision.reason


def test_screen_run_age_hours(tmp_path: Path):
    latest = tmp_path / "latest.json"
    run_at = datetime(2026, 8, 10, 12, 0, tzinfo=UTC).isoformat()
    latest.write_text(json.dumps({"run_at": run_at}), encoding="utf-8")
    now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    age = screen_run_age_hours(latest_path=latest, now=now)
    assert age == 48.0


def test_ingest_loop_materiality_detects_body_delta():
    material, checks = ingest_loop_materiality(
        {
            "health_before": {"filings_with_body": 10, "indexed_without_body": 2},
            "health_after": {"filings_with_body": 11, "indexed_without_body": 1},
        }
    )
    assert material
    assert checks["delta_filings_with_body"] == 1


@patch("value_investor.accelerated_review.weekly_ops_budget_status")
def test_wednesday_anchor_dispatches_on_stale_screen(mock_budget, tmp_path: Path):
    mock_budget.return_value = {
        "remaining_weekly_ops_usd": 40.0,
        "weekly_ops_cap_usd": 50.0,
        "constraining": False,
    }
    latest = tmp_path / "latest.json"
    run_at = (datetime(2026, 8, 9, 12, 0, tzinfo=UTC)).isoformat()
    latest.write_text(json.dumps({"run_at": run_at}), encoding="utf-8")
    wed_afternoon = datetime(2026, 8, 12, 11, 0, tzinfo=UTC)
    decision = evaluate_wednesday_anchor_dispatch(
        queue_status=_idle_status(),
        log_path=tmp_path / "log.json",
        latest_path=latest,
        ingest_loop={"health_before": {}, "health_after": {}},
        now=wed_afternoon,
    )
    assert decision.should_dispatch
    assert decision.checks["anchor_trigger"] == "screen_stale"


def test_wednesday_anchor_blocks_before_afternoon_window(tmp_path: Path):
    wed_morning = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    decision = evaluate_wednesday_anchor_dispatch(
        queue_status=_idle_status(),
        log_path=tmp_path / "log.json",
        now=wed_morning,
    )
    assert not decision.should_dispatch
    assert "anchor window" in decision.reason


def test_wednesday_anchor_blocks_when_fresh_and_no_ingest_change(tmp_path: Path):
    latest = tmp_path / "latest.json"
    run_at = datetime(2026, 8, 12, 9, 0, tzinfo=UTC).isoformat()
    latest.write_text(json.dumps({"run_at": run_at}), encoding="utf-8")
    wed_afternoon = datetime(2026, 8, 12, 11, 0, tzinfo=UTC)
    decision = evaluate_wednesday_anchor_dispatch(
        queue_status=_idle_status(),
        log_path=tmp_path / "log.json",
        latest_path=latest,
        ingest_loop={
            "health_before": {"filings_with_body": 5},
            "health_after": {"filings_with_body": 5},
        },
        now=wed_afternoon,
    )
    assert not decision.should_dispatch
    assert "no material change" in decision.reason


def test_wednesday_anchor_defers_when_micro_compiled(tmp_path: Path):
    latest = tmp_path / "latest.json"
    run_at = datetime(2026, 8, 1, 12, 0, tzinfo=UTC).isoformat()
    latest.write_text(json.dumps({"run_at": run_at}), encoding="utf-8")
    wed_afternoon = datetime(2026, 8, 12, 11, 0, tzinfo=UTC)
    decision = evaluate_wednesday_anchor_dispatch(
        queue_status=_idle_status(),
        log_path=tmp_path / "log.json",
        latest_path=latest,
        ingest_loop={"micro_compiled": True, "health_before": {}, "health_after": {}},
        now=wed_afternoon,
    )
    assert not decision.should_dispatch
    assert "eng-chain" in decision.reason
