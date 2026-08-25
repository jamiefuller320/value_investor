"""Fetch and cache financial history and news for research."""

from __future__ import annotations

import hashlib
import logging
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

FINANCIAL_YEARS = 5
FINANCIAL_QUARTERS = 4
NEWS_LOOKBACK_DAYS = 365
GOOGLE_NEWS_MAX_ITEMS = 40
YFINANCE_NEWS_MAX_ITEMS = 30
USER_AGENT = "value-investor-research/0.1"


def _strip_html(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", unescape(cleaned)).strip()


def _df_years(
    df: pd.DataFrame | None, *, max_years: int = FINANCIAL_YEARS
) -> dict[str, dict[str, float | None]]:
    if df is None or df.empty:
        return {}
    out: dict[str, dict[str, float | None]] = {}
    for column in list(df.columns)[:max_years]:
        year = str(column.year) if hasattr(column, "year") else str(column)[:4]
        year_rows: dict[str, float | None] = {}
        for label, value in df[column].items():
            if pd.notna(value):
                try:
                    year_rows[str(label)] = float(value)
                except (TypeError, ValueError):
                    year_rows[str(label)] = None
        out[year] = year_rows
    return out


def _period_key(column: Any) -> str:
    if hasattr(column, "strftime"):
        return column.strftime("%Y-%m-%d")
    text = str(column)
    return text[:10] if len(text) >= 10 else text


def _df_periods(
    df: pd.DataFrame | None, *, max_periods: int = FINANCIAL_QUARTERS
) -> dict[str, dict[str, float | None]]:
    """Serialize quarterly statement columns keyed by period-end ISO date."""
    if df is None or df.empty:
        return {}
    out: dict[str, dict[str, float | None]] = {}
    for column in list(df.columns)[:max_periods]:
        period = _period_key(column)
        period_rows: dict[str, float | None] = {}
        for label, value in df[column].items():
            if pd.notna(value):
                try:
                    period_rows[str(label)] = float(value)
                except (TypeError, ValueError):
                    period_rows[str(label)] = None
        out[period] = period_rows
    return out


# yfinance cash-flow label variants (mirrors value_investor.financials aliases).
_CASHFLOW_LABEL_ALIASES: dict[str, list[str]] = {
    "operating_cashflow": [
        "Operating Cash Flow",
        "Cash Flow From Continuing Operating Activities",
        "Total Cash From Operating Activities",
        "Cash from Operating Activities",
    ],
    "free_cashflow": [
        "Free Cash Flow",
    ],
}

_CAPEX_LABELS = [
    "Capital Expenditure",
    "Capital Expenditures",
    "Purchase Of PPE",
    "Purchase Of Property Plant And Equipment",
]

_QUARTERLY_CASHFLOW_ATTRS = (
    "quarterly_cashflow",
    "quarterly_cash_flow",
)

_QUARTERLY_INCOME_ATTRS = (
    "quarterly_financials",
    "quarterly_income_stmt",
)

_INCOME_EPS_LABELS = [
    "Diluted EPS",
    "Basic EPS",
]

_INCOME_REVENUE_LABELS = [
    "Total Revenue",
    "Operating Revenue",
    "Revenue",
]

_TTM_CASHFLOW_METRIC_KEYS = (
    "operating_cashflow_ttm",
    "capital_expenditure_ttm",
    "free_cashflow_ttm",
)

CASHFLOW_METRIC_KEYS = tuple(_CASHFLOW_LABEL_ALIASES.keys())


def _resolve_yahoo_quarterly_cashflow_df(stock: Any) -> tuple[pd.DataFrame | None, str | None]:
    """Return the first non-empty quarterly cash-flow frame exposed by yfinance."""
    for attr in _QUARTERLY_CASHFLOW_ATTRS:
        df = getattr(stock, attr, None)
        if df is not None and not df.empty:
            return df, attr
    for method_name in ("get_cashflow", "get_cash_flow"):
        method = getattr(stock, method_name, None)
        if not callable(method):
            continue
        try:
            df = method(freq="quarterly")
        except (TypeError, ValueError):
            continue
        if df is not None and not df.empty:
            return df, f"{method_name}(quarterly)"
    return None, None


def _resolve_yahoo_quarterly_income_df(stock: Any) -> tuple[pd.DataFrame | None, str | None]:
    """Return the first non-empty quarterly income frame exposed by yfinance."""
    for attr in _QUARTERLY_INCOME_ATTRS:
        df = getattr(stock, attr, None)
        if df is not None and not df.empty:
            return df, attr
    for method_name in ("get_income_stmt", "get_financials"):
        method = getattr(stock, method_name, None)
        if not callable(method):
            continue
        try:
            df = method(freq="quarterly")
        except (TypeError, ValueError):
            continue
        if df is not None and not df.empty:
            return df, f"{method_name}(quarterly)"
    return None, None


def quarterly_cashflow_has_usable_series(quarterly: dict[str, Any]) -> bool:
    """True when at least one quarterly period has OCF, FCF, or capex lines."""
    if not quarterly:
        return False
    for rows in quarterly.values():
        if not rows:
            continue
        if _annual_label_value(rows, _CASHFLOW_LABEL_ALIASES["operating_cashflow"]) is not None:
            return True
        if _annual_label_value(rows, _CASHFLOW_LABEL_ALIASES["free_cashflow"]) is not None:
            return True
        if _annual_label_value(rows, _CAPEX_LABELS) is not None:
            return True
    return False


def quarterly_income_has_usable_series(quarterly: dict[str, Any]) -> bool:
    """True when at least one quarterly period has EPS or revenue lines."""
    if not quarterly:
        return False
    for rows in quarterly.values():
        if not rows:
            continue
        if _annual_label_value(rows, _INCOME_EPS_LABELS) is not None:
            return True
        if _annual_label_value(rows, _INCOME_REVENUE_LABELS) is not None:
            return True
    return False


def apply_ttm_cashflow_gate(
    financials: dict[str, Any],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    """Drop mechanical TTM metrics and flag when the quarterly cash-flow series is empty."""
    if quarterly_cashflow_has_usable_series(financials.get("quarterly_cashflow") or {}):
        return metrics

    gated = dict(metrics)
    for key in _TTM_CASHFLOW_METRIC_KEYS:
        gated.pop(key, None)
    gated["ttm_cashflow_suppressed"] = True
    gated["ttm_cashflow_suppressed_reason"] = "quarterly_cashflow_empty"
    return gated


def _sorted_financial_years(section: dict[str, Any]) -> list[str]:
    return sorted((str(year) for year in section.keys()), reverse=True)


def _sorted_period_keys(section: dict[str, Any]) -> list[str]:
    return sorted((str(key) for key in section.keys()), reverse=True)


def _annual_label_value(year_rows: dict[str, Any], labels: list[str]) -> float | None:
    for label in labels:
        value = year_rows.get(label)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if pd.notna(number):
            return number
    return None


def extract_ttm_cashflow_metrics_from_quarterly(
    financials: dict[str, Any],
    *,
    max_quarters: int = FINANCIAL_QUARTERS,
) -> dict[str, float | None]:
    """Sum the latest quarterly cash-flow lines into trailing-twelve-month metrics."""
    quarterly = financials.get("quarterly_cashflow") or {}
    if not quarterly:
        return {}

    periods = _sorted_period_keys(quarterly)[:max_quarters]
    if not periods:
        return {}

    ocf_total = 0.0
    capex_total = 0.0
    fcf_total = 0.0
    ocf_count = 0
    capex_count = 0
    fcf_count = 0

    for period in periods:
        rows = quarterly.get(period) or {}
        ocf = _annual_label_value(rows, _CASHFLOW_LABEL_ALIASES["operating_cashflow"])
        capex = _annual_label_value(rows, _CAPEX_LABELS)
        fcf = _annual_label_value(rows, _CASHFLOW_LABEL_ALIASES["free_cashflow"])
        if ocf is not None:
            ocf_total += ocf
            ocf_count += 1
        if capex is not None:
            capex_total += capex
            capex_count += 1
        if fcf is not None:
            fcf_total += fcf
            fcf_count += 1

    metrics: dict[str, float | None] = {}
    if ocf_count:
        metrics["operating_cashflow_ttm"] = ocf_total
    if capex_count:
        metrics["capital_expenditure_ttm"] = capex_total
    if fcf_count:
        metrics["free_cashflow_ttm"] = fcf_total
    elif ocf_count and capex_count and ocf_count == capex_count == len(periods):
        metrics["free_cashflow_ttm"] = ocf_total + capex_total
    return metrics


def extract_cashflow_metrics_from_annual_financials(
    financials: dict[str, Any],
) -> dict[str, float | None]:
    """Extract annual and TTM cash-flow metrics from ``financials_annual.json``."""
    metrics: dict[str, float | None] = {}
    cash_flow = financials.get("cash_flow") or {}
    if cash_flow:
        years = _sorted_financial_years(cash_flow)
        for key, labels in _CASHFLOW_LABEL_ALIASES.items():
            if years:
                metrics[key] = _annual_label_value(cash_flow.get(years[0]) or {}, labels)
            if len(years) > 1:
                metrics[f"{key}_prev"] = _annual_label_value(cash_flow.get(years[1]) or {}, labels)

    metrics.update(extract_ttm_cashflow_metrics_from_quarterly(financials))
    return apply_ttm_cashflow_gate(financials, metrics)


def apply_cashflow_metrics_fallback(
    metrics: dict[str, Any],
    financials: dict[str, Any],
) -> list[str]:
    """Fill missing cash-flow fields on a metrics dict from annual Yahoo statements."""
    extracted = extract_cashflow_metrics_from_annual_financials(financials)
    filled: list[str] = []
    for key in CASHFLOW_METRIC_KEYS:
        if metrics.get(key) is not None:
            continue
        value = extracted.get(key)
        if value is not None:
            metrics[key] = value
            filled.append(key)
    return filled


def _resolve_cached_annual_financials(
    ticker: str,
    *,
    output_dir: Path | None = None,
    sources_dir: Path | None = None,
) -> dict[str, Any] | None:
    from value_investor.storage import read_json, resolve_json_path

    candidates: list[Path] = []
    if sources_dir is not None:
        candidates.append(sources_dir / "financials_annual.json")
    if output_dir is not None:
        candidates.append(output_dir / "research" / ticker / "sources" / "financials_annual.json")

    for path in candidates:
        resolved = resolve_json_path(path)
        if resolved is None:
            continue
        try:
            payload = read_json(resolved)
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(payload, dict) and payload.get("cash_flow"):
            return payload
    return None


def supplement_company_metrics_cashflow(
    metrics: Any,
    *,
    financials: dict[str, Any] | None = None,
    ticker: str | None = None,
    output_dir: Path | None = None,
    sources_dir: Path | None = None,
    allow_live_fetch: bool = True,
) -> list[str]:
    """
    Populate ``operating_cashflow`` / ``free_cashflow`` on ``CompanyMetrics`` when fetch left gaps.

    Prefers a supplied ``financials`` payload, then cached ``financials_annual.json``, then
    optionally a live Yahoo annual-statement fetch when ``allow_live_fetch`` is True.
    """
    needs_fallback = any(getattr(metrics, key, None) is None for key in CASHFLOW_METRIC_KEYS)
    if not needs_fallback:
        return []

    resolved_ticker = ticker or getattr(metrics, "ticker", None)
    if not resolved_ticker:
        return []

    payload = financials
    if payload is None:
        payload = _resolve_cached_annual_financials(
            str(resolved_ticker),
            output_dir=output_dir,
            sources_dir=sources_dir,
        )
    if allow_live_fetch and (payload is None or not (payload.get("cash_flow") or {})):
        payload = fetch_annual_financials(str(resolved_ticker))

    metrics_dict = metrics.to_dict() if hasattr(metrics, "to_dict") else dict(metrics)
    filled = apply_cashflow_metrics_fallback(metrics_dict, payload)
    if not filled:
        return []

    for key in filled:
        if hasattr(metrics, key):
            setattr(metrics, key, metrics_dict[key])

    source_map = getattr(metrics, "data_sources", None)
    if isinstance(source_map, dict):
        for key in filled:
            source_map[key] = "yahoo_financials_annual"

    return filled


def install_fetch_cashflow_fallback() -> None:
    """Patch ``fetch_company_metrics`` to backfill cash-flow fields from Yahoo annual statements."""
    from value_investor import fetch as fetch_mod

    if getattr(fetch_mod.fetch_company_metrics, "_cashflow_fallback_installed", False):
        return

    original = fetch_mod.fetch_company_metrics

    def fetch_company_metrics_with_cashflow_fallback(
        ticker: str,
        name: str | None = None,
        sector: str | None = None,
        *,
        market: str | None = None,
    ):
        metrics = original(ticker, name=name, sector=sector, market=market)
        try:
            supplement_company_metrics_cashflow(
                metrics,
                output_dir=Path("output"),
                allow_live_fetch=False,
            )
        except Exception as exc:  # noqa: BLE001 — screening should continue
            logger.debug("Cash-flow fallback failed for %s: %s", ticker, exc)
        return metrics

    fetch_company_metrics_with_cashflow_fallback._cashflow_fallback_installed = True  # type: ignore[attr-defined]
    fetch_mod.fetch_company_metrics = fetch_company_metrics_with_cashflow_fallback


def summarize_yahoo_quarterly_for_snapshot(financials: dict[str, Any]) -> dict[str, Any]:
    """Build compact Yahoo quarterly income/cash-flow rows keyed by period-end labels."""
    quarterly_income = financials.get("quarterly_income") or {}
    quarterly_cashflow = financials.get("quarterly_cashflow") or {}
    cashflow_metrics = financials.get("cashflow_metrics") or {}

    income_periods: list[dict[str, Any]] = []
    for period in _sorted_period_keys(quarterly_income)[:FINANCIAL_QUARTERS]:
        rows = quarterly_income.get(period) or {}
        entry: dict[str, Any] = {
            "period_end": period,
            "period_label": period,
        }
        diluted_eps = _annual_label_value(rows, ["Diluted EPS"])
        basic_eps = _annual_label_value(rows, ["Basic EPS"])
        revenue = _annual_label_value(rows, _INCOME_REVENUE_LABELS)
        if diluted_eps is not None:
            entry["diluted_eps"] = diluted_eps
        if basic_eps is not None:
            entry["basic_eps"] = basic_eps
        if revenue is not None:
            entry["total_revenue"] = revenue
        if len(entry) > 2:
            income_periods.append(entry)

    cashflow_periods: list[dict[str, Any]] = []
    for period in _sorted_period_keys(quarterly_cashflow)[:FINANCIAL_QUARTERS]:
        rows = quarterly_cashflow.get(period) or {}
        entry = {
            "period_end": period,
            "period_label": period,
        }
        ocf = _annual_label_value(rows, _CASHFLOW_LABEL_ALIASES["operating_cashflow"])
        fcf = _annual_label_value(rows, _CASHFLOW_LABEL_ALIASES["free_cashflow"])
        capex = _annual_label_value(rows, _CAPEX_LABELS)
        if ocf is not None:
            entry["operating_cashflow"] = ocf
        if fcf is not None:
            entry["free_cashflow"] = fcf
        if capex is not None:
            entry["capital_expenditure"] = capex
        if len(entry) > 2:
            cashflow_periods.append(entry)

    summary: dict[str, Any] = {}
    if income_periods:
        summary["quarterly_income"] = income_periods
    if cashflow_periods:
        summary["quarterly_cashflow"] = cashflow_periods

    ttm_payload = {
        key: cashflow_metrics[key]
        for key in _TTM_CASHFLOW_METRIC_KEYS
        if cashflow_metrics.get(key) is not None
    }
    if ttm_payload:
        summary["ttm_cashflow"] = ttm_payload
    if cashflow_metrics.get("ttm_cashflow_suppressed"):
        summary["ttm_cashflow_suppressed"] = True
        reason = cashflow_metrics.get("ttm_cashflow_suppressed_reason")
        if reason:
            summary["ttm_cashflow_suppressed_reason"] = reason

    income_source = financials.get("quarterly_income_source")
    if income_source:
        summary["quarterly_income_source"] = income_source
    cashflow_source = financials.get("quarterly_cashflow_source")
    if cashflow_source:
        summary["quarterly_cashflow_source"] = cashflow_source
    return summary


def enrich_screening_snapshot_with_yahoo_quarterly(
    snapshot: dict[str, Any],
    financials: dict[str, Any],
) -> dict[str, Any]:
    """Attach period-labelled Yahoo quarterly rows to a screening snapshot dict."""
    yahoo_quarterly = summarize_yahoo_quarterly_for_snapshot(financials)
    if not yahoo_quarterly:
        return snapshot
    updated = dict(snapshot)
    updated["yahoo_quarterly"] = yahoo_quarterly
    return updated


def fetch_annual_financials(ticker: str, *, years: int = FINANCIAL_YEARS) -> dict[str, Any]:
    """Pull up to five years of annual statements from yfinance."""
    stock = yf.Ticker(ticker)
    quarterly_income_df, quarterly_income_source = _resolve_yahoo_quarterly_income_df(stock)
    quarterly_df, quarterly_source = _resolve_yahoo_quarterly_cashflow_df(stock)
    payload: dict[str, Any] = {
        "ticker": ticker,
        "fetched_at": datetime.now(UTC).isoformat(),
        "income_statement": _df_years(stock.financials, max_years=years),
        "balance_sheet": _df_years(stock.balance_sheet, max_years=years),
        "cash_flow": _df_years(stock.cashflow, max_years=years),
        "quarterly_income": _df_periods(
            quarterly_income_df,
            max_periods=FINANCIAL_QUARTERS,
        ),
        "quarterly_cashflow": _df_periods(
            quarterly_df,
            max_periods=FINANCIAL_QUARTERS,
        ),
    }
    if quarterly_income_source:
        payload["quarterly_income_source"] = quarterly_income_source
    if quarterly_source:
        payload["quarterly_cashflow_source"] = quarterly_source
    cashflow_metrics = extract_cashflow_metrics_from_annual_financials(payload)
    if cashflow_metrics:
        payload["cashflow_metrics"] = cashflow_metrics
    return payload


def _normalize_yfinance_article(item: dict[str, Any]) -> dict[str, Any] | None:
    content = item.get("content") or {}
    title = content.get("title") or item.get("title")
    if not title:
        return None
    published = content.get("pubDate") or item.get("providerPublishTime")
    if isinstance(published, (int, float)):
        published = datetime.fromtimestamp(published, tz=UTC).isoformat()
    link = None
    for key in ("clickThroughUrl", "canonicalUrl", "previewUrl"):
        url_obj = content.get(key)
        if isinstance(url_obj, dict) and url_obj.get("url"):
            link = url_obj["url"]
            break
    return {
        "id": str(item.get("id") or hashlib.sha1(title.encode()).hexdigest()[:16]),
        "source": "yfinance",
        "title": _strip_html(str(title)),
        "summary": _strip_html(str(content.get("summary") or content.get("description") or "")),
        "published_at": published,
        "url": link,
    }


def fetch_yfinance_news(
    ticker: str, *, max_items: int = YFINANCE_NEWS_MAX_ITEMS
) -> list[dict[str, Any]]:
    stock = yf.Ticker(ticker)
    articles: list[dict[str, Any]] = []
    for item in (stock.news or [])[:max_items]:
        normalized = _normalize_yfinance_article(item)
        if normalized:
            articles.append(normalized)
    return articles


def _parse_rss_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).astimezone(UTC).isoformat()
    except (TypeError, ValueError):
        return value


def fetch_google_news_rss_query(
    query: str,
    *,
    source_label: str = "google_news",
    max_items: int = GOOGLE_NEWS_MAX_ITEMS,
    lookback_days: int = NEWS_LOOKBACK_DAYS,
    hl: str = "en-GB",
    gl: str = "GB",
    ceid: str = "GB:en",
) -> list[dict[str, Any]]:
    """Fetch recent headlines for an arbitrary Google News RSS query."""
    url = (
        "https://news.google.com/rss/search?"
        f"q={urllib.parse.quote(query)}&hl={hl}&gl={gl}&ceid={ceid}"
    )
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
    except OSError as exc:
        logger.warning("Google News fetch failed for query %r: %s", query, exc)
        return []

    root = ET.fromstring(payload)
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    articles: list[dict[str, Any]] = []

    for item in root.findall(".//item"):
        title = item.findtext("title")
        if not title:
            continue
        link = item.findtext("link")
        published = _parse_rss_date(item.findtext("pubDate"))
        if published:
            try:
                published_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                if published_dt < cutoff:
                    continue
            except ValueError:
                pass
        summary = _strip_html(item.findtext("description") or "")
        article_id = hashlib.sha1(f"{title}|{link}".encode()).hexdigest()[:16]
        articles.append(
            {
                "id": article_id,
                "source": source_label,
                "title": _strip_html(title),
                "summary": summary,
                "published_at": published,
                "url": link,
                "query": query,
            }
        )
        if len(articles) >= max_items:
            break
    return articles


def fetch_google_news_rss(
    company_name: str,
    ticker: str,
    *,
    max_items: int = GOOGLE_NEWS_MAX_ITEMS,
    lookback_days: int = NEWS_LOOKBACK_DAYS,
    market: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch recent headlines from Google News RSS (no API key)."""
    from value_investor.research.news_locale import (
        build_google_news_query,
        resolve_news_locale,
    )

    locale = resolve_news_locale(market, ticker)
    query = build_google_news_query(company_name, ticker, market)
    return fetch_google_news_rss_query(
        query,
        source_label="google_news",
        max_items=max_items,
        lookback_days=lookback_days,
        hl=locale["hl"],
        gl=locale["gl"],
        ceid=locale["ceid"],
    )


def _article_key(article: dict[str, Any]) -> str:
    return str(article.get("id") or article.get("title"))


def merge_news_articles(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in groups:
        for article in group:
            merged[_article_key(article)] = article
    return sorted(
        merged.values(),
        key=lambda item: item.get("published_at") or "",
        reverse=True,
    )


def filter_news_since(articles: list[dict[str, Any]], since: datetime) -> list[dict[str, Any]]:
    fresh: list[dict[str, Any]] = []
    for article in articles:
        published = article.get("published_at")
        if not published:
            fresh.append(article)
            continue
        try:
            published_dt = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
        except ValueError:
            fresh.append(article)
            continue
        if published_dt >= since:
            fresh.append(article)
    return fresh


def filter_misattributed_news_articles(
    articles: list[dict[str, Any]],
    *,
    company_name: str,
    ticker: str,
    market: str | None = None,
) -> list[dict[str, Any]]:
    """Drop UK news headlines that never mention the issuer EPIC or company name."""
    from value_investor.research.filings import headline_relevant_to_issuer, resolve_filings_regime

    if resolve_filings_regime(market, ticker) != "uk_rns":
        return articles
    kept: list[dict[str, Any]] = []
    for article in articles:
        title = str(article.get("title") or "")
        if headline_relevant_to_issuer(title, company_name, ticker):
            kept.append(article)
    return kept


def ingest_research_sources(
    *,
    ticker: str,
    company_name: str,
    screening_snapshot: dict[str, Any],
    sources_dir: Path,
    since: datetime | None = None,
    include_filings: bool = True,
    market: str | None = None,
    deepen_history: bool = False,
) -> dict[str, Any]:
    """
    Download research sources under ``sources_dir``.

    Yahoo annual statements + news remain available for context. Primary
    regulatory filings (UK RNS, US SEC EDGAR, ASX announcements, or Euro
    results discovery) are written under ``filings/`` and kept separate so
    FINANCIAL REVIEW can cite a consistent primary source. Macro context is
    written for memo prompts only — never used for scoring.

    ``deepen_history`` pulls more Companies House accounts years for tickers
    that already triggered memo compilation — forward depth only (does not
    backdate research revisions / PIT overlays).
    """
    sources_dir.mkdir(parents=True, exist_ok=True)

    financials = fetch_annual_financials(ticker)
    financials_path = sources_dir / "financials_annual.json"
    from value_investor.storage import read_json, resolve_json_path, write_json

    write_json(financials_path, financials, compact=True, compress=False)

    snapshot_path = sources_dir / "screening_snapshot.json"
    write_json(
        snapshot_path,
        enrich_screening_snapshot_with_yahoo_quarterly(screening_snapshot, financials),
        compact=True,
        compress=False,
    )

    yf_news = fetch_yfinance_news(ticker)
    google_news = fetch_google_news_rss(company_name, ticker, market=market)
    all_news = merge_news_articles(yf_news, google_news)
    all_news = filter_misattributed_news_articles(
        all_news,
        company_name=company_name,
        ticker=ticker,
        market=market,
    )
    if since is not None:
        new_news = filter_news_since(all_news, since)
    else:
        new_news = all_news

    manifest_path = sources_dir / "news_manifest.json"
    existing_manifest: dict[str, Any] = {"articles": []}
    resolved_manifest = resolve_json_path(manifest_path)
    if resolved_manifest is not None:
        existing_manifest = read_json(resolved_manifest)

    known_ids = {item.get("id") for item in existing_manifest.get("articles", [])}
    combined = list(existing_manifest.get("articles", []))
    for article in all_news:
        if article["id"] not in known_ids:
            combined.append(article)
            known_ids.add(article["id"])

    manifest = {
        "ticker": ticker,
        "updated_at": datetime.now(UTC).isoformat(),
        "articles": sorted(combined, key=lambda item: item.get("published_at") or "", reverse=True),
    }
    write_json(manifest_path, manifest, compact=True, compress=False)

    news_batch = {
        "ticker": ticker,
        "fetched_at": datetime.now(UTC).isoformat(),
        "since": since.isoformat() if since else None,
        "articles": new_news,
    }
    batch_name = f"news_batch_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
    batch_path = sources_dir / batch_name
    write_json(
        batch_path,
        news_batch,
        compact=True,
        compress=False,
    )

    filings_meta: dict[str, Any] = {
        "filings_index_path": None,
        "filings_summary": {
            "total": 0,
            "annual": 0,
            "interim": 0,
            "trading_update": 0,
            "other": 0,
            "with_body": 0,
        },
        "filings_sources": [],
    }
    if include_filings:
        from value_investor.research.filings import ingest_filings

        try:
            filings_meta = ingest_filings(
                ticker=ticker,
                company_name=company_name,
                sources_dir=sources_dir,
                market=market,
                deepen_history=deepen_history,
            )
        except Exception as exc:  # noqa: BLE001 — research should continue without filings
            logger.warning("Filings ingest failed for %s: %s", ticker, exc)
            filings_meta = {
                "filings_index_path": None,
                "filings_summary": {
                    "total": 0,
                    "annual": 0,
                    "interim": 0,
                    "trading_update": 0,
                    "other": 0,
                    "with_body": 0,
                },
                "filings_sources": [],
            }
        else:
            from value_investor.research.filings import (
                refetch_companies_house_filing_bodies,
                resolve_filings_regime,
            )

            if resolve_filings_regime(market, ticker) == "uk_rns":
                summary = filings_meta.get("filings_summary") or {}
                if int(summary.get("with_body") or 0) == 0 and int(summary.get("total") or 0) > 0:
                    ch_refetch = refetch_companies_house_filing_bodies(
                        sources_dir / "filings",
                        max_bodies=12,
                    )
                    if int(ch_refetch.get("fetched") or 0) > 0:
                        index_path = sources_dir / "filings" / "filings_index.json"
                        resolved_index = resolve_json_path(index_path)
                        if resolved_index is not None:
                            try:
                                index_payload = read_json(resolved_index)
                                filings_meta["filings_summary"] = dict(
                                    index_payload.get("summary") or summary
                                )
                                filings_meta["filings_sources"] = list(
                                    index_payload.get("sources_used") or []
                                )
                            except (OSError, ValueError, TypeError):
                                pass
                        filings_meta["ch_body_refetch"] = ch_refetch

            elif resolve_filings_regime(market, ticker) == "euro_filings":
                from value_investor.research.filings import (
                    refetch_ir_allowlist_filing_bodies,
                    refetch_residual_filing_bodies,
                )

                summary = filings_meta.get("filings_summary") or {}
                ir_refetch = refetch_ir_allowlist_filing_bodies(
                    sources_dir / "filings",
                    ticker=ticker,
                    company_name=company_name,
                    max_bodies=12,
                )
                residual_refetch = refetch_residual_filing_bodies(
                    sources_dir / "filings",
                    ticker=ticker,
                    company_name=company_name,
                    max_bodies=12,
                )
                filings_meta["ir_refetch"] = ir_refetch
                filings_meta["residual_refetch"] = residual_refetch
                if int(ir_refetch.get("fetched") or 0) or int(residual_refetch.get("fetched") or 0):
                    index_path = sources_dir / "filings" / "filings_index.json"
                    resolved_index = resolve_json_path(index_path)
                    if resolved_index is not None:
                        try:
                            index_payload = read_json(resolved_index)
                            filings_meta["filings_summary"] = dict(
                                index_payload.get("summary") or summary
                            )
                            filings_meta["filings_sources"] = list(
                                index_payload.get("sources_used") or []
                            )
                        except (OSError, ValueError, TypeError):
                            pass

        if deepen_history:
            from value_investor.research.gap_fill_sources import deepen_thin_filings_if_needed

            filings_summary = filings_meta.get("filings_summary") or {}
            deepen_meta = deepen_thin_filings_if_needed(
                ticker=ticker,
                company_name=company_name,
                sources_dir=sources_dir,
                market=market,
                filings_summary=filings_summary,
            )
            filings_meta["filings_deepen"] = deepen_meta
            if not deepen_meta.get("skipped"):
                # Re-read summary after gap-fill loop may have added bodies.
                index_path = sources_dir / "filings" / "filings_index.json"
                resolved_index = resolve_json_path(index_path)
                if resolved_index is not None:
                    try:
                        index_payload = read_json(resolved_index)
                        filings_meta["filings_summary"] = dict(
                            index_payload.get("summary") or filings_summary
                        )
                        filings_meta["filings_sources"] = list(
                            index_payload.get("sources_used") or []
                        )
                    except (OSError, ValueError, TypeError):
                        pass

    market_s = str(market or "").strip().lower() or None
    macro_meta: dict[str, Any] = {"status": "skipped", "reason": "no_market"}
    if market_s:
        try:
            from value_investor.macro_context import macro_context_for_market

            macro_meta = macro_context_for_market(market_s, refresh_if_missing=False)
            write_json(
                sources_dir / "macro_context.json",
                macro_meta,
                compact=True,
                compress=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Macro context attach failed for %s: %s", ticker, exc)
            macro_meta = {"status": "error", "error": str(exc), "market": market_s}

    written_financials = resolve_json_path(financials_path) or financials_path
    written_snapshot = resolve_json_path(snapshot_path) or snapshot_path
    written_manifest = resolve_json_path(manifest_path) or manifest_path
    written_batch = resolve_json_path(batch_path) or batch_path
    written_macro = resolve_json_path(sources_dir / "macro_context.json")

    return {
        "financials_path": str(written_financials),
        "snapshot_path": str(written_snapshot),
        "news_manifest_path": str(written_manifest),
        "news_batch_path": str(written_batch),
        "financial_years": len(financials.get("income_statement", {})),
        "news_total": len(manifest["articles"]),
        "news_new": len(new_news),
        "filings_index_path": filings_meta.get("filings_index_path"),
        "filings_summary": filings_meta.get("filings_summary") or {},
        "filings_sources": filings_meta.get("filings_sources") or [],
        "filings_regime": filings_meta.get("filings_regime"),
        "macro_context_path": str(written_macro) if written_macro else None,
        "macro_context": macro_meta,
        "market": market_s,
    }
