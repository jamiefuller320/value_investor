"""Tests for primary RNS/results and SEC EDGAR filings ingest (separate from Yahoo)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from value_investor.research.filings import (
    asx_markit_file_url,
    classify_companies_house_period,
    classify_filing_entity_type,
    classify_filing_period,
    classify_rns_headline,
    enrich_filing_rows,
    fetch_filing_body,
    fetch_filings_asx_direct,
    fetch_filings_euro_news,
    fetch_filings_investegate_company,
    fetch_filings_ir_allowlist,
    filter_misattributed_filings,
    headline_relevant_to_issuer,
    ingest_filings,
    load_ir_url_allowlist,
    merge_filings,
    merge_ir_allowlist_filings,
    period_body_coverage,
    prune_orphaned_filing_bodies,
    refetch_companies_house_filing_bodies,
    refetch_indexed_without_body_filing_bodies,
    refetch_investegate_filing_bodies,
    refetch_ir_allowlist_filing_bodies,
    refetch_missing_filing_bodies,
    refetch_ticker_rns_api_filing_bodies,
    resolve_filings_regime,
    resolve_google_news_publisher_url,
    resolve_investegate_document_url,
    resolve_investegate_lse_pdf_url,
    summarize_filings,
    _scrub_misattributed_filing_rows,
    _issuer_matches_sec_name,
    _sec_edgar_supplement_allowed,
    _uk_ticker_sec_dual_listed,
    _extract_investegate_html_text,
    _extract_ixbrl_html_text,
    _compose_pdf_body_text,
    _extract_pdf_depth_sections,
    _filing_text_is_substantive,
)
from value_investor.research.ingest import (
    apply_cashflow_metrics_fallback,
    extract_cashflow_metrics_from_annual_financials,
    fetch_annual_financials,
    ingest_research_sources,
    install_fetch_cashflow_fallback,
    supplement_company_metrics_cashflow,
)
from value_investor.financials import extract_statement_metrics
from value_investor.fetch import CompanyMetrics
import pandas as pd


def test_operating_cashflow_aliases_from_yahoo_labels():
    cashflow = pd.DataFrame(
        {"2024": [90_800_000.0], "2023": [70_000_000.0]},
        index=["Operating Cash Flow"],
    )
    metrics = extract_statement_metrics(None, None, cashflow)
    assert metrics["operating_cashflow"] == 90_800_000.0
    assert metrics["operating_cashflow_prev"] == 70_000_000.0


def test_extract_cashflow_metrics_from_financials_annual_json():
    financials = {
        "ticker": "MEGP.L",
        "cash_flow": {
            "2024": {
                "Operating Cash Flow": 90_800_000.0,
                "Free Cash Flow": 55_000_000.0,
            },
            "2023": {
                "Operating Cash Flow": 70_000_000.0,
                "Free Cash Flow": 40_000_000.0,
            },
        },
    }
    metrics = extract_cashflow_metrics_from_annual_financials(financials)
    assert metrics["operating_cashflow"] == 90_800_000.0
    assert metrics["free_cashflow"] == 55_000_000.0
    assert metrics["operating_cashflow_prev"] == 70_000_000.0


def test_apply_cashflow_metrics_fallback_leaves_existing_values():
    payload = {"operating_cashflow": 1.0, "free_cashflow": None}
    financials = {
        "cash_flow": {
            "2024": {"Operating Cash Flow": 90_800_000.0, "Free Cash Flow": 55_000_000.0},
        }
    }
    filled = apply_cashflow_metrics_fallback(payload, financials)
    assert filled == ["free_cashflow"]
    assert payload["operating_cashflow"] == 1.0
    assert payload["free_cashflow"] == 55_000_000.0


def test_supplement_company_metrics_cashflow_megp_uses_cached_financials(tmp_path: Path):
    sources = tmp_path / "research" / "MEGP.L" / "sources"
    sources.mkdir(parents=True)
    financials = {
        "ticker": "MEGP.L",
        "cash_flow": {"2024": {"Operating Cash Flow": 90_800_000.0, "Free Cash Flow": 55_000_000.0}},
    }
    (sources / "financials_annual.json").write_text(json.dumps(financials), encoding="utf-8")

    metrics = CompanyMetrics(ticker="MEGP.L")
    filled = supplement_company_metrics_cashflow(
        metrics,
        sources_dir=sources,
    )
    assert filled == ["operating_cashflow", "free_cashflow"]
    assert metrics.operating_cashflow == 90_800_000.0
    assert metrics.free_cashflow == 55_000_000.0
    assert metrics.data_sources["operating_cashflow"] == "yahoo_financials_annual"


def test_install_fetch_cashflow_fallback_patches_fetch(monkeypatch):
    from value_investor import fetch as fetch_mod

    metrics = CompanyMetrics(ticker="MEGP.L", operating_cashflow=None, free_cashflow=None)

    def fake_fetch(*_args, **_kwargs):
        return metrics

    monkeypatch.setattr(fetch_mod, "fetch_company_metrics", fake_fetch)
    fetch_mod.fetch_company_metrics._cashflow_fallback_installed = False  # type: ignore[attr-defined]

    calls: list[str] = []

    def fake_supplement(m, **_kw):
        calls.append(m.ticker)
        m.operating_cashflow = 90_800_000.0
        return ["operating_cashflow"]

    monkeypatch.setattr(
        "value_investor.research.ingest.supplement_company_metrics_cashflow",
        fake_supplement,
    )

    install_fetch_cashflow_fallback()
    result = fetch_mod.fetch_company_metrics("MEGP.L")
    assert result.operating_cashflow == 90_800_000.0
    assert calls == ["MEGP.L"]


def test_fetch_cashflow_fallback_does_not_double_fetch_yfinance(monkeypatch):
    """Regression: patched fetch must not re-open yfinance when OCF is missing."""
    from types import SimpleNamespace

    from value_investor import fetch as fetch_mod

    seen: list[str] = []

    class DummyTicker:
        def __init__(self, symbol: str):
            seen.append(symbol)

        @property
        def info(self):
            return {"longName": "ME Group International plc", "marketCap": 2_000_000}

        @property
        def fast_info(self):
            return SimpleNamespace(market_cap=2_000_000)

        @property
        def balance_sheet(self):
            return None

        @property
        def income_stmt(self):
            return None

        @property
        def cashflow(self):
            return None

        financials = pd.DataFrame()
        quarterly_financials = None

    fetch_mod.fetch_company_metrics._cashflow_fallback_installed = False  # type: ignore[attr-defined]
    install_fetch_cashflow_fallback()

    with patch.object(fetch_mod.yf, "Ticker", side_effect=DummyTicker):
        fetch_mod.fetch_company_metrics("MEGP.L")

    assert seen == ["MEGP.L"]


def test_fetch_annual_financials_includes_cashflow_metrics(monkeypatch):
    cashflow_df = pd.DataFrame(
        {"2024": [90_800_000.0, 55_000_000.0]},
        index=["Operating Cash Flow", "Free Cash Flow"],
    )

    class DummyTicker:
        financials = pd.DataFrame()
        balance_sheet = pd.DataFrame()
        cashflow = cashflow_df
        quarterly_financials = None

    monkeypatch.setattr("value_investor.research.ingest.yf.Ticker", lambda _t: DummyTicker())
    payload = fetch_annual_financials("MEGP.L")
    assert payload["cashflow_metrics"]["operating_cashflow"] == 90_800_000.0
    assert payload["cashflow_metrics"]["free_cashflow"] == 55_000_000.0


def test_headline_relevant_to_issuer_filters_noise():
    assert headline_relevant_to_issuer(
        "Morgan Sindall Full Year Results", "Morgan Sindall Group plc", "MGNS.L"
    )
    assert headline_relevant_to_issuer(
        "MGNS Interim Results", "Morgan Sindall Group plc", "MGNS.L"
    )
    assert headline_relevant_to_issuer(
        "ME Group Full Year Results", "ME Group International plc", "MEGP.L"
    )
    assert headline_relevant_to_issuer(
        "MEGP Interim Results", "ME Group International plc", "MEGP.L"
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
    assert not headline_relevant_to_issuer(
        "Development Partnership for 294-unit hotel - Investegate",
        "ME Group International plc",
        "MEGP.L",
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
    assert enriched[0]["period"] == "annual"


def test_enrich_filing_rows_reclassifies_trading_update(monkeypatch):
    google_row = {
        "id": "g2",
        "source": "google_news_investegate",
        "headline": "ITV plc Q1 Trading Update - Investegate",
        "published_at": "2026-05-14T00:00:00+00:00",
        "url": "https://news.google.com/rss/articles/q1",
        "period": "other",
        "has_body": False,
        "priority": 50,
    }
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filings_investegate_company",
        lambda **kwargs: [
            {
                "id": "i2",
                "source": "investegate_direct",
                "headline": "ITV plc Q1 Trading Update",
                "published_at": "2026-05-14T00:00:00+00:00",
                "url": "https://www.investegate.co.uk/announcement/rns/itv--itv/q1-trading/1",
                "period": "interim",
                "has_body": False,
                "priority": 90,
            }
        ],
    )
    enriched = enrich_filing_rows(
        [google_row],
        ticker="ITV.L",
        company_name="ITV plc",
    )
    assert enriched[0]["period"] == "trading_update"
    assert enriched[0]["priority"] >= 60


def test_resolve_investegate_document_url_finds_lse_pdf():
    html = """
    <p>Click on or paste the following link into your web browser to view the associated PDF document.
    <a href="http://www.rns-pdf.londonstockexchange.com/rns/3965V_1-2026-3-4.pdf">PDF</a></p>
    """
    assert resolve_investegate_document_url(html) == (
        "http://www.rns-pdf.londonstockexchange.com/rns/3965V_1-2026-3-4.pdf"
    )


def test_resolve_investegate_lse_pdf_url_upgrades_investegate_page(monkeypatch):
    investegate_url = (
        "https://www.investegate.co.uk/announcement/rns/itv--itv/itv-plc-full-year-results-2025/9459201"
    )
    lse_pdf = "http://www.rns-pdf.londonstockexchange.com/rns/3965V_1-2026-3-4.pdf"
    html = f'<a href="{lse_pdf}">PDF</a>'
    monkeypatch.setattr(
        "value_investor.research.filings._http_get",
        lambda url, headers=None, timeout=60: html.encode("utf-8"),
    )
    assert resolve_investegate_lse_pdf_url(investegate_url) == lse_pdf
    assert resolve_investegate_lse_pdf_url(lse_pdf) == lse_pdf


def test_fetch_filing_body_investegate_follows_lse_pdf(monkeypatch):
    investegate_url = (
        "https://www.investegate.co.uk/announcement/rns/itv--itv/itv-plc-full-year-results-2025/9459201"
    )
    lse_pdf = "http://www.rns-pdf.londonstockexchange.com/rns/3965V_1-2026-3-4.pdf"
    investegate_html = f"""
    <h1>ITV plc Full Year Results 2025</h1>
    <p>Short blurb only.</p>
    <a href="{lse_pdf}">PDF</a>
    """
    pdf_text = "A" * 250 + " revenue increased and operating profit rose sharply."

    def fake_get(url, headers=None, timeout=60):
        if url == investegate_url:
            return investegate_html.encode("utf-8")
        if url == lse_pdf:
            return b"%PDF-fake"
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("value_investor.research.filings._http_get", fake_get)
    monkeypatch.setattr(
        "value_investor.research.filings._extract_filing_document_text",
        lambda raw, content_type: pdf_text,
    )
    text = fetch_filing_body(investegate_url)
    assert text is not None
    assert "revenue increased" in text


def test_refetch_investegate_filing_bodies_resolves_and_downloads(tmp_path, monkeypatch):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    index = {
        "ticker": "ITV.L",
        "company_name": "ITV plc",
        "filings": [
            {
                "id": "gnews1",
                "source": "google_news_investegate",
                "headline": "ITV plc Full Year Results 2025 - Investegate",
                "published_at": "2026-03-05T00:00:00+00:00",
                "url": "https://news.google.com/rss/articles/abc",
                "period": "other",
                "has_body": False,
                "body_path": None,
                "priority": 50,
            }
        ],
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")

    def fake_enrich(rows, *, ticker, company_name):
        return [
            {
                **rows[0],
                "url": "https://www.investegate.co.uk/announcement/rns/itv--itv/fy/1",
                "source": "investegate_resolved",
                "period": "annual",
            }
        ]

    monkeypatch.setattr(
        "value_investor.research.filings.enrich_filing_rows",
        fake_enrich,
    )
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda url: "Annual results narrative " + ("x" * 220),
    )
    result = refetch_investegate_filing_bodies(
        filings_dir,
        ticker="ITV.L",
        company_name="ITV plc",
        max_bodies=5,
    )
    assert result["attempted"] == 1
    assert result["fetched"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert saved["filings"][0]["has_body"] is True
    assert saved["filings"][0]["period"] == "annual"
    assert (filings_dir / "bodies" / "gnews1.txt").exists()


def test_fetch_filing_body_rejects_unresolved_google_news_url(monkeypatch):
    monkeypatch.setattr(
        "value_investor.research.filings.resolve_google_news_publisher_url",
        lambda url: None,
    )
    assert (
        fetch_filing_body(
            "https://news.google.com/rss/articles/CBMiabc?oc=5"
        )
        is None
    )


def test_refetch_investegate_rejects_unresolved_google_news_wrapper(
    tmp_path, monkeypatch
):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    index = {
        "ticker": "RIO.L",
        "company_name": "Rio Tinto Group",
        "filings": [
            {
                "id": "gnews_stuck",
                "source": "google_news_investegate",
                "headline": "Rio Tinto trading update - Investegate",
                "published_at": "2026-03-05T00:00:00+00:00",
                "url": "https://news.google.com/rss/articles/stuck?oc=5",
                "period": "trading_update",
                "has_body": False,
                "body_path": None,
                "priority": 90,
            }
        ],
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.research.filings.enrich_filing_rows",
        lambda rows, *, ticker, company_name: list(rows),
    )
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda url: (_ for _ in ()).throw(AssertionError("should not fetch")),
    )
    result = refetch_investegate_filing_bodies(
        filings_dir,
        ticker="RIO.L",
        company_name="Rio Tinto Group",
        max_bodies=5,
    )
    assert result["attempted"] == 0
    assert result["fetched"] == 0
    assert result["google_news_rejected"] == 1


def test_refetch_investegate_fetches_direct_lse_pdf_url(tmp_path, monkeypatch):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    lse_pdf = "http://www.rns-pdf.londonstockexchange.com/rns/3965V_1-2026-3-4.pdf"
    index = {
        "ticker": "SHEL.L",
        "company_name": "Shell plc",
        "filings": [
            {
                "id": "lse_pdf1",
                "source": "investegate_resolved",
                "headline": "Shell plc Full Year Results",
                "published_at": "2026-02-05T00:00:00+00:00",
                "url": lse_pdf,
                "period": "annual",
                "has_body": False,
                "body_path": None,
                "priority": 100,
            }
        ],
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.research.filings.enrich_filing_rows",
        lambda rows, *, ticker, company_name: list(rows),
    )
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda url: "Annual results narrative " + ("x" * 220),
    )
    result = refetch_investegate_filing_bodies(
        filings_dir,
        ticker="SHEL.L",
        company_name="Shell plc",
        max_bodies=5,
    )
    assert result["attempted"] == 1
    assert result["fetched"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert saved["filings"][0]["has_body"] is True
    assert (filings_dir / "bodies" / "lse_pdf1.txt").exists()


def test_refetch_indexed_without_body_filing_bodies_orchestrates(
    tmp_path, monkeypatch
):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    (filings_dir / "filings_index.json").write_text(
        json.dumps({"filings": [], "summary": {"with_body": 0}}),
        encoding="utf-8",
    )
    investegate_result = {
        "attempted": 2,
        "fetched": 1,
        "with_body_before": 10,
        "with_body_after": 11,
        "google_news_rejected": 1,
    }
    ticker_rns_result = {
        "attempted": 1,
        "fetched": 1,
        "with_body_before": 11,
        "with_body_after": 12,
        "pruned": 0,
    }
    monkeypatch.setattr(
        "value_investor.research.filings.refetch_investegate_filing_bodies",
        lambda *args, **kwargs: dict(investegate_result),
    )
    monkeypatch.setattr(
        "value_investor.research.filings.refetch_ticker_rns_api_filing_bodies",
        lambda *args, **kwargs: dict(ticker_rns_result),
    )
    result = refetch_indexed_without_body_filing_bodies(
        filings_dir,
        ticker="GSK.L",
        company_name="GSK plc",
        max_bodies=20,
    )
    assert result["fetched"] == 2
    assert result["attempted"] == 3
    assert result["with_body_before"] == 10
    assert result["with_body_after"] == 12
    assert result["google_news_rejected"] == 1


def test_resolve_investegate_url_decodes_google_news_to_investegate(monkeypatch):
    from value_investor.research.filings import resolve_investegate_url

    decoded = "https://www.investegate.co.uk/announcement/rns/itv--itv/fy/1"
    monkeypatch.setattr(
        "value_investor.research.filings.resolve_google_news_publisher_url",
        lambda url: decoded,
    )
    row = {
        "url": "https://news.google.com/rss/articles/CBMiabc?oc=5",
        "headline": "ITV plc Full Year Results 2025",
    }
    assert (
        resolve_investegate_url(row, ticker="ITV.L", company_name="ITV plc")
        == decoded
    )


def test_fetch_filing_body_parses_pdf(monkeypatch):
    monkeypatch.setattr(
        "value_investor.research.filings._http_get",
        lambda url, headers=None, timeout=60: b"%PDF-fake",
    )
    monkeypatch.setattr(
        "value_investor.research.filings._extract_filing_document_text",
        lambda raw, content_type: "A" * 250 + " Annual Report cash flow bridge",
    )
    text = fetch_filing_body("https://example.com/results.pdf")
    assert text is not None
    assert "cash flow bridge" in text


def test_compose_pdf_body_text_splices_late_cash_flow_and_notes():
    """Regression: depth extract must reach consolidated cash-flow and note sections."""
    early = "Chief Executive Review and strategic outlook " * 900
    cash_flow_page = (
        "CONSOLIDATED STATEMENT OF CASH FLOW\n"
        "Cash generated from operations 90.8\n"
        "Purchase of property, plant and equipment (65.6)\n"
        "Free cash flow before dividends 25.2"
    )
    exceptional_page = (
        "NOTE 5 Exceptional items\n"
        "Restructuring costs 45\n"
        "Legal settlement 72\n"
        "Total exceptional charge 117"
    )
    segment_page = (
        "SEGMENT INFORMATION\n"
        "UK revenue 800\n"
        "US revenue 400\n"
        "RELATED PARTY TRANSACTIONS\n"
        "Sales to associate 12\n"
        "Purchases from joint venture 3"
    )
    pages = [early[:3500]] * 10 + [cash_flow_page, exceptional_page, segment_page]

    text = _compose_pdf_body_text(pages)
    assert text is not None
    assert "Chief Executive Review" in text
    assert "CONSOLIDATED STATEMENT OF CASH FLOW" in text
    assert "Cash generated from operations 90.8" in text
    assert "NOTE 5 Exceptional items" in text
    assert "Legal settlement 72" in text
    assert "SEGMENT INFORMATION" in text
    assert "RELATED PARTY TRANSACTIONS" in text
    assert "Sales to associate 12" in text


def test_extract_pdf_depth_sections_skips_lead_window():
    lead = "Strategic report narrative " * 1200
    tail = (
        "CONSOLIDATED CASH FLOW STATEMENT operating activities 123 "
        "EXCEPTIONAL ITEMS restructuring 45 "
        "SEGMENT INFORMATION UK revenue 800"
    )
    full = lead + tail
    lead_limit = min(28_000, len(full))
    sections = _extract_pdf_depth_sections(full, skip_before=lead_limit)
    joined = "\n".join(sections)
    assert "CONSOLIDATED CASH FLOW STATEMENT" in joined
    assert "EXCEPTIONAL ITEMS" in joined
    assert "SEGMENT INFORMATION" in joined
    assert lead[:500] not in joined


def test_fetch_filing_body_routes_companies_house_document_api(monkeypatch):
    monkeypatch.setattr(
        "value_investor.research.filings._fetch_companies_house_body",
        lambda row: "A" * 220 + " pension covenant going concern",
    )
    url = "https://document-api.company-information.service.gov.uk/document/abc123"
    text = fetch_filing_body(url)
    assert text is not None
    assert "pension covenant" in text


def test_refetch_companies_house_filing_bodies_pdf_extract(tmp_path, monkeypatch):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    ch_url = "https://document-api.company-information.service.gov.uk/document/ch1"
    index = {
        "filings": [
            {
                "id": "ch_row_1",
                "source": "companies_house",
                "headline": "Companies House accounts — full",
                "url": ch_url,
                "document_metadata_url": ch_url,
                "period": "annual",
                "has_body": False,
                "body_path": None,
                "priority": 140,
            },
            {
                "id": "rns_row_1",
                "source": "investegate_direct",
                "headline": "Trading update",
                "url": "https://www.investegate.co.uk/announcement/rns/x/trading/1",
                "period": "other",
                "has_body": False,
                "body_path": None,
                "priority": 90,
            },
        ]
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    body_text = "A" * 220 + " statutory accounts pension going concern covenant"
    monkeypatch.setattr(
        "value_investor.research.filings._fetch_companies_house_body",
        lambda row: body_text,
    )
    result = refetch_companies_house_filing_bodies(filings_dir, max_bodies=5)
    assert result["attempted"] == 1
    assert result["fetched"] == 1
    assert result["with_body_after"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert saved["filings"][0]["has_body"] is True
    assert (filings_dir / "bodies" / "ch_row_1.txt").exists()
    assert saved["filings"][1]["has_body"] is False


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


def test_refetch_ticker_rns_api_filing_bodies_megp_prunes_and_downloads(tmp_path, monkeypatch):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    pdf_url = "https://newswire.tickerapp.net/rns/2026-03-05/1234M/example.content.pdf"
    index = {
        "ticker": "MEGP.L",
        "company_name": "ME Group International plc",
        "filings": [
            {
                "id": "noise1",
                "source": "google_news_investegate",
                "headline": "Form 8.3 - Rotork plc - Investegate",
                "url": "https://news.google.com/rss/articles/noise",
                "period": "other",
                "has_body": False,
                "body_path": None,
                "priority": 0,
            },
            {
                "id": "megp1",
                "source": "ticker_rns_api",
                "headline": "ME Group Full Year Results",
                "published_at": "2026-03-05T00:00:00+00:00",
                "url": pdf_url,
                "period": "annual",
                "has_body": False,
                "body_path": None,
                "priority": 120,
            },
        ],
        "summary": {"total": 2, "with_body": 0},
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda url: (
            "ME Group International plc full year results "
            + ("revenue increased " * 30)
            if url == pdf_url
            else None
        ),
    )
    result = refetch_ticker_rns_api_filing_bodies(
        filings_dir,
        ticker="MEGP.L",
        company_name="ME Group International plc",
        max_bodies=5,
    )
    assert result["pruned"] == 1
    assert result["attempted"] == 1
    assert result["fetched"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert len(saved["filings"]) == 1
    assert saved["filings"][0]["id"] == "megp1"
    assert saved["filings"][0]["has_body"] is True
    assert (filings_dir / "bodies" / "megp1.txt").exists()


def test_fetch_filings_ticker_api_classifies_trading_update(monkeypatch):
    payload = {
        "data": [
            {
                "headline": "ME Group Q1 Trading Update",
                "symbol": "MEGP",
                "timestamp": "2026-05-14T07:00:00Z",
                "url": "https://newswire.tickerapp.net/rns/2026-05-14/1M/trading.pdf",
            },
        ],
    }
    monkeypatch.setattr(
        "value_investor.research.filings._http_get",
        lambda url, headers=None, timeout=60: json.dumps(payload).encode("utf-8"),
    )
    monkeypatch.setenv("TICKER_API_KEY", "test-key")
    from value_investor.research.filings import fetch_filings_ticker_api

    rows = fetch_filings_ticker_api(
        ticker="MEGP.L",
        company_name="ME Group International plc",
    )
    assert len(rows) == 1
    assert rows[0]["period"] == "trading_update"
    assert rows[0]["priority"] >= 60


def test_fetch_filings_ticker_api_prefers_pdf_publication(monkeypatch):
    payload = {
        "data": [
            {
                "headline": "ME Group Full Year Results",
                "symbol": "MEGP",
                "timestamp": "2026-03-01T07:00:00Z",
                "publications": [
                    {
                        "type": "html",
                        "url": "https://example.com/rns/html",
                    },
                    {
                        "type": "pdf",
                        "url": "https://newswire.tickerapp.net/rns/2026-03-01/1M/a.content.pdf",
                    },
                ],
            },
            {
                "headline": "Form 8.3 - Rotork plc",
                "symbol": "ROR",
                "timestamp": "2026-07-22T10:00:00Z",
                "url": "https://newswire.tickerapp.net/rns/2026-07-22/2M/b.content.pdf",
            },
        ],
    }
    monkeypatch.setattr(
        "value_investor.research.filings._http_get",
        lambda url, headers=None, timeout=60: json.dumps(payload).encode("utf-8"),
    )
    monkeypatch.setenv("TICKER_API_KEY", "test-key")
    from value_investor.research.filings import fetch_filings_ticker_api

    rows = fetch_filings_ticker_api(
        ticker="MEGP.L",
        company_name="ME Group International plc",
    )
    assert len(rows) == 1
    assert rows[0]["url"].endswith(".content.pdf")
    assert "ME Group" in rows[0]["headline"]


def test_classify_companies_house_period_group_and_interim():
    assert classify_companies_house_period("accounts-with-accounts-type-group") == "annual"
    assert classify_companies_house_period("accounts-with-accounts-type-interim") == "interim"
    assert classify_companies_house_period("accounts-with-accounts-type-full") == "annual"


def test_classify_filing_entity_type_s838_from_body():
    row = {
        "source": "companies_house",
        "headline": "Companies House accounts — accounts-with-accounts-type-interim",
        "summary": "accounts-with-accounts-type-interim",
        "category": "accounts",
    }
    s838_body = (
        "Interim parent company financial statements for the 6-month period ended 30 June 2024. "
        "These interim accounts have been prepared, under sections 836 and 838 of the Companies Act 2006, "
        "for the purposes of confirming that the Company now has sufficient distributable reserves."
    )
    assert classify_filing_entity_type(row, body_snippet=s838_body) == "s838_holding"
    assert classify_filing_entity_type(
        {
            "source": "companies_house",
            "headline": "Companies House accounts — accounts-with-accounts-type-group",
            "summary": "accounts-with-accounts-type-group",
        },
        body_snippet="Vistry Group PLC Annual Report 2022 Strategic report",
    ) == "consolidated"
    assert classify_filing_entity_type(
        {"headline": "Form 8.3 - Rotork plc"},
    ) == "holding_disclosure"


def test_sanitize_filings_index_reclassifies_ch_period_and_entity_type(tmp_path: Path):
    filings_dir = tmp_path / "filings"
    bodies_dir = filings_dir / "bodies"
    bodies_dir.mkdir(parents=True)
    body_path = bodies_dir / "ch_interim.txt"
    body_path.write_text(
        "Interim parent company financial statements prepared under s838 of the Act "
        "for confirming distributable reserves. Information about Vistry Group PLC solely "
        "as an individual company.",
        encoding="utf-8",
    )
    (filings_dir / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "id": "ch_interim",
                        "source": "companies_house",
                        "headline": "Companies House accounts — accounts-with-accounts-type-interim",
                        "summary": "accounts-with-accounts-type-interim",
                        "period": "other",
                        "has_body": True,
                        "body_path": str(body_path),
                    },
                    {
                        "id": "ch_group",
                        "source": "companies_house",
                        "headline": "Companies House accounts — accounts-with-accounts-type-group",
                        "summary": "accounts-with-accounts-type-group",
                        "period": "other",
                        "has_body": False,
                    },
                ],
                "summary": {"total": 2, "with_body": 1, "annual": 0, "interim": 0, "other": 2},
            }
        ),
        encoding="utf-8",
    )
    from value_investor.research.filings import sanitize_filings_index

    result = sanitize_filings_index(
        filings_dir,
        company_name="Vistry Group PLC",
        ticker="VTY.L",
    )
    assert result["reclassified"] == 2
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    interim = next(row for row in saved["filings"] if row["id"] == "ch_interim")
    group = next(row for row in saved["filings"] if row["id"] == "ch_group")
    assert interim["period"] == "interim"
    assert interim["entity_type"] == "s838_holding"
    assert group["period"] == "annual"
    assert group["entity_type"] == "consolidated"
    assert saved["summary"]["annual"] == 1
    assert saved["summary"]["interim"] == 1


def test_classify_rns_headline_annual_interim_and_trading_update():
    assert classify_rns_headline("ME Group Full Year Results") == "annual"
    assert classify_rns_headline("Half-year Results for the six months ended 30 June") == "interim"
    assert classify_rns_headline("ITV plc Q1 Trading Update") == "trading_update"
    assert classify_rns_headline("Trading Statement for the 17 weeks ended 3 May") == "trading_update"
    assert classify_rns_headline("Transaction in Own Shares") == "other"
    assert classify_rns_headline("Shell plc First Quarter 2026 Interim Dividend") == "other"


def test_classify_filing_period_annual_and_interim():
    assert classify_filing_period("Shell Plc 4th Quarter 2025 and Full Year Unaudited Results") == "annual"
    assert classify_filing_period("Shell Publishes Annual Report and Accounts") == "annual"
    assert classify_filing_period("Half-year Results") == "interim"
    assert classify_filing_period("Q1 Trading Update") == "trading_update"
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
            "headline": "Example Half-year Results",
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
            "headline": "Example Half-year Results",
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
        {"period": "trading_update", "has_body": True},
        {"period": "other", "has_body": False},
    ]
    summary = summarize_filings(filings)
    assert summary == {
        "total": 5,
        "annual": 1,
        "interim": 2,
        "trading_update": 1,
        "other": 1,
        "with_body": 3,
        "period_coverage": {
            "annual": {"total": 1, "with_body": 1},
            "interim": {"total": 2, "with_body": 1},
            "trading_update": {"total": 1, "with_body": 1},
            "other": {"total": 1, "with_body": 0},
        },
    }


def test_period_body_coverage_from_rns_index_rows():
    filings = [
        {
            "headline": "ME Group Full Year Results",
            "period": classify_rns_headline("ME Group Full Year Results"),
            "has_body": True,
        },
        {
            "headline": "ME Group Q1 Trading Update",
            "period": classify_rns_headline("ME Group Q1 Trading Update"),
            "has_body": False,
        },
    ]
    assert filings[0]["period"] == "annual"
    assert filings[1]["period"] == "trading_update"
    coverage = period_body_coverage(filings)
    assert coverage["annual"] == {"total": 1, "with_body": 1}
    assert coverage["trading_update"] == {"total": 1, "with_body": 0}


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
                    "headline": "Example PLC Full Year Results",
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
            "headline": "Example Half-year Results",
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


def test_filter_misattributed_filings_drops_uk_rns_google_news_noise():
    rows = [
        {
            "id": "bad",
            "source": "google_news_investegate",
            "headline": "Development Partnership for 294-unit hotel - Investegate",
        },
        {
            "id": "good",
            "source": "ticker_rns_api",
            "headline": "ME Group Full Year Results",
        },
    ]
    filtered = filter_misattributed_filings(
        rows,
        company_name="ME Group International plc",
        ticker="MEGP.L",
        regime="uk_rns",
    )
    assert [row["id"] for row in filtered] == ["good"]


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


def test_headline_relevant_to_issuer_asx_suffix():
    assert headline_relevant_to_issuer(
        "Notification of cessation of securities - CSL",
        "CSL Limited",
        "CSL.AX",
    )


@patch("value_investor.research.filings._decode_google_news_article_url")
def test_resolve_google_news_publisher_url_uses_batchexecute(mock_decode):
    mock_decode.return_value = "https://announcements.asx.com.au/asxpdf/20250220/pdf/x.pdf"
    url = "https://news.google.com/rss/articles/CBMiabc?oc=5"
    assert resolve_google_news_publisher_url(url) == mock_decode.return_value
    mock_decode.assert_called_once_with(url)


@patch("value_investor.research.filings._http_get")
def test_resolve_asx_publisher_document_url_finds_markit_pdf(mock_get):
    from value_investor.research.filings import resolve_asx_publisher_document_url

    mock_get.return_value = (
        b'<a href="https://asx.api.markitdigital.com/asx-research/1.0/file/abc">PDF</a>'
    )
    landing = "https://www.marketindex.com.au/asx/wgx/announcements/foo"
    assert (
        resolve_asx_publisher_document_url(landing)
        == "https://asx.api.markitdigital.com/asx-research/1.0/file/abc"
    )


def test_enrich_global_filing_rows_resolves_google_news():
    from value_investor.research.filings import enrich_global_filing_rows

    rows = [
        {
            "source": "google_news_asx",
            "url": "https://news.google.com/rss/articles/CBMiabc?oc=5",
            "headline": "WGX ASX Half Year Results Summary - Market Index",
        }
    ]
    with patch(
        "value_investor.research.filings.resolve_google_news_publisher_url",
        return_value="https://announcements.asx.com.au/asxpdf/20250220/pdf/x.pdf",
    ):
        enriched = enrich_global_filing_rows(rows)
    assert enriched[0]["url"].endswith(".pdf")
    assert enriched[0]["source"] == "google_news_asx_resolved"


def test_merge_ir_allowlist_filings_adds_missing_rows(tmp_path: Path):
    allowlist_path = tmp_path / "ir_urls.json"
    allowlist_path.write_text(
        json.dumps(
            {
                "urls": {
                    "HIK.L": [
                        "https://www.hikma.com/media/1u2besjf/april-2026-trading-update-vfinal.pdf",
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    (filings_dir / "filings_index.json").write_text(
        json.dumps({"filings": [], "summary": {"total": 0, "with_body": 0}}),
        encoding="utf-8",
    )

    result = merge_ir_allowlist_filings("HIK.L", filings_dir, path=allowlist_path)
    assert result["added"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert len(saved["filings"]) == 1
    assert saved["filings"][0]["source"] == "ir_allowlist"
    assert saved["filings"][0]["id"].startswith("ir_")


def test_refetch_ir_allowlist_filing_bodies_retries_failed_fetch(tmp_path: Path, monkeypatch):
    allowlist_path = tmp_path / "ir_urls.json"
    url = "https://www.hikma.com/media/1u2besjf/april-2026-trading-update-vfinal.pdf"
    allowlist_path.write_text(json.dumps({"urls": {"HIK.L": [url]}}), encoding="utf-8")
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    digest = "a9733d0de6aec27d"
    (filings_dir / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "id": f"ir_{digest}",
                        "source": "ir_allowlist",
                        "headline": "IR allowlist document",
                        "url": url,
                        "period": "other",
                        "has_body": False,
                        "body_path": None,
                        "priority": 130,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    attempts = {"count": 0}

    def fake_fetch(body_url):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return None
        return "Trading update narrative " + ("x" * 220)

    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        fake_fetch,
    )

    result = refetch_ir_allowlist_filing_bodies(
        filings_dir,
        "HIK.L",
        max_bodies=5,
        max_retries=2,
        allowlist_path=allowlist_path,
    )
    assert result["attempted"] == 1
    assert result["fetched"] == 1
    assert result["retries_used"] == 1
    assert attempts["count"] == 2
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert saved["filings"][0]["has_body"] is True
    assert (filings_dir / "bodies" / f"ir_{digest}.txt").exists()


def test_fetch_filings_ir_allowlist_itv_l(tmp_path: Path):
    """ITV.L IR results decks are allowlisted for segment/dividend/cash-flow gap-fill."""
    allowlist_path = tmp_path / "empty_ir.json"
    allowlist_path.write_text(json.dumps({"urls": {}}), encoding="utf-8")

    mapping = load_ir_url_allowlist(allowlist_path)
    assert "ITV.L" in mapping
    assert len(mapping["ITV.L"]) >= 3

    rows = fetch_filings_ir_allowlist("ITV.L", path=allowlist_path)
    assert len(rows) == 3
    assert all(row["source"] == "ir_allowlist" for row in rows)
    periods = {row["period"] for row in rows}
    assert "annual" in periods
    assert "interim" in periods
    assert all("itvplc.com" in row["url"] for row in rows)


def test_refetch_ir_allowlist_filing_bodies_itv_l(tmp_path: Path, monkeypatch):
    allowlist_path = tmp_path / "empty_ir.json"
    allowlist_path.write_text(json.dumps({"urls": {}}), encoding="utf-8")
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()

    rows = fetch_filings_ir_allowlist("ITV.L", path=allowlist_path)
    fy_url = next(row["url"] for row in rows if row["period"] == "annual" and "2025" in row["url"])
    import hashlib

    digest = hashlib.sha256(fy_url.encode("utf-8")).hexdigest()[:16]
    (filings_dir / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "id": f"ir_{digest}",
                        "source": "ir_allowlist",
                        "headline": "ITV FY2025 results presentation",
                        "url": fy_url,
                        "period": "annual",
                        "has_body": False,
                        "body_path": None,
                        "priority": 130,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    sample_body = (
        "ITV Studios segment revenue £2,130m. Studios margin 13-15%. "
        "Dividend policy 5.0p per share. Pro-forma cash flow bridge."
        + ("x" * 220)
    )
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda url: sample_body if url == fy_url else None,
    )

    result = refetch_ir_allowlist_filing_bodies(
        filings_dir,
        "ITV.L",
        max_bodies=5,
        allowlist_path=allowlist_path,
    )
    assert result["fetched"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert saved["filings"][0]["has_body"] is True
    body_text = (filings_dir / "bodies" / f"ir_{digest}.txt").read_text(encoding="utf-8")
    assert "Studios margin" in body_text
    assert "Dividend policy" in body_text

