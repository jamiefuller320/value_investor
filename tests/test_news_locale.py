"""Tests for market-aware Google News locale helpers."""

from value_investor.research.news_locale import (
    build_google_news_query,
    euro_filing_site_clause,
    resolve_news_locale,
)


def test_resolve_news_locale_uk_market():
    locale = resolve_news_locale("ftse350", "SHEL.L")
    assert locale["gl"] == "GB"
    assert locale["query_tail"] == "stock UK"


def test_resolve_news_locale_us_market():
    locale = resolve_news_locale("sp500", "AAPL")
    assert locale["gl"] == "US"
    assert locale["query_tail"] == "stock"


def test_resolve_news_locale_infers_from_ticker_suffix():
    locale = resolve_news_locale(None, "SAP.DE")
    assert locale["gl"] == "DE"
    assert locale["query_tail"] == "Aktie"


def test_build_google_news_query_is_not_uk_biased_for_euro():
    query = build_google_news_query("SAP SE", "SAP.DE", "dax")
    assert "stock UK" not in query
    assert "SAP" in query


def test_euro_filing_site_clause_for_german_ticker():
    clause = euro_filing_site_clause("SAP.DE")
    assert "eqs.com" in clause or "dgap.de" in clause
