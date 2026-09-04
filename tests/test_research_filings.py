"""Tests for primary RNS/results and SEC EDGAR filings ingest (separate from Yahoo)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from value_investor.fetch import CompanyMetrics
from value_investor.financials import extract_statement_metrics
from value_investor.research.filings import (
    _BUILTIN_IR_URLS,
    _apply_headline_period,
    _compose_filing_body_with_depth_sections,
    _compose_pdf_body_text,
    _extract_filing_document_text,
    _extract_investegate_html_headline,
    _extract_investegate_html_text,
    _extract_ixbrl_html_text,
    _extract_pdf_depth_sections,
    _fetch_ir_allowlist_body,
    _fetch_rns_filing_body_for_refetch,
    _filing_text_is_substantive,
    _infer_filing_period_from_row,
    _ir_body_content_hash,
    _is_other_results_rns_row,
    _issuer_matches_sec_name,
    _match_ir_row_to_investegate,
    _scrub_misattributed_filing_rows,
    _sec_edgar_supplement_allowed,
    _uk_ticker_sec_dual_listed,
    _validate_ir_allowlist_body_content,
    _validate_rns_filing_body_content,
    _validate_rns_html_headline_match,
    asx_markit_file_url,
    classify_companies_house_period,
    classify_filing_entity_type,
    classify_filing_period,
    classify_rns_headline,
    enrich_filing_rows,
    fetch_filing_body,
    fetch_filings_asx_direct,
    fetch_filings_esef_direct,
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
    reconcile_filing_body_flags,
    reconcile_filings_index_body_flags,
    refetch_companies_house_filing_bodies,
    refetch_indexed_without_body_filing_bodies,
    refetch_investegate_filing_bodies,
    refetch_ir_allowlist_filing_bodies,
    refetch_missing_filing_bodies,
    refetch_residual_filing_bodies,
    refetch_ticker_rns_api_filing_bodies,
    refetch_uk_primary_filing_bodies,
    resolve_filings_regime,
    resolve_google_news_publisher_url,
    resolve_investegate_document_url,
    resolve_investegate_lse_pdf_url,
    resolve_lse_document_url,
    resolve_lse_rns_document_url,
    resolve_sec_cik,
    sanitize_filings_index,
    summarize_filings,
)
from value_investor.research.ingest import (
    apply_cashflow_metrics_fallback,
    enrich_screening_snapshot_with_yahoo_quarterly,
    extract_cashflow_metrics_from_annual_financials,
    extract_ttm_cashflow_metrics_from_quarterly,
    fetch_annual_financials,
    ingest_research_sources,
    install_fetch_cashflow_fallback,
    quarterly_cashflow_has_usable_series,
    quarterly_income_has_usable_series,
    summarize_yahoo_quarterly_for_snapshot,
    supplement_company_metrics_cashflow,
)


def test_extract_ttm_cashflow_metrics_from_quarterly():
    """Regression: mechanical TTM FCF from four Yahoo quarterly cash-flow columns."""
    financials = {
        "quarterly_cashflow": {
            "2025-09-30": {
                "Operating Cash Flow": 29_728_000_000.0,
                "Capital Expenditure": -3_242_000_000.0,
                "Free Cash Flow": 26_486_000_000.0,
            },
            "2025-06-30": {
                "Operating Cash Flow": 53_925_000_000.0,
                "Capital Expenditure": -2_373_000_000.0,
                "Free Cash Flow": 51_552_000_000.0,
            },
            "2025-03-31": {
                "Operating Cash Flow": 28_702_000_000.0,
                "Capital Expenditure": -1_971_000_000.0,
                "Free Cash Flow": 26_731_000_000.0,
            },
            "2024-12-31": {
                "Operating Cash Flow": 34_369_000_000.0,
                "Capital Expenditure": -2_455_000_000.0,
                "Free Cash Flow": 31_914_000_000.0,
            },
        }
    }
    metrics = extract_ttm_cashflow_metrics_from_quarterly(financials)
    assert metrics["operating_cashflow_ttm"] == pytest.approx(146_724_000_000.0)
    assert metrics["capital_expenditure_ttm"] == pytest.approx(-10_041_000_000.0)
    assert metrics["free_cashflow_ttm"] == pytest.approx(136_683_000_000.0)


def test_extract_cashflow_metrics_merges_annual_and_ttm():
    financials = {
        "cash_flow": {
            "2025": {"Operating Cash Flow": 436_000_000.0, "Free Cash Flow": 119_000_000.0},
        },
        "quarterly_cashflow": {
            "2025-06-30": {
                "Operating Cash Flow": 214_000_000.0,
                "Capital Expenditure": -122_000_000.0,
                "Free Cash Flow": 92_000_000.0,
            },
            "2024-12-31": {
                "Operating Cash Flow": 150_000_000.0,
                "Capital Expenditure": -80_000_000.0,
                "Free Cash Flow": 70_000_000.0,
            },
            "2024-09-30": {
                "Operating Cash Flow": 120_000_000.0,
                "Capital Expenditure": -60_000_000.0,
                "Free Cash Flow": 60_000_000.0,
            },
            "2024-06-30": {
                "Operating Cash Flow": 110_000_000.0,
                "Capital Expenditure": -55_000_000.0,
                "Free Cash Flow": 55_000_000.0,
            },
        },
    }
    metrics = extract_cashflow_metrics_from_annual_financials(financials)
    assert metrics["operating_cashflow"] == 436_000_000.0
    assert metrics["free_cashflow"] == 119_000_000.0
    assert metrics["operating_cashflow_ttm"] == pytest.approx(594_000_000.0)
    assert metrics["free_cashflow_ttm"] == pytest.approx(277_000_000.0)


def test_apply_ttm_cashflow_gate_suppresses_when_quarterly_empty():
    """Regression: HIK.L-style empty quarterly_cashflow must not emit mechanical TTM FCF."""
    financials = {
        "cash_flow": {
            "2025": {
                "Operating Cash Flow": 436_000_000.0,
                "Capital Expenditure": -317_000_000.0,
                "Free Cash Flow": 119_000_000.0,
            },
        },
        "quarterly_cashflow": {},
    }
    metrics = extract_cashflow_metrics_from_annual_financials(financials)
    assert metrics["free_cashflow"] == 119_000_000.0
    assert "free_cashflow_ttm" not in metrics
    assert metrics["ttm_cashflow_suppressed"] is True
    assert metrics["ttm_cashflow_suppressed_reason"] == "quarterly_cashflow_empty"


def test_quarterly_cashflow_has_usable_series_requires_cashflow_lines():
    assert not quarterly_cashflow_has_usable_series({})
    assert not quarterly_cashflow_has_usable_series({"2025-06-30": {"Repayment Of Debt": -1.0}})
    assert quarterly_cashflow_has_usable_series(
        {"2025-06-30": {"Operating Cash Flow": 214_000_000.0}}
    )


def test_fetch_annual_financials_resolves_quarterly_cashflow_from_alternate_attr(monkeypatch):
    cashflow_df = pd.DataFrame(
        {"2024": [90_800_000.0, 55_000_000.0]},
        index=["Operating Cash Flow", "Free Cash Flow"],
    )
    quarterly_cashflow_df = pd.DataFrame(
        {
            pd.Timestamp("2025-06-30"): [214_000_000.0, -122_000_000.0, 92_000_000.0],
            pd.Timestamp("2024-12-31"): [150_000_000.0, -80_000_000.0, 70_000_000.0],
            pd.Timestamp("2024-09-30"): [120_000_000.0, -60_000_000.0, 60_000_000.0],
            pd.Timestamp("2024-06-30"): [110_000_000.0, -55_000_000.0, 55_000_000.0],
        },
        index=["Operating Cash Flow", "Capital Expenditure", "Free Cash Flow"],
    )

    class DummyTicker:
        financials = pd.DataFrame()
        balance_sheet = pd.DataFrame()
        cashflow = cashflow_df
        quarterly_financials = None
        quarterly_cashflow = pd.DataFrame()
        quarterly_cash_flow = quarterly_cashflow_df

    monkeypatch.setattr("value_investor.research.ingest.yf.Ticker", lambda _t: DummyTicker())
    payload = fetch_annual_financials("HIK.L")
    assert payload["quarterly_cashflow_source"] == "quarterly_cash_flow"
    assert payload["quarterly_cashflow"]["2025-06-30"]["Operating Cash Flow"] == 214_000_000.0
    assert payload["cashflow_metrics"]["free_cashflow_ttm"] == pytest.approx(277_000_000.0)
    assert "ttm_cashflow_suppressed" not in payload["cashflow_metrics"]


def test_fetch_annual_financials_uk_empty_quarterly_suppresses_ttm(monkeypatch):
    """Regression: UK (.L) tickers with empty Yahoo quarterly cashflow gate TTM at fetch."""
    cashflow_df = pd.DataFrame(
        {"2025": [436_000_000.0, -317_000_000.0, 119_000_000.0]},
        index=["Operating Cash Flow", "Capital Expenditure", "Free Cash Flow"],
    )

    class DummyTicker:
        financials = pd.DataFrame()
        balance_sheet = pd.DataFrame()
        cashflow = cashflow_df
        quarterly_financials = None
        quarterly_cashflow = pd.DataFrame()
        quarterly_cash_flow = pd.DataFrame()

    monkeypatch.setattr("value_investor.research.ingest.yf.Ticker", lambda _t: DummyTicker())
    for ticker in ("HIK.L", "ITV.L"):
        payload = fetch_annual_financials(ticker)
        assert payload["ticker"] == ticker
        assert payload["quarterly_cashflow"] == {}
        assert payload["cashflow_metrics"]["free_cashflow"] == 119_000_000.0
        assert "free_cashflow_ttm" not in payload["cashflow_metrics"]
        assert payload["cashflow_metrics"]["ttm_cashflow_suppressed"] is True
        assert (
            payload["cashflow_metrics"]["ttm_cashflow_suppressed_reason"]
            == "quarterly_cashflow_empty"
        )


def test_fetch_annual_financials_quarterly_income_uses_period_keys(monkeypatch):
    quarterly_income_df = pd.DataFrame(
        {
            pd.Timestamp("2026-06-30"): [94_000_000_000.0, 1.57, 1.58],
            pd.Timestamp("2026-03-31"): [95_400_000_000.0, 1.65, 1.66],
            pd.Timestamp("2025-12-31"): [124_300_000_000.0, 2.4, 2.41],
            pd.Timestamp("2025-09-30"): [94_900_000_000.0, 1.64, 1.65],
        },
        index=["Total Revenue", "Basic EPS", "Diluted EPS"],
    )

    class DummyTicker:
        financials = pd.DataFrame()
        balance_sheet = pd.DataFrame()
        cashflow = pd.DataFrame()
        quarterly_financials = quarterly_income_df
        quarterly_cashflow = pd.DataFrame()

    monkeypatch.setattr("value_investor.research.ingest.yf.Ticker", lambda _t: DummyTicker())
    payload = fetch_annual_financials("AAPL")
    assert payload["quarterly_income_source"] == "quarterly_financials"
    assert list(payload["quarterly_income"].keys()) == [
        "2026-06-30",
        "2026-03-31",
        "2025-12-31",
        "2025-09-30",
    ]
    assert payload["quarterly_income"]["2026-06-30"]["Diluted EPS"] == pytest.approx(1.58)


def test_fetch_annual_financials_resolves_quarterly_income_from_alternate_attr(monkeypatch):
    quarterly_income_df = pd.DataFrame(
        {
            pd.Timestamp("2025-04-30"): [315_400_000.0, 0.0648],
            pd.Timestamp("2024-10-31"): [307_900_000.0, 0.0674],
        },
        index=["Total Revenue", "Diluted EPS"],
    )

    class DummyTicker:
        financials = pd.DataFrame()
        balance_sheet = pd.DataFrame()
        cashflow = pd.DataFrame()
        quarterly_financials = pd.DataFrame()
        quarterly_income_stmt = quarterly_income_df
        quarterly_cashflow = pd.DataFrame()

    monkeypatch.setattr("value_investor.research.ingest.yf.Ticker", lambda _t: DummyTicker())
    payload = fetch_annual_financials("MEGP.L")
    assert payload["quarterly_income_source"] == "quarterly_income_stmt"
    assert payload["quarterly_income"]["2025-04-30"]["Diluted EPS"] == pytest.approx(0.0648)


def test_quarterly_income_has_usable_series_requires_eps_or_revenue():
    assert not quarterly_income_has_usable_series({})
    assert not quarterly_income_has_usable_series({"2025-06-30": {"Tax Rate For Calcs": 0.25}})
    assert quarterly_income_has_usable_series({"2025-06-30": {"Diluted EPS": 0.15}})
    assert quarterly_income_has_usable_series({"2025-06-30": {"Total Revenue": 100.0}})


def test_summarize_yahoo_quarterly_for_snapshot_period_labels():
    financials = {
        "quarterly_income": {
            "2025-04-30": {"Diluted EPS": 0.0648, "Total Revenue": 315_400_000.0},
            "2024-10-31": {"Diluted EPS": 0.0674, "Total Revenue": 307_900_000.0},
        },
        "quarterly_cashflow": {
            "2025-04-30": {
                "Operating Cash Flow": 25_200_000.0,
                "Free Cash Flow": 20_000_000.0,
            }
        },
        "cashflow_metrics": {
            "free_cashflow_ttm": 15_600_000.0,
            "ttm_cashflow_suppressed": False,
        },
        "quarterly_income_source": "quarterly_income_stmt",
        "quarterly_cashflow_source": "quarterly_cashflow",
    }
    summary = summarize_yahoo_quarterly_for_snapshot(financials)
    assert summary["quarterly_income"][0]["period_label"] == "2025-04-30"
    assert summary["quarterly_income"][0]["diluted_eps"] == pytest.approx(0.0648)
    assert summary["quarterly_cashflow"][0]["period_label"] == "2025-04-30"
    assert summary["quarterly_cashflow"][0]["free_cashflow"] == pytest.approx(20_000_000.0)
    assert summary["ttm_cashflow"]["free_cashflow_ttm"] == pytest.approx(15_600_000.0)


def test_enrich_screening_snapshot_with_yahoo_quarterly():
    snapshot = {"ticker": "MEGP.L", "signal": "strong_buy"}
    financials = {
        "quarterly_income": {"2025-04-30": {"Diluted EPS": 0.0648}},
        "quarterly_cashflow": {},
        "cashflow_metrics": {
            "ttm_cashflow_suppressed": True,
            "ttm_cashflow_suppressed_reason": "quarterly_cashflow_empty",
        },
    }
    enriched = enrich_screening_snapshot_with_yahoo_quarterly(snapshot, financials)
    assert enriched["yahoo_quarterly"]["quarterly_income"][0]["period_label"] == "2025-04-30"
    assert enriched["yahoo_quarterly"]["ttm_cashflow_suppressed"] is True


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
        "cash_flow": {
            "2024": {"Operating Cash Flow": 90_800_000.0, "Free Cash Flow": 55_000_000.0}
        },
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
    quarterly_cashflow_df = pd.DataFrame(
        {
            pd.Timestamp("2025-09-30"): [29_728_000_000.0, -3_242_000_000.0, 26_486_000_000.0],
            pd.Timestamp("2025-06-30"): [53_925_000_000.0, -2_373_000_000.0, 51_552_000_000.0],
            pd.Timestamp("2025-03-31"): [28_702_000_000.0, -1_971_000_000.0, 26_731_000_000.0],
            pd.Timestamp("2024-12-31"): [34_369_000_000.0, -2_455_000_000.0, 31_914_000_000.0],
        },
        index=["Operating Cash Flow", "Capital Expenditure", "Free Cash Flow"],
    )

    class DummyTicker:
        financials = pd.DataFrame()
        balance_sheet = pd.DataFrame()
        cashflow = cashflow_df
        quarterly_financials = None
        quarterly_cashflow = quarterly_cashflow_df

    monkeypatch.setattr("value_investor.research.ingest.yf.Ticker", lambda _t: DummyTicker())
    payload = fetch_annual_financials("MEGP.L")
    assert payload["cashflow_metrics"]["operating_cashflow"] == 90_800_000.0
    assert payload["cashflow_metrics"]["free_cashflow"] == 55_000_000.0
    assert payload["quarterly_cashflow"]["2025-09-30"]["Operating Cash Flow"] == 29_728_000_000.0
    assert payload["cashflow_metrics"]["free_cashflow_ttm"] == pytest.approx(136_683_000_000.0)


def test_headline_relevant_to_issuer_filters_noise():
    assert headline_relevant_to_issuer(
        "Morgan Sindall Full Year Results", "Morgan Sindall Group plc", "MGNS.L"
    )
    assert headline_relevant_to_issuer("MGNS Interim Results", "Morgan Sindall Group plc", "MGNS.L")
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
    assert not headline_relevant_to_issuer("Net Asset Value(s)", "AEP Plantations Plc", "AEP.L")
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


def test_fetch_filing_body_resolves_sec_pdf_wrapper(monkeypatch):
    """Regression: HLN.L 6-K indexed as -pdf.htm must follow the linked exhibit PDF."""
    cover_html = """
    <html><body>
    <div>FORM 6-K REPORT OF FOREIGN PRIVATE ISSUER</div>
    <p>Haleon plc Commission File Number: 001-41411</p>
    <a href="a2418q.pdf">Exhibit 99.1</a>
    </body></html>
    """
    pdf_text = (
        "Haleon plc: Cash tender offer for outstanding 2027 3.375% Fixed Rate Notes. "
        "London, 11 August 2026: Haleon plc announces a cash tender offer for "
        "$1,999 million of outstanding senior notes due March 2027. Bondholders will "
        "receive a price equal to the tender offer consideration plus accrued interest. "
        "The tender offer expires on 8 September 2026 unless extended. "
        "Full results of the tender offer will be announced after the expiration date."
    )

    def fake_http_get(url, headers=None, timeout=60):
        if url.endswith("a2418q-pdf.htm"):
            return cover_html.encode("utf-8")
        if url.endswith("a2418q.pdf"):
            return pdf_text.encode("utf-8")
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr("value_investor.research.filings._http_get", fake_http_get)
    monkeypatch.setattr(
        "value_investor.research.filings._extract_filing_document_text",
        lambda raw, content_type: raw.decode("utf-8"),
    )
    url = "https://www.sec.gov/Archives/edgar/data/1900304/000165495426007463/a2418q-pdf.htm"
    text = fetch_filing_body(url)
    assert text is not None
    assert "Cash tender offer" in text
    assert "2027 3.375%" in text


def test_refetch_residual_filing_bodies_fetches_sec_pdf_wrapper(tmp_path, monkeypatch):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    sec_url = "https://www.sec.gov/Archives/edgar/data/1900304/000165495426007463/a2418q-pdf.htm"
    index = {
        "ticker": "HLN.L",
        "company_name": "Haleon plc",
        "filings": [
            {
                "id": "209e954fb6528f31",
                "source": "sec_edgar",
                "headline": "6-K: CASH TENDER OFFER FOR OUTSTANDING 2027 3.375% FIXED RATE NOTES",
                "published_at": "2026-08-11T00:00:00+00:00",
                "url": sec_url,
                "period": "interim",
                "has_body": False,
                "body_path": None,
                "priority": 80,
            }
        ],
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.research.filings.enrich_filing_rows",
        lambda filings, **kwargs: list(filings),
    )
    pdf_text = (
        "Haleon plc: Cash tender offer for outstanding 2027 3.375% Fixed Rate Notes. "
        "London, 11 August 2026: Haleon plc announces a cash tender offer for "
        "$1,999 million of outstanding senior notes due March 2027. Bondholders will "
        "receive a price equal to the tender offer consideration plus accrued interest. "
        "The tender offer expires on 8 September 2026 unless extended. "
        "Full results of the tender offer will be announced after the expiration date."
    )

    def fake_http_get(url, headers=None, timeout=60):
        if url.endswith("a2418q-pdf.htm"):
            return (
                b"<html><body><div>FORM 6-K</div>"
                b'<a href="a2418q.pdf">Exhibit 99.1</a></body></html>'
            )
        if url.endswith("a2418q.pdf"):
            return pdf_text.encode("utf-8")
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr("value_investor.research.filings._http_get", fake_http_get)
    monkeypatch.setattr(
        "value_investor.research.filings._extract_filing_document_text",
        lambda raw, content_type: raw.decode("utf-8"),
    )
    result = refetch_residual_filing_bodies(
        filings_dir,
        ticker="HLN.L",
        company_name="Haleon plc",
        max_bodies=4,
    )
    assert result["attempted"] == 1
    assert result["fetched"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert saved["filings"][0]["has_body"] is True


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


def test_fetch_filings_investegate_company_keeps_bare_rns_headlines(monkeypatch):
    """Issuer company pages list titles without repeating the EPIC or brand name."""
    html = """
    <table>
      <tr>
        <td>13 Jul 2026</td><td>07:00 AM</td>
        <td><a href="https://www.investegate.co.uk/announcement/rns/grafton-group-ut-cdi---gftu/trading-update/1">Trading Update</a></td>
      </tr>
      <tr>
        <td>05 Mar 2026</td><td>07:00 AM</td>
        <td><a href="https://www.investegate.co.uk/announcement/rns/grafton-group-ut-cdi---gftu/final-results/2">Final Results</a></td>
      </tr>
    </table>
    """
    monkeypatch.setattr(
        "value_investor.research.filings._http_get",
        lambda url, headers=None, timeout=60: html.encode("utf-8"),
    )
    rows = fetch_filings_investegate_company(
        ticker="GFTU.L",
        company_name="Grafton Group plc",
    )
    assert len(rows) == 2
    periods = {row["period"] for row in rows}
    assert "trading_update" in periods
    assert "annual" in periods


def test_headline_relevant_to_issuer_gftu_gn5_alias():
    assert headline_relevant_to_issuer(
        "Grafton Group plc (GN5) Trading Update",
        "Grafton Group plc",
        "GFTU.L",
    )
    assert headline_relevant_to_issuer(
        "Grafton Group Full Year Results",
        "Grafton Group plc",
        "GFTU.L",
    )


def test_fetch_filings_ticker_api_tries_gn5_alias_when_gftu_empty(monkeypatch):
    calls: list[str] = []

    def fake_get(url, headers=None, timeout=60):
        if "symbol=GFTU" in url:
            return json.dumps({"data": []}).encode("utf-8")
        if "symbol=GN5" in url:
            calls.append("GN5")
            return json.dumps(
                {
                    "data": [
                        {
                            "headline": "Grafton Group plc Interim Results",
                            "symbol": "GN5",
                            "timestamp": "2026-07-01T07:00:00Z",
                            "url": "https://newswire.tickerapp.net/rns/2026-07-01/gn5/interim.pdf",
                        },
                    ],
                }
            ).encode("utf-8")
        raise AssertionError(url)

    monkeypatch.setattr("value_investor.research.filings._http_get", fake_get)
    monkeypatch.setenv("TICKER_API_KEY", "test-key")
    from value_investor.research.filings import fetch_filings_ticker_api

    rows = fetch_filings_ticker_api(
        ticker="GFTU.L",
        company_name="Grafton Group plc",
    )
    assert calls == ["GN5"]
    assert len(rows) == 1
    assert rows[0]["period"] == "interim"


def test_filter_misattributed_news_articles_drops_sector_noise():
    from value_investor.research.ingest import filter_misattributed_news_articles

    articles = [
        {
            "id": "good",
            "title": "Grafton Group plc Trading Update",
        },
        {
            "id": "bad",
            "title": "Breedon Reports Higher Revenue and Raises Dividend",
        },
    ]
    kept = filter_misattributed_news_articles(
        articles,
        company_name="Grafton Group plc",
        ticker="GFTU.L",
        market="ftse350",
    )
    assert [row["id"] for row in kept] == ["good"]


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
    investegate_url = "https://www.investegate.co.uk/announcement/rns/itv--itv/itv-plc-full-year-results-2025/9459201"
    lse_pdf = "http://www.rns-pdf.londonstockexchange.com/rns/3965V_1-2026-3-4.pdf"
    html = f'<a href="{lse_pdf}">PDF</a>'
    monkeypatch.setattr(
        "value_investor.research.filings._http_get",
        lambda url, headers=None, timeout=60: html.encode("utf-8"),
    )
    assert resolve_investegate_lse_pdf_url(investegate_url) == lse_pdf
    assert resolve_investegate_lse_pdf_url(lse_pdf) == lse_pdf


def test_resolve_lse_document_url_finds_embedded_pdf():
    lse_pdf = "http://www.rns-pdf.londonstockexchange.com/rns/3965V_1-2026-3-4.pdf"
    html = f"""
    <html><body>
    <p>View the associated PDF document.</p>
    <a href="{lse_pdf}">PDF</a>
    </body></html>
    """
    assert resolve_lse_document_url(html) == lse_pdf


def test_resolve_lse_rns_document_url_upgrades_html_wrapper(monkeypatch):
    lse_html = "https://docs.londonstockexchange.com/rns/abc123/announcement.html"
    lse_pdf = "http://www.rns-pdf.londonstockexchange.com/rns/3965V_1-2026-3-4.pdf"
    page_html = f'<a href="{lse_pdf}">Download PDF</a>'

    def fake_get(url, headers=None, timeout=60):
        if url == lse_html:
            return page_html.encode("utf-8")
        raise AssertionError(url)

    monkeypatch.setattr("value_investor.research.filings._http_get", fake_get)
    assert resolve_lse_rns_document_url(lse_html) == lse_pdf
    assert resolve_lse_rns_document_url(lse_pdf) == lse_pdf


def test_fetch_filing_body_lse_html_wrapper_follows_pdf(monkeypatch):
    lse_html = "https://docs.londonstockexchange.com/rns/abc123/announcement.html"
    lse_pdf = "http://www.rns-pdf.londonstockexchange.com/rns/3965V_1-2026-3-4.pdf"
    page_html = f'<a href="{lse_pdf}">Download PDF</a>'
    pdf_text = "A" * 250 + " revenue increased and operating profit rose sharply."

    def fake_get(url, headers=None, timeout=60):
        if url == lse_html:
            return page_html.encode("utf-8")
        if url == lse_pdf:
            return b"%PDF-fake"
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("value_investor.research.filings._http_get", fake_get)
    monkeypatch.setattr(
        "value_investor.research.filings._extract_filing_document_text",
        lambda raw, content_type: pdf_text,
    )
    text = fetch_filing_body(lse_html)
    assert text is not None
    assert "revenue increased" in text


def test_fetch_filings_investegate_company_tries_gn5_alias_for_gftu(monkeypatch):
    html = """
    <table>
      <tr>
        <td>05 Mar 2026</td><td>07:00 AM</td>
        <td><a href="https://www.investegate.co.uk/announcement/rns/grafton-group-ut-cdi---gftu/final-results/2">Final Results</a></td>
      </tr>
    </table>
    """

    def fake_get(url, headers=None, timeout=60):
        if "/company/GFTU" in url:
            return b"<html></html>"
        if "/company/GN5" in url:
            return html.encode("utf-8")
        raise AssertionError(url)

    monkeypatch.setattr("value_investor.research.filings._http_get", fake_get)
    rows = fetch_filings_investegate_company(
        ticker="GFTU.L",
        company_name="Grafton Group plc",
    )
    assert len(rows) == 1
    assert rows[0]["period"] == "annual"


def test_fetch_filing_body_investegate_follows_lse_pdf(monkeypatch):
    investegate_url = "https://www.investegate.co.uk/announcement/rns/itv--itv/itv-plc-full-year-results-2025/9459201"
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


def test_resolve_investegate_document_url_follows_gsk_annual_report_microsite(monkeypatch):
    """GSK stub RNS pages link to annualreport.gsk.com instead of an LSE PDF."""
    investegate_html = """
    <h1>GSK publishes Annual Report 2025</h1>
    <p>Available on the company website.</p>
    <a href="https://annualreport.gsk.com">Annual Report 2025</a>
    """
    microsite_html = """
    <a href="/media/kn0bknmd/annual-report-2025.pdf">Annual Report 2025</a>
    <a href="/media/immdjzop/financial-statements-2025.pdf">Financial statements</a>
    """

    def fake_get(url, headers=None, timeout=60):
        if url == "https://annualreport.gsk.com":
            return microsite_html.encode("utf-8")
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("value_investor.research.filings._http_get", fake_get)
    assert resolve_investegate_document_url(investegate_html) == (
        "https://www.gsk.com/media/kn0bknmd/annual-report-2025.pdf"
    )


def test_fetch_filing_body_investegate_follows_gsk_annual_report_microsite(monkeypatch):
    investegate_url = (
        "https://www.investegate.co.uk/announcement/rns/gsk--gsk/"
        "gsk-publishes-annual-report-2025/9460267"
    )
    microsite_url = "https://annualreport.gsk.com"
    gsk_pdf = "https://www.gsk.com/media/kn0bknmd/annual-report-2025.pdf"
    investegate_html = f"""
    <h1>GSK publishes Annual Report 2025</h1>
    <p>Available on the company website.</p>
    <a href="{microsite_url}">Annual Report 2025</a>
    """
    microsite_html = '<a href="/media/kn0bknmd/annual-report-2025.pdf">Annual Report</a>'
    pdf_text = "Annual report narrative " + ("revenue increased " * 40)

    def fake_get(url, headers=None, timeout=60):
        if url == investegate_url:
            return investegate_html.encode("utf-8")
        if url == microsite_url:
            return microsite_html.encode("utf-8")
        if url == gsk_pdf:
            return b"%PDF-fake"
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("value_investor.research.filings._http_get", fake_get)
    monkeypatch.setattr(
        "value_investor.research.filings._extract_filing_document_text",
        lambda raw, content_type: pdf_text,
    )
    text = fetch_filing_body(investegate_url)
    assert text is not None
    assert "Annual report narrative" in text


def test_refetch_investegate_filing_bodies_gsk_annual_report_stub(tmp_path, monkeypatch):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    investegate_url = (
        "https://www.investegate.co.uk/announcement/rns/gsk--gsk/"
        "gsk-publishes-annual-report-2025/9460267"
    )
    index = {
        "ticker": "GSK.L",
        "company_name": "GSK plc",
        "filings": [
            {
                "id": "db941b0e4174a2a7",
                "source": "investegate_resolved",
                "headline": "GSK publishes Annual Report 2025 - Investegate",
                "published_at": "2026-03-05T10:02:32+00:00",
                "url": investegate_url,
                "period": "annual",
                "has_body": False,
                "body_path": None,
                "priority": 120,
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
        lambda url: "Annual report narrative " + ("revenue increased " * 40),
    )
    result = refetch_investegate_filing_bodies(
        filings_dir,
        ticker="GSK.L",
        company_name="GSK plc",
        max_bodies=5,
    )
    assert result["attempted"] == 1
    assert result["fetched"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert saved["filings"][0]["has_body"] is True
    assert (filings_dir / "bodies" / "db941b0e4174a2a7.txt").exists()


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
    assert fetch_filing_body("https://news.google.com/rss/articles/CBMiabc?oc=5") is None


def test_refetch_investegate_rejects_unresolved_google_news_wrapper(tmp_path, monkeypatch):
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


def test_validate_rns_filing_body_rejects_period_mismatch():
    row = {
        "headline": "ITV plc Full Year Results 2025",
        "period": "annual",
    }
    interim_body = (
        "ITV plc half year interim results for six months ended 30 June 2025. "
        "Advertising revenue down 3% with interim dividend maintained." + ("x" * 220)
    )
    valid, reason = _validate_rns_filing_body_content(
        row,
        interim_body,
        company_name="ITV plc",
        ticker="ITV.L",
    )
    assert valid is False
    assert reason == "period_mismatch"

    annual_body = (
        "ITV plc full year results for the year ended 31 December 2025. "
        "Total revenue £3.5bn with final dividend of 5.0p per share." + ("x" * 220)
    )
    valid, reason = _validate_rns_filing_body_content(
        row,
        annual_body,
        company_name="ITV plc",
        ticker="ITV.L",
    )
    assert valid is True
    assert reason is None


def test_validate_rns_filing_body_rejects_misattributed_issuer():
    row = {
        "headline": "ME Group Full Year Results",
        "period": "annual",
    }
    foreign_body = (
        "Dollar General Corporation reports full year results with revenue growth "
        "across rural America stores and strong cash generation." + ("x" * 220)
    )
    valid, reason = _validate_rns_filing_body_content(
        row,
        foreign_body,
        company_name="ME Group International plc",
        ticker="MEGP.L",
    )
    assert valid is False
    assert reason == "issuer_mismatch"


def test_extract_investegate_html_headline_parses_h1():
    html = """
    <html><body>
    <h1>ITV plc Full Year Results 2025</h1>
    <p>Revenue up 3% with final dividend maintained.</p>
    </body></html>
    """
    assert _extract_investegate_html_headline(html) == "ITV plc Full Year Results 2025"


def test_infer_filing_period_from_other_row_headline():
    row = {
        "period": "other",
        "headline": "ITV plc Full Year Results 2025 - Investegate",
        "url": "https://www.investegate.co.uk/announcement/rns/itv--itv/fy/1",
    }
    assert _infer_filing_period_from_row(row) == "annual"


def test_validate_rns_html_headline_match_rejects_period_mismatch():
    row = {
        "headline": "April 2026 Trading Update",
        "period": "trading_update",
        "url": "https://www.hikma.com/media/april-2026-trading-update-vfinal.pdf",
    }
    valid, reason = _validate_rns_html_headline_match(row, "Half Year Interim Results 2026")
    assert valid is False
    assert reason == "headline_mismatch"


def test_validate_rns_filing_body_rejects_other_row_with_mismatched_html_headline():
    row = {
        "headline": "April 2026 Trading Update",
        "period": "other",
        "url": "https://www.hikma.com/media/april-2026-trading-update-vfinal.pdf",
    }
    body = (
        "Hikma Pharmaceuticals PLC trading update April 2026: group revenue growth "
        "2% to 4% and operating profit guidance maintained." + ("x" * 220)
    )
    valid, reason = _validate_rns_filing_body_content(
        row,
        body,
        company_name="Hikma Pharmaceuticals PLC",
        ticker="HIK.L",
        extracted_headline="Half Year Interim Results 2026",
    )
    assert valid is False
    assert reason == "headline_mismatch"


def test_apply_headline_period_upgrades_other_from_body_cues():
    row = {
        "headline": "Results",
        "period": "other",
        "source": "investegate_resolved",
    }
    body_snippet = (
        "FirstGroup plc full year results for the year ended 31 March 2026. "
        "Revenue £5.2bn with adjusted operating profit of £420m."
    )
    updated = _apply_headline_period(row, body_snippet=body_snippet)
    assert updated["period"] == "annual"


def test_is_other_results_rns_row_detects_fy_headline():
    row = {
        "period": "other",
        "headline": "FY2025 Full Year Results - Investegate",
        "has_body": False,
        "url": "https://www.investegate.co.uk/announcement/rns/example/fy/1",
    }
    assert _is_other_results_rns_row(row) is True


def test_refetch_investegate_rejects_html_fallback_headline_mismatch(tmp_path, monkeypatch):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    index = {
        "ticker": "HIK.L",
        "company_name": "Hikma Pharmaceuticals PLC",
        "filings": [
            {
                "id": "hik_trading",
                "source": "investegate_resolved",
                "headline": "Hikma Pharmaceuticals PLC April 2026 Trading Update",
                "published_at": "2026-04-01T00:00:00+00:00",
                "url": "https://www.investegate.co.uk/announcement/rns/hikma/trading/1",
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
        lambda url: None,
    )
    interim_body = (
        "Hikma Pharmaceuticals PLC half year interim results for six months ended June 2025. "
        "Revenue up 8% with interim dividend maintained." + ("x" * 220)
    )
    monkeypatch.setattr(
        "value_investor.research.filings._fetch_rns_filing_body_for_refetch",
        lambda url: (interim_body, "Half Year Interim Results 2026"),
    )
    result = refetch_investegate_filing_bodies(
        filings_dir,
        ticker="HIK.L",
        company_name="Hikma Pharmaceuticals PLC",
        max_bodies=5,
    )
    assert result["attempted"] == 1
    assert result["fetched"] == 0
    assert result["body_rejected"] == 1
    assert result["html_fallbacks"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert saved["filings"][0]["has_body"] is False


def test_refetch_investegate_rejects_duplicate_rns_body_hash(tmp_path, monkeypatch):
    """Reject RNS refetch when fetched body matches another indexed filing's content hash."""
    filings_dir = tmp_path / "filings"
    bodies_dir = filings_dir / "bodies"
    bodies_dir.mkdir(parents=True)
    shared_body = (
        "Hikma Pharmaceuticals PLC half year interim results for six months ended June 2025. "
        "Core revenue grew 6% with adjusted operating profit up 4%." + ("x" * 220)
    )
    content_hash = _ir_body_content_hash(shared_body)
    interim_path = bodies_dir / "hik_interim.txt"
    interim_path.write_text(shared_body, encoding="utf-8")
    index = {
        "ticker": "HIK.L",
        "company_name": "Hikma Pharmaceuticals PLC",
        "filings": [
            {
                "id": "hik_interim",
                "source": "ticker_rns_api",
                "headline": "Hikma Pharmaceuticals PLC Half Year Results 2025",
                "published_at": "2026-08-01T00:00:00+00:00",
                "url": "https://newswire.tickerapp.net/rns/interim.pdf",
                "period": "interim",
                "has_body": True,
                "body_path": str(interim_path),
                "body_content_hash": content_hash,
                "priority": 120,
            },
            {
                "id": "hik_trading",
                "source": "investegate_resolved",
                "headline": "Hikma Pharmaceuticals PLC April 2026 Trading Update",
                "published_at": "2026-04-01T00:00:00+00:00",
                "url": "https://www.investegate.co.uk/announcement/rns/hikma/trading/1",
                "period": "trading_update",
                "has_body": False,
                "body_path": None,
                "priority": 90,
            },
        ],
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.research.filings.enrich_filing_rows",
        lambda rows, *, ticker, company_name: list(rows),
    )
    monkeypatch.setattr(
        "value_investor.research.filings._fetch_rns_filing_body_for_refetch",
        lambda url: (shared_body, None),
    )
    result = refetch_investegate_filing_bodies(
        filings_dir,
        ticker="HIK.L",
        company_name="Hikma Pharmaceuticals PLC",
        max_bodies=5,
    )
    assert result["attempted"] == 1
    assert result["fetched"] == 0
    assert result["body_rejected"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    trading = next(row for row in saved["filings"] if row["id"] == "hik_trading")
    assert trading["has_body"] is False
    assert not (bodies_dir / "hik_trading.txt").exists()


def test_refetch_ticker_rns_api_stores_body_content_hash(tmp_path, monkeypatch):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    pdf_url = "https://newswire.tickerapp.net/rns/2026-03-05/1234M/example.content.pdf"
    sample_body = (
        "ME Group International plc full year results for the year ended 31 March 2026. "
        "Revenue increased across all segments." + ("x" * 220)
    )
    index = {
        "ticker": "MEGP.L",
        "company_name": "ME Group International plc",
        "filings": [
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
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda url: sample_body if url == pdf_url else None,
    )
    result = refetch_ticker_rns_api_filing_bodies(
        filings_dir,
        ticker="MEGP.L",
        company_name="ME Group International plc",
        max_bodies=5,
    )
    assert result["fetched"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    row = saved["filings"][0]
    assert row["has_body"] is True
    assert row["body_content_hash"] == _ir_body_content_hash(sample_body)


def test_refetch_investegate_prioritizes_other_results_rows(tmp_path, monkeypatch):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    index = {
        "ticker": "FGP.L",
        "company_name": "FirstGroup plc",
        "filings": [
            {
                "id": "trivia",
                "source": "investegate_direct",
                "headline": "Total Voting Rights",
                "published_at": "2026-02-01T00:00:00+00:00",
                "url": "https://www.investegate.co.uk/announcement/rns/firstgroup/tvr/1",
                "period": "other",
                "has_body": False,
                "body_path": None,
                "priority": 10,
            },
            {
                "id": "fy_other",
                "source": "investegate_direct",
                "headline": "FY2025 Full Year Results",
                "published_at": "2026-03-05T00:00:00+00:00",
                "url": "https://www.investegate.co.uk/announcement/rns/firstgroup/fy/1",
                "period": "other",
                "has_body": False,
                "body_path": None,
                "priority": 50,
            },
        ],
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.research.filings.enrich_filing_rows",
        lambda rows, *, ticker, company_name: list(rows),
    )
    fetch_order: list[str] = []

    def fake_fetch(url):
        fetch_order.append(url)
        return "Annual results narrative " + ("x" * 220)

    monkeypatch.setattr(
        "value_investor.research.filings._fetch_rns_filing_body_for_refetch",
        lambda url: (fake_fetch(url), None),
    )
    result = refetch_investegate_filing_bodies(
        filings_dir,
        ticker="FGP.L",
        company_name="FirstGroup plc",
        max_bodies=1,
    )
    assert result["attempted"] == 2
    assert result["fetched"] == 1
    assert result["other_results_candidates"] == 1
    assert fetch_order[0].endswith("/fy/1")
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in saved["filings"]}
    assert by_id["fy_other"]["has_body"] is True
    assert by_id["fy_other"]["period"] == "annual"
    assert by_id["trivia"]["has_body"] is False


def test_fetch_rns_filing_body_for_refetch_uses_html_fallback(monkeypatch):
    investegate_url = "https://www.investegate.co.uk/announcement/rns/itv--itv/itv-plc-full-year-results-2025/9459201"
    html = (
        """
    <html><body>
    <h1>ITV plc Full Year Results 2025</h1>
    <p>Revenue up 3% with adjusted operating profit ahead of expectations.</p>
    """
        + ("detail " * 120)
        + """
    </body></html>
    """
    )
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda url: None,
    )
    monkeypatch.setattr(
        "value_investor.research.filings._http_get",
        lambda url, **kwargs: html.encode("utf-8"),
    )
    body, headline = _fetch_rns_filing_body_for_refetch(investegate_url)
    assert headline == "ITV plc Full Year Results 2025"
    assert body is not None
    assert "Full Year Results 2025" in body


def test_fetch_rns_filing_body_for_refetch_lse_html_fallback(monkeypatch):
    """Regression: direct LSE HTML wrapper without embedded PDF uses narrative fallback."""
    lse_html = "https://docs.londonstockexchange.com/rns/itv/fy2025.html"
    page_html = (
        """
    <html><body>
    <h1>ITV plc Full Year Results 2025</h1>
    <p>Revenue increased 3% and operating profit rose with pension deficit reduced.</p>
    """
        + ("detail " * 120)
        + """
    </body></html>
    """
    )
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda url: None,
    )

    def fake_get(url, headers=None, timeout=60):
        if url == lse_html:
            return page_html.encode("utf-8")
        raise AssertionError(url)

    monkeypatch.setattr("value_investor.research.filings._http_get", fake_get)
    body, headline = _fetch_rns_filing_body_for_refetch(lse_html)
    assert headline == "ITV plc Full Year Results 2025"
    assert body is not None
    assert "Revenue increased" in body


def test_ch_row_needs_body_refetch_when_lacks_financial_depth(tmp_path):
    from value_investor.research.filings import _ch_row_needs_body_refetch

    filings_dir = tmp_path / "filings" / "bodies"
    filings_dir.mkdir(parents=True)
    row_id = "ch_shallow"
    shallow = "Directors report and strategic overview " + ("x" * 220)
    (filings_dir / f"{row_id}.txt").write_text(shallow, encoding="utf-8")
    row = {
        "id": row_id,
        "source": "companies_house",
        "has_body": True,
        "body_path": str(filings_dir / f"{row_id}.txt"),
    }
    assert _ch_row_needs_body_refetch(row, filings_dir) is True


def test_refetch_companies_house_filing_bodies_retries_shallow_ixbrl_body(tmp_path, monkeypatch):
    """Regression: shallow CH front-matter bodies are re-fetched for pension/borrowings depth."""
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    row_id = "ch_shallow_ixbrl"
    shallow = "Directors report and strategic overview " + ("x" * 220)
    deep = "Defined benefit pension scheme borrowings covenant going concern cash flow " + (
        "x" * 220
    )
    index = {
        "filings": [
            {
                "id": row_id,
                "source": "companies_house",
                "headline": "Companies House accounts",
                "url": "https://document-api.company-information.service.gov.uk/document/ch1",
                "period": "annual",
                "has_body": True,
                "body_path": str(filings_dir / "bodies" / f"{row_id}.txt"),
            }
        ],
        "summary": {"total": 1, "with_body": 1},
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    bodies_dir = filings_dir / "bodies"
    bodies_dir.mkdir()
    (bodies_dir / f"{row_id}.txt").write_text(shallow, encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.research.filings._fetch_companies_house_body",
        lambda row: deep if row.get("id") == row_id else None,
    )
    result = refetch_companies_house_filing_bodies(filings_dir, max_bodies=3)
    assert result["attempted"] == 1
    assert result["fetched"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert "borrowings" in (bodies_dir / f"{row_id}.txt").read_text(encoding="utf-8")
    assert saved["filings"][0]["has_body"] is True


def test_refetch_investegate_rejects_misattributed_body(tmp_path, monkeypatch):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    index = {
        "ticker": "ITV.L",
        "company_name": "ITV plc",
        "filings": [
            {
                "id": "itv_fy",
                "source": "investegate_resolved",
                "headline": "ITV plc Full Year Results 2025",
                "published_at": "2026-03-05T00:00:00+00:00",
                "url": "https://www.investegate.co.uk/announcement/rns/itv--itv/fy/1",
                "period": "annual",
                "has_body": False,
                "body_path": None,
                "priority": 120,
            }
        ],
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.research.filings.enrich_filing_rows",
        lambda rows, *, ticker, company_name: list(rows),
    )
    interim_body = (
        "ITV plc half year interim results for six months ended 30 June 2025. "
        "Advertising revenue down 3%." + ("x" * 220)
    )
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda url: interim_body,
    )
    result = refetch_investegate_filing_bodies(
        filings_dir,
        ticker="ITV.L",
        company_name="ITV plc",
        max_bodies=5,
    )
    assert result["attempted"] == 1
    assert result["fetched"] == 0
    assert result["body_rejected"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert saved["filings"][0]["has_body"] is False
    assert not (filings_dir / "bodies" / "itv_fy.txt").exists()


def test_refetch_investegate_reclassifies_period_from_body(tmp_path, monkeypatch):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    index = {
        "ticker": "ITV.L",
        "company_name": "ITV plc",
        "filings": [
            {
                "id": "itv_q1",
                "source": "investegate_resolved",
                "headline": "ITV plc Q1 Trading Update",
                "published_at": "2026-04-01T00:00:00+00:00",
                "url": "https://www.investegate.co.uk/announcement/rns/itv--itv/q1/1",
                "period": "interim",
                "has_body": False,
                "body_path": None,
                "priority": 80,
            }
        ],
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.research.filings.enrich_filing_rows",
        lambda rows, *, ticker, company_name: list(rows),
    )
    trading_body = (
        "ITV plc trading update for the three months to 31 March 2026. "
        "Total advertising revenue up 2% with ITV Studios performing ahead of plan." + ("x" * 220)
    )
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda url: trading_body,
    )
    result = refetch_investegate_filing_bodies(
        filings_dir,
        ticker="ITV.L",
        company_name="ITV plc",
        max_bodies=5,
    )
    assert result["fetched"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert saved["filings"][0]["period"] == "trading_update"
    assert saved["filings"][0]["has_body"] is True


def test_compose_filing_body_includes_principal_risks_section():
    lead = "Annual report narrative " + ("overview " * 5000)
    risks = (
        "\n\nPRINCIPAL RISKS AND UNCERTAINTIES\n"
        "Legal and regulatory risk: pricing pressure in US generics may intensify. "
        "Product pipeline risk: launch delays could affect revenue guidance." + (" detail " * 800)
    )
    composed = _compose_filing_body_with_depth_sections(lead + risks)
    assert composed is not None
    assert "PRINCIPAL RISKS AND UNCERTAINTIES" in composed
    assert "Legal and regulatory risk" in composed


def test_period_body_coverage_excludes_s838_holding():
    filings = [
        {
            "headline": "Companies House interim accounts",
            "period": "interim",
            "entity_type": "s838_holding",
            "has_body": True,
        },
        {
            "headline": "ME Group Interim Results",
            "period": "interim",
            "entity_type": "consolidated",
            "has_body": False,
        },
    ]
    coverage = period_body_coverage(filings)
    assert coverage["interim"] == {"total": 1, "with_body": 0}


def test_refetch_indexed_without_body_filing_bodies_orchestrates(tmp_path, monkeypatch):
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
    assert resolve_investegate_url(row, ticker="ITV.L", company_name="ITV plc") == decoded


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


def test_compose_filing_body_with_depth_sections_includes_pension_and_covenant():
    """Regression: depth extract must reach pension, covenant, and adjusting-item notes."""
    early = "Directors' report and strategic overview " * 900
    pension_page = (
        "DEFINED BENEFIT PENSION SCHEME\n"
        "Scheme assets 1,200\n"
        "Present value of obligations 1,450\n"
        "Net pension deficit 250"
    )
    covenant_page = (
        "FINANCIAL COVENANTS\n"
        "Net debt to EBITDA must remain below 3.5x\n"
        "Interest cover covenant headroom 18%"
    )
    adjusting_page = "ADJUSTING ITEMS\nRestructuring costs 45\nAsset impairment 72"
    full = early[:3500] + pension_page + covenant_page + adjusting_page

    text = _compose_filing_body_with_depth_sections(full)
    assert text is not None
    assert "Directors' report" in text
    assert "DEFINED BENEFIT PENSION SCHEME" in text
    assert "Net pension deficit 250" in text
    assert "FINANCIAL COVENANTS" in text
    assert "Interest cover covenant headroom 18%" in text
    assert "ADJUSTING ITEMS" in text
    assert "Asset impairment 72" in text


def test_extract_ixbrl_html_text_splices_late_pension_and_covenant_notes():
    early = "STRATEGIC REPORT revenue increased operating profit rose " * 650
    tail = (
        " DEFINED BENEFIT PENSION obligations 1,450 scheme assets 1,200"
        " FINANCIAL COVENANTS net debt to EBITDA 3.5x headroom adequate"
        " CONSOLIDATED STATEMENT OF CASH FLOW operating activities 90.8"
    )
    html = f"<html><body><div>{early}{tail}</div></body></html>"
    text = _extract_ixbrl_html_text(html)
    assert "STRATEGIC REPORT" in text
    assert "DEFINED BENEFIT PENSION" in text
    assert "FINANCIAL COVENANTS" in text
    assert "CONSOLIDATED STATEMENT OF CASH FLOW" in text


def test_refetch_uk_primary_filing_bodies_orchestrates_ch_and_lse(tmp_path, monkeypatch):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    (filings_dir / "filings_index.json").write_text(
        json.dumps({"filings": [], "summary": {"with_body": 0}}),
        encoding="utf-8",
    )
    ch_result = {
        "attempted": 2,
        "fetched": 1,
        "with_body_before": 0,
        "with_body_after": 1,
    }
    rns_result = {
        "investegate": {
            "attempted": 3,
            "fetched": 2,
            "with_body_before": 1,
            "with_body_after": 3,
            "google_news_rejected": 1,
        },
        "ticker_rns": {
            "attempted": 1,
            "fetched": 0,
            "with_body_before": 3,
            "with_body_after": 3,
        },
        "attempted": 4,
        "fetched": 2,
        "with_body_before": 1,
        "with_body_after": 3,
        "google_news_rejected": 1,
    }
    monkeypatch.setattr(
        "value_investor.research.filings.refetch_companies_house_filing_bodies",
        lambda *args, **kwargs: dict(ch_result),
    )
    monkeypatch.setattr(
        "value_investor.research.filings.refetch_indexed_without_body_filing_bodies",
        lambda *args, **kwargs: dict(rns_result),
    )
    residual_result = {
        "attempted": 0,
        "fetched": 0,
        "pruned": 0,
        "with_body_before": 3,
        "with_body_after": 3,
    }
    monkeypatch.setattr(
        "value_investor.research.filings.refetch_residual_filing_bodies",
        lambda *args, **kwargs: dict(residual_result),
    )
    result = refetch_uk_primary_filing_bodies(
        filings_dir,
        ticker="FGP.L",
        company_name="FirstGroup plc",
        max_bodies=20,
    )
    assert result["fetched"] == 3
    assert result["attempted"] == 6
    assert result["with_body_before"] == 0
    assert result["with_body_after"] == 3
    assert result["google_news_rejected"] == 1
    assert result["companies_house"]["fetched"] == 1
    assert result["rns"]["investegate"]["fetched"] == 2


def test_uk_primary_pipeline_investegate_lse_pdf_persists_with_validation_gate(
    tmp_path, monkeypatch
):
    """UK primary refetch persists Investegate/LSE bodies that pass period/issuer validation."""
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    index = {
        "ticker": "ITV.L",
        "company_name": "ITV plc",
        "filings": [
            {
                "id": "itv_fy",
                "source": "investegate_resolved",
                "headline": "ITV plc Full Year Results 2025",
                "published_at": "2026-03-05T00:00:00+00:00",
                "url": "https://www.investegate.co.uk/announcement/rns/itv--itv/fy/1",
                "period": "annual",
                "has_body": False,
                "body_path": None,
                "priority": 120,
            }
        ],
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    annual_body = (
        "ITV plc full year results for the year ended 31 December 2025. "
        "Total revenue £3.5bn with final dividend of 5.0p per share." + ("x" * 220)
    )
    monkeypatch.setattr(
        "value_investor.research.filings.enrich_filing_rows",
        lambda rows, *, ticker, company_name: list(rows),
    )
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda url: annual_body,
    )
    monkeypatch.setattr(
        "value_investor.research.filings._fetch_companies_house_body",
        lambda row: None,
    )
    result = refetch_uk_primary_filing_bodies(
        filings_dir,
        ticker="ITV.L",
        company_name="ITV plc",
        max_bodies=5,
    )
    assert result["fetched"] >= 1
    assert result["rns"]["investegate"]["fetched"] >= 1
    assert (filings_dir / "bodies" / "itv_fy.txt").exists()
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert saved["filings"][0]["has_body"] is True
    assert saved["filings"][0]["period"] == "annual"


def test_refetch_residual_filing_bodies_fetches_sec_edgar(tmp_path, monkeypatch):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    sec_url = "https://www.sec.gov/Archives/edgar/data/123/000123456789012345/accession.htm"
    index = {
        "ticker": "HLN.L",
        "company_name": "Haleon plc",
        "filings": [
            {
                "id": "sec1",
                "source": "sec_edgar",
                "headline": "6-K: Tender offer",
                "published_at": "2026-01-15T00:00:00+00:00",
                "url": sec_url,
                "period": "other",
                "has_body": False,
                "body_path": None,
                "priority": 80,
            }
        ],
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.research.filings.enrich_filing_rows",
        lambda filings, **kwargs: list(filings),
    )
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda url: "SEC exhibit body " + ("x" * 220) if "sec.gov" in url else None,
    )
    result = refetch_residual_filing_bodies(
        filings_dir,
        ticker="HLN.L",
        company_name="Haleon plc",
        max_bodies=4,
    )
    assert result["attempted"] == 1
    assert result["fetched"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert saved["filings"][0]["has_body"] is True


def test_refetch_residual_filing_bodies_validates_uk_rns_body(tmp_path, monkeypatch):
    """Residual sweep applies period/issuer validation for LSE RNS rows."""
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    lse_html = "https://docs.londonstockexchange.com/rns/itv/fy2025.html"
    index = {
        "ticker": "ITV.L",
        "company_name": "ITV plc",
        "filings": [
            {
                "id": "itv_residual",
                "source": "ticker_rns_api",
                "headline": "ITV plc Full Year Results 2025",
                "published_at": "2026-03-05T00:00:00+00:00",
                "url": lse_html,
                "period": "annual",
                "has_body": False,
                "body_path": None,
                "priority": 120,
            }
        ],
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    interim_body = (
        "ITV plc half year interim results for six months ended 30 June 2025. "
        "Advertising revenue down 3%." + ("x" * 220)
    )
    monkeypatch.setattr(
        "value_investor.research.filings.enrich_filing_rows",
        lambda filings, **kwargs: list(filings),
    )
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda url: interim_body,
    )
    result = refetch_residual_filing_bodies(
        filings_dir,
        ticker="ITV.L",
        company_name="ITV plc",
        max_bodies=4,
    )
    assert result["attempted"] == 1
    assert result["fetched"] == 0
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert saved["filings"][0]["has_body"] is False
    assert not (filings_dir / "bodies" / "itv_residual.txt").exists()


def test_refetch_residual_filing_bodies_prunes_unfetchable_google_news(tmp_path, monkeypatch):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    gnews_url = "https://news.google.com/rss/articles/CBMiW0FVX3lxTE1QVElPVGsx"
    index = {
        "ticker": "JD.L",
        "company_name": "JD Sports Fashion Plc",
        "filings": [
            {
                "id": "gn1",
                "source": "google_news_investegate",
                "headline": "JD Sports Fashion (JD.) Share Price - Investegate",
                "published_at": "2026-01-15T00:00:00+00:00",
                "url": gnews_url,
                "period": "other",
                "has_body": False,
                "body_path": None,
                "priority": 10,
            }
        ],
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.research.filings.enrich_filing_rows",
        lambda filings, **kwargs: list(filings),
    )
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda url: None,
    )
    result = refetch_residual_filing_bodies(
        filings_dir,
        ticker="JD.L",
        company_name="JD Sports Fashion Plc",
        max_bodies=4,
    )
    assert result["attempted"] == 1
    assert result["fetched"] == 0
    assert result["pruned_noise"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert saved["filings"] == []


def test_refetch_residual_filing_bodies_prunes_share_price_headline_noise(tmp_path, monkeypatch):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    index = {
        "ticker": "JD.L",
        "company_name": "JD Sports Fashion Plc",
        "filings": [
            {
                "id": "gn1",
                "source": "google_news_investegate",
                "headline": "JD Sports Fashion (JD.) Share Price - investegate.co.uk",
                "published_at": "2026-01-15T00:00:00+00:00",
                "url": "https://www.investegate.co.uk/announcement/rns/jd/share-price",
                "period": "other",
                "has_body": False,
                "body_path": None,
                "priority": 10,
            }
        ],
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.research.filings.enrich_filing_rows",
        lambda filings, **kwargs: list(filings),
    )
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda url: None,
    )
    result = refetch_residual_filing_bodies(
        filings_dir,
        ticker="JD.L",
        company_name="JD Sports Fashion Plc",
        max_bodies=4,
    )
    assert result["pruned_noise"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert saved["filings"] == []


def test_refetch_residual_filing_bodies_intensive_prunes_after_failed_fetch(tmp_path, monkeypatch):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    sec_url = "https://www.sec.gov/Archives/edgar/data/123/000123456789012345/accession.htm"
    index = {
        "ticker": "HLN.L",
        "company_name": "Haleon plc",
        "filings": [
            {
                "id": "sec1",
                "source": "sec_edgar",
                "headline": "6-K: Tender offer",
                "published_at": "2026-01-15T00:00:00+00:00",
                "url": sec_url,
                "period": "other",
                "has_body": False,
                "body_path": None,
                "priority": 80,
            }
        ],
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.research.filings.enrich_filing_rows",
        lambda filings, **kwargs: list(filings),
    )
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda url: None,
    )
    result = refetch_residual_filing_bodies(
        filings_dir,
        ticker="HLN.L",
        company_name="Haleon plc",
        max_bodies=4,
        prune_unfetchable_after_attempt=True,
    )
    assert result["attempted"] == 1
    assert result["fetched"] == 0
    assert result["pruned_unfetchable"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert saved["filings"] == []


def test_refetch_residual_weekday_keeps_failed_sec_row(tmp_path, monkeypatch):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    sec_url = "https://www.sec.gov/Archives/edgar/data/123/000123456789012345/accession.htm"
    index = {
        "ticker": "HLN.L",
        "company_name": "Haleon plc",
        "filings": [
            {
                "id": "sec1",
                "source": "sec_edgar",
                "headline": "6-K: Tender offer",
                "published_at": "2026-01-15T00:00:00+00:00",
                "url": sec_url,
                "period": "other",
                "has_body": False,
                "body_path": None,
                "priority": 80,
            }
        ],
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.research.filings.enrich_filing_rows",
        lambda filings, **kwargs: list(filings),
    )
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda url: None,
    )
    result = refetch_residual_filing_bodies(
        filings_dir,
        ticker="HLN.L",
        company_name="Haleon plc",
        max_bodies=4,
        prune_unfetchable_after_attempt=False,
    )
    assert result["attempted"] == 1
    assert result["pruned_unfetchable"] == 0
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert len(saved["filings"]) == 1


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
    borrowings_page = (
        "NOTE 12 Borrowings\n"
        "Bank loans 450\n"
        "Revolving credit facility 120\n"
        "FINANCIAL COVENANTS net debt to EBITDA must remain below 3.5x"
    )
    pages = [early[:3500]] * 10 + [cash_flow_page, exceptional_page, borrowings_page, segment_page]

    text = _compose_pdf_body_text(pages)
    assert text is not None
    assert "Chief Executive Review" in text
    assert "CONSOLIDATED STATEMENT OF CASH FLOW" in text
    assert "Cash generated from operations 90.8" in text
    assert "NOTE 5 Exceptional items" in text
    assert "Legal settlement 72" in text
    assert "NOTE 12 Borrowings" in text
    assert "Revolving credit facility 120" in text
    assert "FINANCIAL COVENANTS" in text
    assert "SEGMENT INFORMATION" in text
    assert "RELATED PARTY TRANSACTIONS" in text
    assert "Sales to associate 12" in text


def test_fetch_filing_body_pdf_splices_late_borrowings_pension_and_segment(monkeypatch):
    """Regression: PDF fetch must reach borrowings, pension, covenant, and segment notes."""
    early = "Strategic report and chairman's statement " * 900
    notes_tail = (
        " NOTE 12 Borrowings bank loans 450 revolving credit facility 120 "
        " NOTE 24 Defined benefit pension scheme deficit 85 "
        " FINANCIAL COVENANTS net debt to EBITDA 3.5x headroom adequate "
        " SEGMENT INFORMATION UK revenue 800 US revenue 400"
    )
    full_pdf_text = early[:3500] + notes_tail

    monkeypatch.setattr(
        "value_investor.research.filings._http_get",
        lambda url, headers=None, timeout=60: b"%PDF-fake",
    )
    monkeypatch.setattr(
        "value_investor.research.filings._extract_filing_document_text",
        lambda raw, content_type: _compose_filing_body_with_depth_sections(full_pdf_text),
    )
    text = fetch_filing_body("https://example.com/accounts.pdf")
    assert text is not None
    assert "Strategic report" in text
    assert "NOTE 12 Borrowings" in text
    assert "Defined benefit pension" in text
    assert "FINANCIAL COVENANTS" in text
    assert "SEGMENT INFORMATION" in text


def test_extract_filing_document_text_ocr_applies_depth_sections(monkeypatch):
    early = "Cover page and contents " * 1200
    tail = (
        " CONSOLIDATED STATEMENT OF CASH FLOW operating activities 90.8 "
        " NOTE 18 Borrowings term loan 200"
    )
    ocr_full = early + tail
    monkeypatch.setattr(
        "value_investor.research.filings._extract_pdf_text",
        lambda raw: None,
    )
    monkeypatch.setattr(
        "value_investor.research.filings._ocr_pdf_text",
        lambda raw: ocr_full,
    )
    text = _extract_filing_document_text(b"%PDF-1.4", "application/pdf")
    assert text is not None
    assert "CONSOLIDATED STATEMENT OF CASH FLOW" in text
    assert "NOTE 18 Borrowings" in text


def test_extract_filing_document_text_ocr_upgrades_shallow_pypdf_extract(monkeypatch):
    """Image-only CH PDFs that yield CEO-only pypdf text should fall through to OCR depth."""
    shallow = (
        "Strategic report and chairman's statement for the year ended 31 December 2025. "
        "Revenue increased and the board recommends a final dividend." + (" overview " * 80)
    )
    ocr_full = shallow + (
        " CONSOLIDATED STATEMENT OF CASH FLOW operating activities 90.8 "
        " Defined benefit pension scheme obligations 45.2 "
        " NOTE 18 Borrowings covenant compliance maintained"
    )
    monkeypatch.setattr(
        "value_investor.research.filings._extract_pdf_text",
        lambda raw: shallow,
    )
    monkeypatch.setattr(
        "value_investor.research.filings._extract_pdf_text_fitz",
        lambda raw: None,
    )
    monkeypatch.setattr(
        "value_investor.research.filings._ocr_pdf_text",
        lambda raw: ocr_full,
    )
    text = _extract_filing_document_text(b"%PDF-1.4", "application/pdf")
    assert text is not None
    assert "CONSOLIDATED STATEMENT OF CASH FLOW" in text
    assert "Defined benefit pension" in text
    assert "Borrowings covenant" in text


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


def test_refetch_companies_house_filing_bodies_retries_stale_has_body(tmp_path, monkeypatch):
    """Regression: re-fetch when index marks has_body but on-disk text is missing."""
    filings_dir = tmp_path / "filings"
    bodies_dir = filings_dir / "bodies"
    bodies_dir.mkdir(parents=True)
    ch_url = "https://document-api.company-information.service.gov.uk/document/ch-stale"
    index = {
        "filings": [
            {
                "id": "ch_stale",
                "source": "companies_house",
                "headline": "Companies House accounts — group",
                "url": ch_url,
                "document_metadata_url": ch_url,
                "period": "annual",
                "has_body": True,
                "body_path": str(bodies_dir / "ch_stale.txt"),
                "priority": 140,
            }
        ]
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    body_text = "A" * 220 + " statutory accounts pension going concern covenant"
    monkeypatch.setattr(
        "value_investor.research.filings._fetch_companies_house_body",
        lambda row: body_text,
    )
    result = refetch_companies_house_filing_bodies(filings_dir, max_bodies=3)
    assert result["attempted"] == 1
    assert result["fetched"] == 1
    assert (bodies_dir / "ch_stale.txt").read_text(encoding="utf-8") == body_text


def test_refetch_companies_house_filing_bodies_multi_indexed_rows(tmp_path, monkeypatch):
    """Regression: MER.L-style index with several CH rows and zero bodies."""
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    ch_url = "https://document-api.company-information.service.gov.uk/document/ch"
    rows = [
        {
            "id": f"ch_row_{idx}",
            "source": "companies_house",
            "headline": f"Companies House accounts — group {idx}",
            "url": f"{ch_url}{idx}",
            "document_metadata_url": f"{ch_url}{idx}",
            "period": "annual",
            "has_body": False,
            "body_path": None,
            "priority": 140,
        }
        for idx in range(5)
    ]
    (filings_dir / "filings_index.json").write_text(
        json.dumps({"ticker": "MER.L", "filings": rows, "summary": {"total": 5, "with_body": 0}}),
        encoding="utf-8",
    )
    body_text = "A" * 220 + " consolidated income pension covenant going concern"
    monkeypatch.setattr(
        "value_investor.research.filings._fetch_companies_house_body",
        lambda row: body_text,
    )
    result = refetch_companies_house_filing_bodies(filings_dir, max_bodies=2)
    assert result["attempted"] == 5
    assert result["fetched"] == 2
    assert result["with_body_after"] == 2
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert sum(1 for row in saved["filings"] if row.get("has_body")) == 2


def test_fetch_document_bytes_attempts_oversized_pdf_when_only_format(monkeypatch):
    """Regression: do not skip PDF when it is the only available CH format."""
    from value_investor.research.companies_house import (
        MIME_PDF,
        fetch_document_bytes,
    )

    meta = {
        "links": {"document": "/document/vct-only/content"},
        "resources": {MIME_PDF: {"content_length": 95_000_000}},
    }
    calls: list[str] = []

    def fake_get(url, *, api_key, accept="application/json", timeout=60.0, retries=2):
        if url.endswith("/document/vct-only"):
            return json.dumps(meta).encode("utf-8")
        calls.append(accept)
        return b"%PDF-1.4 oversized statutory accounts"

    monkeypatch.setattr("value_investor.research.companies_house._ch_get", fake_get)
    monkeypatch.setattr(
        "value_investor.research.companies_house.time.sleep", lambda *_a, **_k: None
    )
    fetched = fetch_document_bytes(
        "https://document-api.company-information.service.gov.uk/document/vct-only",
        api_key="test-key",
    )
    assert fetched is not None
    assert fetched[1] == MIME_PDF
    assert MIME_PDF in calls


_VCT_IXBRL_FIXTURE_HTML = (
    b'<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL">'
    b"<body><div>STRATEGIC REPORT</div>"
    b"<p>Victrex plc consolidated revenue pension covenant going concern borrowings. "
    b"Segment information and related party transactions for the group. "
    b"Notes to the financial statements cover exceptional items and adjusting items. "
    b"Consolidated cash flow statement and consolidated balance sheet disclosures.</p>"
    b"</body></html>"
)


def test_extract_filing_document_text_parses_ch_zip_ixbrl_package():
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("reports/report.html", _VCT_IXBRL_FIXTURE_HTML)
    text = _extract_filing_document_text(buf.getvalue(), "application/zip")
    assert text is not None
    assert "STRATEGIC REPORT" in text
    assert "Victrex" in text


def test_refetch_companies_house_filing_bodies_vct_l_zip_ixbrl_gap(tmp_path, monkeypatch):
    """Regression: VCT.L FY2025 CH annual gap (ch_02793780_MzUwMzgzMTQyOWFkaXF6a2N4)."""
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    ch_url = (
        "https://document-api.company-information.service.gov.uk/document/"
        "7iLf3HQWfOUlSiKOvCISIf9zIePMlIhubeQAUqF0Ivg"
    )
    index = {
        "ticker": "VCT.L",
        "company_name": "Victrex plc",
        "filings": [
            {
                "id": "ch_02793780_MzUwMzgzMTQyOWFkaXF6a2N4",
                "source": "companies_house",
                "headline": "Companies House accounts — accounts-with-accounts-type-group",
                "published_at": "2026-02-09T00:00:00+00:00",
                "url": ch_url,
                "document_metadata_url": ch_url,
                "period": "annual",
                "has_body": False,
                "body_path": None,
                "priority": 100,
                "company_number": "02793780",
            }
        ],
        "summary": {"total": 1, "annual": 1, "with_body": 0},
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    body_text = (
        "A" * 220
        + " Victrex plc consolidated income statement pension covenant going concern borrowings"
    )
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "test-key")
    monkeypatch.setattr(
        "value_investor.research.filings._fetch_companies_house_body",
        lambda row: body_text if row.get("id") == "ch_02793780_MzUwMzgzMTQyOWFkaXF6a2N4" else None,
    )
    result = refetch_companies_house_filing_bodies(filings_dir, max_bodies=5)
    assert result["attempted"] == 1
    assert result["fetched"] == 1
    assert result["with_body_after"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert saved["filings"][0]["has_body"] is True
    assert (filings_dir / "bodies" / "ch_02793780_MzUwMzgzMTQyOWFkaXF6a2N4.txt").exists()


def test_fetch_companies_house_body_vct_l_zip_ixbrl_end_to_end(monkeypatch):
    """End-to-end: zip-only CH metadata yields substantive Victrex accounts text."""
    import io
    import zipfile

    from value_investor.research.companies_house import MIME_ZIP, iter_ch_document_downloads
    from value_investor.research.filings import _fetch_companies_house_body

    ch_url = (
        "https://document-api.company-information.service.gov.uk/document/"
        "7iLf3HQWfOUlSiKOvCISIf9zIePMlIhubeQAUqF0Ivg"
    )
    html = _VCT_IXBRL_FIXTURE_HTML
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("reports/report.html", html)
    zip_payload = buf.getvalue()

    meta = {
        "links": {"document": "/document/vct/content"},
        "resources": {MIME_ZIP: {"content_length": len(zip_payload)}},
    }

    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "test-key")
    monkeypatch.setattr(
        "value_investor.research.companies_house.fetch_document_metadata",
        lambda *args, **kwargs: meta,
    )
    monkeypatch.setattr(
        "value_investor.research.companies_house.fetch_document_bytes",
        lambda *args, **kwargs: (zip_payload, MIME_ZIP),
    )
    downloads = iter_ch_document_downloads(ch_url, api_key="test-key")
    assert len(downloads) == 1
    row = {
        "id": "ch_02793780_MzUwMzgzMTQyOWFkaXF6a2N4",
        "document_metadata_url": ch_url,
        "url": ch_url,
    }
    body = _fetch_companies_house_body(row)
    assert body is not None
    assert "Victrex" in body
    assert "STRATEGIC REPORT" in body


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
        "value_investor.research.filings.refetch_companies_house_filing_bodies",
        lambda *args, **kwargs: {
            "attempted": 0,
            "fetched": 0,
            "with_body_before": 0,
            "with_body_after": 0,
        },
    )
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda url: "Body text " + ("x" * 220),
    )
    result = refetch_missing_filing_bodies(filings_dir, max_bodies=4)
    assert result["fetched"] == 1
    assert result["with_body_after"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert saved["filings"][0]["has_body"] is True


def test_refetch_missing_filing_bodies_delegates_ch_rows(tmp_path, monkeypatch):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    ch_url = "https://document-api.company-information.service.gov.uk/document/ch1"
    index = {
        "filings": [
            {
                "id": "ch_row",
                "source": "companies_house",
                "headline": "Companies House accounts",
                "url": ch_url,
                "document_metadata_url": ch_url,
                "period": "annual",
                "has_body": False,
                "body_path": None,
                "priority": 140,
            }
        ]
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    body_text = "A" * 220 + " statutory accounts pension going concern"
    monkeypatch.setattr(
        "value_investor.research.filings._fetch_companies_house_body",
        lambda row: body_text,
    )
    result = refetch_missing_filing_bodies(filings_dir, max_bodies=4)
    assert result["fetched"] == 1
    assert result["with_body_after"] == 1
    assert (filings_dir / "bodies" / "ch_row.txt").exists()


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
            "ME Group International plc full year results " + ("revenue increased " * 30)
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
    assert classify_companies_house_period("full", category="accounts") == "annual"


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
    assert (
        classify_filing_entity_type(
            {
                "source": "companies_house",
                "headline": "Companies House accounts — accounts-with-accounts-type-group",
                "summary": "accounts-with-accounts-type-group",
            },
            body_snippet="Vistry Group PLC Annual Report 2022 Strategic report",
        )
        == "consolidated"
    )
    assert (
        classify_filing_entity_type(
            {"headline": "Form 8.3 - Rotork plc"},
        )
        == "holding_disclosure"
    )


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
    assert (
        classify_rns_headline("Trading Statement for the 17 weeks ended 3 May") == "trading_update"
    )
    assert classify_rns_headline("Transaction in Own Shares") == "other"
    assert classify_rns_headline("Shell plc First Quarter 2026 Interim Dividend") == "other"


def test_classify_filing_period_annual_and_interim():
    assert (
        classify_filing_period("Shell Plc 4th Quarter 2025 and Full Year Unaudited Results")
        == "annual"
    )
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


def test_reconcile_filing_body_flags_restores_disk_bodies(tmp_path: Path):
    bodies_dir = tmp_path / "bodies"
    bodies_dir.mkdir()
    row_id = "abcd1234abcd1234"
    body_path = bodies_dir / f"{row_id}.txt"
    body_path.write_text(
        "Annual results for Example PLC with revenue and profit and dividend commentary. "
        "The group reported strong revenue growth and operating profit improvement "
        "with net debt reduction and cash flow from operations remaining robust.",
        encoding="utf-8",
    )
    filings = [
        {
            "id": row_id,
            "headline": "Full Year Results",
            "published_at": "2026-01-01",
            "has_body": False,
            "body_path": None,
        }
    ]
    reconciled = reconcile_filing_body_flags(
        filings,
        bodies_dir,
        company_name="Example PLC",
        ticker="EXAM.L",
    )
    assert reconciled[0]["has_body"] is True
    assert reconciled[0]["body_path"] == str(body_path)


def test_reconcile_filings_index_body_flags_updates_summary(tmp_path: Path):
    filings_dir = tmp_path / "filings"
    bodies_dir = filings_dir / "bodies"
    bodies_dir.mkdir(parents=True)
    row_id = "abcd1234abcd1234"
    (bodies_dir / f"{row_id}.txt").write_text(
        "Interim results for Example PLC with revenue and operating profit growth. "
        "The group reported revenue and earnings improvement with dividend maintained "
        "and net debt reduced while cash flow from operations remained positive.",
        encoding="utf-8",
    )
    index = {
        "ticker": "EXAM.L",
        "filings": [
            {
                "id": row_id,
                "headline": "Half-year Results",
                "published_at": "2026-01-01",
                "has_body": False,
                "body_path": None,
            }
        ],
        "summary": {"with_body": 0, "annual": 0, "interim": 0, "other": 0},
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    result = reconcile_filings_index_body_flags(
        filings_dir,
        company_name="Example PLC",
        ticker="EXAM.L",
    )
    assert result["restored"] == 1
    data = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert data["summary"]["with_body"] == 1


def test_ingest_filings_preserves_prior_body_on_reingest(tmp_path: Path):
    filings_dir = tmp_path / "filings"
    bodies_dir = filings_dir / "bodies"
    bodies_dir.mkdir(parents=True)
    row_id = "abcd1234abcd1234"
    body_path = bodies_dir / f"{row_id}.txt"
    body_path.write_text(
        "Annual results for Example PLC with revenue and profit and dividend commentary. "
        "The group reported strong revenue growth and operating profit improvement "
        "with net debt reduction and cash flow from operations remaining robust.",
        encoding="utf-8",
    )
    prior = {
        "ticker": "EXAM.L",
        "company_name": "Example PLC",
        "filings": [
            {
                "id": row_id,
                "source": "investegate_rns_full",
                "headline": "Full Year Results",
                "published_at": "2026-02-05T07:00:00+00:00",
                "url": "https://www.investegate.co.uk/announcement/rns/example/full-year/1",
                "period": "annual",
                "has_body": True,
                "body_path": str(body_path),
                "priority": 120,
            }
        ],
        "summary": {"with_body": 1, "annual": 1, "interim": 0, "other": 0},
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(prior), encoding="utf-8")

    fresh_rows = [
        {
            "id": row_id,
            "source": "google_news_investegate",
            "headline": "Full Year Results",
            "published_at": "2026-02-05T07:00:00+00:00",
            "url": "https://news.google.com/rss/articles/x",
            "period": "annual",
            "has_body": False,
            "body_path": None,
            "priority": 120,
        }
    ]
    with (
        patch("value_investor.research.filings.fetch_filings_ticker_api", return_value=[]),
        patch("value_investor.research.filings.fetch_filings_google_news", return_value=fresh_rows),
        patch("value_investor.research.filings.fetch_filing_body", return_value=None),
        patch(
            "value_investor.research.companies_house.fetch_filings_companies_house",
            return_value=[],
        ),
        patch("value_investor.research.filings.fetch_filings_ir_allowlist", return_value=[]),
        patch(
            "value_investor.research.filings.fetch_filings_investegate_company",
            return_value=[],
        ),
    ):
        meta = ingest_filings(
            ticker="EXAM.L",
            company_name="Example PLC",
            sources_dir=tmp_path,
        )

    assert meta["filings_summary"]["with_body"] >= 1
    data = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert any(row.get("has_body") for row in data["filings"])


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
                "quarterly_income": {
                    "2025-04-30": {"Diluted EPS": 0.0648, "Total Revenue": 315_400_000.0},
                },
                "quarterly_cashflow": {
                    "2025-04-30": {
                        "Operating Cash Flow": 25_200_000.0,
                        "Free Cash Flow": 20_000_000.0,
                    }
                },
                "cashflow_metrics": {
                    "free_cashflow_ttm": 15_600_000.0,
                },
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
    snapshot = json.loads((sources / "screening_snapshot.json").read_text(encoding="utf-8"))
    assert snapshot["yahoo_quarterly"]["quarterly_income"][0]["period_label"] == "2025-04-30"
    assert snapshot["yahoo_quarterly"]["quarterly_cashflow"][0]["period_label"] == "2025-04-30"


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
        patch(
            "value_investor.research.filings.fetch_filings_sec_edgar", return_value=sec_rows
        ) as sec,
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

    assert (
        _issuer_matches_sec_name(
            "Costain Group PLC",
            "COSTCO WHOLESALE CORP /NEW",
            "COST.L",
        )
        is False
    )
    assert (
        _issuer_matches_sec_name(
            "Shell plc",
            "Shell plc",
            "SHEL.L",
        )
        is True
    )
    assert (
        _issuer_matches_sec_name(
            "Rio Tinto Group",
            "RIO TINTO PLC",
            "RIO.L",
        )
        is True
    )


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


def test_headline_relevant_to_issuer_rejects_vct_trust_for_victrex():
    """VCT.L (Victrex) must not match unrelated Venture Capital Trust RNS headlines."""
    reject = [
        'Foresight 4 VCT PLC (the "Company") - Investegate',
        "Albion Technology & General VCT PLC: Annual Financial Report",
        "ProVen VCT plc: Annual Financial Report - Investegate",
    ]
    accept = [
        "Victrex plc Preliminary Results",
        "Full Year Results - VCT",
        "Interim Management Statement - VCT",
    ]
    for headline in reject:
        assert headline_relevant_to_issuer(headline, "Victrex plc", "VCT.L") is False
    for headline in accept:
        assert headline_relevant_to_issuer(headline, "Victrex plc", "VCT.L") is True


def test_filter_misattributed_filings_drops_investegate_resolved_vct_trust():
    rows = [
        {
            "id": "noise",
            "source": "investegate_resolved",
            "headline": 'Foresight 4 VCT PLC (the "Company") - Investegate',
            "url": "https://www.investegate.co.uk/announcement/rns/foresight-enterprise-vct--ftf/x/6610520",
        },
        {
            "id": "good_direct",
            "source": "investegate_direct",
            "headline": "Annual Financial Report",
            "url": "https://www.investegate.co.uk/announcement/rns/victrex--vct/annual/1",
        },
        {
            "id": "good_resolved",
            "source": "investegate_resolved",
            "headline": "Victrex plc Trading Statement - Investegate",
            "url": "https://www.investegate.co.uk/announcement/rns/victrex--vct/trading/2",
        },
    ]
    filtered = filter_misattributed_filings(
        rows,
        company_name="Victrex plc",
        ticker="VCT.L",
        regime="uk_rns",
    )
    assert [row["id"] for row in filtered] == ["good_direct", "good_resolved"]


def test_refetch_investegate_prunes_vct_trust_noise_for_vct_l(tmp_path, monkeypatch):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    index = {
        "filings": [
            {
                "id": "vct_noise",
                "source": "investegate_resolved",
                "headline": 'Foresight 4 VCT PLC (the "Company") - Investegate',
                "url": "https://www.investegate.co.uk/announcement/rns/foresight-enterprise-vct--ftf/x/6610520",
                "has_body": False,
            },
            {
                "id": "ch_gap",
                "source": "companies_house",
                "headline": "Companies House accounts — group",
                "url": "https://document-api.company-information.service.gov.uk/document/ch1",
                "document_metadata_url": "https://document-api.company-information.service.gov.uk/document/ch1",
                "has_body": False,
            },
        ]
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.research.filings.enrich_filing_rows",
        lambda rows, **kwargs: list(rows),
    )
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda url: None,
    )
    result = refetch_investegate_filing_bodies(
        filings_dir,
        ticker="VCT.L",
        company_name="Victrex plc",
        max_bodies=5,
    )
    assert result["misattributed_pruned"] == 1
    assert result["attempted"] == 0
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert [row["id"] for row in saved["filings"]] == ["ch_gap"]


def test_sanitize_filings_index_prunes_vct_l_vct_trust_rows(tmp_path):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    index = {
        "filings": [
            {
                "id": "vct_noise",
                "source": "investegate_resolved",
                "headline": "ProVen VCT plc: Annual Financial Report - Investegate",
                "has_body": False,
            },
            {
                "id": "victrex",
                "source": "investegate_direct",
                "headline": "Annual Financial Report",
                "has_body": True,
                "body_path": str(filings_dir / "bodies" / "victrex.txt"),
            },
        ]
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    bodies_dir = filings_dir / "bodies"
    bodies_dir.mkdir()
    (bodies_dir / "victrex.txt").write_text(
        "Victrex plc annual results " + ("x" * 300), encoding="utf-8"
    )
    result = sanitize_filings_index(
        filings_dir,
        company_name="Victrex plc",
        ticker="VCT.L",
    )
    assert result["pruned"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert [row["id"] for row in saved["filings"]] == ["victrex"]


def test_asx_markit_file_url():
    key = "2924-03107929-2A1682457"
    assert asx_markit_file_url(key).endswith(f"/file/{key}")


@patch("value_investor.research.filings._http_get")
def test_fetch_filings_asx_direct_accepts_bsl_style_results_without_issuer_tokens(mock_get):
    """Markit symbol-scoped rows without issuer tokens still index FY results packs."""
    payload = {
        "data": {
            "items": [
                {
                    "announcementType": "PERIODIC REPORTS",
                    "date": "2026-08-16T08:00:00.000Z",
                    "documentKey": "2924-03121440-3A698870",
                    "headline": "FY2026 Results Presentation",
                },
                {
                    "announcementType": "OTHER",
                    "date": "2026-09-04T08:00:00.000Z",
                    "documentKey": "2924-03132082-PS-6A1342316",
                    "headline": "S&P DJI Announces September 2026 Quarterly Rebalance",
                },
            ]
        }
    }
    mock_get.return_value = json.dumps(payload).encode("utf-8")
    rows = fetch_filings_asx_direct(company_name="BlueScope Steel Limited", ticker="BSL.AX")
    assert len(rows) == 1
    assert rows[0]["period"] == "annual"
    assert rows[0]["headline"] == "FY2026 Results Presentation"


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


@patch("value_investor.research.filings._http_get")
def test_fetch_filings_esef_direct_parses_xbrl_api(mock_get):
    entity_payload = {
        "data": [
            {
                "attributes": {
                    "name": "SAP SE",
                    "identifier": "529900D6BF99LW9R2E68",
                }
            }
        ]
    }
    filings_payload = {
        "data": [
            {
                "attributes": {
                    "period_end": "2024-12-31",
                    "report_url": "/529900/example/reports/sap-2024.xhtml",
                }
            }
        ]
    }

    def _fake_get(url: str, **kwargs):
        if "/entities?" in url:
            return json.dumps(entity_payload).encode("utf-8")
        return json.dumps(filings_payload).encode("utf-8")

    mock_get.side_effect = _fake_get
    rows = fetch_filings_esef_direct(company_name="SAP SE", ticker="SAP.DE")
    assert len(rows) == 1
    assert rows[0]["source"] == "esef_direct"
    assert rows[0]["url"].endswith("sap-2024.xhtml")
    assert rows[0]["period"] == "annual"


def test_resolve_sec_cik_euro_depth_dual_listed_aliases():
    assert resolve_sec_cik("SHELL") == resolve_sec_cik("SHEL")
    assert resolve_sec_cik("NOVN") == resolve_sec_cik("NVS")
    assert resolve_sec_cik("LOGN") == resolve_sec_cik("LOGI")


def test_sec_edgar_supplement_allowed_euro_depth_representatives():
    assert _sec_edgar_supplement_allowed("SHELL.AS", "Shell plc") is True
    assert _sec_edgar_supplement_allowed("NOVN.SW", "Novartis AG") is True
    assert _sec_edgar_supplement_allowed("ABI.BR", "Anheuser-Busch InBev SA/NV") is True
    assert _sec_edgar_supplement_allowed("LOGN.SW", "Logitech International SA") is True
    assert _sec_edgar_supplement_allowed("C5H.IR", "CRH plc") is True
    assert _sec_edgar_supplement_allowed("C5H.IR", "Cairn Homes plc") is False


def test_fetch_filings_ir_allowlist_shell_as_inherits_shel_l(tmp_path: Path):
    allowlist_path = tmp_path / "ir.json"
    allowlist_path.write_text(json.dumps({"urls": {}}), encoding="utf-8")

    rows = fetch_filings_ir_allowlist("SHELL.AS", path=allowlist_path)
    assert rows
    assert all(row["source"] == "ir_allowlist" for row in rows)
    assert any("sec.gov" in row["url"] for row in rows)


def test_fetch_filings_ir_allowlist_euro_depth_belgian_builtins(tmp_path: Path):
    allowlist_path = tmp_path / "ir.json"
    allowlist_path.write_text(json.dumps({"urls": {}}), encoding="utf-8")

    for ticker in ("ACKB.BR", "UMI.BR", "MELE.BR"):
        rows = fetch_filings_ir_allowlist(ticker, path=allowlist_path)
        assert rows, ticker
        assert all(row["source"] == "ir_allowlist" for row in rows)


def test_fetch_filings_ir_allowlist_euro_depth_aed_br_builtins(tmp_path: Path):
    """Regression: AED.BR unmeasured when ESEF/news miss — IR allowlist seeds indexes."""
    allowlist_path = tmp_path / "ir.json"
    allowlist_path.write_text(json.dumps({"urls": {}}), encoding="utf-8")

    rows = fetch_filings_ir_allowlist("AED.BR", path=allowlist_path)
    assert rows
    assert all(row["source"] == "ir_allowlist" for row in rows)
    assert any("aedifica.eu" in row["url"] for row in rows)
    assert any("annual" in row["period"] for row in rows)


def test_fetch_filings_ir_allowlist_euro_depth_assa_b_st_builtins(tmp_path: Path):
    """Regression: ASSA-B.ST zero-body — English IR PDF alongside Swedish ESEF."""
    allowlist_path = tmp_path / "ir.json"
    allowlist_path.write_text(json.dumps({"urls": {}}), encoding="utf-8")

    rows = fetch_filings_ir_allowlist("ASSA-B.ST", path=allowlist_path)
    assert rows
    assert all(row["source"] == "ir_allowlist" for row in rows)
    assert any("assaabloy.com" in row["url"] for row in rows)


def test_esef_entity_variants_include_aedifica_and_assa_abloy():
    from value_investor.research.filings import _esef_entity_name_variants

    aed = _esef_entity_name_variants("Aedifica NV/SA", ticker="AED.BR")
    assert any("Aedifica" in v for v in aed)
    assa = _esef_entity_name_variants("ASSA ABLOY AB (publ)", ticker="ASSA-B.ST")
    assert any("ASSA ABLOY" in v for v in assa)


@patch("value_investor.research.filings._http_get")
def test_fetch_filing_body_treats_pdf_query_string_as_pdf(mock_get):
    """Regression: IR PDFs with ?VersionId= must not be parsed as HTML."""
    mock_get.return_value = b"%PDF-1.4 fake pdf body " + (b"x" * 400)
    url = (
        "https://www.randstad.com/s3fs-media/rscom/public/2026-02/"
        "Randstad_Annual_Report_2025_F.pdf?VersionId=abc123"
    )
    with patch(
        "value_investor.research.filings._extract_filing_document_text",
        return_value="Randstad consolidated income statement " + ("x" * 400),
    ) as mock_extract:
        body = fetch_filing_body(url)
    assert body
    mock_extract.assert_called_once()
    assert mock_extract.call_args[0][1] == "application/pdf"


def test_fetch_filings_ir_allowlist_euro_depth_periphery_builtins(tmp_path: Path):
    """Regression: STOXX/periphery names with no ESEF/news hits carry IR allowlist rows."""
    allowlist_path = tmp_path / "ir.json"
    allowlist_path.write_text(json.dumps({"urls": {}}), encoding="utf-8")

    cases = {
        "VOE.VI": "voestalpine.com",
        "BAS.DE": "report.basf.com",
        "ESSITY-B.ST": "essity.com",
        "VIG.VI": "group.vig",
        "APAM.AS": "aperam.com",
        "POST.VI": "post.at",
        "OMV.VI": "reports.omv.com",
        "NVG.LS": "thenavigatorcompany.com",
        "DQ7A.IR": "dcc.ie",
        "NBA.LS": "novabase.com",
        "MUV2.DE": "munichre.com",
        "DOC.VI": "doco.com",
        "STR.VI": "strabag.com",
        "VOLV-B.ST": "volvogroup.com",
        "GVR.IR": "glenveagh.ie",
        "PHIA.AS": "philips.com",
        "HEIA.AS": "theheinekencompany.com",
        "UCB.BR": "ucb.com",
        "TTE.PA": "totalenergies.com",
        "ABI.BR": "sec.gov/Archives/edgar/data/1668717",
    }
    for ticker, host_fragment in cases.items():
        rows = fetch_filings_ir_allowlist(ticker, path=allowlist_path)
        assert rows, ticker
        assert all(row["source"] == "ir_allowlist" for row in rows)
        assert any(host_fragment in row["url"] for row in rows), ticker


@patch("value_investor.research.filings._fetch_filings_investegate_company_for_epic")
def test_fetch_filings_investegate_c5h_ir_resolves_via_crn_epic(mock_fetch):
    mock_fetch.side_effect = lambda *, epic, max_items: (
        [
            {
                "id": "ig_crn_annual",
                "source": "investegate_direct",
                "headline": "Cairn Homes Plc: Annual Report and Notice of Annual General Meeting",
                "published_at": "2026-03-30T00:00:00+00:00",
                "url": "https://www.investegate.co.uk/announcement/eqs/cairn-homes-cdi---crn/annual-report/1",
                "period": "annual",
            }
        ]
        if epic == "CRN"
        else []
    )
    rows = fetch_filings_investegate_company(ticker="C5H.IR", company_name="Cairn Homes plc")
    assert len(rows) == 1
    assert mock_fetch.call_args_list[-1].kwargs["epic"] == "CRN"


@patch("value_investor.research.filings._http_get")
def test_esef_entity_search_skf_ab_resolves_via_group_alias(mock_get):
    entity_payload = {
        "data": [{"attributes": {"identifier": "894500JU9WRAJQOVBI12", "name": "SKF Group"}}]
    }
    filings_payload = {
        "data": [
            {
                "attributes": {
                    "period_end": "2025-12-31",
                    "report_url": "/894500JU9WRAJQOVBI12/reports/skf-2025.xhtml",
                }
            }
        ]
    }

    def _fake_get(url: str, **kwargs):
        if "/entities?" in url:
            return json.dumps(entity_payload).encode("utf-8")
        return json.dumps(filings_payload).encode("utf-8")

    mock_get.side_effect = _fake_get
    rows = fetch_filings_esef_direct(company_name="SKF AB", ticker="SKF-B.ST")
    assert len(rows) == 1
    assert rows[0]["source"] == "esef_direct"
    assert any("/entities?" in str(args[0]) for args, _kwargs in mock_get.call_args_list if args)


def test_esef_entity_variants_include_periphery_aliases_and_strip_bv():
    from value_investor.research.filings import (
        _esef_country_hint,
        _esef_entity_name_variants,
    )

    assert _esef_country_hint("PHIA.AS") == "NL"
    assert _esef_country_hint("ANDR.VI") == "AT"
    variants = _esef_entity_name_variants("Koninklijke Philips N.V.", ticker="PHIA.AS")
    assert any("Philips" in v for v in variants)
    stripped = _esef_entity_name_variants("Randstad N.V.", ticker="RAND.AS")
    assert any(v == "Randstad" for v in stripped)


@patch("value_investor.research.filings._http_get")
def test_esef_entity_search_retries_without_country_filter(mock_get):
    empty = {"data": []}
    entity_payload = {
        "data": [{"attributes": {"identifier": "529900D6BF99LW9R2E68", "name": "SAP SE"}}]
    }
    filings_payload = {
        "data": [
            {
                "attributes": {
                    "period_end": "2024-12-31",
                    "report_url": "/529900/example/reports/sap-2024.xhtml",
                }
            }
        ]
    }
    calls: list[str] = []

    def _fake_get(url: str, **kwargs):
        calls.append(url)
        if "/entities?" in url and "filter%5Bcountry%5D" in url:
            return json.dumps(empty).encode("utf-8")
        if "/entities?" in url:
            return json.dumps(entity_payload).encode("utf-8")
        return json.dumps(filings_payload).encode("utf-8")

    mock_get.side_effect = _fake_get
    rows = fetch_filings_esef_direct(company_name="SAP SE", ticker="SAP.DE")
    assert len(rows) == 1
    assert any("filter%5Bcountry%5D" in u for u in calls)
    assert any("/entities?" in u and "filter%5Bcountry%5D" not in u for u in calls)


@patch("value_investor.research.filings._http_get")
def test_esef_entity_search_retries_without_country_on_http_400(mock_get):
    """Regression: filings.xbrl.org no longer accepts filter[country] (HTTP 400)."""
    import urllib.error

    entity_payload = {
        "data": [
            {
                "attributes": {
                    "identifier": "7245009EAAUUQJ0U4T57",
                    "name": "Randstad N.V.",
                }
            }
        ]
    }
    filings_payload = {
        "data": [
            {
                "attributes": {
                    "period_end": "2025-12-31",
                    "report_url": "/7245009EAAUUQJ0U4T57/2025/reports/rand-2025.xhtml",
                }
            }
        ]
    }
    calls: list[str] = []

    def _fake_get(url: str, **kwargs):
        calls.append(url)
        if "/entities?" in url and "filter%5Bcountry%5D" in url:
            raise urllib.error.HTTPError(url, 400, "BAD REQUEST", {}, None)
        if "/entities?" in url:
            return json.dumps(entity_payload).encode("utf-8")
        return json.dumps(filings_payload).encode("utf-8")

    mock_get.side_effect = _fake_get
    rows = fetch_filings_esef_direct(company_name="Randstad N.V.", ticker="RAND.AS")
    assert len(rows) == 1
    assert rows[0]["source"] == "esef_direct"
    assert any("filter%5Bcountry%5D" in u for u in calls)
    assert any("/entities?" in u and "filter%5Bcountry%5D" not in u for u in calls)


def test_fetch_filings_ir_allowlist_rand_as_builtins(tmp_path: Path):
    """Regression: RAND.AS unmeasured when ESEF/news miss — IR allowlist seeds bodies."""
    allowlist_path = tmp_path / "ir.json"
    allowlist_path.write_text(json.dumps({"urls": {}}), encoding="utf-8")

    rows = fetch_filings_ir_allowlist("RAND.AS", path=allowlist_path)
    assert rows
    assert all(row["source"] == "ir_allowlist" for row in rows)
    assert any("randstad.com" in row["url"] for row in rows)


def test_sec_edgar_supplement_rejects_rand_as_homonym():
    """RAND.AS must not pull Rand Capital Corp SEC filings (CIK homonym on RAND)."""
    assert _sec_edgar_supplement_allowed("RAND.AS", "Randstad N.V.") is False


@patch("value_investor.research.filings.fetch_filings_euro_news", return_value=[])
@patch("value_investor.research.filings.fetch_filings_investegate_company", return_value=[])
@patch("value_investor.research.filings.fetch_filing_body", return_value=None)
@patch("value_investor.research.filings.fetch_filings_esef_direct")
@patch("value_investor.research.filings.fetch_filings_ir_allowlist")
def test_ingest_filings_euro_depth_rand_as_indexes_esef_and_ir(
    mock_ir,
    mock_esef,
    _mock_body,
    _mock_investegate,
    _mock_news,
    tmp_path: Path,
):
    mock_esef.return_value = [
        {
            "id": "esefrand2025",
            "source": "esef_direct",
            "headline": "ESEF report period end 2025-12-31",
            "published_at": "2025-12-31T00:00:00+00:00",
            "url": "https://filings.xbrl.org/7245009EAAUUQJ0U4T57/2025/reports/rand-2025.xhtml",
            "period": "annual",
            "has_body": False,
        }
    ]
    mock_ir.return_value = [
        {
            "id": "irrand2025",
            "source": "ir_allowlist",
            "headline": "Randstad annual report 2025 (PDF)",
            "published_at": None,
            "url": "https://www.randstad.com/s3fs-media/rscom/public/2026-02/Randstad_Annual_Report_2025_F.pdf",
            "period": "annual",
            "has_body": False,
        }
    ]
    meta = ingest_filings(
        ticker="RAND.AS",
        company_name="Randstad N.V.",
        sources_dir=tmp_path,
        market="euro_depth",
    )
    summary = meta.get("filings_summary") or {}
    assert int(summary.get("total") or 0) > 0
    index = json.loads(Path(meta["filings_index_path"]).read_text(encoding="utf-8"))
    assert "esef_direct" in index["sources_used"]
    assert "ir_allowlist" in index["sources_used"]
    assert "sec_edgar" not in index["sources_used"]


@patch("value_investor.research.filings.fetch_filings_euro_news", return_value=[])
@patch("value_investor.research.filings.fetch_filings_investegate_company", return_value=[])
@patch("value_investor.research.filings.fetch_filings_esef_direct", return_value=[])
@patch("value_investor.research.filings.fetch_filing_body", return_value=None)
@patch("value_investor.research.filings.fetch_filings_ir_allowlist")
def test_ingest_filings_euro_depth_aed_br_indexes_ir_allowlist(
    mock_ir,
    _mock_body,
    _mock_esef,
    _mock_investegate,
    _mock_news,
    tmp_path: Path,
):
    mock_ir.return_value = [
        {
            "id": "iraed2025",
            "source": "ir_allowlist",
            "headline": "Aedifica 2025 annual report (PDF)",
            "published_at": None,
            "url": "https://aedifica.eu/wp-content/uploads/2026/03/AEDIFICA-RA25_EN_2026-03-24b.pdf",
            "period": "annual",
            "has_body": False,
        }
    ]
    meta = ingest_filings(
        ticker="AED.BR",
        company_name="Aedifica NV/SA",
        sources_dir=tmp_path,
        market="euro_depth",
    )
    summary = meta.get("filings_summary") or {}
    assert int(summary.get("total") or 0) > 0
    index = json.loads(Path(meta["filings_index_path"]).read_text(encoding="utf-8"))
    assert "ir_allowlist" in index["sources_used"]


@patch("value_investor.research.filings.fetch_filings_euro_news", return_value=[])
@patch("value_investor.research.filings.fetch_filings_investegate_company", return_value=[])
@patch("value_investor.research.filings.fetch_filing_body", return_value=None)
@patch("value_investor.research.filings.fetch_filings_esef_direct")
@patch("value_investor.research.filings.fetch_filings_ir_allowlist")
def test_ingest_filings_euro_depth_assa_b_st_indexes_esef_and_ir(
    mock_ir,
    mock_esef,
    _mock_body,
    _mock_investegate,
    _mock_news,
    tmp_path: Path,
):
    mock_esef.return_value = [
        {
            "id": "esefassa2024",
            "source": "esef_direct",
            "headline": "ESEF report period end 2024-12-31",
            "published_at": "2024-12-31T00:00:00+00:00",
            "url": "https://filings.xbrl.org/549300YECS8HKCIMMB67/2024-12-31/ESEF/SE/1/ASSAABLOY-2024-12-31-0-sv/reports/ASSAABLOY-2024-12-31-0-sv.xhtml",
            "period": "annual",
            "has_body": False,
        }
    ]
    mock_ir.return_value = [
        {
            "id": "irassa2025",
            "source": "ir_allowlist",
            "headline": "ASSA ABLOY Annual Report 2025 (PDF)",
            "published_at": None,
            "url": "https://www.assaabloy.com/group/en/documents/investors/annual-reports/2025/Annual%20Report%202025.pdf",
            "period": "annual",
            "has_body": False,
        }
    ]
    meta = ingest_filings(
        ticker="ASSA-B.ST",
        company_name="ASSA ABLOY AB (publ)",
        sources_dir=tmp_path,
        market="euro_depth",
    )
    summary = meta.get("filings_summary") or {}
    assert int(summary.get("total") or 0) > 0
    index = json.loads(Path(meta["filings_index_path"]).read_text(encoding="utf-8"))
    assert "esef_direct" in index["sources_used"]
    assert "ir_allowlist" in index["sources_used"]


@patch("value_investor.research.filings.fetch_filings_euro_news", return_value=[])
@patch("value_investor.research.filings.fetch_filings_esef_direct", return_value=[])
@patch("value_investor.research.filings.fetch_filings_investegate_company", return_value=[])
@patch("value_investor.research.filings.fetch_filings_sec_edgar")
def test_ingest_filings_euro_depth_shell_as_indexes_sec_and_ir(
    mock_sec,
    _mock_investegate,
    _mock_esef,
    _mock_news,
    tmp_path: Path,
):
    mock_sec.return_value = [
        {
            "id": "sec1",
            "source": "sec_edgar",
            "headline": "20-F",
            "url": "https://www.sec.gov/Archives/edgar/data/1306965/000162828026017024/shel-20251231.htm",
            "period": "annual",
            "has_body": False,
        }
    ]
    meta = ingest_filings(
        ticker="SHELL.AS",
        company_name="Shell plc",
        sources_dir=tmp_path,
        market="euro_depth",
        deepen_history=False,
    )
    summary = meta.get("filings_summary") or {}
    assert int(summary.get("total") or 0) > 0
    mock_sec.assert_called_once()
    assert mock_sec.call_args.kwargs["ticker"] == "SHELL"


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
    mock_euro_news.return_value = [
        {"id": "gn1", "source": "google_news_euro", "headline": "Results"}
    ]
    mock_investegate.return_value = [
        {"id": "ig1", "source": "investegate_direct", "headline": "Annual"}
    ]
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
                    "CUSTOM.L": [
                        "https://example.com/custom-trading-update-vfinal.pdf",
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

    result = merge_ir_allowlist_filings("CUSTOM.L", filings_dir, path=allowlist_path)
    assert result["added"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert len(saved["filings"]) == 1
    assert saved["filings"][0]["source"] == "ir_allowlist"
    assert saved["filings"][0]["id"].startswith("ir_")


def test_refetch_ir_allowlist_filing_bodies_retries_failed_fetch(tmp_path: Path, monkeypatch):
    allowlist_path = tmp_path / "ir_urls.json"
    url = "https://example.com/custom-trading-update-vfinal.pdf"
    allowlist_path.write_text(json.dumps({"urls": {"CUSTOM.L": [url]}}), encoding="utf-8")
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    digest = "553f48faa4590e00"
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
        return (
            "Trading update revenue growth 2% to 4% and operating profit "
            "in the range of $720 million with dividend guidance." + ("x" * 220)
        )

    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        fake_fetch,
    )
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filings_investegate_company",
        lambda **kwargs: [],
    )

    result = refetch_ir_allowlist_filing_bodies(
        filings_dir,
        "CUSTOM.L",
        max_bodies=5,
        max_retries=2,
        allowlist_path=allowlist_path,
    )
    assert result["attempted"] == 1
    assert result["fetched"] == 1
    assert result["retries_used"] == 1
    assert attempts["count"] == 2
    assert any(entry["outcome"] == "retry" for entry in result.get("retry_log") or [])
    assert any(entry["outcome"] == "fetched_pdf" for entry in result.get("retry_log") or [])
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert saved["filings"][0]["has_body"] is True
    assert (filings_dir / "bodies" / f"ir_{digest}.txt").exists()


def test_refetch_ir_allowlist_marks_failed_rows_unfetchable_and_skips(tmp_path: Path, monkeypatch):
    allowlist_path = tmp_path / "ir_urls.json"
    url = "https://example.com/dead-ir.pdf"
    allowlist_path.write_text(json.dumps({"urls": {"SLOW.PA": [url]}}), encoding="utf-8")
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    digest = __import__("hashlib").sha256(url.encode("utf-8")).hexdigest()[:16]
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

    def fake_fetch(_url):
        attempts["count"] += 1
        return None

    monkeypatch.setattr("value_investor.research.filings.fetch_filing_body", fake_fetch)
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filings_investegate_company",
        lambda **kwargs: [],
    )
    first = refetch_ir_allowlist_filing_bodies(
        filings_dir,
        "SLOW.PA",
        max_bodies=5,
        max_retries=1,
        allowlist_path=allowlist_path,
    )
    assert first["failed"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert saved["filings"][0]["unfetchable"] is True
    after_first = attempts["count"]
    second = refetch_ir_allowlist_filing_bodies(
        filings_dir,
        "SLOW.PA",
        max_bodies=5,
        max_retries=1,
        allowlist_path=allowlist_path,
    )
    assert second["attempted"] == 0
    assert second["skipped_unfetchable"] >= 1
    assert attempts["count"] == after_first


def test_refetch_ir_allowlist_marks_removed_row_unfetchable_even_with_body(tmp_path: Path):
    stale = "https://www.bmv.com.mx/docs-pub/10-k/wrong-issuer.pdf"
    fresh = "https://www.sec.gov/Archives/edgar/data/1668717/000119312526088105/d65314d20f.htm"
    allowlist_path = tmp_path / "ir_urls.json"
    allowlist_path.write_text(json.dumps({"urls": {"FAKE.BR": [fresh]}}), encoding="utf-8")
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    (filings_dir / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "id": "ir_stale_bmv",
                        "source": "ir_allowlist",
                        "headline": "Wrong issuer 10-K",
                        "url": stale,
                        "period": "annual",
                        "has_body": True,
                        "body_path": "bodies/ir_stale_bmv.txt",
                        "priority": 80,
                    },
                    {
                        "id": "ir_fresh_20f",
                        "source": "ir_allowlist",
                        "headline": "20-F",
                        "url": fresh,
                        "period": "annual",
                        "has_body": True,
                        "body_path": "bodies/ir_fresh_20f.txt",
                        "priority": 130,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    result = refetch_ir_allowlist_filing_bodies(
        filings_dir,
        "FAKE.BR",
        max_bodies=5,
        allowlist_path=allowlist_path,
    )
    assert result["attempted"] == 0
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    stale_row = next(row for row in saved["filings"] if row["url"] == stale)
    assert stale_row["unfetchable"] is True
    assert stale_row["unfetchable_reason"] == "allowlist_removed"
    assert stale_row["has_body"] is True


def test_refetch_residual_stops_at_deadline(tmp_path: Path, monkeypatch):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    index = {
        "ticker": "ABI.BR",
        "company_name": "Anheuser-Busch InBev SA/NV",
        "filings": [
            {
                "id": "sec1",
                "source": "sec_edgar",
                "headline": "6-K: 6-K",
                "published_at": "2026-07-30T00:00:00+00:00",
                "url": "https://www.sec.gov/Archives/edgar/data/1668717/000119312526326285/d175040d6k.htm",
                "period": "interim",
                "has_body": False,
                "body_path": None,
                "priority": 80,
            }
        ],
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.research.filings.enrich_filing_rows",
        lambda filings, **kwargs: list(filings),
    )

    def _boom(_url):
        raise AssertionError("deadline should skip residual fetch")

    monkeypatch.setattr("value_investor.research.filings.fetch_filing_body", _boom)
    result = refetch_residual_filing_bodies(
        filings_dir,
        ticker="ABI.BR",
        company_name="Anheuser-Busch InBev SA/NV",
        max_bodies=4,
        deadline_monotonic=0.0,
    )
    assert result["deadline_hit"] is True
    assert result["attempted"] == 0
    assert result["fetched"] == 0


def test_refetch_ir_allowlist_stops_at_deadline(tmp_path: Path, monkeypatch):
    allowlist_path = tmp_path / "ir_urls.json"
    url = "https://example.com/slow-ir.pdf"
    allowlist_path.write_text(json.dumps({"urls": {"SLOW.PA": [url]}}), encoding="utf-8")
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    (filings_dir / "filings_index.json").write_text(
        json.dumps({"filings": []}),
        encoding="utf-8",
    )
    merge_ir_allowlist_filings("SLOW.PA", filings_dir, path=allowlist_path)
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda _url: None,
    )
    result = refetch_ir_allowlist_filing_bodies(
        filings_dir,
        "SLOW.PA",
        max_bodies=5,
        max_retries=2,
        allowlist_path=allowlist_path,
        deadline_monotonic=0.0,
    )
    assert result["deadline_hit"] is True
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert not saved["filings"][0].get("unfetchable")


def test_dg_pa_ir_allowlist_uses_vinci_pdfs_not_globenewswire_html():
    rows = fetch_filings_ir_allowlist("DG.PA")
    urls = [row["url"] for row in rows]
    assert urls
    assert all("vinci.com" in url for url in urls)
    assert all("globenewswire.com/news-release" not in url for url in urls)
    assert any("2025-vinci-consolidated-financial-statements" in url for url in urls)


def test_abi_br_ir_allowlist_uses_sec_ab_inbev_not_bmv():
    rows = fetch_filings_ir_allowlist("ABI.BR")
    urls = [row["url"] for row in rows]
    assert urls
    assert all("sec.gov/Archives/edgar/data/1668717" in url for url in urls)
    assert all("bmv.com.mx" not in url for url in urls)
    assert any("d65314d20f.htm" in url for url in urls)
    assert any("d142827dex991.htm" in url for url in urls)
    builtins = _BUILTIN_IR_URLS["ABI.BR"]
    assert all("bmv.com.mx" not in url for url in builtins)


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
        "ITV Studios segment revenue £2,130m for FY2025. Studios margin 13-15%. "
        "Dividend policy 5.0p per share. Pro-forma cash flow bridge." + ("x" * 220)
    )
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda url: sample_body if url == fy_url else None,
    )
    monkeypatch.setattr(
        "value_investor.research.filings._fetch_ir_pdf_alternate_candidates",
        lambda _url: [],
    )
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filings_investegate_company",
        lambda **kwargs: [],
    )

    result = refetch_ir_allowlist_filing_bodies(
        filings_dir,
        "ITV.L",
        company_name="ITV plc",
        max_bodies=5,
        allowlist_path=allowlist_path,
    )
    assert result["fetched"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert saved["filings"][0]["has_body"] is True
    body_text = (filings_dir / "bodies" / f"ir_{digest}.txt").read_text(encoding="utf-8")
    assert "Studios margin" in body_text
    assert "Dividend policy" in body_text


def test_fetch_ir_allowlist_body_rejects_short_pdf(monkeypatch):
    url = "https://www.hikma.com/media/1u2besjf/april-2026-trading-update-vfinal.pdf"
    row = {
        "id": "ir_a9733d0de6aec27d",
        "source": "ir_allowlist",
        "headline": "IR allowlist document — april-2026-trading-update-vfinal.pdf",
        "url": url,
        "period": "trading_update",
    }
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda _url: "too short",
    )
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filings_investegate_company",
        lambda **kwargs: [],
    )

    body, source = _fetch_ir_allowlist_body(
        row,
        ticker="HIK.L",
        company_name="Hikma Pharmaceuticals PLC",
        investegate_cache=[],
    )
    assert body is None
    assert source is None


def test_fetch_ir_allowlist_body_investegate_fallback_hik_trading_update(monkeypatch):
    url = "https://www.hikma.com/media/1u2besjf/april-2026-trading-update-vfinal.pdf"
    investegate_url = (
        "https://www.investegate.co.uk/announcement/rns/hikma-pharmaceuticals--hik/"
        "trading-statement/9533700"
    )
    row = {
        "id": "ir_a9733d0de6aec27d",
        "source": "ir_allowlist",
        "headline": "IR allowlist document — april-2026-trading-update-vfinal.pdf",
        "url": url,
        "period": "trading_update",
    }
    investegate_rows = [
        {
            "source": "investegate_direct",
            "headline": "Trading Statement",
            "url": investegate_url,
            "period": "trading_update",
        }
    ]
    sample_html = (
        "Hikma reiterates full year 2026 guidance following encouraging start to the year. "
        "Group revenue to grow in the range of 2% to 4% and operating profit "
        "in the range of $720 million to $770 million. Dividend of 48 cents per share."
        + ("x" * 220)
    )

    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda _url: None,
    )
    monkeypatch.setattr(
        "value_investor.research.filings._fetch_investegate_html_body",
        lambda ig_url: sample_html if ig_url == investegate_url else None,
    )

    body, source = _fetch_ir_allowlist_body(
        row,
        ticker="HIK.L",
        company_name="Hikma Pharmaceuticals PLC",
        investegate_cache=investegate_rows,
    )
    assert source == "investegate_html"
    assert "720 million" in (body or "")
    assert _filing_text_is_substantive(body or "")


def test_validate_ir_allowlist_body_rejects_interim_for_trading_update():
    """April trading-update URL must not accept H1 interim HTML (HIK.L regression)."""
    url = "https://www.hikma.com/media/1u2besjf/april-2026-trading-update-vfinal.pdf"
    row = {
        "id": "ir_a9733d0de6aec27d",
        "source": "ir_allowlist",
        "headline": "IR allowlist document — april-2026-trading-update-vfinal.pdf",
        "url": url,
        "period": "trading_update",
    }
    interim_body = (
        "Hikma Pharmaceuticals PLC announces half year interim results for the six months "
        "ended 30 June 2025. Revenue increased 8% and interim dividend declared." + ("x" * 220)
    )
    valid, reason = _validate_ir_allowlist_body_content(row, interim_body)
    assert valid is False
    assert reason == "period_mismatch"

    trading_body = (
        "Hikma reiterates full year 2026 guidance following an encouraging start to the year. "
        "Trading update: group revenue to grow 2% to 4% and operating profit "
        "in the range of $720 million to $770 million." + ("x" * 220)
    )
    valid, reason = _validate_ir_allowlist_body_content(row, trading_body)
    assert valid is True
    assert reason is None


def test_fetch_ir_allowlist_body_rejects_mismatched_investegate_fallback(monkeypatch):
    """Investegate HTML that fails period validation must not be accepted."""
    url = "https://www.hikma.com/media/1u2besjf/april-2026-trading-update-vfinal.pdf"
    investegate_url = (
        "https://www.investegate.co.uk/announcement/rns/hikma-pharmaceuticals--hik/"
        "interim-results/9533700"
    )
    row = {
        "id": "ir_a9733d0de6aec27d",
        "source": "ir_allowlist",
        "headline": "IR allowlist document — april-2026-trading-update-vfinal.pdf",
        "url": url,
        "period": "trading_update",
    }
    interim_html = (
        "Hikma Pharmaceuticals PLC half year interim results for six months ended June 2025. "
        "Revenue up 8% with interim dividend of 17 cents per share." + ("x" * 220)
    )
    investegate_rows = [
        {
            "headline": "Trading Statement",
            "url": investegate_url,
            "period": "trading_update",
        }
    ]

    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda _url: None,
    )
    monkeypatch.setattr(
        "value_investor.research.filings._fetch_ir_pdf_alternate_candidates",
        lambda _url: [],
    )
    monkeypatch.setattr(
        "value_investor.research.filings._fetch_investegate_html_body",
        lambda ig_url: interim_html if ig_url == investegate_url else None,
    )

    body, source = _fetch_ir_allowlist_body(
        row,
        ticker="HIK.L",
        company_name="Hikma Pharmaceuticals PLC",
        investegate_cache=investegate_rows,
    )
    assert body is None
    assert source is None


def test_fetch_ir_allowlist_body_alternate_pdf_parser_on_mismatch(monkeypatch):
    """When pypdf text fails validation, retry with alternate parser output."""
    url = "https://www.hikma.com/media/1u2besjf/april-2026-trading-update-vfinal.pdf"
    row = {
        "id": "ir_a9733d0de6aec27d",
        "source": "ir_allowlist",
        "headline": "IR allowlist document — april-2026-trading-update-vfinal.pdf",
        "url": url,
        "period": "trading_update",
    }
    bad_pdf = (
        "Hikma Pharmaceuticals PLC half year interim results for six months ended June 2025."
        + ("x" * 220)
    )
    good_pdf = (
        "Hikma trading update April 2026: group revenue growth 2% to 4% and operating profit "
        "guidance $720 million to $770 million." + ("x" * 220)
    )

    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda _url: bad_pdf,
    )
    monkeypatch.setattr(
        "value_investor.research.filings._fetch_ir_pdf_alternate_candidates",
        lambda _url: [(good_pdf, "pymupdf")],
    )
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filings_investegate_company",
        lambda **kwargs: [],
    )

    body, source = _fetch_ir_allowlist_body(
        row,
        ticker="HIK.L",
        company_name="Hikma Pharmaceuticals PLC",
    )
    assert source == "pdf_pymupdf"
    assert "trading update" in (body or "").lower()


def test_refetch_ir_allowlist_filing_bodies_stores_content_hash(tmp_path: Path, monkeypatch):
    allowlist_path = tmp_path / "ir_urls.json"
    url = "https://example.com/april-2026-trading-update-vfinal.pdf"
    allowlist_path.write_text(json.dumps({"urls": {"CUSTOM.L": [url]}}), encoding="utf-8")
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    digest = "269391cd9a247a83"
    (filings_dir / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "id": f"ir_{digest}",
                        "source": "ir_allowlist",
                        "headline": "IR allowlist document — april-2026-trading-update-vfinal.pdf",
                        "url": url,
                        "period": "trading_update",
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
        "Trading update April 2026: revenue growth 2% to 4% and operating profit "
        "in the range of $720 million." + ("x" * 220)
    )

    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda _url: sample_body,
    )
    monkeypatch.setattr(
        "value_investor.research.filings._fetch_ir_pdf_alternate_candidates",
        lambda _url: [],
    )
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filings_investegate_company",
        lambda **kwargs: [],
    )

    result = refetch_ir_allowlist_filing_bodies(
        filings_dir,
        "CUSTOM.L",
        max_bodies=5,
        allowlist_path=allowlist_path,
    )
    assert result["fetched"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    row = saved["filings"][0]
    assert row["has_body"] is True
    assert row["body_content_hash"] == _ir_body_content_hash(sample_body)


def test_match_ir_row_to_investegate_prefers_period_and_tokens():
    row = {
        "url": "https://www.hikma.com/media/1u2besjf/april-2026-trading-update-vfinal.pdf",
        "headline": "IR allowlist document — april-2026-trading-update-vfinal.pdf",
        "period": "trading_update",
    }
    candidates = [
        {
            "headline": "Full Year Results 2025",
            "url": "https://www.investegate.co.uk/announcement/rns/hik/fy/1",
            "period": "annual",
        },
        {
            "headline": "Trading Statement",
            "url": "https://www.investegate.co.uk/announcement/rns/hik/trading/1",
            "period": "trading_update",
        },
    ]
    matched = _match_ir_row_to_investegate(row, candidates)
    assert matched is not None
    assert matched["headline"] == "Trading Statement"


def test_refetch_ir_allowlist_filing_bodies_investegate_fallback(tmp_path: Path, monkeypatch):
    allowlist_path = tmp_path / "ir_urls.json"
    url = "https://example.com/april-2026-trading-update-vfinal.pdf"
    allowlist_path.write_text(json.dumps({"urls": {"CUSTOM.L": [url]}}), encoding="utf-8")
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    digest = "269391cd9a247a83"
    (filings_dir / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "id": f"ir_{digest}",
                        "source": "ir_allowlist",
                        "headline": "IR allowlist document — april-2026-trading-update-vfinal.pdf",
                        "url": url,
                        "period": "trading_update",
                        "has_body": False,
                        "body_path": None,
                        "priority": 130,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    investegate_url = (
        "https://www.investegate.co.uk/announcement/rns/custom-co--cus/trading-statement/9533700"
    )
    fallback_body = (
        "Trading update April 2026: Hikma reiterates full year 2026 guidance. "
        "Revenue growth 2% to 4%. Operating profit $720 million to $770 million." + ("x" * 220)
    )

    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filing_body",
        lambda _url: None,
    )
    monkeypatch.setattr(
        "value_investor.research.filings._fetch_ir_pdf_alternate_candidates",
        lambda _url: [],
    )
    monkeypatch.setattr(
        "value_investor.research.filings.fetch_filings_investegate_company",
        lambda **kwargs: [
            {
                "headline": "Trading Statement",
                "url": investegate_url,
                "period": "trading_update",
            }
        ],
    )
    monkeypatch.setattr(
        "value_investor.research.filings._fetch_investegate_html_body",
        lambda ig_url: fallback_body if ig_url == investegate_url else None,
    )

    result = refetch_ir_allowlist_filing_bodies(
        filings_dir,
        "CUSTOM.L",
        company_name="Custom Co PLC",
        max_bodies=5,
        allowlist_path=allowlist_path,
    )
    assert result["fetched"] == 1
    assert result["investegate_fallbacks"] == 1
    saved = json.loads((filings_dir / "filings_index.json").read_text(encoding="utf-8"))
    assert saved["filings"][0]["has_body"] is True
    assert (filings_dir / "bodies" / f"ir_{digest}.txt").exists()


def test_fetch_filings_ir_allowlist_hik_l_builtin(tmp_path: Path):
    """HIK.L trading-update and results PDFs ship in the built-in IR allowlist."""
    allowlist_path = tmp_path / "empty_ir.json"
    allowlist_path.write_text(json.dumps({"urls": {}}), encoding="utf-8")

    rows = fetch_filings_ir_allowlist("HIK.L", path=allowlist_path)
    urls = {row["url"] for row in rows}
    assert any("april-2026-trading-update-vfinal.pdf" in url for url in urls)
    assert any("annual-report" in url for url in urls)
    assert all(row["source"] == "ir_allowlist" for row in rows)


def test_fetch_filings_ir_allowlist_ebo_ax_builtin(tmp_path: Path):
    """EBO.AX annual/interim PDFs ship in the built-in IR allowlist (Markit + ASX)."""
    allowlist_path = tmp_path / "empty_ir.json"
    allowlist_path.write_text(json.dumps({"urls": {}}), encoding="utf-8")

    rows = fetch_filings_ir_allowlist("EBO.AX", path=allowlist_path)
    urls = {row["url"] for row in rows}
    assert any("2924-02984095-2A1616605" in url for url in urls)
    assert any("06nczkd8fndm9c.pdf" in url for url in urls)
    assert len(rows) >= 4
    assert all(row["source"] == "ir_allowlist" for row in rows)


def test_fetch_filings_ir_allowlist_asx200_unmeasured_builtin(tmp_path: Path):
    """CDA/BSL/PXA buy-tier IR PDFs ship in the built-in allowlist."""
    allowlist_path = tmp_path / "empty_ir.json"
    allowlist_path.write_text(json.dumps({"urls": {}}), encoding="utf-8")

    cda = fetch_filings_ir_allowlist("CDA.AX", path=allowlist_path)
    assert len(cda) >= 4
    assert any("Codan-Limited_Annual-Report_2025.pdf" in row["url"] for row in cda)
    assert any("H1-FY26" in row["url"] for row in cda)

    bsl = fetch_filings_ir_allowlist("BSL.AX", path=allowlist_path)
    assert len(bsl) >= 4
    assert any(
        "FY2026_BlueScope_Full_Year_Results_Investor_Presentation.pdf" in row["url"] for row in bsl
    )

    pxa = fetch_filings_ir_allowlist("PXA.AX", path=allowlist_path)
    assert len(pxa) >= 4
    assert any("Appendix-4D-and-half-year-report-FY26" in row["url"] for row in pxa)
    assert any(row["period"] == "annual" for row in pxa)
    assert all(row["source"] == "ir_allowlist" for row in cda + bsl + pxa)


@patch("value_investor.research.filings.fetch_filings_asx_news", return_value=[])
@patch("value_investor.research.filings.fetch_filings_asx_direct", return_value=[])
def test_ingest_filings_asx200_ebo_ax_indexes_ir_allowlist_bodies(
    _mock_asx_direct,
    _mock_asx_news,
    tmp_path: Path,
):
    """When Markit latest-five lacks results rows, EBO.AX still indexes IR allowlist filings."""
    meta = ingest_filings(
        ticker="EBO.AX",
        company_name="EBOS Group Limited",
        sources_dir=tmp_path,
        market="asx200",
    )
    assert meta["filings_regime"] == "asx_announcements"
    summary = meta.get("filings_summary") or {}
    assert summary.get("total", 0) >= 4
    index = json.loads(Path(meta["filings_index_path"]).read_text(encoding="utf-8"))
    assert "ir_allowlist" in index.get("sources_used", [])
    assert all(row["source"] == "ir_allowlist" for row in index.get("filings") or [])
    assert (tmp_path / "filings" / "filings_index.json").exists()


@patch("value_investor.research.filings.fetch_filings_asx_news", return_value=[])
@patch("value_investor.research.filings.fetch_filings_asx_direct", return_value=[])
def test_ingest_filings_asx200_cda_ax_indexes_ir_allowlist_bodies(
    _mock_asx_direct,
    _mock_asx_news,
    tmp_path: Path,
):
    """When Markit latest-five lacks results rows, CDA.AX still indexes IR allowlist filings."""
    meta = ingest_filings(
        ticker="CDA.AX",
        company_name="Codan Limited",
        sources_dir=tmp_path,
        market="asx200",
    )
    assert meta["filings_regime"] == "asx_announcements"
    summary = meta.get("filings_summary") or {}
    assert summary.get("total", 0) >= 4
    index = json.loads(Path(meta["filings_index_path"]).read_text(encoding="utf-8"))
    assert "ir_allowlist" in index.get("sources_used", [])
    assert all(row["source"] == "ir_allowlist" for row in index.get("filings") or [])


def test_load_ir_url_allowlist_merges_file_with_builtin(tmp_path: Path):
    """File allowlist URLs are merged with built-in IR URLs (not replaced)."""
    path = tmp_path / "ir.json"
    file_hik_urls = [
        "https://www.hikma.com/investors/annual-report-2024.pdf",
        "https://www.hikma.com/investors/interim-results.pdf",
    ]
    path.write_text(
        json.dumps(
            {
                "urls": {
                    "HIK.L": file_hik_urls,
                    "SHEL.L": [
                        "https://www.sec.gov/Archives/edgar/data/1306965/000162828026017024/shel-20251231.htm",
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    mapping = load_ir_url_allowlist(path)
    builtin_hik = _BUILTIN_IR_URLS.get("HIK.L") or []
    assert all(url in mapping["HIK.L"] for url in file_hik_urls)
    assert len(mapping["HIK.L"]) == len(file_hik_urls) + len(builtin_hik)

    rows = fetch_filings_ir_allowlist("HIK.L", path=path)
    assert len(rows) == len(mapping["HIK.L"])
    assert rows[0]["source"] == "ir_allowlist"
    assert rows[0]["url"] == file_hik_urls[0]
    assert rows[0]["period"] == "annual"
    assert rows[1]["url"] == file_hik_urls[1]
    assert rows[1]["period"] == "interim"
    shel = fetch_filings_ir_allowlist("SHEL.L", path=path)
    builtin_shel = _BUILTIN_IR_URLS.get("SHEL.L") or []
    assert len(mapping["SHEL.L"]) == len(builtin_shel)
    assert len(shel) == len(mapping["SHEL.L"])
    assert shel[0]["period"] == "annual"


def test_fetch_filings_ir_allowlist_gftu_l(tmp_path: Path):
    """GFTU.L IR results decks are allowlisted for segment and FCF gap-fill."""
    allowlist_path = tmp_path / "empty_ir.json"
    allowlist_path.write_text(json.dumps({"urls": {}}), encoding="utf-8")

    mapping = load_ir_url_allowlist(allowlist_path)
    assert "GFTU.L" in mapping
    assert len(mapping["GFTU.L"]) >= 4

    rows = fetch_filings_ir_allowlist("GFTU.L", path=allowlist_path)
    assert len(rows) >= 4
    assert all(row["source"] == "ir_allowlist" for row in rows)
    assert all("graftonplc.com" in row["url"] for row in rows)
    periods = {row["period"] for row in rows}
    assert "annual" in periods
    assert "trading_update" in periods


def test_fetch_filings_ir_allowlist_megp_l_includes_june_trading_update(tmp_path: Path):
    """MEGP.L allowlist includes June 2026 profit-warning trading update."""
    allowlist_path = tmp_path / "empty_ir.json"
    allowlist_path.write_text(json.dumps({"urls": {}}), encoding="utf-8")

    rows = fetch_filings_ir_allowlist("MEGP.L", path=allowlist_path)
    trading = [
        row
        for row in rows
        if row["period"] == "trading_update" and "260601-ME-Group-Trading-Update.pdf" in row["url"]
    ]
    assert trading
    presentation = [row for row in rows if "Annual-Results-Presentation.pdf" in row["url"]]
    assert presentation


def test_fetch_filings_ir_allowlist_fgp_l(tmp_path: Path):
    """FGP.L IR results decks are allowlisted for FCF bridge and forward guidance."""
    allowlist_path = tmp_path / "empty_ir.json"
    allowlist_path.write_text(json.dumps({"urls": {}}), encoding="utf-8")

    mapping = load_ir_url_allowlist(allowlist_path)
    assert "FGP.L" in mapping
    assert len(mapping["FGP.L"]) >= 2

    rows = fetch_filings_ir_allowlist("FGP.L", path=allowlist_path)
    assert len(rows) >= 2
    assert all(row["source"] == "ir_allowlist" for row in rows)
    assert all("firstgroupplc.com" in row["url"] for row in rows)


def test_fetch_filings_ir_allowlist_megp_l(tmp_path: Path):
    """MEGP.L IR results decks are allowlisted for cash-flow gap-fill."""
    allowlist_path = tmp_path / "empty_ir.json"
    allowlist_path.write_text(json.dumps({"urls": {}}), encoding="utf-8")

    mapping = load_ir_url_allowlist(allowlist_path)
    assert "MEGP.L" in mapping
    assert len(mapping["MEGP.L"]) >= 3

    rows = fetch_filings_ir_allowlist("MEGP.L", path=allowlist_path)
    assert len(rows) >= 3
    assert all(row["source"] == "ir_allowlist" for row in rows)
    assert all("me-group.com" in row["url"] for row in rows)


def test_parse_ir_cash_bridge_slides_megp_fixture():
    from value_investor.research.filings import parse_ir_cash_bridge_slides

    fixture = Path("docs/data/research/MEGP.L/sources/filings/bodies/ir_59ec4565fa7e453b.txt")
    if not fixture.is_file():
        pytest.skip("MEGP IR body fixture not present")
    parsed = parse_ir_cash_bridge_slides(fixture.read_text(encoding="utf-8"))
    assert parsed is not None
    assert parsed["bridge_type"] == "net_cash_bridge"
    by_label = {row["label"]: row["amount_millions"] for row in parsed["lines"]}
    assert by_label["opening_net_cash"] == 29.5
    assert by_label["closing_net_cash"] == 26.5
    assert by_label["operating_cash_flow"] == 115.5
    assert by_label["capex_infrastructure"] == -65.6
    assert by_label["dividends_paid"] == -29.8


def test_extract_ir_presentation_metrics_from_ir_body(tmp_path: Path):
    from value_investor.research.filings import extract_ir_presentation_metrics

    filings_dir = tmp_path / "filings"
    bodies_dir = filings_dir / "bodies"
    bodies_dir.mkdir(parents=True)
    body_id = "ir_59ec4565fa7e453b"
    fixture = Path("docs/data/research/MEGP.L/sources/filings/bodies/ir_59ec4565fa7e453b.txt")
    if not fixture.is_file():
        pytest.skip("MEGP IR body fixture not present")
    body_path = bodies_dir / f"{body_id}.txt"
    body_path.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    (filings_dir / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "id": body_id,
                        "source": "ir_allowlist",
                        "headline": "MEGP FY2025 results presentation",
                        "period": "annual",
                        "has_body": True,
                        "body_path": str(body_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    metrics = extract_ir_presentation_metrics(
        filings_dir,
        "MEGP.L",
        sources_dir=sources_dir,
    )
    assert metrics["bridge_count"] == 1
    assert (sources_dir / "ir_presentation_metrics.json").exists()
    bridge = metrics["bridges"][0]
    assert bridge["source_body_id"] == body_id
    labels = {row["label"] for row in bridge["lines"]}
    assert "operating_cash_flow" in labels
    assert "dividends_paid" in labels


def test_parse_ir_fcf_division_bridge_fgp_fixture():
    from value_investor.research.filings import parse_ir_fcf_division_bridge

    fixture = Path("docs/data/research/FGP.L/sources/filings/bodies/ir_af873270e9c4b29f.txt")
    if not fixture.is_file():
        pytest.skip("FGP IR body fixture not present")
    parsed = parse_ir_fcf_division_bridge(fixture.read_text(encoding="utf-8"))
    assert parsed is not None
    assert parsed["bridge_type"] == "fcf_by_division"
    by_label = {row["label"]: row["amount_millions"] for row in parsed["lines"]}
    assert by_label["total"] == -35.6
    assert by_label["first_bus"] == -44.6


def test_parse_ir_segment_revenue_splits_hik_fixture():
    from value_investor.research.filings import parse_ir_segment_revenue_splits

    fixture = Path("docs/data/research/HIK.L/sources/filings/bodies/ir_3a67962eb8770824.txt")
    if not fixture.is_file():
        pytest.skip("HIK IR body fixture not present")
    parsed = parse_ir_segment_revenue_splits(fixture.read_text(encoding="utf-8"))
    assert parsed is not None
    assert parsed["currency"] == "USD"
    segments = {row["segment"]: row for row in parsed["segments"]}
    assert segments["Injectables"]["revenue_current"] == 1423.0
    assert segments["Branded"]["revenue_current"] == 849.0


def test_parse_ir_ifrs16_lease_maturity_megp_fixture():
    from value_investor.research.filings import parse_ir_ifrs16_lease_maturity

    fixture = Path("docs/data/research/MEGP.L/sources/filings/bodies/ir_55af4b8f27e3dd6f.txt")
    if not fixture.is_file():
        pytest.skip("MEGP annual report IR body fixture not present")
    parsed = parse_ir_ifrs16_lease_maturity(fixture.read_text(encoding="utf-8"))
    assert parsed is not None
    assert parsed["table_type"] == "ifrs16_lease_maturity"
    buckets = {row["bucket"]: row["amount_thousands"] for row in parsed["buckets"]}
    assert buckets["within_one_year"] == 4953.0
    assert buckets["total"] == 12271.0


def test_extract_ir_presentation_metrics_structured_fields(tmp_path: Path):
    from value_investor.research.filings import extract_ir_presentation_metrics

    filings_dir = tmp_path / "filings"
    bodies_dir = filings_dir / "bodies"
    bodies_dir.mkdir(parents=True)

    fixtures = [
        (
            "ir_fgp",
            Path("docs/data/research/FGP.L/sources/filings/bodies/ir_af873270e9c4b29f.txt"),
            "annual",
        ),
        (
            "ir_hik",
            Path("docs/data/research/HIK.L/sources/filings/bodies/ir_3a67962eb8770824.txt"),
            "annual",
        ),
    ]
    filings: list[dict[str, object]] = []
    for body_id, fixture, period in fixtures:
        if not fixture.is_file():
            pytest.skip(f"{fixture} not present")
        body_path = bodies_dir / f"{body_id}.txt"
        body_path.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
        filings.append(
            {
                "id": body_id,
                "source": "ir_allowlist",
                "headline": f"IR allowlist document — {body_id}",
                "period": period,
                "has_body": True,
                "body_path": str(body_path),
            }
        )

    (filings_dir / "filings_index.json").write_text(
        json.dumps({"filings": filings}),
        encoding="utf-8",
    )
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    metrics = extract_ir_presentation_metrics(
        filings_dir,
        "FGP.L",
        sources_dir=sources_dir,
    )
    assert metrics["bridge_count"] >= 1
    assert metrics["segment_split_count"] >= 1
    assert metrics["mandatory"] is True
    assert (sources_dir / "ir_presentation_metrics.json").exists()
    bridge_types = {row["bridge_type"] for row in metrics["bridges"]}
    assert "fcf_by_division" in bridge_types
    assert any(
        row["split_type"] == "segmental_core_revenue" for row in metrics["segment_revenue_splits"]
    )


def test_extract_ir_presentation_metrics_includes_ifrs16_lease_maturity(tmp_path: Path):
    """End-to-end: MEGP annual-report IR body yields IFRS 16 lease maturity rows."""
    from value_investor.research.filings import extract_ir_presentation_metrics

    filings_dir = tmp_path / "filings"
    bodies_dir = filings_dir / "bodies"
    bodies_dir.mkdir(parents=True)
    body_id = "ir_55af4b8f27e3dd6f"
    fixture = Path("docs/data/research/MEGP.L/sources/filings/bodies/ir_55af4b8f27e3dd6f.txt")
    if not fixture.is_file():
        pytest.skip("MEGP annual report IR body fixture not present")
    body_path = bodies_dir / f"{body_id}.txt"
    body_path.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    (filings_dir / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "id": body_id,
                        "source": "ir_allowlist",
                        "headline": "MEGP FY2025 annual report",
                        "period": "annual",
                        "has_body": True,
                        "body_path": str(body_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    metrics = extract_ir_presentation_metrics(
        filings_dir,
        "MEGP.L",
        sources_dir=sources_dir,
    )
    assert metrics["lease_maturity_count"] >= 1
    assert metrics["mandatory"] is True
    saved = json.loads((sources_dir / "ir_presentation_metrics.json").read_text(encoding="utf-8"))
    lease_rows = saved["ifrs_16_lease_maturity"]
    assert lease_rows
    assert lease_rows[0]["table_type"] == "ifrs16_lease_maturity"
    buckets = {row["bucket"]: row["amount_thousands"] for row in lease_rows[0]["buckets"]}
    assert buckets["within_one_year"] == 4953.0
    assert buckets["total"] == 12271.0


def test_parse_ir_operating_cash_flow_highlights_hik_fixture():
    from value_investor.research.filings import parse_ir_operating_cash_flow_highlights

    fixture = Path("docs/data/research/HIK.L/sources/filings/bodies/ir_a70365d580129295.txt")
    if not fixture.is_file():
        pytest.skip("HIK interim IR body fixture not present")
    parsed = parse_ir_operating_cash_flow_highlights(fixture.read_text(encoding="utf-8"))
    assert parsed is not None
    assert parsed["bridge_type"] == "operating_cash_flow_highlight"
    assert parsed["currency"] == "USD"
    by_label = {row["label"]: row["amount_millions"] for row in parsed["lines"]}
    assert by_label["operating_cash_flow_prior"] == 198.0
    assert by_label["operating_cash_flow_current"] == 161.0


def test_parse_ir_segment_operating_margins_hik_fixture():
    from value_investor.research.filings import parse_ir_segment_operating_margins

    fixture = Path("docs/data/research/HIK.L/sources/filings/bodies/ir_a70365d580129295.txt")
    if not fixture.is_file():
        pytest.skip("HIK interim IR body fixture not present")
    parsed = parse_ir_segment_operating_margins(fixture.read_text(encoding="utf-8"))
    assert parsed is not None
    assert parsed["split_type"] == "segment_operating_margin"
    segments = {row["segment"]: row for row in parsed["segments"]}
    assert segments["Injectables"]["margin_prior_pct"] == 36.3
    assert segments["Injectables"]["margin_current_pct"] == 30.0
    assert segments["Hikma Rx"]["margin_current_pct"] == 17.6


def test_parse_ir_interim_segment_revenue_hik_fixture():
    from value_investor.research.filings import parse_ir_interim_segment_revenue

    fixture = Path("docs/data/research/HIK.L/sources/filings/bodies/ir_a70365d580129295.txt")
    if not fixture.is_file():
        pytest.skip("HIK interim IR body fixture not present")
    parsed = parse_ir_interim_segment_revenue(fixture.read_text(encoding="utf-8"))
    assert parsed is not None
    assert parsed["split_type"] == "interim_segment_revenue"
    segments = {row["segment"]: row for row in parsed["segments"]}
    assert segments["Injectables"]["revenue_current"] == 683.0
    assert segments["Branded"]["revenue_current"] == 437.0
    assert segments["Hikma Rx"]["revenue_current"] == 522.0


def test_extract_ir_presentation_metrics_hik_interim_fixture(tmp_path: Path):
    """End-to-end: HIK H1 results presentation yields OCF bridge and segment tables."""
    from value_investor.research.filings import extract_ir_presentation_metrics

    filings_dir = tmp_path / "filings"
    bodies_dir = filings_dir / "bodies"
    bodies_dir.mkdir(parents=True)
    body_id = "ir_a70365d580129295"
    fixture = Path("docs/data/research/HIK.L/sources/filings/bodies/ir_a70365d580129295.txt")
    if not fixture.is_file():
        pytest.skip("HIK interim IR body fixture not present")
    body_path = bodies_dir / f"{body_id}.txt"
    body_path.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    (filings_dir / "filings_index.json").write_text(
        json.dumps(
            {
                "filings": [
                    {
                        "id": body_id,
                        "source": "ir_allowlist",
                        "headline": "Hikma 2025 interim results presentation",
                        "period": "interim",
                        "has_body": True,
                        "body_path": str(body_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    metrics = extract_ir_presentation_metrics(
        filings_dir,
        "HIK.L",
        sources_dir=sources_dir,
    )
    assert metrics["bridge_count"] >= 1
    assert metrics["segment_split_count"] >= 2
    assert (sources_dir / "ir_presentation_metrics.json").exists()
    bridge_types = {row["bridge_type"] for row in metrics["bridges"]}
    assert "operating_cash_flow_highlight" in bridge_types
    split_types = {row["split_type"] for row in metrics["segment_revenue_splits"]}
    assert "interim_segment_revenue" in split_types
    assert "segment_operating_margin" in split_types
