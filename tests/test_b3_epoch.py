"""Tests for B3 evidentiary demotion + matched-30 cold-start."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from value_investor.assessment_model import ASSESSMENT_MODEL_FILENAME, frozen_tracks, load_assessment_model
from value_investor.b3_epoch import POLICY_ID, apply_b3_lock
from value_investor.fair_cost_lab import (
    AI_JUDGMENT_FAIR_TRACK_ID,
    AI_MATCHED30_TRACK_ID,
    BUY_TIER_MATCHED30_TRACK_ID,
    spawn_matched30_twins,
)
from value_investor.paper_automation import (
    BUY_TIER_LEVEL_TRACK_ID,
    CONFIG_FILENAME,
    ensure_learning_track_configs,
)


WHEN = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def _seed_assessment_root(tmp_path: Path) -> Path:
    base = tmp_path / "paper"
    ensure_learning_track_configs(base)
    # Minimal fair primary config so matched-30 can copy knobs.
    from value_investor.fair_cost_lab import spawn_fair_cost_lab

    spawn_fair_cost_lab(base, force=True)
    model = {
        "schema_version": 1,
        "primary_track": AI_JUDGMENT_FAIR_TRACK_ID,
        "control_track": BUY_TIER_LEVEL_TRACK_ID,
        "frozen_tracks": {},
        "twins": {
            "ai_judgment_hold5_fair": {
                "started_at": "2026-10-06T00:00:00+00:00",
                "parent_track": AI_JUDGMENT_FAIR_TRACK_ID,
                "varied": {"exit_confirm_screens": {"parent": 2, "twin": 5}},
                "parent_knobs_at_start": {"max_positions": 3},
                "learning_question": "hold5",
                "readiness_gate": "gate",
            },
            "ai_judgment_graduated_fair": {
                "started_at": "2026-10-06T00:00:00+00:00",
                "parent_track": AI_JUDGMENT_FAIR_TRACK_ID,
                "varied": {"use_graduated_allocation": {"parent": False, "twin": True}},
                "parent_knobs_at_start": {"max_positions": 3},
                "learning_question": "grad",
                "readiness_gate": "gate",
            },
        },
        "policy_changes": [],
        "switches": [],
    }
    # Ensure twin dirs exist so freeze can capture final records.
    for tid in ("ai_judgment_hold5_fair", "ai_judgment_graduated_fair"):
        tdir = base / tid
        tdir.mkdir(parents=True, exist_ok=True)
        parent_cfg = json.loads(
            (base / AI_JUDGMENT_FAIR_TRACK_ID / CONFIG_FILENAME).read_text(encoding="utf-8")
        )
        parent_cfg["track_id"] = tid
        (tdir / CONFIG_FILENAME).write_text(json.dumps(parent_cfg, indent=2) + "\n", encoding="utf-8")
        (tdir / "automated_fund.json").write_text(
            json.dumps(
                {
                    "holdings": {"KLR.L": {}},
                    "trades": [{}],
                    "equity_curve": [
                        {
                            "at": "2026-10-14T09:30:00+01:00",
                            "portfolio_value": 900.0,
                            "contributed_capital": 1000.0,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
    (base / ASSESSMENT_MODEL_FILENAME).write_text(json.dumps(model, indent=2) + "\n", encoding="utf-8")
    return base


def test_spawn_matched30_twins_idempotent(tmp_path: Path):
    base = _seed_assessment_root(tmp_path)
    first = spawn_matched30_twins(base, dry_run=False)
    assert first[AI_MATCHED30_TRACK_ID]["spawned"] is True
    assert first[AI_MATCHED30_TRACK_ID]["created"] is True
    assert first[BUY_TIER_MATCHED30_TRACK_ID]["spawned"] is True
    ai_cfg = json.loads(
        (base / AI_MATCHED30_TRACK_ID / CONFIG_FILENAME).read_text(encoding="utf-8")
    )
    ctrl_cfg = json.loads(
        (base / BUY_TIER_MATCHED30_TRACK_ID / CONFIG_FILENAME).read_text(encoding="utf-8")
    )
    assert ai_cfg["max_positions"] == 30
    assert ai_cfg["sector_cap"] == 0.2
    assert ai_cfg["is_churn_policy_twin"] is True
    assert ctrl_cfg["max_positions"] == 30
    assert ctrl_cfg["sector_cap"] == 0.2
    assert ctrl_cfg["min_conviction"] == 0.0
    assert ctrl_cfg["require_research_accumulate"] is False
    second = spawn_matched30_twins(base, dry_run=False)
    assert second[AI_MATCHED30_TRACK_ID]["created"] is False
    assert second[AI_MATCHED30_TRACK_ID]["reason"] == "already exists"


def test_apply_b3_lock_demotes_freezes_and_registers(tmp_path: Path):
    base = _seed_assessment_root(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    result = apply_b3_lock(base, data_dir=data, now=WHEN)
    model = load_assessment_model(base)
    assert model["primary_track"] == AI_JUDGMENT_FAIR_TRACK_ID
    assert model["control_track"] == BUY_TIER_LEVEL_TRACK_ID
    policy_ids = {row["id"] for row in model.get("policy_changes") or []}
    assert POLICY_ID in policy_ids
    frozen = frozen_tracks(base)
    assert "ai_judgment_hold5_fair" in frozen
    assert "ai_judgment_graduated_fair" in frozen
    assert AI_JUDGMENT_FAIR_TRACK_ID not in frozen
    assert AI_MATCHED30_TRACK_ID in (model.get("twins") or {})
    assert BUY_TIER_MATCHED30_TRACK_ID in (model.get("twins") or {})
    assert (data / "n210_ai_judgment_observe.json").exists()
    assert (data / "n210_ai_judgment_registration.json").exists()
    assert (data / "b3_scoreboard_epoch_registration.json").exists()
    assert result["n210_registration_id"] == "strand-e-ai-judgment-fixed-stake-v0"
    # Idempotent policy + freeze
    again = apply_b3_lock(base, data_dir=data, now=WHEN)
    model2 = load_assessment_model(base)
    assert sum(1 for row in model2["policy_changes"] if row["id"] == POLICY_ID) == 1
    assert again["primary_track"] == AI_JUDGMENT_FAIR_TRACK_ID
