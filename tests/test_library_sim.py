"""Tests for offline library observe-only paper sims."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from value_investor.library_sim import (
    build_library_run_snapshot,
    enrich_signals_with_library_research,
    ingest_profile_observe_sim_markets,
    iter_library_screen_runs,
    observe_sim_markets_for_policy,
    run_library_observe_sim,
    run_observe_sims_for_screened_markets,
    save_library_run_snapshots,
)


def _write_screen_run(
    screen_dir: Path,
    *,
    stamp: str,
    tickers: list[tuple[str, float, str]],
) -> None:
    run_at = datetime.strptime(stamp, "%Y%m%d_%H%M%S").replace(tzinfo=UTC)
    signals = pd.DataFrame(
        [
            {
                "ticker": ticker,
                "signal": signal,
                "conviction_score": 0.8,
                "data_quality_score": 1.0,
            }
            for ticker, _price, signal in tickers
        ]
    )
    universe = pd.DataFrame(
        [{"ticker": ticker, "last_price": price} for ticker, price, _signal in tickers]
    )
    signals.to_csv(screen_dir / f"signals_{stamp}.csv", index=False)
    universe.to_csv(screen_dir / f"universe_{stamp}.csv", index=False)
    return run_at


def test_iter_library_screen_runs_skips_latest_alias(tmp_path: Path):
    screen_dir = tmp_path / "screen"
    screen_dir.mkdir()
    _write_screen_run(screen_dir, stamp="20260701_120000", tickers=[("AAA", 10.0, "buy")])
    (screen_dir / "latest_signals.csv").write_text("ticker\n", encoding="utf-8")
    runs = iter_library_screen_runs(screen_dir)
    assert len(runs) == 1
    assert runs[0][0].strftime("%Y%m%d_%H%M%S") == "20260701_120000"


def test_enrich_signals_with_library_research_pit(tmp_path: Path):
    research_dir = tmp_path / "research" / "AAA"
    research_dir.mkdir(parents=True)
    (research_dir / "research.json").write_text(
        '{"ticker":"AAA","created_at":"2026-07-01T12:00:00+00:00","research_verdict":"caution"}',
        encoding="utf-8",
    )
    signals = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "signal": "strong_buy",
                "conviction_score": 0.9,
                "data_quality_score": 1.0,
            }
        ]
    )
    run_at = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)
    enriched = enrich_signals_with_library_research(
        signals,
        research_dir=tmp_path / "research",
        run_at=run_at,
    )
    assert enriched.loc[0, "research_verdict"] == "caution"
    assert enriched.loc[0, "adjusted_signal"] == "buy"


def test_enrich_signals_with_library_research_reads_sibling_home(tmp_path: Path):
    sibling = tmp_path / "omxs30" / "ERIC-B.ST"
    sibling.mkdir(parents=True)
    (sibling / "research.json").write_text(
        '{"ticker":"ERIC-B.ST","created_at":"2026-07-01T12:00:00+00:00","research_verdict":"accumulate"}',
        encoding="utf-8",
    )
    signals = pd.DataFrame(
        [
            {
                "ticker": "ERIC-B.ST",
                "signal": "buy",
                "conviction_score": 0.7,
                "data_quality_score": 1.0,
            }
        ]
    )
    enriched = enrich_signals_with_library_research(
        signals,
        research_dir=tmp_path / "euro_depth",
        run_at=datetime(2026, 7, 2, 12, 0, tzinfo=UTC),
        extra_research_dirs=[tmp_path / "omxs30"],
    )
    assert enriched.loc[0, "research_verdict"] == "accumulate"


def test_run_library_observe_sim_writes_summary(tmp_path: Path):
    root = tmp_path / "library"
    screen_dir = root / "markets" / "sp500" / "screen"
    screen_dir.mkdir(parents=True)
    _write_screen_run(
        screen_dir,
        stamp="20260701_120000",
        tickers=[("AAA", 10.0, "strong_buy"), ("BBB", 20.0, "buy")],
    )
    _write_screen_run(
        screen_dir,
        stamp="20260708_120000",
        tickers=[("AAA", 11.0, "strong_buy"), ("BBB", 19.0, "hold")],
    )

    benchmark_series = pd.Series(
        {pd.Timestamp("2026-07-01", tz="UTC"): 100.0, pd.Timestamp("2026-07-08", tz="UTC"): 102.0}
    )

    with patch("value_investor.library_sim._benchmark_closes", return_value=benchmark_series):
        result = run_library_observe_sim(root, "sp500", rebuild_snapshots=True)

    assert result.snapshot_count == 2
    assert (screen_dir / "sim" / "observe_summary.json").exists()
    assert "screen_rules" in result.tracks
    assert result.tracks["screen_rules"]["periods"] == 2
    # Default cost is fair market proxy (~0.175% for sp500), not 3% stress.
    assert result.tracks["screen_rules"]["trade_cost_pct"] < 0.01
    assert result.tracks["screen_rules"]["trade_cost_pct"] > 0.001


def test_observe_sim_markets_from_policy_respects_toggle(tmp_path: Path):
    policy = {"ladder": {"observe_sim_after_screen": False, "observe_sim_markets": ["sp500"]}}
    assert observe_sim_markets_for_policy(policy) == []
    policy = {"ladder": {"observe_sim_after_screen": True, "observe_sim_markets": ["sp500"]}}
    assert observe_sim_markets_for_policy(policy) == ["sp500"]
    policy = {
        "ladder": {
            "observe_sim_after_screen": True,
            "observe_sim_markets": ["sp500", "euro_stoxx50", "iseq20", "unknown_market"],
        }
    }
    assert observe_sim_markets_for_policy(policy) == ["sp500", "euro_stoxx50", "iseq20"]


def test_observe_sim_markets_graduated_benchmark_mode():
    from value_investor.library_sim import OBSERVE_SIM_MARKETS_MODE_GRADUATED_BENCHMARK

    policy = {
        "ladder": {
            "observe_sim_after_screen": True,
            "observe_sim_markets_mode": OBSERVE_SIM_MARKETS_MODE_GRADUATED_BENCHMARK,
        },
        "graduated_markets": [
            {"market": "sp500"},
            {"market": "aim"},
            {"market": "iseq20"},
            {"market": "euro_stoxx50"},
        ],
    }
    assert observe_sim_markets_for_policy(policy) == [
        "sp500",
        "iseq20",
        "euro_stoxx50",
    ]


def test_ingest_profile_observe_sim_markets_excludes_grow_only():
    policy = {
        "focus_market": "euro_depth",
        "ingest_parallel_sprint": ["sp500"],
        "ingest_parallel_sprint_2": ["asx200"],
        "ingest_parity_markets": ["euro_depth"],
        "ftse_equivalent_markets": ["sp500"],
        "graduated_markets": [{"market": "nasdaq100"}, {"market": "dax"}],
        "ladder": {"weekly_paper_shard_markets": ["euro_depth"]},
    }
    assert ingest_profile_observe_sim_markets(policy) == [
        "euro_depth",
        "sp500",
        "asx200",
    ]


def test_observe_sim_markets_include_ingest_profile_by_default():
    policy = {
        "focus_market": "euro_depth",
        "ingest_parallel_sprint": ["sp500"],
        "ingest_parallel_sprint_2": ["asx200"],
        "ingest_parity_markets": ["euro_depth"],
        "ftse_equivalent_markets": ["sp500"],
        "ladder": {
            "observe_sim_after_screen": True,
            "observe_sim_markets_mode": "explicit",
            "observe_sim_markets": ["euro_depth"],
        },
    }
    assert observe_sim_markets_for_policy(policy) == ["euro_depth", "sp500", "asx200"]
    policy["ladder"]["observe_sim_include_ingest_profile"] = False
    assert observe_sim_markets_for_policy(policy) == ["euro_depth"]


def test_observe_sim_ingest_profile_keeps_parity_and_equivalent_after_sprint():
    policy = {
        "focus_market": "euro_depth",
        "ingest_parallel_sprint": [],
        "ingest_parallel_sprint_2": [],
        "ingest_parity_markets": ["asx200"],
        "ftse_equivalent_markets": ["sp500"],
        "ladder": {
            "observe_sim_after_screen": True,
            "observe_sim_markets_mode": "explicit",
            "observe_sim_markets": ["euro_depth"],
        },
    }
    assert observe_sim_markets_for_policy(policy) == ["euro_depth", "asx200", "sp500"]


def test_live_policy_observe_sim_follows_ingest_profile():
    from value_investor.agent_model_policy import DEFAULT_POLICY_PATH, load_policy

    policy = load_policy(DEFAULT_POLICY_PATH)
    assert observe_sim_markets_for_policy(policy) == ["euro_depth", "sp500", "asx200"]


def test_benchmark_for_iseq20():
    from value_investor.library_sim import benchmark_for_market

    assert benchmark_for_market("iseq20") == "^IETP"


def test_build_library_run_snapshot_defaults_missing_conviction(tmp_path: Path):
    signals = pd.DataFrame([{"ticker": "AAA", "signal": "buy", "data_quality_score": 0.9}])
    universe = pd.DataFrame([{"ticker": "AAA", "last_price": 10.0}])
    benchmark_series = pd.Series({pd.Timestamp("2026-07-01", tz="UTC"): 100.0})
    snapshot = build_library_run_snapshot(
        signals=signals,
        universe=universe,
        run_at=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        benchmark="^IETP",
        benchmark_closes=benchmark_series,
    )
    assert snapshot.signals[0]["conviction_score"] == 0.0


def test_run_observe_sims_for_screened_markets_skips_when_not_screened(tmp_path: Path):
    policy = {"ladder": {"observe_sim_after_screen": True, "observe_sim_markets": ["sp500"]}}
    result = run_observe_sims_for_screened_markets(tmp_path, policy, {"euro_stoxx50"})
    assert result["skipped"] is True


def test_save_library_run_snapshots(tmp_path: Path):
    root = tmp_path / "library"
    screen_dir = root / "markets" / "sp500" / "screen"
    screen_dir.mkdir(parents=True)
    _write_screen_run(screen_dir, stamp="20260701_120000", tickers=[("AAA", 10.0, "buy")])

    benchmark_series = pd.Series({pd.Timestamp("2026-07-01", tz="UTC"): 5000.0})
    with patch("value_investor.library_sim._benchmark_closes", return_value=benchmark_series):
        paths = save_library_run_snapshots(root, "sp500", benchmark="^GSPC")

    assert len(paths) == 1
    snapshot = build_library_run_snapshot(
        signals=pd.read_csv(screen_dir / "signals_20260701_120000.csv"),
        universe=pd.read_csv(screen_dir / "universe_20260701_120000.csv"),
        run_at=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        benchmark="^GSPC",
        benchmark_closes=benchmark_series,
    )
    assert snapshot.prices["AAA"] == 10.0
    assert snapshot.prices["^GSPC"] == 5000.0
