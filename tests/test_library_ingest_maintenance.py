"""Tests for unified library ingest maintenance and parity handoff."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from value_investor.library_graduation import (
    evaluate_ingest_parity_handoff,
    maybe_record_ingest_parity,
)
from value_investor.library_ingest_dispatch import list_library_ingest_maintenance_markets
from value_investor.library_ingest_maintenance import (
    maybe_handoff_focus_on_ingest_parity,
    run_library_ingest_maintenance,
)


def test_list_library_ingest_maintenance_markets_includes_focus_at_parity():
    policy = {"focus_market": "euro_depth", "ingest_parity_markets": ["aex"]}
    health = {
        "unmeasured_buy_tier": 0,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 0,
        "indexed_without_body": 0,
    }
    with patch(
        "value_investor.library_ingest_dispatch.snapshot_library_buy_tier_filing_health",
        return_value=health,
    ):
        markets = list_library_ingest_maintenance_markets(policy=policy)
    assert markets == ["aex", "euro_depth"]


def test_list_library_ingest_maintenance_markets_excludes_stale_parity_list():
    policy = {"focus_market": "euro_depth", "ingest_parity_markets": ["euro_depth"]}
    health = {
        "unmeasured_buy_tier": 0,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 29,
        "indexed_without_body": 94,
    }
    with patch(
        "value_investor.library_ingest_dispatch.snapshot_library_buy_tier_filing_health",
        return_value=health,
    ):
        markets = list_library_ingest_maintenance_markets(policy=policy)
    assert markets == []


def test_maybe_record_ingest_parity_adds_market_once():
    policy: dict = {"ingest_parity_markets": []}
    health = {
        "unmeasured_buy_tier": 0,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 0,
        "indexed_without_body": 0,
    }
    policy, event = maybe_record_ingest_parity(
        policy,
        "euro_depth",
        library_root=Path("/tmp"),
        health=health,
    )
    assert event["recorded"] is True
    assert event["first_time"] is True
    assert policy["ingest_parity_markets"] == ["euro_depth"]

    policy, event2 = maybe_record_ingest_parity(
        policy,
        "euro_depth",
        library_root=Path("/tmp"),
        health=health,
    )
    assert event2["first_time"] is False


def test_evaluate_ingest_parity_handoff_can_advance_when_queue_has_next():
    policy = {
        "focus_market": "euro_depth",
        "market_queue": ["ftse_smallcap"],
        "graduated_markets": [],
        "focus_graduation": {"advance_focus_on_ingest_parity": True},
    }
    health = {
        "unmeasured_buy_tier": 0,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 0,
        "indexed_without_body": 0,
    }
    with patch(
        "value_investor.library_ingest_escalation.snapshot_library_buy_tier_filing_health",
        return_value=health,
    ):
        evaluation = evaluate_ingest_parity_handoff(Path("/tmp"), policy)
    assert evaluation["ingest_parity_met"] is True
    assert evaluation["can_advance"] is True
    assert evaluation["next_focus"] == "ftse_smallcap"


def test_list_library_ingest_maintenance_markets_includes_exhausted_leftovers():
    policy = {
        "focus_market": "euro_depth",
        "ingest_parity_markets": ["euro_depth"],
        "ingest_exhausted_markets": ["sp500"],
    }

    def _health_for(market_id: str, **_kwargs):
        if market_id == "sp500":
            return {
                "unmeasured_buy_tier": 0,
                "zero_body_buy_tier": 0,
                "thin_body_buy_tier": 1,
                "indexed_without_body": 5,
                "ingest_exhausted": True,
                "parked_tickers": ["FICO"],
            }
        return {
            "unmeasured_buy_tier": 0,
            "zero_body_buy_tier": 0,
            "thin_body_buy_tier": 0,
            "indexed_without_body": 0,
        }

    with patch(
        "value_investor.library_ingest_dispatch.snapshot_library_buy_tier_filing_health",
        side_effect=_health_for,
    ):
        markets = list_library_ingest_maintenance_markets(policy=policy)
    assert markets == ["euro_depth", "sp500"]


def test_run_library_ingest_maintenance_runs_exhausted_market():
    exhausted_health = {
        "unmeasured_buy_tier": 0,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 1,
        "indexed_without_body": 5,
        "ingest_exhausted": True,
        "parked_tickers": ["FICO"],
    }
    with (
        patch(
            "value_investor.library_ingest_maintenance.list_library_ingest_maintenance_markets",
            return_value=["sp500"],
        ),
        patch(
            "value_investor.library_ingest_maintenance.snapshot_library_buy_tier_filing_health",
            return_value=exhausted_health,
        ),
        patch("value_investor.library_ingest_maintenance.run_library_ingest_loop") as run_loop,
    ):
        run_loop.return_value.to_dict.return_value = {"market_id": "sp500"}
        outcome = run_library_ingest_maintenance()
    run_loop.assert_called_once()
    assert outcome.errors == []
    assert outcome.markets == ["sp500"]


def test_run_library_ingest_maintenance_skips_market_when_parity_lost():
    with (
        patch(
            "value_investor.library_ingest_maintenance.list_library_ingest_maintenance_markets",
            return_value=["euro_depth"],
        ),
        patch(
            "value_investor.library_ingest_maintenance.snapshot_library_buy_tier_filing_health",
            return_value={"unmeasured_buy_tier": 1, "zero_body_buy_tier": 0},
        ),
        patch("value_investor.library_ingest_maintenance.run_library_ingest_loop") as run_loop,
    ):
        outcome = run_library_ingest_maintenance()
    run_loop.assert_not_called()
    assert "parity lost" in outcome.errors[0]


def test_maybe_handoff_focus_on_ingest_parity_advances_focus(tmp_path: Path):
    policy_path = tmp_path / "policy.json"
    policy = {
        "focus_market": "euro_depth",
        "market_queue": ["ftse_smallcap"],
        "graduated_markets": [],
        "ingest_parity_markets": [],
        "focus_graduation": {"advance_focus_on_ingest_parity": True},
    }
    health = {
        "unmeasured_buy_tier": 0,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 0,
        "indexed_without_body": 0,
    }
    with (
        patch(
            "value_investor.library_ingest_maintenance.load_policy",
            return_value=dict(policy),
        ),
        patch(
            "value_investor.library_ingest_maintenance.save_policy",
            side_effect=lambda p, _path: None,
        ) as save_policy,
        patch(
            "value_investor.library_ingest_maintenance.snapshot_library_buy_tier_filing_health",
            return_value=health,
        ),
        patch(
            "value_investor.euro_depth_ingest_dispatch.refresh_euro_ingest_dispatch",
            return_value={"mode": "sprint"},
        ),
    ):
        event = maybe_handoff_focus_on_ingest_parity(
            market_id="euro_depth",
            library_root=tmp_path,
            policy_path=policy_path,
            health=health,
        )
    assert event["parity_recorded"] is True
    assert event["focus_advanced"] is True
    assert save_policy.call_count >= 2
