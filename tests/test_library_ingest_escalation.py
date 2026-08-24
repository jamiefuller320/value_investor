"""Tests for library ingest escalation (FTSE parity)."""

from __future__ import annotations

from pathlib import Path

from value_investor.library_ingest_escalation import (
    compile_library_ingest_engineering_tasks_micro,
    library_ingest_filing_gaps,
    library_ingest_health_stalled,
    library_ingest_ticker_has_gaps,
)
from value_investor.storage import write_json


def _health(unmeasured: int = 0, zero_body: int = 0) -> dict:
    return {
        "market_id": "euro_depth",
        "buy_tier_count": 10,
        "unmeasured_buy_tier": unmeasured,
        "zero_body_buy_tier": zero_body,
        "thin_body_buy_tier": 0,
        "unmeasured_tickers": ["AAA.DE"] if unmeasured else [],
        "zero_body_tickers": [],
    }


def test_library_ingest_filing_gaps_sums_unmeasured_and_zero_body():
    assert library_ingest_filing_gaps(_health(unmeasured=3, zero_body=2)) == 5


def test_library_ingest_health_stalled_requires_flat_gap_window(tmp_path: Path):
    log_path = tmp_path / "ingest_health_log.json"
    write_json(
        log_path,
        {
            "entries": [
                {
                    "market_id": "euro_depth",
                    "health_before": _health(unmeasured=5),
                    "health_after": _health(unmeasured=5),
                    "improved": 0,
                },
                {
                    "market_id": "euro_depth",
                    "health_before": _health(unmeasured=5),
                    "health_after": _health(unmeasured=5),
                    "improved": 0,
                },
            ]
        },
        compact=False,
    )
    assert library_ingest_health_stalled(log_path, market_id="euro_depth", min_runs=2) is True


def test_library_ingest_health_not_stalled_when_gaps_shrink(tmp_path: Path):
    log_path = tmp_path / "ingest_health_log.json"
    write_json(
        log_path,
        {
            "entries": [
                {
                    "market_id": "euro_depth",
                    "health_before": _health(unmeasured=5),
                    "health_after": _health(unmeasured=4),
                    "improved": 1,
                },
                {
                    "market_id": "euro_depth",
                    "health_before": _health(unmeasured=4),
                    "health_after": _health(unmeasured=4),
                    "improved": 0,
                },
            ]
        },
        compact=False,
    )
    assert library_ingest_health_stalled(log_path, market_id="euro_depth", min_runs=2) is False


def test_library_ingest_ticker_has_gaps_unmeasured(tmp_path: Path):
    root = tmp_path / "library"
    market = "euro_depth"
    ticker = "AAA.DE"
    filings_dir = root / "markets" / market / "screen" / "research" / ticker / "sources" / "filings"
    filings_dir.mkdir(parents=True)
    write_json(
        filings_dir / "filings_index.json",
        {"summary": {"total": 0, "with_body": 0}, "filings": []},
        compact=False,
    )
    assert library_ingest_ticker_has_gaps(ticker, market_id=market, library_root=root) is True


def test_compile_library_ingest_micro_when_stalled(tmp_path: Path, monkeypatch):
    tasks_path = tmp_path / "engineering_tasks.json"
    write_json(tasks_path, {"tasks": []}, compact=False)
    monkeypatch.setattr(
        "value_investor.library_ingest_escalation.has_open_ingest_engineering_tasks",
        lambda *a, **k: False,
    )
    result = compile_library_ingest_engineering_tasks_micro(
        market_id="euro_depth",
        health_after=_health(unmeasured=4, zero_body=1),
        tasks_path=tasks_path,
        committed_path=tasks_path,
    )
    assert result["compiled_count"] == 1
    payload = __import__("value_investor.storage", fromlist=["read_json"]).read_json(tasks_path)
    task = payload["tasks"][0]
    assert task["area"] == "ingest"
    assert task["source"] == "library_ingest_stall"
    assert task["evidence"]["market_id"] == "euro_depth"
