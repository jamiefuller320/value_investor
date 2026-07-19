"""Tests for shared decreasing-resolution retention helpers."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from value_investor.library_retention import dates_to_remove
from value_investor.signal_stability import HISTORY_FILE, prune_signal_history_rows


def test_dates_to_remove_keeps_dense_and_thins_coarse():
    today = date(2026, 7, 19)
    items = [
        ("dense_a", date(2026, 7, 10)),
        ("dense_b", date(2026, 7, 1)),
        ("month_old", date(2025, 8, 5)),
        ("month_new", date(2025, 8, 28)),
        ("q_old", date(2020, 1, 10)),
        ("q_new", date(2020, 2, 20)),
        ("q_lone", date(2019, 8, 1)),
    ]
    drop = dates_to_remove(items, keep_days=30, monthly_until_days=400, now=today)
    assert drop == {"month_old", "q_old"}
    assert "dense_a" not in drop and "dense_b" not in drop
    assert "q_lone" not in drop


def test_prune_signal_history_rows_thins_old_runs(tmp_path: Path):
    screen = tmp_path / "screen"
    screen.mkdir()
    path = screen / HISTORY_FILE
    frame = pd.DataFrame(
        [
            {
                "run_at": "2020-01-10T01:00:00+00:00",
                "ticker": "AAA",
                "signal": "buy",
                "signal_rank": 3,
                "conviction_score": 0.5,
                "data_quality_score": 0.8,
            },
            {
                "run_at": "2020-02-20T01:00:00+00:00",
                "ticker": "AAA",
                "signal": "buy",
                "signal_rank": 3,
                "conviction_score": 0.6,
                "data_quality_score": 0.8,
            },
            {
                "run_at": "2026-07-15T01:00:00+00:00",
                "ticker": "AAA",
                "signal": "buy",
                "signal_rank": 3,
                "conviction_score": 0.7,
                "data_quality_score": 0.8,
            },
        ]
    )
    frame.to_csv(path, index=False)

    stats = prune_signal_history_rows(
        screen,
        keep_days=30,
        monthly_until_days=90,
        now=date(2026, 7, 19),
    )
    assert stats["removed_runs"] == 1
    assert stats["removed_rows"] == 1
    kept = pd.read_csv(path)
    assert "2020-01-10T01:00:00+00:00" not in set(kept["run_at"].astype(str))
    assert "2020-02-20T01:00:00+00:00" in set(kept["run_at"].astype(str))
    assert "2026-07-15T01:00:00+00:00" in set(kept["run_at"].astype(str))
