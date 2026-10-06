"""HKEXnews direct announcement feed for ``.HK`` tickers (``asia_filings`` regime).

HKEXnews exposes the same public JSON its own title-search page uses: a stock
prefix lookup (code → internal ``stockId``) and a title search filtered by
headline category. Two category queries per ticker:

* results group (``t1code=10000``, ``t2Gcode=3``) — final / interim / quarterly
  results announcements and profit warnings;
* financial statements (``t1code=40000``) — annual and interim reports.

The category label (``LONG_TEXT``) is authoritative for ``period``; headlines
like "ANNOUNCEMENT OF THE RESULTS FOR THE THREE MONTHS ENDED…" do not classify
reliably. Board-meeting dates, dividend forms and ESG reports are dropped.

SGX has no equivalent: ``api.sgx.com`` announcements are token-gated at the edge.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from html import unescape
from typing import Any

logger = logging.getLogger(__name__)

HttpGet = Callable[..., bytes]

SOURCE = "hkex_direct"
USER_AGENT = "value-investor-research/0.1 (+filings)"
HKEXNEWS_SEARCH_BASE = "https://www1.hkexnews.hk/search"
HKEX_PREFIX_URL = HKEXNEWS_SEARCH_BASE + "/prefix.do"
HKEX_TITLE_SEARCH_URL = HKEXNEWS_SEARCH_BASE + "/titleSearchServlet.do"
# Same host the hand-seeded IR allowlist uses, so URLs dedupe against it.
HKEX_DOCUMENT_ORIGIN = "https://www.hkexnews.hk"
HKEX_LOOKBACK_DAYS = 800
HKEX_MAX_ITEMS = 16
HKEX_ROW_RANGE = 100

HKEX_CATEGORY_QUERIES: tuple[dict[str, str], ...] = (
    {"t1code": "10000", "t2Gcode": "3"},
    {"t1code": "40000", "t2Gcode": "-2"},
)

# Ordered: first match wins. Values are (period, priority bonus). Results
# announcements carry full statements in a few hundred KB; annual/interim
# reports are multi-MB and truncated at the body cap, so rank them second.
_CATEGORY_RULES: tuple[tuple[re.Pattern[str], str, int], ...] = (
    (re.compile(r"environmental,\s*social|\besg report\b", re.I), "skip", 0),
    (re.compile(r"\bfinal results\b", re.I), "annual", 120),
    (re.compile(r"\binterim results\b", re.I), "interim", 100),
    (re.compile(r"\bquarterly results\b", re.I), "interim", 95),
    (re.compile(r"\bannual report\b", re.I), "annual", 110),
    (re.compile(r"\binterim/half-year report\b", re.I), "interim", 90),
    (re.compile(r"\bquarterly report\b", re.I), "interim", 85),
    (re.compile(r"\bprofit warning\b", re.I), "trading_update", 70),
)

_JSONP_RE = re.compile(r"^\s*\w+\((.*)\)\s*;?\s*$", re.S)
_HK_CODE_RE = re.compile(r"^(\d{1,5})\.HK$", re.I)

_stock_id_cache: dict[str, int | None] = {}


def hk_stock_code(ticker: str) -> str | None:
    """``2382.HK`` → ``02382`` (HKEX five-digit code); ``None`` for non-HK tickers."""
    match = _HK_CODE_RE.match(str(ticker or "").strip())
    if not match:
        return None
    return match.group(1).zfill(5)


def is_hkex_ticker(ticker: str) -> bool:
    return hk_stock_code(ticker) is not None


def _http_get(url: str, *, timeout: int = 30) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/javascript"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _filing_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def parse_prefix_response(payload: str, code: str) -> int | None:
    """Return the HKEX ``stockId`` for an exact five-digit ``code`` from JSONP."""
    match = _JSONP_RE.match(payload or "")
    body = match.group(1) if match else payload
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None
    for item in data.get("stockInfo") or []:
        if str(item.get("code") or "") == code:
            try:
                return int(item["stockId"])
            except (KeyError, TypeError, ValueError):
                return None
    return None


def resolve_hkex_stock_id(ticker: str, *, http_get: HttpGet | None = None) -> int | None:
    code = hk_stock_code(ticker)
    if code is None:
        return None
    if code in _stock_id_cache:
        return _stock_id_cache[code]
    getter = http_get or _http_get
    params = urllib.parse.urlencode(
        {"callback": "callback", "lang": "EN", "type": "A", "name": code, "market": "SEHK"}
    )
    try:
        payload = getter(f"{HKEX_PREFIX_URL}?{params}", timeout=30).decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("HKEX stock lookup failed for %s: %s", ticker, exc)
        return None
    stock_id = parse_prefix_response(payload, code)
    _stock_id_cache[code] = stock_id
    return stock_id


def classify_hkex_category(long_text: str) -> tuple[str, int] | None:
    """Map an HKEX headline category to ``(period, priority)``; ``None`` drops the row."""
    label = unescape(long_text or "")
    for pattern, period, priority in _CATEGORY_RULES:
        if pattern.search(label):
            return None if period == "skip" else (period, priority)
    return None


def _parse_hkex_datetime(value: str) -> datetime | None:
    try:
        # HKEX publishes in Hong Kong time (UTC+8).
        local = datetime.strptime(value.strip(), "%d/%m/%Y %H:%M")
    except (ValueError, AttributeError):
        return None
    return (local - timedelta(hours=8)).replace(tzinfo=UTC)


def _title_search_url(stock_id: int, query: dict[str, str], *, lookback_days: int) -> str:
    today = datetime.now(UTC)
    params = {
        "sortDir": "0",
        "sortByOptions": "DateTime",
        "category": "0",
        "market": "SEHK",
        "stockId": str(stock_id),
        "documentType": "-1",
        "fromDate": (today - timedelta(days=lookback_days)).strftime("%Y%m%d"),
        "toDate": today.strftime("%Y%m%d"),
        "title": "",
        "searchType": "1",
        "t1code": query["t1code"],
        "t2Gcode": query["t2Gcode"],
        "t2code": "-2",
        "rowRange": str(HKEX_ROW_RANGE),
        "lang": "E",
    }
    return f"{HKEX_TITLE_SEARCH_URL}?{urllib.parse.urlencode(params)}"


def parse_title_search_payload(payload: bytes | str) -> list[dict[str, Any]]:
    """Decode ``{"result": "<json array string>"}`` into raw HKEX rows."""
    text = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else payload
    try:
        outer = json.loads(text)
        inner = outer.get("result")
        rows = json.loads(inner) if isinstance(inner, str) and inner.strip() else []
    except (json.JSONDecodeError, AttributeError, TypeError):
        return []
    return [row for row in rows if isinstance(row, dict)]


def hkex_document_url(file_link: str) -> str | None:
    link = str(file_link or "").strip()
    if not link:
        return None
    if link.startswith("http"):
        return link
    return HKEX_DOCUMENT_ORIGIN + ("" if link.startswith("/") else "/") + link


def hkex_row_to_filing(
    raw: dict[str, Any], *, cutoff: datetime | None = None
) -> dict[str, Any] | None:
    classified = classify_hkex_category(str(raw.get("LONG_TEXT") or ""))
    if classified is None:
        return None
    period, priority = classified
    url = hkex_document_url(str(raw.get("FILE_LINK") or ""))
    headline = " ".join(unescape(str(raw.get("TITLE") or "")).split())
    if not url or not headline:
        return None
    published_dt = _parse_hkex_datetime(str(raw.get("DATE_TIME") or ""))
    if cutoff is not None and published_dt is not None and published_dt < cutoff:
        return None
    category = unescape(str(raw.get("LONG_TEXT") or "")).strip()
    news_id = str(raw.get("NEWS_ID") or "").strip()
    return {
        "id": _filing_id(SOURCE, news_id or url),
        "source": SOURCE,
        "headline": headline,
        "published_at": published_dt.isoformat() if published_dt else None,
        "url": url,
        "period": period,
        "hkex_period": period,
        "category": category or None,
        "summary": headline,
        "has_body": False,
        "body_path": None,
        "priority": priority,
        "hkex_news_id": news_id or None,
        "file_type": str(raw.get("FILE_TYPE") or "").strip() or None,
        "file_info": str(raw.get("FILE_INFO") or "").strip() or None,
    }


def fetch_filings_hkex_direct(
    *,
    ticker: str,
    company_name: str = "",
    max_items: int = HKEX_MAX_ITEMS,
    lookback_days: int = HKEX_LOOKBACK_DAYS,
    http_get: HttpGet | None = None,
) -> list[dict[str, Any]]:
    """Results announcements and periodic reports for one ``.HK`` ticker."""
    del company_name  # Symbol-scoped feed; issuer relevance is implied by stockId.
    stock_id = resolve_hkex_stock_id(ticker, http_get=http_get)
    if stock_id is None:
        return []
    getter = http_get or _http_get
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for query in HKEX_CATEGORY_QUERIES:
        url = _title_search_url(stock_id, query, lookback_days=lookback_days)
        try:
            payload = getter(url, timeout=40)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning("HKEX title search failed for %s (%s): %s", ticker, query, exc)
            continue
        for raw in parse_title_search_payload(payload):
            row = hkex_row_to_filing(raw, cutoff=cutoff)
            if row is None or row["url"] in seen:
                continue
            seen.add(row["url"])
            rows.append(row)
    rows.sort(key=lambda r: r.get("published_at") or "", reverse=True)
    rows = _cap_rows(rows, max_items)
    if rows:
        logger.info("HKEX direct: %s → %d announcements", ticker, len(rows))
    return rows


def _cap_rows(rows: list[dict[str, Any]], max_items: int) -> list[dict[str, Any]]:
    """Keep the newest ``max_items`` rows, reserving the latest annual and interim."""
    if len(rows) <= max_items:
        return rows
    reserved: list[dict[str, Any]] = []
    for period in ("annual", "interim"):
        latest = next((r for r in rows if r["period"] == period), None)
        if latest is not None:
            reserved.append(latest)
    reserved = reserved[:max_items]
    reserved_ids = {id(r) for r in reserved}
    rest = [r for r in rows if id(r) not in reserved_ids][: max_items - len(reserved)]
    return sorted(reserved + rest, key=lambda r: r.get("published_at") or "", reverse=True)


def normalize_hkexnews_url(url: str) -> str:
    """Host-insensitive key for hkexnews document URLs (``www`` vs ``www1``)."""
    text = str(url or "").strip()
    return re.sub(r"^https?://www1?\.hkexnews\.hk", HKEX_DOCUMENT_ORIGIN, text, flags=re.I)


def drop_allowlist_rows_covered_by_hkex(
    allowlist_rows: list[dict[str, Any]], hkex_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Drop hand-seeded IR allowlist rows whose PDF the direct feed already indexes."""
    covered = {normalize_hkexnews_url(str(r.get("url") or "")) for r in hkex_rows}
    if not covered:
        return allowlist_rows
    return [
        row
        for row in allowlist_rows
        if normalize_hkexnews_url(str(row.get("url") or "")) not in covered
    ]
