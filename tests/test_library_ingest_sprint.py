"""Tests for parallel library ingest sprint."""

from __future__ import annotations

from unittest.mock import patch

from value_investor.library_ingest_dispatch import list_library_ingest_parallel_sprint_markets
from value_investor.library_ingest_sprint import (
    parallel_sprint_markets_needing_ingest,
    run_library_ingest_sprint,
)


def test_list_parallel_sprint_excludes_focus():
    policy = {
        "focus_market": "euro_depth",
        "ingest_parallel_sprint": ["sp500", "euro_depth"],
    }
    assert list_library_ingest_parallel_sprint_markets(policy=policy) == ["sp500"]


def test_list_parallel_sprint_stream_2():
    policy = {
        "focus_market": "euro_depth",
        "ingest_parallel_sprint_2": ["asx200", "euro_depth"],
    }
    assert list_library_ingest_parallel_sprint_markets(policy=policy, parallel_stream=2) == [
        "asx200"
    ]


def test_parallel_sprint_markets_needing_ingest():
    policy = {
        "focus_market": "euro_depth",
        "ingest_parallel_sprint": ["sp500"],
    }
    health = {"unmeasured_buy_tier": 3, "zero_body_buy_tier": 1}
    with patch(
        "value_investor.library_ingest_sprint.snapshot_library_buy_tier_filing_health",
        return_value=health,
    ):
        markets = parallel_sprint_markets_needing_ingest(policy=policy)
    assert markets == ["sp500"]


def test_parallel_sprint_markets_needing_ingest_includes_thin_bodies_at_parity():
    policy = {
        "focus_market": "euro_depth",
        "ingest_parallel_sprint": ["sp500"],
    }
    health = {"unmeasured_buy_tier": 0, "zero_body_buy_tier": 0, "thin_body_buy_tier": 5}
    with patch(
        "value_investor.library_ingest_sprint.snapshot_library_buy_tier_filing_health",
        return_value=health,
    ):
        markets = parallel_sprint_markets_needing_ingest(policy=policy)
    assert markets == ["sp500"]


def test_run_library_ingest_sprint_skips_when_no_work():
    policy = {"focus_market": "euro_depth", "ingest_parallel_sprint": ["sp500"]}
    health = {"unmeasured_buy_tier": 0, "zero_body_buy_tier": 0, "thin_body_buy_tier": 0}
    with (
        patch(
            "value_investor.library_ingest_sprint.load_policy",
            return_value=policy,
        ),
        patch(
            "value_investor.library_ingest_sprint.parallel_sprint_markets_needing_ingest",
            return_value=["sp500"],
        ),
        patch(
            "value_investor.library_ingest_sprint.snapshot_library_buy_tier_filing_health",
            return_value=health,
        ),
        patch("value_investor.library_ingest_sprint.run_library_ingest_loop") as run_loop,
        patch(
            "value_investor.library_ingest_dispatch.refresh_euro_ingest_dispatch",
        ),
    ):
        outcome = run_library_ingest_sprint()
    run_loop.assert_not_called()
    assert outcome.skipped[0]["market_id"] == "sp500"


def test_ingest_sprint_cli_accepts_max_targets_and_parallel_stream():
    """Regression: --parallel-stream must not drop --max-targets (workflow still passes it)."""
    from value_investor.data_library_cli import build_parser

    args = build_parser().parse_args(
        [
            "ingest-sprint",
            "--max-targets",
            "24",
            "--parallel-stream",
            "2",
            "--head-idle",
            "--json",
        ]
    )
    assert args.max_targets == 24
    assert args.parallel_stream == 2
    assert args.head_idle is True
    assert args.json is True

    sched = build_parser().parse_args(["ingest-schedule", "--stream", "2", "--head-idle", "--json"])
    assert sched.parallel_stream == 2
    assert sched.head_idle is True
