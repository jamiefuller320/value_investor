"""Tests for observe utilization dashboard rollup (L461)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from value_investor.observe_utilization import (
    DECISION_INPUT_FINDING_TITLE,
    FLIP_LAG_FINDING_TITLE,
    SHARD_NAV_FX_FINDING_TITLE,
    build_observe_utilization_snapshot,
    refresh_observe_utilization,
)
from value_investor.storage import write_json


def _write(path: Path, payload: dict) -> None:
    write_json(path, payload, compact=False)


def _quiet_shard_fx(now: datetime) -> dict:
    return {
        "updated_at": (now - timedelta(hours=1)).isoformat(),
        "summary": {
            "market_count": 1,
            "gbp_warp_count": 0,
            "native_twin_active": 1,
            "native_twin_pending": 0,
            "warn_count": 0,
            "warn_markets": [],
        },
    }


def test_observe_utilization_fresh_warn_and_trajectory(tmp_path: Path):
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    flip_path = tmp_path / "buy_tier_flip_lag.json"
    decision_path = tmp_path / "decision_input_inventory.json"
    shard_fx_path = tmp_path / "shard_nav_fx_warp.json"
    ops_path = tmp_path / "ops_status.json"
    store_path = tmp_path / "observe_utilization.json"

    _write(
        flip_path,
        {
            "updated_at": (now - timedelta(hours=1)).isoformat(),
            "summary": {
                "cohort_count": 100,
                "open_not_usable": 40,
                "warn_not_usable": 10,
                "usable_in_window": 60,
                "market_count": 3,
                "blocking_stage_counts": {"no_memo": 8},
            },
        },
    )
    _write(
        decision_path,
        {
            "generated_at": (now - timedelta(hours=1)).isoformat(),
            "summary": {
                "inventory_count": 50,
                "fully_ready_count": 10,
                "names_with_any_gap": 40,
                "gap_counts": {"memo_recent": 40, "overlay_bound": 4},
                "verdict": "memo_recent",
                "sunday_bind_field": "memo_recent",
            },
            "rollup": {
                "verdict": "memo_recent",
                "dominant_gap_field": "memo_recent",
                "gap_counts": {"memo_recent": 40, "overlay_bound": 4},
            },
        },
    )
    _write(shard_fx_path, _quiet_shard_fx(now))
    _write(
        ops_path,
        {
            "run_at": (now - timedelta(minutes=30)).isoformat(),
            "overall": "warn",
            "findings": [
                {
                    "title": FLIP_LAG_FINDING_TITLE,
                    "severity": "warn",
                    "summary": "10 recent buy-tier flip(s) still missing…",
                },
                {
                    "title": DECISION_INPUT_FINDING_TITLE,
                    "severity": "warn",
                    "summary": "Dominant gap memo_recent: 40 of 50 names…",
                },
            ],
        },
    )
    # Seed prior cycle with higher warn/gap counts → improving trajectory.
    _write(
        store_path,
        {
            "schema_version": 1,
            "generated_at": (now - timedelta(hours=12)).isoformat(),
            "history": [
                {
                    "at": (now - timedelta(hours=12)).isoformat(),
                    "buy_tier_flip_lag": {
                        "primary_value": 20,
                        "warn_active": True,
                        "freshness_state": "fresh",
                    },
                    "decision_input_inventory": {
                        "primary_value": 48,
                        "warn_active": True,
                        "freshness_state": "fresh",
                    },
                    "shard_nav_fx_warp": {
                        "primary_value": 0,
                        "warn_active": False,
                        "freshness_state": "fresh",
                    },
                }
            ],
        },
    )

    snap = refresh_observe_utilization(
        store_path=store_path,
        flip_lag_path=flip_path,
        decision_input_path=decision_path,
        shard_nav_fx_path=shard_fx_path,
        ops_status_path=ops_path,
        now=now,
    )
    assert snap["surface_freshness"] == "fresh"
    assert snap["warn_instrument_count"] == 2
    by_id = {row["id"]: row for row in snap["instruments"]}
    flip = by_id["buy_tier_flip_lag"]
    decision = by_id["decision_input_inventory"]
    assert "shard_nav_fx_warp" in by_id
    assert flip["warn_active"] is True
    assert flip["primary_value"] == 10
    assert flip["trajectory"]["direction"] == "improving"
    assert flip["trajectory"]["delta"] == -10
    assert decision["primary_value"] == 40
    assert decision["trajectory"]["direction"] == "improving"
    assert decision["freshness"]["state"] == "fresh"
    assert "Better" in flip["trajectory"]["label"]
    saved = json.loads(store_path.read_text(encoding="utf-8"))
    assert len(saved["history"]) == 2


def test_observe_utilization_stale_and_missing(tmp_path: Path):
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    flip_path = tmp_path / "buy_tier_flip_lag.json"
    decision_path = tmp_path / "decision_input_inventory.json"
    ops_path = tmp_path / "ops_status.json"

    _write(
        flip_path,
        {
            "updated_at": (now - timedelta(hours=48)).isoformat(),
            "summary": {"warn_not_usable": 2, "open_not_usable": 2, "cohort_count": 5},
        },
    )
    # decision_path + shard_fx missing
    _write(ops_path, {"run_at": now.isoformat(), "overall": "ok", "findings": []})

    snap = build_observe_utilization_snapshot(
        flip_lag_path=flip_path,
        decision_input_path=decision_path,
        shard_nav_fx_path=tmp_path / "missing_fx.json",
        ops_status_path=ops_path,
        prior_path=tmp_path / "missing.json",
        now=now,
    )
    by_id = {row["id"]: row for row in snap["instruments"]}
    assert by_id["buy_tier_flip_lag"]["freshness"]["state"] == "stale"
    assert by_id["decision_input_inventory"]["freshness"]["state"] == "missing"
    assert by_id["shard_nav_fx_warp"]["freshness"]["state"] == "missing"
    assert snap["surface_freshness"] == "degraded"
    assert snap["warn_instrument_count"] >= 1


def test_observe_utilization_store_lag_vs_ops(tmp_path: Path):
    """Lagging is a commit-path anomaly after L460 (stores should co-commit)."""
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    flip_path = tmp_path / "flip.json"
    decision_path = tmp_path / "decision.json"
    shard_fx_path = tmp_path / "fx.json"
    ops_path = tmp_path / "ops.json"
    # Store from yesterday; ops ran an hour ago (simulates missed store commit).
    _write(
        flip_path,
        {
            "updated_at": (now - timedelta(hours=20)).isoformat(),
            "summary": {"warn_not_usable": 0, "open_not_usable": 0, "cohort_count": 1},
        },
    )
    _write(
        decision_path,
        {
            "generated_at": (now - timedelta(hours=20)).isoformat(),
            "summary": {
                "inventory_count": 10,
                "fully_ready_count": 10,
                "names_with_any_gap": 0,
                "gap_counts": {},
                "verdict": "P1 green-enough",
            },
            "rollup": {"verdict": "P1 green-enough", "dominant_gap_field": "P1 green-enough"},
        },
    )
    _write(
        shard_fx_path,
        {
            "updated_at": (now - timedelta(hours=20)).isoformat(),
            "summary": {"warn_count": 0, "gbp_warp_count": 0, "market_count": 0},
        },
    )
    _write(ops_path, {"run_at": (now - timedelta(hours=1)).isoformat(), "findings": []})

    snap = build_observe_utilization_snapshot(
        flip_lag_path=flip_path,
        decision_input_path=decision_path,
        shard_nav_fx_path=shard_fx_path,
        ops_status_path=ops_path,
        prior_path=tmp_path / "prior.json",
        now=now,
        stale_after_hours=30.0,
        store_lag_warn_hours=2.0,
    )
    assert snap["surface_freshness"] == "lagging"
    assert all(row["freshness"]["state"] == "lagging" for row in snap["instruments"])
    detail = snap["instruments"][0]["freshness"]["detail"]
    assert "commit" in detail.lower()
    assert "L460" not in detail
    assert "commit-path anomaly" in snap["headline"]
    assert "uncommitted" not in snap["headline"]
    assert "optional (L460)" not in snap["trajectory_summary"]["note"]
    assert "commit with ops-monitor" in snap["trajectory_summary"]["note"]


def test_observe_utilization_co_committed_stores_are_fresh(tmp_path: Path):
    """Happy path after L460: stores refreshed in the same ops cycle → fresh."""
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    flip_path = tmp_path / "flip.json"
    decision_path = tmp_path / "decision.json"
    shard_fx_path = tmp_path / "fx.json"
    ops_path = tmp_path / "ops.json"
    as_of = now - timedelta(minutes=5)
    _write(
        flip_path,
        {
            "updated_at": as_of.isoformat(),
            "summary": {"warn_not_usable": 0, "open_not_usable": 0, "cohort_count": 1},
        },
    )
    _write(
        decision_path,
        {
            "generated_at": as_of.isoformat(),
            "summary": {
                "inventory_count": 10,
                "fully_ready_count": 10,
                "names_with_any_gap": 0,
                "gap_counts": {},
                "verdict": "P1 green-enough",
            },
            "rollup": {"verdict": "P1 green-enough", "dominant_gap_field": "P1 green-enough"},
        },
    )
    _write(
        shard_fx_path,
        {
            "updated_at": as_of.isoformat(),
            "summary": {"warn_count": 0, "gbp_warp_count": 0, "market_count": 1},
        },
    )
    # ops_status run_at a few minutes after store refresh (same job) — not lagging.
    _write(ops_path, {"run_at": (now - timedelta(minutes=2)).isoformat(), "findings": []})

    snap = build_observe_utilization_snapshot(
        flip_lag_path=flip_path,
        decision_input_path=decision_path,
        shard_nav_fx_path=shard_fx_path,
        ops_status_path=ops_path,
        prior_path=tmp_path / "prior.json",
        now=now,
        stale_after_hours=30.0,
        store_lag_warn_hours=2.0,
    )
    assert snap["surface_freshness"] == "fresh"
    assert all(row["freshness"]["state"] == "fresh" for row in snap["instruments"])
    assert "lag" not in snap["headline"].lower()
    assert SHARD_NAV_FX_FINDING_TITLE
