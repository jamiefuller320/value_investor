"""Primary regulatory filings for research memos (separate from Yahoo).

Memo-eligible names only. Yahoo remains the screening source; this module
collects primary filings for FINANCIAL REVIEW.

Regimes:
- ``uk_rns`` (FTSE / ``.L``): Ticker.app RNS API + Investegate via Google News
- ``sec_edgar`` (S&P 500 / bare US tickers): SEC EDGAR submissions + HTML bodies
- ``asx_announcements`` (ASX 200 / ``.AX``): ASX / Market Index via Google News
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
) -> list[dict[str, Any]]:
    """Discover Euro-listed results releases via Google News headlines."""
    epic = _base_symbol(ticker)
    query = (
        f'("{company_name}" OR {epic} OR {ticker}) '
        f'("Annual Report" OR "Full Year Results" OR "Half-year Results" OR '
        f'"Interim Results" OR "Quarterly Results" OR "Half Year Results" OR '
        f'"Preliminary Results")'
    )
    return fetch_filings_google_news(
        company_name=company_name,
        ticker=ticker,
        max_items=max_items,
        lookback_days=lookback_days,
        query=query,
        source_label="google_news_euro",
        hl="en",
        gl="DE",
        ceid="DE:en",
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


def fetch_filing_body(url: str | None) -> str | None:
    """Download and extract plain text from a direct announcement URL."""
    if not url or not url.startswith("http"):
        return None
    # Google News wrappers rarely expose the publisher body.
    if "news.google.com" in url:
        return None
    headers: dict[str, str] = {}
    if "sec.gov" in url:
        headers["User-Agent"] = _sec_user_agent()
    try:
        raw = _http_get(url, headers=headers, timeout=60)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.debug("Filing body fetch failed for %s: %s", url, exc)
        return None

    # urlopen doesn't return headers here easily — sniff
    if raw[:4] == b"%PDF":
        text = _extract_pdf_text(raw)
        if not text or len(text) < 200:
            logger.info("PDF filing body empty/unreadable: %s", url)
            return None
    else:
        text = _strip_html(raw.decode("utf-8", errors="replace"))
        if len(text) < 200:
            return None
    if len(text) > FILINGS_BODY_MAX_CHARS:
        text = text[:FILINGS_BODY_MAX_CHARS] + "\n\n[truncated]"
    return text


def _source_bonus(source: str | None) -> int:
    if source in {"ticker_rns_api", "sec_edgar", "companies_house"}:
        return 30
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
                if row.get("source") == "companies_house" and (
                    row.get("document_metadata_url") or row.get("url")
                ):
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
    for raw, content_type in downloads:
        text = _extract_filing_document_text(raw, content_type)
        if not text or len(text) < 200:
            continue
        if len(text) > FILINGS_BODY_MAX_CHARS:
            text = text[:FILINGS_BODY_MAX_CHARS] + "\n\n[truncated]"
        return text
    return None


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
    missing = [
        row
        for row in filings
        if row.get("url")
        and not row.get("has_body")
        and "news.google.com" not in str(row.get("url") or "")
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
            fetch_filings_companies_house(
                ticker=ticker,
                company_name=company_name,
                max_accounts=int(ch_accounts),
            )
        )
        # Dual-listed UK names (e.g. RIO.L, SHEL.L) also file 20-F with the SEC.
        if resolve_sec_cik(_base_symbol(ticker)):
            groups.append(
                fetch_filings_sec_edgar(
                    ticker=_base_symbol(ticker),
                    include_current_reports=False,
                )
            )
    elif regime == "sec_edgar":
        groups.append(fetch_filings_sec_edgar(ticker=ticker))
    elif regime == "asx_announcements":
        groups.append(fetch_filings_asx_news(company_name=company_name, ticker=ticker))
    elif regime == "euro_filings":
        groups.append(fetch_filings_euro_news(company_name=company_name, ticker=ticker))
        # Dual-listed names may also file 20-F / 6-K with the SEC.
        groups.append(fetch_filings_sec_edgar(ticker=_base_symbol(ticker)))
    elif regime == "tsx_announcements":
        groups.append(fetch_filings_tsx_news(company_name=company_name, ticker=ticker))
        groups.append(fetch_filings_sec_edgar(ticker=_base_symbol(ticker)))
    elif regime == "asia_filings":
        groups.append(fetch_filings_asia_news(company_name=company_name, ticker=ticker))
        groups.append(fetch_filings_sec_edgar(ticker=_base_symbol(ticker)))
    else:
        logger.info(
            "No filings regime for market=%s ticker=%s — writing empty index",
            market,
            ticker,
        )

    # Optional manual IR/results PDFs (MVP until a generic IR crawler).
    groups.append(fetch_filings_ir_allowlist(ticker))

    merged = merge_filings(*groups) if groups else []
    # Allow more bodies when deepening historical accounts for memo names.
    max_bodies = 20 if deepen_history else 12
    merged = _write_bodies(merged, bodies_dir, max_bodies=max_bodies)

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
            + "), optional IR allowlist URLs, and SEC 20-F when dual-listed. "
            "period=annual|interim|other. Bodies from PDF/HTML/iXBRL when available."
        )
    elif regime == "asx_announcements":
        note = (
            "Primary ASX announcement discovery via Google News (asx.com.au / "
            "marketindex.com.au). period=annual|interim|other. Bodies only when a "
            "direct publisher URL is downloadable; many ASX PDFs are not parsed."
        )
    elif regime == "euro_filings":
        note = (
            "Euro-listed results discovery via Google News, plus SEC 20-F/6-K when "
            "the issuer is dual-listed. period=annual|interim|other. Bodies when a "
            "direct HTML URL is available."
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
    written = resolve_json_path(index_path) or index_path

    return {
        "filings_index_path": str(written),
        "filings_dir": str(filings_dir),
        "filings_summary": index["summary"],
        "filings_sources": index["sources_used"],
        "filings_regime": regime,
    }
