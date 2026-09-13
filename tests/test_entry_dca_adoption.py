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
        finding={"leading_cadence": "dca_4x_weekly", "first_entry_by_track": {"ai_judgment": 1, "rules": 0}},
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
