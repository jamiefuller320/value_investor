"""Tests for observe-sim screen pass when research is skipped."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from value_investor.library_ladder import _screen_observe_sim_markets


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
