"""Tests for L448 market-rotating eng gap burn-down."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from value_investor.library_maintenance_stagger import write_maintenance_slot_cursor
from value_investor.market_eng_gap_burndown import (
    assess_market_eng_gap_burndown,
    rotate_burndown_markets,
    try_market_rotating_eng_gap_burndown,
)
from value_investor.storage import write_json


def test_rotate_burndown_uses_maintenance_cursor(tmp_path: Path):
    write_maintenance_slot_cursor(tmp_path, last_head="asx200", selected=["euro_depth"], deferred=[])
    order = rotate_burndown_markets(["sp500", "asx200", "euro_depth"], library_root=tmp_path)
    assert order[0] == "euro_depth"


def test_try_burndown_skipped_when_open_ingest_task(tmp_path: Path):
    tasks = tmp_path / "engineering_tasks.json"
    write_json(
        tasks,
        {
            "tasks": [
                {
                    "id": "eng-open",
                    "area": "ingest",
                    "status": "open",
                    "source": "ingest_gap_closure",
                    "evidence": {"ticker": "KGF.L"},
                }
            ]
        },
    )
    out = try_market_rotating_eng_gap_burndown(
        apply=False,
        library_root=tmp_path,
        tasks_path=tasks,
    )
    assert out["compiled_count"] == 0
    assert "open ingest engineering task" in out["reason"]


def test_try_burndown_dry_run_picks_rotated_needy_market(tmp_path: Path):
    tasks = tmp_path / "engineering_tasks.json"
    write_json(tasks, {"tasks": []})
    health = {
        "unmeasured_buy_tier": 2,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 0,
        "indexed_without_body": 0,
        "buy_tier_count": 10,
    }
    with (
        patch(
            "value_investor.market_eng_gap_burndown.burndown_market_universe",
            return_value=["sp500", "asx200"],
        ),
        patch(
            "value_investor.market_eng_gap_burndown.snapshot_library_buy_tier_filing_health",
            return_value=health,
        ),
        patch(
            "value_investor.market_eng_gap_burndown.library_ingest_health_stalled",
            return_value=False,
        ),
        patch(
            "value_investor.market_eng_gap_burndown.has_open_library_ingest_task_for_market",
            return_value=False,
        ),
        patch(
            "value_investor.market_eng_gap_burndown.summarize_queue",
            return_value=type("Q", (), {"pr_open_count": 0})(),
        ),
    ):
        out = try_market_rotating_eng_gap_burndown(
            apply=False,
            library_root=tmp_path,
            tasks_path=tasks,
        )
    assert out["market_id"] == "asx200"
    assert "dry-run" in out["reason"]


def test_assess_market_respects_open_task(tmp_path: Path):
    tasks = tmp_path / "engineering_tasks.json"
    write_json(
        tasks,
        {
            "tasks": [
                {
                    "id": "eng-dax",
                    "area": "ingest",
                    "status": "open",
                    "source": "library_ingest_stall",
                    "evidence": {"market_id": "dax"},
                }
            ]
        },
    )
    with patch(
        "value_investor.market_eng_gap_burndown.snapshot_library_buy_tier_filing_health",
        return_value={"unmeasured_buy_tier": 3, "zero_body_buy_tier": 0},
    ):
        out = assess_market_eng_gap_burndown("dax", tasks_path=tasks)
    assert out["needs_work"] is True
    assert out["needs_eng"] is False
    assert out["open_eng_for_market"] is True
