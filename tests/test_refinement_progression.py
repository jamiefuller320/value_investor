"""Tests for post-graduation refinement progression (observe-only)."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.experiment_assessment import refresh_experiment_assessment
from value_investor.refinement_progression import (
    apply_graduation_refinements,
    disagreement_theme_ready,
    load_refinement_lanes,
    preserve_lineage_fields,
)


def test_disagreement_theme_fail_closed_when_thin():
    theme = disagreement_theme_ready({"tracks": {"rules": {"veto_sell_count": 1}}})
    assert theme["ready"] is False
    assert theme["fail_closed"] is True


def test_disagreement_theme_ready_with_multi_track_vetoes():
    theme = disagreement_theme_ready(
        {
            "tracks": {
                "rules": {"veto_sell_count": 2},
                "ai_judgment": {"veto_sell_count": 2},
            }
        }
    )
    assert theme["ready"] is True
    assert theme["veto_sell_total"] == 4


def test_preserve_lineage_fields_aligns_aliases():
    row: dict = {}
    preserve_lineage_fields(row, {"parent_id": "entry_dca_overlay"})
    assert row["parent_id"] == "entry_dca_overlay"
    assert row["refinement_of"] == "entry_dca_overlay"


def test_dca_graduation_opens_timing_shift_lane(tmp_path: Path):
    data_dir = tmp_path / "data"
    paper_root = data_dir / "paper_automation"
    paper_root.mkdir(parents=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    (paper_root / "still_in_buy_set").mkdir()

    experiments = [
        {
            "experiment_id": "entry_dca_overlay",
            "kind": "lifecycle_overlay",
            "status": "recommend",
            "human_acked": True,
        }
    ]
    adoption = {
        "acked": True,
        "execute_started": False,
        "finding": {"ready_for_cadence_analysis": True, "leading_cadence": "dca_4x_weekly"},
        "stages": [
            {"id": "acked", "status": "done", "ready": True},
            {"id": "paper_execute_graduated", "status": "blocked", "ready": False},
        ],
    }
    result = apply_graduation_refinements(
        experiments,
        data_dir=data_dir,
        paper_root=paper_root,
        adoption=adoption,
        agree_veto_rollup={"tracks": {}},
        persist=True,
    )
    assert result["influences_live"] is False
    assert any(row["child_id"] == "entry_dca_timing_shift_overlay" for row in result["opened"])
    child = next(
        row for row in experiments if row["experiment_id"] == "entry_dca_timing_shift_overlay"
    )
    assert child["parent_id"] == "entry_dca_overlay"
    assert child["refinement_of"] == "entry_dca_overlay"
    assert child["observe_only"] is True
    assert child["influences_live"] is False
    assert child["status"] == "proposed"
    lanes = load_refinement_lanes(data_dir)
    assert any(row.get("child_id") == "entry_dca_timing_shift_overlay" for row in lanes["lanes"])
    # Sell-gate twin satisfied without spawning a duplicate.
    assert any(row.get("parent_id") == "still_in_buy_set" for row in result["satisfied"])

    # Idempotent on second pass.
    result2 = apply_graduation_refinements(
        experiments,
        data_dir=data_dir,
        paper_root=paper_root,
        adoption=adoption,
        agree_veto_rollup={"tracks": {}},
        persist=True,
    )
    assert result2["opened"] == []
    assert sum(
        1 for row in experiments if row["experiment_id"] == "entry_dca_timing_shift_overlay"
    ) == 1


def test_llm_challenger_fail_closed_without_theme(tmp_path: Path):
    data_dir = tmp_path / "data"
    paper_root = data_dir / "paper_automation"
    paper_root.mkdir(parents=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    result = apply_graduation_refinements(
        [],
        data_dir=data_dir,
        paper_root=paper_root,
        adoption={},
        agree_veto_rollup={"tracks": {"rules": {"veto_sell_count": 1}}},
        persist=True,
    )
    assert not any(row.get("child_id") == "llm_agree_veto_judge_ab" for row in result["opened"])
    assert any(
        row.get("reason") in {"disagreement_theme_absent", "llm_fail_closed_no_disagreement_theme"}
        or row.get("child_id") == "llm_agree_veto_judge_ab"
        for row in result["skipped"]
    )


def test_llm_challenger_opens_when_theme_ready(tmp_path: Path):
    data_dir = tmp_path / "data"
    paper_root = data_dir / "paper_automation"
    paper_root.mkdir(parents=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    experiments: list[dict] = []
    result = apply_graduation_refinements(
        experiments,
        data_dir=data_dir,
        paper_root=paper_root,
        adoption={},
        agree_veto_rollup={
            "tracks": {
                "rules": {"veto_sell_count": 2},
                "ai_judgment": {"veto_sell_count": 2},
            }
        },
        persist=True,
    )
    assert any(row["child_id"] == "llm_agree_veto_judge_ab" for row in result["opened"])
    child = next(row for row in experiments if row["experiment_id"] == "llm_agree_veto_judge_ab")
    assert child["parent_id"] == "llm_agree_veto_shadow"
    assert child["influences_live"] is False
    assert child["forward_evidence"]["llm_evidence_required"] is True


def test_refresh_preserves_refinement_lineage(tmp_path: Path):
    data_dir = tmp_path / "data"
    paper_root = data_dir / "paper_automation"
    paper_root.mkdir(parents=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "experiment_assessment.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "experiments": [
                    {
                        "experiment_id": "entry_dca_timing_shift_overlay",
                        "kind": "lifecycle_overlay_refinement",
                        "title": "DCA timing-shift",
                        "status": "proposed",
                        "parent_id": "entry_dca_overlay",
                        "refinement_of": "entry_dca_overlay",
                        "observe_only": True,
                        "influences_live": False,
                        "initiated_at": "2026-09-01T00:00:00+00:00",
                        "forward_evidence": {"opened_by": "graduation_hook"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (paper_root / "learning_tracks_entry_dca.json").write_text(
        json.dumps({"scored_count": 0, "readiness": {}}),
        encoding="utf-8",
    )
    payload = refresh_experiment_assessment(data_dir, paper_root=paper_root)
    child = next(
        row
        for row in payload["experiments"]
        if row["experiment_id"] == "entry_dca_timing_shift_overlay"
    )
    assert child["parent_id"] == "entry_dca_overlay"
    assert child["refinement_of"] == "entry_dca_overlay"
    assert "refinement_progression" in payload
    slim = payload.get("refinement_progression") or {}
    assert slim["observe_only"] is True
    assert slim["influences_live"] is False
