"""Tests for library maintenance discovery scan."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

from value_investor.ingest_discovery_scan import TickerDiscoveryHit
from value_investor.library_discovery_scan import (
    run_library_buy_tier_discovery_scan,
    scan_library_ticker_for_new_filings,
)
from value_investor.summary import CompanyReport


def _report(ticker: str) -> CompanyReport:
    return CompanyReport(
        ticker=ticker,
        name=f"{ticker} Co",
        sector="X",
        signal="buy",
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
        conviction_score=0.5,
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


def test_scan_library_ticker_detects_new_rows(tmp_path: Path):
    root = tmp_path / "library"
    market = "euro_depth"
    filings_dir = (
        root / "markets" / market / "screen" / "research" / "AAA.DE" / "sources" / "filings"
    )
    filings_dir.mkdir(parents=True)
    (filings_dir / "filings_index.json").write_text(
        '{"summary":{"total":1,"with_body":0},"filings":[{"id":"old","url":"http://x"}]}',
        encoding="utf-8",
    )
    discovered = [
        {"id": "old", "url": "http://x", "headline": "Old"},
        {"id": "new", "url": "http://y", "headline": "New"},
    ]
    with patch(
        "value_investor.library_discovery_scan.list_regime_filings_index_only",
        return_value=discovered,
    ):
        hit = scan_library_ticker_for_new_filings(
            _report("AAA.DE"),
            library_root=root,
            market_id=market,
            persist_index=False,
        )
    assert hit.new_row_count == 1
    assert hit.has_work is True


def test_run_library_buy_tier_discovery_scan_counts_hits(tmp_path: Path):
    def _hit(report: CompanyReport) -> TickerDiscoveryHit:
        return TickerDiscoveryHit(
            ticker=report.ticker,
            name=report.name,
            signal=report.signal,
            new_row_count=1 if report.ticker == "AAA.DE" else 0,
        )

    with patch(
        "value_investor.library_discovery_scan.scan_library_ticker_for_new_filings",
        side_effect=lambda report, **kwargs: _hit(report),
    ):
        summary = run_library_buy_tier_discovery_scan(
            [_report("AAA.DE"), _report("BBB.DE")],
            library_root=tmp_path,
            market_id="euro_depth",
            persist_summary=False,
        )
    assert summary.scanned == 2
    assert summary.hits == 1
    assert summary.new_rows_total == 1
    assert summary.runtime_cutoff is False


def test_run_library_buy_tier_discovery_scan_stops_at_deadline():
    def _slow_hit(report: CompanyReport, **_kwargs) -> TickerDiscoveryHit:
        time.sleep(0.04)
        return TickerDiscoveryHit(
            ticker=report.ticker,
            name=report.name,
            signal=report.signal,
            new_row_count=0,
        )

    with patch(
        "value_investor.library_discovery_scan.scan_library_ticker_for_new_filings",
        side_effect=_slow_hit,
    ):
        summary = run_library_buy_tier_discovery_scan(
            [_report("AAA.DE"), _report("BBB.DE"), _report("CCC.DE")],
            library_root=Path("."),
            market_id="euro_depth",
            persist_summary=False,
            max_runtime_seconds=0.05,
        )
    assert summary.runtime_cutoff is True
    assert 1 <= summary.scanned < 3


def test_run_library_buy_tier_discovery_scan_prefers_critical_tickers():
    order: list[str] = []

    def _hit(report: CompanyReport, **_kwargs) -> TickerDiscoveryHit:
        order.append(report.ticker)
        return TickerDiscoveryHit(
            ticker=report.ticker,
            name=report.name,
            signal=report.signal,
        )

    with patch(
        "value_investor.library_discovery_scan.scan_library_ticker_for_new_filings",
        side_effect=_hit,
    ):
        run_library_buy_tier_discovery_scan(
            [_report("AAA.DE"), _report("BBB.DE"), _report("CCC.DE")],
            library_root=Path("."),
            market_id="euro_depth",
            persist_summary=False,
            prefer_tickers=["CCC.DE"],
        )
    assert order[0] == "CCC.DE"
