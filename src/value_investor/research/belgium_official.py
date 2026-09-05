"""Belgium official-register / Euronext Brussels regulated-information harvest.

Identity (ISIN, CBE, MIC, LEI) is durable in ``issuer_identifiers``. Filing
influence stays time-bounded: lookback plus an official-annual floor, same
shape as the ESEF path. Only ``.BR`` tickers are queried.

The live Euronext product page is a Drupal app; ``/regulated-information``
often 302s to the quote page with no PDF hrefs. The HTML parser still harvests
direct document links when the register emits them. Do not call the
sales-gated Euronext Web Services gateway.
"""

from __future__ import annotations

import hashlib
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from html import unescape
from pathlib import Path
from typing import Any

from value_investor.research.issuer_identifiers import (
    cached_issuer_identity,
    save_issuer_identity,
)

logger = logging.getLogger(__name__)

HttpGet = Callable[..., bytes]

USER_AGENT = "value-investor-research/0.1 (+belgium-official)"
EURONEXT_LIVE_ORIGIN = "https://live.euronext.com"
# Match ESEF: ~2.2 years, keep two latest official period-ends if lookback is empty.
BELGIUM_LOOKBACK_DAYS = 800
BELGIUM_OFFICIAL_ANNUAL_FLOOR = 2
BELGIUM_MAX_ITEMS = 40

_DOC_ATTR_RE = re.compile(
    r"""(?:href|data-file|data-url|data-href|data-document)\s*=\s*["']([^"']+)["']""",
    re.I,
)
_DOC_EXT_RE = re.compile(r"\.(pdf|xhtml|html|htm|zip)(?:[?#].*)?$", re.I)
_SKIP_HREF_RE = re.compile(r"^(javascript:|mailto:|#)", re.I)
_KEYWORD_RE = re.compile(
    r"annual|interim|half[-\s]?year|quarter|q[1-4]|regulated|results|"
    r"financial|report|accounts|full[-\s]?year|year[-\s]?end|"
    r"jaarverslag|semestr|rapport|comptes",
    re.I,
)
_ISO_DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")
_DMY_DATE_RE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b")
_TEXT_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+"
    r"(january|february|march|april|may|june|july|august|september|october|"
    r"november|december|janvier|février|fevrier|mars|avril|mai|juin|juillet|"
    r"août|aout|septembre|octobre|novembre|décembre|decembre|"
    r"januari|februari|maart|april|mei|juni|juli|augustus|september|"
    r"oktober|november|december)\s+(20\d{2})\b",
    re.I,
)
_MONTHS = {
    "january": 1,
    "januari": 1,
    "janvier": 1,
    "february": 2,
    "februari": 2,
    "février": 2,
    "fevrier": 2,
    "march": 3,
    "maart": 3,
    "mars": 3,
    "april": 4,
    "avril": 4,
    "may": 5,
    "mei": 5,
    "mai": 5,
    "june": 6,
    "juni": 6,
    "juin": 6,
    "july": 7,
    "juli": 7,
    "juillet": 7,
    "august": 8,
    "augustus": 8,
    "août": 8,
    "aout": 8,
    "september": 9,
    "septembre": 9,
    "october": 10,
    "oktober": 10,
    "octobre": 10,
    "november": 11,
    "novembre": 11,
    "december": 12,
    "décembre": 12,
    "decembre": 12,
}


def is_brussels_ticker(ticker: str) -> bool:
    return (ticker or "").strip().upper().endswith(".BR")


def euronext_regulated_info_url(isin: str, mic: str = "XBRU") -> str:
    clean_isin = re.sub(r"[^A-Z0-9]", "", (isin or "").strip().upper())
    clean_mic = re.sub(r"[^A-Z]", "", (mic or "XBRU").strip().upper()) or "XBRU"
    return (
        f"{EURONEXT_LIVE_ORIGIN}/en/product/equities/{clean_isin}-{clean_mic}/regulated-information"
    )


def resolve_belgium_identity(
    ticker: str,
    *,
    path: Path | None = None,
    persist: bool = True,
) -> dict[str, str]:
    """Return ISIN / CBE / MIC / LEI for a leftover Belgian name."""
    row = cached_issuer_identity(ticker, path=path)
    identity = {
        "lei": str(row.get("lei") or ""),
        "lei_name": str(row.get("lei_name") or ""),
        "lei_country": str(row.get("lei_country") or ""),
        "isin": str(row.get("isin") or ""),
        "cbe": str(row.get("cbe") or ""),
        "mic": str(row.get("mic") or "XBRU"),
    }
    if persist and (identity["isin"] or identity["cbe"] or identity["lei"]):
        try:
            save_issuer_identity(
                ticker,
                path=path,
                lei=identity["lei"],
                lei_name=identity["lei_name"],
                lei_country=identity["lei_country"],
                isin=identity["isin"],
                cbe=identity["cbe"],
                mic=identity["mic"],
                source="belgium_official",
            )
        except (OSError, ValueError, TypeError) as exc:
            logger.debug("Persist Belgium identity for %s failed: %s", ticker, exc)
    return identity


def _http_get(url: str, *, headers: dict[str, str] | None = None, timeout: int = 25) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            **(headers or {}),
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _absolute_url(href: str, page_url: str) -> str | None:
    raw = unescape((href or "").strip())
    if not raw or _SKIP_HREF_RE.match(raw):
        return None
    if raw.startswith("//"):
        raw = "https:" + raw
    joined = urllib.parse.urljoin(page_url, raw)
    parsed = urllib.parse.urlparse(joined)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return joined


def _strip_tags(html: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    return unescape(re.sub(r"\s+", " ", text)).strip()


def _headline_near(html: str, href: str) -> str:
    idx = html.find(href)
    if idx < 0:
        return ""
    window = html[max(0, idx - 280) : idx + len(href) + 280]
    text = _strip_tags(window)
    if not text:
        return ""
    # Prefer the nearest non-trivial phrase.
    parts = [part.strip(" -–|/.,") for part in re.split(r"\s{2,}|[|•]", text) if part.strip()]
    for part in parts:
        if 8 <= len(part) <= 180 and not part.lower().startswith("http"):
            return part
    return text[:180]


def _parse_date(blob: str) -> str | None:
    iso = _ISO_DATE_RE.search(blob)
    if iso:
        try:
            datetime.strptime(iso.group(1), "%Y-%m-%d")
        except ValueError:
            pass
        else:
            return iso.group(1)
    text = _TEXT_DATE_RE.search(blob)
    if text:
        month = _MONTHS.get(text.group(2).lower())
        if month:
            return f"{text.group(3)}-{month:02d}-{int(text.group(1)):02d}"
    dmy = _DMY_DATE_RE.search(blob)
    if dmy:
        day, month, year = int(dmy.group(1)), int(dmy.group(2)), dmy.group(3)
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year}-{month:02d}-{day:02d}"
    return None


def _classify_period(headline: str) -> str:
    lower = (headline or "").lower()
    if re.search(r"half[-\s]?year|interim|semestr|q[1-4]|quarter", lower):
        return "interim"
    if re.search(r"annual|jaarverslag|full[-\s]?year|year[-\s]?end|accounts", lower):
        return "annual"
    return "other"


def _priority(headline: str, period: str) -> int:
    score = 20
    if period == "annual":
        score += 100
    elif period == "interim":
        score += 80
    if _KEYWORD_RE.search(headline or ""):
        score += 10
    return score


def _filing_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def _period_end_dt(value: str) -> datetime | None:
    raw = (value or "")[:10]
    try:
        return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def apply_belgium_recency_bound(
    rows: list[dict[str, Any]],
    *,
    lookback_days: int = BELGIUM_LOOKBACK_DAYS,
    official_annual_floor: int = BELGIUM_OFFICIAL_ANNUAL_FLOOR,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Keep recent rows; if the window is empty, keep the latest official period-ends."""
    now_dt = now or datetime.now(UTC)
    cutoff = now_dt - timedelta(days=max(0, int(lookback_days)))
    recent: list[dict[str, Any]] = []
    older: list[dict[str, Any]] = []
    for row in rows:
        period_dt = _period_end_dt(str(row.get("period_end") or row.get("published_at") or ""))
        if period_dt is None or period_dt >= cutoff:
            recent.append(row)
        else:
            older.append(row)
    if recent:
        return recent
    floor = max(0, int(official_annual_floor))
    if floor <= 0 or not older:
        return []
    older_sorted = sorted(
        older,
        key=lambda row: str(row.get("period_end") or row.get("published_at") or ""),
        reverse=True,
    )
    kept: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in older_sorted:
        period_end = str(row.get("period_end") or "")[:10]
        if period_end in seen:
            continue
        seen.add(period_end)
        kept.append(row)
        if len(kept) >= floor:
            break
    return kept


def parse_euronext_regulated_info_html(
    html: str,
    *,
    page_url: str,
    ticker: str = "",
) -> list[dict[str, Any]]:
    """Harvest PDF / XHTML / zip document links from a regulated-info HTML page."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in _DOC_ATTR_RE.finditer(html or ""):
        href = match.group(1)
        if not _DOC_EXT_RE.search(urllib.parse.urlparse(href).path):
            continue
        url = _absolute_url(href, page_url)
        if not url or url in seen:
            continue
        headline = _headline_near(html, href) or urllib.parse.unquote(
            Path(urllib.parse.urlparse(url).path).name
        )
        blob = f"{headline} {url}"
        if not _KEYWORD_RE.search(blob):
            continue
        period = _classify_period(headline)
        published = _parse_date(blob)
        period_end = published or ""
        seen.add(url)
        rows.append(
            {
                "id": _filing_id("belgium_official", url),
                "source": "belgium_official",
                "headline": headline or f"Euronext Brussels filing {ticker}".strip(),
                "published_at": f"{published}T00:00:00+00:00" if published else None,
                "url": url,
                "period": period,
                "period_end": period_end,
                "category": "EURONEXT_BRUSSELS",
                "summary": headline,
                "has_body": False,
                "body_path": None,
                "priority": _priority(headline, period),
                "isin": "",
            }
        )
    return rows


def fetch_filings_belgium_official(
    *,
    ticker: str,
    company_name: str = "",
    max_items: int = BELGIUM_MAX_ITEMS,
    lookback_days: int = BELGIUM_LOOKBACK_DAYS,
    official_annual_floor: int = BELGIUM_OFFICIAL_ANNUAL_FLOOR,
    identity_path: Path | None = None,
    persist_identity: bool = True,
    http_get: HttpGet | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Listing-only harvest of Euronext Brussels regulated-information documents."""
    if not is_brussels_ticker(ticker):
        return []
    identity = resolve_belgium_identity(
        ticker,
        path=identity_path,
        persist=persist_identity,
    )
    isin = identity.get("isin") or ""
    if not isin:
        logger.info("Belgium official: no ISIN for %s — skip Euronext harvest", ticker)
        return []
    page_url = euronext_regulated_info_url(isin, identity.get("mic") or "XBRU")
    getter = http_get or _http_get
    try:
        html = getter(page_url, timeout=25).decode("utf-8", errors="replace")
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        UnicodeDecodeError,
        TypeError,
        ValueError,
    ) as exc:
        logger.warning("Belgium official fetch failed for %s: %s", ticker, exc)
        return []
    rows = parse_euronext_regulated_info_html(html, page_url=page_url, ticker=ticker)
    for row in rows:
        row["isin"] = isin
        row["cbe"] = identity.get("cbe") or ""
        row["entity_identifier"] = identity.get("lei") or isin
        if company_name and not row.get("headline"):
            row["headline"] = f"{company_name} Euronext Brussels filing"
    rows = apply_belgium_recency_bound(
        rows,
        lookback_days=lookback_days,
        official_annual_floor=official_annual_floor,
        now=now,
    )
    if len(rows) > max_items:
        rows = rows[: max(1, int(max_items))]
    if rows:
        logger.info("Belgium official: %s → %d filings", ticker, len(rows))
    return rows


__all__ = [
    "BELGIUM_LOOKBACK_DAYS",
    "BELGIUM_OFFICIAL_ANNUAL_FLOOR",
    "apply_belgium_recency_bound",
    "euronext_regulated_info_url",
    "fetch_filings_belgium_official",
    "is_brussels_ticker",
    "parse_euronext_regulated_info_html",
    "resolve_belgium_identity",
]
