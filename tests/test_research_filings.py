"""Tests for primary RNS/results filings ingest (separate from Yahoo)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from value_investor.research.filings import (
    classify_filing_period,
    ingest_filings,
    merge_filings,
    summarize_filings,
)
from value_investor.research.ingest import ingest_research_sources


def test_classify_filing_period_annual_and_interim():
    assert classify_filing_period("Shell Plc 4th Quarter 2025 and Full Year Unaudited Results") == "annual"
    assert classify_filing_period("Shell Publishes Annual Report and Accounts") == "annual"
    assert classify_filing_period("Half-year Results") == "interim"
    assert classify_filing_period("Q1 Trading Update") == "interim"
    assert classify_filing_period("Interim Results for the six months ended 30 June") == "interim"
    assert classify_filing_period("Transaction in Own Shares") == "other"
    assert classify_filing_period("Shell plc First Quarter 2026 Interim Dividend") == "other"
    assert classify_filing_period("Shell plc Announces Final Results of Exchange Offers") == "other"


def test_merge_filings_prefers_body_and_ticker_source():
    google = [
        {
            "id": "g1",
            "source": "google_news_investegate",
            "headline": "Half-year Results",
            "published_at": "2026-07-01T07:00:00+00:00",
            "url": "https://news.google.com/rss/articles/abc",
            "period": "interim",
            "has_body": False,
            "priority": 100,
        }
    ]
    ticker = [
        {
            "id": "t1",
            "source": "ticker_rns_api",
            "headline": "Half-year Results",
            "published_at": "2026-07-01T07:00:00+00:00",
            "url": "https://www.investegate.co.uk/announcement/rns/example/half-year/1",
            "period": "interim",
            "has_body": False,
            "priority": 100,
        }
    ]
    merged = merge_filings(google, ticker)
    assert len(merged) == 1
    assert merged[0]["source"] == "ticker_rns_api"


def test_summarize_filings_counts_periods():
    filings = [
        {"period": "annual", "has_body": True},
        {"period": "interim", "has_body": False},
        {"period": "interim", "has_body": True},
        {"period": "other", "has_body": False},
    ]
    summary = summarize_filings(filings)
    assert summary == {
        "total": 4,
        "annual": 1,
        "interim": 2,
        "other": 1,
        "with_body": 2,
    }


def test_ingest_filings_writes_index(tmp_path: Path):
    fake_rows = [
        {
            "id": "abcd1234abcd1234",
            "source": "google_news_investegate",
            "headline": "Example Full Year Results",
            "published_at": "2026-02-05T07:00:00+00:00",
            "url": "https://news.google.com/rss/articles/x",
            "period": "annual",
            "category": None,
            "summary": "",
            "has_body": False,
            "body_path": None,
            "priority": 120,
        },
        {
            "id": "efefefefefefefef",
            "source": "google_news_investegate",
            "headline": "Example Half-year Results",
            "published_at": "2025-08-01T07:00:00+00:00",
            "url": "https://news.google.com/rss/articles/y",
            "period": "interim",
            "category": None,
            "summary": "",
            "has_body": False,
            "body_path": None,
            "priority": 100,
        },
    ]
    with (
        patch("value_investor.research.filings.fetch_filings_ticker_api", return_value=[]),
        patch("value_investor.research.filings.fetch_filings_google_news", return_value=fake_rows),
        patch("value_investor.research.filings.fetch_filing_body", return_value=None),
    ):
        meta = ingest_filings(
            ticker="EXAM.L",
            company_name="Example PLC",
            sources_dir=tmp_path,
        )

    index_path = Path(meta["filings_index_path"])
    assert index_path.exists()
    data = json.loads(index_path.read_text(encoding="utf-8"))
    assert data["ticker"] == "EXAM.L"
    assert data["summary"]["annual"] == 1
    assert data["summary"]["interim"] == 1
    assert (tmp_path / "filings" / "filings_index.json").exists()


def test_ingest_research_sources_keeps_filings_separate_from_yahoo(tmp_path: Path):
    sources = tmp_path / "sources"
    with (
        patch(
            "value_investor.research.ingest.fetch_annual_financials",
            return_value={
                "ticker": "EXAM.L",
                "income_statement": {"2025": {"Total Revenue": 1.0}},
                "balance_sheet": {},
                "cash_flow": {},
                "quarterly_income": {},
            },
        ),
        patch("value_investor.research.ingest.fetch_yfinance_news", return_value=[]),
        patch("value_investor.research.ingest.fetch_google_news_rss", return_value=[]),
        patch(
            "value_investor.research.filings.fetch_filings_ticker_api",
            return_value=[],
        ),
        patch(
            "value_investor.research.filings.fetch_filings_google_news",
            return_value=[
                {
                    "id": "f1f1f1f1f1f1f1f1",
                    "source": "google_news_investegate",
                    "headline": "Full Year Results",
                    "published_at": "2026-02-01T07:00:00+00:00",
                    "url": "https://news.google.com/rss/articles/z",
                    "period": "annual",
                    "category": None,
                    "summary": "",
                    "has_body": False,
                    "body_path": None,
                    "priority": 120,
                }
            ],
        ),
        patch("value_investor.research.filings.fetch_filing_body", return_value=None),
    ):
        meta = ingest_research_sources(
            ticker="EXAM.L",
            company_name="Example PLC",
            screening_snapshot={"ticker": "EXAM.L", "signal": "strong_buy"},
            sources_dir=sources,
        )

    assert (sources / "financials_annual.json").exists()
    assert (sources / "filings" / "filings_index.json").exists()
    assert meta["filings_summary"]["annual"] == 1
    # Yahoo and filings remain distinct files
    yahoo = json.loads((sources / "financials_annual.json").read_text(encoding="utf-8"))
    filings = json.loads((sources / "filings" / "filings_index.json").read_text(encoding="utf-8"))
    assert "income_statement" in yahoo
    assert "filings" in filings
    assert yahoo != filings


def test_ingest_filings_saves_body_for_direct_url(tmp_path: Path):
    rows = [
        {
            "id": "bodybodybodybody",
            "source": "ticker_rns_api",
            "headline": "Half-year Results",
            "published_at": "2026-07-01T07:00:00+00:00",
            "url": "https://www.investegate.co.uk/announcement/rns/example--ex/half-year/1",
            "period": "interim",
            "category": "Half-year Report",
            "summary": "",
            "has_body": False,
            "body_path": None,
            "priority": 100,
        }
    ]
    body_text = "A" * 250 + " revenue increased and cash generation remained solid."
    with (
        patch("value_investor.research.filings.fetch_filings_ticker_api", return_value=rows),
        patch("value_investor.research.filings.fetch_filings_google_news", return_value=[]),
        patch("value_investor.research.filings.fetch_filing_body", return_value=body_text),
    ):
        meta = ingest_filings(
            ticker="EX.L",
            company_name="Example",
            sources_dir=tmp_path,
        )

    assert meta["filings_summary"]["with_body"] == 1
    bodies = list((tmp_path / "filings" / "bodies").glob("*.txt"))
    assert len(bodies) == 1
    assert "revenue increased" in bodies[0].read_text(encoding="utf-8")
