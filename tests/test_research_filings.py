"""Tests for primary RNS/results and SEC EDGAR filings ingest (separate from Yahoo)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from value_investor.research.filings import (
    asx_markit_file_url,
    classify_filing_period,
    enrich_filing_rows,
    fetch_filing_body,
    fetch_filings_asx_direct,
    fetch_filings_euro_news,
    fetch_filings_investegate_company,
    filter_misattributed_filings,
    headline_relevant_to_issuer,
    ingest_filings,
    merge_filings,
    prune_orphaned_filing_bodies,
    refetch_missing_filing_bodies,
    resolve_filings_regime,
    resolve_google_news_publisher_url,
    summarize_filings,
    _scrub_misattributed_filing_rows,
    _issuer_matches_sec_name,
    _sec_edgar_supplement_allowed,
    _uk_ticker_sec_dual_listed,
    _extract_investegate_html_text,
    _extract_ixbrl_html_text,
    _filing_text_is_substantive,
)
from value_investor.research.ingest import ingest_research_sources
from value_investor.financials import extract_statement_metrics
import pandas as pd


def test_operating_cashflow_aliases_from_yahoo_labels():
    cashflow = pd.DataFrame(
        {"2024": [90_800_000.0], "2023": [70_000_000.0]},
        index=["Operating Cash Flow"],
    )
    metrics = extract_statement_metrics(None, None, cashflow)
    assert metrics["operating_cashflow"] == 90_800_000.0
    assert metrics["operating_cashflow_prev"] == 70_000_000.0


def test_headline_relevant_to_issuer_filters_noise():
    assert headline_relevant_to_issuer(
        "Morgan Sindall Full Year Results", "Morgan Sindall Group plc", "MGNS.L"
    )
    assert headline_relevant_to_issuer(
        "MGNS Interim Results", "Morgan Sindall Group plc", "MGNS.L"
    )
    assert not headline_relevant_to_issuer(
        "Abri Group / SEGRO trading update", "Morgan Sindall Group plc", "MGNS.L"
    )
    assert not headline_relevant_to_issuer(
        "Form 8.3 - Rotork plc", "Hikma Pharmaceuticals PLC", "HIK.L"
    )
    assert not headline_relevant_to_issuer(
        "Net Asset Value(s)", "AEP Plantations Plc", "AEP.L"
    )


def test_fetch_filings_ticker_api_drops_unrelated_global_feed(monkeypatch):
    payload = {
        "data": [
            {"headline": "Form 8.3 - Rotork plc", "timestamp": "2026-07-22T10:00:00Z"},
            {
                "headline": "Hikma Pharmaceuticals Full Year Results",
                "timestamp": "2026-03-01T07:00:00Z",
                "url": "https://example.com/hikma-fy.html",
            },
        ],
        "warnings": ["The 'symbol' filter is not available on your plan and was ignored."],
    }
    monkeypatch.setattr(
        "value_investor.research.filings._http_get",
        lambda url, headers=None, timeout=60: json.dumps(payload).encode("utf-8"),
    )
    monkeypatch.setenv("TICKER_API_KEY", "test-key")
    from value_investor.research.filings import fetch_filings_ticker_api

    rows = fetch_filings_ticker_api(
        ticker="HIK.L",
        company_name="Hikma Pharmaceuticals PLC",
    )
    assert len(rows) == 1
    assert "Hikma" in rows[0]["headline"]


def test_fetch_filing_body_parses_sec_inline_xbrl(monkeypatch):
    html = """
    <html><body>
    <ix:header><ix:hidden>us-gaap:RevenueMember 2025-01-01 0000863064</ix:hidden></ix:header>
    <ix:hidden>rio:RioTintoLimitedMember iso4217:USD xbrli:shares</ix:hidden>
    <div>Cover page checkbox ITEM 1. Legal Proceedings noise</div>
    <div>CONSOLIDATED INCOME STATEMENT</div>
    <p>Revenue increased to $57.6 billion in 2025 driven by copper and aluminium.</p>
    <p>Underlying EBITDA was $25.4 billion and net debt increased after acquisitions.</p>
    <p>Operating cash flow remained strong while capital expenditure rose on growth projects.</p>
    </body></html>
    """
    monkeypatch.setattr(
        "value_investor.research.filings._http_get",
        lambda url, headers=None, timeout=60: html.encode("utf-8"),
    )
    text = fetch_filing_body("https://www.sec.gov/Archives/edgar/data/863064/x/rio-20251231.htm")
    assert text is not None
    assert "CONSOLIDATED INCOME STATEMENT" in text
    assert "Revenue increased" in text
    assert "us-gaap:RevenueMember" not in text
    assert "RioTintoLimitedMember" not in text


def test_extract_ixbrl_html_text_prefers_statutory_sections():
    html = """
    <html><body>
    <ix:hidden>ifrs-full:RevenueMember 2025-01-01</ix:hidden>
    <div>Cover noise</div>
    <div>STRATEGIC REPORT</div>
    <p>Revenue increased to £1.2 billion and operating profit rose 8%.</p>
    <p>Going concern: the directors have a reasonable expectation the group can meet its liabilities.</p>
    <p>Pension deficit reduced following triennial review and covenant headroom remains adequate.</p>
    </body></html>
    """
    text = _extract_ixbrl_html_text(html)
    assert "STRATEGIC REPORT" in text
    assert "Going concern" in text
    assert "ifrs-full:RevenueMember" not in text
    assert _filing_text_is_substantive(text)


def test_extract_investegate_html_text_keeps_results_narrative():
    html = """
    <html><body>
    <h1>ITV plc Full Year Results 2025</h1>
    <div>Summary by AI BETA Close X Short AI blurb only.</div>
    <p>Total external revenue increased 1% to £3,511 million and adjusted EBITA was £534 million.</p>
    <p>The proposed dividend is 5.0p per share, approximately £190 million in total.</p>
    <div>Related announcements</div>
  </body></html>
    """
    text = _extract_investegate_html_text(html)
    assert "£3,511 million" in text
    assert "dividend" in text.lower()
    assert "Related announcements" not in text


def test_fetch_filings_investegate_company_parses_company_page(monkeypatch):
    html = """
    <table>
      <tr>
        <td>05 Mar 2026</td><td>07:00 AM</td>
        <td><a href="https://www.investegate.co.uk/announcement/rns/itv--itv/itv-plc-full-year-results-2025/9459201">ITV plc Full Year Results 2025</a></td>
      </tr>
    </table>
    """
    monkeypatch.setattr(
        "value_investor.research.filings._http_get",
        lambda url, headers=None, timeout=60: html.encode("utf-8"),
    )
    rows = fetch_filings_investegate_company(ticker="ITV.L", company_name="ITV plc")
    assert len(rows) == 1
    assert rows[0]["source"] == "investegate_direct"
    assert rows[0]["period"] == "annual"
    assert "investegate.co.uk/announcement/" in rows[0]["url"]


def test_enrich_filing_rows_resolves_google_wrapper(monkeypatch):
    google_row = {
        "id": "g1",
        "source": "google_news_investegate",
        "headline": "ITV plc Full Year Results 2025 - Investegate",
        "published_at": "2026-03-05T00:00:00+00:00",
        "url": "https://news.google.com/rss/articles/abc",
        "period": "annual",
        "has_body": False,
        "priority": 100,
    }
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filings_investegate_company",
        lambda **kwargs: [
            {
                "id": "i1",
                "source": "investegate_direct",
                "headline": "ITV plc Full Year Results 2025",
                "published_at": "2026-03-05T00:00:00+00:00",
                "url": "https://www.investegate.co.uk/announcement/rns/itv--itv/itv-plc-full-year-results-2025/9459201",
                "period": "annual",
                "has_body": False,
                "priority": 125,
            }
        ],
    )
    enriched = enrich_filing_rows(
        [google_row],
        ticker="ITV.L",
        company_name="ITV plc",
    )
    assert enriched[0]["source"] == "investegate_resolved"
    assert "investegate.co.uk/announcement/" in enriched[0]["url"]


def test_fetch_filing_body_parses_pdf(monkeypatch):
    monkeypatch.setattr(
        "value_investor.research.filings._http_get",
        lambda url, headers=None, timeout=60: b"%PDF-fake",
    )
    monkeypatch.setattr(
        "value_investor.research.filings._extract_pdf_text",
        lambda raw: "A" * 250 + " Annual Report cash flow bridge",
    )
    text = fetch_filing_body("https://example.com/results.pdf")
    assert text is not None
    assert "cash flow bridge" in text


def test_refetch_missing_filing_bodies(tmp_path, monkeypatch):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    index = {
        "filings": [
            {
                "id": "t1",
                "source": "ticker_rns_api",
                "headline": "Full Year Results",
                "published_at": "2026-07-01T07:00:00+00:00",
                "url": "https://www.investegate.co.uk/announcement/rns/example/fy/1",
                "period": "annual",
                "has_body": False,
                "body_path": None,
                "priority": 100,
            }
        ]
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda url: "Body text " + ("x" * 220),
    )
    result = refetch_missing_filing_bodies(filings_dir, max_bodies=4)
    assert result["fetched"] == 1
    assert result["with_body_after"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert saved["filings"][0]["has_body"] is True


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
    assert resolve_filings_regime("dax", "ADS.DE") == "euro_filings"
    assert resolve_filings_regime("cac40", "AIR.PA") == "euro_filings"
    assert resolve_filings_regime(None, "SAP.DE") == "euro_filings"
    assert resolve_filings_regime("nasdaq100", "AAPL") == "sec_edgar"
    assert resolve_filings_regime("ftse_smallcap", "ASIT.L") == "uk_rns"
    assert resolve_filings_regime("tsx60", "AEM.TO") == "tsx_announcements"
    assert resolve_filings_regime("aim", "ABDP.L") == "uk_rns"
    assert resolve_filings_regime("ibex35", "ACS.MC") == "euro_filings"
    assert resolve_filings_regime("hang_seng", "0005.HK") == "asia_filings"
    assert resolve_filings_regime("sti", "D05.SI") == "asia_filings"
    assert resolve_filings_regime("us_adr_asia", "BABA") == "sec_edgar"
    assert resolve_filings_regime(None, "AEM.TO") == "tsx_announcements"


def test_resolve_google_news_publisher_url_passthrough():
    assert resolve_google_news_publisher_url("https://sec.gov/foo") == "https://sec.gov/foo"
    assert resolve_google_news_publisher_url(None) is None


@patch("value_investor.research.filings.fetch_filings_google_news")
def test_fetch_filings_euro_news_uses_market_locale(mock_fetch):
    mock_fetch.return_value = []
    fetch_filings_euro_news(company_name="SAP SE", ticker="SAP.DE", market="dax")
    kwargs = mock_fetch.call_args.kwargs
    assert kwargs["hl"] == "de"
    assert kwargs["gl"] == "DE"
    assert "dgap.de" in kwargs["query"] or "eqs.com" in kwargs["query"]


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
        patch(
            "value_investor.research.companies_house.fetch_filings_companies_house",
            return_value=[],
        ),
        patch("value_investor.research.filings.fetch_filings_ir_allowlist", return_value=[]),
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
        patch(
            "value_investor.research.companies_house.fetch_filings_companies_house",
            return_value=[],
        ),
        patch("value_investor.research.filings.fetch_filings_ir_allowlist", return_value=[]),
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
        patch(
            "value_investor.research.companies_house.fetch_filings_companies_house",
            return_value=[],
        ),
        patch("value_investor.research.filings.fetch_filings_ir_allowlist", return_value=[]),
        patch("value_investor.research.filings.fetch_filing_body", return_value=body_text),
        patch("value_investor.research.filings.resolve_sec_cik", return_value=None),
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
        patch("value_investor.research.filings.fetch_filings_asx_direct", return_value=[]),
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
            "headline": "20-F: SAP SE Annual report",
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
        patch(
            "value_investor.research.filings._sec_edgar_supplement_allowed",
            return_value=True,
        ),
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
    sec.assert_called_once_with(ticker="SAP", include_current_reports=False)
    assert meta["filings_regime"] == "euro_filings"
    assert meta["filings_summary"]["annual"] >= 1
    index = json.loads(Path(meta["filings_index_path"]).read_text(encoding="utf-8"))
    assert index["regime"] == "euro_filings"
    assert "google_news_euro" in index["sources_used"]
    assert "sec_edgar" in index["sources_used"]


def test_ingest_filings_uk_rns_includes_sec_when_dual_listed(tmp_path: Path):
    uk_rows = [
        {
            "id": "ukukukukukukukuk",
            "source": "ticker_rns_api",
            "headline": "Rio Tinto Full Year Results",
            "published_at": "2026-02-20T07:00:00+00:00",
            "url": "https://www.investegate.co.uk/announcement/rns/rio/fy/1",
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
            "url": "https://www.sec.gov/Archives/edgar/data/863064/0001/rio-20251231.htm",
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
        patch("value_investor.research.filings.fetch_filings_ticker_api", return_value=uk_rows),
        patch("value_investor.research.filings.fetch_filings_google_news", return_value=[]),
        patch(
            "value_investor.research.companies_house.fetch_filings_companies_house",
            return_value=[],
        ),
        patch("value_investor.research.filings._uk_ticker_sec_dual_listed", return_value=True),
        patch(
            "value_investor.research.filings.fetch_filings_sec_edgar",
            return_value=sec_rows,
        ) as sec,
        patch("value_investor.research.filings.fetch_filings_ir_allowlist", return_value=[]),
        patch("value_investor.research.filings.fetch_filing_body", return_value=None),
    ):
        meta = ingest_filings(
            ticker="RIO.L",
            company_name="Rio Tinto plc",
            sources_dir=tmp_path,
            market="ftse350",
        )

    sec.assert_called_once_with(ticker="RIO", include_current_reports=False)
    assert meta["filings_regime"] == "uk_rns"
    index = json.loads(Path(meta["filings_index_path"]).read_text(encoding="utf-8"))
    assert "sec_edgar" in index["sources_used"]
    assert "SEC 20-F when dual-listed" in index["note"]


def test_issuer_matches_sec_name_rejects_us_homonyms():
    from value_investor.research.filings import _issuer_matches_sec_name

    assert _issuer_matches_sec_name(
        "Costain Group PLC",
        "COSTCO WHOLESALE CORP /NEW",
        "COST.L",
    ) is False
    assert _issuer_matches_sec_name(
        "Shell plc",
        "Shell plc",
        "SHEL.L",
    ) is True
    assert _issuer_matches_sec_name(
        "Rio Tinto Group",
        "RIO TINTO PLC",
        "RIO.L",
    ) is True


def test_uk_ticker_sec_dual_listed_rejects_costain_costco_collision(monkeypatch):
    monkeypatch.setattr(
        "value_investor.research.filings.resolve_sec_cik",
        lambda ticker: 909832 if ticker == "COST" else None,
    )
    monkeypatch.setattr(
        "value_investor.research.filings._sec_submissions_entity_name",
        lambda cik: "COSTCO WHOLESALE CORP /NEW",
    )
    assert _uk_ticker_sec_dual_listed("COST.L", "Costain Group PLC") is False


def test_sec_edgar_supplement_rejects_vinci_dg_collision(monkeypatch):
    monkeypatch.setattr(
        "value_investor.research.filings.resolve_sec_cik",
        lambda ticker: 29534 if ticker == "DG" else None,
    )
    monkeypatch.setattr(
        "value_investor.research.filings._sec_submissions_entity_name",
        lambda cik: "DOLLAR GENERAL CORP",
    )
    assert _sec_edgar_supplement_allowed("DG.PA", "Vinci SA") is False


def test_filter_misattributed_filings_drops_us_homonym_sec_rows():
    rows = [
        {
            "id": "bad",
            "source": "sec_edgar",
            "headline": "Dollar General Corp 10-K Annual Report",
            "form": "10-K",
        },
        {
            "id": "good",
            "source": "google_news_euro",
            "headline": "Vinci SA Full Year Results",
        },
    ]
    filtered = filter_misattributed_filings(
        rows,
        company_name="Vinci SA",
        ticker="DG.PA",
        regime="euro_filings",
    )
    assert [row["id"] for row in filtered] == ["good"]


def test_asx_markit_file_url():
    key = "2924-03107929-2A1682457"
    assert asx_markit_file_url(key).endswith(f"/file/{key}")


@patch("value_investor.research.filings._http_get")
def test_fetch_filings_asx_direct_parses_markit_json(mock_get):
    payload = {
        "data": {
            "items": [
                {
                    "announcementType": "PERIODIC REPORTS",
                    "date": "2026-02-26T08:00:00.000Z",
                    "documentKey": "2924-03107929-2A1682457",
                    "headline": "Worley Half Year 2026 Results",
                    "isPriceSensitive": True,
                },
                {
                    "announcementType": "ISSUED CAPITAL",
                    "date": "2026-07-01T05:45:06.000Z",
                    "documentKey": "2924-03106455-2A1681295",
                    "headline": "Notification of cessation of securities - WOR",
                },
            ]
        }
    }
    mock_get.return_value = json.dumps(payload).encode("utf-8")
    rows = fetch_filings_asx_direct(company_name="Worley Limited", ticker="WOR.AX")
    assert len(rows) == 1
    assert rows[0]["source"] == "asx_direct"
    assert rows[0]["period"] == "interim"
    assert rows[0]["url"] == asx_markit_file_url("2924-03107929-2A1682457")


def test_prune_orphaned_filing_bodies(tmp_path: Path):
    filings_dir = tmp_path / "filings"
    bodies_dir = filings_dir / "bodies"
    bodies_dir.mkdir(parents=True)
    (bodies_dir / "keepme.txt").write_text("Vinci SA annual results", encoding="utf-8")
    (bodies_dir / "orphan.txt").write_text("Dollar General", encoding="utf-8")
    index = {
        "filings": [
            {
                "id": "keepme",
                "has_body": True,
                "body_path": str(bodies_dir / "keepme.txt"),
            }
        ]
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    result = prune_orphaned_filing_bodies(filings_dir)
    assert result["removed"] == 1
    assert (bodies_dir / "keepme.txt").exists()
    assert not (bodies_dir / "orphan.txt").exists()


def test_scrub_misattributed_filing_rows(tmp_path: Path):
    bodies_dir = tmp_path / "bodies"
    bodies_dir.mkdir()
    bad_path = bodies_dir / "badid.txt"
    bad_path.write_text("Dollar General Corporation 10-Q", encoding="utf-8")
    rows = [
        {
            "id": "badid",
            "has_body": True,
            "body_path": str(bad_path),
            "headline": "10-Q",
        }
    ]
    cleaned = _scrub_misattributed_filing_rows(
        rows,
        bodies_dir,
        company_name="Vinci SA",
        ticker="DG.PA",
    )
    assert cleaned[0]["has_body"] is False
    assert not bad_path.exists()


def test_filter_misattributed_keeps_sec_when_supplement_validated():
    rows = [
        {
            "id": "sec1",
            "source": "sec_edgar",
            "form": "20-F",
            "headline": "20-F: FORM 20-F",
        }
    ]
    with patch(
        "value_investor.research.filings._sec_edgar_supplement_allowed",
        return_value=True,
    ):
        kept = filter_misattributed_filings(
            rows,
            company_name="SAP SE",
            ticker="SAP.DE",
            regime="euro_filings",
        )
    assert len(kept) == 1


def test_issuer_matches_sec_name_exact():
    assert _issuer_matches_sec_name("SAP SE", "SAP SE", "SAP.DE") is True


@patch("value_investor.research.filings.fetch_filings_ir_allowlist", return_value=[])
@patch("value_investor.research.filings._write_bodies")
@patch("value_investor.research.filings.enrich_filing_rows")
@patch("value_investor.research.filings.fetch_filings_investegate_company")
@patch("value_investor.research.filings.fetch_filings_euro_news")
def test_ingest_filings_euro_includes_investegate(
    mock_euro_news,
    mock_investegate,
    mock_enrich,
    mock_write_bodies,
    _mock_ir,
    tmp_path: Path,
):
    mock_euro_news.return_value = [{"id": "gn1", "source": "google_news_euro", "headline": "Results"}]
    mock_investegate.return_value = [{"id": "ig1", "source": "investegate_direct", "headline": "Annual"}]
    mock_enrich.side_effect = lambda rows, **_: rows
    mock_write_bodies.side_effect = lambda rows, *_a, **_k: rows

    ingest_filings(
        ticker="TTE.PA",
        company_name="TotalEnergies SE",
        sources_dir=tmp_path,
        market="euro_stoxx50",
    )
    mock_investegate.assert_called_once()
    mock_enrich.assert_called_once()
