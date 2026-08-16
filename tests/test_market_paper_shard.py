"""Tests for Phase 2 weekly paper shard runner."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd

from value_investor.market_paper_shard import (
    ensure_shard_meta,
    run_weekly_market_paper_shard,
    session_defaults_for_market,
)
from value_investor.market_shard_phases import PHASE1_MIN_SCREEN_ARCHIVES
from value_investor.storage import write_json


def _seed_screen_artifacts(root: Path, market_id: str) -> None:
    screen_dir = root / "markets" / market_id / "screen"
    screen_dir.mkdir(parents=True, exist_ok=True)
    for idx in range(PHASE1_MIN_SCREEN_ARCHIVES):
        stamp = f"202607{idx + 1:02d}_120000"
        pd.DataFrame([{"ticker": "AAA", "signal": "buy", "conviction_score": 0.8}]).to_csv(
            screen_dir / f"signals_{stamp}.csv",
            index=False,
        )
        pd.DataFrame([{"ticker": "AAA", "last_price": 10.0}]).to_csv(
            screen_dir / f"universe_{stamp}.csv",
            index=False,
        )
    pd.DataFrame([{"ticker": "AAA", "signal": "buy", "composite_score": 0.8}]).to_csv(
        screen_dir / "latest_signals.csv",
        index=False,
    )
    pd.DataFrame([{"ticker": "AAA", "score": 0.8, "passed": True, "model_name": "value"}]).to_csv(
        screen_dir / "latest_model_results.csv",
        index=False,
    )
    sim_dir = screen_dir / "sim"
    sim_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        sim_dir / "observe_summary.json",
        {
            "snapshot_count": PHASE1_MIN_SCREEN_ARCHIVES,
            "tracks": {
                "ai_judgment": {"excess_return": 0.04},
                "screen_rules": {"excess_return": 0.01},
            },
        },
        compact=False,
    )


def test_session_defaults_for_sp500():
    session = session_defaults_for_market("sp500")
    assert session["timezone"] == "America/New_York"
    assert session["market_open"] == "09:30"


def test_ensure_shard_meta_writes_benchmark(tmp_path: Path):
    shard_root = tmp_path / "markets" / "sp500"
    meta = ensure_shard_meta("sp500", shard_root)
    assert meta["benchmark_ticker"] == "^GSPC"
    assert (shard_root / "shard_meta.json").exists()


def test_run_weekly_market_paper_shard(tmp_path: Path):
    library_root = tmp_path / "library"
    shard_root = tmp_path / "paper" / "markets" / "sp500"
    _seed_screen_artifacts(library_root, "sp500")
    fake_tracks = {"tracks": {"rules": {"acted": True, "trades": 1, "note": "ok"}}}
    fake_review = {
        "verdict": "insufficient_data",
        "beat_control": False,
        "primary_excess_after_costs": None,
    }
    with (
        patch("value_investor.market_paper_shard.run_learning_tracks", return_value=fake_tracks),
        patch("value_investor.market_paper_shard.compare_learning_tracks", return_value=fake_review),
    ):
        result = run_weekly_market_paper_shard(
            "sp500",
            library_root=library_root,
            shard_root=shard_root,
        )
    assert (shard_root / "screen_latest.json").exists()
    assert (shard_root / "weekly_batch_log.json").exists()
    assert (shard_root / "shard_phase.json").exists()
    assert result["review"]["verdict"] == "insufficient_data"
