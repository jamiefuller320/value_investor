"""Tests for admitted-market epoch-0 start and L322 threshold admission."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd

from value_investor.library_near_miss_watch import write_library_near_miss_watch
from value_investor.market_paper_shard import run_epoch0_market_shard
from value_investor.market_shard_admission import (
    admit_market_to_learning,
    admitted_learning_markets_for_policy,
    sync_admitted_learning_markets,
)


def test_admitted_markets_union_explicit_exhausted_and_parity():
    policy = {
        "ladder": {"admitted_learning_markets": ["sp500", "asx200"]},
        "ingest_exhausted_markets": ["sp500", "ftse_smallcap"],
        "ingest_parity_markets": ["euro_depth", "asx200"],
    }
    assert admitted_learning_markets_for_policy(policy) == [
        "sp500",
        "asx200",
        "ftse_smallcap",
        "euro_depth",
    ]


def test_admitted_markets_include_parity_threshold_signal():
    """L322: stored parity is a sprint_ingest_complete signal and admits learning."""
    policy = {
        "ladder": {"admitted_learning_markets": []},
        "ingest_exhausted_markets": [],
        "ingest_parity_markets": ["euro_depth"],
    }
    assert admitted_learning_markets_for_policy(policy) == ["euro_depth"]


def test_admit_market_to_learning_persists_once():
    policy: dict = {"ladder": {"admitted_learning_markets": ["sp500"]}}
    assert admit_market_to_learning(policy, "asx200") is True
    assert policy["ladder"]["admitted_learning_markets"] == ["sp500", "asx200"]
    assert admit_market_to_learning(policy, "asx200") is False


def test_sync_admitted_learning_markets_rewrites_explicit_roster():
    policy = {
        "ladder": {"admitted_learning_markets": ["sp500"]},
        "ingest_exhausted_markets": ["ftse_smallcap", "euro_depth"],
        "ingest_parity_markets": ["asx200"],
    }
    synced = sync_admitted_learning_markets(policy)
    assert synced == ["sp500", "ftse_smallcap", "euro_depth", "asx200"]
    assert policy["ladder"]["admitted_learning_markets"] == synced


def test_near_miss_watch_splits_wait_and_hold(tmp_path: Path):
    screen = tmp_path / "markets" / "sp500" / "screen"
    screen.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "signal": "buy",
                "timing_signal": "wait",
                "conviction_score": 0.6,
            },
            {
                "ticker": "BBB",
                "signal": "hold",
                "timing_signal": "buy",
                "conviction_score": 0.4,
            },
            {
                "ticker": "CCC",
                "signal": "buy",
                "timing_signal": "buy",
                "conviction_score": 0.7,
            },
        ]
    ).to_csv(screen / "latest_signals.csv", index=False)
    payload = write_library_near_miss_watch(tmp_path, "sp500")
    assert payload["buy_tier_not_now_count"] == 1
    assert payload["hold_near_buy_count"] == 1
    assert payload["not_buy_tier_count"] == 1
    assert payload["buy_tier_not_now"][0]["ticker"] == "AAA"
    assert payload["hold_near_buy"][0]["ticker"] == "BBB"
    assert payload["timing_signal_present"] is True


def test_epoch0_runs_only_buy_tier_level(tmp_path: Path):
    library_root = tmp_path / "library"
    screen = library_root / "markets" / "sp500" / "screen"
    screen.mkdir(parents=True)
    pd.DataFrame([{"ticker": "AAA", "signal": "buy", "composite_score": 0.8}]).to_csv(
        screen / "latest_signals.csv",
        index=False,
    )
    pd.DataFrame([{"ticker": "AAA", "score": 0.8, "passed": True, "model_name": "value"}]).to_csv(
        screen / "latest_model_results.csv", index=False
    )
    shard_root = tmp_path / "paper" / "markets" / "sp500"
    captured: dict[str, object] = {}

    class _Pass:
        acted = True
        trades = [1, 2, 3]
        note = "ok"

    def _fake_daily(**kwargs):
        captured["output_dir"] = str(kwargs.get("output_dir"))
        return _Pass()

    with (
        patch(
            "value_investor.market_paper_shard.write_market_screen_bundle",
            return_value=shard_root / "screen_latest.json",
        ),
        patch(
            "value_investor.market_paper_shard.run_daily_automation",
            side_effect=_fake_daily,
        ),
    ):
        shard_root.mkdir(parents=True)
        (shard_root / "screen_latest.json").write_text("{}", encoding="utf-8")
        result = run_epoch0_market_shard(
            "sp500",
            library_root=library_root,
            shard_root=shard_root,
        )
    assert str(captured["output_dir"]).endswith("buy_tier_level")
    assert not (shard_root / "ai_judgment").exists()
    assert result["ai_judgment"] is False
    assert result["knob_apply"] is False
    assert (shard_root / "weekday_batch_log.json").exists()
