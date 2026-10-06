"""Cision newsroom feed for Swedish issuers (``euro_filings`` regime).

Nasdaq Stockholm issuers distribute regulated releases (interim, year-end and
annual reports) through a newswire; most OMXS30 names use Cision. Each issuer
newsroom has a public per-company RSS feed (``robots.txt`` allows it):

    https://news.cision.com/<newsroom>/ListItems?format=rss&pageSize=400

Items carry title, link, date and a short description only. Report releases
link the full report as the first ``mb.cision.com/Main/…pdf`` attachment on
the release page; ingest resolves it (one page fetch per kept row) and falls
back to the release page itself. The listing-only discovery scan skips that
step.

Issuers are keyed by an explicit ticker → newsroom map (no name guessing: a
wrong newsroom would import another company's reports). H&M and NIBE do not
publish on Cision and stay on ESEF + IR allowlist + Google News.
"""

from __future__ import annotations

import hashlib
import html
import logging
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

logger = logging.getLogger(__name__)

HttpGet = Callable[..., bytes]

SOURCE = "cision_direct"
USER_AGENT = "value-investor-research/0.1 (+filings)"
CISION_BASE_URL = "https://news.cision.com"
CISION_PAGE_SIZE = 400
CISION_LOOKBACK_DAYS = 800
REFILING_WINDOW_DAYS = 10

# Verified newsrooms (2026-10-06): each feed lists that issuer's own interim /
# year-end reports. OMXS30 constituents; .ST names in euro_depth reuse them.
# Not mapped: ABB (no reports on Cision since 2023), Industrivärden and Lifco
# (feeds end 2010 / 2023), H&M and NIBE (not on Cision).
CISION_NEWSROOMS: dict[str, str] = {
    "ADDT-B.ST": "addtech",
    "ALFA.ST": "alfa-laval",
    "ASSA-B.ST": "assa-abloy",
    "ATCO-A.ST": "atlas-copco",
    "ATCO-B.ST": "atlas-copco",
    "AZN.ST": "astrazeneca",
    "BOL.ST": "boliden",
    "EPI-A.ST": "epiroc",
    "EPI-B.ST": "epiroc",
    "EQT.ST": "eqt",
    "ERIC-B.ST": "ericsson",
    "ESSITY-B.ST": "essity",
    "EVO.ST": "evolution",
    "HEXA-B.ST": "hexagon",
    "INVE-B.ST": "investor",
    "NDA-SE.ST": "nordea",
    "SAAB-B.ST": "saab",
    "SAND.ST": "sandvik",
    "SCA-B.ST": "sca",
    "SEB-A.ST": "seb",
    "SHB-A.ST": "handelsbanken",
    "SKA-B.ST": "skanska",
    "SKF-B.ST": "skf",
    "SWED-A.ST": "swedbank",
    "TEL2-B.ST": "tele2-ab",
    "TELIA.ST": "telia-company",
    "VOLV-B.ST": "ab-volvo",
}

# Newest rows kept per kind; sum (8) stays under the 12-body ingest cap.
CISION_KIND_QUOTAS: dict[str, int] = {
    "final_results": 2,
    "annual_report": 2,
    "interim_results": 2,
    "quarterly_update": 2,
}
CISION_MAX_ITEMS = sum(CISION_KIND_QUOTAS.values())

_KIND_PERIOD_PRIORITY: dict[str, tuple[str, int]] = {
    "final_results": ("annual", 120),
    "annual_report": ("annual", 110),
    "interim_results": ("interim", 100),
    "quarterly_update": ("trading_update", 80),
}

_NOT_REPORT_RE = re.compile(
    r"invitation|inbjudan|webcast|webbs[äa]nd|conference call|telephone conference|"
    r"presentation of|to present|will present|to publish|will publish|publication date|"
    r"capital markets day|financial calendar|general meeting|st[äa]mma|nomination|"
    r"buy-?back|repurchase|own shares|egna aktier|voting rights|prospectus|bond|"
    r"silent period|correction|changed date|comments on|(?:will|to) be presented|"
    r"filing of|filed with",
    re.I,
)
# Deal news can name a quarter ("approvals anticipated in Q1 2026"); report
# headlines that also mention a deal ("Q4 2024: … announced acquisition") stay.
_DEAL_RE = re.compile(r"merger|acquisition|acquires|agreement|tender offer", re.I)
_REPORT_HEADLINE_RE = re.compile(
    r"\bQ[1-4](?:\s+20\d{2})?\s*:|\breport\b|\bresults\b|rapport|bokslutskommunik",
    re.I,
)
_ANNUAL_REPORT_RE = re.compile(
    r"annual (?:and sustainability )?report|annual review|[åa]rs(?:- och h[åa]llbarhets)?redovisning|"
    r"\b20-F\b",
    re.I,
)
_FULL_YEAR_RE = re.compile(
    r"year[- ]end report|full[- ]year|fourth[- ]quarter|\bQ4\b|"
    r"january\s*-+\s*december|bokslutskommunik[ée]|helår",
    re.I,
)
_QUARTER_RE = re.compile(
    r"\bQ[13]\b|first[- ]quarter|third[- ]quarter|nine[- ]months?|"
    r"january\s*-+\s*(?:march|september)|f[öo]rsta kvartalet|tredje kvartalet",
    re.I,
)
_HALF_RE = re.compile(
    r"\bQ2\b|second[- ]quarter|half[- ]year|six[- ]months?|"
    r"january\s*-+\s*june|andra kvartalet|halv[åa]r",
    re.I,
)
_REPORT_RE = re.compile(
    r"interim report|quarterly report|del[åa]rsrapport|kvartalsrapport|\bresults?\b|"
    r"\bQ[1-4]\b|quarter|year[- ]end report|full[- ]year|half[- ]year|bokslutskommunik",
    re.I,
)
_DASHES_RE = re.compile(r"[\u2010-\u2015\u2212]")
_ITEM_RE = re.compile(r"<item>(.*?)</item>", re.S)
_ATTACHMENT_RE = re.compile(r'href="(https://mb\.cision\.com/Main/[^"\s]+?\.pdf)"', re.I)
_RELEASE_ID_RE = re.compile(r",c(\d+)(?:$|[/?#])")


def cision_newsroom(ticker: str) -> str | None:
    return CISION_NEWSROOMS.get(str(ticker or "").strip().upper())


def cision_eligible(ticker: str) -> bool:
    return cision_newsroom(ticker) is not None


def cision_feed_url(newsroom: str, *, page_size: int = CISION_PAGE_SIZE) -> str:
    return f"{CISION_BASE_URL}/{newsroom}/ListItems?format=rss&pageSize={page_size}"


def _http_get(url: str, *, timeout: int = 30) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _filing_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def _tag(block: str, name: str) -> str:
    match = re.search(rf"<{name}>(.*?)</{name}>", block, re.S)
    if not match:
        return ""
    text = match.group(1).strip()
    if text.startswith("<![CDATA[") and text.endswith("]]>"):
        text = text[len("<![CDATA[") : -len("]]>")]
    return " ".join(html.unescape(text).split())


def parse_cision_rss(payload: bytes | str) -> list[dict[str, Any]]:
    """RSS items as ``{title, link, published, description}`` dicts."""
    text = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else payload
    items: list[dict[str, Any]] = []
    for block in _ITEM_RE.findall(text or ""):
        try:
            published = parsedate_to_datetime(_tag(block, "pubDate"))
        except (TypeError, ValueError, IndexError):
            published = None
        if published is not None and published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        items.append(
            {
                "title": _tag(block, "title"),
                "link": _tag(block, "link"),
                "published": published,
                "description": _tag(block, "description"),
            }
        )
    return items


def classify_cision_release(
    title: str, published: datetime | None = None
) -> tuple[str, str, int] | None:
    """Map a release headline to ``(kind, period, priority)``; ``None`` drops it."""
    title = _DASHES_RE.sub("-", " ".join(str(title or "").split()))
    if not title or _NOT_REPORT_RE.search(title):
        return None
    if _DEAL_RE.search(title) and not _REPORT_HEADLINE_RE.search(title):
        return None
    kind: str | None = None
    if (
        _ANNUAL_REPORT_RE.search(title)
        and not _FULL_YEAR_RE.search(title)
        and not re.search(r"interim|quarter|kvartal", title, re.I)
    ):
        kind = "annual_report"
    elif _FULL_YEAR_RE.search(title):
        kind = "final_results"
    elif _QUARTER_RE.search(title):
        kind = "quarterly_update"
    elif _HALF_RE.search(title):
        kind = "interim_results"
    elif _REPORT_RE.search(title) and re.search(
        r"interim report|quarterly report|del[åa]rsrapport|kvartalsrapport", title, re.I
    ):
        # Undated "Interim report": period from the release month.
        if published is None:
            return None
        if published.month <= 3:
            kind = "final_results"
        elif 7 <= published.month <= 9:
            kind = "interim_results"
        else:
            kind = "quarterly_update"
    if kind is None:
        return None
    period, priority = _KIND_PERIOD_PRIORITY[kind]
    return kind, period, priority


def release_id(link: str) -> str:
    match = _RELEASE_ID_RE.search(str(link or ""))
    return match.group(1) if match else ""


def cision_item_to_filing(
    item: dict[str, Any], *, newsroom: str, cutoff: datetime | None = None
) -> dict[str, Any] | None:
    link = str(item.get("link") or "").strip()
    if not link.startswith(f"{CISION_BASE_URL}/{newsroom}/"):
        return None
    published = item.get("published")
    if cutoff is not None and published is not None and published < cutoff:
        return None
    title = str(item.get("title") or "")
    classified = classify_cision_release(title, published)
    if classified is None:
        return None
    kind, period, priority = classified
    rid = release_id(link)
    return {
        "id": _filing_id(SOURCE, rid or link),
        "source": SOURCE,
        "headline": title,
        "published_at": published.isoformat() if published else None,
        "url": link,
        "release_url": link,
        "period": period,
        "cision_period": period,
        "cision_kind": kind,
        "cision_newsroom": newsroom,
        "cision_release_id": rid or None,
        "category": "Regulatory report",
        "summary": str(item.get("description") or title)[:400],
        "has_body": False,
        "body_path": None,
        "priority": priority,
    }


def _is_refiling(row: dict[str, Any], kept: list[dict[str, Any]]) -> bool:
    """Same release, or same kind + headline within ``REFILING_WINDOW_DAYS`` (correction)."""
    headline = str(row.get("headline") or "").lower()
    published = row.get("published_at") or ""
    for other in kept:
        if other.get("release_url") == row.get("release_url"):
            return True
        if other.get("cision_kind") != row.get("cision_kind"):
            continue
        if str(other.get("headline") or "").lower() != headline:
            continue
        try:
            gap = abs(
                datetime.fromisoformat(str(other.get("published_at")))
                - datetime.fromisoformat(str(published))
            )
        except ValueError:
            return True
        if gap <= timedelta(days=REFILING_WINDOW_DAYS):
            return True
    return False


def select_rows_by_kind_quota(
    rows: list[dict[str, Any]], quotas: dict[str, int] | None = None
) -> list[dict[str, Any]]:
    """Newest rows per ``cision_kind`` up to its quota, returned newest first."""
    quotas = CISION_KIND_QUOTAS if quotas is None else quotas
    newest_first = sorted(rows, key=lambda r: r.get("published_at") or "", reverse=True)
    taken: dict[str, int] = {}
    kept: list[dict[str, Any]] = []
    for row in newest_first:
        kind = str(row.get("cision_kind") or "")
        if taken.get(kind, 0) >= int(quotas.get(kind, 0)):
            continue
        taken[kind] = taken.get(kind, 0) + 1
        kept.append(row)
    return kept


def report_attachment_url(page: bytes | str) -> str | None:
    """First ``mb.cision.com/Main`` PDF on a release page (the report itself)."""
    text = page.decode("utf-8", "replace") if isinstance(page, bytes) else page
    match = _ATTACHMENT_RE.search(text or "")
    return html.unescape(match.group(1)) if match else None


def fetch_filings_cision_direct(
    *,
    ticker: str,
    company_name: str = "",
    max_items: int = CISION_MAX_ITEMS,
    lookback_days: int = CISION_LOOKBACK_DAYS,
    resolve_attachments: bool = True,
    http_get: HttpGet | None = None,
) -> list[dict[str, Any]]:
    """Interim, year-end and annual report releases for one mapped Swedish issuer."""
    del company_name  # Issuer-scoped by the newsroom map.
    newsroom = cision_newsroom(ticker)
    if newsroom is None:
        return []
    getter = http_get or _http_get
    try:
        payload = getter(cision_feed_url(newsroom), timeout=40)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("Cision feed failed for %s (%s): %s", ticker, newsroom, exc)
        return []
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    items = sorted(
        parse_cision_rss(payload),
        key=lambda i: i.get("published") or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    rows: list[dict[str, Any]] = []
    for item in items:
        row = cision_item_to_filing(item, newsroom=newsroom, cutoff=cutoff)
        if row is not None and not _is_refiling(row, rows):
            rows.append(row)
    rows = select_rows_by_kind_quota(rows)[:max_items]
    if resolve_attachments:
        for row in rows:
            try:
                attachment = report_attachment_url(getter(row["release_url"], timeout=30))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                logger.info("Cision release page failed for %s: %s", row["release_url"], exc)
                continue
            if attachment:
                row["url"] = attachment
    if rows:
        logger.info("Cision direct: %s → %d filings", ticker, len(rows))
    return rows


__all__ = [
    "CISION_KIND_QUOTAS",
    "CISION_MAX_ITEMS",
    "CISION_NEWSROOMS",
    "SOURCE",
    "cision_eligible",
    "cision_feed_url",
    "cision_item_to_filing",
    "cision_newsroom",
    "classify_cision_release",
    "fetch_filings_cision_direct",
    "parse_cision_rss",
    "report_attachment_url",
    "select_rows_by_kind_quota",
]
