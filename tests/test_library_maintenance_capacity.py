"""Crowded maintenance slot width + automated capacity review (L454)."""

from __future__ import annotations

from pathlib import Path

from value_investor.data_library_cli import main as library_main
from value_investor.library_maintenance_capacity import (
    DEFAULT_MAX_MARKETS_WHEN_CROWDED,
    assess_maintenance_capacity,
    empty_capacity,
    record_maintenance_capacity_sample,
    review_maintenance_capacity,
    save_maintenance_capacity,
)
from value_investor.library_maintenance_stagger import plan_maintenance_slot


def test_default_crowded_width_is_two():
    assert DEFAULT_MAX_MARKETS_WHEN_CROWDED == 2
    plan = plan_maintenance_slot(
        ["sp500", "asx200", "euro_depth"],
        last_head="asx200",
    )
    assert plan["staggered"] is True
    assert plan["selected"] == ["euro_depth", "sp500"]
    assert plan["deferred"] == ["asx200"]
    assert plan["max_markets_when_crowded"] == 2


def test_capacity_file_overrides_width(tmp_path: Path):
    capacity = empty_capacity()
    capacity["max_markets_when_crowded"] = 1
    save_maintenance_capacity(tmp_path, capacity)
    plan = plan_maintenance_slot(
        ["sp500", "asx200", "euro_depth"],
        library_root=tmp_path,
        last_head="asx200",
    )
    assert plan["selected"] == ["euro_depth"]
    assert plan["max_markets_when_crowded"] == 1


def test_review_steps_up_with_headroom(tmp_path: Path):
    capacity = empty_capacity()
    capacity["max_markets_when_crowded"] = 2
    capacity["samples"] = [
        {
            "width": 2,
            "configured_count": 7,
            "used_seconds_total": 600,
            "runtime_cutoff_count": 0,
            "error_count": 0,
            "name_cap_hit": False,
        }
        for _ in range(4)
    ]
    save_maintenance_capacity(tmp_path, capacity)
    assessment = assess_maintenance_capacity(tmp_path)
    assert assessment["decision"] == "step_up"
    assert assessment["proposed_width"] == 3
    applied = review_maintenance_capacity(tmp_path, apply=True)
    assert applied["applied"] is True
    assert applied["width_after"] == 3


def test_review_steps_down_on_cutoff(tmp_path: Path):
    capacity = empty_capacity()
    capacity["max_markets_when_crowded"] = 2
    capacity["samples"] = [
        {
            "width": 2,
            "configured_count": 7,
            "used_seconds_total": 800,
            "runtime_cutoff_count": 1,
            "error_count": 0,
        }
        for _ in range(4)
    ]
    save_maintenance_capacity(tmp_path, capacity)
    applied = review_maintenance_capacity(tmp_path, apply=True)
    assert applied["assessment"]["decision"] == "step_down"
    assert applied["width_after"] == 1


def test_review_proposes_matrix_at_sequential_cap(tmp_path: Path):
    capacity = empty_capacity()
    capacity["max_markets_when_crowded"] = 3
    capacity["samples"] = [
        {
            "width": 3,
            "configured_count": 7,
            "used_seconds_total": 900,
            "runtime_cutoff_count": 0,
            "error_count": 0,
        }
        for _ in range(4)
    ]
    save_maintenance_capacity(tmp_path, capacity)
    applied = review_maintenance_capacity(tmp_path, apply=True)
    assert applied["assessment"]["decision"] == "propose_matrix"
    assert applied["matrix_parallel"]["proposed"] is True
    assert applied["matrix_parallel"]["enabled"] is False


def test_record_sample_and_cli(tmp_path: Path, capsys):
    record_maintenance_capacity_sample(
        tmp_path,
        {
            "run_at": "2026-09-23T12:00:00+00:00",
            "markets": ["asx200", "cac40"],
            "configured_markets": ["asx200", "cac40", "sp500"],
            "deferred_markets": ["sp500"],
            "stagger": {"staggered": True, "max_markets_when_crowded": 2},
            "results": [
                {
                    "market_id": "asx200",
                    "targets": ["A", "B"],
                    "used_seconds": 120,
                    "runtime_cutoff": False,
                }
            ],
            "errors": [],
        },
    )
    assert library_main(["maintenance-capacity-review", "--root", str(tmp_path), "--json"]) == 0
    out = capsys.readouterr().out
    assert "decision" in out or "assessment" in out
