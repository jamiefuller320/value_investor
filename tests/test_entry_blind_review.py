"""Entry-blind review queue v0 — PIT-only; no outcome leakage."""

from __future__ import annotations

from pathlib import Path

from value_investor.entry_blind_review import (
    ACTIVE_ATTENTION_CAP,
    assert_no_outcome_leakage,
    build_entry_blind_review_queue,
    entry_blind_pit_window,
    family_id,
    ops_findings_from_entry_blind_queue,
    refresh_entry_blind_review_queue,
    review_fingerprint,
    strip_outcome_fields,
)
from value_investor.entry_blind_review_actions import run_entry_blind_review_action


def _sealed_fixture() -> dict:
    return {
        "models": [
            {
                "model_id": "n200",
                "label": "N200",
                "registration_id": "strand-b-plain-value-tech-timing-v0",
                "columns": {
                    "just_bought": {
                        "count": 2,
                        "chips": [
                            {
                                "ticker": "AAA.L",
                                "name": "Alpha",
                                "phase": "just_bought",
                                "status": "open",
                                "entry_run_at": "2026-10-20T10:00:00+00:00",
                                "exit_run_at": None,
                                # Must be stripped from blind cards:
                                "return_pct": 0.12,
                                "return_basis": "fair_cost_episode",
                                "days_in_phase": 3,
                                "entry_reason": "enter_buy_tier",
                            },
                            {
                                "ticker": "BBB.L",
                                "phase": "just_bought",
                                "status": "open",
                                "entry_run_at": "2026-10-18T10:00:00+00:00",
                                "return_pct": -0.08,
                                "days_in_phase": 5,
                            },
                        ],
                    }
                },
            }
        ]
    }


def _lab_fixture() -> dict:
    return {
        "lab_id": "cue_consumer_mft",
        "registration_id": "cue-consumer-mft-v0",
        "open_lab_buys": [
            {
                "ticker": "LAB.L",
                "name": "Lab Co",
                "entry_at": "2026-10-22T09:00:00+00:00",
                "return_pct": 0.99,  # must never appear on card
            }
        ],
    }


def test_review_fingerprint_stable_entry_blind():
    a = review_fingerprint(
        book_id="n200",
        ticker="aaa.l",
        entry_at="2026-10-20T10:00:00+00:00",
    )
    b = review_fingerprint(
        book_id="n200",
        ticker="AAA.L",
        entry_at="2026-10-20T10:00:00+00:00",
    )
    assert a == b
    assert len(a) == 20


def test_family_id_is_book_ticker_entry_day():
    assert (
        family_id(
            book_id="n200",
            ticker="aaa.l",
            entry_at="2026-10-20T10:00:00+00:00",
        )
        == "n200|AAA.L|2026-10-20"
    )


def test_pit_window_hard_clips_at_buy_day():
    window = entry_blind_pit_window("2026-10-20T10:00:00+00:00", before_days=180)
    assert window is not None
    assert window["end"] == "2026-10-20"
    assert window["asof"] == "2026-10-20"
    assert window["days_after"] == 0
    assert window["forbidden_forward_path"] is True
    assert window["start"] < window["end"]


def test_strip_outcome_fields_removes_leakage():
    dirty = {
        "ticker": "AAA.L",
        "return_pct": 12.0,
        "exit_at": "2026-11-01",
        "sell_decision": {"code": "leave_buy_tier"},
        "charts": {"pit": {"end": "2026-10-20", "forbidden_forward_path": True}, "wider_tf": {}},
        "close_in": {"start": "x"},
    }
    clean = strip_outcome_fields(dirty)
    assert "return_pct" not in clean
    assert "exit_at" not in clean
    assert "sell_decision" not in clean
    assert "close_in" not in clean
    assert "wider_tf" not in clean.get("charts", {})
    assert clean["stage"] == "entry_blind"
    assert assert_no_outcome_leakage(clean) == []


def test_build_queue_strips_returns_and_prefers_lab(tmp_path: Path):
    payload = build_entry_blind_review_queue(
        data_dir=tmp_path,
        sealed=_sealed_fixture(),
        lab=_lab_fixture(),
        labels={"events": [], "actioned_review_ids": [], "active_replies": []},
        active_cap=ACTIVE_ATTENTION_CAP,
    )
    assert payload["stage"] == "entry_blind"
    assert payload["influences_live"] is False
    assert payload["active_count"] >= 1
    # Lab buy ranks first under interesting default.
    first = payload["active"][0]
    assert first["population"] == "lab"
    assert first["ticker"] == "LAB.L"
    for row in payload["active"]:
        assert assert_no_outcome_leakage(row) == []
        assert "return_pct" not in row
        assert row.get("stage") == "entry_blind"
        pit = (row.get("charts") or {}).get("pit") or {}
        assert pit.get("end") == str(row.get("entry_at") or "")[:10]
        assert pit.get("forbidden_forward_path") is True
        marks = (row.get("chart_annotations") or {}).get("marks") or []
        assert isinstance(marks, list) and marks
        assert any(m.get("pattern") == "entry_quality" for m in marks)
        assert all(m.get("influences_live") is False for m in marks)


def test_accept_clears_active(tmp_path: Path):
    refresh_entry_blind_review_queue(
        data_dir=tmp_path,
        persist=True,
    )
    # Seed with fixtures via rebuild after writing sealed/lab into tmp.
    # Use build + action on fixture-backed queue instead.
    payload = build_entry_blind_review_queue(
        data_dir=tmp_path,
        sealed=_sealed_fixture(),
        lab=_lab_fixture(),
        labels={"events": [], "actioned_review_ids": [], "active_replies": []},
    )
    assert payload["active"]
    rid = payload["active"][0]["review_id"]
    # Persist queue so resolve_snapshot can find identity.
    from value_investor.storage import write_json

    write_json(tmp_path / "entry_blind_review_queue.json", payload, compact=False)
    result = run_entry_blind_review_action(
        tmp_path,
        review_id=rid,
        decision="accept",
        snapshot=payload["active"][0],
        refresh_queue=False,
    )
    assert result["ok"] is True
    # Rebuild with same fixtures + labels store on disk.
    again = build_entry_blind_review_queue(
        data_dir=tmp_path,
        sealed=_sealed_fixture(),
        lab=_lab_fixture(),
    )
    assert all(row.get("review_id") != rid for row in again["active"])


def test_ops_findings_info_and_not_autofixable():
    findings = ops_findings_from_entry_blind_queue(
        {
            "active_count": 2,
            "new_count": 2,
            "reply_count": 0,
            "actioned_count": 0,
            "unreplied_comments": 0,
            "coverage": {"candidate_buys": 5},
        }
    )
    assert findings
    assert findings[0]["title"] == "Entry-blind review queue (observe)"
    assert findings[0]["auto_fixable"] is False
