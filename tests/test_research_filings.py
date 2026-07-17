"""Tests for primary RNS/results and SEC EDGAR filings ingest (separate from Yahoo)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from value_investor.research.filings import (
    classify_filing_period,
    ingest_filings,
    merge_filings,
    resolve_filings_regime,
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
    assert classify_filing_period("10-K", form="10-K") == "annual"
    assert classify_filing_period("10-Q", form="10-Q") == "interim"
    assert classify_filing_period("8-K", form="8-K") == "other"


def test_resolve_filings_regime_by_market_and_ticker():
    assert resolve_filings_regime("sp500", "ACN") == "sec_edgar"
    assert resolve_filings_regime("ftse350", "SHEL.L") == "uk_rns"
    assert resolve_filings_regime(None, "SHEL.L") == "uk_rns"
    assert resolve_filings_regime(None, "ACN") == "sec_edgar"
    assert resolve_filings_regime("asx200", "BHP.AX") == "asx_announcements"
    assert resolve_filings_regime(None, "BHP.AX") == "asx_announcements"
    assert resolve_filings_regime("euro_stoxx50", "SAP.DE") == "euro_filings"
    assert resolve_filings_regime(None, "SAP.DE") == "euro_filings"


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


def test_ingest_filings_sec_edgar_writes_annual_interim_bodies(tmp_path: Path):
    sec_rows = [
        {
            "id": "sec10k10k10k10k",
            "source": "sec_edgar",
            "headline": "10-K: Annual report",
            "published_at": "2026-02-10T00:00:00+00:00",
            "url": "https://www.sec.gov/Archives/edgar/data/91142/000009114226000008/aos-20251231.htm",
            "period": "annual",
            "category": "10-K",
            "form": "10-K",
            "summary": "",
            "has_body": False,
            "body_path": None,
            "priority": 130,
        },
        {
            "id": "sec10q10q10q10q",
            "source": "sec_edgar",
            "headline": "10-Q: Quarterly report",
            "published_at": "2026-04-30T00:00:00+00:00",
            "url": "https://www.sec.gov/Archives/edgar/data/91142/000009114226000084/aos-20260331.htm",
            "period": "interim",
            "category": "10-Q",
            "form": "10-Q",
            "summary": "",
            "has_body": False,
            "body_path": None,
            "priority": 100,
        },
    ]
    body_text = "A" * 250 + " Item 8 Financial Statements and Consolidated Balance Sheets."
    with (
        patch("value_investor.research.filings.fetch_filings_sec_edgar", return_value=sec_rows),
        patch("value_investor.research.filings.fetch_filing_body", return_value=body_text),
        patch("value_investor.research.filings.fetch_filings_ticker_api") as uk_api,
        patch("value_investor.research.filings.fetch_filings_google_news") as uk_news,
    ):
        meta = ingest_filings(
            ticker="AOS",
            company_name="A. O. Smith Corporation",
            sources_dir=tmp_path,
            market="sp500",
        )

    uk_api.assert_not_called()
    uk_news.assert_not_called()
    assert meta["filings_regime"] == "sec_edgar"
    assert meta["filings_summary"]["annual"] == 1
    assert meta["filings_summary"]["interim"] == 1
    assert meta["filings_summary"]["with_body"] == 2
    index = json.loads(Path(meta["filings_index_path"]).read_text(encoding="utf-8"))
    assert index["regime"] == "sec_edgar"
    assert index["sources_used"] == ["sec_edgar"]


def test_ingest_filings_asx_regime(tmp_path: Path):
    asx_rows = [
        {
            "id": "asxasxasxasxasxa",
            "source": "google_news_asx",
            "headline": "Example Full Year Results",
            "published_at": "2026-02-05T07:00:00+00:00",
            "url": "https://news.google.com/rss/articles/asx1",
            "period": "annual",
            "category": None,
            "summary": "",
            "has_body": False,
            "body_path": None,
            "priority": 120,
        }
    ]
    with (
        patch("value_investor.research.filings.fetch_filings_asx_news", return_value=asx_rows),
        patch("value_investor.research.filings.fetch_filing_body", return_value=None),
        patch("value_investor.research.filings.fetch_filings_sec_edgar") as sec,
        patch("value_investor.research.filings.fetch_filings_ticker_api") as uk_api,
    ):
        meta = ingest_filings(
            ticker="BHP.AX",
            company_name="BHP Group",
            sources_dir=tmp_path,
            market="asx200",
        )
    sec.assert_not_called()
    uk_api.assert_not_called()
    assert meta["filings_regime"] == "asx_announcements"
    assert meta["filings_summary"]["annual"] == 1
    index = json.loads(Path(meta["filings_index_path"]).read_text(encoding="utf-8"))
    assert index["regime"] == "asx_announcements"


def test_ingest_filings_euro_regime_includes_sec_dual_list(tmp_path: Path):
    euro_rows = [
        {
            "id": "euroeuroeuroeuro",
            "source": "google_news_euro",
            "headline": "SAP Full Year Results",
            "published_at": "2026-01-15T07:00:00+00:00",
            "url": "https://news.google.com/rss/articles/euro1",
            "period": "annual",
            "category": None,
            "summary": "",
            "has_body": False,
            "body_path": None,
            "priority": 120,
        }
    ]
    sec_rows = [
        {
            "id": "sec20f20f20f20f",
            "source": "sec_edgar",
            "headline": "20-F: Annual report",
            "published_at": "2026-02-20T00:00:00+00:00",
            "url": "https://www.sec.gov/Archives/edgar/data/1/0001/sap-20f.htm",
            "period": "annual",
            "category": "20-F",
            "form": "20-F",
            "summary": "",
            "has_body": False,
            "body_path": None,
            "priority": 130,
        }
    ]
    with (
        patch("value_investor.research.filings.fetch_filings_euro_news", return_value=euro_rows),
        patch("value_investor.research.filings.fetch_filings_sec_edgar", return_value=sec_rows) as sec,
        patch("value_investor.research.filings.fetch_filing_body", return_value=None),
        patch("value_investor.research.filings.fetch_filings_ticker_api") as uk_api,
    ):
        meta = ingest_filings(
            ticker="SAP.DE",
            company_name="SAP SE",
            sources_dir=tmp_path,
            market="euro_stoxx50",
        )
    uk_api.assert_not_called()
    sec.assert_called_once_with(ticker="SAP")
    assert meta["filings_regime"] == "euro_filings"
    assert meta["filings_summary"]["annual"] >= 1
    index = json.loads(Path(meta["filings_index_path"]).read_text(encoding="utf-8"))
    assert index["regime"] == "euro_filings"
    assert "google_news_euro" in index["sources_used"]
    assert "sec_edgar" in index["sources_used"]
