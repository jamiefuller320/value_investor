"""Tests for L323 maintenance-slot stagger."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from value_investor.library_ingest_maintenance import run_library_ingest_maintenance
from value_investor.library_maintenance_stagger import (
    plan_maintenance_slot,
    rotate_after,
)


def test_rotate_after_starts_past_last_head():
    assert rotate_after(["sp500", "asx200", "euro_depth"], "asx200")[0] == "euro_depth"
    assert rotate_after(["sp500", "asx200", "euro_depth"], "sp500")[0] == "asx200"
    assert rotate_after(["sp500"], "missing") == ["sp500"]


def test_plan_fits_two_markets_in_one_job():
    plan = plan_maintenance_slot(["asx200", "sp500"])
    assert plan["staggered"] is False
    assert plan["selected"] == ["asx200", "sp500"]
    assert plan["deferred"] == []


def test_plan_rotates_one_when_three_markets():
    plan = plan_maintenance_slot(
        ["sp500", "asx200", "euro_depth"],
        last_head="asx200",
    )
    assert plan["staggered"] is True
    assert plan["selected"] == ["euro_depth"]
    assert plan["deferred"] == ["sp500", "asx200"]


def test_run_maintenance_staggers_three_default_markets(tmp_path: Path):
    health = {
        "unmeasured_buy_tier": 0,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 1,
        "indexed_without_body": 0,
        "ingest_exhausted": True,
    }
    with (
        patch(
            "value_investor.library_ingest_maintenance.list_library_ingest_maintenance_markets",
            return_value=["asx200", "euro_depth", "sp500"],
        ),
        patch(
            "value_investor.library_ingest_maintenance.load_policy",
            return_value={"ladder": {"admitted_learning_markets": ["asx200", "sp500"]}},
        ),
        patch(
            "value_investor.library_ingest_maintenance.snapshot_library_buy_tier_filing_health",
            return_value=health,
        ),
        patch(
            "value_investor.library_ingest_maintenance.should_keep_on_library_maintenance",
            return_value=True,
        ),
        patch("value_investor.library_ingest_maintenance.run_library_ingest_loop") as run_loop,
    ):
        run_loop.return_value.to_dict.return_value = {"market_id": "asx200"}
        outcome = run_library_ingest_maintenance(library_root=tmp_path)
    assert outcome.stagger["staggered"] is True
    assert outcome.markets == ["asx200"]
    assert outcome.deferred_markets == ["euro_depth", "sp500"]
    run_loop.assert_called_once()
    cursor = tmp_path / "maintenance_slot_cursor.json"
    assert cursor.exists()


def test_explicit_markets_bypass_stagger(tmp_path: Path):
    health = {
        "unmeasured_buy_tier": 0,
        "zero_body_buy_tier": 0,
        "ingest_exhausted": True,
    }
    with (
        patch(
            "value_investor.library_ingest_maintenance.snapshot_library_buy_tier_filing_health",
            return_value=health,
        ),
        patch(
            "value_investor.library_ingest_maintenance.should_keep_on_library_maintenance",
            return_value=True,
        ),
        patch("value_investor.library_ingest_maintenance.run_library_ingest_loop") as run_loop,
    ):
        run_loop.return_value.to_dict.return_value = {"ok": True}
        outcome = run_library_ingest_maintenance(
            library_root=tmp_path,
            markets=["asx200", "euro_depth", "sp500"],
        )
    assert outcome.stagger["reason"] == "explicit_markets"
    assert outcome.markets == ["asx200", "euro_depth", "sp500"]
    assert run_loop.call_count == 3
