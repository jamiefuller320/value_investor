"""Equal-support package: timing, near-miss groups, counterfactual archives."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from value_investor.library_equal_support import (
    run_equal_support_package,
    stamp_library_timing_archives,
)
from value_investor.library_near_miss_watch import write_library_near_miss_watch
from value_investor.library_sim import observe_sim_markets_for_policy
from value_investor.library_timing import stamp_timing_on_signals


def _price_history(ticker: str = "AAA") -> dict[str, pd.DataFrame]:
    idx = pd.date_range("2025-01-01", periods=220, freq="D", tz="UTC")
    close = pd.Series(range(100, 320), index=idx, dtype=float)
    frame = pd.DataFrame(
        {"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Volume": 1_000_000}
    )
    return {ticker: frame}


def _seed_market(root: Path, market_id: str) -> None:
    screen = root / "markets" / market_id / "screen"
    screen.mkdir(parents=True)
    rows_a = [
        {
            "ticker": "AAA",
            "signal": "buy",
            "conviction_score": 0.8,
            "last_price": 10.0,
        },
        {
            "ticker": "BBB",
            "signal": "hold",
            "conviction_score": 0.4,
            "last_price": 8.0,
        },
        {
            "ticker": "CCC",
            "signal": "avoid",
            "conviction_score": 0.1,
            "last_price": 5.0,
        },
    ]
    rows_b = [
        {
            "ticker": "AAA",
            "signal": "buy",
            "conviction_score": 0.7,
            "last_price": 11.0,
        },
        {
            "ticker": "BBB",
            "signal": "hold",
            "conviction_score": 0.45,
            "last_price": 8.5,
        },
        {
            "ticker": "CCC",
            "signal": "avoid",
            "conviction_score": 0.1,
            "last_price": 5.2,
        },
    ]
    for stamp, rows in (("20260801_120000", rows_a), ("20260808_120000", rows_b)):
        pd.DataFrame(rows).to_csv(screen / f"signals_{stamp}.csv", index=False)
        pd.DataFrame([{"ticker": r["ticker"], "last_price": r["last_price"]} for r in rows]).to_csv(
            screen / f"universe_{stamp}.csv", index=False
        )
    pd.DataFrame(rows_b).to_csv(screen / "latest_signals.csv", index=False)
    pd.DataFrame([{"ticker": "AAA", "score": 0.8, "passed": True, "model_name": "value"}]).to_csv(
        screen / "latest_model_results.csv", index=False
    )


def test_stamp_timing_uses_market_history():
    signals = pd.DataFrame([{"ticker": "AAA", "signal": "buy", "conviction_score": 0.8}])
    stamped = stamp_timing_on_signals(signals, market="sp500", history=_price_history())
    assert stamped.loc[0, "timing_signal"] not in {"", None}
    assert "timing_score" in stamped.columns


def test_near_miss_splits_not_buy_tier_and_never_buy(tmp_path: Path):
    _seed_market(tmp_path, "sp500")
    payload = write_library_near_miss_watch(tmp_path, "sp500")
    assert payload["not_buy_tier_count"] == 2
    assert payload["hold_near_buy_count"] == 1
    assert payload["never_buy_tier_count"] == 2
    never = {row["ticker"] for row in payload["never_buy_tier"]}
    assert never == {"BBB", "CCC"}


def test_equal_support_package_writes_archives_and_timing(tmp_path: Path):
    _seed_market(tmp_path, "sp500")
    policy = {
        "ladder": {
            "admitted_learning_markets": ["sp500"],
            "rememo_body_lag_threshold": 10,
        }
    }
    result = run_equal_support_package(
        tmp_path,
        policy,
        stamp_timing=True,
        run_archives=True,
        price_history=_price_history(),
    )
    row = result["markets"]["sp500"]
    assert row["ai_judgment"] is False
    assert row["knob_apply"] is False
    assert row["timing"]["timing_signal_present"] is True
    near = row["near_miss"]
    assert near["not_buy_tier_count"] == 2
    assert near["never_buy_tier_count"] == 2
    archives = row["archives"]
    assert archives["snapshots_written"] >= 2
    assert archives["exclusion"]["snapshot_count"] >= 2
    screen = tmp_path / "markets" / "sp500" / "screen"
    assert (screen / "exclusion_universe_review.json").exists() or (
        screen / "exclusion_universe_archive.json"
    ).exists()
    assert (screen / "exit_timing_near_miss.json").exists() or (
        screen / "exit_timing_near_miss_review.json"
    ).exists()


def test_observe_sim_includes_admitted_markets():
    policy = {
        "ladder": {
            "observe_sim_after_screen": True,
            "observe_sim_markets_mode": "explicit",
            "observe_sim_markets": ["euro_depth"],
            "observe_sim_include_ingest_profile": False,
            "observe_sim_include_admitted": True,
            "admitted_learning_markets": ["sp500", "asx200"],
        }
    }
    markets = observe_sim_markets_for_policy(policy)
    assert "sp500" in markets
    assert "asx200" in markets
    assert "euro_depth" in markets


def test_stamp_archives_is_point_in_time(tmp_path: Path):
    _seed_market(tmp_path, "sp500")
    out = stamp_library_timing_archives(tmp_path, "sp500", history=_price_history())
    assert out["dated_archives_stamped"] == 2
    latest = pd.read_csv(tmp_path / "markets" / "sp500" / "screen" / "latest_signals.csv")
    assert "timing_signal" in latest.columns
