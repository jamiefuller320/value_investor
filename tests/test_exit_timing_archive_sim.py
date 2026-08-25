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


def test_default_gate_aligns_with_pre_buy_floor():
    from value_investor.exit_timing_archive_sim import (
        DEFAULT_MAX_EPISODES_PER_WEEK,
        DEFAULT_MIN_CONVICTION,
    )
    from value_investor.trajectory_evidence import PRE_BUY_CONVICTION

    cfg = ExitTimingArchiveSimConfig()
    assert cfg.min_conviction == PRE_BUY_CONVICTION == DEFAULT_MIN_CONVICTION
    assert cfg.max_episodes_per_week == DEFAULT_MAX_EPISODES_PER_WEEK == 25
    assert _is_near_miss({"ticker": "A.L", "signal": "hold", "conviction_score": 0.28}, cfg)
    assert not _is_near_miss({"ticker": "B.L", "signal": "hold", "conviction_score": 0.27}, cfg)


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
    assert review["episodes_opened"]["hold_recovery_near_miss"] >= 1
    closed_hold = (review.get("hold_recovery") or {}).get("closed") or {}
    assert closed_hold.get("count", 0) >= 1
    bands = review.get("by_conviction_band") or {}
    assert "high_ge_0.45" in bands
    assert bands["high_ge_0.45"]["closed_count"] >= 1


def test_run_exit_timing_archive_sim_held_book_episodes(tmp_path: Path):
    """Held tickers from rebalance_log with buy-tier history open hold/swap episodes."""
    from value_investor.rebalance_log import append_rebalance_log

    paper_root = tmp_path / "paper_automation"
    track_dir = paper_root
    track_dir.mkdir(parents=True)

    held_entry = {
        "schema_version": 2,
        "track_id": "rules",
        "acted": True,
        "trade_cost_pct": 0.03,
        "gate": {"local_time": "2026-01-08T13:00:00+00:00"},
        "holdings_before": [
            {
                "ticker": "HELD.L",
                "shares": 10.0,
                "avg_cost": 100.0,
                "name": "Held Co",
                "momentum_grace": False,
            }
        ],
        "rebalance_state_before": {"exit_streak": {"HELD.L": 1}},
        "candidates": [
            {
                "ticker": "HELD.L",
                "signal": "strong_buy",
                "adjusted_signal": "hold",
                "conviction_score": 0.5,
                "data_quality_score": 0.8,
                "price": 95.0,
            },
            {
                "ticker": "NEW.L",
                "signal": "buy",
                "conviction_score": 0.9,
                "price": 50.0,
            },
        ],
        "screen_buy_tier": [
            {"ticker": "HELD.L", "signal": "strong_buy", "conviction_score": 0.5},
            {"ticker": "NEW.L", "signal": "buy", "conviction_score": 0.9},
        ],
        "trades": [
            {
                "ticker": "HELD.L",
                "side": "sell",
                "price": 95.0,
                "shares": 10.0,
                "gross": 950.0,
                "cost": 5.0,
                "note": "Automated exit",
            },
            {
                "ticker": "NEW.L",
                "side": "buy",
                "price": 50.0,
                "shares": 18.0,
                "gross": 900.0,
                "cost": 5.0,
                "note": "Automated buy",
            },
        ],
    }
    append_rebalance_log(track_dir, held_entry)

    rows = [
        {
            "ticker": "HELD.L",
            "signal": "hold",
            "conviction_score": 0.5,
            "data_quality_score": 0.8,
        },
        {"ticker": "NEW.L", "signal": "buy", "conviction_score": 0.9},
    ]
    _write_history_snapshot(
        tmp_path,
        "run_20260101_100000.json",
        "2026-01-01T10:00:00+00:00",
        {"HELD.L": 100.0, "NEW.L": 50.0, "^FTSE": 8000.0},
        rows,
    )
    _write_history_snapshot(
        tmp_path,
        "run_20260129_100000.json",
        "2026-01-29T10:00:00+00:00",
        {"HELD.L": 102.0, "NEW.L": 55.0, "^FTSE": 8100.0},
        rows,
    )
    _write_history_snapshot(
        tmp_path,
        "run_20260326_100000.json",
        "2026-03-26T10:00:00+00:00",
        {"HELD.L": 98.0, "NEW.L": 60.0, "^FTSE": 8200.0},
        rows,
    )

    review = run_exit_timing_archive_sim(
        tmp_path,
        config=ExitTimingArchiveSimConfig(
            min_conviction=0.35,
            max_episodes_per_week=5,
            paper_root=paper_root,
            track_ids=("rules",),
        ),
    )
    opened = review.get("episodes_opened") or {}
    assert opened.get("hold_recovery_held_book", 0) >= 1
    assert opened.get("swap_rotation_log_book", 0) >= 1

    store = json.loads((tmp_path / COHORTS_FILENAME).read_text(encoding="utf-8"))
    held_episodes = [
        row
        for row in store.get("hold_episodes") or []
        if row.get("episode_kind") == "held_book_observe"
    ]
    log_swaps = [
        row
        for row in store.get("swap_rotations") or []
        if row.get("rotation_kind") == "log_swap_observe"
    ]
    assert held_episodes
    assert log_swaps
    assert held_episodes[0]["ticker"] == "HELD.L"
    assert log_swaps[0]["verdict"] in {
        "replacement_outperformed",
        "exit_outperformed",
        "inconclusive",
    }


def test_run_exit_timing_archive_sim_needs_two_snapshots(tmp_path: Path):
    review = run_exit_timing_archive_sim(tmp_path)
    assert review["snapshot_count"] == 0
    assert "2 archived" in str(review.get("note") or "")
