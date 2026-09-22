"""Skip re-pinning tickers that already burned a zero-yield intensive pass."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from value_investor.ingest_gap_closure import (
    evaluate_library_ingest_gap_closure_followup,
    has_recent_zero_yield_intensive_for_ticker,
    intensive_run_was_zero_yield,
    select_library_gap_closure_candidate,
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
    filings_dir.mkdir(parents=True)
    write_json(
        filings_dir / "filings_index.json",
        {"summary": {"total": total, "with_body": with_body}, "filings": []},
        compact=False,
    )


def _record_zero_yield(
    runs_path: Path,
    *,
    ticker: str,
    market_id: str,
    hours_ago: float = 1.0,
) -> None:
    stamp = (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat()
    write_json(
        runs_path,
        {
            "runs": [
                {
                    "id": "igc-zero-01",
                    "ticker": ticker,
                    "status": "pending_review",
                    "recorded_at": stamp,
                    "completed_at": stamp,
                    "params": {
                        "intensive_gap_closure": True,
                        "market_id": market_id,
                        "require_outstanding_gaps": True,
                    },
                    "outcome": {
                        "delta_filings_with_body": 0,
                        "per_ticker": [{"ticker": ticker, "improved": False}],
                        "results": [
                            {
                                "ticker": ticker,
                                "improved": False,
                                "ir_refetch": {"attempted": 0, "fetched": 0},
                            }
                        ],
                    },
                }
            ],
            "updated_at": stamp,
        },
        compact=False,
    )


def test_intensive_run_was_zero_yield_detects_empty_ir():
    run = {
        "outcome": {
            "delta_filings_with_body": 0,
            "per_ticker": [{"improved": False}],
            "results": [{"ir_refetch": {"attempted": 0, "fetched": 0}}],
        },
        "params": {"market_id": "euro_depth"},
    }
    assert intensive_run_was_zero_yield(run) is True


def test_select_skips_recent_zero_yield_ticker(tmp_path: Path):
    root = tmp_path / "library"
    market = "euro_depth"
    _write_index(root, market, "RAND.AS", total=3, with_body=0)
    _write_index(root, market, "ABI.BR", total=5, with_body=2)
    reports = [_report("RAND.AS"), _report("ABI.BR", conviction=0.9)]
    runs_path = tmp_path / "runs.json"
    _record_zero_yield(runs_path, ticker="RAND.AS", market_id=market)

    assert has_recent_zero_yield_intensive_for_ticker(
        "RAND.AS",
        runs_path=runs_path,
        market_id=market,
    )

    result = select_library_gap_closure_candidate(
        market_id=market,
        library_root=root,
        reports=reports,
        runs_path=runs_path,
    )
    assert result["should_dispatch"] is True
    assert result["pin_ticker"] == "ABI.BR"
    assert result.get("skipped_zero_yield", 0) >= 1


def test_followup_skips_when_only_zero_yield_candidates_remain(tmp_path: Path):
    root = tmp_path / "library"
    market = "euro_depth"
    _write_index(root, market, "RAND.AS", total=3, with_body=0)
    reports = [_report("RAND.AS")]
    runs_path = tmp_path / "runs.json"
    _record_zero_yield(runs_path, ticker="RAND.AS", market_id=market, hours_ago=7.0)

    result = evaluate_library_ingest_gap_closure_followup(
        market_id=market,
        health_after={
            "indexed_without_body": 1,
            "zero_body_buy_tier": 1,
            "unmeasured_buy_tier": 0,
            "zero_body_tickers": ["RAND.AS"],
        },
        was_gap_closure_run=False,
        stalled=True,
        improved=[],
        library_root=root,
        reports=reports,
        tasks_path=tmp_path / "engineering_tasks.json",
        runs_path=runs_path,
    )
    assert result["should_dispatch"] is False
    assert "zero-yield" in result["reason"]
