"""Tests for market-shard phase gates and advancement triggers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from value_investor.market_shard_phases import (
    PHASE1_MIN_SCREEN_ARCHIVES,
    PHASE_OBSERVE,
    PHASE_WEEKLY_PAPER,
    append_weekday_batch_log,
    append_weekly_batch_log,
    evaluate_market_phase,
    markets_eligible_for_weekly_paper,
    phase1_gate_met,
    phase3_gate_met,
    refresh_committed_phase_rollup,
    weekly_paper_shard_markets_for_policy,
)
from value_investor.storage import read_json, write_json


def _write_screen_archive(screen_dir: Path, stamp: str) -> None:
    screen_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"ticker": "AAA", "signal": "buy", "conviction_score": 0.8}]).to_csv(
        screen_dir / f"signals_{stamp}.csv",
        index=False,
    )
    pd.DataFrame([{"ticker": "AAA", "last_price": 10.0}]).to_csv(
        screen_dir / f"universe_{stamp}.csv",
        index=False,
    )


def _seed_phase1_ready(root: Path, market_id: str) -> None:
    screen_dir = root / "markets" / market_id / "screen"
    for idx in range(PHASE1_MIN_SCREEN_ARCHIVES):
        stamp = f"202607{idx + 1:02d}_120000"
        _write_screen_archive(screen_dir, stamp)
    sim_dir = screen_dir / "sim"
    sim_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        sim_dir / "observe_summary.json",
        {
            "snapshot_count": PHASE1_MIN_SCREEN_ARCHIVES,
            "tracks": {
                "ai_judgment": {"excess_return": 0.05},
                "screen_rules": {"excess_return": 0.02},
            },
        },
        compact=False,
    )
    screen_dir.joinpath("latest_signals.csv").write_text(
        "ticker,signal\nAAA,buy\n", encoding="utf-8"
    )
    screen_dir.joinpath("latest_model_results.csv").write_text("ticker\nAAA\n", encoding="utf-8")


def test_weekly_paper_shard_markets_respects_toggle():
    policy = {
        "ladder": {
            "weekly_paper_shard_after_screen": False,
            "weekly_paper_shard_markets": ["sp500"],
        }
    }
    assert weekly_paper_shard_markets_for_policy(policy) == []
    policy["ladder"]["weekly_paper_shard_after_screen"] = True
    assert weekly_paper_shard_markets_for_policy(policy) == ["sp500"]


def test_weekly_paper_shard_capacity_truncates():
    from value_investor.market_shard_phases import weekly_paper_shard_capacity_for_policy

    policy = {
        "ladder": {
            "weekly_paper_shard_after_screen": True,
            "weekly_paper_shard_capacity": 2,
            "weekly_paper_shard_markets": ["sp500", "euro_stoxx50", "iseq20"],
        }
    }
    assert weekly_paper_shard_capacity_for_policy(policy) == 2
    assert weekly_paper_shard_markets_for_policy(policy) == ["sp500", "euro_stoxx50"]


def test_phase1_gate_requires_archives_and_snapshots(tmp_path: Path):
    root = tmp_path / "library"
    market_id = "sp500"
    screen_dir = root / "markets" / market_id / "screen"
    _write_screen_archive(screen_dir, "20260701_120000")
    ok, detail = phase1_gate_met(root, market_id)
    assert ok is False
    assert detail["screen_archives"] == 1


def test_markets_eligible_for_weekly_paper(tmp_path: Path):
    root = tmp_path / "library"
    _seed_phase1_ready(root, "sp500")
    policy = {
        "ladder": {
            "weekly_paper_shard_after_screen": True,
            "weekly_paper_shard_markets": ["sp500", "euro_stoxx50"],
        }
    }
    assert markets_eligible_for_weekly_paper(
        policy, library_root=root, screened_markets={"sp500"}
    ) == ["sp500"]


def test_evaluate_market_phase_blockers_for_iseq20(tmp_path: Path):
    root = tmp_path / "library"
    policy = {
        "ladder": {
            "weekly_paper_shard_after_screen": True,
            "weekly_paper_shard_markets": ["iseq20"],
        }
    }
    evaluation = evaluate_market_phase("iseq20", library_root=root, policy=policy)
    assert evaluation["current_phase"] == PHASE_OBSERVE
    assert evaluation["blockers"]


def test_refresh_committed_phase_rollup_writes_files(tmp_path: Path, monkeypatch):
    root = tmp_path / "library"
    shard_root = tmp_path / "shards" / "sp500"
    _seed_phase1_ready(root, "sp500")
    monkeypatch.setattr(
        "value_investor.market_shard_phases.DEFAULT_SHARD_ROOT",
        tmp_path / "shards",
    )
    monkeypatch.setattr(
        "value_investor.market_shard_phases.shard_root_for_market",
        lambda market_id, base=None: tmp_path / "shards" / market_id,
    )
    policy = {
        "ladder": {
            "weekly_paper_shard_after_screen": True,
            "weekly_paper_shard_markets": ["sp500"],
        }
    }
    rollup = refresh_committed_phase_rollup(
        ["sp500"],
        library_root=root,
        policy=policy,
        path=tmp_path / "shard_phases.json",
    )
    assert "sp500" in rollup["markets"]
    assert (shard_root / "shard_phase.json").exists()
    assert (tmp_path / "shard_phases.json").exists()


def test_phase1_gate_respects_sprint_policy(tmp_path: Path):
    root = tmp_path / "library"
    market_id = "euro_depth"
    screen_dir = root / "markets" / market_id / "screen"
    for idx in range(4):
        stamp = f"202607{idx + 1:02d}_120000"
        _write_screen_archive(screen_dir, stamp)
    sim_dir = screen_dir / "sim"
    sim_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        sim_dir / "observe_summary.json",
        {"snapshot_count": 4, "tracks": {}},
        compact=False,
    )
    policy = {"ladder": {"phase1_min_screen_archives": 4, "phase1_require_ai_beat_rules": False}}
    ok, detail = phase1_gate_met(root, market_id, policy=policy)
    assert ok is True
    assert detail["min_archives"] == 4


def test_phase3_gate_weekday_batches(tmp_path: Path, monkeypatch):
    shard_root = tmp_path / "shards" / "euro_depth"
    shard_root.mkdir(parents=True)
    for _ in range(8):
        append_weekday_batch_log(shard_root, {"run_at": "2026-08-01T12:00:00+00:00"})
    monkeypatch.setattr(
        "value_investor.market_shard_phases.exit_shadow_closed_count",
        lambda *_args, **_kwargs: 10,
    )
    policy = {
        "ladder": {
            "phase3_min_weekday_batches": 8,
            "phase3_min_exit_shadow_closed": 8,
        }
    }
    ok, detail = phase3_gate_met(shard_root, policy=policy)
    assert ok is True
    assert detail["weekday_batch_count"] == 8


def test_append_weekly_batch_log(tmp_path: Path):
    shard_root = tmp_path / "sp500"
    append_weekly_batch_log(
        shard_root, {"run_at": datetime.now(UTC).isoformat(), "verdict": "insufficient_data"}
    )
    payload = read_json(shard_root / "weekly_batch_log.json")
    assert len(payload["entries"]) == 1


def test_evaluate_market_phase_weekly_when_phase1_met(tmp_path: Path, monkeypatch):
    root = tmp_path / "library"
    _seed_phase1_ready(root, "sp500")
    monkeypatch.setattr(
        "value_investor.market_shard_phases.shard_root_for_market",
        lambda market_id, base=None: tmp_path / "shards" / market_id,
    )
    policy = {
        "ladder": {
            "weekly_paper_shard_after_screen": True,
            "weekly_paper_shard_markets": ["sp500"],
        }
    }
    evaluation = evaluate_market_phase("sp500", library_root=root, policy=policy)
    assert evaluation["current_phase"] == PHASE_WEEKLY_PAPER
    assert evaluation["phase1_ready"] is True
