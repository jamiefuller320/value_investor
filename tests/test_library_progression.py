"""Tests for offline universe progression helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from value_investor.library_progression import (
    assess_offline_universe_progression,
    effective_focus_grow_tickers,
    evaluate_eng_idle_offline_dispatch,
)


def _write_policy(tmp_path: Path, *, focus: str = "omxs30") -> Path:
    policy = tmp_path / "policy.json"
    policy.write_text(
        f'{{"focus_market":"{focus}","market_queue":["{focus}"],"graduated_markets":[],'
        f'"focus_graduation":{{"min_coverage_pct":0.95,"max_stale_pct":0.15,"auto_advance":true}},'
        f'"ladder":{{"min_metrics_for_screen":25}}}}',
        encoding="utf-8",
    )
    return policy


def _write_manifest(tmp_path: Path, market: str, *, ok: int, failed: int) -> Path:
    import json

    root = tmp_path / "library"
    market_dir = root / "markets" / market
    market_dir.mkdir(parents=True)
    tickers = [f"T{i}.ST" for i in range(ok + failed)]
    state = {}
    for i, ticker in enumerate(tickers):
        if i < ok:
            state[ticker] = {
                "fetch_status": "ok",
                "fields_present": ["market_cap"],
                "last_refresh": "x",
            }
        else:
            state[ticker] = {
                "fetch_status": "failed",
                "errors": ["401"],
                "last_refresh": "x",
            }
    manifest = {
        "market": market,
        "tickers": tickers,
        "ticker_count": len(tickers),
        "ticker_state": state,
        "coverage_count": ok,
    }
    (market_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (market_dir / "metrics").mkdir()
    (market_dir / "metrics" / "latest.json").write_text("[]", encoding="utf-8")
    return root


def test_effective_focus_grow_tickers_uses_full_tail_market(tmp_path: Path):
    root = _write_manifest(tmp_path, "omxs30", ok=0, failed=30)
    policy = _write_policy(tmp_path)
    tickers = effective_focus_grow_tickers(
        root=root,
        policy_path=policy,
        market_id="omxs30",
        plan_max_tickers=40,
    )
    assert tickers == 30


def test_assess_offline_progression_growing(tmp_path: Path):
    root = _write_manifest(tmp_path, "omxs30", ok=3, failed=27)
    policy = _write_policy(tmp_path)
    with patch(
        "value_investor.library_progression.snapshot_focus_market_health",
        return_value={
            "market": "omxs30",
            "ticker_count": 30,
            "ok_fetch_count": 3,
            "failed_fetch_count": 27,
            "honest_coverage_pct": 0.1,
            "usable_metrics_rows": 3,
            "latent_failure": False,
        },
    ):
        result = assess_offline_universe_progression(
            root=root,
            policy_path=policy,
            tasks_path=tmp_path / "tasks.json",
        )
    assert result["status"] == "growing"


def test_eng_idle_offline_dispatches_when_growing(tmp_path: Path):
    run_now = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)
    with (
        patch(
            "value_investor.library_progression.assess_offline_universe_progression",
            return_value={"status": "growing", "market": "omxs30", "reason": "growing"},
        ),
        patch(
            "value_investor.library_progression._last_ladder_run_at",
            return_value=run_now - timedelta(hours=48),
        ),
    ):
        result = evaluate_eng_idle_offline_dispatch(
            open_count=0,
            pr_open_count=0,
            now=run_now,
        )
    assert result["should_dispatch"] is True
    assert result["suite"] == "ladder_only"


def test_eng_idle_offline_skips_when_stalled(tmp_path: Path):
    with patch(
        "value_investor.library_progression.assess_offline_universe_progression",
        return_value={
            "status": "stalled_needs_engineering",
            "market": "omxs30",
            "reason": "stalled",
        },
    ):
        result = evaluate_eng_idle_offline_dispatch(open_count=0, pr_open_count=0)
    assert result["should_dispatch"] is False
