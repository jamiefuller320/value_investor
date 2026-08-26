"""Tests for S&P 500 FTSE-equivalent learning-depth measurement."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from value_investor.data_library_cli import main as library_main
from value_investor.library_ingest_dispatch import ingest_parity_met
from value_investor.library_ingest_escalation import (
    is_ftse_equivalent_market,
    snapshot_library_buy_tier_filing_health,
)
from value_investor.library_ingest_loop import _filing_coverage_for_ticker
from value_investor.library_learning_depth import (
    assess_library_learning_depth,
    assess_screen_archive_span,
    learning_depth_path,
    write_library_trajectory_artifacts,
)
from value_investor.storage import write_json
from value_investor.summary import CompanyReport


def _report(ticker: str, signal: str = "buy", conviction: float = 0.5) -> CompanyReport:
    return CompanyReport(
        ticker=ticker,
        name=f"{ticker} Co",
        sector="X",
        signal=signal,
        models_passed=5,
        model_count=10,
        composite_score=0.6,
        sector_composite_score=0.55,
        families_passed=3,
        passed_families="cheapness",
        data_quality_score=0.8,
        metrics_present=10,
        metrics_total=12,
        weeks_at_signal=1,
        signal_trend="stable",
        conviction_score=conviction,
        stability_label="stable",
        timing_signal="hold",
        timing_score=0.0,
        rsi_14=None,
        price_vs_sma200_pct=None,
        action_note="",
        trade_plan=None,
        summary="",
        passed_models=[],
        key_metrics={},
    )


def _write_index(root: Path, market: str, ticker: str, *, total: int, with_body: int) -> None:
    filings_dir = root / "markets" / market / "screen" / "research" / ticker / "sources" / "filings"
    filings_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        filings_dir / "filings_index.json",
        {"summary": {"total": total, "with_body": with_body}, "filings": []},
        compact=False,
    )


def _write_screen_run(
    screen_dir: Path,
    *,
    stamp: str,
    tickers: list[tuple[str, float, str]],
) -> None:
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
    screen_dir.mkdir(parents=True, exist_ok=True)
    signals.to_csv(screen_dir / f"signals_{stamp}.csv", index=False)
    universe.to_csv(screen_dir / f"universe_{stamp}.csv", index=False)


def test_is_ftse_equivalent_market_from_policy():
    assert is_ftse_equivalent_market("sp500", {"ftse_equivalent_markets": ["sp500"]})
    assert not is_ftse_equivalent_market("euro_depth", {"ftse_equivalent_markets": ["sp500"]})
    assert not is_ftse_equivalent_market("nasdaq100", {"ftse_equivalent_markets": ["sp500"]})
    assert is_ftse_equivalent_market("sp500", {})  # product default


def test_sp500_health_ignores_nasdaq100_overlap(tmp_path: Path):
    root = tmp_path / "library"
    policy = {"ftse_equivalent_markets": ["sp500"]}
    _write_index(root, "nasdaq100", "ADBE", total=20, with_body=18)
    _write_index(root, "sp500", "AAPL", total=12, with_body=10)
    reports = [_report("ADBE"), _report("AAPL"), _report("ROP")]
    with patch(
        "value_investor.library_ingest_loop.load_library_buy_tier_reports",
        return_value=reports,
    ):
        health = snapshot_library_buy_tier_filing_health(
            "sp500",
            library_root=root,
            policy=policy,
        )
    assert health["ftse_equivalent"] is True
    assert health["coverage_scope"] == "canonical"
    assert health["unmeasured_buy_tier"] == 2
    assert set(health["unmeasured_tickers"]) == {"ADBE", "ROP"}
    assert health["zero_body_buy_tier"] == 0
    assert health["bodies_min"] == 10
    assert health["bodies_max"] == 10
    assert not ingest_parity_met(health)


def test_euro_depth_health_keeps_shard_fallback(tmp_path: Path):
    root = tmp_path / "library"
    policy = {"ftse_equivalent_markets": ["sp500"]}
    _write_index(root, "aex", "PHIA.AS", total=8, with_body=8)
    reports = [_report("PHIA.AS")]
    with patch(
        "value_investor.library_ingest_loop.load_library_buy_tier_reports",
        return_value=reports,
    ):
        health = snapshot_library_buy_tier_filing_health(
            "euro_depth",
            library_root=root,
            policy=policy,
        )
    assert health["ftse_equivalent"] is False
    assert health["coverage_scope"] == "canonical_plus_shards"
    assert health["unmeasured_buy_tier"] == 0
    assert health["bodies_min"] == 8
    assert ingest_parity_met(health)


def test_assess_learning_depth_not_ready(tmp_path: Path):
    root = tmp_path / "library"
    policy = {"ftse_equivalent_markets": ["sp500"]}
    screen_dir = root / "markets" / "sp500" / "screen"
    _write_screen_run(
        screen_dir,
        stamp="20260701_120000",
        tickers=[("AAPL", 10.0, "buy")],
    )
    _write_screen_run(
        screen_dir,
        stamp="20260708_120000",
        tickers=[("AAPL", 11.0, "hold")],
    )
    _write_index(root, "sp500", "AAPL", total=11, with_body=8)
    reports = [_report("AAPL"), _report("ROP"), _report("ADBE")]
    now = datetime(2026, 8, 26, tzinfo=UTC)
    with patch(
        "value_investor.library_ingest_loop.load_library_buy_tier_reports",
        return_value=reports,
    ):
        payload = assess_library_learning_depth(
            "sp500",
            library_root=root,
            policy=policy,
            write=True,
            write_trajectory=True,
            now=now,
        )
    assert payload["filing_ready"] is False
    assert payload["trajectory_ready"] is False
    assert payload["learning_ready"] is False
    assert payload["unmeasured_buy_tier"] == 2
    assert payload["ftse_equivalent"] is True
    assert payload["coverage_scope"] == "canonical"
    assert payload["screen"]["unique_days"] == 2
    assert payload["screen"]["span_weeks"] == 1.0
    assert payload["screen"]["stale"] is True
    assert payload["trajectory"]["event_count"] >= 0
    assert learning_depth_path(root, "sp500").exists()
    assert (screen_dir / "trajectory_transitions.json").exists()
    assert (screen_dir / "trajectory_boundary_watch.json").exists()


def test_assess_screen_archive_span_unique_days(tmp_path: Path):
    root = tmp_path / "library"
    screen_dir = root / "markets" / "sp500" / "screen"
    _write_screen_run(screen_dir, stamp="20260701_090000", tickers=[("AAA", 1.0, "buy")])
    _write_screen_run(screen_dir, stamp="20260701_180000", tickers=[("AAA", 1.1, "buy")])
    _write_screen_run(screen_dir, stamp="20260729_120000", tickers=[("AAA", 1.2, "buy")])
    span = assess_screen_archive_span(
        root,
        "sp500",
        now=datetime(2026, 8, 26, tzinfo=UTC),
    )
    assert span["archive_files"] == 3
    assert span["unique_days"] == 2
    assert span["span_weeks"] == 4.0
    assert span["last_screen"] == "2026-07-29"
    assert span["stale"] is True


def test_write_trajectory_from_snapshots(tmp_path: Path):
    root = tmp_path / "library"
    screen_dir = root / "markets" / "sp500" / "screen"
    history = screen_dir / "history"
    history.mkdir(parents=True)
    write_json(
        history / "run_20260701_120000.json",
        {
            "run_at": "2026-07-01T12:00:00+00:00",
            "prices": {"AAA": 10.0},
            "signals": [
                {"ticker": "AAA", "signal": "buy", "conviction_score": 0.4, "data_quality_score": 1.0}
            ],
        },
        compact=True,
    )
    write_json(
        history / "run_20260708_120000.json",
        {
            "run_at": "2026-07-08T12:00:00+00:00",
            "prices": {"AAA": 11.0},
            "signals": [
                {
                    "ticker": "AAA",
                    "signal": "hold",
                    "conviction_score": 0.3,
                    "data_quality_score": 1.0,
                }
            ],
        },
        compact=True,
    )
    written = write_library_trajectory_artifacts(root, "sp500")
    assert written["generated"] is True
    assert written["event_count"] >= 1
    assert Path(written["transitions_path"]).exists()


def test_learning_depth_cli_json(tmp_path: Path):
    root = tmp_path / "library"
    policy_path = tmp_path / "policy.json"
    write_json(
        policy_path,
        {"focus_market": "euro_depth", "ftse_equivalent_markets": ["sp500"]},
        compact=False,
    )
    with patch(
        "value_investor.library_learning_depth.assess_library_learning_depth",
        return_value={
            "market_id": "sp500",
            "filing_ready": False,
            "trajectory_ready": False,
            "learning_ready": False,
            "unmeasured_buy_tier": 8,
        },
    ):
        assert (
            library_main(
                [
                    "learning-depth",
                    "--market",
                    "sp500",
                    "--json",
                    "--root",
                    str(root),
                    "--policy",
                    str(policy_path),
                ]
            )
            == 0
        )


def test_canonical_only_default_for_select_targets(tmp_path: Path):
    root = tmp_path / "library"
    _write_index(root, "nasdaq100", "ADBE", total=9, with_body=9)
    from value_investor.library_ingest_loop import select_library_ingest_targets

    targets = select_library_ingest_targets(
        [_report("ADBE")],
        library_root=root,
        market_id="sp500",
        max_targets=1,
        canonical_only=True,
    )
    assert targets[0].reason == "unmeasured"
    fallback = _filing_coverage_for_ticker(
        "ADBE",
        library_root=root,
        market_id="sp500",
        canonical_only=False,
    )
    assert fallback["filings_with_body"] == 9
