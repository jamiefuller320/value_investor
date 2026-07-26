"""Primary regulatory filings for research memos (separate from Yahoo).

Memo-eligible names only. Yahoo remains the screening source; this module
collects primary filings for FINANCIAL REVIEW.

Regimes:
- ``uk_rns`` (FTSE / ``.L``): Ticker.app RNS API + Investegate via Google News
- ``sec_edgar`` (S&P 500 / bare US tickers): SEC EDGAR submissions + HTML bodies
- ``asx_announcements`` (ASX 200 / ``.AX``): Markit Digital JSON feed (direct PDFs) + Google News fallback
- ``euro_filings`` (EURO STOXX 50 / DAX / CAC): results headlines via Google News + SEC 20-F/6-K when dual-listed
- ``tsx_announcements`` (TSX 60 / ``.TO``): SEDAR+ / issuer headlines via Google News

Interim vs annual is classified from form type (10-K/10-Q) or headline cues.
"""

from __future__ import annotations

import gzip
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
CH_OCR_MAX_PAGES = int(os.environ.get("COMPANIES_HOUSE_OCR_MAX_PAGES", "12"))
CH_OCR_DPI = int(os.environ.get("COMPANIES_HOUSE_OCR_DPI", "150"))
TICKER_API_BASE = "https://api.tickerapp.net/v2"
DEFAULT_IR_URLS_PATH = Path("docs/data/research_ir_urls.json")
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
SEC_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/{document}"
SEC_ANNUAL_FORMS = frozenset({"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"})
SEC_INTERIM_FORMS = frozenset({"10-Q", "10-Q/A", "6-K"})
SEC_OTHER_FORMS = frozenset({"8-K", "8-K/A"})
SEC_FORM_ALLOWLIST = SEC_ANNUAL_FORMS | SEC_INTERIM_FORMS | SEC_OTHER_FORMS
ASX_MARKIT_API_BASE = "https://asx.api.markitdigital.com/asx-research/1.0"
ASX_MARKIT_ANNOUNCEMENTS_URL = ASX_MARKIT_API_BASE + "/companies/{symbol}/announcements"
ASX_MARKIT_FILE_URL = ASX_MARKIT_API_BASE + "/file/{document_key}"
# Markit returns at most five rows per request (no public pagination).
ASX_MARKIT_MAX_ITEMS = 5
_ASX_SKIP_ANNOUNCEMENT_TYPES = frozenset(
    {
        "ISSUED CAPITAL",
        "SECURITY HOLDER DETAILS",
        "CHANGE OF AUDITOR",
        "CHANGE OF COMPANY DETAILS",
    }
)

_sec_ticker_cik_cache: dict[str, int] | None = None

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


_SEC_NARRATIVE_MARKERS: tuple[tuple[str, int], ...] = (
    (r"\bCONSOLIDATED (?:INCOME|STATEMENT OF COMPREHENSIVE)\b", 1),
    (r"\bFINANCIAL REVIEW\b", 2),
    (r"\bMANAGEMENT[\u2019']S DISCUSSION AND ANALYSIS\b", 2),
    (r"\bTABLE OF CONTENTS\b", 3),
    (r"\bITEM\s+1[\.\s\-–]", 4),
)
_SEC_XBRL_TOKEN = re.compile(
    r"\b(?:[a-z]{2,10}[-:]){1,3}[\w:-]+\b",
    flags=re.I,
)
_SEC_MEMBER_TOKEN = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+){3,}Member\b")


def _extract_sec_html_text(html: str) -> str:
    """Extract readable narrative text from SEC inline-XBRL HTML filings."""
    cleaned = re.sub(r"<ix:header[\s\S]*?</ix:header>", " ", html or "", flags=re.I)
    cleaned = re.sub(r"<ix:hidden[\s\S]*?</ix:hidden>", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"<!--[\s\S]*?-->", " ", cleaned)
    text = _strip_html(cleaned)

    best_start: int | None = None
    best_rank = 99
    for pattern, rank in _SEC_NARRATIVE_MARKERS:
        match = re.search(pattern, text, flags=re.I)
        if not match:
            continue
        start = match.start()
        if rank < best_rank or (rank == best_rank and (best_start is None or start < best_start)):
            best_rank = rank
            best_start = start
    if best_start:
        text = text[best_start:]

    text = _SEC_XBRL_TOKEN.sub(" ", text)
    text = re.sub(r"\b\d{10}\b", " ", text)
    text = re.sub(r"\b20\d{2}-\d{2}-\d{2}\b", " ", text)
    text = _SEC_MEMBER_TOKEN.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


_IXBRL_NARRATIVE_MARKERS: tuple[tuple[str, int], ...] = (
    (r"\bCONSOLIDATED (?:INCOME|STATEMENT OF COMPREHENSIVE|BALANCE SHEET|CASH FLOW)\b", 1),
    (r"\bSTRATEGIC REPORT\b", 2),
    (r"\bDIRECTORS[\u2019'] REPORT\b", 2),
    (r"\bNOTES TO THE (?:FINANCIAL|GROUP) STATEMENTS\b", 2),
    (r"\bGOING CONCERN\b", 3),
    (r"\bPENSION\b", 3),
)
_INVESTEGATE_COMPANY_URL = "https://www.investegate.co.uk/company/{epic}"
_INVESTEGATE_USER_AGENT = "value-investor-research/0.1 (+investegate; research@local)"
_INVESTEGATE_MAX_ITEMS = 50
_SUBSTANTIVE_FILING_TERMS = (
    "revenue",
    "earnings",
    "profit",
    "ebitda",
    "dividend",
    "million",
    "billion",
    "cash flow",
    "net debt",
    "pension",
    "going concern",
    "covenant",
    "borrowings",
    "results",
)


def _is_ixbrl_html(raw: bytes | str) -> bool:
    sample = raw[:8000] if isinstance(raw, bytes) else (raw or "")[:8000]
    if isinstance(sample, bytes):
        sample = sample.decode("utf-8", errors="ignore")
    lower = sample.lower()
    return "xmlns:ix=" in lower or "<ix:" in lower or "xbrl" in lower


def _extract_ixbrl_html_text(html: str) -> str:
    """Extract readable narrative from UK Companies House iXBRL/XHTML accounts."""
    cleaned = re.sub(r"<ix:header[\s\S]*?</ix:header>", " ", html or "", flags=re.I)
    cleaned = re.sub(r"<ix:hidden[\s\S]*?</ix:hidden>", " ", cleaned, flags=re.I)
    cleaned = re.sub(r"<!--[\s\S]*?-->", " ", cleaned)
    text = _strip_html(cleaned)

    best_start: int | None = None
    best_rank = 99
    for pattern, rank in _IXBRL_NARRATIVE_MARKERS:
        match = re.search(pattern, text, flags=re.I)
        if not match:
            continue
        start = match.start()
        if rank < best_rank or (rank == best_rank and (best_start is None or start < best_start)):
            best_rank = rank
            best_start = start
    if best_start:
        text = text[best_start:]

    text = _SEC_XBRL_TOKEN.sub(" ", text)
    text = re.sub(r"\b\d{10}\b", " ", text)
    text = re.sub(r"\b20\d{2}-\d{2}-\d{2}\b", " ", text)
    text = _SEC_MEMBER_TOKEN.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _score_ch_body_text(text: str) -> int:
    """Prefer iXBRL narrative and penalise OCR front-matter noise."""
    lower = (text or "").lower()
    score = min(len(text), 20_000)
    for term in _SUBSTANTIVE_FILING_TERMS:
        if term in lower:
            score += 400
    if lower.count("fontsymbol") > 2 or lower.count("|") > 30:
        score -= 2_000
    if "consolidated" in lower and "income" in lower:
        score += 800
    return score


def _extract_investegate_html_text(html: str) -> str:
    """Extract the RNS announcement body from an Investegate HTML page."""
    lower = (html or "").lower()
    start = lower.find("<h1")
    if start < 0:
        start = 0
    end_markers = (
        "related announcements",
        "cookie policy",
        "sign up for investor",
        "all information",
    )
    end = len(html)
    for marker in end_markers:
        pos = lower.find(marker, start)
        if pos > start:
            end = min(end, pos)
    chunk = html[start:end]
    text = _strip_html(chunk)
    text = re.sub(
        r"^.*?Summary by AI.*?(?=\b[A-Z0-9])",
        "",
        text,
        count=1,
        flags=re.I | re.S,
    )
    return re.sub(r"\s+", " ", text).strip()


def _filing_text_is_substantive(text: str, *, min_chars: int = 200) -> bool:
    if not text or len(text) < min_chars:
        return False
    lower = text.lower()
    hits = sum(1 for term in _SUBSTANTIVE_FILING_TERMS if term in lower)
    return hits >= 2 or len(text) >= 1_200


def _try_sec_exhibit_body(url: str) -> str | None:
    """When a 6-K primary doc is cover-only, try linked exhibits from the filing index."""
    match = re.match(
        r"(https://www\.sec\.gov/Archives/edgar/data/\d+/\d+)/([^/]+)$",
        url,
        flags=re.I,
    )
    if not match:
        return None
    base, _primary = match.groups()
    accession_nodash = base.rsplit("/", 1)[-1]
    if len(accession_nodash) != 18:
        return None
    accession = f"{accession_nodash[:10]}-{accession_nodash[10:12]}-{accession_nodash[12:]}"
    index_url = f"{base}/{accession}-index.htm"
    try:
        raw = _http_get(index_url, headers={"User-Agent": _sec_user_agent()}, timeout=40)
        html = raw.decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.debug("SEC index fetch failed for %s: %s", index_url, exc)
        return None

    candidates: list[str] = []
    for href in re.findall(r'href="([^"]+\.htm)"', html, flags=re.I):
        if any(skip in href.lower() for skip in ("-index.htm", ".xsd", ".xml", ".xsl")):
            continue
        if href.startswith("http"):
            candidates.append(href)
        else:
            candidates.append(f"{base}/{href.lstrip('/')}")
    for exhibit_url in candidates[:6]:
        body = fetch_filing_body(exhibit_url, allow_sec_exhibits=False)
        if body and _filing_text_is_substantive(body, min_chars=400):
            return body
    return None


def fetch_filings_investegate_company(
    *,
    ticker: str,
    company_name: str,
    max_items: int = _INVESTEGATE_MAX_ITEMS,
) -> list[dict[str, Any]]:
    """Fetch recent RNS announcements from the issuer's Investegate company page."""
    epic = _base_symbol(ticker)
    if not epic:
        return []
    url = _INVESTEGATE_COMPANY_URL.format(epic=urllib.parse.quote(epic))
    try:
        raw = _http_get(url, headers={"User-Agent": _INVESTEGATE_USER_AGENT}, timeout=40)
        html = raw.decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("Investegate company page failed for %s: %s", ticker, exc)
        return []

    rows: list[dict[str, Any]] = []
    pattern = re.compile(
        r'<tr>\s*<td>(\d{2} \w{3} \d{4})</td>\s*<td>([^<]*)</td>[\s\S]*?'
        r'href="(https://www\.investegate\.co\.uk/announcement/[^"]+)"[^>]*>'
        r'([^<]+)</a>',
        flags=re.I,
    )
    for match in pattern.finditer(html):
        date_s, _time_s, link, headline = match.groups()
        headline_clean = unescape(headline.strip())
        if not headline_relevant_to_issuer(headline_clean, company_name, ticker):
            continue
        try:
            published = (
                datetime.strptime(date_s, "%d %b %Y").replace(tzinfo=UTC).isoformat()
            )
        except ValueError:
            published = None
        period = classify_filing_period(headline_clean)
        rows.append(
            {
                "id": _filing_id("investegate", link),
                "source": "investegate_direct",
                "headline": headline_clean,
                "published_at": published,
                "url": link,
                "period": period,
                "category": None,
                "summary": headline_clean,
                "has_body": False,
                "body_path": None,
                "priority": 125 if period in ("annual", "interim") else 90,
            }
        )
        if len(rows) >= max_items:
            break
    if rows:
        logger.info("Investegate company page: %s → %d announcements", ticker, len(rows))
    return rows


def resolve_investegate_url(
    row: dict[str, Any],
    *,
    ticker: str,
    company_name: str,
    cache: list[dict[str, Any]] | None = None,
) -> str | None:
    """Resolve a Google News wrapper URL to a direct Investegate announcement URL."""
    url = str(row.get("url") or "")
    if "investegate.co.uk/announcement/" in url:
        return url
    if "news.google.com" not in url:
        return None
    candidates = cache or fetch_filings_investegate_company(
        ticker=ticker,
        company_name=company_name,
    )
    headline = str(row.get("headline") or "").strip().lower()
    headline = re.sub(r"\s*-\s*investegate\s*$", "", headline, flags=re.I)
    date_prefix = str(row.get("published_at") or "")[:10]
    for candidate in candidates:
        cand_headline = str(candidate.get("headline") or "").strip().lower()
        cand_date = str(candidate.get("published_at") or "")[:10]
        if date_prefix and cand_date and date_prefix != cand_date:
            continue
        if headline and (
            headline in cand_headline
            or cand_headline in headline
            or headline_relevant_to_issuer(cand_headline, headline, ticker)
        ):
            return str(candidate.get("url") or "") or None
    return None


def enrich_filing_rows(
    rows: list[dict[str, Any]],
    *,
    ticker: str,
    company_name: str,
) -> list[dict[str, Any]]:
    """Rewrite wrapper URLs and merge direct Investegate links where possible."""
    investegate_rows = fetch_filings_investegate_company(
        ticker=ticker,
        company_name=company_name,
    )
    by_url = {str(row.get("url") or ""): row for row in investegate_rows if row.get("url")}
    enriched: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for row in rows:
        item = dict(row)
        resolved = resolve_investegate_url(
            item,
            ticker=ticker,
            company_name=company_name,
            cache=investegate_rows,
        )
        if resolved:
            item["url"] = resolved
            if item.get("source") == "google_news_investegate":
                item["source"] = "investegate_resolved"
        url = str(item.get("url") or "")
        if url:
            seen_urls.add(url)
        enriched.append(item)
    for row in investegate_rows:
        url = str(row.get("url") or "")
        if url and url not in seen_urls:
            enriched.append(row)
            seen_urls.add(url)
    return enriched


_EXCHANGE_SUFFIXES = (
    ".L",
    ".AX",
    ".TO",
    ".DE",
    ".PA",
    ".AS",
    ".MI",
    ".BR",
    ".HE",
    ".MC",
    ".IR",
    ".LS",
    ".AT",
    ".SW",
    ".HK",
    ".SI",
)


def _epic(ticker: str) -> str:
    return ticker.replace(".L", "").replace(".l", "").strip().upper()


def _base_symbol(ticker: str) -> str:
    """Strip common Yahoo exchange suffixes for headline matching."""
    t = (ticker or "").strip().upper()
    for suf in _EXCHANGE_SUFFIXES:
        if t.endswith(suf):
            return t[: -len(suf)]
    return t


_ISSUER_STOPWORDS = frozenset(
    {
        "plc",
        "ltd",
        "limited",
        "group",
        "holdings",
        "holding",
        "company",
        "companies",
        "the",
        "and",
        "inc",
        "corp",
        "corporation",
        "sa",
        "ag",
        "nv",
        "se",
    }
)


def headline_relevant_to_issuer(headline: str, company_name: str, ticker: str) -> bool:
    """True when the headline mentions the EPIC or a meaningful company-name token."""
    text = (headline or "").lower()
    if not text:
        return False
    epic = _base_symbol(ticker).lower()
    if epic and re.search(rf"\b{re.escape(epic)}\b", text, flags=re.IGNORECASE):
        return True
    # ASX Markit headlines often end with " - CSL" / " - WOR".
    if epic and re.search(rf"[-–]\s*{re.escape(epic)}\s*$", text, flags=re.IGNORECASE):
        return True
    tokens = [
        tok
        for tok in re.split(r"[^a-z0-9]+", (company_name or "").lower())
        if len(tok) >= 4 and tok not in _ISSUER_STOPWORDS
    ]
    return any(tok in text for tok in tokens[:4])


def _companies_house_ocr_enabled() -> bool:
    flag = (os.environ.get("COMPANIES_HOUSE_OCR") or "1").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def _ocr_pdf_text(raw: bytes, *, max_pages: int | None = None) -> str | None:
    """OCR image-only PDF pages when pypdf returns no text layer."""
    if not _companies_house_ocr_enabled():
        return None
    try:
        import fitz  # pymupdf
        import pytesseract
        from PIL import Image
    except ImportError:
        logger.info(
            "Companies House OCR skipped — install pymupdf, pytesseract, Pillow "
            "and system tesseract-ocr"
        )
        return None

    page_limit = max_pages if max_pages is not None else CH_OCR_MAX_PAGES
    try:
        doc = fitz.open(stream=raw, filetype="pdf")
        scale = max(72, CH_OCR_DPI) / 72.0
        matrix = fitz.Matrix(scale, scale)
        chunks: list[str] = []
        for index, page in enumerate(doc):
            if index >= page_limit:
                break
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            page_text = (pytesseract.image_to_string(image) or "").strip()
            if page_text:
                chunks.append(page_text)
            joined = "\n\n".join(chunks)
            if len(joined) >= FILINGS_BODY_MAX_CHARS:
                break
        text = "\n\n".join(chunks).strip()
        if text:
            logger.info(
                "Companies House OCR extracted %s chars from %s page(s)",
                len(text),
                min(page_limit, len(doc)),
            )
        return text or None
    except Exception as exc:  # noqa: BLE001
        logger.debug("Companies House OCR failed: %s", exc)
        return None


def _extract_filing_document_text(raw: bytes, content_type: str) -> str | None:
    """Extract searchable text from a filing document (PDF, HTML, or iXBRL)."""
    if raw[:4] == b"%PDF" or "pdf" in (content_type or "").lower():
        text = _extract_pdf_text(raw)
        if text and len(text) >= 200:
            return text
        ocr_text = _ocr_pdf_text(raw)
        return ocr_text or text
    if _is_ixbrl_html(raw) or "xhtml" in (content_type or "").lower():
        return _extract_ixbrl_html_text(raw.decode("utf-8", errors="replace"))
    return _strip_html(raw.decode("utf-8", errors="replace"))


def _extract_pdf_text(raw: bytes) -> str | None:
    """Best-effort PDF text extract; returns None when pypdf is unavailable or empty."""
    try:
        from io import BytesIO

        from pypdf import PdfReader
    except ImportError:
        logger.info("pypdf not installed — cannot parse PDF filing bodies")
        return None
    try:
        reader = PdfReader(BytesIO(raw))
        chunks: list[str] = []
        for page in reader.pages:
            try:
                page_text = page.extract_text() or ""
            except Exception:  # noqa: BLE001
                continue
            if page_text.strip():
                chunks.append(page_text)
            joined = "\n".join(chunks)
            if len(joined) >= FILINGS_BODY_MAX_CHARS:
                break
        text = "\n".join(chunks).strip()
        return text or None
    except Exception as exc:  # noqa: BLE001
        logger.debug("PDF extract failed: %s", exc)
        return None


def resolve_filings_regime(market: str | None, ticker: str) -> str:
    """
    Choose filing source regime for a ticker.

    Explicit market ids win; otherwise infer from Yahoo-style suffixes.
    """
    m = (market or "").strip().lower()
    if m in {"sp500", "nasdaq100", "us", "nyse", "nasdaq", "us_adr_asia"}:
        return "sec_edgar"
    if m in {"ftse350", "ftse_smallcap", "aim", "uk", "lse"}:
        return "uk_rns"
    if m in {"asx200", "asx"}:
        return "asx_announcements"
    if m in {
        "euro_stoxx50",
        "dax",
        "cac40",
        "ibex35",
        "ftse_mib",
        "aex",
        "bel20",
        "eu",
    }:
        return "euro_filings"
    if m in {"tsx60", "tsx", "canada"}:
        return "tsx_announcements"
    if m in {"hang_seng", "sti", "hk", "sgx", "asia"}:
        return "asia_filings"

    t = (ticker or "").strip().upper()
    if t.endswith(".L"):
        return "uk_rns"
    if t.endswith(".AX"):
        return "asx_announcements"
    if t.endswith(".TO"):
        return "tsx_announcements"
    if t.endswith(".HK") or t.endswith(".SI"):
        return "asia_filings"
    if any(
        t.endswith(suf)
        for suf in _EXCHANGE_SUFFIXES
        if suf not in {".L", ".AX", ".TO", ".HK", ".SI"}
    ):
        return "euro_filings"
    # Bare US-style symbols (library research) → EDGAR
    if re.fullmatch(r"[A-Z]{1,5}", _epic(t)):
        return "sec_edgar"
    return "uk_rns"


def _sec_user_agent() -> str:
    # SEC fair-access policy expects an identifying UA with a contact email.
    return (
        os.environ.get("SEC_USER_AGENT")
        or "value-investor-research/0.1 (contact: research@example.com)"
    )


def classify_filing_period(
    headline: str,
    *,
    category: str | None = None,
    form: str | None = None,
) -> str:
    """
    Return ``annual``, ``interim``, or ``other``.

    Uses SEC form types when present, else headline keywords / provider categories.
    """
    if form:
        form_u = str(form).strip().upper()
        if form_u in SEC_ANNUAL_FORMS:
            return "annual"
        if form_u in SEC_INTERIM_FORMS:
            return "interim"
        if form_u in SEC_OTHER_FORMS or form_u.startswith("8-K"):
            return "other"

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
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
        **(headers or {}),
    }
    request = urllib.request.Request(url, headers=request_headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read()
        encoding = (response.headers.get("Content-Encoding") or "").lower()
        if encoding == "gzip" or data[:2] == b"\x1f\x8b":
            try:
                data = gzip.decompress(data)
            except OSError:
                pass
        return data


def _http_post(
    url: str,
    *,
    data: bytes,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> bytes:
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
        **(headers or {}),
    }
    request = urllib.request.Request(url, data=data, headers=request_headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
        encoding = (response.headers.get("Content-Encoding") or "").lower()
        if encoding == "gzip" or payload[:2] == b"\x1f\x8b":
            try:
                payload = gzip.decompress(payload)
            except OSError:
                pass
        return payload


def _load_sec_ticker_cik_map() -> dict[str, int]:
    global _sec_ticker_cik_cache
    if _sec_ticker_cik_cache is not None:
        return _sec_ticker_cik_cache
    try:
        payload = _http_get(
            SEC_COMPANY_TICKERS_URL,
            headers={"User-Agent": _sec_user_agent()},
            timeout=40,
        )
        data = json.loads(payload.decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.warning("SEC company_tickers fetch failed: %s", exc)
        _sec_ticker_cik_cache = {}
        return _sec_ticker_cik_cache
    mapping: dict[str, int] = {}
    if isinstance(data, dict):
        rows = data.values()
    elif isinstance(data, list):
        rows = data
    else:
        rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip().upper()
        cik = row.get("cik_str")
        if ticker and cik is not None:
            try:
                mapping[ticker] = int(cik)
            except (TypeError, ValueError):
                continue
    _sec_ticker_cik_cache = mapping
    return mapping


def resolve_sec_cik(ticker: str) -> int | None:
    """Map a US ticker to SEC CIK, or None if unknown."""
    epic = _epic(ticker)
    return _load_sec_ticker_cik_map().get(epic)


def _sec_submissions_entity_name(cik: int) -> str | None:
    """Return the registrant name from SEC submissions metadata."""
    cik10 = f"{cik:010d}"
    url = SEC_SUBMISSIONS_URL.format(cik10=cik10)
    try:
        payload = _http_get(url, headers={"User-Agent": _sec_user_agent()}, timeout=40)
        data = json.loads(payload.decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.debug("SEC submissions name lookup failed for CIK %s: %s", cik, exc)
        return None
    name = str(data.get("name") or "").strip()
    return name or None


def _issuer_matches_sec_name(company_name: str, sec_name: str, ticker: str) -> bool:
    """True when a non-US issuer name plausibly matches an SEC registrant."""
    norm_company = " ".join(
        tok for tok in re.split(r"[^a-z0-9]+", (company_name or "").lower()) if tok
    ).strip()
    norm_sec = " ".join(
        tok for tok in re.split(r"[^a-z0-9]+", (sec_name or "").lower()) if tok
    ).strip()
    if norm_company and norm_company == norm_sec:
        return True
    tokens = [
        tok
        for tok in re.split(r"[^a-z0-9]+", (company_name or "").lower())
        if len(tok) >= 4 and tok not in _ISSUER_STOPWORDS
    ]
    sec_l = (sec_name or "").lower()
    hits = sum(1 for tok in tokens[:6] if tok in sec_l)
    if hits >= 2:
        return True
    if hits == 1 and any(len(tok) >= 5 and tok in sec_l for tok in tokens):
        return True
    epic = _base_symbol(ticker).lower()
    if len(epic) >= 4 and re.search(rf"\b{re.escape(epic)}\b", sec_l, flags=re.I):
        return any(len(tok) >= 5 and tok in sec_l for tok in tokens)
    return False


def _uk_ticker_sec_dual_listed(ticker: str, company_name: str) -> bool:
    """True when a `.L` ticker maps to an SEC CIK for the same issuer (not a US homonym)."""
    if not (ticker or "").upper().endswith(".L"):
        return False
    return _sec_edgar_supplement_allowed(ticker, company_name)


def _sec_edgar_supplement_allowed(ticker: str, company_name: str) -> bool:
    """
    True when SEC EDGAR is a same-issuer supplement for a non-US listing.

    Prevents homonym collisions (e.g. Vinci ``DG.PA`` vs Dollar General ``DG``).
    """
    base = _base_symbol(ticker)
    if not base or base == (ticker or "").strip().upper():
        return False
    cik = resolve_sec_cik(base)
    if cik is None:
        return False
    sec_name = _sec_submissions_entity_name(cik)
    if not sec_name:
        return False
    return _issuer_matches_sec_name(company_name, sec_name, ticker)


def filter_misattributed_filings(
    rows: list[dict[str, Any]],
    *,
    company_name: str,
    ticker: str,
    regime: str,
) -> list[dict[str, Any]]:
    """Drop SEC (and noisy headline) rows that clearly belong to a different issuer."""
    if regime in {"sec_edgar", "uk_rns"}:
        return rows
    sec_supplement_ok = _sec_edgar_supplement_allowed(ticker, company_name)
    kept: list[dict[str, Any]] = []
    for row in rows:
        headline = str(row.get("headline") or "")
        source = str(row.get("source") or "")
        if source == "sec_edgar":
            if sec_supplement_ok:
                kept.append(row)
                continue
            form = str(row.get("form") or row.get("category") or "").upper()
            # Foreign listings should not pull domestic 10-K/10-Q from a homonym US ticker.
            if form in {"10-K", "10-Q"} and not headline_relevant_to_issuer(
                headline, company_name, ticker
            ):
                continue
            if not headline_relevant_to_issuer(headline, company_name, ticker):
                continue
        kept.append(row)
    return kept


def enrich_global_filing_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve Google News wrapper URLs to publisher links before body fetch."""
    enriched: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        url = str(item.get("url") or "")
        if "news.google.com" in url:
            resolved = resolve_google_news_publisher_url(url)
            if resolved and "news.google.com" not in resolved:
                item["url"] = resolved
                src = str(item.get("source") or "google_news")
                if not src.endswith("_resolved"):
                    item["source"] = f"{src}_resolved"
        url = str(item.get("url") or "")
        doc_url = resolve_asx_publisher_document_url(url)
        if doc_url and doc_url != url:
            item["url"] = doc_url
            src = str(item.get("source") or "google_news")
            if not src.endswith("_resolved"):
                item["source"] = f"{src}_resolved"
        enriched.append(item)
    return enriched


def fetch_filings_sec_edgar(
    *,
    ticker: str,
    max_items: int = FILINGS_MAX_ITEMS,
    lookback_days: int = FILINGS_LOOKBACK_DAYS,
    include_current_reports: bool = True,
) -> list[dict[str, Any]]:
    """
    Fetch recent SEC EDGAR filings (10-K / 10-Q / optional 8-K) for a US ticker.

    Returns metadata rows with direct archive HTML URLs suitable for body extract.
    """
    cik = resolve_sec_cik(ticker)
    if cik is None:
        logger.warning("SEC CIK not found for ticker %s", ticker)
        return []

    cik10 = f"{cik:010d}"
    url = SEC_SUBMISSIONS_URL.format(cik10=cik10)
    try:
        payload = _http_get(url, headers={"User-Agent": _sec_user_agent()}, timeout=40)
        data = json.loads(payload.decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.warning("SEC submissions fetch failed for %s: %s", ticker, exc)
        return []

    recent = (data.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accessions = recent.get("accessionNumber") or []
    documents = recent.get("primaryDocument") or []
    descriptions = recent.get("primaryDocDescription") or []

    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    rows: list[dict[str, Any]] = []
    annual_interim = 0
    other_count = 0
    # Prefer keeping room for 10-K/10-Q; cap noisy 8-Ks.
    max_other = max(4, max_items // 4) if include_current_reports else 0

    for idx, form in enumerate(forms):
        form_s = str(form or "").strip()
        if form_s not in SEC_FORM_ALLOWLIST:
            continue
        if form_s in SEC_OTHER_FORMS and not include_current_reports:
            continue

        filing_date = dates[idx] if idx < len(dates) else None
        published = None
        if filing_date:
            try:
                published_dt = datetime.strptime(str(filing_date), "%Y-%m-%d").replace(tzinfo=UTC)
                if published_dt < cutoff:
                    continue
                published = published_dt.isoformat()
            except ValueError:
                published = str(filing_date)

        accession = accessions[idx] if idx < len(accessions) else None
        document = documents[idx] if idx < len(documents) else None
        if not accession or not document:
            continue
        # Skip binary primary docs; we only extract HTML/text bodies.
        doc_l = str(document).lower()
        if doc_l.endswith(".pdf") or doc_l.endswith(".zip"):
            continue

        period = classify_filing_period(form_s, form=form_s)
        if period == "other":
            if other_count >= max_other:
                continue
            other_count += 1
        else:
            annual_interim += 1

        desc = descriptions[idx] if idx < len(descriptions) else ""
        headline = f"{form_s}: {desc}".strip(": ").strip() if desc else form_s
        archive_url = SEC_ARCHIVE_URL.format(
            cik=cik,
            accession_nodash=str(accession).replace("-", ""),
            document=document,
        )
        rows.append(
            {
                "id": _filing_id("sec", str(accession), form_s),
                "source": "sec_edgar",
                "headline": headline,
                "published_at": published,
                "url": archive_url,
                "period": period,
                "category": form_s,
                "form": form_s,
                "summary": "",
                "has_body": False,
                "body_path": None,
                "priority": _priority_score(headline, period)
                + (10 if form_s in SEC_ANNUAL_FORMS else 0),
                "provider_id": str(accession),
                "cik": cik,
            }
        )
        if len(rows) >= max_items:
            break

    if not rows:
        logger.info("No SEC filings in lookback for %s (CIK %s)", ticker, cik)
    else:
        logger.info(
            "SEC EDGAR: %s → %d filings (%d annual/interim)",
            ticker,
            len(rows),
            annual_interim,
        )
    return rows


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
    query: str | None = None,
    source_label: str = "google_news_investegate",
    hl: str = "en-GB",
    gl: str = "GB",
    ceid: str = "GB:en",
) -> list[dict[str, Any]]:
    """
    Discover results / announcement headlines via Google News RSS.

    Returns metadata rows (title, date, url, period). Full text is usually not
    available from the Google wrapper URL; bodies are filled later when a direct
    publisher URL is known.
    """
    epic = _base_symbol(ticker)
    if query is None:
        query = (
            f'site:investegate.co.uk "{company_name}" OR {epic} '
            f'(Results OR "Annual Report" OR Interim OR "Half-year" OR "Trading Update" OR RNS)'
        )
    url = (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote(query)
        + f"&hl={hl}&gl={gl}&ceid={ceid}"
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
        # Drop mis-attributed headlines that never mention the issuer.
        if not headline_relevant_to_issuer(title, company_name, ticker):
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
                "id": _filing_id("gnews", source_label, title, published or "", link or ""),
                "source": source_label,
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


def asx_markit_file_url(document_key: str) -> str:
    """Direct PDF URL for an ASX announcement document key from the Markit feed."""
    return ASX_MARKIT_FILE_URL.format(document_key=document_key)


def fetch_filings_asx_direct(
    *,
    company_name: str,
    ticker: str,
    max_items: int = ASX_MARKIT_MAX_ITEMS,
    lookback_days: int = FILINGS_LOOKBACK_DAYS,
) -> list[dict[str, Any]]:
    """
    Fetch recent ASX announcements via the public Markit Digital JSON feed.

    Returns metadata rows with direct PDF URLs (``asx.api.markitdigital.com``).
    The feed exposes only the latest handful of announcements per symbol.
    """
    epic = _base_symbol(ticker)
    if not epic:
        return []
    url = (
        ASX_MARKIT_ANNOUNCEMENTS_URL.format(symbol=urllib.parse.quote(epic))
        + "?market=asx"
        + f"&count={max(ASX_MARKIT_MAX_ITEMS, min(max_items, ASX_MARKIT_MAX_ITEMS))}"
    )
    try:
        payload = _http_get(url, timeout=40)
        data = json.loads(payload.decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.warning("ASX Markit announcements fetch failed for %s: %s", ticker, exc)
        return []

    items = (data.get("data") or {}).get("items") or []
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    rows: list[dict[str, Any]] = []
    for item in items:
        headline = _strip_html(str(item.get("headline") or ""))
        if not headline:
            continue
        ann_type = str(item.get("announcementType") or "").strip().upper()
        if ann_type in _ASX_SKIP_ANNOUNCEMENT_TYPES and not any(
            token in headline.lower()
            for token in ("result", "annual", "interim", "half year", "full year", "report")
        ):
            continue
        if not headline_relevant_to_issuer(headline, company_name, ticker):
            continue
        published_raw = str(item.get("date") or "")
        published: str | None = None
        if published_raw:
            try:
                published_dt = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
                if published_dt < cutoff:
                    continue
                published = published_dt.isoformat()
            except ValueError:
                published = published_raw
        document_key = str(item.get("documentKey") or "").strip()
        if not document_key:
            continue
        period = classify_filing_period(headline, form=ann_type)
        file_url = asx_markit_file_url(document_key)
        rows.append(
            {
                "id": _filing_id("asx_direct", document_key),
                "source": "asx_direct",
                "headline": headline,
                "published_at": published,
                "url": file_url,
                "period": period,
                "category": ann_type or None,
                "summary": headline,
                "has_body": False,
                "body_path": None,
                "priority": _priority_score(headline, period) + 15,
                "document_key": document_key,
            }
        )
        if len(rows) >= max_items:
            break
    if rows:
        logger.info("ASX Markit direct: %s → %d announcements", ticker, len(rows))
    return rows


def fetch_filings_asx_news(
    *,
    company_name: str,
    ticker: str,
    max_items: int = FILINGS_MAX_ITEMS,
    lookback_days: int = FILINGS_LOOKBACK_DAYS,
) -> list[dict[str, Any]]:
    """Discover ASX results / announcements via Google News (ASX + Market Index)."""
    epic = _base_symbol(ticker)
    query = (
        f'(site:asx.com.au OR site:marketindex.com.au) ("{company_name}" OR {epic}) '
        f'(Results OR "Annual Report" OR "Half Year" OR "Half-year" OR Interim OR '
        f'"Full Year" OR "Preliminary Final" OR "Quarterly Activities")'
    )
    return fetch_filings_google_news(
        company_name=company_name,
        ticker=ticker,
        max_items=max_items,
        lookback_days=lookback_days,
        query=query,
        source_label="google_news_asx",
        hl="en-AU",
        gl="AU",
        ceid="AU:en",
    )


def fetch_filings_euro_news(
    *,
    company_name: str,
    ticker: str,
    max_items: int = FILINGS_MAX_ITEMS,
    lookback_days: int = FILINGS_LOOKBACK_DAYS,
    market: str | None = None,
) -> list[dict[str, Any]]:
    """Discover Euro-listed results releases via Google News headlines."""
    from value_investor.research.news_locale import euro_filing_site_clause, resolve_news_locale

    epic = _base_symbol(ticker)
    site_clause = euro_filing_site_clause(ticker)
    locale = resolve_news_locale(market, ticker)
    query = (
        f"{site_clause}"
        f'("{company_name}" OR {epic} OR {ticker}) '
        f'("Annual Report" OR "Full Year Results" OR "Half-year Results" OR '
        f'"Interim Results" OR "Quarterly Results" OR "Half Year Results" OR '
        f'"Preliminary Results" OR "Geschäftsbericht" OR "Résultats")'
    )
    return fetch_filings_google_news(
        company_name=company_name,
        ticker=ticker,
        max_items=max_items,
        lookback_days=lookback_days,
        query=query,
        source_label="google_news_euro",
        hl=locale["hl"],
        gl=locale["gl"],
        ceid=locale["ceid"],
    )


def fetch_filings_tsx_news(
    *,
    company_name: str,
    ticker: str,
    max_items: int = FILINGS_MAX_ITEMS,
    lookback_days: int = FILINGS_LOOKBACK_DAYS,
) -> list[dict[str, Any]]:
    """Discover Canadian issuer results / SEDAR+ headlines via Google News."""
    epic = _base_symbol(ticker)
    query = (
        f'(site:sedarplus.ca OR site:sedar.com OR site:newswire.ca) '
        f'("{company_name}" OR {epic}) '
        f'(Results OR "Annual Report" OR "Annual Financial" OR Interim OR '
        f'"Management\'s Discussion" OR "MD&A" OR "Quarterly Report")'
    )
    return fetch_filings_google_news(
        company_name=company_name,
        ticker=ticker,
        max_items=max_items,
        lookback_days=lookback_days,
        query=query,
        source_label="google_news_tsx",
        hl="en-CA",
        gl="CA",
        ceid="CA:en",
    )


def fetch_filings_asia_news(
    *,
    company_name: str,
    ticker: str,
    max_items: int = FILINGS_MAX_ITEMS,
    lookback_days: int = FILINGS_LOOKBACK_DAYS,
) -> list[dict[str, Any]]:
    """Discover HK / Singapore results headlines via Google News."""
    epic = _base_symbol(ticker)
    query = (
        f'("{company_name}" OR {epic} OR {ticker}) '
        f'("Annual Report" OR "Full Year Results" OR "Interim Results" OR '
        f'"Half-year Results" OR "Quarterly Results" OR "Final Results")'
    )
    gl = "HK" if ticker.upper().endswith(".HK") else "SG"
    return fetch_filings_google_news(
        company_name=company_name,
        ticker=ticker,
        max_items=max_items,
        lookback_days=lookback_days,
        query=query,
        source_label="google_news_asia",
        hl="en",
        gl=gl,
        ceid=f"{gl}:en",
    )


def fetch_filings_ticker_api(
    *,
    ticker: str,
    company_name: str = "",
    api_key: str | None = None,
    max_items: int = FILINGS_MAX_ITEMS,
    lookback_days: int = FILINGS_LOOKBACK_DAYS,
) -> list[dict[str, Any]]:
    """
    Fetch RNS items from Ticker.app when ``TICKER_API_KEY`` is configured.

    Free/lite tiers vary; failures are logged and return an empty list so the
    Google News path can still populate the index.

    Some plans ignore the ``symbol`` filter and return a global RNS feed — we
    always drop headlines that do not mention the issuer EPIC / name tokens.
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

    warnings = data.get("warnings") if isinstance(data, dict) else None
    if warnings:
        logger.info("Ticker RNS API warnings for %s: %s", ticker, warnings)

    items = data.get("data") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []

    rows: list[dict[str, Any]] = []
    skipped_unrelated = 0
    for item in items[: max(max_items * 3, max_items)]:
        if len(rows) >= max_items:
            break
        if not isinstance(item, dict):
            continue
        headline = str(item.get("headline") or item.get("title") or "").strip()
        if not headline:
            continue
        if not headline_relevant_to_issuer(headline, company_name or epic, ticker):
            skipped_unrelated += 1
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
    if skipped_unrelated:
        logger.info(
            "Ticker RNS API: dropped %s unrelated headline(s) for %s (kept %s)",
            skipped_unrelated,
            ticker,
            len(rows),
        )
    return rows


def _google_news_article_id(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.lower() != "news.google.com":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[-2] not in {"articles", "read"}:
        return None
    return parts[-1] or None


def _google_news_decoding_params(article_id: str) -> tuple[str, str] | None:
    for prefix in ("articles", "rss/articles"):
        page_url = f"https://news.google.com/{prefix}/{article_id}"
        try:
            raw = _http_get(page_url, headers={"User-Agent": USER_AGENT}, timeout=20)
            html = raw.decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.debug("Google News params fetch failed for %s: %s", page_url, exc)
            continue
        signature = re.search(r'data-n-a-sg="([^"]+)"', html)
        timestamp = re.search(r'data-n-a-ts="([^"]+)"', html)
        if signature and timestamp and timestamp.group(1).isdigit():
            return signature.group(1), timestamp.group(1)
    return None


def _decode_google_news_article_url(url: str) -> str | None:
    """Resolve post-2024 Google News article wrappers via batchexecute."""
    article_id = _google_news_article_id(url)
    if not article_id:
        return None
    params = _google_news_decoding_params(article_id)
    if not params:
        return None
    signature, timestamp = params
    payload = [
        "Fbv4je",
        (
            '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
            f'"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{article_id}",{timestamp},"{signature}"]'
        ),
    ]
    post_body = urllib.parse.urlencode(
        {"f.req": json.dumps([[payload]], separators=(",", ":"))}
    ).encode("utf-8")
    try:
        raw = _http_post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            data=post_body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "User-Agent": USER_AGENT,
            },
            timeout=20,
        )
        parsed = json.loads(raw.decode("utf-8", errors="replace").split("\n\n", 1)[1])
        if isinstance(parsed, list) and len(parsed) >= 3:
            parsed = parsed[:-2]
        decoded = json.loads(parsed[0][2])
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, IndexError, TypeError) as exc:
        logger.debug("Google News batchexecute decode failed for %s: %s", article_id, exc)
        return None
    if (
        isinstance(decoded, list)
        and len(decoded) >= 2
        and decoded[0] == "garturlres"
        and isinstance(decoded[1], str)
        and decoded[1].startswith("http")
    ):
        return decoded[1]
    return None


def resolve_google_news_publisher_url(url: str | None) -> str | None:
    """Follow Google News wrapper redirects to the publisher URL when possible."""
    if not url or "news.google.com" not in url:
        return url
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=20) as response:
            final = response.geturl()
            if final and "news.google.com" not in final:
                return final
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.debug("Google News URL resolve failed for %s: %s", url, exc)
    return _decode_google_news_article_url(url)


def resolve_asx_publisher_document_url(url: str | None) -> str | None:
    """
    Upgrade ASX publisher landing pages to direct PDF/document URLs when possible.

    Market Index announcement pages and Google News wrappers often point at HTML
    shells; this follows embedded PDF links (including data-api inline PDFs).
    """
    if not url or not url.startswith("http"):
        return None
    if url.lower().endswith(".pdf") or "/asxpdf/" in url.lower():
        return url
    host = urllib.parse.urlparse(url).netloc.lower()
    if "marketindex.com.au" not in host:
        return url
    if "/pdf/" in url.lower() or "data-api" in url.lower():
        return url
    try:
        raw = _http_get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        html = raw.decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.debug("ASX publisher page fetch failed for %s: %s", url, exc)
        return url
    for pattern in (
        r'"(https://www\.marketindex\.com\.au/data-api/api/v1/announcements/[^"]+/pdf/[^"]+)"',
        r'"(https://asx\.api\.markitdigital\.com/[^"]+)"',
        r'"(https://announcements\.asx\.com\.au/asxpdf/[^"]+\.pdf)"',
        r'href="([^"]+\.pdf[^"]*)"',
    ):
        match = re.search(pattern, html, flags=re.I)
        if match:
            candidate = match.group(1)
            if candidate.startswith("http"):
                return candidate
    return url


def _is_ch_document_url(url: str | None) -> bool:
    """True for Companies House document-api metadata or content URLs."""
    return bool(url) and "document-api.company-information.service.gov.uk" in url


def _is_ch_filing_row(row: dict[str, Any]) -> bool:
    """True when a filing row points at Companies House filed accounts."""
    if str(row.get("source") or "") == "companies_house":
        return True
    return _is_ch_document_url(str(row.get("document_metadata_url") or "")) or _is_ch_document_url(
        str(row.get("url") or "")
    )


def fetch_filing_body(url: str | None, *, allow_sec_exhibits: bool = True) -> str | None:
    """Download and extract plain text from a direct announcement URL."""
    if not url or not url.startswith("http"):
        return None
    if _is_ch_document_url(url):
        return _fetch_companies_house_body(
            {"url": url, "document_metadata_url": url, "source": "companies_house"}
        )
    if "news.google.com" in url:
        resolved = resolve_google_news_publisher_url(url)
        if not resolved or "news.google.com" in resolved:
            return None
        url = resolved
    url = resolve_asx_publisher_document_url(url) or url
    headers: dict[str, str] = {}
    if "sec.gov" in url:
        headers["User-Agent"] = _sec_user_agent()
    try:
        raw = _http_get(url, headers=headers, timeout=60)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.debug("Filing body fetch failed for %s: %s", url, exc)
        return None

    # urlopen doesn't return headers here easily — sniff
    if raw[:4] == b"%PDF" or str(url).lower().endswith(".pdf"):
        text = _extract_filing_document_text(raw, "application/pdf")
        if not text or len(text) < 200:
            logger.info("PDF filing body empty/unreadable: %s", url)
            return None
    else:
        if "sec.gov" in url:
            text = _extract_sec_html_text(raw.decode("utf-8", errors="replace"))
            if allow_sec_exhibits and not _filing_text_is_substantive(text, min_chars=400):
                exhibit = _try_sec_exhibit_body(url)
                if exhibit:
                    text = exhibit
        elif "investegate.co.uk" in url:
            text = _extract_investegate_html_text(raw.decode("utf-8", errors="replace"))
        else:
            html = raw.decode("utf-8", errors="replace")
            text = (
                _extract_ixbrl_html_text(html)
                if _is_ixbrl_html(html)
                else _strip_html(html)
            )
        if not _filing_text_is_substantive(text):
            return None
    if len(text) > FILINGS_BODY_MAX_CHARS:
        text = text[:FILINGS_BODY_MAX_CHARS] + "\n\n[truncated]"
    return text


def _source_bonus(source: str | None) -> int:
    if source in {"ticker_rns_api", "sec_edgar", "companies_house"}:
        return 30
    if source in {"investegate_direct", "investegate_resolved"}:
        return 28
    if source == "asx_direct":
        return 27
    if source == "ir_allowlist":
        return 25
    return 0


def load_ir_url_allowlist(path: Path | None = None) -> dict[str, list[str]]:
    """Manual IR/results PDF URLs by Yahoo ticker (MVP until a generic crawler)."""
    path = path or DEFAULT_IR_URLS_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    urls = data.get("urls") if isinstance(data, dict) else data
    if not isinstance(urls, dict):
        return {}
    out: dict[str, list[str]] = {}
    for key, value in urls.items():
        if isinstance(value, str) and value.strip():
            out[str(key).upper()] = [value.strip()]
        elif isinstance(value, list):
            cleaned = [str(u).strip() for u in value if str(u).strip()]
            if cleaned:
                out[str(key).upper()] = cleaned
    return out


def fetch_filings_ir_allowlist(
    ticker: str,
    *,
    path: Path | None = None,
) -> list[dict[str, Any]]:
    """Build filing rows from the optional per-ticker IR URL allowlist."""
    mapping = load_ir_url_allowlist(path)
    urls = mapping.get(ticker.upper()) or mapping.get(_base_symbol(ticker)) or []
    rows: list[dict[str, Any]] = []
    for url in urls:
        lower = url.lower()
        period = "other"
        if any(
            token in lower
            for token in (
                "annual",
                "fy",
                "full-year",
                "full_year",
                "accounts",
                "20-f",
                "20f",
                "10-k",
                "10k",
            )
        ) or re.search(r"-\d{4}1231\.(htm|html|pdf)(?:$|\?)", lower):
            period = "annual"
        elif any(
            token in lower
            for token in ("interim", "half", "h1", "q1", "q2", "q3", "trading", "10-q", "10q")
        ):
            period = "interim"
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        rows.append(
            {
                "id": f"ir_{digest}",
                "source": "ir_allowlist",
                "headline": f"IR allowlist document — {url.rsplit('/', 1)[-1] or url}",
                "published_at": None,
                "url": url,
                "period": period,
                "category": "ir_allowlist",
                "summary": "Manual IR/results URL from docs/data/research_ir_urls.json",
                "has_body": False,
                "body_path": None,
                "priority": 130,
            }
        )
    return rows


def _is_ir_allowlist_row(row: dict[str, Any]) -> bool:
    return str(row.get("source") or "") == "ir_allowlist"


IR_BODY_FETCH_RETRIES = 2


def merge_ir_allowlist_filings(
    ticker: str,
    filings_dir: Path,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Ensure manual IR allowlist rows are present in ``filings_index.json``."""
    filings_dir = Path(filings_dir)
    index_path = filings_dir / "filings_index.json"
    allowlist_rows = fetch_filings_ir_allowlist(ticker, path=path)
    if not allowlist_rows:
        return {"added": 0, "total_allowlist": 0, "note": "no allowlist urls for ticker"}

    if index_path.exists():
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            payload = {}
    else:
        payload = {}
        filings_dir.mkdir(parents=True, exist_ok=True)

    filings = list(payload.get("filings") or [])
    known_ids = {row.get("id") for row in filings}
    known_urls = {str(row.get("url") or "").strip() for row in filings if row.get("url")}
    added = 0
    for row in allowlist_rows:
        url = str(row.get("url") or "").strip()
        if row.get("id") in known_ids or url in known_urls:
            continue
        filings.append(row)
        known_ids.add(row.get("id"))
        known_urls.add(url)
        added += 1

    payload["filings"] = filings
    payload["summary"] = summarize_filings(filings)
    if added:
        payload["ir_allowlist_merged_at"] = datetime.now(UTC).isoformat()
    index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {
        "added": added,
        "total_allowlist": len(allowlist_rows),
        "note": "merge_ir_allowlist_filings",
    }


def refetch_ir_allowlist_filing_bodies(
    filings_dir: Path,
    ticker: str,
    *,
    max_bodies: int = 20,
    max_retries: int = IR_BODY_FETCH_RETRIES,
    allowlist_path: Path | None = None,
) -> dict[str, Any]:
    """
    Merge IR allowlist URLs then re-download bodies with retries.

    Used when ``gap_fill_source_map.json`` plans ``company_ir_presentation`` or
    when indexed IR PDF rows (e.g. ``ir_a9733d0de6aec27d``) still lack bodies.
    """
    filings_dir = Path(filings_dir)
    merge_meta = merge_ir_allowlist_filings(ticker, filings_dir, path=allowlist_path)
    index_path = filings_dir / "filings_index.json"
    bodies_dir = filings_dir / "bodies"
    if not index_path.exists():
        return {
            "attempted": 0,
            "fetched": 0,
            "with_body_before": 0,
            "with_body_after": 0,
            "merge": merge_meta,
            "note": "no filings_index.json",
        }
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        return {
            "attempted": 0,
            "fetched": 0,
            "with_body_before": 0,
            "with_body_after": 0,
            "merge": merge_meta,
            "note": f"unreadable index: {exc}",
        }

    filings = list(payload.get("filings") or [])
    before = sum(1 for row in filings if row.get("has_body"))
    ir_rows = [row for row in filings if _is_ir_allowlist_row(row)]
    missing = [row for row in ir_rows if row.get("url") and not row.get("has_body")]
    if not missing:
        return {
            "attempted": 0,
            "fetched": 0,
            "with_body_before": before,
            "with_body_after": before,
            "merge": merge_meta,
            "note": "no missing IR allowlist bodies",
        }

    bodies_dir.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    retries_used = 0
    updated: list[dict[str, Any]] = []
    for row in filings:
        item = dict(row)
        if (
            downloaded < max_bodies
            and _is_ir_allowlist_row(item)
            and item.get("url")
            and not item.get("has_body")
        ):
            body = None
            url = str(item["url"])
            for attempt in range(max_retries + 1):
                body = fetch_filing_body(url)
                if body:
                    break
                if attempt < max_retries:
                    retries_used += 1
            if body:
                filename = f"{item['id']}.txt"
                path = bodies_dir / filename
                path.write_text(body, encoding="utf-8")
                item["has_body"] = True
                item["body_path"] = str(path)
                downloaded += 1
        updated.append(item)

    after = sum(1 for row in updated if row.get("has_body"))
    payload["filings"] = updated
    payload["summary"] = summarize_filings(updated)
    payload["ir_refetched_at"] = datetime.now(UTC).isoformat()
    index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {
        "attempted": len(missing),
        "fetched": max(0, after - before),
        "with_body_before": before,
        "with_body_after": after,
        "retries_used": retries_used,
        "merge": merge_meta,
        "note": "refetch_ir_allowlist_filing_bodies",
    }


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
            # Prefer primary regulator / body-bearing rows
            existing_score = (
                int(existing.get("priority") or 0)
                + (50 if existing.get("has_body") else 0)
                + _source_bonus(existing.get("source"))
            )
            new_score = (
                int(row.get("priority") or 0)
                + (50 if row.get("has_body") else 0)
                + _source_bonus(row.get("source"))
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
        if downloaded < max_bodies and not row.get("has_body"):
            period = row.get("period")
            if period in ("annual", "interim", "other"):
                # Always try annual/interim; only try a few "other" if slots remain
                if period == "other" and downloaded >= max(4, max_bodies // 2):
                    updated.append(row)
                    continue
                body = None
                if _is_ch_filing_row(row):
                    body = _fetch_companies_house_body(row)
                elif row.get("url"):
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


def _fetch_companies_house_body(row: dict[str, Any]) -> str | None:
    """Download and extract text from a Companies House accounts filing."""
    from value_investor.research.companies_house import (
        companies_house_api_key,
        iter_ch_document_downloads,
    )

    key = companies_house_api_key()
    if not key:
        return None
    meta_url = str(row.get("document_metadata_url") or row.get("url") or "")
    if not meta_url:
        return None
    try:
        downloads = iter_ch_document_downloads(meta_url, api_key=key)
    except Exception as exc:  # noqa: BLE001
        logger.debug("CH body fetch failed for %s: %s", row.get("id"), exc)
        return None
    best_text: str | None = None
    best_score = -1
    for raw, content_type in downloads:
        text = _extract_filing_document_text(raw, content_type)
        if not text or len(text) < 200:
            continue
        score = _score_ch_body_text(text)
        if score > best_score:
            best_score = score
            best_text = text
    if not best_text:
        return None
    if len(best_text) > FILINGS_BODY_MAX_CHARS:
        best_text = best_text[:FILINGS_BODY_MAX_CHARS] + "\n\n[truncated]"
    return best_text


def _body_clearly_misattributed(text: str, company_name: str, ticker: str) -> bool:
    """
    True when body text is clearly from a different issuer (homonym collision).

    Conservative: generic filing prose without issuer tokens is kept.
    """
    if headline_relevant_to_issuer(text, company_name, ticker):
        return False
    lower = (text or "").lower()
    foreign_markers = (
        "dollar general",
        "banco santander",
        "costco wholesale",
    )
    return any(marker in lower for marker in foreign_markers)


def _scrub_misattributed_filing_rows(
    filings: list[dict[str, Any]],
    bodies_dir: Path,
    *,
    company_name: str,
    ticker: str,
) -> list[dict[str, Any]]:
    """Remove body files and clear flags when text does not match the issuer."""
    bodies_dir = Path(bodies_dir)
    cleaned: list[dict[str, Any]] = []
    for row in filings:
        item = dict(row)
        if not item.get("has_body"):
            cleaned.append(item)
            continue
        row_id = str(item.get("id") or "")
        body_path = item.get("body_path")
        candidate = Path(str(body_path)) if body_path else bodies_dir / f"{row_id}.txt"
        if not candidate.is_file():
            item["has_body"] = False
            item["body_path"] = None
            cleaned.append(item)
            continue
        try:
            sample = candidate.read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            item["has_body"] = False
            item["body_path"] = None
            cleaned.append(item)
            continue
        if not _body_clearly_misattributed(sample, company_name, ticker):
            cleaned.append(item)
            continue
        try:
            candidate.unlink()
        except OSError:
            pass
        item["has_body"] = False
        item["body_path"] = None
        cleaned.append(item)
    return cleaned


def prune_orphaned_filing_bodies(filings_dir: Path) -> dict[str, Any]:
    """
    Delete ``bodies/*.txt`` files not referenced by ``filings_index.json``.

    Orphaned bodies can remain after SEC homonym collisions or index rewrites.
    """
    filings_dir = Path(filings_dir)
    index_path = filings_dir / "filings_index.json"
    bodies_dir = filings_dir / "bodies"
    if not bodies_dir.is_dir():
        return {"removed": 0, "kept": 0, "removed_paths": []}
    referenced: set[str] = set()
    if index_path.exists():
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
            for row in payload.get("filings") or []:
                row_id = str(row.get("id") or "").strip()
                if row_id:
                    referenced.add(row_id)
        except (OSError, ValueError, TypeError):
            referenced = set()
    removed_paths: list[str] = []
    kept = 0
    for path in sorted(bodies_dir.glob("*.txt")):
        if path.stem in referenced:
            kept += 1
            continue
        try:
            path.unlink()
            removed_paths.append(str(path))
        except OSError as exc:
            logger.debug("Failed to prune orphaned body %s: %s", path, exc)
    if removed_paths:
        logger.info("Pruned %d orphaned filing body file(s) under %s", len(removed_paths), bodies_dir)
    return {"removed": len(removed_paths), "kept": kept, "removed_paths": removed_paths}


def prune_misattributed_filing_bodies(
    filings_dir: Path,
    *,
    company_name: str,
    ticker: str,
) -> dict[str, Any]:
    """
    Drop body files whose text clearly belongs to a different issuer.

    Clears ``has_body`` on affected index rows and deletes the body file.
    """
    filings_dir = Path(filings_dir)
    index_path = filings_dir / "filings_index.json"
    bodies_dir = filings_dir / "bodies"
    if not index_path.exists() or not bodies_dir.is_dir():
        return {"removed": 0, "cleared_rows": 0, "removed_paths": []}
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        return {"removed": 0, "cleared_rows": 0, "removed_paths": [], "note": str(exc)}
    filings = list(payload.get("filings") or [])
    removed_paths: list[str] = []
    cleared_rows = 0
    for row in filings:
        if not row.get("has_body"):
            continue
        row_id = str(row.get("id") or "")
        body_path = row.get("body_path")
        candidate = Path(str(body_path)) if body_path else bodies_dir / f"{row_id}.txt"
        if not candidate.is_file():
            continue
        try:
            sample = candidate.read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            continue
        if not _body_clearly_misattributed(sample, company_name, ticker):
            continue
        try:
            candidate.unlink()
            removed_paths.append(str(candidate))
        except OSError:
            pass
        row["has_body"] = False
        row["body_path"] = None
        cleared_rows += 1
    if cleared_rows:
        payload["filings"] = filings
        payload["summary"] = summarize_filings(filings)
        from value_investor.storage import write_json

        write_json(index_path, payload, compact=True, compress=False)
        logger.info(
            "Pruned %d misattributed filing body file(s) for %s",
            len(removed_paths),
            ticker,
        )
    return {
        "removed": len(removed_paths),
        "cleared_rows": cleared_rows,
        "removed_paths": removed_paths,
    }


def refetch_companies_house_filing_bodies(
    filings_dir: Path,
    *,
    max_bodies: int = 20,
) -> dict[str, Any]:
    """
    Re-download filed-accounts PDF/iXBRL bodies for indexed CH rows without text.

    Used by ingest-improvement and gap-fill when ``filings_with_body`` is zero
    but ``filings_index.json`` already lists Companies House document URLs.
    """
    filings_dir = Path(filings_dir)
    index_path = filings_dir / "filings_index.json"
    bodies_dir = filings_dir / "bodies"
    if not index_path.exists():
        return {
            "attempted": 0,
            "fetched": 0,
            "with_body_before": 0,
            "with_body_after": 0,
            "note": "no filings_index.json",
        }
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        return {
            "attempted": 0,
            "fetched": 0,
            "with_body_before": 0,
            "with_body_after": 0,
            "note": f"unreadable index: {exc}",
        }

    filings = list(payload.get("filings") or [])
    before = sum(1 for row in filings if row.get("has_body"))
    ch_rows = [row for row in filings if _is_ch_filing_row(row)]
    missing = [row for row in ch_rows if not row.get("has_body")]
    if not missing:
        return {
            "attempted": 0,
            "fetched": 0,
            "with_body_before": before,
            "with_body_after": before,
            "note": "no missing CH bodies",
        }

    bodies_dir.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    updated: list[dict[str, Any]] = []
    for row in filings:
        item = dict(row)
        if (
            downloaded < max_bodies
            and _is_ch_filing_row(item)
            and not item.get("has_body")
        ):
            body = _fetch_companies_house_body(item)
            if body:
                filename = f"{item['id']}.txt"
                path = bodies_dir / filename
                path.write_text(body, encoding="utf-8")
                item["has_body"] = True
                item["body_path"] = str(path)
                downloaded += 1
        updated.append(item)

    after = sum(1 for row in updated if row.get("has_body"))
    payload["filings"] = updated
    payload["summary"] = summarize_filings(updated)
    payload["ch_refetched_at"] = datetime.now(UTC).isoformat()
    index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {
        "attempted": len(missing),
        "fetched": max(0, after - before),
        "with_body_before": before,
        "with_body_after": after,
        "note": "refetch_companies_house_filing_bodies",
    }


def refetch_missing_filing_bodies(
    filings_dir: Path,
    *,
    max_bodies: int = 12,
) -> dict[str, Any]:
    """
    Re-attempt body downloads for an existing filings index (PDF-capable).

    Used by gap-fill so previously skipped PDFs / direct RNS URLs are filled
    before the agent answers open questions.
    """
    filings_dir = Path(filings_dir)
    index_path = filings_dir / "filings_index.json"
    bodies_dir = filings_dir / "bodies"
    if not index_path.exists():
        return {
            "attempted": 0,
            "fetched": 0,
            "with_body_before": 0,
            "with_body_after": 0,
            "note": "no filings_index.json",
        }
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        return {
            "attempted": 0,
            "fetched": 0,
            "with_body_before": 0,
            "with_body_after": 0,
            "note": f"unreadable index: {exc}",
        }
    filings = list(payload.get("filings") or [])
    before = sum(1 for row in filings if row.get("has_body"))
    ticker = str(payload.get("ticker") or "")
    company_name = str(payload.get("company_name") or "")
    if ticker and company_name:
        filings = enrich_filing_rows(
            filings,
            ticker=ticker,
            company_name=company_name,
        )
    missing = [
        row
        for row in filings
        if row.get("url") and not row.get("has_body")
    ]
    updated = _write_bodies(filings, bodies_dir, max_bodies=max_bodies)
    after = sum(1 for row in updated if row.get("has_body"))
    payload["filings"] = updated
    payload["summary"] = summarize_filings(updated)
    payload["refetched_at"] = datetime.now(UTC).isoformat()
    index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {
        "attempted": len(missing),
        "fetched": max(0, after - before),
        "with_body_before": before,
        "with_body_after": after,
        "note": "refetch_missing_filing_bodies",
    }


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
    market: str | None = None,
    deepen_history: bool = False,
    max_ch_accounts: int | None = None,
) -> dict[str, Any]:
    """
    Build ``sources/filings/`` for a memo ticker.

    Writes:
    - ``filings_index.json`` — catalog with period labels (annual/interim/other)
    - ``bodies/*.txt`` — plain-text announcement extracts when downloadable

    When ``deepen_history`` is true (memo tickers), pull more Companies House
    accounts years. Does **not** backdate research revisions — sources deepen
    for forward learning only.
    """
    from value_investor.research.companies_house import (
        DEEPEN_MAX_ACCOUNTS,
        DEFAULT_MAX_ACCOUNTS,
        fetch_filings_companies_house,
    )

    filings_dir = sources_dir / "filings"
    bodies_dir = filings_dir / "bodies"
    filings_dir.mkdir(parents=True, exist_ok=True)

    regime = resolve_filings_regime(market, ticker)
    groups: list[list[dict[str, Any]]] = []
    ch_accounts = max_ch_accounts
    if ch_accounts is None:
        ch_accounts = DEEPEN_MAX_ACCOUNTS if deepen_history else DEFAULT_MAX_ACCOUNTS

    if regime == "uk_rns":
        groups.append(
            fetch_filings_ticker_api(
                ticker=ticker,
                company_name=company_name,
                api_key=api_key,
            )
        )
        groups.append(fetch_filings_google_news(company_name=company_name, ticker=ticker))
        groups.append(
            fetch_filings_investegate_company(
                ticker=ticker,
                company_name=company_name,
            )
        )
        groups.append(
            fetch_filings_companies_house(
                ticker=ticker,
                company_name=company_name,
                max_accounts=int(ch_accounts),
            )
        )
        # Dual-listed UK names (e.g. RIO.L, SHEL.L) also file 20-F with the SEC.
        if _sec_edgar_supplement_allowed(ticker, company_name):
            groups.append(
                fetch_filings_sec_edgar(
                    ticker=_base_symbol(ticker),
                    include_current_reports=False,
                )
            )
    elif regime == "sec_edgar":
        groups.append(fetch_filings_sec_edgar(ticker=ticker))
    elif regime == "asx_announcements":
        groups.append(
            fetch_filings_asx_direct(company_name=company_name, ticker=ticker)
        )
        groups.append(fetch_filings_asx_news(company_name=company_name, ticker=ticker))
    elif regime == "euro_filings":
        groups.append(
            fetch_filings_euro_news(company_name=company_name, ticker=ticker, market=market)
        )
        groups.append(
            fetch_filings_investegate_company(
                ticker=ticker,
                company_name=company_name,
            )
        )
        if _sec_edgar_supplement_allowed(ticker, company_name):
            groups.append(
                fetch_filings_sec_edgar(
                    ticker=_base_symbol(ticker),
                    include_current_reports=False,
                )
            )
    elif regime == "tsx_announcements":
        groups.append(fetch_filings_tsx_news(company_name=company_name, ticker=ticker))
        if _sec_edgar_supplement_allowed(ticker, company_name):
            groups.append(
                fetch_filings_sec_edgar(
                    ticker=_base_symbol(ticker),
                    include_current_reports=False,
                )
            )
    elif regime == "asia_filings":
        groups.append(fetch_filings_asia_news(company_name=company_name, ticker=ticker))
        if _sec_edgar_supplement_allowed(ticker, company_name):
            groups.append(
                fetch_filings_sec_edgar(
                    ticker=_base_symbol(ticker),
                    include_current_reports=False,
                )
            )
    else:
        logger.info(
            "No filings regime for market=%s ticker=%s — writing empty index",
            market,
            ticker,
        )

    # Optional manual IR/results PDFs (MVP until a generic IR crawler).
    groups.append(fetch_filings_ir_allowlist(ticker))

    merged = merge_filings(*groups) if groups else []
    if regime in {"uk_rns", "euro_filings"}:
        merged = enrich_filing_rows(
            merged,
            ticker=ticker,
            company_name=company_name,
        )
    elif regime in {"asx_announcements", "tsx_announcements", "asia_filings"}:
        merged = enrich_global_filing_rows(merged)
    merged = filter_misattributed_filings(
        merged,
        company_name=company_name,
        ticker=ticker,
        regime=regime,
    )
    # Allow more bodies when deepening historical accounts for memo names.
    max_bodies = 20 if deepen_history else 12
    merged = _write_bodies(merged, bodies_dir, max_bodies=max_bodies)
    merged = _scrub_misattributed_filing_rows(
        merged,
        bodies_dir,
        company_name=company_name,
        ticker=ticker,
    )

    if regime == "sec_edgar":
        note = (
            "Primary regulatory filings via SEC EDGAR (separate from Yahoo). "
            "period=annual (10-K/20-F) | interim (10-Q) | other (8-K). "
            "Bodies are plain-text extracts from the primary HTML document "
            f"(truncated at {FILINGS_BODY_MAX_CHARS:,} chars)."
        )
    elif regime == "uk_rns":
        note = (
            "Primary regulatory filings for research (separate from Yahoo): "
            "Ticker RNS / Investegate discovery plus Companies House accounts "
            f"(up to {ch_accounts} filings"
            + (", historical deepen" if deepen_history else "")
            + "), optional IR allowlist URLs, Investegate direct RNS, and SEC 20-F when dual-listed. "
            "period=annual|interim|other. Bodies from PDF/HTML/iXBRL when available."
        )
    elif regime == "asx_announcements":
        note = (
            "Primary ASX announcements via Markit Digital JSON feed (direct PDF URLs) "
            "plus Google News fallback (asx.com.au / marketindex.com.au). "
            "period=annual|interim|other. Bodies from downloadable PDF/HTML."
        )
    elif regime == "euro_filings":
        note = (
            "Euro-listed results discovery via Google News and Investegate (when listed), "
            "plus SEC 20-F/6-K when the issuer is dual-listed. period=annual|interim|other. "
            "Bodies when a direct HTML/PDF URL is available."
        )
    elif regime == "tsx_announcements":
        note = (
            "Canadian issuer announcement discovery via Google News (SEDAR+ / "
            "newswire), plus SEC filings when dual-listed. period=annual|interim|other."
        )
    elif regime == "asia_filings":
        note = (
            "Hong Kong / Singapore results discovery via Google News, plus SEC "
            "filings when dual-listed. period=annual|interim|other."
        )
    else:
        note = (
            f"No primary filings source configured for market={market!r} "
            f"(regime={regime}). Yahoo financials remain available as secondary context."
        )

    index = {
        "ticker": ticker,
        "company_name": company_name,
        "market": market,
        "regime": regime,
        "fetched_at": datetime.now(UTC).isoformat(),
        "note": note,
        "sources_used": sorted(
            {str(row.get("source")) for row in merged if row.get("source")}
        ),
        "summary": summarize_filings(merged),
        "filings": merged,
    }

    from value_investor.storage import resolve_json_path, write_json

    index_path = filings_dir / "filings_index.json"
    write_json(index_path, index, compact=True, compress=False)
    prune_orphaned_filing_bodies(filings_dir)
    written = resolve_json_path(index_path) or index_path

    return {
        "filings_index_path": str(written),
        "filings_dir": str(filings_dir),
        "filings_summary": index["summary"],
        "filings_sources": index["sources_used"],
        "filings_regime": regime,
    }
