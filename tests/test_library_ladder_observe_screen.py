"""Tests for observe-sim screen-lite backfill."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from value_investor.library_ladder import (
    _screen_observe_sim_markets,
    _stale_clock_markets,
    observe_sim_screen_should_run,
)


def test_screen_observe_sim_markets_adds_to_screened_set():
    policy = {
        "ladder": {
            "observe_sim_after_screen": True,
            "observe_sim_markets_mode": "explicit",
            "observe_sim_markets": ["sp500", "euro_stoxx50"],
        }
    }
    screened: set[str] = {"iseq20"}
    run_at = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
    with patch("value_investor.library_ladder.run_library_screen") as mock_screen:
        result = _screen_observe_sim_markets(
            Path("/tmp/library"),
            policy,
            screened_markets=screened,
            run_at=run_at,
        )
    assert result["skipped"] is False
    assert result["markets"] == ["sp500", "euro_stoxx50"]
    assert screened == {"iseq20", "sp500", "euro_stoxx50"}
    assert mock_screen.call_count == 2


def test_screen_observe_sim_markets_skips_when_all_screened():
    policy = {
        "ladder": {
            "observe_sim_after_screen": True,
            "observe_sim_markets": ["sp500"],
        }
    }
    screened = {"sp500"}
    result = _screen_observe_sim_markets(
        Path("/tmp/library"),
        policy,
        screened_markets=screened,
        run_at=datetime.now(UTC),
    )
    assert result["skipped"] is True


def test_stale_clock_markets_are_added_even_when_already_in_observe_list(tmp_path: Path):
    policy = {
        "focus_market": "euro_depth",
        "market_queue": ["sp500"],
        "ladder": {
            "observe_sim_after_screen": True,
            "observe_sim_markets_mode": "explicit",
            "observe_sim_markets": ["euro_stoxx50"],
            "observe_sim_include_ingest_profile": False,
            "observe_sim_screen_when_stale": True,
        },
    }
    with patch(
        "value_investor.library_learning_depth.assess_screen_archive_span",
        side_effect=lambda root, mid, **kwargs: {"stale": mid == "sp500"},
    ):
        stale = _stale_clock_markets(tmp_path, policy)
    assert stale == ["sp500"]

    screened: set[str] = {"euro_stoxx50"}
    with (
        patch(
            "value_investor.library_learning_depth.assess_screen_archive_span",
            side_effect=lambda root, mid, **kwargs: {"stale": mid == "sp500"},
        ),
        patch("value_investor.library_ladder.run_library_screen") as mock_screen,
        patch("value_investor.library_learning_depth.assess_library_learning_depth"),
    ):
        result = _screen_observe_sim_markets(
            tmp_path,
            policy,
            screened_markets=screened,
            run_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        )
    assert result["skipped"] is False
    assert "sp500" in result["markets"]
    assert result["stale_clock_added"] == ["sp500"]
    assert mock_screen.call_count == 1


def test_observe_sim_screen_runs_even_when_research_ran():
    enabled, reason = observe_sim_screen_should_run(skip_screen=False, ladder_cfg={})
    assert enabled is True
    assert reason == ""
    enabled, reason = observe_sim_screen_should_run(
        skip_screen=False,
        ladder_cfg={"observe_sim_screen_when_research_skipped": False},
    )
    assert enabled is False
    assert "observe_sim_screen_when_research_skipped" in reason
    enabled, reason = observe_sim_screen_should_run(skip_screen=True, ladder_cfg={})
    assert enabled is False
    assert reason == "screen-lite disabled"
    enabled, reason = observe_sim_screen_should_run(
        skip_screen=False,
        ladder_cfg={"observe_sim_screen_missing_markets": False},
    )
    assert enabled is False
    assert "observe_sim_screen_missing_markets" in reason
