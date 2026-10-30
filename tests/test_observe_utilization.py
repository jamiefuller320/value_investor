"""Tests for observe utilization dashboard rollup (L461)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from value_investor.observe_utilization import (
    CUE_CONSUMER_MFT_FINDING_TITLE,
    DECISION_INPUT_FINDING_TITLE,
    FLIP_LAG_FINDING_TITLE,
    LAB_LEARNING_PROGRESS_FINDING_TITLE,
    PARALLEL_TIMING_LENSES_FINDING_TITLE,
    SHARD_NAV_FX_FINDING_TITLE,
    build_lab_learning_progress_finding,
    build_observe_utilization_snapshot,
    refresh_observe_utilization,
)
from value_investor.storage import write_json


def _write(path: Path, payload: dict) -> None:
    write_json(path, payload, compact=False)


def _quiet_mft(now: datetime) -> dict:
    return {
        "generated_at": (now - timedelta(hours=1)).isoformat(),
        "pipeline_status": "episode_walker_active",
        "open_lab_episodes": 30,
        "closed_lab_episodes": 87,
        "evolutionary_shadows_eligible": True,
        "declared_incomparable": True,
        "influences_live": False,
        "episode_walker": {"status": "active", "cues_accepted": 117},
        "path_scoreboard": {"smooth_ret_cohort_median": 0.021},
        "start_gate_cohort": {"proposed_n": 0, "frozen_n": 12, "owner_freeze_pending": False},
        "mom_levers": [
            {"id": "stock_choice", "mom_score": None, "status": "diagnostic_partial"},
            {"id": "buy_timing", "mom_score": None, "status": "diagnostic_partial"},
        ],
        "judgment_in_the_round": {"fill_status": "filled"},
    }


def _quiet_parallel_timing_lenses(now: datetime) -> dict:
    return {
        "generated_at": (now - timedelta(hours=1)).isoformat(),
        "asof": (now - timedelta(hours=1)).date().isoformat(),
        "influences_live": False,
        "observe_only": True,
        "package": "M",
        "summary": {
            "candidate_count": 2,
            "buy_candidates": 1,
            "sell_candidates": 1,
            "lenses_looking": 3,
            "lenses_entered": 2,
            "lenses_abandoned": 1,
            "buy_watch_armed": 0,
            "concurrence_mean": 1.0,
            "concurrence_samples": 1,
        },
        "candidates": [],
    }


def _rich_parallel_timing_lenses(now: datetime) -> dict:
    """Lenses store with scored companions for the lab learning strip."""
    base = _quiet_parallel_timing_lenses(now)
    base["candidates"] = [
        {
            "candidate_id": "ptl_test_1",
            "ticker": "AAA.L",
            "side": "buy",
            "favourite_lens_id": "buy_support_bounce",
            "concurrence": {
                "count": 2,
                "lens_ids": ["buy_support_bounce", "buy_news_improve_path"],
                "influences_live": False,
            },
            "lenses": [
                {
                    "lens_id": "buy_support_bounce",
                    "status": "entered",
                    "episode": {
                        "fair_cost_episode_pct": 0.04,
                        "drawdown_depth": -0.08,
                        "drawdown_duration_days": 5,
                    },
                    "outcome_review": {
                        "scored_at": now.date().isoformat(),
                        "had_but_ignored": {
                            "text": "PIT info available but not weighted",
                            "cites": ["B1:cheapness=0.2", "B2:timing_score=0.4"],
                        },
                        "missing_that_might_help": {
                            "text": "Missing news polarity",
                            "cites": ["entry_news_polarity=no_usable_news"],
                        },
                    },
                },
                {
                    "lens_id": "buy_news_improve_path",
                    "status": "entered",
                    "episode": {
                        "fair_cost_episode_pct": 0.02,
                        "drawdown_depth": None,
                        "drawdown_duration_days": None,
                    },
                    "outcome_review": {
                        "scored_at": now.date().isoformat(),
                        "had_but_ignored": {
                            "text": "unused B1",
                            "cites": ["B1:cheapness=0.1"],
                        },
                        "missing_that_might_help": {
                            "text": None,
                            "cites": [],
                        },
                    },
                },
                {
                    "lens_id": "buy_cheap_trend_confirm",
                    "status": "looking",
                    "episode": {
                        "fair_cost_episode_pct": None,
                        "drawdown_depth": None,
                        "drawdown_duration_days": None,
                    },
                    "outcome_review": {
                        "scored_at": None,
                        "had_but_ignored": {"text": None, "cites": []},
                        "missing_that_might_help": {"text": None, "cites": []},
                    },
                },
            ],
        }
    ]
    base["summary"] = {
        "candidate_count": 1,
        "buy_candidates": 1,
        "sell_candidates": 0,
        "lenses_looking": 1,
        "lenses_entered": 2,
        "lenses_abandoned": 0,
        "buy_watch_armed": 0,
        "concurrence_mean": 2.0,
        "concurrence_samples": 1,
    }
    return base


def _quiet_combined(now: datetime) -> dict:
    return {
        "updated_at": (now - timedelta(hours=1)).isoformat(),
        "summary": {
            "market_count": 3,
            "source_files": 0,
            "record_count": 0,
            "open_count": 0,
            "closed_count": 0,
            "first_episode_closed_count": 0,
            "source_records_missing_market_id": 0,
            "warn": False,
        },
    }


def _quiet_archive_miss(now: datetime) -> dict:
    return {
        "updated_at": (now - timedelta(hours=1)).isoformat(),
        "summary": {
            "cohort_count": 0,
            "enter_body_miss_count": 0,
            "miss_rate": 0.0,
            "open_still_missing_bodies": 0,
            "warn": False,
            "by_market": {},
        },
    }


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
    archive_miss_path = tmp_path / "universe_filing_archive_miss_rate.json"
    combined_path = tmp_path / "combined_tagged_learning.json"
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
                "blocking_stage_counts": {"no_key_bodies": 2, "no_memo": 1},
            },
            "open": [
                {
                    "ticker": "AAA.L",
                    "market_id": "sp500",
                    "blocking_stage": "no_key_bodies",
                    "has_memo": True,
                    "memo_home_market": "euro_depth",
                    "hours_since_flip": 30,
                },
                {
                    "ticker": "CAM.L",
                    "market_id": "ftse350",
                    "blocking_stage": "no_memo",
                    "has_memo": False,
                    "memo_home_market": None,
                    "hours_since_flip": 40,
                },
            ],
            "warn_open": [
                {
                    "ticker": "AAA.L",
                    "market_id": "sp500",
                    "blocking_stage": "no_key_bodies",
                    "has_memo": True,
                    "memo_home_market": "euro_depth",
                    "hours_since_flip": 30,
                }
            ],
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
    _write(archive_miss_path, _quiet_archive_miss(now))
    _write(combined_path, _quiet_combined(now))
    mft_path = tmp_path / "cue_consumer_mft_observe.json"
    _write(mft_path, _quiet_mft(now))
    lenses_path = tmp_path / "parallel_timing_lenses.json"
    _write(lenses_path, _quiet_parallel_timing_lenses(now))
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
                {
                    "title": CUE_CONSUMER_MFT_FINDING_TITLE,
                    "severity": "info",
                    "summary": "Walker active; open=30 closed=87.",
                },
                {
                    "title": PARALLEL_TIMING_LENSES_FINDING_TITLE,
                    "severity": "info",
                    "summary": "L652 looking=3 entered=2.",
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
                    "universe_filing_archive_miss_rate": {
                        "primary_value": 0,
                        "warn_active": False,
                        "freshness_state": "fresh",
                    },
                    "combined_tagged_learning": {
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
        archive_miss_path=archive_miss_path,
        combined_tagged_path=combined_path,
        cue_consumer_mft_path=mft_path,
        parallel_timing_lenses_path=lenses_path,
        ops_status_path=ops_path,
        now=now,
    )
    assert snap["surface_freshness"] == "fresh"
    assert snap["warn_instrument_count"] == 2
    by_id = {row["id"]: row for row in snap["instruments"]}
    flip = by_id["buy_tier_flip_lag"]
    decision = by_id["decision_input_inventory"]
    assert "shard_nav_fx_warp" in by_id
    assert "universe_filing_archive_miss_rate" in by_id
    assert "combined_tagged_learning" in by_id
    assert "cue_consumer_mft" in by_id
    assert "parallel_timing_lenses" in by_id
    assert "lab_learning_progress" in by_id
    mft = by_id["cue_consumer_mft"]
    assert mft["warn_active"] is False
    assert mft["primary_value"] == 30
    assert mft["metrics"]["closed_lab_episodes"] == 87
    assert mft["metrics"]["mom_levers"][0]["id"] == "stock_choice"
    assert mft["influences_live"] is False
    lenses = by_id["parallel_timing_lenses"]
    assert lenses["warn_active"] is False
    assert lenses["primary_value"] == 3
    assert lenses["metrics"]["lenses_entered"] == 2
    assert lenses["influences_live"] is False
    lab = by_id["lab_learning_progress"]
    assert lab["warn_active"] is False
    assert lab["influences_live"] is False
    assert lab["metrics"]["lab_open"] == 30
    assert lab["metrics"]["lab_closed"] == 87
    assert lab["primary_value"] == 87  # closed MFT + 0 lens fair-cost in quiet fixture
    assert by_id["combined_tagged_learning"]["warn_active"] is False
    assert by_id["universe_filing_archive_miss_rate"]["warn_active"] is False
    assert flip["warn_active"] is True
    assert flip["primary_value"] == 10
    assert flip["metrics"]["sibling_home_open_count"] == 1
    assert flip["metrics"]["true_no_memo_open_count"] == 1
    assert flip["metrics"]["warn_sample"][0]["memo_home_market"] == "euro_depth"
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
    # decision_path + shard_fx + archive_miss missing
    _write(ops_path, {"run_at": now.isoformat(), "overall": "ok", "findings": []})

    snap = build_observe_utilization_snapshot(
        flip_lag_path=flip_path,
        decision_input_path=decision_path,
        shard_nav_fx_path=tmp_path / "missing_fx.json",
        archive_miss_path=tmp_path / "missing_archive_miss.json",
        combined_tagged_path=tmp_path / "missing_combined.json",
        cue_consumer_mft_path=tmp_path / "missing_mft.json",
        parallel_timing_lenses_path=tmp_path / "missing_lenses.json",
        ops_status_path=ops_path,
        prior_path=tmp_path / "missing.json",
        now=now,
    )
    by_id = {row["id"]: row for row in snap["instruments"]}
    assert by_id["buy_tier_flip_lag"]["freshness"]["state"] == "stale"
    assert by_id["decision_input_inventory"]["freshness"]["state"] == "missing"
    assert by_id["shard_nav_fx_warp"]["freshness"]["state"] == "missing"
    assert by_id["universe_filing_archive_miss_rate"]["freshness"]["state"] == "missing"
    assert by_id["combined_tagged_learning"]["freshness"]["state"] == "missing"
    assert by_id["cue_consumer_mft"]["freshness"]["state"] == "missing"
    assert by_id["parallel_timing_lenses"]["freshness"]["state"] == "missing"
    assert by_id["lab_learning_progress"]["freshness"]["state"] == "missing"
    assert snap["surface_freshness"] == "degraded"
    assert snap["warn_instrument_count"] >= 1


def test_observe_utilization_store_lag_vs_ops(tmp_path: Path):
    """Lagging is a commit-path anomaly after L460 (stores should co-commit)."""
    now = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
    flip_path = tmp_path / "flip.json"
    decision_path = tmp_path / "decision.json"
    shard_fx_path = tmp_path / "fx.json"
    archive_miss_path = tmp_path / "archive_miss.json"
    combined_path = tmp_path / "combined.json"
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
    _write(
        archive_miss_path,
        {
            "updated_at": (now - timedelta(hours=20)).isoformat(),
            "summary": {
                "cohort_count": 0,
                "enter_body_miss_count": 0,
                "miss_rate": 0.0,
                "open_still_missing_bodies": 0,
                "warn": False,
            },
        },
    )
    _write(
        combined_path,
        {
            "updated_at": (now - timedelta(hours=20)).isoformat(),
            "summary": {"source_records_missing_market_id": 0, "closed_count": 0, "warn": False},
        },
    )
    mft_path = tmp_path / "mft.json"
    quiet = _quiet_mft(now - timedelta(hours=19))
    quiet["generated_at"] = (now - timedelta(hours=20)).isoformat()
    _write(mft_path, quiet)
    lenses_path = tmp_path / "lenses.json"
    lenses = _quiet_parallel_timing_lenses(now - timedelta(hours=19))
    lenses["generated_at"] = (now - timedelta(hours=20)).isoformat()
    _write(lenses_path, lenses)
    _write(ops_path, {"run_at": (now - timedelta(hours=1)).isoformat(), "findings": []})

    snap = build_observe_utilization_snapshot(
        flip_lag_path=flip_path,
        decision_input_path=decision_path,
        shard_nav_fx_path=shard_fx_path,
        archive_miss_path=archive_miss_path,
        combined_tagged_path=combined_path,
        cue_consumer_mft_path=mft_path,
        parallel_timing_lenses_path=lenses_path,
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
    archive_miss_path = tmp_path / "archive_miss.json"
    combined_path = tmp_path / "combined.json"
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
    _write(
        archive_miss_path,
        {
            "updated_at": as_of.isoformat(),
            "summary": {
                "cohort_count": 0,
                "enter_body_miss_count": 0,
                "miss_rate": 0.0,
                "open_still_missing_bodies": 0,
                "warn": False,
            },
        },
    )
    _write(
        combined_path,
        {
            "updated_at": as_of.isoformat(),
            "summary": {"source_records_missing_market_id": 0, "closed_count": 0, "warn": False},
        },
    )
    mft_path = tmp_path / "mft.json"
    quiet = _quiet_mft(as_of)
    quiet["generated_at"] = as_of.isoformat()
    _write(mft_path, quiet)
    lenses_path = tmp_path / "lenses.json"
    lenses = _quiet_parallel_timing_lenses(as_of)
    lenses["generated_at"] = as_of.isoformat()
    _write(lenses_path, lenses)
    # ops_status run_at a few minutes after store refresh (same job) — not lagging.
    _write(ops_path, {"run_at": (now - timedelta(minutes=2)).isoformat(), "findings": []})

    snap = build_observe_utilization_snapshot(
        flip_lag_path=flip_path,
        decision_input_path=decision_path,
        shard_nav_fx_path=shard_fx_path,
        archive_miss_path=archive_miss_path,
        combined_tagged_path=combined_path,
        cue_consumer_mft_path=mft_path,
        parallel_timing_lenses_path=lenses_path,
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
    assert any(row["id"] == "cue_consumer_mft" for row in snap["instruments"])
    assert any(row["id"] == "parallel_timing_lenses" for row in snap["instruments"])
    assert any(row["id"] == "lab_learning_progress" for row in snap["instruments"])


def test_lab_learning_progress_companions_and_finding(tmp_path: Path):
    now = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    mft_path = tmp_path / "mft.json"
    lenses_path = tmp_path / "lenses.json"
    ops_path = tmp_path / "ops.json"
    _write(mft_path, _quiet_mft(now))
    _write(lenses_path, _rich_parallel_timing_lenses(now))
    _write(
        ops_path,
        {
            "run_at": (now - timedelta(minutes=10)).isoformat(),
            "findings": [
                {
                    "title": LAB_LEARNING_PROGRESS_FINDING_TITLE,
                    "severity": "info",
                    "summary": "Lab learning progress strip refreshed.",
                }
            ],
        },
    )
    snap = build_observe_utilization_snapshot(
        flip_lag_path=tmp_path / "missing_flip.json",
        decision_input_path=tmp_path / "missing_decision.json",
        shard_nav_fx_path=tmp_path / "missing_fx.json",
        archive_miss_path=tmp_path / "missing_archive.json",
        combined_tagged_path=tmp_path / "missing_combined.json",
        cue_consumer_mft_path=mft_path,
        parallel_timing_lenses_path=lenses_path,
        ops_status_path=ops_path,
        prior_path=tmp_path / "prior.json",
        now=now,
    )
    by_id = {row["id"]: row for row in snap["instruments"]}
    lab = by_id["lab_learning_progress"]
    metrics = lab["metrics"]
    assert metrics["lab_closed"] == 87
    assert metrics["lab_median_fair_cost_pct"] == 0.021
    assert metrics["lenses_entered"] == 2
    assert metrics["concurrence_mean"] == 2.0
    assert metrics["entered_by_lens"]["buy_support_bounce"] == 1
    assert metrics["entered_by_lens"]["buy_news_improve_path"] == 1
    assert metrics["drawdown_depth_median"] == -0.08
    assert metrics["drawdown_duration_days_median"] == 5.0
    assert metrics["lens_fair_cost_n"] == 2
    assert metrics["learning_marks_n"] == 89  # 87 closed + 2 lens fair-cost
    assert lab["primary_value"] == 89
    assert metrics["had_but_ignored_theme_counts"]["B1_cheapness"] == 2
    assert metrics["missing_that_might_help_theme_counts"]["news_polarity"] == 1
    assert metrics["outcome_gap_note"] is None
    assert metrics["concurrence_fair_cost_bands"]
    assert metrics["concurrence_fair_cost_bands"][0]["concurrence"] == 2
    assert lab["influences_live"] is False

    finding = build_lab_learning_progress_finding(
        cue_consumer_mft_path=mft_path,
        parallel_timing_lenses_path=lenses_path,
    )
    assert finding["title"] == LAB_LEARNING_PROGRESS_FINDING_TITLE
    assert finding["auto_fixable"] is False
    assert finding["severity"] == "info"
    assert "influences_live=false" in finding["summary"]
    assert PARALLEL_TIMING_LENSES_FINDING_TITLE  # imported for wiring sanity
