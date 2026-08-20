"""Market-aware Google News locale and query helpers for research ingest."""

from __future__ import annotations

import re

# Google News RSS locale (hl / gl / ceid) and query tail by market id.
MARKET_NEWS_LOCALE: dict[str, dict[str, str]] = {
    "ftse350": {"hl": "en-GB", "gl": "GB", "ceid": "GB:en", "query_tail": "stock UK"},
    "ftse_smallcap": {"hl": "en-GB", "gl": "GB", "ceid": "GB:en", "query_tail": "stock UK"},
    "aim": {"hl": "en-GB", "gl": "GB", "ceid": "GB:en", "query_tail": "stock UK"},
    "sp500": {"hl": "en-US", "gl": "US", "ceid": "US:en", "query_tail": "stock"},
    "nasdaq100": {"hl": "en-US", "gl": "US", "ceid": "US:en", "query_tail": "stock"},
    "us_adr_asia": {"hl": "en-US", "gl": "US", "ceid": "US:en", "query_tail": "stock"},
    "asx200": {"hl": "en-AU", "gl": "AU", "ceid": "AU:en", "query_tail": "ASX stock"},
    "tsx60": {"hl": "en-CA", "gl": "CA", "ceid": "CA:en", "query_tail": "TSX stock"},
    "euro_stoxx50": {"hl": "en", "gl": "DE", "ceid": "DE:en", "query_tail": "stock"},
    "euro_depth": {"hl": "en", "gl": "DE", "ceid": "DE:en", "query_tail": "stock"},
    "dax": {"hl": "de", "gl": "DE", "ceid": "DE:de", "query_tail": "Aktie"},
    "cac40": {"hl": "fr", "gl": "FR", "ceid": "FR:fr", "query_tail": "action"},
    "ibex35": {"hl": "es", "gl": "ES", "ceid": "ES:es", "query_tail": "acciones"},
    "ftse_mib": {"hl": "it", "gl": "IT", "ceid": "IT:it", "query_tail": "azioni"},
    "aex": {"hl": "nl", "gl": "NL", "ceid": "NL:nl", "query_tail": "aandeel"},
    "bel20": {"hl": "fr", "gl": "BE", "ceid": "BE:fr", "query_tail": "action"},
    "hang_seng": {"hl": "en", "gl": "HK", "ceid": "HK:en", "query_tail": "stock"},
    "sti": {"hl": "en", "gl": "SG", "ceid": "SG:en", "query_tail": "stock"},
    "atx": {"hl": "de", "gl": "AT", "ceid": "AT:de", "query_tail": "Aktie"},
    "psi20": {"hl": "pt", "gl": "PT", "ceid": "PT:pt", "query_tail": "acções"},
    "smi": {"hl": "de", "gl": "CH", "ceid": "CH:de", "query_tail": "Aktie"},
    "omxs30": {"hl": "sv", "gl": "SE", "ceid": "SE:sv", "query_tail": "aktie"},
    "iseq20": {"hl": "en-GB", "gl": "IE", "ceid": "IE:en", "query_tail": "stock"},
}

# Infer locale from Yahoo-style exchange suffix when market id is absent.
SUFFIX_NEWS_LOCALE: dict[str, dict[str, str]] = {
    ".L": {"hl": "en-GB", "gl": "GB", "ceid": "GB:en", "query_tail": "stock UK"},
    ".AX": {"hl": "en-AU", "gl": "AU", "ceid": "AU:en", "query_tail": "ASX stock"},
    ".TO": {"hl": "en-CA", "gl": "CA", "ceid": "CA:en", "query_tail": "TSX stock"},
    ".DE": {"hl": "de", "gl": "DE", "ceid": "DE:de", "query_tail": "Aktie"},
    ".PA": {"hl": "fr", "gl": "FR", "ceid": "FR:fr", "query_tail": "action"},
    ".AS": {"hl": "nl", "gl": "NL", "ceid": "NL:nl", "query_tail": "aandeel"},
    ".MI": {"hl": "it", "gl": "IT", "ceid": "IT:it", "query_tail": "azioni"},
    ".MC": {"hl": "es", "gl": "ES", "ceid": "ES:es", "query_tail": "acciones"},
    ".BR": {"hl": "fr", "gl": "BE", "ceid": "BE:fr", "query_tail": "action"},
    ".HK": {"hl": "en", "gl": "HK", "ceid": "HK:en", "query_tail": "stock"},
    ".SI": {"hl": "en", "gl": "SG", "ceid": "SG:en", "query_tail": "stock"},
    ".SW": {"hl": "de", "gl": "CH", "ceid": "CH:de", "query_tail": "Aktie"},
    ".VI": {"hl": "de", "gl": "AT", "ceid": "AT:de", "query_tail": "Aktie"},
    ".ST": {"hl": "sv", "gl": "SE", "ceid": "SE:sv", "query_tail": "aktie"},
    ".IR": {"hl": "en-GB", "gl": "IE", "ceid": "IE:en", "query_tail": "stock"},
    ".LS": {"hl": "pt", "gl": "PT", "ceid": "PT:pt", "query_tail": "acções"},
}

DEFAULT_NEWS_LOCALE = {"hl": "en-US", "gl": "US", "ceid": "US:en", "query_tail": "stock"}

# Exchange-site hints for Euro filing discovery queries.
EURO_EXCHANGE_SITES: dict[str, str] = {
    ".DE": "site:eqs.com OR site:dgap.de OR site:deutsche-boerse.com",
    ".PA": "site:amf-france.org OR site:euronext.com",
    ".AS": "site:euronext.com",
    ".MI": "site:borsaitaliana.it OR site:consob.it",
    ".MC": "site:bolsamadrid.es OR site:cnmv.es",
    ".BR": "site:euronext.com",
    ".HE": "site:euronext.com",
    ".IR": "site:euronext.com",
    ".LS": "site:euronext.com",
    ".AT": "site:wienerborse.at",
    ".SW": "site:six-group.com",
    ".VI": "site:wienerborse.at",
}


def _ticker_suffix(ticker: str) -> str | None:
    t = (ticker or "").strip().upper()
    for suffix in sorted(SUFFIX_NEWS_LOCALE, key=len, reverse=True):
        if t.endswith(suffix):
            return suffix
    return None


def resolve_news_locale(market: str | None, ticker: str) -> dict[str, str]:
    """Return Google News RSS locale fields and a query tail for the issuer."""
    mid = (market or "").strip().lower()
    if mid in MARKET_NEWS_LOCALE:
        return dict(MARKET_NEWS_LOCALE[mid])
    suffix = _ticker_suffix(ticker)
    if suffix and suffix in SUFFIX_NEWS_LOCALE:
        return dict(SUFFIX_NEWS_LOCALE[suffix])
    if "." not in (ticker or "").strip():
        return dict(MARKET_NEWS_LOCALE["sp500"])
    return dict(DEFAULT_NEWS_LOCALE)


def build_google_news_query(company_name: str, ticker: str, market: str | None = None) -> str:
    """Build a market-appropriate Google News RSS query."""
    locale = resolve_news_locale(market, ticker)
    symbol = re.sub(r"\.[A-Z]{1,3}$", "", (ticker or "").strip(), flags=re.IGNORECASE)
    tail = locale.get("query_tail") or "stock"
    return f'"{company_name}" OR {symbol} {tail}'


def euro_filing_site_clause(ticker: str) -> str:
    """Optional site: filter for Euro filing headline discovery."""
    suffix = _ticker_suffix(ticker)
    if not suffix:
        return ""
    clause = EURO_EXCHANGE_SITES.get(suffix)
    return f"({clause}) " if clause else ""
