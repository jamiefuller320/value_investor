"""Fetch and cache financial history and news for research."""

from __future__ import annotations

import hashlib
import json
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


def _df_years(df: pd.DataFrame | None, *, max_years: int = FINANCIAL_YEARS) -> dict[str, dict[str, float | None]]:
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


def fetch_annual_financials(ticker: str, *, years: int = FINANCIAL_YEARS) -> dict[str, Any]:
    """Pull up to five years of annual statements from yfinance."""
    stock = yf.Ticker(ticker)
    return {
        "ticker": ticker,
        "fetched_at": datetime.now(UTC).isoformat(),
        "income_statement": _df_years(stock.financials, max_years=years),
        "balance_sheet": _df_years(stock.balance_sheet, max_years=years),
        "cash_flow": _df_years(stock.cashflow, max_years=years),
        "quarterly_income": _df_years(getattr(stock, "quarterly_financials", None), max_years=4),
    }


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


def fetch_yfinance_news(ticker: str, *, max_items: int = YFINANCE_NEWS_MAX_ITEMS) -> list[dict[str, Any]]:
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


def fetch_google_news_rss(
    company_name: str,
    ticker: str,
    *,
    max_items: int = GOOGLE_NEWS_MAX_ITEMS,
    lookback_days: int = NEWS_LOOKBACK_DAYS,
) -> list[dict[str, Any]]:
    """Fetch recent headlines from Google News RSS (no API key)."""
    symbol = ticker.replace(".L", "")
    query = urllib.parse.quote(f'"{company_name}" OR {symbol} stock UK')
    url = f"https://news.google.com/rss/search?q={query}&hl=en-GB&gl=GB&ceid=GB:en"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
    except OSError as exc:
        logger.warning("Google News fetch failed for %s: %s", ticker, exc)
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
                "source": "google_news",
                "title": _strip_html(title),
                "summary": summary,
                "published_at": published,
                "url": link,
            }
        )
        if len(articles) >= max_items:
            break
    return articles


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


def ingest_research_sources(
    *,
    ticker: str,
    company_name: str,
    screening_snapshot: dict[str, Any],
    sources_dir: Path,
    since: datetime | None = None,
    include_filings: bool = True,
) -> dict[str, Any]:
    """
    Download research sources under ``sources_dir``.

    Yahoo annual statements + news remain available for context. Primary
    regulatory filings (RNS / results) are written under ``filings/`` and kept
    separate so FINANCIAL REVIEW can cite a consistent primary source.
    """
    sources_dir.mkdir(parents=True, exist_ok=True)

    financials = fetch_annual_financials(ticker)
    financials_path = sources_dir / "financials_annual.json"
    from value_investor.storage import read_json, resolve_json_path, write_json

    write_json(financials_path, financials, compact=True, compress=False)

    snapshot_path = sources_dir / "screening_snapshot.json"
    write_json(snapshot_path, screening_snapshot, compact=True, compress=False)

    yf_news = fetch_yfinance_news(ticker)
    google_news = fetch_google_news_rss(company_name, ticker)
    all_news = merge_news_articles(yf_news, google_news)
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
        "filings_summary": {"total": 0, "annual": 0, "interim": 0, "other": 0, "with_body": 0},
        "filings_sources": [],
    }
    if include_filings:
        from value_investor.research.filings import ingest_filings

        try:
            filings_meta = ingest_filings(
                ticker=ticker,
                company_name=company_name,
                sources_dir=sources_dir,
            )
        except Exception as exc:  # noqa: BLE001 — research should continue without filings
            logger.warning("Filings ingest failed for %s: %s", ticker, exc)

    written_financials = resolve_json_path(financials_path) or financials_path
    written_snapshot = resolve_json_path(snapshot_path) or snapshot_path
    written_manifest = resolve_json_path(manifest_path) or manifest_path
    written_batch = resolve_json_path(batch_path) or batch_path

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
    }
