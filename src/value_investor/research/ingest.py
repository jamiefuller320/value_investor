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

CASHFLOW_METRIC_KEYS = tuple(_CASHFLOW_LABEL_ALIASES.keys())


def _sorted_financial_years(section: dict[str, Any]) -> list[str]:
    return sorted((str(year) for year in section.keys()), reverse=True)


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


def extract_cashflow_metrics_from_annual_financials(
    financials: dict[str, Any],
) -> dict[str, float | None]:
    """Extract latest (and prior-year) cash-flow metrics from ``financials_annual.json``."""
    cash_flow = financials.get("cash_flow") or {}
    if not cash_flow:
        return {}

    years = _sorted_financial_years(cash_flow)
    metrics: dict[str, float | None] = {}
    for key, labels in _CASHFLOW_LABEL_ALIASES.items():
        if years:
            metrics[key] = _annual_label_value(cash_flow.get(years[0]) or {}, labels)
        if len(years) > 1:
            metrics[f"{key}_prev"] = _annual_label_value(cash_flow.get(years[1]) or {}, labels)
    return metrics


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


def fetch_annual_financials(ticker: str, *, years: int = FINANCIAL_YEARS) -> dict[str, Any]:
    """Pull up to five years of annual statements from yfinance."""
    stock = yf.Ticker(ticker)
    payload: dict[str, Any] = {
        "ticker": ticker,
        "fetched_at": datetime.now(UTC).isoformat(),
        "income_statement": _df_years(stock.financials, max_years=years),
        "balance_sheet": _df_years(stock.balance_sheet, max_years=years),
        "cash_flow": _df_years(stock.cashflow, max_years=years),
        "quarterly_income": _df_years(getattr(stock, "quarterly_financials", None), max_years=4),
    }
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
    write_json(snapshot_path, screening_snapshot, compact=True, compress=False)

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
