"""Tests for parallel sprint queue auto-advance on ingest parity."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from value_investor.library_ingest_dispatch import (
    list_library_ingest_parallel_sprint_markets,
    next_parallel_sprint_queue_market,
    parallel_sprint_stream_for_market,
    sprint_expansion_market_order,
)
from value_investor.library_ingest_maintenance import (
    maybe_advance_parallel_sprint_on_parity,
    reconcile_parallel_sprint_queues,
    refresh_buy_tier_screen_for_sprint_entry,
    reseed_empty_parallel_sprint_slots,
)


def test_next_parallel_sprint_queue_market_skips_focus_and_occupied():
    policy = {
        "focus_market": "euro_depth",
        "market_queue": ["sp500", "asx200", "ftse_smallcap"],
        "ingest_parallel_sprint": ["sp500"],
        "ingest_parallel_sprint_2": ["asx200"],
    }
    health = {
        "unmeasured_buy_tier": 1,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 0,
        "indexed_without_body": 0,
    }
    with patch(
        "value_investor.library_ingest_dispatch.snapshot_library_buy_tier_filing_health",
        return_value=health,
    ):
        assert next_parallel_sprint_queue_market(policy, vacating="sp500") == "ftse_smallcap"


def test_maybe_advance_parallel_sprint_promotes_next_market(tmp_path: Path):
    policy_path = tmp_path / "policy.json"
    policy = {
        "focus_market": "euro_depth",
        "market_queue": ["sp500", "asx200", "ftse_smallcap", "tsx60"],
        "ingest_parallel_sprint": ["sp500"],
        "ingest_parallel_sprint_2": ["asx200"],
        "ingest_parity_markets": ["euro_depth"],
        "ftse_equivalent_markets": [],
        "focus_graduation": {"advance_parallel_sprint_on_ingest_parity": True},
    }
    parity_health = {
        "unmeasured_buy_tier": 0,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 0,
        "indexed_without_body": 0,
    }
    sprint_health = {
        "unmeasured_buy_tier": 2,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 0,
        "indexed_without_body": 0,
    }

    def _health(market_id: str, **_kwargs):
        if market_id == "sp500":
            return parity_health
        return sprint_health

    saved: dict = {}

    def _save(updated, path):
        saved.clear()
        saved.update(updated)

    with (
        patch(
            "value_investor.library_ingest_maintenance.load_policy",
            return_value=dict(policy),
        ),
        patch("value_investor.library_ingest_maintenance.save_policy", side_effect=_save),
        patch(
            "value_investor.library_ingest_dispatch.snapshot_library_buy_tier_filing_health",
            side_effect=_health,
        ),
        patch(
            "value_investor.library_ingest_dispatch.refresh_euro_ingest_dispatch",
            return_value={},
        ),
        patch(
            "value_investor.library_ingest_maintenance.refresh_buy_tier_screen_for_sprint_entry",
            return_value={"refreshed": True, "market_id": "ftse_smallcap"},
        ) as screen_refresh,
    ):
        event = maybe_advance_parallel_sprint_on_parity(
            market_id="sp500",
            library_root=tmp_path,
            policy_path=policy_path,
            health=parity_health,
        )

    assert event["advanced"] is True
    assert event["from_market"] == "sp500"
    assert event["to_market"] == "ftse_smallcap"
    assert event["parallel_stream"] == 1
    assert event["screen_refresh"]["refreshed"] is True
    screen_refresh.assert_called_once()
    assert list_library_ingest_parallel_sprint_markets(policy=saved) == ["ftse_smallcap"]
    assert "sp500" in saved["ingest_parity_markets"]


def test_maybe_advance_skips_ftse_equivalent_until_learning_ready(tmp_path: Path):
    policy = {
        "focus_market": "euro_depth",
        "market_queue": ["sp500", "ftse_smallcap"],
        "ingest_parallel_sprint": ["sp500"],
        "ftse_equivalent_markets": ["sp500"],
        "ingest_parity_markets": [],
        "focus_graduation": {"advance_parallel_sprint_on_ingest_parity": True},
    }
    parity_health = {
        "unmeasured_buy_tier": 0,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 0,
        "indexed_without_body": 0,
    }
    saved: list[dict] = []
    sprint_health = {
        "unmeasured_buy_tier": 1,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 0,
        "indexed_without_body": 0,
    }

    def _health(market_id: str, **_kwargs):
        if market_id == "ftse_smallcap":
            return sprint_health
        return parity_health

    with (
        patch(
            "value_investor.library_ingest_maintenance.load_policy",
            return_value=policy,
        ),
        patch(
            "value_investor.library_ingest_maintenance.save_policy",
            side_effect=lambda updated, _path: saved.append(dict(updated)),
        ),
        patch(
            "value_investor.library_ingest_dispatch.snapshot_library_buy_tier_filing_health",
            side_effect=_health,
        ),
        patch(
            "value_investor.library_learning_depth.assess_library_learning_depth",
            return_value={"learning_ready": False, "filing_ready": True},
        ),
        patch(
            "value_investor.library_ingest_dispatch.refresh_euro_ingest_dispatch",
            return_value={},
        ),
        patch(
            "value_investor.library_ingest_maintenance.refresh_buy_tier_screen_for_sprint_entry",
            return_value={"refreshed": True, "market_id": "ftse_smallcap"},
        ),
    ):
        event = maybe_advance_parallel_sprint_on_parity(
            market_id="sp500",
            library_root=tmp_path,
            policy_path=tmp_path / "policy.json",
            health=parity_health,
        )

    assert event["advanced"] is True
    assert event["to_market"] == "ftse_smallcap"
    assert event["parity_event"]["reason"] == "learning_depth_not_ready"
    assert "sp500" not in saved[-1]["ingest_parity_markets"]


def test_parallel_sprint_stream_for_market():
    policy = {
        "focus_market": "euro_depth",
        "ingest_parallel_sprint": ["sp500"],
        "ingest_parallel_sprint_2": ["asx200"],
    }
    assert parallel_sprint_stream_for_market("sp500", policy=policy) == 1
    assert parallel_sprint_stream_for_market("asx200", policy=policy) == 2
    assert parallel_sprint_stream_for_market("ftse_smallcap", policy=policy) is None


def test_next_parallel_sprint_picks_unadmitted_when_queue_sprint_complete():
    """Spare slot should front-start DEFAULT_MARKET_QUEUE tail when queue is exhausted."""
    policy = {
        "focus_market": "euro_depth",
        "market_queue": ["sp500", "asx200", "ftse_smallcap", "tsx60"],
        "ingest_parallel_sprint": ["asx200"],
        "ingest_parallel_sprint_2": [],
    }
    complete = {
        "unmeasured_buy_tier": 0,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 0,
        "indexed_without_body": 0,
        "ingest_exhausted": True,
    }
    needs_sprint = {
        "unmeasured_buy_tier": 2,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 0,
        "indexed_without_body": 0,
    }

    def _health(market_id: str, **_kwargs):
        if market_id == "euro_stoxx50":
            return needs_sprint
        if market_id in {"sp500", "asx200", "ftse_smallcap", "tsx60"}:
            return complete
        return complete

    with patch(
        "value_investor.library_ingest_dispatch.snapshot_library_buy_tier_filing_health",
        side_effect=_health,
    ):
        order = sprint_expansion_market_order(policy)
        assert order.index("sp500") < order.index("euro_stoxx50")
        assert next_parallel_sprint_queue_market(policy) == "euro_stoxx50"


def test_reseed_empty_parallel_sprint_slots_fills_queue_order(tmp_path: Path):
    policy_path = tmp_path / "policy.json"
    policy = {
        "focus_market": "euro_depth",
        "market_queue": ["sp500", "asx200", "ftse_smallcap", "tsx60"],
        "ingest_parallel_sprint": [],
        "ingest_parallel_sprint_2": [],
        "focus_graduation": {"advance_parallel_sprint_on_ingest_parity": True},
    }

    def _health(market_id: str, **_kwargs):
        if market_id == "asx200":
            return {
                "unmeasured_buy_tier": 0,
                "zero_body_buy_tier": 0,
                "thin_body_buy_tier": 0,
                "indexed_without_body": 1,
            }
        return {
            "unmeasured_buy_tier": 0,
            "zero_body_buy_tier": 0,
            "thin_body_buy_tier": 0,
            "indexed_without_body": 0,
            "ingest_exhausted": True,
        }

    saved: dict = {}

    def _save(updated, path):
        saved.clear()
        saved.update(updated)

    with (
        patch(
            "value_investor.library_ingest_maintenance.load_policy",
            return_value=dict(policy),
        ),
        patch("value_investor.library_ingest_maintenance.save_policy", side_effect=_save),
        patch(
            "value_investor.library_ingest_dispatch.snapshot_library_buy_tier_filing_health",
            side_effect=_health,
        ),
        patch(
            "value_investor.library_ingest_dispatch.refresh_euro_ingest_dispatch",
            return_value={},
        ),
        patch(
            "value_investor.library_ingest_maintenance.refresh_buy_tier_screen_for_sprint_entry",
            return_value={"refreshed": True, "market_id": "asx200"},
        ),
    ):
        events = reseed_empty_parallel_sprint_slots(
            library_root=tmp_path,
            policy_path=policy_path,
        )

    assert len(events) == 1
    assert events[0]["to_market"] == "asx200"
    assert events[0]["parallel_stream"] == 1
    assert events[0]["screen_refresh"]["refreshed"] is True
    assert saved["ingest_parallel_sprint"] == ["asx200"]
    assert saved["ingest_parallel_sprint_2"] == []


def test_reseed_fills_stream_two_when_two_markets_need_sprint(tmp_path: Path):
    policy_path = tmp_path / "policy.json"
    policy = {
        "focus_market": "euro_depth",
        "market_queue": ["sp500", "asx200", "ftse_smallcap"],
        "ingest_parallel_sprint": [],
        "ingest_parallel_sprint_2": [],
        "focus_graduation": {"advance_parallel_sprint_on_ingest_parity": True},
    }

    def _health(market_id: str, **_kwargs):
        if market_id in {"asx200", "ftse_smallcap"}:
            return {
                "unmeasured_buy_tier": 1,
                "zero_body_buy_tier": 0,
                "thin_body_buy_tier": 0,
                "indexed_without_body": 0,
            }
        return {
            "unmeasured_buy_tier": 0,
            "zero_body_buy_tier": 0,
            "thin_body_buy_tier": 0,
            "indexed_without_body": 0,
            "ingest_exhausted": True,
        }

    saved: dict = {}

    with (
        patch(
            "value_investor.library_ingest_maintenance.load_policy",
            return_value=dict(policy),
        ),
        patch(
            "value_investor.library_ingest_maintenance.save_policy",
            side_effect=lambda updated, _path: saved.update(updated),
        ),
        patch(
            "value_investor.library_ingest_dispatch.snapshot_library_buy_tier_filing_health",
            side_effect=_health,
        ),
        patch(
            "value_investor.library_ingest_dispatch.refresh_euro_ingest_dispatch",
            return_value={},
        ),
        patch(
            "value_investor.library_ingest_maintenance.refresh_buy_tier_screen_for_sprint_entry",
            return_value={"refreshed": True},
        ),
    ):
        events = reseed_empty_parallel_sprint_slots(
            library_root=tmp_path,
            policy_path=policy_path,
        )

    assert [e["to_market"] for e in events] == ["asx200", "ftse_smallcap"]
    assert saved["ingest_parallel_sprint"] == ["asx200"]
    assert saved["ingest_parallel_sprint_2"] == ["ftse_smallcap"]


def test_reconcile_parallel_sprint_queues_advances_at_parity(tmp_path: Path):
    policy = {
        "focus_market": "euro_depth",
        "market_queue": ["sp500", "asx200", "ftse_smallcap"],
        "ingest_parallel_sprint": ["sp500"],
        "ingest_parallel_sprint_2": [],
        "ingest_parity_markets": [],
        "focus_graduation": {"advance_parallel_sprint_on_ingest_parity": True},
    }
    parity_health = {
        "unmeasured_buy_tier": 0,
        "zero_body_buy_tier": 0,
        "thin_body_buy_tier": 0,
        "indexed_without_body": 0,
    }

    with (
        patch(
            "value_investor.library_ingest_maintenance.load_policy",
            return_value=policy,
        ),
        patch(
            "value_investor.library_ingest_maintenance.maybe_advance_parallel_sprint_on_parity",
            return_value={"advanced": True, "from_market": "sp500", "to_market": "ftse_smallcap"},
        ) as advance,
        patch(
            "value_investor.library_ingest_maintenance.reseed_empty_parallel_sprint_slots",
            return_value=[],
        ),
        patch(
            "value_investor.library_ingest_maintenance.snapshot_library_buy_tier_filing_health",
            return_value=parity_health,
        ),
    ):
        events = reconcile_parallel_sprint_queues(
            library_root=tmp_path,
            policy_path=tmp_path / "policy.json",
        )

    assert len(events) == 1
    advance.assert_called_once()


def test_refresh_buy_tier_screen_for_sprint_entry_skips_fresh(tmp_path: Path):
    from datetime import UTC, datetime

    from value_investor.storage import write_json

    market = "dax"
    screen = tmp_path / "markets" / market / "screen"
    screen.mkdir(parents=True)
    write_json(
        screen / "latest_summary.json",
        {
            "market": market,
            "run_at": "2026-09-18T12:00:00+00:00",
            "shortlist_count": 10,
        },
        compact=False,
    )
    with patch(
        "value_investor.library_screen.run_library_screen",
    ) as run_screen:
        result = refresh_buy_tier_screen_for_sprint_entry(
            tmp_path,
            market,
            force=False,
            now=datetime(2026, 9, 19, 13, 0, tzinfo=UTC),
        )
    assert result["skipped"] is True
    assert result["reason"] == "screen_fresh"
    run_screen.assert_not_called()


def test_refresh_buy_tier_screen_for_sprint_entry_force_runs(tmp_path: Path):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from value_investor.storage import write_json

    market = "cac40"
    screen = tmp_path / "markets" / market / "screen"
    screen.mkdir(parents=True)
    write_json(
        screen / "latest_summary.json",
        {
            "market": market,
            "run_at": "2026-08-16T11:58:34+00:00",
            "shortlist_count": 14,
        },
        compact=False,
    )
    fake = SimpleNamespace(
        summary={
            "run_at": "2026-09-19T13:00:00+00:00",
            "shortlist_count": 15,
            "ticker_count": 40,
        }
    )
    with patch(
        "value_investor.library_screen.run_library_screen",
        return_value=fake,
    ) as run_screen:
        result = refresh_buy_tier_screen_for_sprint_entry(
            tmp_path,
            market,
            force=True,
            now=datetime(2026, 9, 19, 13, 0, tzinfo=UTC),
        )
    assert result["refreshed"] is True
    assert result["prior_age_days"] == 34
    run_screen.assert_called_once()
