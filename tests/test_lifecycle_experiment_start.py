"""Tests for dashboard Start observe-ack helper."""

from __future__ import annotations

from pathlib import Path

import pytest

from value_investor.lifecycle_experiment_start import (
    START_DECISION,
    run_lifecycle_experiment_start,
)
from value_investor.storage import write_json


def _seed(data_dir: Path) -> None:
    paper = data_dir / "paper_automation"
    paper.mkdir(parents=True)
    write_json(
        data_dir / "experiment_assessment.json",
        {
            "schema_version": 1,
            "experiments": [
                {
                    "experiment_id": "entry_dca_overlay",
                    "status": "recommend",
                    "human_ack_required": True,
                    "human_acked": False,
                    "forward_evidence": {
                        "leading_cadence": "dca_4x_weekly",
                        "ready_for_cadence_analysis": True,
                        "scored_count": 5,
                        "tracks_with_closed": 2,
                        "model_independent_hint": True,
                    },
                }
            ],
        },
    )
    write_json(data_dir / "experiment_acks.json", {"schema_version": 1, "acks": []})
    write_json(data_dir / "latest.json", {"reports": [], "run_at": "2026-09-14T00:00:00Z"})
    write_json(
        paper / "learning_tracks_entry_dca.json",
        {
            "leading_cadence": "dca_4x_weekly",
            "scored_count": 5,
            "tracks_with_closed": 2,
            "model_independent_hint": True,
            "readiness": {"ready_for_cadence_analysis": True},
            "tracks": {},
        },
    )


def test_start_records_observe_ack_only(tmp_path: Path):
    _seed(tmp_path)
    result = run_lifecycle_experiment_start(
        tmp_path,
        experiment_id="entry_dca_overlay",
        factor_id="entry_dca_cadence",
        kind="human_ack",
    )
    assert result["ok"] is True
    assert result["observe_only"] is True
    assert result["decision"] == START_DECISION
    assert result["ack"]["decision"] == START_DECISION
    assert Path(result["lifecycle_board_path"]).exists()


def test_start_rejects_optional_execute(tmp_path: Path):
    _seed(tmp_path)
    with pytest.raises(ValueError, match="human_ack"):
        run_lifecycle_experiment_start(
            tmp_path,
            experiment_id="entry_dca_overlay",
            kind="optional_execute",
        )
