"""Tests for archive → history backfill and rebalance log bootstrap."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from value_investor.archive_history import (
    backfill_run_history_from_archives,
    list_dashboard_archives,
)
from value_investor.backtest import load_run_snapshots
from value_investor.paper_automation import AutomationConfig
from value_investor.paper_fund import PaperFund, PaperFundConfig
from value_investor.rebalance_log import (
    REBALANCE_LOG_FILENAME,
    bootstrap_rebalance_log,
    load_rebalance_log,
)
from value_investor.simulator import SimulatorConfig, run_grace_parameter_sweep


def test_list_dashboard_archives_sorted(tmp_path: Path):
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "2026-07-20.json").write_text(
        json.dumps({"run_at": "2026-07-20T12:00:00+00:00", "reports": []}),
        encoding="utf-8",
    )
    (archive / "2026-07-19.json").write_text(
        json.dumps({"run_at": "2026-07-19T12:00:00+00:00", "reports": []}),
        encoding="utf-8",
    )
    found = list_dashboard_archives(archive)
    assert [path.name for _, path in found] == ["2026-07-19.json", "2026-07-20.json"]


def test_backfill_skips_existing_snapshot_dates(tmp_path: Path, monkeypatch):
    data = tmp_path / "data"
    archive = data / "archive"
    history = data / "history"
    archive.mkdir(parents=True)
    history.mkdir(parents=True)

    (archive / "2026-07-20.json").write_text(
        json.dumps(
            {
                "run_at": "2026-07-20T20:00:00+00:00",
                "reports": [
                    {
                        "ticker": "AAA.L",
                        "signal": "strong_buy",
                        "conviction_score": 0.9,
                        "timing_signal": "neutral",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    stamp = "run_20260720_120000.json.gz"
    gzip.open(history / stamp, "wt").write(
        json.dumps(
            {
                "run_at": "2026-07-20T15:00:00+00:00",
                "prices": {"AAA.L": 10.0},
                "signals": [{"ticker": "AAA.L", "signal": "strong_buy"}],
            }
        )
    )

    monkeypatch.setattr(
        "value_investor.archive_history.snapshot_prices",
        lambda tickers: {t: 10.0 for t in tickers} | {"^FTSE": 8000.0},
    )

    written = backfill_run_history_from_archives(data, fetch_prices=True)
    assert written == []
    assert len(load_run_snapshots(data)) == 1


def test_backfill_writes_missing_archive_day(tmp_path: Path, monkeypatch):
    data = tmp_path / "data"
    archive = data / "archive"
    archive.mkdir(parents=True)
    (archive / "2026-07-19.json").write_text(
        json.dumps(
            {
                "run_at": "2026-07-19T10:00:00+00:00",
                "reports": [
                    {
                        "ticker": "BBB.L",
                        "signal": "buy",
                        "conviction_score": 0.8,
                        "timing_signal": "accumulate",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "value_investor.archive_history.snapshot_prices",
        lambda tickers: {t: 12.0 for t in tickers} | {"^FTSE": 8000.0},
    )
    written = backfill_run_history_from_archives(data, fetch_prices=True)
    assert len(written) == 1
    snapshots = load_run_snapshots(data)
    assert len(snapshots) == 1
    assert snapshots[0].signals[0]["ticker"] == "BBB.L"


def test_bootstrap_rebalance_log_from_trades_and_archive(tmp_path: Path):
    track = tmp_path / "rules"
    track.mkdir()
    archive = tmp_path / "archive"
    archive.mkdir()

    fund = PaperFund.create(
        PaperFundConfig(
            name="Auto",
            mode="automated",
            initial_cash=1000,
            trade_cost_pct=0.0,
            max_positions=2,
        )
    )
    fund.buy(
        ticker="AAA.L",
        price=10,
        sizing_mode="cash",
        amount=400,
        sector="Banks",
        name="Alpha",
        acted_at="2026-07-20T21:32:40+01:00",
    )
    fund.buy(
        ticker="BBB.L",
        price=20,
        sizing_mode="cash",
        amount=400,
        sector="Mining",
        name="Beta",
        acted_at="2026-07-20T21:32:40+01:00",
    )
    (track / "automated_fund.json").write_text(
        json.dumps(fund.to_dict()),
        encoding="utf-8",
    )
    (track / "config.json").write_text(
        json.dumps(AutomationConfig(max_positions=2, trade_cost_pct=0.0).to_dict()),
        encoding="utf-8",
    )
    (archive / "2026-07-20.json").write_text(
        json.dumps(
            {
                "run_at": "2026-07-20T20:32:27+00:00",
                "reports": [
                    {
                        "ticker": "AAA.L",
                        "signal": "strong_buy",
                        "conviction_score": 0.9,
                        "timing_signal": "neutral",
                        "sector": "Banks",
                    },
                    {
                        "ticker": "BBB.L",
                        "signal": "buy",
                        "conviction_score": 0.8,
                        "timing_signal": "neutral",
                        "sector": "Mining",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = bootstrap_rebalance_log(track, archive_dir=archive, fetch_prices=False)
    assert result["ok"] is True
    assert result["entries"] == 1
    entries = load_rebalance_log(track)
    assert len(entries) == 1
    assert entries[0]["bootstrapped"] is True
    assert entries[0]["acted"] is True
    assert entries[0]["schema_version"] == 2
    assert "screen_buy_tier" in entries[0]
    assert "gate_excluded" in entries[0]
    assert len(entries[0]["trades"]) == 2
    assert (track / REBALANCE_LOG_FILENAME).exists()


def test_grace_parameter_sweep_runs():
    from value_investor.backtest import RunSnapshot

    snapshots = [
        RunSnapshot(
            run_at="2026-01-01T00:00:00+00:00",
            prices={"AAA.L": 10.0, "^FTSE": 8000.0},
            signals=[
                {
                    "ticker": "AAA.L",
                    "signal": "strong_buy",
                    "conviction_score": 0.9,
                    "timing_signal": "neutral",
                    "price_vs_sma200_pct": 0.05,
                }
            ],
        ),
        RunSnapshot(
            run_at="2026-01-08T00:00:00+00:00",
            prices={"AAA.L": 11.0, "^FTSE": 8100.0},
            signals=[
                {
                    "ticker": "AAA.L",
                    "signal": "hold",
                    "conviction_score": 0.4,
                    "timing_signal": "neutral",
                    "price_vs_sma200_pct": 0.04,
                }
            ],
        ),
        RunSnapshot(
            run_at="2026-01-15T00:00:00+00:00",
            prices={"AAA.L": 12.0, "^FTSE": 8200.0},
            signals=[
                {
                    "ticker": "AAA.L",
                    "signal": "hold",
                    "conviction_score": 0.3,
                    "timing_signal": "neutral",
                    "price_vs_sma200_pct": 0.03,
                }
            ],
        ),
    ]
    sweep = run_grace_parameter_sweep(
        snapshots,
        grace_weeks_values=[4, 6],
        base=SimulatorConfig(initial_capital=1000, trade_cost_pct=0.0, max_positions=1),
    )
    assert len(sweep) == 2
    assert sweep[0]["grace_weeks"] == 4
    assert "total_return" in sweep[0]
