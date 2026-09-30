"""Daily hub History builder + status conventions + stale flag."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from value_investor.daily_focus import (
    build_daily_focus,
    compute_stale_for_local_date,
    derive_ready_status,
    parse_status_conventions,
    parse_today_bullets_from_notes,
    write_daily_focus,
)
from value_investor.daily_focus_acks import (
    append_discuss_inbox,
    record_daily_focus_ack,
    resolve_discuss_inbox_item,
)
from value_investor.daily_hub_history import (
    ACCEPT_STREAK_THRESHOLD,
    build_daily_hub_history,
    write_daily_hub_history,
)
from value_investor.storage import write_json


def _seed_board(data_dir: Path) -> None:
    write_json(
        data_dir / "human_tasks_board.json",
        {
            "schema_version": 1,
            "counts": {"new_info": 0, "unacked": 0, "acked": 0, "automated": 0, "human": 0},
            "tasks": [],
        },
        compact=False,
    )
    write_json(data_dir / "progress_report.json", {"actionable": {"defer_now": []}}, compact=False)
    write_json(
        data_dir / "ui_state_reconciliation.json",
        {"overall": "ok", "checks": [], "summary": {"ok": 1, "warn": 0, "fail": 0}},
        compact=False,
    )
    write_json(data_dir / "latest.json", {"learning_tracks_dual_suite": {"a": 1}}, compact=False)
    write_json(data_dir / "observe_utilization.json", {"surface_freshness": "fresh"}, compact=False)


def test_parse_status_conventions_next_and_waiting() -> None:
    status = parse_status_conventions(
        title="P1 rememo",
        summary="Leave euro fat slot",
        notes_block="Next: Confirm RAT.L memo\nWaiting on: body_lag after ingest",
    )
    assert status["next_steps"] == ["Confirm RAT.L memo"]
    assert status["waiting_on"][0]["detail"] == "body_lag after ingest"
    assert status["state"] == "waiting"
    ready = derive_ready_status(status, recommendation_present=True, closed=False)
    assert ready["ready"] is False
    assert ready["state"] == "waiting"


def test_compose_assessment_from_notes_conventions() -> None:
    from value_investor.daily_focus import compose_assessment, format_stage_duration

    status = parse_status_conventions(
        title="P1 rememo",
        notes_block=(
            "Where: RAT.L body_lag after holdings-first rememo\n"
            "Since: 2026-09-27\n"
            "Waiting on: filing body land\n"
            "How: ingest then body-lag rememo; leave euro fat slot\n"
            "Next: Confirm RAT.L memo"
        ),
    )
    now = datetime(2026, 9, 30, 8, 0, tzinfo=UTC)
    assess = compose_assessment(
        status=status,
        title="P1 rememo",
        notes_block=(
            "Where: RAT.L body_lag after holdings-first rememo\n"
            "Since: 2026-09-27\n"
            "Waiting on: filing body land\n"
            "How: ingest then body-lag rememo; leave euro fat slot\n"
            "Next: Confirm RAT.L memo"
        ),
        now=now,
    )
    assert "RAT.L body_lag" in assess["where_we_are"]
    assert assess["waiting_for"] == "filing body land"
    assert "body-lag rememo" in assess["how_achieved"]
    assert assess["stage_since"] == "2026-09-27"
    assert assess["days_in_stage"] == 3
    assert "3 days" in assess["stage_duration"]
    days, label = format_stage_duration(None, now=now)
    assert days is None
    assert label == "duration unknown"


def test_compose_assessment_does_not_invent_duration() -> None:
    from value_investor.daily_focus import compose_assessment

    status = parse_status_conventions(
        title="Ship History",
        notes_block="Next: Open draft PR\nWaiting on: CI green",
    )
    assess = compose_assessment(status=status, title="Ship History", now=datetime(2026, 9, 30, tzinfo=UTC))
    assert assess["stage_since"] is None
    assert assess["days_in_stage"] is None
    assert assess["stage_duration"] == "duration unknown"
    assert "stage_duration" in assess["incomplete_fields"]
    assert assess["waiting_for"] == "CI green"
    assert assess["how_achieved"] == "Open draft PR"
    assert assess["observe_only"] is True


def test_build_daily_focus_attaches_expansive_assessment(tmp_path: Path) -> None:
    _seed_board(tmp_path)
    write_json(
        tmp_path / "project_daily_seed.json",
        {
            "focus_lines": [
                {
                    "id": "focus-1",
                    "title": "P1 rememo",
                    "summary": "Leave euro fat slot",
                    "source": "project_notes",
                    "tags": ["p1", "rememo"],
                    "notes_block": (
                        "Where: Holdings rememo queue · RAT.L first\n"
                        "Since: 2026-09-28\n"
                        "Waiting on: memo body\n"
                        "How: body_lag rememo after ingest"
                    ),
                    "waiting_on": [{"kind": "artifact", "detail": "memo body"}],
                }
            ]
        },
        compact=False,
    )
    now = datetime(2026, 9, 30, 1, 30, tzinfo=UTC)
    payload = build_daily_focus(data_dir=tmp_path, now=now)
    task = next(t for t in payload["tasks"] if t["task_ref"] == "focus-1")
    assess = task["assessment"]
    assert assess["where_we_are"].startswith("Holdings rememo")
    assert assess["waiting_for"] == "memo body"
    assert "body_lag rememo" in assess["how_achieved"]
    assert assess["days_in_stage"] == 2
    assert task["status"]["assessment"]["stage_since"] == "2026-09-28"


def test_assessment_carries_stage_since_across_rebuilds(tmp_path: Path) -> None:
    _seed_board(tmp_path)
    write_json(
        tmp_path / "project_daily_seed.json",
        {
            "focus_lines": [
                {
                    "id": "focus-carry",
                    "title": "Carry duration",
                    "summary": "Waiting on: review",
                    "tags": ["carry"],
                    "assessment": {
                        "where_we_are": "In review",
                        "stage_since": "2026-09-25",
                        "waiting_for": "review",
                        "how_achieved": "human Discuss",
                    },
                    "waiting_on": [{"kind": "human", "detail": "review"}],
                }
            ]
        },
        compact=False,
    )
    first = write_daily_focus(data_dir=tmp_path, now=datetime(2026, 9, 28, 8, 0, tzinfo=UTC))
    t1 = next(t for t in first["tasks"] if t["task_ref"] == "focus-carry")
    assert t1["assessment"]["stage_since"] == "2026-09-25"
    # Drop explicit stage_since from seed; prior assessment should carry it.
    write_json(
        tmp_path / "project_daily_seed.json",
        {
            "focus_lines": [
                {
                    "id": "focus-carry",
                    "title": "Carry duration",
                    "summary": "Waiting on: review",
                    "tags": ["carry"],
                    "waiting_on": [{"kind": "human", "detail": "review"}],
                }
            ]
        },
        compact=False,
    )
    second = build_daily_focus(data_dir=tmp_path, now=datetime(2026, 9, 30, 8, 0, tzinfo=UTC))
    t2 = next(t for t in second["tasks"] if t["task_ref"] == "focus-carry")
    assert t2["assessment"]["stage_since"] == "2026-09-25"
    assert t2["assessment"]["days_in_stage"] == 5
    assert "prior:stage_since" in t2["assessment"]["provenance"]


def test_parse_today_bullets_captures_status_lines() -> None:
    notes = """## Daily
- [ ] Today — P1 holdings rememo / RAT.L
  Where: Holdings rememo · RAT.L first
  Since: 2026-09-27
  Next: Confirm memo body
  Waiting on: RAT.L filing body
  How: body_lag rememo after ingest
- Today — Ship daily hub History
"""
    bullets = parse_today_bullets_from_notes(notes)
    assert len(bullets) == 2
    assert bullets[0]["status"]["next_steps"][0] == "Confirm memo body"
    assert "RAT.L filing body" in bullets[0]["status"]["waiting_on"][0]["detail"]
    assess = bullets[0]["assessment"]
    assert "Holdings rememo" in assess["where_we_are"]
    assert assess["stage_since"] == "2026-09-27"
    assert "body_lag rememo" in assess["how_achieved"]
    assert bullets[1]["title"].startswith("Ship daily hub")


def test_compute_stale_for_local_date_wall_clock() -> None:
    # Artifact still on 28 Sep; wall clock is 29 Sep morning London.
    now = datetime(2026, 9, 29, 5, 0, tzinfo=UTC)
    assert compute_stale_for_local_date("2026-09-28", now=now) is True
    assert compute_stale_for_local_date("2026-09-29", now=now) is False


def test_build_daily_focus_status_and_work_class(tmp_path: Path) -> None:
    _seed_board(tmp_path)
    write_json(
        tmp_path / "project_daily_seed.json",
        {
            "focus_lines": [
                {
                    "id": "focus-1",
                    "title": "P1 rememo",
                    "summary": "Leave euro fat slot. Next: confirm body.",
                    "source": "project_notes",
                    "tags": ["p1", "rememo"],
                    "waiting_on": [{"kind": "artifact", "detail": "memo body"}],
                }
            ]
        },
        compact=False,
    )
    now = datetime(2026, 9, 29, 1, 30, tzinfo=UTC)  # before 04:00 London
    payload = build_daily_focus(data_dir=tmp_path, now=now)
    assert payload["stale_for_local_date"] is False
    task = next(t for t in payload["tasks"] if t["task_ref"] == "focus-1")
    assert task["work_class"] == "dev"
    assert task["task_family"] in {"p1", "rememo", "focus-1"}
    assert task["status"]["ready"] is False
    assert task["status"]["waiting_on"]


def test_ack_enrichment_stores_outcome_fields(tmp_path: Path) -> None:
    _seed_board(tmp_path)
    write_json(
        tmp_path / "project_daily_seed.json",
        {
            "focus_lines": [
                {
                    "id": "focus-2",
                    "title": "Daily hub Phase A",
                    "summary": "History + status",
                    "tags": ["daily-hub-phase-a"],
                    "task_family": "daily-hub-phase-a",
                    "work_class": "dev",
                }
            ]
        },
        compact=False,
    )
    write_daily_focus(data_dir=tmp_path, now=datetime(2026, 9, 28, 12, 0, tzinfo=UTC))
    row = record_daily_focus_ack(
        tmp_path,
        focus_id="focus-2",
        decision="accept",
        local_date="2026-09-28",
        recommendation_id="rec-abc",
    )
    assert row["outcome"] == "accept_followed"
    assert row["had_discuss"] is False
    assert row["work_class"] == "dev"
    assert row["title"]
    assert row["task_family"] == "daily-hub-phase-a"


def test_history_builder_accept_vs_discuss_and_filters_ops_gate(tmp_path: Path) -> None:
    _seed_board(tmp_path)
    # Dev accept (no discuss)
    record_daily_focus_ack(
        tmp_path,
        task_ref="focus-1",
        decision="accept",
        local_date="2026-09-28",
        title="Ship History",
        summary="dev close",
        work_class="dev",
        task_family="daily-hub-phase-a",
        had_discuss=False,
        outcome="accept_followed",
    )
    # Routine ops_gate should not enter default History
    record_daily_focus_ack(
        tmp_path,
        task_ref="human:weekday-daily-hub-glance",
        decision="accept",
        local_date="2026-09-28",
        title="Glance Daily hub",
        work_class="ops_gate",
        task_family="weekday-daily-hub-glance",
        had_discuss=False,
        outcome="accept_followed",
    )
    # Discuss resolved
    append_discuss_inbox(
        tmp_path,
        recommendation={
            "id": "rec-discuss-1",
            "task_id": "focus-3",
            "summary": "Rewrite focus",
            "rationale": "r",
            "discuss_prompt": "Discuss daily recommendation `rec-discuss-1`",
            "options": [],
            "priority": 1,
        },
        local_date="2026-09-27",
        work_class="dev",
        task_family="daily-hub-phase-a",
        title="Rewrite focus bullet",
    )
    resolved = resolve_discuss_inbox_item(
        tmp_path,
        recommendation_id="rec-discuss-1",
        local_date="2026-09-27",
        resolution_summary="Narrowed to P1 rememo only",
    )
    assert resolved is not None
    assert resolved["status"] == "resolved"

    now = datetime(2026, 9, 29, 8, 0, tzinfo=UTC)
    hist = build_daily_hub_history(data_dir=tmp_path, now=now)
    entries = [e for s in hist["sessions"] for e in s["entries"]]
    refs = {e["task_ref"] for e in entries}
    assert "focus-1" in refs
    assert "human:weekday-daily-hub-glance" not in refs
    accept = next(e for e in entries if e["task_ref"] == "focus-1")
    assert accept["outcome"] == "accept_followed"
    assert accept["had_discuss"] is False
    discuss = next(e for e in entries if e["outcome"] == "discuss_resolved")
    assert discuss["had_discuss"] is True
    assert "Narrowed" in discuss["summary"] or discuss["title"]


def test_accept_streak_candidate_at_threshold(tmp_path: Path) -> None:
    _seed_board(tmp_path)
    base = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    for i in range(ACCEPT_STREAK_THRESHOLD):
        day = (base - timedelta(days=i)).date().isoformat()
        record_daily_focus_ack(
            tmp_path,
            task_ref=f"focus-streak-{i}",
            decision="accept",
            local_date=day,
            title=f"Gate glance {i}",
            work_class="dev",
            task_family="weekday-verify-paper-auto",
            had_discuss=False,
            outcome="accept_followed",
        )
    hist = write_daily_hub_history(data_dir=tmp_path, now=base)
    assert hist["summary"]["candidate_count"] >= 1
    cand = hist["automation_candidates"][0]
    assert cand["task_family"] == "weekday-verify-paper-auto"
    assert cand["accept_streak"] >= ACCEPT_STREAK_THRESHOLD
    assert cand["discuss_count_30d"] == 0
    assert cand["auto_fixable"] is False
    assert (tmp_path / "daily_hub_history.json").exists()


def test_had_discuss_true_when_inbox_queued_before_accept(tmp_path: Path) -> None:
    _seed_board(tmp_path)
    append_discuss_inbox(
        tmp_path,
        recommendation={
            "id": "rec-x",
            "task_id": "focus-9",
            "summary": "s",
            "rationale": "r",
            "discuss_prompt": "Discuss daily recommendation `rec-x`",
            "options": [],
            "priority": 1,
        },
        local_date="2026-09-28",
        work_class="dev",
        task_family="daily-hub-phase-a",
    )
    row = record_daily_focus_ack(
        tmp_path,
        task_ref="focus-9",
        recommendation_id="rec-x",
        decision="accept",
        local_date="2026-09-28",
        title="After discuss",
        work_class="dev",
        task_family="daily-hub-phase-a",
    )
    assert row["had_discuss"] is True
    assert row["outcome"] == "accept_followed"
    hist = build_daily_hub_history(data_dir=tmp_path, now=datetime(2026, 9, 29, 12, 0, tzinfo=UTC))
    entry = next(e for s in hist["sessions"] for e in s["entries"] if e["task_ref"] == "focus-9")
    assert entry["had_discuss"] is True
    # Streak candidacy requires had_discuss=false
    assert entry["automation_signal"]["eligible"] is False
