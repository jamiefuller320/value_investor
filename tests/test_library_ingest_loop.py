"""Tests for library weekday ingest loop."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from value_investor.library_ingest_loop import (
    select_library_ingest_targets,
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


def test_select_library_ingest_targets_prioritizes_unmeasured(tmp_path: Path):
    root = tmp_path / "library"
    market = "euro_depth"
    screen_dir = root / "markets" / market / "screen"
    research_dir = screen_dir / "research"
    for ticker in ("AAA.DE", "BBB.DE"):
        filings_dir = research_dir / ticker / "sources" / "filings"
        filings_dir.mkdir(parents=True)
        write_json(
            filings_dir / "filings_index.json",
            {
                "summary": {"total": 0 if ticker == "AAA.DE" else 5, "with_body": 0},
                "filings": [],
            },
            compact=False,
        )
    reports = [_report("AAA.DE"), _report("BBB.DE", conviction=0.9)]
    targets = select_library_ingest_targets(
        reports,
        library_root=root,
        market_id=market,
        max_targets=2,
    )
    assert targets[0].ticker == "AAA.DE"
    assert targets[0].reason == "unmeasured"
