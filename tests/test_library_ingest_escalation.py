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


def test_compile_library_ingest_micro_ignores_open_hunter(tmp_path: Path):
    from value_investor.engineering_tasks import (
        PARKED_SOURCE_HUNTER_PRIORITY_SCORE,
        PARKED_SOURCE_HUNTER_SOURCE,
    )
    from value_investor.storage import read_json

    tasks_path = tmp_path / "engineering_tasks.json"
    write_json(
        tasks_path,
        {
            "tasks": [
                {
                    "id": "eng-20260906-01",
                    "area": "ingest",
                    "title": "Hunt fetchable IR source for parked sp500 leftover FICO",
                    "summary": "low priority hunter",
                    "priority": "low",
                    "priority_score": PARKED_SOURCE_HUNTER_PRIORITY_SCORE,
                    "source": PARKED_SOURCE_HUNTER_SOURCE,
                    "status": "open",
                    "evidence": {"market_id": "sp500", "hunter_ticker": "FICO"},
                }
            ]
        },
        compact=False,
    )
    result = compile_library_ingest_engineering_tasks_micro(
        market_id="euro_depth",
        health_after=_health(unmeasured=4, zero_body=1),
        tasks_path=tasks_path,
        committed_path=tasks_path,
    )
    assert result["compiled_count"] == 1
    payload = read_json(tasks_path)
    sources = [row["source"] for row in payload["tasks"] if row.get("status") == "open"]
    assert PARKED_SOURCE_HUNTER_SOURCE in sources
    assert "library_ingest_stall" in sources


def test_compile_parked_source_hunter_sits_at_back_and_chains(tmp_path: Path):
    from value_investor.engineering_tasks import (
        PARKED_SOURCE_HUNTER_PRIORITY_SCORE,
        PARKED_SOURCE_HUNTER_SOURCE,
    )
    from value_investor.library_ingest_escalation import compile_parked_source_hunter_task
    from value_investor.storage import read_json

    root = tmp_path / "library"
    tasks_path = tmp_path / "engineering_tasks.json"
    write_json(tasks_path, {"tasks": []}, compact=False)
    exhaustion_dir = root / "markets" / "sp500"
    exhaustion_dir.mkdir(parents=True)
    write_json(
        exhaustion_dir / "ingest_exhaustion.json",
        {
            "schema_version": 1,
            "market_id": "sp500",
            "exhausted": True,
            "parked": [
                {"ticker": "FICO", "reason": "unfetchable_iwb"},
                {"ticker": "JBH.AX", "reason": "awaiting_periodic_report"},
            ],
        },
        compact=False,
    )
    policy = {
        "focus_market": "euro_depth",
        "market_queue": ["sp500", "asx200"],
        "ingest_exhausted_markets": ["sp500"],
    }
    first = compile_parked_source_hunter_task(
        library_root=root,
        policy=policy,
        tasks_path=tasks_path,
        committed_path=tasks_path,
    )
    assert first["compiled_count"] == 1
    assert first["hunter_ticker"] == "FICO"
    assert first["priority_score"] == PARKED_SOURCE_HUNTER_PRIORITY_SCORE
    payload = read_json(tasks_path)
    hunter = payload["tasks"][0]
    assert hunter["source"] == PARKED_SOURCE_HUNTER_SOURCE
    assert hunter["priority"] == "low"
    assert hunter["auto_merge"] is False

    second = compile_parked_source_hunter_task(
        library_root=root,
        policy=policy,
        tasks_path=tasks_path,
        committed_path=tasks_path,
    )
    assert second["compiled_count"] == 0
    assert second["reason"] == "open parked-source hunter already queued"

    payload["tasks"][0]["status"] = "merged"
    write_json(tasks_path, payload, compact=False)
    third = compile_parked_source_hunter_task(
        library_root=root,
        policy=policy,
        tasks_path=tasks_path,
        committed_path=tasks_path,
    )
    assert third["compiled_count"] == 1
    assert third["hunter_ticker"] == "JBH.AX"
