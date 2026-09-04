"""Runtime P2 ingest scheduler: leftover, wait, fill-down."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from value_investor.library_ingest_cascade import (
    HEAD_RELEASE_PHASE2,
    load_cascade_config,
)
from value_investor.library_ingest_scheduler import (
    claim_leftover,
    evaluate_scheduler,
    fill_down_markets,
    leftover_seconds,
    persist_head_runtime_from_loop,
    record_head_run,
)

POLICY = {
    "focus_market": "euro_depth",
    "market_queue": ["sp500", "asx200", "ftse_smallcap"],
    "ingest_parallel_sprint": ["sp500"],
    "ingest_parallel_sprint_2": ["asx200"],
    "ingest_effort_cascade": {"enabled": True, "scheduler_enabled": True},
}
AFTERNOON = datetime(2026, 9, 4, 14, 15, tzinfo=UTC)
PEAK = datetime(2026, 9, 4, 8, 15, tzinfo=UTC)


def _head_state(
    *,
    leftover: float,
    finished_at: datetime,
    allocations: list[dict] | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "head_run": {
            "finished_at": finished_at.isoformat(),
            "leftover_seconds": leftover,
        },
        "allocations": allocations or [],
    }


def test_leftover_seconds_fresh_unclaimed():
    cfg = load_cascade_config(POLICY)
    state = _head_state(leftover=900.0, finished_at=AFTERNOON)
    assert leftover_seconds(state, config=cfg, now=AFTERNOON + timedelta(minutes=10)) == 900.0


def test_leftover_seconds_stale_after_max_age():
    cfg = load_cascade_config(POLICY)
    state = _head_state(leftover=900.0, finished_at=AFTERNOON)
    later = AFTERNOON + timedelta(hours=5)
    assert leftover_seconds(state, config=cfg, now=later) == 0.0


def test_leftover_seconds_subtracts_claims():
    cfg = load_cascade_config(POLICY)
    state = _head_state(
        leftover=900.0,
        finished_at=AFTERNOON,
        allocations=[{"stream": 1, "granted_seconds": 400.0}],
    )
    assert leftover_seconds(state, config=cfg, now=AFTERNOON) == 500.0


def test_fill_down_keeps_assigned_when_it_needs_work():
    assert fill_down_markets(1, policy=POLICY, needing=["sp500", "ftse_smallcap"]) == ["sp500"]
    assert fill_down_markets(2, policy=POLICY, needing=["asx200", "ftse_smallcap"]) == ["asx200"]


def test_fill_down_skips_other_stream_assigned_markets():
    assert fill_down_markets(1, policy=POLICY, needing=["asx200", "ftse_smallcap"]) == [
        "ftse_smallcap"
    ]
    assert fill_down_markets(2, policy=POLICY, needing=["sp500", "ftse_smallcap"]) == [
        "ftse_smallcap"
    ]


def test_evaluate_scheduler_waits_then_skips_after_wait():
    waiting = evaluate_scheduler(
        1,
        policy=POLICY,
        head_at_parity=False,
        needing_markets=["sp500"],
        head_in_progress=True,
        now=AFTERNOON,
    )
    assert waiting.action == "wait"
    assert waiting.code == "wait_predecessor"
    assert waiting.wait_seconds == 2400.0

    skipped = evaluate_scheduler(
        1,
        policy=POLICY,
        head_at_parity=False,
        needing_markets=["sp500"],
        head_in_progress=True,
        waited_seconds=2400.0,
        now=AFTERNOON,
    )
    assert skipped.action == "skip"
    assert skipped.code == "yield_after_wait"


def test_evaluate_scheduler_small_leftover_does_not_shrink_spare():
    state = _head_state(leftover=200.0, finished_at=AFTERNOON)
    decision = evaluate_scheduler(
        1,
        policy=POLICY,
        head_at_parity=False,
        needing_markets=["sp500"],
        leftover_state=state,
        head_in_progress=False,
        now=AFTERNOON,
    )
    assert decision.action == "run"
    assert decision.code == "spare_fraction"
    assert decision.budget_mode == "spare"
    assert decision.max_runtime_seconds == 1050.0
    assert decision.leftover_granted == 0.0


def test_evaluate_scheduler_large_leftover_boosts_spare():
    state = _head_state(leftover=1700.0, finished_at=AFTERNOON)
    decision = evaluate_scheduler(
        1,
        policy=POLICY,
        head_at_parity=False,
        needing_markets=["sp500"],
        leftover_state=state,
        head_in_progress=False,
        now=AFTERNOON,
    )
    assert decision.action == "run"
    assert decision.code == "leftover"
    assert decision.budget_mode == "leftover"
    assert decision.max_runtime_seconds == 1700.0
    assert decision.leftover_granted == 1700.0
    assert decision.max_targets == 19


def test_evaluate_scheduler_peak_hour_fallback_only_when_head_unknown():
    unknown = evaluate_scheduler(
        2,
        policy=POLICY,
        head_at_parity=False,
        needing_markets=["asx200"],
        head_in_progress=None,
        now=PEAK,
    )
    assert unknown.action == "skip"
    assert unknown.code == "peak_hour_fallback"

    idle = evaluate_scheduler(
        2,
        policy=POLICY,
        head_at_parity=False,
        needing_markets=["asx200"],
        head_in_progress=False,
        now=PEAK,
    )
    assert idle.action == "run"
    assert idle.code == "spare_fraction"
    assert idle.max_runtime_seconds == 525.0


def test_evaluate_scheduler_phase2_release():
    policy = {
        **POLICY,
        "ingest_effort_cascade": {
            "enabled": True,
            "scheduler_enabled": True,
            "head_release_when": HEAD_RELEASE_PHASE2,
        },
    }
    still_fat = evaluate_scheduler(
        1,
        policy=policy,
        head_at_parity=False,
        phase2_ready=False,
        needing_markets=["sp500"],
        head_in_progress=False,
        now=AFTERNOON,
    )
    assert still_fat.budget_mode == "spare"
    released = evaluate_scheduler(
        1,
        policy=policy,
        head_at_parity=False,
        phase2_ready=True,
        needing_markets=["sp500"],
        head_in_progress=False,
        now=AFTERNOON,
    )
    assert released.action == "run"
    assert released.code == "head_released"
    assert released.budget_mode == "full"
    assert released.max_runtime_seconds == 2100.0


def test_evaluate_scheduler_disabled_still_uses_static_fractions():
    policy = {
        **POLICY,
        "ingest_effort_cascade": {"enabled": True, "scheduler_enabled": False},
    }
    decision = evaluate_scheduler(
        1,
        policy=policy,
        head_at_parity=False,
        needing_markets=["sp500"],
        leftover_state=_head_state(leftover=1700.0, finished_at=AFTERNOON),
        head_in_progress=False,
        now=AFTERNOON,
    )
    assert decision.code == "spare_fraction"
    assert decision.max_runtime_seconds == 1050.0
    assert decision.leftover_granted == 0.0


def test_claim_leftover_and_persist_head_runtime(tmp_path: Path):
    path = tmp_path / "ingest_cascade_runtime.json"
    state = record_head_run(
        used_seconds=400.0,
        budget_seconds=2100.0,
        runtime_cutoff=False,
        head_market="euro_depth",
        head_at_parity=False,
        now=AFTERNOON,
        path=path,
    )
    assert state["head_run"]["leftover_seconds"] == 1700.0
    cfg = load_cascade_config(POLICY)
    claim_leftover(state, stream=1, granted_seconds=1700.0, now=AFTERNOON, path=path)
    assert leftover_seconds(state, config=cfg, now=AFTERNOON) == 0.0

    cutoff = record_head_run(
        used_seconds=2100.0,
        budget_seconds=2100.0,
        runtime_cutoff=True,
        head_market="euro_depth",
        head_at_parity=False,
        now=AFTERNOON,
        path=path,
    )
    assert cutoff["head_run"]["leftover_seconds"] == 0.0

    written = persist_head_runtime_from_loop(
        market_id="euro_depth",
        used_seconds=500.0,
        budget_seconds=2100.0,
        runtime_cutoff=False,
        head_at_parity=False,
        policy=POLICY,
        library_root=tmp_path,
        now=AFTERNOON,
    )
    assert written is not None
    assert written["head_run"]["leftover_seconds"] == 1600.0
    assert (
        persist_head_runtime_from_loop(
            market_id="sp500",
            used_seconds=100.0,
            budget_seconds=1050.0,
            runtime_cutoff=False,
            head_at_parity=False,
            policy=POLICY,
            library_root=tmp_path,
            now=AFTERNOON,
        )
        is None
    )


def test_dispatch_attaches_fill_down_scheduler_markets():
    from unittest.mock import patch

    from value_investor.library_ingest_dispatch import _scheduler_stream_markets

    evaluation = {
        "parallel_sprint_status": [
            {"market_id": "sp500", "should_run_parallel_ingest": False}
        ],
        "parallel_sprint_2_status": [
            {"market_id": "asx200", "should_run_parallel_ingest": False}
        ],
    }
    gaps = {
        "unmeasured_buy_tier": 2,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 1,
        "indexed_without_body": 4,
    }
    parity = {
        "unmeasured_buy_tier": 0,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 0,
        "indexed_without_body": 0,
    }

    def _health(market_id: str, **_kwargs):
        return gaps if market_id == "ftse_smallcap" else parity

    with patch(
        "value_investor.library_ingest_dispatch.snapshot_library_buy_tier_filing_health",
        side_effect=_health,
    ):
        attached = _scheduler_stream_markets(
            evaluation, policy=POLICY, library_root=Path(".")
        )
    assert attached["scheduler_stream_1_markets"] == ["ftse_smallcap"]
    assert attached["scheduler_stream_2_markets"] == ["ftse_smallcap"]
