"""Post-sale notes: one grounded point per closed primary episode, else none."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from value_investor.strategy_book_post_sale_notes import (
    NOTES_FILENAME,
    PRIMARY_EXIT_FAMILY,
    build_post_sale_note,
    build_strategy_book_post_sale_notes,
)
from value_investor.strategy_book_reviews import (
    refresh_strategy_book_reviews,
    registered_exit_family,
)
from value_investor.strategy_book_rules import COLUMN_PRIMARY

NOW = datetime(2026, 11, 25, 6, 0, tzinfo=UTC)
GOOG_ID = "nasdaq100:GOOG:primary:2026-11-19"
REPO = Path(__file__).resolve().parents[1]


def _goog(**overrides: object) -> dict:
    row = {
        "episode_id": GOOG_ID,
        "market": "nasdaq100",
        "ticker": "GOOG",
        "column": "primary",
        "status": "closed",
        "signal_session": "2026-11-19",
        "fill_session": "2026-11-20",
        "exit_signal_session": "2026-11-23",
        "exit_session": "2026-11-24",
        "exit_reason": "thesis_break",
        "exit_fill": 276.58,
        "return_entry_fill": 264.0,
        "fair_cost_return": 0.04415151515151511,
        "matched_excess": 0.003775934570071783,
        "held_sessions": 2,
        "mature": False,
        "provenance_missing": False,
        "influences_live": True,
        "decision_log": [
            {
                "session": "2026-11-20",
                "index": 0,
                "close": 264.0,
                "entry_fill": 264.0,
                "action": "fill",
                "launched": False,
            },
            {
                "session": "2026-11-23",
                "index": 1,
                "close": 279.53,
                "entry_fill": 264.0,
                "action": "thesis_break",
                "launched": False,
                "reasons": ["headwind"],
            },
        ],
    }
    row.update(overrides)
    return row


def test_primary_exit_family_matches_the_review_queue() -> None:
    assert PRIMARY_EXIT_FAMILY == registered_exit_family(COLUMN_PRIMARY)


def test_goog_note_is_the_registered_headwind_rule() -> None:
    note = build_post_sale_note(_goog())
    assert note["influences_live"] is False
    assert note["observe_only"] is True
    assert note["counts_as_evidence"] is True
    assert note["learning_point_status"] == "grounded"
    assert note["missing_inputs"] == []
    assert note["ticker"] == "GOOG"
    assert note["fill_session"] == "2026-11-20"
    assert note["exit_signal_session"] == "2026-11-23"
    assert note["exit_session"] == "2026-11-24"
    assert note["exit_reason"] == "thesis_break"
    assert note["rule_reasons"] == ["headwind"]
    assert note["fair_cost_return_pct"] == 4.415
    assert note["matched_excess_pp"] == 0.378
    assert note["held_sessions"] == 2
    assert note["mature"] is False
    assert note["entry_fill"] == 264.0
    assert note["exit_fill"] == 276.58
    point = note["learning_point"]
    assert point is not None
    assert "registered thesis break" in point
    assert "2026-11-23" in point
    assert "sector verdict headwind" in point
    assert "2026-11-24 at 276.58" in point
    assert "2026-11-20 fill at 264" in point
    assert "+4.415%" in point
    assert "+0.378 percentage points" in point
    assert "Held 2 sessions." in point
    assert "The episode is not mature." in point
    assert "should have" not in point.lower()


def test_missing_reason_does_not_invent_a_point() -> None:
    episode = _goog()
    episode["decision_log"][1]["reasons"] = []
    note = build_post_sale_note(episode)
    assert note["learning_point"] is None
    assert note["learning_point_status"] == "insufficient_data"
    assert "decision_log.reasons" in note["missing_inputs"]
    assert note["influences_live"] is False
    blob = json.dumps(note)
    assert "headwind" not in blob
    assert "sector verdict" not in blob


def test_unknown_reason_code_is_withheld() -> None:
    episode = _goog()
    episode["decision_log"][1]["reasons"] = ["mystery"]
    note = build_post_sale_note(episode)
    assert note["learning_point"] is None
    assert "decision_log.reason_unknown" in note["missing_inputs"]
    assert "mystery" not in json.dumps(note)


def test_a_reason_dated_after_the_exit_is_not_used() -> None:
    episode = _goog()
    episode["decision_log"] = [
        {
            "session": "2026-11-25",
            "index": 3,
            "action": "thesis_break",
            "entry_fill": 264.0,
            "launched": False,
            "reasons": ["declining"],
        }
    ]
    note = build_post_sale_note(episode)
    assert note["learning_point"] is None
    assert "decision_log" in note["missing_inputs"]
    assert "declining" not in json.dumps(note)


def test_provenance_miss_is_not_a_learning_point() -> None:
    note = build_post_sale_note(_goog(provenance_missing=True))
    assert note["learning_point"] is None
    assert "provenance" in note["missing_inputs"]


def test_floor_exit_cites_the_floor_and_a_missing_floor_does_not() -> None:
    grounded = build_post_sale_note(
        _goog(
            episode_id="ftse350:AAA.L:primary:2026-01-05",
            ticker="AAA.L",
            market="ftse350",
            exit_reason="floor_exit",
            exit_signal_session="2026-03-02",
            exit_session="2026-03-03",
            fill_session="2026-01-06",
            held_sessions=40,
            mature=True,
            fair_cost_return=0.12,
            matched_excess=0.08,
            exit_fill=110.0,
            decision_log=[
                {
                    "session": "2026-03-02",
                    "index": 40,
                    "action": "floor_exit",
                    "entry_fill": 100.0,
                    "floor": 0.05,
                    "launched": True,
                }
            ],
        )
    )
    assert grounded["learning_point_status"] == "grounded"
    assert "registered floor exit" in grounded["learning_point"]
    assert "profit floor +5%" in grounded["learning_point"]
    assert "The episode is mature." in grounded["learning_point"]
    withheld = build_post_sale_note(
        _goog(
            exit_reason="floor_exit",
            decision_log=[
                {
                    "session": "2026-11-23",
                    "index": 1,
                    "action": "floor_exit",
                    "floor": None,
                    "launched": True,
                }
            ],
        )
    )
    assert withheld["learning_point"] is None
    assert "decision_log.floor" in withheld["missing_inputs"]


def test_only_closed_primary_episodes_are_collated() -> None:
    observe = {
        "registration_id": "owner-strategy-book-v0",
        "scoring_date": "2026-11-24",
        "influences_live": True,
        "episodes": [
            _goog(),
            _goog(episode_id="nasdaq100:GOOG:primary:open", status="open", exit_session=None, exit_reason=None),
            _goog(
                episode_id="nasdaq100:GOOG:buy_on_signal:2026-11-17",
                column="buy_on_signal",
                exit_reason="ineligible_runs",
            ),
            _goog(episode_id="", ticker="BLANK"),
            _goog(),
        ],
    }
    payload = build_strategy_book_post_sale_notes(observe, now=NOW)
    assert payload["influences_live"] is False
    assert payload["opinion_llm"] is False
    assert payload["auto_fixable"] is False
    assert payload["version_review_only"] is True
    assert payload["counts"]["notes"] == 1
    assert payload["counts"]["grounded"] == 1
    assert payload["counts"]["fail_closed"] == 0
    assert payload["counts"]["skipped_blank_id"] == 1
    assert payload["notes"][0]["episode_id"] == GOOG_ID


def test_refresh_writes_the_notes_store_and_clears_it_when_observe_is_missing(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    observe = data / "strategy_book_observe.json"
    observe.write_text(
        json.dumps({"registration_id": "owner-strategy-book-v0", "episodes": [_goog()]}),
        encoding="utf-8",
    )
    first = refresh_strategy_book_reviews(data_dir=data, now=NOW)
    notes_path = data / NOTES_FILENAME
    assert notes_path.is_file()
    stored = json.loads(notes_path.read_text(encoding="utf-8"))
    assert stored["notes"][0]["learning_point_status"] == "grounded"
    assert stored["influences_live"] is False
    assert first["post_sale_notes"]["grounded"] == 1
    assert first["post_sale_notes"]["influences_live"] is False
    second = refresh_strategy_book_reviews(data_dir=data, now=NOW)
    again = json.loads(notes_path.read_text(encoding="utf-8"))
    assert again["notes"][0]["learning_point"] == stored["notes"][0]["learning_point"]
    assert second["post_sale_notes"]["notes"] == first["post_sale_notes"]["notes"]
    observe.unlink()
    cleared = refresh_strategy_book_reviews(data_dir=data, now=NOW)
    empty = json.loads(notes_path.read_text(encoding="utf-8"))
    assert empty["notes"] == []
    assert empty["observe_status"] == "missing"
    assert empty["influences_live"] is False
    assert cleared["post_sale_notes"]["notes"] == 0
    assert "GOOG" not in notes_path.read_text(encoding="utf-8")


def test_committed_notes_match_the_observe_store() -> None:
    observe = json.loads((REPO / "docs/data/strategy_book_observe.json").read_text(encoding="utf-8"))
    committed = json.loads(
        (REPO / "docs/data/strategy_book_post_sale_notes.json").read_text(encoding="utf-8")
    )
    expected = build_strategy_book_post_sale_notes(observe, now=NOW, observe_status="ok")
    committed = dict(committed)
    expected = dict(expected)
    committed.pop("generated_at", None)
    expected.pop("generated_at", None)
    assert committed == expected
    note = next(row for row in committed["notes"] if row["ticker"] == "GOOG")
    assert note["learning_point_status"] == "grounded"
    assert note["fair_cost_return_pct"] == 4.415
    assert note["matched_excess_pp"] == 0.378
    assert note["held_sessions"] == 2
    assert note["mature"] is False
    assert note["rule_reasons"] == ["headwind"]
    assert committed["influences_live"] is False
