"""Tests for buy-tier ingest utilization audit."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.ingest_utilization_audit import run_ingest_utilization_audit


def test_ingest_utilization_audit_buy_tier_matrix(tmp_path: Path):
    latest = tmp_path / "latest.json"
    research_root = tmp_path / "research"
    memo_dir = tmp_path / "memos"
    memo_dir.mkdir()

    ticker = "TST.L"
    sources = research_root / ticker / "sources"
    filings = sources / "filings"
    bodies = filings / "bodies"
    bodies.mkdir(parents=True)
    (filings / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "period": "interim",
                        "has_body": True,
                        "body_path": "bodies/interim.txt",
                        "published_at": "2026-01-01",
                    },
                    {"period": "annual", "has_body": False},
                ],
                "summary": {"total": 2, "with_body": 1},
            }
        ),
        encoding="utf-8",
    )
    (bodies / "interim.txt").write_text(
        "diluted earnings per share decline of 5.0%",
        encoding="utf-8",
    )
    (sources / "financials_annual.json").write_text(
        json.dumps({"income_statement": {"2024": {"Net Income": 100}}}),
        encoding="utf-8",
    )
    (memo_dir / f"{ticker}.md").write_text("# memo", encoding="utf-8")

    latest.write_text(
        json.dumps(
            {
                "run_at": "2026-08-01T00:00:00+00:00",
                "reports": [
                    {
                        "ticker": ticker,
                        "name": "Test plc",
                        "signal": "buy",
                        "adjusted_signal": "buy",
                        "research_verdict": "accumulate",
                        "research_confidence": 0.8,
                        "interim_eps_decline_pct": 0.05,
                    },
                ],
                "research": [
                    {
                        "ticker": ticker,
                        "memo_quality": {"grade": "adequate"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = run_ingest_utilization_audit(
        latest_path=latest,
        research_root=research_root,
        memo_dir=memo_dir,
    )
    assert payload["summary"]["buy_tier_count"] == 1
    row = payload["rows"][0]
    assert row["ticker"] == ticker
    assert row["filings_with_body"] == 1
    assert row["indexed_without_body"] == 1
    assert row["has_memo"] is True
    assert row["interim_eps_source"] == "body"
    assert row["screen_uses_body_parser"] is True
    assert row["ai_track_buy_eligible"] is True


def test_ingest_utilization_audit_resolves_filename_only_body_path(tmp_path: Path):
    latest = tmp_path / "latest.json"
    research_root = tmp_path / "research"
    memo_dir = tmp_path / "memos"
    memo_dir.mkdir()
    ticker = "MEGP.L"
    sources = research_root / ticker / "sources"
    bodies = sources / "filings" / "bodies"
    bodies.mkdir(parents=True)
    (sources / "filings" / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "period": "interim",
                        "has_body": True,
                        "body_path": "abc123.txt",
                        "published_at": "2026-03-01",
                    }
                ],
                "summary": {"total": 1, "with_body": 1},
            }
        ),
        encoding="utf-8",
    )
    (bodies / "abc123.txt").write_text(
        "diluted earnings per share decline of 3.9%",
        encoding="utf-8",
    )
    (memo_dir / f"{ticker}.md").write_text("# memo", encoding="utf-8")
    latest.write_text(
        json.dumps(
            {
                "reports": [
                    {
                        "ticker": ticker,
                        "signal": "buy",
                        "adjusted_signal": "buy",
                        "research_verdict": "accumulate",
                        "interim_eps_decline_pct": 0.039,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    payload = run_ingest_utilization_audit(
        latest_path=latest,
        research_root=research_root,
        memo_dir=memo_dir,
    )
    row = payload["rows"][0]
    assert row["interim_eps_source"] == "body"
    assert row["screen_uses_body_parser"] is True
