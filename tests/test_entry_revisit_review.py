"""Entry-revisit (buy+28d) queue — after entry_blind; Package M observe-only."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from value_investor.entry_blind_review import review_fingerprint
from value_investor.entry_revisit_review import (
    ENTRY_REVISIT_DAYS,
    build_entry_revisit_review_queue,
    entry_revisit_clock_ready,
    entry_revisit_due_at,
    entry_revisit_path_window,
    ops_findings_from_entry_revisit_queue,
    refresh_entry_revisit_review_queue,
)
from value_investor.entry_revisit_review_actions import run_entry_revisit_review_action
from value_investor.storage import write_json


def test_due_at_is_buy_plus_28_calendar_days():
    assert entry_revisit_due_at("2026-09-01T10:00:00+00:00") == "2026-09-29"
    assert ENTRY_REVISIT_DAYS == 28
    assert entry_revisit_clock_ready(
        "2026-09-01T10:00:00+00:00",
        asof=datetime(2026, 9, 29, tzinfo=UTC),
    )
    assert not entry_revisit_clock_ready(
        "2026-09-01T10:00:00+00:00",
        asof=datetime(2026, 9, 28, tzinfo=UTC),
    )


def test_path_window_clips_at_buy_plus_28():
    window = entry_revisit_path_window("2026-09-01T10:00:00+00:00")
    assert window is not None
    assert window["end"] == "2026-09-29"
    assert window["forbidden_forward_path"] is False
    assert window["revisit_horizon"] == "buy_plus_28d"


def test_queue_requires_blind_accept_and_clock(tmp_path: Path):
    data = tmp_path
    blind_id = review_fingerprint(
        book_id="cue_consumer_mft",
        ticker="LAB.L",
        entry_at="2026-09-01T09:00:00+00:00",
        kind="entry_blind",
    )
    write_json(
        data / "entry_blind_review_labels.json",
        {
            "schema_version": 1,
            "actioned_review_ids": [blind_id],
            "events": [
                {
                    "kind": "accept",
                    "review_id": blind_id,
                    "at": "2026-09-02T12:00:00+00:00",
                    "stage": "entry_blind",
                    "snapshot": {
                        "stage": "entry_blind",
                        "book_id": "cue_consumer_mft",
                        "book_tag": "Cue-consumer MFT",
                        "ticker": "LAB.L",
                        "entry_at": "2026-09-01T09:00:00+00:00",
                        "population": "lab",
                        "framing": "blind framing",
                        "buy_decision": {
                            "label": "enter",
                            "code": "enter_target_set",
                            "join_ok": True,
                        },
                    },
                }
            ],
        },
    )
    write_json(
        data / "entry_revisit_review_labels.json",
        {"schema_version": 1, "actioned_review_ids": [], "events": [], "active_replies": []},
    )
    write_json(
        data / "cue_consumer_mft_observe.json",
        {
            "lab_id": "cue_consumer_mft",
            "closed_episodes_sample": [
                {
                    "ticker": "LAB.L",
                    "entry_run_at": "2026-09-01T09:00:00+00:00",
                    "exit_run_at": "2026-09-20T09:00:00+00:00",
                    "status": "closed",
                    "return_pct": 0.042,
                    "exit_reason": "identity_break_not_buy_tier",
                }
            ],
        },
    )

    early = build_entry_revisit_review_queue(
        data_dir=data,
        asof=datetime(2026, 9, 15, tzinfo=UTC),
    )
    assert early["active_count"] == 0

    due = build_entry_revisit_review_queue(
        data_dir=data,
        asof=datetime(2026, 10, 1, tzinfo=UTC),
    )
    assert due["active_count"] == 1
    card = due["active"][0]
    assert card["stage"] == "entry_revisit"
    assert card["influences_live"] is False
    assert card["blind_review_id"] == blind_id
    assert card["frozen_blind"]["immutable"] is True
    assert card["path_status"]["status"] == "already_exited"
    assert card["fair_cost_return_pct_to_plus28"] == 0.042
    assert card["review_id"] != blind_id

    findings = ops_findings_from_entry_revisit_queue(due)
    assert findings
    assert all(f["auto_fixable"] is False for f in findings)

    payload = refresh_entry_revisit_review_queue(
        data_dir=data,
        persist=True,
        asof=datetime(2026, 10, 1, tzinfo=UTC),
    )
    assert Path(payload["path"]).is_file()

    result = run_entry_revisit_review_action(
        data,
        review_id=card["review_id"],
        decision="accept",
        snapshot=card,
        refresh_queue=True,
    )
    assert result["ok"] is True
    assert result["influences_live"] is False
    after = build_entry_revisit_review_queue(
        data_dir=data,
        asof=datetime(2026, 10, 1, tzinfo=UTC),
    )
    assert after["active_count"] == 0
