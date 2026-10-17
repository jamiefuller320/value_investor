"""Occupancy badge vs fat-slot bit, and exhausted is not labeled sprint."""

from __future__ import annotations

from pathlib import Path

from value_investor.ingest_occupancy import MISMATCH_TITLE, build_ingest_occupancy
from value_investor.market_status import (
    INGEST_MAINTENANCE,
    INGEST_SPRINT,
    _classify_ingest,
)
from value_investor.ops_monitor import check_ingest_occupancy_mismatch


def test_exhausted_focus_is_not_labeled_sprint() -> None:
    ingest, stream = _classify_ingest(
        "euro_depth",
        focus="euro_depth",
        graduated=set(),
        queue=set(),
        sprint_markets={"euro_depth", "sp500"},
        maintenance_markets=set(),
        sprint_streams={"euro_depth": 1},
        dispatch_mode="exhausted",
    )
    assert ingest == INGEST_MAINTENANCE
    assert stream is None

    still_sprint, _stream = _classify_ingest(
        "euro_depth",
        focus="euro_depth",
        graduated=set(),
        queue=set(),
        sprint_markets={"euro_depth"},
        maintenance_markets=set(),
        sprint_streams={},
        dispatch_mode="sprint",
    )
    assert still_sprint == INGEST_SPRINT


def _row(*, badge: str, bit: bool) -> dict:
    return build_ingest_occupancy(
        dispatch={
            "mode": "exhausted",
            "focus_market": "euro_depth",
            "should_run_sprint_ingest": False,
            "evaluated_at": "2026-10-16T07:33:09+00:00",
            "ingest_cascade": {"head_needs_fat_slot": bit},
            "parallel_sprint_markets": ["sp500"],
            "parallel_sprint_status": [{"market_id": "sp500", "should_run_parallel_ingest": True}],
        },
        market_status={
            "markets": [
                {
                    "market_id": "euro_depth",
                    "ingest": badge,
                    "ingest_reason": "thin=10",
                }
            ]
        },
        pack_run={
            "generated_at": "2026-10-16T00:04:29+00:00",
            "gate": {
                "evaluated_at": "2026-10-16T00:04:29+00:00",
                "focus_pressure_reasons": ["focus_unmeasured_buy_tier=1"],
            },
        },
        tasks={"tasks": [{"status": "open"}, {"status": "done"}]},
    )


def test_mismatch_finding_only_when_badge_and_bit_disagree() -> None:
    agree = _row(badge="sprint", bit=True)
    assert agree["mismatch"] is False
    quiet = _row(badge="maintenance", bit=False)
    assert quiet["mismatch"] is False
    disagree = _row(badge="sprint", bit=False)
    assert disagree["mismatch"] is True
    assert disagree["should_run_sprint_ingest"] is False
    assert disagree["head_needs_fat_slot"] is False
    assert disagree["cold_store_gate_at"] == "2026-10-16T00:04:29+00:00"
    assert disagree["dispatch_evaluated_at"] == "2026-10-16T07:33:09+00:00"
    assert disagree["spare_should_run_parallel_ingest"] is True
    assert disagree["eng_open_count"] == 1


def test_check_fires_only_on_disagreement(tmp_path: Path) -> None:
    store = tmp_path / "ingest_occupancy.json"
    common = {
        "pack_run": {
            "gate": {"evaluated_at": "2026-10-16T00:04:29+00:00", "focus_pressure_reasons": []}
        },
        "tasks": {"tasks": [{"status": "open"}]},
        "store_path": store,
        "persist": True,
    }
    dispatch_base = {
        "mode": "exhausted",
        "focus_market": "euro_depth",
        "should_run_sprint_ingest": False,
        "evaluated_at": "2026-10-16T07:33:09+00:00",
        "parallel_sprint_markets": ["sp500"],
        "parallel_sprint_status": [{"market_id": "sp500", "should_run_parallel_ingest": True}],
    }

    def status(badge: str) -> dict:
        return {
            "markets": [{"market_id": "euro_depth", "ingest": badge, "ingest_reason": "thin=10"}]
        }

    agree = check_ingest_occupancy_mismatch(
        dispatch={**dispatch_base, "ingest_cascade": {"head_needs_fat_slot": True}},
        market_status=status("sprint"),
        **common,
    )
    assert agree == []

    released = check_ingest_occupancy_mismatch(
        dispatch={**dispatch_base, "ingest_cascade": {"head_needs_fat_slot": False}},
        market_status=status("maintenance"),
        **common,
    )
    assert released == []

    mismatch = check_ingest_occupancy_mismatch(
        dispatch={**dispatch_base, "ingest_cascade": {"head_needs_fat_slot": False}},
        market_status=status("sprint"),
        **common,
    )
    assert len(mismatch) == 1
    assert mismatch[0].title == MISMATCH_TITLE
    assert mismatch[0].auto_fixable is False
    assert "head_needs_fat_slot=False" in mismatch[0].summary
    assert store.exists()
