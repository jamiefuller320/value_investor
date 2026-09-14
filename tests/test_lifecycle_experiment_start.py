"""Tests for dashboard Start graduated-execute helper."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from value_investor.lifecycle_experiment_start import (
    START_DECISION,
    run_lifecycle_experiment_start,
)
from value_investor.storage import write_json


def _seed_ready(data_dir: Path) -> Path:
    paper = data_dir / "paper_automation"
    graduated = paper / "graduated_allocation"
    graduated.mkdir(parents=True)
    write_json(
        data_dir / "experiment_assessment.json",
        {
            "schema_version": 1,
            "experiments": [
                {
                    "experiment_id": "entry_dca_overlay",
                    "status": "recommend",
                    "human_ack_required": False,
                    "human_acked": True,
                    "forward_evidence": {
                        "leading_cadence": "dca_4x_weekly",
                        "ready_for_cadence_analysis": True,
                        "scored_count": 12,
                        "tracks_with_closed": 3,
                        "model_independent_hint": True,
                    },
                }
            ],
        },
    )
    write_json(
        data_dir / "experiment_acks.json",
        {
            "schema_version": 1,
            "acks": [
                {
                    "experiment_id": "entry_dca_overlay",
                    "decision": "ack_observe",
                    "status": "open",
                    "acked_at": "2026-09-13T00:00:00+00:00",
                    "finding": {
                        "leading_cadence": "dca_4x_weekly",
                        "ready_for_cadence_analysis": True,
                        "first_entry_by_track": {"ai_judgment": 0, "rules": 0},
                    },
                }
            ],
        },
    )
    write_json(data_dir / "latest.json", {"reports": [], "run_at": "2026-09-14T00:00:00Z"})
    write_json(
        paper / "learning_tracks_entry_dca.json",
        {
            "leading_cadence": "dca_4x_weekly",
            "scored_count": 12,
            "tracks_with_closed": 3,
            "model_independent_hint": True,
            "readiness": {"ready_for_cadence_analysis": True},
            "tracks": {
                "ai_judgment": {"entry_kind_counts": {"first_entry": 4}},
                "rules": {"entry_kind_counts": {"first_entry": 2}},
                "ai_judgment_fair": {
                    "entry_kind_counts": {"first_entry": 1},
                    "winning_cadence_counts": {"dca_4x_weekly": 1},
                },
                "rules_fair": {
                    "entry_kind_counts": {"first_entry": 1},
                    "winning_cadence_counts": {"dca_4x_weekly": 1},
                },
            },
        },
    )
    write_json(
        paper / "learning_tracks_review.json",
        {
            "reviews": {
                "graduated_allocation": {"metrics": {"equity_marks": 10, "cost_drag": 0.02}},
                "ai_judgment_fair": {"metrics": {"beat_market": False}},
            }
        },
    )
    write_json(
        graduated / "config.json",
        {
            "enabled": True,
            "track_id": "graduated_allocation",
            "use_graduated_allocation": True,
            "max_positions": 3,
            "initial_cash": 1000.0,
        },
    )
    return graduated


def test_start_enables_graduated_execute(tmp_path: Path):
    graduated = _seed_ready(tmp_path)
    result = run_lifecycle_experiment_start(
        tmp_path,
        experiment_id="entry_dca_overlay",
        factor_id="entry_dca_cadence",
        kind="optional_execute",
        decision=START_DECISION,
        cadence="dca_4x_weekly",
    )
    assert result["ok"] is True
    assert result["observe_only"] is False
    assert result["decision"] == START_DECISION
    assert result["cadence"] == "dca_4x_weekly"
    assert result["track_id"] == "graduated_allocation"
    cfg = json.loads((graduated / "config.json").read_text())
    assert cfg["entry_dca_execute_cadence"] == "dca_4x_weekly"
    assert (tmp_path / "experiment_starts.json").exists()
    assert Path(result["lifecycle_board_path"]).exists()


def test_start_rejects_human_ack_kind(tmp_path: Path):
    _seed_ready(tmp_path)
    with pytest.raises(ValueError, match="optional_execute"):
        run_lifecycle_experiment_start(
            tmp_path,
            experiment_id="entry_dca_overlay",
            kind="human_ack",
        )


def test_start_rejects_when_gates_not_ready(tmp_path: Path):
    paper = tmp_path / "paper_automation"
    paper.mkdir(parents=True)
    write_json(
        tmp_path / "experiment_assessment.json",
        {
            "schema_version": 1,
            "experiments": [
                {
                    "experiment_id": "entry_dca_overlay",
                    "status": "recommend",
                    "human_acked": True,
                    "forward_evidence": {
                        "leading_cadence": "dca_4x_weekly",
                        "ready_for_cadence_analysis": True,
                        "model_independent_hint": True,
                    },
                }
            ],
        },
    )
    write_json(
        tmp_path / "experiment_acks.json",
        {
            "schema_version": 1,
            "acks": [
                {
                    "experiment_id": "entry_dca_overlay",
                    "decision": "ack_observe",
                    "status": "open",
                    "finding": {"leading_cadence": "dca_4x_weekly"},
                }
            ],
        },
    )
    write_json(tmp_path / "latest.json", {"reports": []})
    write_json(
        paper / "learning_tracks_entry_dca.json",
        {
            "leading_cadence": "dca_4x_weekly",
            "model_independent_hint": True,
            "readiness": {"ready_for_cadence_analysis": True},
            "tracks": {"ai_judgment": {"entry_kind_counts": {"first_entry": 1}}},
        },
    )
    write_json(paper / "learning_tracks_review.json", {"reviews": {}})
    (paper / "graduated_allocation").mkdir()
    write_json(
        paper / "graduated_allocation" / "config.json",
        {"track_id": "graduated_allocation", "use_graduated_allocation": True},
    )
    with pytest.raises(ValueError, match="paper_execute_graduated"):
        run_lifecycle_experiment_start(
            tmp_path,
            experiment_id="entry_dca_overlay",
            kind="optional_execute",
        )
