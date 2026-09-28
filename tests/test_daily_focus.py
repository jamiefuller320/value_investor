"""Daily focus hub builder + recommendations + discuss inbox."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from value_investor.daily_focus import (
    build_daily_focus,
    parse_today_bullets_from_notes,
    write_daily_focus,
)
from value_investor.daily_focus_acks import append_discuss_inbox, record_daily_focus_ack
from value_investor.daily_hub_actions import run_daily_discuss, run_daily_focus_ack
from value_investor.storage import write_json


def _write_minimal_board(data_dir: Path) -> None:
    write_json(
        data_dir / "human_tasks_board.json",
        {
            "schema_version": 1,
            "generated_at": "2026-09-28T01:00:00+00:00",
            "counts": {"new_info": 1, "unacked": 1, "acked": 0, "automated": 0, "human": 2},
            "tasks": [
                {
                    "id": "weekday-daily-hub-glance",
                    "title": "Glance Daily hub",
                    "summary": "Open Daily before chat todos.",
                    "sort_bucket": "new_info",
                    "analysis": {
                        "fingerprint": "abc123deadbeef01",
                        "headline": "Hub shipped",
                        "bullets": ["open daily"],
                    },
                    "ack": {"acked": False, "stale": False},
                },
                {
                    "id": "weekday-engineering-parked-backlog-clear",
                    "title": "Clear parked backlog",
                    "summary": "Triage parks",
                    "sort_bucket": "unacked",
                    "analysis": {"fingerprint": "fff0001112223334", "headline": "", "bullets": []},
                    "ack": {"acked": False, "stale": False},
                },
            ],
        },
        compact=False,
    )
    write_json(
        data_dir / "progress_report.json",
        {
            "schema_version": 1,
            "generated_at": "2026-09-28T01:00:00+00:00",
            "actionable": {
                "defer_now": [
                    {
                        "id": "defer-1",
                        "title": "Do the thing",
                        "summary": "A now item",
                    }
                ],
                "counts": {"defer_now": 1},
            },
        },
        compact=False,
    )
    write_json(
        data_dir / "ui_state_reconciliation.json",
        {
            "schema_version": 1,
            "generated_at": "2026-09-28T01:00:00+00:00",
            "overall": "warn",
            "checks": [
                {
                    "id": "learning_tracks_dual_suite_present",
                    "title": "Dual-suite scoreboard published",
                    "status": "warn",
                    "drift_class": "publish_lag",
                    "detail": "null",
                    "runbook": "docs/ops/primary-learning-track.md",
                }
            ],
            "summary": {"ok": 0, "warn": 1, "fail": 0},
        },
        compact=False,
    )
    write_json(
        data_dir / "project_daily_seed.json",
        {
            "schema_version": 1,
            "focus_lines": [
                {
                    "id": "focus-1",
                    "priority": 1,
                    "title": "P1 holdings rememo / RAT.L",
                    "summary": "Leave euro fat slot",
                    "source": "project_notes",
                    "tags": ["p1"],
                }
            ],
        },
        compact=False,
    )
    write_json(data_dir / "latest.json", {"learning_tracks_dual_suite": None}, compact=False)
    write_json(
        data_dir / "observe_utilization.json",
        {"surface_freshness": "fresh"},
        compact=False,
    )


def test_parse_today_bullets_from_notes() -> None:
    notes = """## Daily focus
- [ ] Today — P1 holdings rememo / RAT.L; leave euro fat slot
- [ ] Other task without Today prefix
- Today — Watch RAT.L first memo
"""
    bullets = parse_today_bullets_from_notes(notes)
    assert len(bullets) == 2
    assert "P1 holdings" in bullets[0]["title"]
    assert bullets[0]["source"] == "project_notes"


def test_build_daily_focus_collates_sources(tmp_path: Path) -> None:
    _write_minimal_board(tmp_path)
    now = datetime(2026, 9, 28, 2, 0, tzinfo=UTC)  # before 04:00 London in BST/GMT
    payload = build_daily_focus(data_dir=tmp_path, now=now)
    assert payload["schema_version"] == 1
    assert payload["timezone"] == "Europe/London"
    assert payload["local_date"] == "2026-09-28"
    assert payload["refresh_deadline_local"] == "04:00"
    assert payload["focus_lines"][0]["id"] == "focus-1"
    refs = [t["task_ref"] for t in payload["tasks"]]
    assert "focus-1" in refs
    assert "human:weekday-daily-hub-glance" in refs
    assert "human:weekday-engineering-parked-backlog-clear" in refs
    assert "progress:defer-1" in refs
    assert "reconcile:learning_tracks_dual_suite_present" in refs
    recs = payload["recommendations"]
    assert recs
    sample = recs[0]
    for key in (
        "id",
        "task_id",
        "summary",
        "rationale",
        "accept_action",
        "discuss_prompt",
        "priority",
    ):
        assert key in sample
    assert sample["accept_action"]["kind"] in {"focus-ack", "human-task-ack", "link_only"}
    assert "Discuss daily recommendation" in sample["discuss_prompt"]
    # Tasks embed recommendation object
    focus_task = next(t for t in payload["tasks"] if t["task_ref"] == "focus-1")
    assert focus_task["recommendation"]["id"].startswith("rec-")
    assert payload["illumination_hints"]["automation.human"]["new_info"] is True


def test_focus_ack_closes_for_local_date(tmp_path: Path) -> None:
    _write_minimal_board(tmp_path)
    result = run_daily_focus_ack(
        tmp_path,
        focus_id="focus-1",
        decision="accept",
        local_date="2026-09-28",
        recommendation_id="rec-test",
    )
    assert result["ok"] is True
    acks = json.loads((tmp_path / "daily_focus_acks.json").read_text(encoding="utf-8"))
    assert any(a.get("focus_id") == "focus-1" for a in acks["acks"])
    focus = json.loads((tmp_path / "daily_focus.json").read_text(encoding="utf-8"))
    focus_task = next(t for t in focus["tasks"] if t["task_ref"] == "focus-1")
    assert focus_task["closed"] is True


def test_discuss_inbox_queues_project_pickup(tmp_path: Path) -> None:
    _write_minimal_board(tmp_path)
    write_daily_focus(data_dir=tmp_path, now=datetime(2026, 9, 28, 2, 0, tzinfo=UTC))
    focus = json.loads((tmp_path / "daily_focus.json").read_text(encoding="utf-8"))
    rec = focus["recommendations"][0]
    result = run_daily_discuss(
        tmp_path,
        recommendation_id=rec["id"],
        recommendation=rec,
        local_date="2026-09-28",
    )
    assert result["ok"] is True
    assert "discuss daily recommendation" in (result.get("project_pickup") or "").lower()
    inbox = json.loads((tmp_path / "daily_discuss_inbox.json").read_text(encoding="utf-8"))
    assert inbox["items"]
    assert inbox["items"][-1]["recommendation_id"] == rec["id"]
    assert inbox["items"][-1]["discuss_prompt"]


def test_append_discuss_dedupes_same_day(tmp_path: Path) -> None:
    rec = {
        "id": "rec-abc",
        "task_id": "focus-1",
        "summary": "s",
        "rationale": "r",
        "discuss_prompt": "Discuss daily recommendation `rec-abc`",
        "options": [],
        "priority": 1,
    }
    append_discuss_inbox(tmp_path, recommendation=rec, local_date="2026-09-28")
    append_discuss_inbox(tmp_path, recommendation=rec, local_date="2026-09-28")
    inbox = json.loads((tmp_path / "daily_discuss_inbox.json").read_text(encoding="utf-8"))
    open_items = [
        i
        for i in inbox["items"]
        if i.get("recommendation_id") == "rec-abc" and i.get("status") == "open"
    ]
    assert len(open_items) == 1


def test_record_daily_focus_ack_rejects_bad_decision(tmp_path: Path) -> None:
    try:
        record_daily_focus_ack(tmp_path, focus_id="focus-1", decision="explode")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "Unknown decision" in str(exc)
