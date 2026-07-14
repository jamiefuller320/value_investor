"""Primary UK regulatory filings for research memos (separate from Yahoo).

Memo-eligible names only. Yahoo remains the screening source; this module
collects RNS / results announcements for FINANCIAL REVIEW.

Sources (in priority order for body text):
1. Optional Ticker.app RNS API when ``TICKER_API_KEY`` is set
2. Google News RSS discovery of Investegate / results headlines
3. HTML body fetch when a direct Investegate (or similar) URL is available

Interim vs annual is classified from headlines / FCA-style categories.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

USER_AGENT = "value-investor-research/0.1 (+filings)"
FILINGS_LOOKBACK_DAYS = 800  # ~2.2 years — cover annual + several interims
FILINGS_MAX_ITEMS = 40
FILINGS_BODY_MAX_CHARS = 80_000
TICKER_API_BASE = "https://api.tickerapp.net/v2"

# Headline cues for regulatory results packs.
_ANNUAL_PATTERNS = (
    r"\bfull[- ]year\b",
    r"\bfinal results\b",
    r"\bannual report\b",
    r"\bannual results\b",
    r"\byear[- ]end results\b",
    r"\baudited results\b",
)
_INTERIM_PATTERNS = (
    r"\bhalf[- ]year\b",
    r"\binterim results\b",
    r"\binterim report\b",
    r"\bh1 results\b",
    r"\bh2 results\b",
    r"\bq[1-4]\b",
    r"\bfirst quarter\b",
    r"\bsecond quarter\b",
    r"\bthird quarter\b",
    r"\bfourth quarter\b",
    r"\btrading update\b",
    r"\btrading statement\b",
)

# Prefer results / accounts over buybacks and trivia when ranking.
_PRIORITY_PATTERNS = _ANNUAL_PATTERNS + _INTERIM_PATTERNS + (r"\bannual report and accounts\b",)


def _strip_html(text: str) -> str:
    cleaned = re.sub(r"<script[\s\S]*?</script>", " ", text or "", flags=re.I)
    cleaned = re.sub(r"<style[\s\S]*?</style>", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    return re.sub(r"\s+", " ", unescape(cleaned)).strip()


def _epic(ticker: str) -> str:
    return ticker.replace(".L", "").replace(".l", "").strip().upper()


def classify_filing_period(headline: str, *, category: str | None = None) -> str:
    """
    Return ``annual``, ``interim``, or ``other``.

    Uses headline keywords and optional provider category codes/names.
    """
    blob = f"{headline or ''} {category or ''}".lower()

    # Dividends / buybacks / exchange offers are not results packs.
    if re.search(
        r"\b(interim dividend|final dividend|dividend timetable|transaction in own shares|"
        r"director/?pdmr|exchange offers?|total voting rights|block listing)\b",
        blob,
    ):
        return "other"

    if any(re.search(pat, blob) for pat in _ANNUAL_PATTERNS):
        return "annual"
    if any(re.search(pat, blob) for pat in _INTERIM_PATTERNS):
        return "interim"
    # FCA-style codes sometimes appear in provider metadata
    if re.search(r"\b(fr|final results|annual)\b", blob):
        return "annual"
    if re.search(r"\b(ir|half[- ]year report|interim results)\b", blob):
        return "interim"
    return "other"


def _filing_id(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _parse_rss_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).astimezone(UTC).isoformat()
    except (TypeError, ValueError):
        return value


def _http_get(url: str, *, headers: dict[str, str] | None = None, timeout: int = 30) -> bytes:
    request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    request = urllib.request.Request(url, headers=request_headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _priority_score(headline: str, period: str) -> int:
    score = 0
    if period == "annual":
        score += 100
    elif period == "interim":
        score += 80
    lower = (headline or "").lower()
    if any(re.search(pat, lower) for pat in _PRIORITY_PATTERNS):
        score += 20
    if "transaction in own shares" in lower or "director/pdmr" in lower:
        score -= 50
    return score


def fetch_filings_google_news(
    *,
    company_name: str,
    ticker: str,
    max_items: int = FILINGS_MAX_ITEMS,
    lookback_days: int = FILINGS_LOOKBACK_DAYS,
) -> list[dict[str, Any]]:
    """
    Discover UK results / RNS-style announcements via Google News RSS.

    Returns metadata rows (title, date, url, period). Full text is usually not
    available from the Google wrapper URL; bodies are filled later when a direct
    publisher URL is known.
    """
    epic = _epic(ticker)
    query = (
        f'site:investegate.co.uk "{company_name}" OR {epic} '
        f'(Results OR "Annual Report" OR Interim OR "Half-year" OR "Trading Update" OR RNS)'
    )
    url = (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote(query)
        + "&hl=en-GB&gl=GB&ceid=GB:en"
    )
    try:
        payload = _http_get(url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("Google News filings fetch failed for %s: %s", ticker, exc)
        return []

    root = ET.fromstring(payload)
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    rows: list[dict[str, Any]] = []
    for item in root.findall(".//item"):
        title = _strip_html(item.findtext("title") or "")
        if not title:
            continue
        # Drop index/landing pages
        if re.search(r"\bRNS Announcements\b", title) and "results" not in title.lower():
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
        period = classify_filing_period(title)
        summary = _strip_html(item.findtext("description") or "")
        rows.append(
            {
                "id": _filing_id("gnews", title, published or "", link or ""),
                "source": "google_news_investegate",
                "headline": title,
                "published_at": published,
                "url": link,
                "period": period,
                "category": None,
                "summary": summary[:1000] if summary else "",
                "has_body": False,
                "body_path": None,
                "priority": _priority_score(title, period),
            }
        )
        if len(rows) >= max_items:
            break
    return rows


def fetch_filings_ticker_api(
    *,
    ticker: str,
    api_key: str | None = None,
    max_items: int = FILINGS_MAX_ITEMS,
    lookback_days: int = FILINGS_LOOKBACK_DAYS,
) -> list[dict[str, Any]]:
    """
    Fetch RNS items from Ticker.app when ``TICKER_API_KEY`` is configured.

    Free/lite tiers vary; failures are logged and return an empty list so the
    Google News path can still populate the index.
    """
    key = api_key or os.environ.get("TICKER_API_KEY") or os.environ.get("RNS_API_KEY")
    if not key:
        return []

    epic = _epic(ticker)
    date_from = (datetime.now(UTC) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    params = urllib.parse.urlencode(
        {
            "symbol": epic,
            "pageSize": min(max_items, 50),
            "dateFrom": date_from,
        }
    )
    url = f"{TICKER_API_BASE}/disclosures/sources/rns/items?{params}"
    try:
        payload = _http_get(url, headers={"x-api-key": key, "Accept": "application/json"})
        data = json.loads(payload.decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.warning("Ticker RNS API failed for %s: %s", ticker, exc)
        return []

    items = data.get("data") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []

    rows: list[dict[str, Any]] = []
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        headline = str(item.get("headline") or item.get("title") or "").strip()
        if not headline:
            continue
        categories = item.get("category") or []
        category_label = None
        if isinstance(categories, list) and categories:
            first = categories[0]
            if isinstance(first, dict):
                category_label = str(first.get("name") or first.get("code") or "")
            else:
                category_label = str(first)
        elif isinstance(categories, str):
            category_label = categories

        published = item.get("timestamp") or item.get("published_at") or item.get("date")
        if isinstance(published, (int, float)):
            published = datetime.fromtimestamp(published, tz=UTC).isoformat()

        # Prefer HTML publication URL when present
        pub_url = None
        publications = item.get("publication") or item.get("publications") or []
        if isinstance(publications, list):
            for pub in publications:
                if not isinstance(pub, dict):
                    continue
                candidate = pub.get("url") or pub.get("href")
                if candidate and str(candidate).startswith("http"):
                    pub_url = str(candidate)
                    if str(pub.get("type") or "").lower() in ("html", "text", ""):
                        break
        pub_url = pub_url or item.get("url") or item.get("sourceUrl")

        period = classify_filing_period(headline, category=category_label)
        rns_id = str(item.get("rnsId") or item.get("id") or "")
        rows.append(
            {
                "id": _filing_id("ticker", rns_id or headline, str(published or "")),
                "source": "ticker_rns_api",
                "headline": headline,
                "published_at": published,
                "url": pub_url,
                "period": period,
                "category": category_label,
                "summary": "",
                "has_body": False,
                "body_path": None,
                "priority": _priority_score(headline, period),
                "provider_id": rns_id or None,
            }
        )
    return rows


def fetch_filing_body(url: str | None) -> str | None:
    """Download and extract plain text from a direct announcement URL."""
    if not url or not url.startswith("http"):
        return None
    # Google News wrappers rarely expose the publisher body.
    if "news.google.com" in url:
        return None
    try:
        raw = _http_get(url, timeout=40)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.debug("Filing body fetch failed for %s: %s", url, exc)
        return None

    content_type = ""
    # urlopen doesn't return headers here easily — sniff
    if raw[:4] == b"%PDF":
        logger.info("Skipping PDF filing body (not parsed): %s", url)
        return None

    text = _strip_html(raw.decode("utf-8", errors="replace"))
    if len(text) < 200:
        return None
    if len(text) > FILINGS_BODY_MAX_CHARS:
        text = text[:FILINGS_BODY_MAX_CHARS] + "\n\n[truncated]"
    return text


def merge_filings(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge filing rows, preferring entries with bodies and higher priority."""
    merged: dict[str, dict[str, Any]] = {}
    for group in groups:
        for row in group:
            key = (
                (row.get("headline") or "").strip().lower(),
                (str(row.get("published_at") or ""))[:10],
            )
            existing = merged.get(str(key))
            if existing is None:
                merged[str(key)] = row
                continue
            # Prefer ticker API / body-bearing rows
            existing_score = int(existing.get("priority") or 0) + (
                50 if existing.get("has_body") else 0
            ) + (30 if existing.get("source") == "ticker_rns_api" else 0)
            new_score = int(row.get("priority") or 0) + (50 if row.get("has_body") else 0) + (
                30 if row.get("source") == "ticker_rns_api" else 0
            )
            if new_score >= existing_score:
                # Keep body path if new row lacks one
                if not row.get("body_path") and existing.get("body_path"):
                    row = {**row, "body_path": existing["body_path"], "has_body": True}
                merged[str(key)] = row
    return sorted(
        merged.values(),
        key=lambda item: (
            -int(item.get("priority") or 0),
            item.get("published_at") or "",
        ),
    )


def _write_bodies(
    filings: list[dict[str, Any]],
    bodies_dir: Path,
    *,
    max_bodies: int = 12,
) -> list[dict[str, Any]]:
    """Fetch bodies for the highest-priority filings with direct URLs."""
    bodies_dir.mkdir(parents=True, exist_ok=True)
    # Prefer annual/interim first
    candidates = sorted(
        filings,
        key=lambda row: (-int(row.get("priority") or 0), row.get("published_at") or ""),
    )
    downloaded = 0
    updated: list[dict[str, Any]] = []
    for row in candidates:
        row = dict(row)
        if downloaded < max_bodies and row.get("url") and not row.get("has_body"):
            period = row.get("period")
            if period in ("annual", "interim", "other"):
                # Always try annual/interim; only try a few "other" if slots remain
                if period == "other" and downloaded >= max(4, max_bodies // 2):
                    updated.append(row)
                    continue
                body = fetch_filing_body(str(row["url"]))
                if body:
                    filename = f"{row['id']}.txt"
                    path = bodies_dir / filename
                    path.write_text(body, encoding="utf-8")
                    row["has_body"] = True
                    row["body_path"] = str(path)
                    downloaded += 1
        updated.append(row)
    return updated


def summarize_filings(filings: list[dict[str, Any]]) -> dict[str, Any]:
    annual = sum(1 for f in filings if f.get("period") == "annual")
    interim = sum(1 for f in filings if f.get("period") == "interim")
    other = sum(1 for f in filings if f.get("period") == "other")
    with_body = sum(1 for f in filings if f.get("has_body"))
    return {
        "total": len(filings),
        "annual": annual,
        "interim": interim,
        "other": other,
        "with_body": with_body,
    }


def ingest_filings(
    *,
    ticker: str,
    company_name: str,
    sources_dir: Path,
    api_key: str | None = None,
) -> dict[str, Any]:
    """
    Build ``sources/filings/`` for a memo ticker.

    Writes:
    - ``filings_index.json`` — catalog with period labels (annual/interim/other)
    - ``bodies/*.txt`` — plain-text announcement extracts when downloadable
    """
    filings_dir = sources_dir / "filings"
    bodies_dir = filings_dir / "bodies"
    filings_dir.mkdir(parents=True, exist_ok=True)

    ticker_rows = fetch_filings_ticker_api(ticker=ticker, api_key=api_key)
    google_rows = fetch_filings_google_news(company_name=company_name, ticker=ticker)
    merged = merge_filings(ticker_rows, google_rows)
    merged = _write_bodies(merged, bodies_dir)

    index = {
        "ticker": ticker,
        "company_name": company_name,
        "fetched_at": datetime.now(UTC).isoformat(),
        "note": (
            "Primary regulatory filings for research (separate from Yahoo). "
            "period=annual|interim|other. Bodies are plain-text extracts when a "
            "direct publisher URL was available; Google News wrappers often lack bodies."
        ),
        "sources_used": sorted({row.get("source") for row in merged if row.get("source")}),
        "summary": summarize_filings(merged),
        "filings": merged,
    }

    from value_investor.storage import resolve_json_path, write_json

    index_path = filings_dir / "filings_index.json"
    write_json(index_path, index, compact=True, compress=False)
    written = resolve_json_path(index_path) or index_path

    return {
        "filings_index_path": str(written),
        "filings_dir": str(filings_dir),
        "filings_summary": index["summary"],
        "filings_sources": index["sources_used"],
    }
