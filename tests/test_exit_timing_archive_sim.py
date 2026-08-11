"""Tests for observe-only exit-timing archive near-miss simulation."""

import json
from pathlib import Path

from value_investor.backtest import HISTORY_DIR
from value_investor.exit_timing_archive_sim import (
    COHORTS_FILENAME,
    REVIEW_FILENAME,
    ExitTimingArchiveSimConfig,
    _is_near_miss,
    run_exit_timing_archive_sim,
)


def _write_history_snapshot(
    output_dir: Path,
    filename: str,
    run_at: str,
    prices: dict[str, float],
    signals: list[dict],
) -> None:
    history = output_dir / HISTORY_DIR
    history.mkdir(parents=True, exist_ok=True)
    payload = {"run_at": run_at, "prices": prices, "signals": signals}
    (history / filename).write_text(json.dumps(payload), encoding="utf-8")


def test_is_near_miss_filters_buy_tier():
    cfg = ExitTimingArchiveSimConfig(min_conviction=0.3)
    assert _is_near_miss({"ticker": "A.L", "signal": "hold", "conviction_score": 0.5}, cfg)
    assert not _is_near_miss({"ticker": "B.L", "signal": "buy", "conviction_score": 0.9}, cfg)
    assert not _is_near_miss({"ticker": "C.L", "signal": "hold", "conviction_score": 0.1}, cfg)


def test_run_exit_timing_archive_sim_scores_episodes(tmp_path: Path):
    signals_hold = {
        "ticker": "NEAR.L",
        "signal": "hold",
        "conviction_score": 0.55,
        "data_quality_score": 0.85,
    }
    signals_buy = {
        "ticker": "BUY.L",
        "signal": "buy",
        "conviction_score": 0.9,
        "data_quality_score": 0.9,
    }
    rows = [signals_hold, signals_buy]
    _write_history_snapshot(
        tmp_path,
        "run_20260101_100000.json",
        "2026-01-01T10:00:00+00:00",
        {"NEAR.L": 100.0, "BUY.L": 50.0, "^FTSE": 8000.0},
        rows,
    )
    _write_history_snapshot(
        tmp_path,
        "run_20260129_100000.json",
        "2026-01-29T10:00:00+00:00",
        {"NEAR.L": 108.0, "BUY.L": 52.0, "^FTSE": 8100.0},
        rows,
    )
    _write_history_snapshot(
        tmp_path,
        "run_20260326_100000.json",
        "2026-03-26T10:00:00+00:00",
        {"NEAR.L": 95.0, "BUY.L": 60.0, "^FTSE": 8200.0},
        rows,
    )

    review = run_exit_timing_archive_sim(
        tmp_path,
        config=ExitTimingArchiveSimConfig(min_conviction=0.35, max_episodes_per_week=5),
    )
    assert review["scope"] == "archive_near_miss"
    assert (tmp_path / COHORTS_FILENAME).exists()
    assert (tmp_path / REVIEW_FILENAME).exists()
    assert review["episodes_opened"]["hold_recovery"] >= 1
    assert review["episodes_opened"]["swap_rotation"] >= 1
    closed_hold = (review.get("hold_recovery") or {}).get("closed") or {}
    assert closed_hold.get("count", 0) >= 1


def test_run_exit_timing_archive_sim_needs_two_snapshots(tmp_path: Path):
    review = run_exit_timing_archive_sim(tmp_path)
    assert review["snapshot_count"] == 0
    assert "2 archived" in str(review.get("note") or "")
