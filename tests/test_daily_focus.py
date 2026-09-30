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
    reconcile = next(
        t
        for t in payload["tasks"]
        if t["task_ref"] == "reconcile:learning_tracks_dual_suite_present"
    )
    assert reconcile["closeable"] is True
    assert reconcile["close_action"] == "daily-focus-ack"
    assert reconcile["close_payload"]["decision"] == "dismiss"
    assert reconcile["dismissable"] is True
    reconcile_rec = reconcile["recommendation"]
    assert reconcile_rec["accept_action"]["kind"] == "focus-ack"
    assert reconcile_rec["accept_action"]["payload"]["decision"] == "dismiss"
    assert reconcile_rec["accept_action"]["payload"]["focus_id"] == (
        "reconcile:learning_tracks_dual_suite_present"
    )
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
    assert sample["accept_action"]["kind"] in {
        "focus-ack",
        "human-task-ack",
        "link_only",
    }
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


def test_reconcile_dismiss_closes_for_local_date(tmp_path: Path) -> None:
    """UI reconcile Accept is observe-dismiss via daily-focus-ack (not link_only)."""
    _write_minimal_board(tmp_path)
    # Keep planted Cap B warn so the reconcile row is present (skip live refresh).
    write_daily_focus(
        data_dir=tmp_path,
        now=datetime(2026, 9, 28, 2, 0, tzinfo=UTC),
        refresh_reconcile=False,
    )
    focus = json.loads((tmp_path / "daily_focus.json").read_text(encoding="utf-8"))
    ref = "reconcile:learning_tracks_dual_suite_present"
    assert any(t.get("task_ref") == ref and not t.get("closed") for t in focus["tasks"])
    rec = next(t for t in focus["tasks"] if t.get("task_ref") == ref)["recommendation"]
    result = run_daily_focus_ack(
        tmp_path,
        focus_id=ref,
        decision="dismiss",
        local_date="2026-09-28",
        recommendation_id=rec["id"],
    )
    assert result["ok"] is True
    acks = json.loads((tmp_path / "daily_focus_acks.json").read_text(encoding="utf-8"))
    dismiss_rows = [
        a for a in acks["acks"] if a.get("task_ref") == ref and a.get("decision") == "dismiss"
    ]
    assert dismiss_rows
    refreshed = json.loads((tmp_path / "daily_focus.json").read_text(encoding="utf-8"))
    # Dismiss closes for local_date even if Cap B refresh clears the amber source.
    assert ref in refreshed.get("closed_today") or not any(
        t.get("task_ref") == ref and not t.get("closed") for t in refreshed["tasks"]
    )


def test_write_daily_focus_refreshes_stale_reconcile_amber(tmp_path: Path) -> None:
    """Hub-only writes must not keep embedding a Cap B amber that already passes live."""
    _write_minimal_board(tmp_path)
    # Plant healthy artifacts so live Cap B is ok despite stale warn store.
    now = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    write_json(
        tmp_path / "daily_focus.json",
        {
            "local_date": "2026-09-28",
            "timezone": "Europe/London",
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "stale_for_local_date": False,
            "focus_lines": [],
            "tasks": [],
        },
        compact=False,
    )
    write_json(
        tmp_path / "progress_report.json",
        {"schema_version": 1, "generated_at": now.isoformat()},
        compact=False,
    )
    write_json(
        tmp_path / "latest.json",
        {
            "learning_tracks_dual_suite": {"suite_a": {}, "suite_b": {}},
            "paper_automation": {"learning_tracks_review": {"tracks": [{"id": "x"}]}},
        },
        compact=False,
    )
    write_json(
        tmp_path / "human_task_acks.json",
        {"acks": []},
        compact=False,
    )
    write_json(
        tmp_path / "lifecycle_board.json",
        {"generated_at": now.isoformat()},
        compact=False,
    )
    # Stale Cap B warn (the sticky-amber failure mode).
    write_json(
        tmp_path / "ui_state_reconciliation.json",
        {
            "schema_version": 1,
            "generated_at": "2026-09-28T07:00:00Z",
            "overall": "warn",
            "checks": [
                {
                    "id": "daily_hub_local_date_matches_today",
                    "title": "Daily hub local_date matches today",
                    "status": "warn",
                    "detail": "stale planted amber",
                }
            ],
            "summary": {"ok": 0, "warn": 1, "fail": 0},
        },
        compact=False,
    )
    payload = write_daily_focus(data_dir=tmp_path, now=now)
    cap_b = json.loads((tmp_path / "ui_state_reconciliation.json").read_text(encoding="utf-8"))
    assert cap_b.get("overall") == "ok"
    assert payload.get("counts", {}).get("reconcile", 0) == 0
    assert not any(
        str(t.get("task_ref") or "").startswith("reconcile:") and not t.get("closed")
        for t in payload.get("tasks") or []
    )


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
    assert "open_task_count" in result
    inbox = json.loads((tmp_path / "daily_discuss_inbox.json").read_text(encoding="utf-8"))
    assert inbox["items"]
    assert inbox["items"][-1]["recommendation_id"] == rec["id"]
    assert inbox["items"][-1]["discuss_prompt"]
    # Discuss must refresh hub (not leave a stale checkout copy for GHA commit).
    refreshed = json.loads((tmp_path / "daily_focus.json").read_text(encoding="utf-8"))
    assert refreshed.get("local_date") == "2026-09-28"


def test_merge_daily_focus_acks_keeps_accepts_across_stale_discuss(
    tmp_path: Path,
) -> None:
    from value_investor.daily_focus_acks import merge_daily_focus_acks_stores

    accepts = {
        "schema_version": 1,
        "updated_at": "2026-09-30T08:42:27+00:00",
        "acks": [
            {
                "task_ref": "focus-1",
                "focus_id": "focus-1",
                "decision": "accept",
                "status": "open",
                "local_date": "2026-09-30",
                "acked_at": "2026-09-30T08:42:20+00:00",
            },
            {
                "task_ref": "mwarn:dax:zero_improve_stall",
                "focus_id": "mwarn:dax:zero_improve_stall",
                "decision": "accept",
                "status": "open",
                "local_date": "2026-09-30",
                "acked_at": "2026-09-30T08:42:21+00:00",
            },
        ],
    }
    # Stale discuss job never saw the accepts; only wrote discuss rows.
    discuss_stale = {
        "schema_version": 1,
        "updated_at": "2026-09-30T08:42:33+00:00",
        "acks": [
            {
                "task_ref": "mwarn:dax:unmeasured_stuck",
                "focus_id": "mwarn:dax:unmeasured_stuck",
                "decision": "discuss",
                "status": "open",
                "local_date": "2026-09-30",
                "acked_at": "2026-09-30T08:42:33+00:00",
            }
        ],
    }
    merged = merge_daily_focus_acks_stores(accepts, discuss_stale)
    refs = {a["task_ref"] for a in merged["acks"]}
    assert refs == {
        "focus-1",
        "mwarn:dax:zero_improve_stall",
        "mwarn:dax:unmeasured_stuck",
    }
    assert merged["updated_at"] == "2026-09-30T08:42:33+00:00"


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
