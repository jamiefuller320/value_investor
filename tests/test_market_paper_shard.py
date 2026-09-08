"""Tests for Phase 2 weekly paper shard runner."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd

from datetime import UTC, datetime

from value_investor.market_paper_shard import (
    ensure_shard_meta,
    epoch0_marked_on_local_day,
    run_epoch0_weekday_market_shard,
    run_weekly_market_paper_shard,
    session_defaults_for_market,
)
from value_investor.market_shard_phases import append_weekday_batch_log
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
    assert "trading_costs" in meta
    assert meta["trading_costs"]["fx_applies"] is True
    assert meta["trading_costs"]["stamp_duty_on_buy"] is False


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
        patch(
            "value_investor.market_paper_shard.compare_learning_tracks", return_value=fake_review
        ),
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


def test_epoch0_weekday_skips_before_settle(tmp_path: Path):
    library_root = tmp_path / "library"
    shard_root = tmp_path / "paper" / "markets" / "sp500"
    _seed_screen_artifacts(library_root, "sp500")
    before = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)  # 08:00 New York
    result = run_epoch0_weekday_market_shard(
        "sp500",
        library_root=library_root,
        shard_root=shard_root,
        now=before,
    )
    assert result["skipped"] is True
    assert "settle" in str(result.get("reason") or "").lower() or result.get("reason")
    assert not (shard_root / "weekday_batch_log.json").exists()


def test_epoch0_weekday_skips_when_already_marked(tmp_path: Path):
    shard_root = tmp_path / "paper" / "markets" / "sp500"
    shard_root.mkdir(parents=True)
    append_weekday_batch_log(
        shard_root,
        {"run_at": "2026-09-08T14:20:00+00:00", "cadence": "weekday"},
    )
    session = session_defaults_for_market("sp500")
    when = datetime(2026, 9, 8, 18, 0, tzinfo=UTC)
    assert epoch0_marked_on_local_day(shard_root, session, when=when) is True
    result = run_epoch0_weekday_market_shard(
        "sp500",
        library_root=tmp_path / "library",
        shard_root=shard_root,
        now=when,
    )
    assert result["skipped"] is True
    assert result["reason"] == "already_marked_local_day"


def test_epoch0_weekday_marks_after_settle(tmp_path: Path):
    library_root = tmp_path / "library"
    shard_root = tmp_path / "paper" / "markets" / "sp500"
    _seed_screen_artifacts(library_root, "sp500")

    class _Pass:
        acted = True
        trades = [1]
        note = "ok"

    after = datetime(2026, 9, 8, 14, 30, tzinfo=UTC)  # 10:30 New York
    with (
        patch(
            "value_investor.market_paper_shard.write_market_screen_bundle",
            return_value=shard_root / "screen_latest.json",
        ),
        patch(
            "value_investor.market_paper_shard.run_daily_automation",
            return_value=_Pass(),
        ),
        patch(
            "value_investor.market_paper_shard.write_library_near_miss_watch",
            return_value={"buy_tier_not_now_count": 1, "hold_near_buy_count": 2},
        ),
    ):
        shard_root.mkdir(parents=True)
        (shard_root / "screen_latest.json").write_text("{}", encoding="utf-8")
        result = run_epoch0_weekday_market_shard(
            "sp500",
            library_root=library_root,
            shard_root=shard_root,
            now=after,
        )
    assert result.get("skipped") is False
    assert result["cadence"] == "weekday"
    assert result["ai_judgment"] is False
    log = (shard_root / "weekday_batch_log.json")
    assert log.exists()
    import json

    entries = json.loads(log.read_text())["entries"]
    assert entries[-1]["cadence"] == "weekday"
