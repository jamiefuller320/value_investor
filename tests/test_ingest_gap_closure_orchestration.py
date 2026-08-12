"""Tests for ingest gap-closure orchestration hooks."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.ingest_gap_closure import (
    evaluate_eng_idle_gap_closure_dispatch,
    evaluate_weekly_gap_closure_followup,
    paper_holding_tickers,
)


def _gap_data_dir(tmp_path: Path, ticker: str = "HLN.L") -> Path:
    data_dir = tmp_path / "docs" / "data"
    filings = data_dir / "research" / ticker / "sources" / "filings"
    filings.mkdir(parents=True)
    (filings / "filings_index.json").write_text(
        json.dumps(
            {
                "summary": {"total": 2, "annual": 1, "interim": 1, "with_body": 1},
                "filings": [
                    {"period": "annual", "has_body": True},
                    {"period": "interim", "has_body": False},
                ],
            }
        ),
        encoding="utf-8",
    )
    latest = data_dir / "latest.json"
    latest.write_text(
        json.dumps(
            {
                "reports": [
                    {
                        "ticker": ticker,
                        "name": "Test Co",
                        "sector": "Health",
                        "signal": "strong_buy",
                        "models_passed": 5,
                        "model_count": 10,
                        "composite_score": 0.8,
                        "sector_composite_score": 0.8,
                        "families_passed": 4,
                        "passed_families": "cheapness,quality",
                        "data_quality_score": 0.9,
                        "metrics_present": 18,
                        "metrics_total": 20,
                        "weeks_at_signal": 1,
                        "signal_trend": "new",
                        "conviction_score": 0.5,
                        "stability_label": "new",
                        "timing_signal": "neutral",
                        "timing_score": 0.0,
                        "rsi_14": 50.0,
                        "price_vs_sma200_pct": 0.0,
                        "action_note": "",
                        "summary": "test",
                        "passed_models": [],
                        "key_metrics": {},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return data_dir


def test_weekly_gap_closure_followup_dispatches_when_gaps_remain(tmp_path: Path):
    data_dir = _gap_data_dir(tmp_path)
    result = evaluate_weekly_gap_closure_followup(
        health_after={"indexed_without_body": 3, "zero_body_buy_tier": 0},
        was_gap_closure_run=False,
        latest_path=data_dir / "latest.json",
        data_dir=data_dir,
        tasks_path=data_dir / "engineering_tasks.json",
        runs_path=data_dir / "ingest_gap_closure_runs.json",
    )
    assert result["should_dispatch"] is True
    assert result["trigger"] == "weekly_followup"
    assert result["pin_ticker"] == "HLN.L"


def test_eng_idle_gap_closure_prefers_paper_holdings(tmp_path: Path):
    data_dir = _gap_data_dir(tmp_path, ticker="HLN.L")
    paper_dir = data_dir / "paper_automation" / "ai_judgment"
    paper_dir.mkdir(parents=True)
    (paper_dir / "automated_fund.json").write_text(
        json.dumps({"holdings": {"HLN.L": {"shares": 10}}}),
        encoding="utf-8",
    )
    assert "HLN.L" in paper_holding_tickers(data_dir)
    result = evaluate_eng_idle_gap_closure_dispatch(
        open_count=0,
        pr_open_count=0,
        latest_path=data_dir / "latest.json",
        data_dir=data_dir,
        tasks_path=data_dir / "engineering_tasks.json",
        runs_path=data_dir / "ingest_gap_closure_runs.json",
    )
    assert result["should_dispatch"] is True
    assert result["trigger"] == "eng_idle"
    assert result["pin_ticker"] == "HLN.L"


def test_eng_idle_skips_when_queue_not_idle(tmp_path: Path):
    data_dir = _gap_data_dir(tmp_path)
    result = evaluate_eng_idle_gap_closure_dispatch(
        open_count=2,
        pr_open_count=0,
        latest_path=data_dir / "latest.json",
        data_dir=data_dir,
    )
    assert result["should_dispatch"] is False
    assert result["reason"] == "engineering queue not idle"
