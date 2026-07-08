"""Tests for run-over-run signal diffing."""

import pandas as pd

from value_investor.run_diff import compute_run_diff, format_run_diff_text


def test_compute_run_diff_tracks_upgrades_and_downgrades():
    previous = pd.DataFrame([
        {"ticker": "AAA.L", "name": "Alpha", "signal": "buy"},
        {"ticker": "BBB.L", "name": "Beta", "signal": "strong_buy"},
        {"ticker": "CCC.L", "name": "Gamma", "signal": "hold"},
    ])
    current = pd.DataFrame([
        {"ticker": "AAA.L", "name": "Alpha", "signal": "strong_buy"},
        {"ticker": "BBB.L", "name": "Beta", "signal": "buy"},
        {"ticker": "CCC.L", "name": "Gamma", "signal": "hold"},
    ])

    diff = compute_run_diff(previous, current)

    assert diff.has_changes()
    assert any("Alpha" in item for item in diff.new_strong_buys)
    assert any("Beta" in item for item in diff.lost_strong_buys)
    assert diff.unchanged_top_signals == 1

    text = format_run_diff_text(diff)
    assert "New strong buys" in text
    assert "Unchanged signals" in text
