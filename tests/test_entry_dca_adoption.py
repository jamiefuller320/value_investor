"""Tests for the entry-DCA review/implementation plan."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.entry_dca_adoption import (
    evaluate_entry_dca_adoption_plan,
    first_entry_by_track,
)
from value_investor.experiment_acks import record_ack


def _write_rollup(
    paper_root: Path,
    *,
    ai_first: int = 1,
    rules_first: int = 0,
    graduated_marks: int = 6,
    beat_market: bool = False,
) -> None:
    paper_root.mkdir(parents=True, exist_ok=True)
    (paper_root / "learning_tracks_entry_dca.json").write_text(
        json.dumps(
            {
                "scored_count": 22,
                "tracks_with_closed": 9,
                "leading_cadence": "dca_4x_weekly",
                "model_independent_hint": True,
                "readiness": {"ready_for_cadence_analysis": True},
                "tracks": {
                    "ai_judgment": {
                        "entry_kind_counts": {"first_entry": ai_first, "recommit": 3},
                        "winning_cadence_counts": {"dca_4x_weekly": 1},
                    },
                    "rules": {
                        "entry_kind_counts": {"first_entry": rules_first, "recommit": 4},
                        "winning_cadence_counts": {},
                    },
                    "ai_judgment_fair": {
                        "entry_kind_counts": {"first_entry": 1},
                        "winning_cadence_counts": {"dca_4x_weekly": 1},
                    },
                    "rules_fair": {
                        "entry_kind_counts": {"first_entry": 1},
                        "winning_cadence_counts": {"dca_4x_weekly": 1},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (paper_root / "learning_tracks_review.json").write_text(
        json.dumps(
            {
                "reviews": {
                    "graduated_allocation": {
                        "metrics": {"equity_marks": graduated_marks, "cost_drag": 0.04}
                    },
                    "ai_judgment": {
                        "metrics": {"beat_market": beat_market, "excess_after_costs": -0.28}
                    },
                    "ai_judgment_fair": {
                        "metrics": {"beat_market": beat_market, "excess_after_costs": -0.1}
                    },
                }
            }
        ),
        encoding="utf-8",
    )


def test_first_entry_by_track_reads_kind_counts(tmp_path: Path):
    paper = tmp_path / "paper"
    _write_rollup(paper, ai_first=1, rules_first=0)
    rollup = json.loads((paper / "learning_tracks_entry_dca.json").read_text(encoding="utf-8"))
    counts = first_entry_by_track(rollup)
    assert counts["ai_judgment"] == 1
    assert counts["rules"] == 0


def test_plan_stays_on_out_of_sample_after_ack(tmp_path: Path):
    data = tmp_path / "data"
    paper = data / "paper_automation"
    _write_rollup(paper, ai_first=1, rules_first=0, graduated_marks=6)
    record_ack(
        data,
        experiment_id="entry_dca_overlay",
        finding={
            "leading_cadence": "dca_4x_weekly",
            "first_entry_by_track": {"ai_judgment": 1, "rules": 0},
        },
    )
    plan = evaluate_entry_dca_adoption_plan(data_dir=data, paper_root=paper)
    by_id = {row["id"]: row for row in plan["stages"]}
    assert plan["acked"] is True
    assert plan["current_stage"] == "out_of_sample_first_entry"
    assert by_id["acked"]["status"] == "done"
    assert by_id["out_of_sample_first_entry"]["ready"] is False
    assert by_id["paper_execute_graduated"]["status"] == "blocked"
    assert by_id["primary_or_live"]["status"] == "blocked"
    assert "Spawn a per-model DCA paper book" in plan["do_not"]


def test_plan_opens_graduated_execute_when_gates_clear(tmp_path: Path):
    data = tmp_path / "data"
    paper = data / "paper_automation"
    _write_rollup(paper, ai_first=3, rules_first=1, graduated_marks=8)
    record_ack(
        data,
        experiment_id="entry_dca_overlay",
        finding={
            "leading_cadence": "dca_4x_weekly",
            "first_entry_by_track": {"ai_judgment": 1, "rules": 0},
        },
    )
    plan = evaluate_entry_dca_adoption_plan(data_dir=data, paper_root=paper)
    by_id = {row["id"]: row for row in plan["stages"]}
    assert by_id["out_of_sample_first_entry"]["ready"] is True
    assert by_id["paper_execute_graduated"]["ready"] is True
    assert by_id["paper_execute_graduated"]["status"] == "open"
    assert by_id["primary_or_live"]["ready"] is False
    assert plan["current_stage"] == "paper_execute_graduated"


def _write_assessment_model(paper_root: Path, *, twins: tuple[str, ...] = ()) -> None:
    (paper_root / "assessment_model.json").write_text(
        json.dumps(
            {
                "primary_track": "ai_judgment_fair",
                "control_track": "buy_tier_level",
                "frozen_tracks": {"ai_judgment": {}, "rules": {}, "rules_fair": {}},
                "twins": {track_id: {"parent_track": "ai_judgment_fair"} for track_id in twins},
            }
        ),
        encoding="utf-8",
    )


def _set_track(paper_root: Path, track_id: str, *, first: int, winners: dict[str, int]) -> None:
    path = paper_root / "learning_tracks_entry_dca.json"
    rollup = json.loads(path.read_text(encoding="utf-8"))
    rollup["tracks"][track_id] = {
        "entry_kind_counts": {"first_entry": first},
        "winning_cadence_counts": winners,
    }
    path.write_text(json.dumps(rollup), encoding="utf-8")


def _ack_with_snapshot(data: Path) -> None:
    record_ack(
        data,
        experiment_id="entry_dca_overlay",
        finding={
            "leading_cadence": "dca_4x_weekly",
            "first_entry_by_track": {
                "ai_judgment": 1,
                "rules": 0,
                "ai_judgment_fair": 1,
                "buy_tier_level": 0,
            },
        },
    )


def test_frozen_books_no_longer_gate_out_of_sample(tmp_path: Path):
    data = tmp_path / "data"
    paper = data / "paper_automation"
    _write_rollup(paper, ai_first=9, rules_first=9, graduated_marks=8)
    _write_assessment_model(paper)
    _set_track(paper, "buy_tier_level", first=0, winners={})
    _ack_with_snapshot(data)

    plan = evaluate_entry_dca_adoption_plan(data_dir=data, paper_root=paper)
    stage = {row["id"]: row for row in plan["stages"]}["out_of_sample_first_entry"]
    assert stage["ready"] is False
    assert stage["evidence"]["live_books"] == {
        "primary": "ai_judgment_fair",
        "control": "buy_tier_level",
    }
    assert stage["evidence"]["first_entry_by_track"] == {
        "ai_judgment_fair": 1,
        "buy_tier_level": 0,
    }
    assert "ai_judgment_fair first_entry>=3" in stage["revisit_when"]
    assert "rules_fair" not in stage["evidence"]["fair_winning_cadence"]


def test_primary_and_control_first_entries_clear_out_of_sample(tmp_path: Path):
    data = tmp_path / "data"
    paper = data / "paper_automation"
    _write_rollup(paper, ai_first=0, rules_first=0, graduated_marks=8)
    _write_assessment_model(paper)
    _set_track(paper, "ai_judgment_fair", first=3, winners={"dca_4x_weekly": 2})
    _set_track(paper, "buy_tier_level", first=5, winners={"dca_2x_weekly": 3})
    _ack_with_snapshot(data)

    plan = evaluate_entry_dca_adoption_plan(data_dir=data, paper_root=paper)
    stage = {row["id"]: row for row in plan["stages"]}["out_of_sample_first_entry"]
    assert stage["ready"] is True
    assert stage["evidence"]["live_winning_cadence"] == {
        "ai_judgment_fair": "dca_4x_weekly",
        "buy_tier_level": "dca_2x_weekly",
    }
    assert plan["current_stage"] == "paper_execute_graduated"


def test_twin_disagreement_blocks_out_of_sample(tmp_path: Path):
    data = tmp_path / "data"
    paper = data / "paper_automation"
    _write_rollup(paper, ai_first=0, rules_first=0, graduated_marks=8)
    _write_assessment_model(paper, twins=("ai_judgment_hold5_fair",))
    _set_track(paper, "ai_judgment_fair", first=3, winners={"dca_4x_weekly": 2})
    _set_track(paper, "buy_tier_level", first=5, winners={"dca_4x_weekly": 3})
    _set_track(paper, "ai_judgment_hold5_fair", first=2, winners={"dca_5x_weekday": 2})
    _ack_with_snapshot(data)

    plan = evaluate_entry_dca_adoption_plan(data_dir=data, paper_root=paper)
    stage = {row["id"]: row for row in plan["stages"]}["out_of_sample_first_entry"]
    assert stage["ready"] is False
    assert stage["evidence"]["fair_winning_cadence"] == {
        "ai_judgment_fair": "dca_4x_weekly",
        "ai_judgment_hold5_fair": "dca_5x_weekday",
    }


def test_frozen_graduated_book_blocks_execute_stage(tmp_path: Path):
    data = tmp_path / "data"
    paper = data / "paper_automation"
    _write_rollup(paper, ai_first=3, rules_first=1, graduated_marks=8)
    (paper / "assessment_model.json").write_text(
        json.dumps({"frozen_tracks": {"graduated_allocation": {"reason": "stress"}}}),
        encoding="utf-8",
    )
    record_ack(
        data,
        experiment_id="entry_dca_overlay",
        finding={
            "leading_cadence": "dca_4x_weekly",
            "first_entry_by_track": {"ai_judgment": 1, "rules": 0},
        },
    )
    plan = evaluate_entry_dca_adoption_plan(data_dir=data, paper_root=paper)
    stage = {row["id"]: row for row in plan["stages"]}["paper_execute_graduated"]
    assert stage["ready"] is False
    assert stage["status"] == "blocked"
    assert stage["evidence"]["graduated_frozen"] is True
