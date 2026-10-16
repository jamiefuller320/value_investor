"""P2 ingest effort cascade (spare streams yield to the focus fat slot)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from value_investor.library_ingest_cascade import (
    evaluate_ingest_cascade,
    head_market_id,
    load_cascade_config,
    scale_spare_budget,
    should_skip_spare_stream,
)
from value_investor.library_ingest_sprint import run_library_ingest_sprint


def test_head_market_defaults_to_euro_depth():
    assert head_market_id({}) == "euro_depth"
    assert head_market_id({"focus_market": "sp500"}) == "sp500"


def test_scale_spare_budget_full_when_head_at_parity():
    cfg = load_cascade_config({})
    targets, runtime, mode = scale_spare_budget(1, 24, 2100.0, config=cfg, head_needs_fat=False)
    assert (targets, runtime, mode) == (24, 2100.0, "full")


def test_dynamic_width_reserves_host_while_head_needs_slot():
    cfg = load_cascade_config({})
    stream_1 = scale_spare_budget(
        1,
        24,
        2100.0,
        config=cfg,
        head_needs_fat=True,
        unfilled=14,
        head_unfilled=14,
    )
    stream_2 = scale_spare_budget(
        2,
        24,
        2100.0,
        config=cfg,
        head_needs_fat=True,
        unfilled=14,
        head_unfilled=14,
    )
    assert stream_1[2] == "spare"
    assert stream_2[2] == "spare"
    # Host budget 24, head keeps 14, spare gets the 10 left. Stream id is not a fraction.
    assert stream_1[0] == stream_2[0] == 10
    assert stream_1[1] == stream_2[1] == 875.0


def test_dynamic_width_does_not_cut_spares_when_head_released():
    cfg = load_cascade_config({})
    targets, runtime, mode = scale_spare_budget(
        1,
        24,
        2100.0,
        config=cfg,
        head_needs_fat=False,
        unfilled=8,
        head_unfilled=20,
    )
    assert mode == "full"
    assert targets == 8
    assert runtime == 700.0


def test_empty_strand_width_is_zero():
    cfg = load_cascade_config({})
    for head_needs in (True, False):
        targets, runtime, mode = scale_spare_budget(
            1,
            24,
            2100.0,
            config=cfg,
            head_needs_fat=head_needs,
            unfilled=0,
        )
        assert (targets, runtime, mode) == (0, 0.0, "empty")


def test_kind_changes_names_that_fit_in_the_job():
    from value_investor.library_ingest_cascade import dynamic_ingest_width

    filing = dynamic_ingest_width(
        unfilled=400, host_budget_left=400, time_left_seconds=100, kind="filing_body"
    )
    price = dynamic_ingest_width(
        unfilled=400, host_budget_left=400, time_left_seconds=100, kind="daily_price"
    )
    memo = dynamic_ingest_width(
        unfilled=400, host_budget_left=400, time_left_seconds=100, kind="memo"
    )
    assert filing == 1
    assert price == 20
    assert memo == 1


def test_stream_2_skips_peak_overlap_hours_only():
    cfg = load_cascade_config({})
    assert should_skip_spare_stream(2, hour_utc=8, config=cfg, head_needs_fat=True)
    assert should_skip_spare_stream(2, hour_utc=11, config=cfg, head_needs_fat=True)
    assert not should_skip_spare_stream(2, hour_utc=14, config=cfg, head_needs_fat=True)
    assert not should_skip_spare_stream(1, hour_utc=8, config=cfg, head_needs_fat=True)
    assert not should_skip_spare_stream(2, hour_utc=8, config=cfg, head_needs_fat=False)


def test_evaluate_ingest_cascade_skip_stream_2_at_peak():
    decision = evaluate_ingest_cascade(
        {"focus_market": "euro_depth"},
        head_at_parity=False,
        now=datetime(2026, 9, 4, 8, 15, tzinfo=UTC),
    )
    assert decision.head_needs_fat_slot is True
    assert decision.skip_stream_2_now is True
    assert decision.stream_1_mode == "spare"
    assert "yields hour 08" in decision.reason


def test_evaluate_ingest_cascade_full_caps_after_parity():
    decision = evaluate_ingest_cascade(
        {"focus_market": "euro_depth"},
        head_at_parity=True,
        now=datetime(2026, 9, 4, 8, 15, tzinfo=UTC),
    )
    assert decision.head_needs_fat_slot is False
    assert decision.skip_stream_2_now is False
    assert decision.stream_1_mode == "full"
    assert decision.stream_2_mode == "full"


def test_run_sprint_stream_2_yields_at_peak_when_head_has_gaps():
    policy = {
        "focus_market": "euro_depth",
        "ingest_parallel_sprint_2": ["asx200"],
        "ingest_effort_cascade": {"enabled": True},
    }
    head_gaps = {
        "unmeasured_buy_tier": 2,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 1,
        "indexed_without_body": 4,
    }
    with (
        patch(
            "value_investor.library_ingest_sprint.load_policy",
            return_value=policy,
        ),
        patch(
            "value_investor.library_ingest_sprint.snapshot_library_buy_tier_filing_health",
            return_value=head_gaps,
        ),
        patch("value_investor.library_ingest_sprint.run_library_ingest_loop") as run_loop,
        patch(
            "value_investor.library_ingest_dispatch.refresh_euro_ingest_dispatch",
        ),
    ):
        outcome = run_library_ingest_sprint(
            parallel_stream=2,
            now=datetime(2026, 9, 4, 8, 15, tzinfo=UTC),
        )
    run_loop.assert_not_called()
    assert outcome.skipped[0]["reason"] == "peak_hour_fallback"
    assert outcome.max_targets == 7


def test_run_sprint_stream_2_runs_at_peak_when_head_idle():
    policy = {
        "focus_market": "euro_depth",
        "ingest_parallel_sprint_2": ["asx200"],
        "ingest_effort_cascade": {"enabled": True},
    }
    gaps = {
        "unmeasured_buy_tier": 2,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 1,
        "indexed_without_body": 4,
    }

    class _Loop:
        def to_dict(self) -> dict:
            return {"market_id": "asx200", "ok": True}

    with (
        patch(
            "value_investor.library_ingest_sprint.load_policy",
            return_value=policy,
        ),
        patch(
            "value_investor.library_ingest_sprint.snapshot_library_buy_tier_filing_health",
            return_value=gaps,
        ),
        patch(
            "value_investor.library_ingest_sprint.parallel_sprint_markets_needing_ingest",
            return_value=["asx200"],
        ),
        patch(
            "value_investor.library_ingest_sprint.run_library_ingest_loop",
            return_value=_Loop(),
        ) as run_loop,
        patch(
            "value_investor.library_ingest_dispatch.refresh_euro_ingest_dispatch",
        ),
    ):
        outcome = run_library_ingest_sprint(
            parallel_stream=2,
            now=datetime(2026, 9, 4, 8, 15, tzinfo=UTC),
            head_in_progress=False,
        )
    run_loop.assert_called_once()
    assert outcome.max_targets == 7
    assert outcome.max_runtime_seconds == 612.5
    assert run_loop.call_args.kwargs["max_targets"] == 7


def test_run_sprint_stream_2_fills_down_when_assigned_has_no_gaps():
    policy = {
        "focus_market": "euro_depth",
        "market_queue": ["sp500", "asx200", "ftse_smallcap"],
        "ingest_parallel_sprint": ["sp500"],
        "ingest_parallel_sprint_2": ["asx200"],
        "ingest_effort_cascade": {"enabled": True},
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

    class _Loop:
        def to_dict(self) -> dict:
            return {"market_id": "ftse_smallcap", "ok": True}

    def _health(market_id: str, **_kwargs):
        if market_id in {"euro_depth", "ftse_smallcap"}:
            return gaps
        return parity

    with (
        patch(
            "value_investor.library_ingest_sprint.load_policy",
            return_value=policy,
        ),
        patch(
            "value_investor.library_ingest_sprint.snapshot_library_buy_tier_filing_health",
            side_effect=_health,
        ),
        patch(
            "value_investor.library_ingest_sprint.run_library_ingest_loop",
            return_value=_Loop(),
        ) as run_loop,
        patch(
            "value_investor.library_ingest_dispatch.refresh_euro_ingest_dispatch",
        ),
    ):
        outcome = run_library_ingest_sprint(
            parallel_stream=2,
            markets=["ftse_smallcap"],
            now=datetime(2026, 9, 4, 14, 15, tzinfo=UTC),
            head_in_progress=False,
        )
    run_loop.assert_called_once()
    assert outcome.markets == ["ftse_smallcap"]
    assert run_loop.call_args.args[0] == "ftse_smallcap"


def test_run_sprint_stream_1_uses_spare_budget_when_head_has_gaps():
    policy = {
        "focus_market": "euro_depth",
        "ingest_parallel_sprint": ["sp500"],
        "ingest_effort_cascade": {"enabled": True},
    }
    gaps = {
        "unmeasured_buy_tier": 1,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 3,
        "indexed_without_body": 10,
    }

    class _Loop:
        def to_dict(self) -> dict:
            return {"market_id": "sp500", "ok": True}

    with (
        patch(
            "value_investor.library_ingest_sprint.load_policy",
            return_value=policy,
        ),
        patch(
            "value_investor.library_ingest_sprint.snapshot_library_buy_tier_filing_health",
            return_value=gaps,
        ),
        patch(
            "value_investor.library_ingest_sprint.parallel_sprint_markets_needing_ingest",
            return_value=["sp500"],
        ),
        patch(
            "value_investor.library_ingest_sprint.run_library_ingest_loop",
            return_value=_Loop(),
        ) as run_loop,
        patch(
            "value_investor.library_ingest_dispatch.refresh_euro_ingest_dispatch",
        ),
    ):
        outcome = run_library_ingest_sprint(
            parallel_stream=1,
            now=datetime(2026, 9, 4, 14, 15, tzinfo=UTC),
        )
    assert outcome.max_targets == 10
    assert outcome.max_runtime_seconds == 875.0
    run_loop.assert_called_once()
    assert run_loop.call_args.kwargs["max_targets"] == 10
    assert run_loop.call_args.kwargs["max_runtime_seconds"] == 875.0
