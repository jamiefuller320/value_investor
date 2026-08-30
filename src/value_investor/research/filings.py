"""Primary regulatory filings for research memos (separate from Yahoo).

Memo-eligible names only. Yahoo remains the screening source; this module
collects primary filings for FINANCIAL REVIEW.

Regimes:
- ``uk_rns`` (FTSE / ``.L``): Ticker.app RNS API + Investegate via Google News
- ``sec_edgar`` (S&P 500 / bare US tickers): SEC EDGAR submissions + HTML bodies
- ``asx_announcements`` (ASX 200 / ``.AX``): Markit Digital JSON feed (direct PDFs) + Google News fallback
- ``euro_filings`` (EURO STOXX 50 / DAX / CAC): results headlines via Google News + SEC 20-F/6-K when dual-listed
- ``tsx_announcements`` (TSX 60 / ``.TO``): SEDAR+ / issuer headlines via Google News

UK RNS headlines are tagged ``period=annual|interim|trading_update|other`` via
:classify_rns_headline`; SEC forms use annual/interim/other from form type.
Companies House rows also carry ``entity_type=consolidated|s838_holding|holding_disclosure|other``
so parent-company s.838 distributable-reserve stubs are not treated as group results.
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
import zipfile
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from io import BytesIO
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

USER_AGENT = "value-investor-research/0.1 (+filings)"
FILINGS_LOOKBACK_DAYS = 800  # ~2.2 years — cover annual + several interims
FILINGS_MAX_ITEMS = 40
FILINGS_BODY_MAX_CHARS = 80_000
# Lead narrative kept from the start; depth sections are spliced from later pages.
_PDF_DEPTH_LEAD_CHARS = 28_000
_PDF_DEPTH_SECTION_CHARS = 6_000
_PDF_DEPTH_MAX_SECTIONS = 8
_PDF_EXTRACT_MAX_PAGES = 200
CH_OCR_MAX_PAGES = int(os.environ.get("COMPANIES_HOUSE_OCR_MAX_PAGES", "12"))
CH_OCR_DPI = int(os.environ.get("COMPANIES_HOUSE_OCR_DPI", "150"))
TICKER_API_BASE = "https://api.tickerapp.net/v2"
DEFAULT_IR_URLS_PATH = Path("docs/data/research_ir_urls.json")
# Code-shipped IR URLs for tickers not yet in research_ir_urls.json (or needing extra decks).
_BUILTIN_IR_URLS: dict[str, list[str]] = {
    "HIK.L": [
        "https://www.hikma.com/media/wsnfgf3v/1-2025-annual-report.pdf",
        "https://www.hikma.com/media/etij3sft/hikma-pharmaceuticals-plc-2025-full-year-results-combined-press-release-vfinal.pdf",
        "https://www.hikma.com/media/5nyls5gx/hikma-2025-interim-results-presentation-07-aug-2025.pdf",
        "https://www.hikma.com/media/1u2besjf/april-2026-trading-update-vfinal.pdf",
    ],
    "ITV.L": [
        "https://www.itvplc.com/~/media/Files/I/ITV-PLC-V2/ITV%20Plc%202025%20FY%20Results%20Presentation.pdf",
        "https://www.itvplc.com/~/media/Files/I/ITV-PLC-V2/ITV%20Plc%20_%202025%20Interim%20Results%20Presentation.pdf",
        "https://www.itvplc.com/~/media/Files/I/ITV-PLC-V2/ITV%20Plc%20FY%202024%20Results%20Presentation%20-%2006032025.pdf",
    ],
    "MEGP.L": [
        "https://me-group.com/wp-content/uploads/2026/03/ME-Group-Annual-Report-2025.pdf",
        "https://me-group.com/wp-content/uploads/2026/03/ME-Group-2025-Annual-Results.pdf",
        "https://me-group.com/wp-content/uploads/2026/03/ME-Group-2025-Annual-Results-Presentation.pdf",
        "https://me-group.com/wp-content/uploads/2026/06/260601-ME-Group-Trading-Update.pdf",
        "https://me-group.com/wp-content/uploads/2026/07/260713-ME-Group-2026-Interim-Results-RNS-FINAL.pdf",
        "https://me-group.com/wp-content/uploads/2025/02/ME-Group-Annual-Report-2024.pdf",
    ],
    "GFTU.L": [
        "https://www.graftonplc.com/~/media/Files/G/Grafton-Group/2025%20FULL%20YEAR%20RESULTS%20march%202026/Grafton-Group%20plc-Final%20Results-31-December-2025-FINAL.pdf",
        "https://www.graftonplc.com/~/media/Files/G/Grafton-Group/2025%20FULL%20YEAR%20RESULTS%20march%202026/Grafton-Group%20plc-Final-Results-2025-Presentation-FINAL.pdf",
        "https://www.graftonplc.com/~/media/Files/G/Grafton-Group/2025%20FULL%20YEAR%20RESULTS%20march%202026/Grafton-Annual-Report-2025.pdf",
        "https://www.graftonplc.com/~/media/Files/G/Grafton-Group/Grafton%20CME26%20all%20docs/Grafton_CME26_Full_Presentation_FINAL_website.pdf",
        "https://www.graftonplc.com/~/media/Files/G/Grafton-Group/trading%20updates%202026/Trading_Update_July_2026_Final.pdf",
        "https://www.graftonplc.com/~/media/Files/G/Grafton-Group/2025%20HYR/Grafton%20Group%20plc%20-%20Interim%20Results%20-%2030%20June%202025%20Final.pdf",
    ],
    "FGP.L": [
        "https://www.firstgroupplc.com/~/media/Files/F/Firstgroup-Plc/reports-and-presentations/presentation/firstgroup-plc-fy-2025-results-presentation.pdf",
        "https://www.firstgroupplc.com/~/media/Files/F/Firstgroup-Plc/reports-and-presentations/presentation/251118-firstgroup-plc-h1-2026-results-presentation.pdf",
        "https://www.firstgroupplc.com/~/media/Files/F/Firstgroup-Plc/reports-and-presentations/press-release/firstgroup-plc-h1-2026-results.pdf",
    ],
    # euro_depth buy-tier deepen — representative periphery / STOXX names without ESEF hits.
    "ACKB.BR": [
        "https://www.avh.be/~/media/Files/A/avh/corp/annual-report-2025-UK/2025-AvH-annualreport_UK_A4.pdf",
    ],
    "UMI.BR": [
        "https://www.umicore.com/files/secure-documents/7cfa416e-e500-4fbd-a040-2b45c0575430.pdf",
        "https://www.umicore.com/files/secure-documents/8b39d7eb-8694-4c9b-9dfc-5b12a2d2cf81.pdf",
    ],
    "MELE.BR": [
        "https://www.melexis.com/-/media/files/documents/investor-relations/2026/en/260204-melexis-q4-2025-investor-presentation.pdf?ts=20260205t0821293810",
        "https://www.melexis.com/-/media/files/documents/press-releases/2026/pr_eng_melexis_q4-2025.pdf?ts=20260203t1849342568",
        "https://www.melexis.com/-/media/files/documents/investor-relations/reports/statutory-reports/en/2024-statutory-report-melexis-en.pdf?ts=20250410t1351177737",
    ],
    "SHEL.L": [
        "https://www.sec.gov/Archives/edgar/data/1306965/000162828026017024/shel-20251231.htm",
        "https://www.sec.gov/Archives/edgar/data/1306965/000130696525000007/shel-20241231.htm",
        "https://www.sec.gov/Archives/edgar/data/1306965/000130696524000026/shel-20231231.htm",
    ],
    "VOE.VI": [
        "https://www.voestalpine.com/group/static/sites/group/.downloads/en/publications-2025-26/2025-26-annual-report.pdf",
    ],
    "BAS.DE": [
        "https://report.basf.com/2025/en/_assets/downloads/full-basf-report-2025-basf-ar25.pdf",
    ],
    "ESSITY-B.ST": [
        "https://assets.www.essity.com/essity/Annual-Report-2025-digital.pdf",
    ],
    "DOC.VI": [
        "https://www.doco.com/Portals/8/berichte/jahres-und-quartalsberichte/en/q4_2526.pdf",
        "https://www.doco.com/Portals/8/berichte/jahres-und-quartalsberichte/en/q4_2425.pdf",
    ],
    "VIG.VI": [
        "https://group.vig/media/kyij42ig/2025-vig-group-annual-report.pdf",
    ],
    "APAM.AS": [
        "https://www.aperam.com/sites/default/files/documents/Aperam_AnnualReport_2025.pdf",
    ],
    "POST.VI": [
        "https://assets.post.at/-/media/Dokumente/En/Investor-Relations/Geschaefts--und-Nachhaltigkeitsberichte/AustrianPost_Annual_Report_2025.pdf",
    ],
    "OMV.VI": [
        "https://reports.omv.com/en/annual-report/2025/_assets/downloads/entire-omv-ar25.pdf",
    ],
    "NVG.LS": [
        "https://thenavigatorcompany.com/wp-content/uploads/2026/02/NVG_Divulgacao_Resultados_2025-1.pdf",
        "https://thenavigatorcompany.com/wp-content/uploads/2025/02/Navigator-l-Divulgacao_Resultados_2024.pdf",
    ],
    "DQ7A.IR": [
        "https://www.dcc.ie/~/media/Files/D/Dcc-Corp-v3/documents/investors/annual-and-sustainability-reports/2025/annual-report-2025.pdf",
    ],
    "NBA.LS": [
        "https://content.novabase.com/storage/uploads/relatorio-contas-novabase-2025-versao-ingles-nao-esef.pdf",
    ],
    "MUV2.DE": [
        "https://www.munichre.com/content/dam/munichre/mrwebsiteslaunches/2025-annual-report/MunichRe-Group-Annual-Report-2025-en.pdf/_jcr_content/renditions/original./MunichRe-Group-Annual-Report-2025-en.pdf",
    ],
    # euro_depth buy-tier deepen — remaining unmeasured STOXX/periphery names (2026-08-27).
    "STR.VI": [
        "https://www.strabag.com/site/strabag-company-locale/get/params_E1717455665/2418307/Annual_and_Sustainability_Report_2025.pdf",
        "https://www.strabag.com/site/strabag-company-locale/get/params_E815001242/2418311/STRABAG_Annual%20Financial%20Report%202025_e.pdf",
    ],
    "VOLV-B.ST": [
        "https://www.volvogroup.com/content/dam/volvo-group/markets/master/news/2026/feb/Volvo-Group-Annual-Report-2025.pdf",
        "https://www.volvogroup.com/content/dam/volvo-group/markets/master/investors/reports-and-presentations/interim-reports/2025/volvo-group-q4-2025-eng.pdf",
    ],
    "GVR.IR": [
        "https://glenveagh.ie/download/annual-report-and-accounts-2025",
    ],
}

# Yahoo base symbol → SEC EDGAR ticker for verified dual-listed EU issuers.
_SEC_TICKER_ALIASES: dict[str, str] = {
    "SHELL": "SHEL",
    "NOVN": "NVS",
    "ABI": "BUD",
    "LOGN": "LOGI",
    "C5H": "CRH",
}

# Cross-listing inheritance for manual IR allowlist URLs (e.g. Amsterdam vs LSE Shell).
_IR_ALLOWLIST_TICKER_ALIASES: dict[str, tuple[str, ...]] = {
    "SHELL.AS": ("SHEL.L",),
}

# filings.xbrl.org entity search aliases when Yahoo/legal names miss the ESEF index.
_ESEF_ENTITY_SEARCH_ALIASES: dict[str, tuple[str, ...]] = {
    "SKF": ("SKF Group",),
    "SKF-B": ("SKF Group",),
}

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
)
_TRADING_UPDATE_PATTERNS = (
    r"\btrading update\b",
    r"\btrading statement\b",
)

# Prefer results / accounts over buybacks and trivia when ranking.
_PRIORITY_PATTERNS = (
    _ANNUAL_PATTERNS
    + _INTERIM_PATTERNS
    + _TRADING_UPDATE_PATTERNS
    + (r"\bannual report and accounts\b",)
)


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
    (r"\b(?:DEFINED BENEFIT|PENSION)\b", 3),
    (r"\b(?:FINANCIAL )?COVENANTS?\b", 3),
    (r"\bBORROWINGS\b", 3),
    (r"\bSEGMENT(?:AL)? (?:INFORMATION|ANALYSIS|REPORTING)\b", 3),
)
_INVESTEGATE_COMPANY_URL = "https://www.investegate.co.uk/company/{epic}"
_INVESTEGATE_USER_AGENT = "value-investor-research/0.1 (+investegate; research@local)"
_INVESTEGATE_MAX_ITEMS = 50
_LSE_RNS_PDF_HOSTS = ("rns-pdf.londonstockexchange.com", "docs.londonstockexchange.com")
_INVESTEGATE_LSE_PDF_PATTERNS = (
    r'https?://(?:www\.)?rns-pdf\.londonstockexchange\.com/rns/[^"\s<>]+\.pdf',
    r'https?://(?:www\.)?docs\.londonstockexchange\.com/[^"\s<>]+\.pdf',
)
# Stub RNS pages ("publishes annual report") often link to IR microsites instead of LSE PDFs.
_INVESTEGATE_PUBLISHER_LINK_PATTERNS = (r"https?://annualreport\.[a-z0-9.-]+",)
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
    text = re.sub(r"\s+", " ", text).strip()
    composed = _compose_filing_body_with_depth_sections(text)
    return composed or text


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
    if "consolidated" in lower and "cash flow" in lower:
        score += 900
    if "exceptional item" in lower:
        score += 700
    if "related party" in lower:
        score += 700
    if "segment" in lower and any(
        token in lower for token in ("information", "analysis", "reporting")
    ):
        score += 500
    if "borrowings" in lower and any(token in lower for token in ("covenant", "facility", "note")):
        score += 600
    if "principal risk" in lower:
        score += 500
    if "defined benefit" in lower or "pension scheme" in lower:
        score += 400
    return score


_CH_FINANCIAL_DEPTH_MARKERS: tuple[str, ...] = (
    "cash flow",
    "defined benefit",
    "pension scheme",
    "borrowings",
    "covenant",
    "principal risk",
    "going concern",
    "related party",
)


def _ch_body_lacks_financial_depth(text: str) -> bool:
    """True when extracted PDF text looks like front-matter only (no notes/statements)."""
    lower = (text or "").lower()
    return not any(marker in lower for marker in _CH_FINANCIAL_DEPTH_MARKERS)


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


def _extract_investegate_html_headline(html: str) -> str | None:
    """Extract the announcement ``<h1>`` title from an Investegate HTML page."""
    match = re.search(r"<h1[^>]*>([\s\S]*?)</h1>", html or "", flags=re.I)
    if not match:
        return None
    headline = _strip_html(match.group(1))
    return headline or None


def _infer_filing_period_from_row(row: dict[str, Any]) -> str:
    """Resolve the effective period tag from indexed metadata and headline/URL cues."""
    period = str(row.get("period") or "other")
    if period != "other":
        return period
    headline = str(row.get("headline") or "")
    inferred = classify_filing_period(headline, category=row.get("category"))
    if inferred != "other":
        return inferred
    url_slug = str(row.get("url") or "").rsplit("/", 1)[-1].replace("-", " ")
    return classify_filing_period(url_slug, category=row.get("category"))


def _is_other_results_rns_row(row: dict[str, Any]) -> bool:
    """True when an indexed ``period=other`` row looks like FY/interim results worth refetching."""
    if str(row.get("period") or "other") != "other" or row.get("has_body"):
        return False
    headline = str(row.get("headline") or "").lower()
    headline = re.sub(r"\s*-\s*investegate\s*$", "", headline, flags=re.I)
    blob = f"{headline} {str(row.get('url') or '').rsplit('/', 1)[-1].replace('-', ' ')}"
    if classify_filing_period(blob, category=row.get("category")) != "other":
        return True
    return bool(re.search(r"\bfy\s*20\d{2}\b|\bfy20\d{2}\b", blob))


def _other_results_rns_priority(row: dict[str, Any]) -> int:
    """Rank ``period=other`` results rows ahead of routine RNS trivia during refetch."""
    if not _is_other_results_rns_row(row):
        return 0
    headline = str(row.get("headline") or "").lower()
    if any(re.search(pat, headline) for pat in _ANNUAL_PATTERNS):
        return 120
    if any(re.search(pat, headline) for pat in _INTERIM_PATTERNS):
        return 110
    if any(re.search(pat, headline) for pat in _TRADING_UPDATE_PATTERNS):
        return 100
    return 90


def _filing_text_is_substantive(text: str, *, min_chars: int = 200) -> bool:
    if not text or len(text) < min_chars:
        return False
    lower = text.lower()
    hits = sum(1 for term in _SUBSTANTIVE_FILING_TERMS if term in lower)
    return hits >= 2 or len(text) >= 1_200


def _sec_filing_base_url(url: str) -> str | None:
    match = re.match(
        r"(https://www\.sec\.gov/Archives/edgar/data/\d+/\d+)/",
        url,
        flags=re.I,
    )
    return match.group(1) if match else None


def _resolve_sec_pdf_candidates(url: str, html: str | None = None) -> list[str]:
    """Build candidate PDF URLs when a SEC primary doc is cover-only HTML."""
    candidates: list[str] = []
    seen: set[str] = set()
    base = _sec_filing_base_url(url)

    def _add(candidate: str) -> None:
        cleaned = candidate.strip()
        if cleaned and cleaned not in seen:
            candidates.append(cleaned)
            seen.add(cleaned)

    if url.lower().endswith("-pdf.htm"):
        _add(url[:-8] + ".pdf")

    if html:
        for href in re.findall(r'href=["\']([^"\']+\.pdf)["\']', html, flags=re.I):
            if href.startswith("http"):
                _add(href)
            elif base:
                _add(f"{base}/{href.lstrip('/')}")

    return candidates


def _try_sec_linked_pdf_body(url: str, html: str) -> str | None:
    """Follow SEC -pdf.htm wrappers and inline PDF hrefs to the substantive exhibit."""
    for pdf_url in _resolve_sec_pdf_candidates(url, html):
        body = fetch_filing_body(pdf_url, allow_sec_exhibits=False)
        if body and _filing_text_is_substantive(body, min_chars=400):
            return body
    return None


def _try_sec_exhibit_body(url: str) -> str | None:
    """When a 6-K primary doc is cover-only, try linked exhibits from the filing index."""
    match = re.match(
        r"(https://www\.sec\.gov/Archives/edgar/data/\d+/\d+)/([^/]+)$",
        url,
        flags=re.I,
    )
    if not match:
        return None
    base, primary_name = match.groups()
    primary_lower = primary_name.lower()
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
    for href in re.findall(r'href="([^"]+\.(?:htm|pdf))"', html, flags=re.I):
        if any(skip in href.lower() for skip in ("-index.htm", ".xsd", ".xml", ".xsl")):
            continue
        if href.startswith("http"):
            candidate = href
        else:
            candidate = f"{base}/{href.lstrip('/')}"
        name = candidate.rsplit("/", 1)[-1].lower()
        if name == primary_lower:
            continue
        candidates.append(candidate)

    def _candidate_rank(candidate: str) -> tuple[int, str]:
        name = candidate.rsplit("/", 1)[-1].lower()
        if name.endswith(".pdf"):
            return (0, name)
        return (1, name)

    candidates.sort(key=_candidate_rank)
    for exhibit_url in candidates[:8]:
        body = fetch_filing_body(exhibit_url, allow_sec_exhibits=False)
        if body and _filing_text_is_substantive(body, min_chars=400):
            return body
    return None


def _parse_investegate_company_page_html(
    html: str,
    *,
    max_items: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pattern = re.compile(
        r"<tr>\s*<td>(\d{2} \w{3} \d{4})</td>\s*<td>([^<]*)</td>[\s\S]*?"
        r'href="(https://www\.investegate\.co\.uk/announcement/[^"]+)"[^>]*>'
        r"([^<]+)</a>",
        flags=re.I,
    )
    for match in pattern.finditer(html):
        date_s, _time_s, link, headline = match.groups()
        headline_clean = unescape(headline.strip())
        # Issuer company page is already scoped — bare titles like "Trading Update"
        # rarely repeat the EPIC or company name.
        try:
            published = datetime.strptime(date_s, "%d %b %Y").replace(tzinfo=UTC).isoformat()
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
                "priority": (
                    125
                    if period in ("annual", "interim")
                    else 100
                    if period == "trading_update"
                    else 90
                ),
            }
        )
        if len(rows) >= max_items:
            break
    return rows


def _fetch_filings_investegate_company_for_epic(
    *,
    epic: str,
    max_items: int = _INVESTEGATE_MAX_ITEMS,
) -> list[dict[str, Any]]:
    url = _INVESTEGATE_COMPANY_URL.format(epic=urllib.parse.quote(epic))
    try:
        raw = _http_get(url, headers={"User-Agent": _INVESTEGATE_USER_AGENT}, timeout=40)
        html = raw.decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.debug("Investegate company page failed for EPIC %s: %s", epic, exc)
        return []
    return _parse_investegate_company_page_html(html, max_items=max_items)


def fetch_filings_investegate_company(
    *,
    ticker: str,
    company_name: str,
    max_items: int = _INVESTEGATE_MAX_ITEMS,
) -> list[dict[str, Any]]:
    """Fetch recent RNS announcements from the issuer's Investegate company page."""
    primary = _base_symbol(ticker)
    if not primary:
        return []
    for epic in _uk_rns_epics(ticker):
        rows = _fetch_filings_investegate_company_for_epic(epic=epic, max_items=max_items)
        if rows:
            if epic != primary:
                logger.info(
                    "Investegate company page: %s matched via alternate EPIC %s (%d rows)",
                    ticker,
                    epic,
                    len(rows),
                )
            else:
                logger.info("Investegate company page: %s → %d announcements", ticker, len(rows))
            return rows
    logger.warning("Investegate company page returned no rows for %s", ticker)
    return []


def _is_lse_rns_url(url: str | None) -> bool:
    """True for LSE RNS hosts including HTML wrapper pages and direct PDFs."""
    lower = (url or "").lower()
    return any(host in lower for host in _LSE_RNS_PDF_HOSTS)


def _is_lse_rns_pdf_url(url: str | None) -> bool:
    return _is_lse_rns_url(url) and (url or "").lower().endswith(".pdf")


def resolve_lse_document_url(html: str) -> str | None:
    """Extract an embedded LSE RNS PDF URL from an LSE HTML wrapper page."""
    for pattern in _INVESTEGATE_LSE_PDF_PATTERNS:
        match = re.search(pattern, html or "", flags=re.I)
        if match:
            return match.group(0)
    return None


def resolve_lse_rns_document_url(url: str | None) -> str | None:
    """
    Upgrade an LSE RNS HTML wrapper to the linked PDF when present.

    Returns ``url`` unchanged when it already points at a PDF or is not LSE RNS.
    """
    if not url or not url.startswith("http"):
        return url
    if _is_lse_rns_pdf_url(url):
        return url
    if not _is_lse_rns_url(url):
        return url
    try:
        raw = _http_get(url, headers={"User-Agent": _INVESTEGATE_USER_AGENT}, timeout=40)
        html = raw.decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.debug("LSE RNS page fetch failed for %s: %s", url, exc)
        return url
    pdf_url = resolve_lse_document_url(html)
    return pdf_url or url


_RNS_BODY_FETCH_SOURCES = frozenset(
    {
        "google_news_investegate",
        "investegate_direct",
        "investegate_resolved",
        "ticker_rns_api",
    }
)

_INDEX_NOISE_HEADLINE_MARKERS = (
    "share price",
    "interactive stock chart",
    "interactive chart",
    "stock chart",
    "yahoo finance",
    "kalkine media",
    "simplywall.st",
    "across the markets:",
)


def _is_index_noise_row(row: dict[str, Any]) -> bool:
    """True when an indexed row without body is headline/URL noise, not a real filing."""
    if row.get("has_body"):
        return False
    url = str(row.get("url") or "").lower()
    if "news.google.com" in url:
        return True
    headline = str(row.get("headline") or "").lower()
    source = str(row.get("source") or "")
    if source.startswith("google_news"):
        return any(marker in headline for marker in _INDEX_NOISE_HEADLINE_MARKERS)
    if "share price" in headline and (
        "investegate" in headline or source.startswith("google_news")
    ):
        return True
    return False


def _is_rns_body_fetch_candidate(row: dict[str, Any]) -> bool:
    """True when a row points at Investegate or LSE RNS content worth body-fetching."""
    url = str(row.get("url") or "")
    if not url or row.get("has_body"):
        return False
    if "news.google.com" in url:
        return False
    source = str(row.get("source") or "")
    return source in _RNS_BODY_FETCH_SOURCES or "investegate.co.uk" in url or _is_lse_rns_url(url)


def _annual_report_microsite_media_base(publisher_url: str) -> str:
    """Map annual-report microsite hosts to the corporate media CDN base URL."""
    parsed = urllib.parse.urlparse(publisher_url)
    host = parsed.netloc.lower()
    if host.startswith("annualreport."):
        brand = host.split("annualreport.", 1)[1]
        return f"https://www.{brand}"
    return f"{parsed.scheme}://{parsed.netloc}"


def _score_annual_report_pdf_href(href: str) -> int:
    """Prefer full annual-report PDFs over section splits or 20-F duplicates."""
    lower = href.lower()
    score = 0
    if "annual-report" in lower or "annual_report" in lower:
        score += 100
    if re.search(r"annual-report-20\d{2}\.pdf", lower):
        score += 50
    if "financial-statements" in lower:
        score += 40
    if "form-20-f" in lower or "/20-f" in lower:
        score -= 30
    year_match = re.search(r"20\d{2}", lower)
    if year_match:
        score += int(year_match.group(0)) - 2000
    return score


def _resolve_annual_report_microsite_pdf(publisher_url: str) -> str | None:
    """
    Follow annual-report microsites (e.g. annualreport.gsk.com) to a downloadable PDF.

    Microsites often serve HTML shells at ``/media/*.pdf`` paths; the real PDFs live on
    the parent ``www.{brand}.com/media/...`` CDN.
    """
    if not publisher_url or not publisher_url.startswith("http"):
        return None
    try:
        raw = _http_get(
            publisher_url.rstrip("/"),
            headers={"User-Agent": _INVESTEGATE_USER_AGENT},
            timeout=40,
        )
        page_html = raw.decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.debug("Annual-report microsite fetch failed for %s: %s", publisher_url, exc)
        return None

    hrefs = re.findall(r'href="([^"]+\.pdf[^"]*)"', page_html, flags=re.I)
    if not hrefs:
        return None

    media_base = _annual_report_microsite_media_base(publisher_url)
    ranked = sorted(set(hrefs), key=_score_annual_report_pdf_href, reverse=True)
    for href in ranked:
        if href.startswith("http"):
            candidate = href
        elif href.startswith("/"):
            candidate = urllib.parse.urljoin(media_base, href)
        else:
            candidate = urllib.parse.urljoin(publisher_url.rstrip("/") + "/", href)
        if candidate.startswith("http"):
            return candidate
    return None


def _resolve_investegate_publisher_annual_report_pdf(html: str) -> str | None:
    """Resolve stub Investegate RNS pages that link to IR annual-report microsites."""
    for pattern in _INVESTEGATE_PUBLISHER_LINK_PATTERNS:
        for match in re.finditer(pattern, html or "", flags=re.I):
            publisher_url = match.group(0).rstrip("/\"'")
            pdf_url = _resolve_annual_report_microsite_pdf(publisher_url)
            if pdf_url:
                return pdf_url
    return None


def resolve_investegate_document_url(html: str) -> str | None:
    """Extract a direct document URL embedded in an Investegate announcement page."""
    pdf_url = resolve_lse_document_url(html)
    if pdf_url:
        return pdf_url
    return _resolve_investegate_publisher_annual_report_pdf(html)


def resolve_investegate_lse_pdf_url(url: str | None) -> str | None:
    """
    Upgrade an Investegate announcement URL to the linked LSE RNS PDF when present.

    Returns ``url`` unchanged when it already points at an LSE PDF or is not Investegate.
    """
    if not url or not url.startswith("http"):
        return url
    if _is_lse_rns_pdf_url(url):
        return url
    if "investegate.co.uk/announcement/" not in url:
        return url
    try:
        raw = _http_get(url, headers={"User-Agent": _INVESTEGATE_USER_AGENT}, timeout=40)
        html = raw.decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.debug("Investegate page fetch failed for %s: %s", url, exc)
        return url
    pdf_url = resolve_investegate_document_url(html)
    return pdf_url or url


def _apply_headline_period(
    row: dict[str, Any],
    *,
    candidate: dict[str, Any] | None = None,
    body_snippet: str | None = None,
) -> dict[str, Any]:
    """Re-classify period and entity_type from headline, CH metadata, and body cues."""
    item = dict(row)
    if candidate:
        if candidate.get("headline"):
            item["headline"] = candidate["headline"]
        if candidate.get("published_at") and not item.get("published_at"):
            item["published_at"] = candidate["published_at"]
    headline = str(item.get("headline") or "")
    summary = str(item.get("summary") or "")
    category = item.get("category")
    period = classify_companies_house_period(summary or headline, category=category)
    if period is None:
        period = classify_filing_period(
            headline,
            category=category,
            form=item.get("form"),
        )
    if period == "other" and body_snippet:
        body_period = classify_filing_period(
            body_snippet[:4000],
            category=category,
            form=item.get("form"),
        )
        if body_period != "other":
            period = body_period
    item["period"] = period
    item["entity_type"] = classify_filing_entity_type(item, body_snippet=body_snippet)
    item["priority"] = _priority_score(
        headline,
        period,
        entity_type=str(item.get("entity_type") or "other"),
    )
    return item


def resolve_investegate_url(
    row: dict[str, Any],
    *,
    ticker: str,
    company_name: str,
    cache: list[dict[str, Any]] | None = None,
) -> str | None:
    """Resolve a Google News wrapper URL to a direct Investegate announcement URL."""
    url = str(row.get("url") or "")
    if "investegate.co.uk/announcement/" in url or _is_lse_rns_url(url):
        return url
    if "news.google.com" in url:
        decoded = resolve_google_news_publisher_url(url)
        if decoded and "news.google.com" not in decoded:
            lower = decoded.lower()
            if "investegate.co.uk/announcement/" in lower or _is_lse_rns_url(decoded):
                return decoded
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
        candidate = by_url.get(resolved) if resolved else None
        if resolved:
            item["url"] = resolved
            if item.get("source") == "google_news_investegate":
                item["source"] = "investegate_resolved"
        item = _apply_headline_period(item, candidate=candidate)
        url = str(item.get("url") or "")
        if url:
            seen_urls.add(url)
        enriched.append(item)
    for row in investegate_rows:
        url = str(row.get("url") or "")
        if url and url not in seen_urls:
            enriched.append(_apply_headline_period(row))
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
    ".VI",
    ".ST",
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


# Alternate LSE/ISE EPICs seen in RNS headlines and Ticker.app metadata (primary EPIC first).
_UK_RNS_EPIC_ALIASES: dict[str, tuple[str, ...]] = {
    "GFTU": ("GN5",),  # Grafton Group: LSE GFTU / ISE GN5
    "C5H": ("CRN",),  # Cairn Homes: ISE C5H.IR / LSE CRN CDI Investegate epic
}


def _uk_rns_epics(ticker: str) -> list[str]:
    """Return primary UK EPIC plus known alternate symbols for the issuer."""
    primary = _base_symbol(ticker).upper()
    if not primary:
        return []
    epics = [primary]
    for alias in _UK_RNS_EPIC_ALIASES.get(primary, ()):
        alias_u = str(alias).strip().upper()
        if alias_u and alias_u not in epics:
            epics.append(alias_u)
    return epics


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


def _issuer_name_phrases(company_name: str) -> list[str]:
    """Leading multi-word brand phrases (e.g. ``me group`` from ME Group International)."""
    lower = (company_name or "").lower()
    for suf in (
        " plc",
        " limited",
        " ltd",
        " sa",
        " se",
        " ag",
        " nv",
        " inc",
        " corp",
        " corporation",
    ):
        if lower.endswith(suf):
            lower = lower[: -len(suf)].strip()
    words = [w for w in re.split(r"[^a-z0-9]+", lower) if w]
    phrases: list[str] = []
    if len(words) >= 2:
        phrases.append(f"{words[0]} {words[1]}")
    if len(words) >= 3:
        phrases.append(f"{words[0]} {words[1]} {words[2]}")
    return phrases


# UK EPICs that collide with unrelated issuer tokens (VCT = Victrex vs Venture Capital Trust).
_AMBIGUOUS_UK_EPICS: frozenset[str] = frozenset({"VCT"})

_VCT_TRUST_HEADLINE = re.compile(
    r"\b(?:\d+\s+)?(?:[\w&]+\s+)*vct\s+plc\b",
    re.I,
)


def _issuer_distinctive_tokens(company_name: str) -> list[str]:
    return [
        tok
        for tok in re.split(r"[^a-z0-9]+", (company_name or "").lower())
        if len(tok) >= 4 and tok not in _ISSUER_STOPWORDS
    ]


def _epic_match_is_ambiguous_noise(
    text: str,
    epic: str,
    *,
    company_name: str,
) -> bool:
    """True when an EPIC word-boundary hit is a known homonym (e.g. VCT trust vs Victrex)."""
    if epic.upper() not in _AMBIGUOUS_UK_EPICS:
        return False
    lower = (text or "").lower()
    if any(tok in lower for tok in _issuer_distinctive_tokens(company_name)):
        return False
    epic_l = epic.lower()
    # Victrex RNS often ends with " - VCT".
    if re.search(rf"[-–]\s*{re.escape(epic_l)}\s*$", lower):
        return False
    if _VCT_TRUST_HEADLINE.search(lower):
        return True
    # "ProVen VCT", "Foresight 4 VCT", etc.
    return bool(re.search(r"\b\w+\s+vct\b", lower))


def headline_relevant_to_issuer(headline: str, company_name: str, ticker: str) -> bool:
    """True when the headline mentions the EPIC or a meaningful company-name token."""
    text = (headline or "").lower()
    if not text:
        return False
    for epic in _uk_rns_epics(ticker):
        epic_l = epic.lower()
        if epic_l and re.search(rf"\b{re.escape(epic_l)}\b", text, flags=re.IGNORECASE):
            if _epic_match_is_ambiguous_noise(text, epic, company_name=company_name):
                continue
            return True
        # ASX Markit headlines often end with " - CSL" / " - WOR".
        if epic_l and re.search(rf"[-–]\s*{re.escape(epic_l)}\s*$", text, flags=re.IGNORECASE):
            return True
    for phrase in _issuer_name_phrases(company_name):
        if phrase in text:
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


def _extract_ch_zip_ixbrl(raw: bytes) -> str | None:
    """Extract narrative text from a Companies House iXBRL zip package."""
    try:
        with zipfile.ZipFile(BytesIO(raw)) as zf:
            html_names = sorted(
                (
                    name
                    for name in zf.namelist()
                    if name.lower().endswith((".html", ".xhtml", ".htm"))
                    and not name.startswith("__MACOSX")
                ),
                key=lambda name: zf.getinfo(name).file_size,
                reverse=True,
            )
            for name in html_names:
                try:
                    payload = zf.read(name)
                except (KeyError, OSError):
                    continue
                text = _extract_ixbrl_html_text(payload.decode("utf-8", errors="replace"))
                if not text or len(text) < 200:
                    text = _strip_html(payload.decode("utf-8", errors="replace"))
                if text and len(text) >= 200:
                    composed = _compose_filing_body_with_depth_sections(text)
                    return composed or text
    except (zipfile.BadZipFile, OSError) as exc:
        logger.debug("CH zip iXBRL extract failed: %s", exc)
    return None


def _extract_filing_document_text(raw: bytes, content_type: str) -> str | None:
    """Extract searchable text from a filing document (PDF, HTML, iXBRL, or zip)."""
    ct = (content_type or "").lower()
    if ct == "application/zip" or raw[:2] == b"PK":
        return _extract_ch_zip_ixbrl(raw)
    if raw[:4] == b"%PDF" or "pdf" in ct:
        text = _extract_pdf_text(raw)
        if not text or len(text) < 200:
            text = _extract_pdf_text_fitz(raw)
        needs_ocr = not text or len(text) < 200 or _ch_body_lacks_financial_depth(text)
        if needs_ocr:
            ocr_text = _ocr_pdf_text(raw)
            if ocr_text:
                ocr_composed = _compose_filing_body_with_depth_sections(ocr_text) or ocr_text
                if text and len(text) >= 200:
                    return (
                        ocr_composed
                        if _score_ch_body_text(ocr_composed) > _score_ch_body_text(text)
                        else text
                    )
                return ocr_composed
        if text and len(text) >= 200:
            return text
        return text
    if _is_ixbrl_html(raw) or "xhtml" in ct:
        return _extract_ixbrl_html_text(raw.decode("utf-8", errors="replace"))
    return _strip_html(raw.decode("utf-8", errors="replace"))


_PDF_DEPTH_SECTION_MARKERS: tuple[tuple[str, int], ...] = (
    (r"\bCONSOLIDATED (?:STATEMENT OF )?CASH FLOW", 1),
    (r"\bCONSOLIDATED CASH FLOW STATEMENT", 1),
    (r"\bSTATEMENT OF CASH FLOWS\b", 1),
    (r"\bCASH FLOW STATEMENT\b", 1),
    (r"\bCONSOLIDATED (?:INCOME|STATEMENT OF COMPREHENSIVE INCOME)\b", 1),
    (r"\bCONSOLIDATED BALANCE SHEET\b", 1),
    (r"\bCONSOLIDATED STATEMENT OF FINANCIAL POSITION\b", 1),
    (r"\b(?:NOTE|NOTES)\s+(?:TO THE )?(?:FINANCIAL|GROUP) STATEMENTS\b", 2),
    (r"\bEXCEPTIONAL ITEMS?\b", 2),
    (r"\bADJUSTING ITEMS?\b", 2),
    (r"\b(?:NOTE|NOTES)\s+\d+[\.\s\-–—]*(?:Exceptional|Adjusting items?)", 2),
    (r"\b(?:NOTE|NOTES)\s+\d+[\.\s\-–—]*Borrowings\b", 2),
    (r"\b(?:NON[- ]CURRENT )?BORROWINGS\b", 2),
    (r"\b(?:DEFINED BENEFIT|PENSION(?: SCHEME| OBLIGATIONS?)?)\b", 2),
    (r"\b(?:FINANCIAL )?COVENANTS?\b", 2),
    (r"\bGOING CONCERN\b", 2),
    (r"\bRELATED PARTY TRANSACTIONS?\b", 3),
    (r"\bRELATED PARTIES\b", 3),
    (r"\bSEGMENT(?:AL)? (?:INFORMATION|ANALYSIS|REPORTING)\b", 3),
    (r"\bGEOGRAPHIC(?:AL)? (?:INFORMATION|SEGMENTS?|ANALYSIS)\b", 3),
    (r"\bANALYSIS BY SEGMENT\b", 3),
    (r"\bOPERATING SEGMENTS?\b", 3),
    (r"\bPRINCIPAL RISKS?(?: AND UNCERTAINTIES)?\b", 2),
    (r"\bVIABILITY STATEMENT\b", 2),
    (r"\b(?:LEGAL|REGULATORY)[-/ ]RISKS?\b", 2),
    (r"\bRISK MANAGEMENT\b", 3),
)


def _extract_pdf_depth_sections(full_text: str, *, skip_before: int = 0) -> list[str]:
    """Pull windows for cash-flow, pensions, covenants, adjusting items, and segment tables."""
    sections: list[str] = []
    used_ranges: list[tuple[int, int]] = []
    for pattern, _rank in _PDF_DEPTH_SECTION_MARKERS:
        for match in re.finditer(pattern, full_text, flags=re.I):
            if match.start() < skip_before:
                continue
            start = max(skip_before, match.start() - 150)
            end = min(len(full_text), match.end() + _PDF_DEPTH_SECTION_CHARS)
            if any(start < used_end and end > used_start for used_start, used_end in used_ranges):
                continue
            chunk = full_text[start:end].strip()
            if len(chunk) < 80:
                continue
            sections.append(chunk)
            used_ranges.append((start, end))
            if len(sections) >= _PDF_DEPTH_MAX_SECTIONS:
                return sections
    return sections


def _compose_filing_body_with_depth_sections(full_text: str) -> str | None:
    """
    Compose filing body text with page-range depth extract.

    Keeps the opening narrative, then splices consolidated cash-flow statements,
    pension/covenant notes, adjusting items, and related-party / segment disclosures
    that often sit beyond the first ~30 pages of annual reports and filed accounts.
    """
    if not full_text.strip():
        return None

    lead_limit = min(_PDF_DEPTH_LEAD_CHARS, len(full_text))
    lead = full_text[:lead_limit].rstrip()
    depth_sections = _extract_pdf_depth_sections(full_text, skip_before=lead_limit)

    parts = [lead]
    for section in depth_sections:
        parts.append("\n\n---\n\n" + section)

    text = "".join(parts).strip()
    if len(text) > FILINGS_BODY_MAX_CHARS:
        text = text[:FILINGS_BODY_MAX_CHARS] + "\n\n[truncated]"
    return text or None


def _compose_pdf_body_text(pages: list[str]) -> str | None:
    """Compose filing body text from PDF pages (see :func:`_compose_filing_body_with_depth_sections`)."""
    full = "\n".join(page.strip() for page in pages if page and page.strip())
    return _compose_filing_body_with_depth_sections(full)


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
        pages: list[str] = []
        for index, page in enumerate(reader.pages):
            if index >= _PDF_EXTRACT_MAX_PAGES:
                break
            try:
                page_text = page.extract_text() or ""
            except Exception:  # noqa: BLE001
                continue
            if page_text.strip():
                pages.append(page_text)
        return _compose_pdf_body_text(pages)
    except Exception as exc:  # noqa: BLE001
        logger.debug("PDF extract failed: %s", exc)
        return None


def _extract_pdf_text_fitz(raw: bytes) -> str | None:
    """Alternate PDF text extract via pymupdf when pypdf output fails validation."""
    try:
        import fitz  # pymupdf
    except ImportError:
        return None
    try:
        doc = fitz.open(stream=raw, filetype="pdf")
        pages: list[str] = []
        for index, page in enumerate(doc):
            if index >= _PDF_EXTRACT_MAX_PAGES:
                break
            try:
                page_text = page.get_text() or ""
            except Exception:  # noqa: BLE001
                continue
            if page_text.strip():
                pages.append(page_text)
        return _compose_pdf_body_text(pages)
    except Exception as exc:  # noqa: BLE001
        logger.debug("pymupdf PDF extract failed: %s", exc)
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
        "euro_depth",
        "dax",
        "cac40",
        "ibex35",
        "ftse_mib",
        "aex",
        "bel20",
        "atx",
        "psi20",
        "smi",
        "omxs30",
        "iseq20",
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


def classify_rns_headline(
    headline: str,
    *,
    category: str | None = None,
) -> str:
    """
    Tag UK RNS announcement headlines as ``annual``, ``interim``, ``trading_update``, or ``other``.

    Trading updates are classified before interim quarter cues so a headline like
    "Q1 Trading Update" is not treated as interim results.
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
    if any(re.search(pat, blob) for pat in _TRADING_UPDATE_PATTERNS):
        return "trading_update"
    if any(re.search(pat, blob) for pat in _INTERIM_PATTERNS):
        return "interim"
    # FCA-style codes sometimes appear in provider metadata
    if re.search(r"\b(fr|final results|annual)\b", blob):
        return "annual"
    if re.search(r"\b(ir|half[- ]year report|interim results)\b", blob):
        return "interim"
    return "other"


def classify_filing_period(
    headline: str,
    *,
    category: str | None = None,
    form: str | None = None,
) -> str:
    """
    Return ``annual``, ``interim``, ``trading_update``, or ``other``.

    Uses SEC form types when present, else :func:`classify_rns_headline`.
    """
    if form:
        form_u = str(form).strip().upper()
        if form_u in SEC_ANNUAL_FORMS:
            return "annual"
        if form_u in SEC_INTERIM_FORMS:
            return "interim"
        if form_u in SEC_OTHER_FORMS or form_u.startswith("8-K"):
            return "other"

    return classify_rns_headline(headline, category=category)


def classify_companies_house_period(
    description: str,
    *,
    category: str | None = None,
) -> str | None:
    """Map Companies House account filing descriptions to ``period`` tags."""
    blob = f"{description or ''} {category or ''}".lower()
    if re.search(r"accounts-type-(?:group|full|total-exemption-full|medium|small)", blob):
        return "annual"
    if re.search(r"accounts-type-interim", blob):
        return "interim"
    if (category or "").lower() == "accounts":
        if re.search(r"\binterim\b", blob):
            return "interim"
        if re.search(
            r"\b(?:group|full|medium|small|micro(?:-entity)?|total-exemption-full)\b",
            blob,
        ):
            return "annual"
    return None


_S838_BODY_PATTERNS = (
    r"\bs\.?\s*838\b",
    r"\bsection\s+838\b",
    r"\bsections\s+836\s+and\s+838\b",
    r"\bparent company financial statements\b",
    r"\bsolely as an individual company\b",
    r"\binformation about .+ solely as an individual company\b",
    r"\bdistributable reserves?\b",
)
_HOLDING_DISCLOSURE_PATTERNS = (
    r"\bform\s+8\.3\b",
    r"\bsection\s+838\b.*\bdisclosure\b",
    r"\bholding[s]?\s+disclosure\b",
)


def classify_filing_entity_type(
    row: dict[str, Any],
    *,
    body_snippet: str | None = None,
) -> str:
    """
    Tag whether a filing is consolidated group results vs a holding / s.838 stub.

    Returns ``consolidated``, ``s838_holding``, ``holding_disclosure``, or ``other``.
    """
    headline = str(row.get("headline") or "")
    summary = str(row.get("summary") or "")
    category = str(row.get("category") or "")
    source = str(row.get("source") or "")
    blob = f"{headline} {summary} {category}".lower()

    if any(re.search(pat, blob, flags=re.I) for pat in _HOLDING_DISCLOSURE_PATTERNS):
        return "holding_disclosure"

    body = (body_snippet or "").lower()
    if body and any(re.search(pat, body, flags=re.I) for pat in _S838_BODY_PATTERNS):
        if re.search(r"\bparent company\b", body, flags=re.I) or re.search(
            r"\bindividual company\b", body, flags=re.I
        ):
            return "s838_holding"

    if source == "companies_house":
        if re.search(r"accounts-type-interim", blob):
            return "s838_holding" if body and "s838" in body else "consolidated"
        if re.search(r"accounts-type-(?:group|full)", blob):
            return "consolidated"

    form = str(row.get("form") or category or "").upper()
    if form in SEC_ANNUAL_FORMS | SEC_INTERIM_FORMS:
        return "consolidated"

    if classify_filing_period(headline, category=category or None, form=row.get("form")) in {
        "annual",
        "interim",
    }:
        return "consolidated"

    return "other"


def _body_snippet_for_row(row: dict[str, Any], filings_dir: Path) -> str | None:
    """Read a short body excerpt for entity-type classification."""
    filings_dir = Path(filings_dir)
    body_path = row.get("body_path")
    candidates: list[Path] = []
    if body_path:
        path = Path(str(body_path))
        candidates.append(path if path.is_absolute() else filings_dir.parent / path)
        candidates.append(filings_dir / "bodies" / path.name)
    row_id = str(row.get("id") or "")
    if row_id:
        candidates.append(filings_dir / "bodies" / f"{row_id}.txt")
    for path in candidates:
        if not path.is_file():
            continue
        try:
            return path.read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            continue
    return None


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
    mapping = _load_sec_ticker_cik_map()
    cik = mapping.get(epic)
    if cik is not None:
        return cik
    alias = _SEC_TICKER_ALIASES.get(epic)
    if alias:
        return mapping.get(alias)
    return None


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
    if norm_company and sec_l:
        short_token = norm_company.split()[0]
        if len(short_token) >= 3 and sec_l.startswith(short_token):
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
    if regime == "sec_edgar":
        return rows
    sec_supplement_ok = _sec_edgar_supplement_allowed(ticker, company_name)
    kept: list[dict[str, Any]] = []
    for row in rows:
        headline = str(row.get("headline") or "")
        source = str(row.get("source") or "")
        if regime == "uk_rns" and (
            source == "ticker_rns_api"
            or source == "investegate_resolved"
            or source.startswith("google_news")
        ):
            if not headline_relevant_to_issuer(headline, company_name, ticker):
                continue
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


def _priority_score(
    headline: str,
    period: str,
    *,
    entity_type: str = "other",
) -> int:
    score = 0
    if period == "annual":
        score += 100
    elif period == "interim":
        score += 80
    elif period == "trading_update":
        score += 60
    lower = (headline or "").lower()
    if any(re.search(pat, lower) for pat in _PRIORITY_PATTERNS):
        score += 20
    if "transaction in own shares" in lower or "director/pdmr" in lower:
        score -= 50
    if entity_type == "s838_holding":
        score -= 40
    elif entity_type == "holding_disclosure":
        score -= 60
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
    if query is None:
        symbol_terms = " OR ".join(_uk_rns_epics(ticker))
        query = (
            f'site:investegate.co.uk "{company_name}" OR {symbol_terms} '
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


ESEF_API_BASE = "https://filings.xbrl.org/api"
ESEF_FILINGS_BASE = "https://filings.xbrl.org"


def _esef_entity_name_variants(company_name: str, *, ticker: str = "") -> list[str]:
    """Candidate legal names for filings.xbrl.org entity search."""
    raw = (company_name or "").strip()
    if not raw:
        return []
    variants: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        cleaned = " ".join(name.split()).strip()
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            variants.append(cleaned)

    _add(raw)
    simplified = re.sub(
        r"\b(AG|SE|SA|S\.A\.|S\.A/NV|plc|PLC|N\.V\.|NV|AB|A/S|ASA|SE & Co\. KGaA|KGaA)\b",
        "",
        raw,
        flags=re.I,
    )
    simplified = re.sub(r"\s+", " ", simplified).strip(" ,.-/")
    if simplified:
        _add(simplified)
    parts = raw.replace(",", " ").split()
    if len(parts) >= 2:
        _add(" ".join(parts[:2]))
    if len(parts) >= 3:
        _add(" ".join(parts[:3]))
    upper = (ticker or "").strip().upper()
    base = _base_symbol(ticker)
    for key in (upper, base):
        for alias in _ESEF_ENTITY_SEARCH_ALIASES.get(key, ()):
            _add(str(alias))
    return variants


def _esef_search_entity_identifier(company_name: str, *, ticker: str = "") -> str | None:
    """Resolve an ESEF entity LEI/identifier via name search."""
    for name in _esef_entity_name_variants(company_name, ticker=ticker):
        query = urllib.parse.urlencode(
            {
                "filter[name]": name,
                "page[size]": "5",
            }
        )
        url = f"{ESEF_API_BASE}/entities?{query}"
        try:
            payload = json.loads(_http_get(url, timeout=30).decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            logger.warning("ESEF entity search failed for %r: %s", name, exc)
            continue
        for row in payload.get("data") or []:
            attrs = row.get("attributes") or {}
            identifier = str(attrs.get("identifier") or "").strip()
            if identifier:
                return identifier
    return None


def fetch_filings_esef_direct(
    *,
    company_name: str,
    ticker: str,
    max_items: int = FILINGS_MAX_ITEMS,
    lookback_days: int = FILINGS_LOOKBACK_DAYS,
) -> list[dict[str, Any]]:
    """
    Fetch EU annual/interim ESEF/iXBRL filings via the public filings.xbrl.org API.

    Returns metadata rows with direct XHTML report URLs suitable for body extraction.
    """
    identifier = _esef_search_entity_identifier(company_name, ticker=ticker)
    if not identifier:
        return []
    query = urllib.parse.urlencode(
        {
            "filter[entity.identifier]": identifier,
            "page[size]": str(max(1, min(max_items, 20))),
            "sort": "-period_end",
        }
    )
    url = f"{ESEF_API_BASE}/filings?{query}"
    try:
        payload = json.loads(_http_get(url, timeout=40).decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.warning("ESEF filings fetch failed for %s (%s): %s", ticker, company_name, exc)
        return []

    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    rows: list[dict[str, Any]] = []
    for item in payload.get("data") or []:
        attrs = item.get("attributes") or {}
        period_end = str(attrs.get("period_end") or "")
        published: str | None = period_end or None
        if period_end:
            try:
                published_dt = datetime.strptime(period_end, "%Y-%m-%d").replace(tzinfo=UTC)
                if published_dt < cutoff:
                    continue
                published = published_dt.isoformat()
            except ValueError:
                published = period_end
        report_path = str(attrs.get("report_url") or "").strip()
        if not report_path:
            continue
        file_url = (
            report_path if report_path.startswith("http") else f"{ESEF_FILINGS_BASE}{report_path}"
        )
        headline = f"ESEF report period end {period_end or 'unknown'}"
        period = classify_filing_period(headline, form="ESEF")
        if period == "other" and period_end:
            month = int(period_end[5:7]) if len(period_end) >= 7 else 0
            period = "interim" if month in {6, 9} else "annual"
        rows.append(
            {
                "id": _filing_id("esef_direct", report_path),
                "source": "esef_direct",
                "headline": headline,
                "published_at": published,
                "url": file_url,
                "period": period,
                "category": "ESEF",
                "summary": headline,
                "has_body": False,
                "body_path": None,
                "priority": _priority_score(headline, period) + 20,
                "entity_identifier": identifier,
            }
        )
        if len(rows) >= max_items:
            break
    if rows:
        logger.info("ESEF direct: %s → %d filings", ticker, len(rows))
    return rows


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
        f"(site:sedarplus.ca OR site:sedar.com OR site:newswire.ca) "
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


def _ticker_rns_item_symbol(item: dict[str, Any]) -> str:
    """Best-effort EPIC/symbol from a Ticker.app RNS API item."""
    for key in ("symbol", "ticker", "epic"):
        val = str(item.get(key) or "").strip().upper()
        if val:
            return _base_symbol(val)
    company = item.get("company") or item.get("issuer") or {}
    if isinstance(company, dict):
        for key in ("symbol", "ticker", "epic"):
            val = str(company.get(key) or "").strip().upper()
            if val:
                return _base_symbol(val)
    symbols = item.get("symbols")
    if isinstance(symbols, list) and symbols:
        first = symbols[0]
        if isinstance(first, str):
            return _base_symbol(first)
        if isinstance(first, dict):
            val = str(first.get("symbol") or first.get("ticker") or "").strip().upper()
            if val:
                return _base_symbol(val)
    return ""


def _ticker_rns_item_matches_issuer(
    item: dict[str, Any],
    *,
    company_name: str,
    ticker: str,
) -> bool:
    """True when API metadata or headline plausibly belongs to the requested issuer."""
    allowed = {sym.upper() for sym in _uk_rns_epics(ticker)}
    item_sym = _ticker_rns_item_symbol(item)
    if item_sym and item_sym.upper() not in allowed:
        return False
    if item_sym and item_sym.upper() in allowed:
        return True
    headline = str(item.get("headline") or item.get("title") or "").strip()
    return headline_relevant_to_issuer(headline, company_name, ticker)


def _is_ticker_rns_pdf_url(url: str | None) -> bool:
    lower = (url or "").lower()
    return "newswire.tickerapp.net" in lower or (
        "tickerapp.net" in lower and lower.endswith(".pdf")
    )


def _fetch_filings_ticker_api_for_epic(
    *,
    epic: str,
    ticker: str,
    company_name: str,
    api_key: str,
    max_items: int,
    lookback_days: int,
) -> list[dict[str, Any]]:
    """Fetch Ticker.app RNS rows for a single EPIC symbol."""
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
        payload = _http_get(url, headers={"x-api-key": api_key, "Accept": "application/json"})
        data = json.loads(payload.decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.warning("Ticker RNS API failed for %s (%s): %s", ticker, epic, exc)
        return []

    warnings = data.get("warnings") if isinstance(data, dict) else None
    if warnings:
        logger.info("Ticker RNS API warnings for %s (%s): %s", ticker, epic, warnings)

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
        if not _ticker_rns_item_matches_issuer(
            item,
            company_name=company_name or epic,
            ticker=ticker,
        ):
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

        # Prefer direct PDF (newswire/LSE) over HTML wrappers for body extract.
        pub_url = None
        pdf_url = None
        html_url = None
        publications = item.get("publication") or item.get("publications") or []
        if isinstance(publications, list):
            for pub in publications:
                if not isinstance(pub, dict):
                    continue
                candidate = pub.get("url") or pub.get("href")
                if not candidate or not str(candidate).startswith("http"):
                    continue
                candidate_s = str(candidate)
                if _is_ticker_rns_pdf_url(candidate_s) or candidate_s.lower().endswith(".pdf"):
                    pdf_url = candidate_s
                elif str(pub.get("type") or "").lower() in ("html", "text", ""):
                    html_url = candidate_s
        pub_url = pdf_url or html_url or item.get("url") or item.get("sourceUrl")
        if pub_url and not _is_ticker_rns_pdf_url(pub_url):
            for fallback in (item.get("url"), item.get("sourceUrl")):
                if fallback and _is_ticker_rns_pdf_url(str(fallback)):
                    pub_url = str(fallback)
                    break

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
            "Ticker RNS API (%s): dropped %s unrelated headline(s) for %s (kept %s)",
            epic,
            skipped_unrelated,
            ticker,
            len(rows),
        )
    return rows


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
    When the primary EPIC returns no rows, known alternate symbols (e.g. GN5
    for GFTU) are tried before giving up.
    """
    key = api_key or os.environ.get("TICKER_API_KEY") or os.environ.get("RNS_API_KEY")
    if not key:
        return []

    for epic in _uk_rns_epics(ticker):
        rows = _fetch_filings_ticker_api_for_epic(
            epic=epic,
            ticker=ticker,
            company_name=company_name,
            api_key=key,
            max_items=max_items,
            lookback_days=lookback_days,
        )
        if rows:
            if epic != _base_symbol(ticker):
                logger.info(
                    "Ticker RNS API: %s matched via alternate EPIC %s (%d rows)",
                    ticker,
                    epic,
                    len(rows),
                )
            return rows
    return []


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
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        json.JSONDecodeError,
        IndexError,
        TypeError,
    ) as exc:
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


def _ch_row_needs_body_refetch(row: dict[str, Any], bodies_dir: Path) -> bool:
    """True when an indexed CH row lacks a substantive on-disk body extract."""
    if not _is_ch_filing_row(row):
        return False
    if not row.get("has_body"):
        return True
    row_id = str(row.get("id") or "")
    body_path = row.get("body_path")
    candidate = Path(str(body_path)) if body_path else Path(bodies_dir) / f"{row_id}.txt"
    if not candidate.is_file():
        return True
    try:
        text = candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return True
    return not _filing_text_is_substantive(text, min_chars=200)


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
    if "investegate.co.uk/announcement/" in url:
        url = resolve_investegate_lse_pdf_url(url) or url
    elif _is_lse_rns_url(url) and not _is_lse_rns_pdf_url(url):
        url = resolve_lse_rns_document_url(url) or url
    headers: dict[str, str] = {}
    if "sec.gov" in url:
        headers["User-Agent"] = _sec_user_agent()
    elif "investegate.co.uk" in url or _is_lse_rns_url(url):
        headers["User-Agent"] = _INVESTEGATE_USER_AGENT
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
            html = raw.decode("utf-8", errors="replace")
            text = _extract_sec_html_text(html)
            if allow_sec_exhibits and not _filing_text_is_substantive(text, min_chars=400):
                pdf_body = _try_sec_linked_pdf_body(url, html)
                if pdf_body:
                    text = pdf_body
                else:
                    exhibit = _try_sec_exhibit_body(url)
                    if exhibit:
                        text = exhibit
        elif "investegate.co.uk" in url:
            html = raw.decode("utf-8", errors="replace")
            text = _extract_investegate_html_text(html)
            if not _filing_text_is_substantive(text):
                pdf_url = resolve_investegate_document_url(html)
                if pdf_url and pdf_url != url:
                    pdf_body = fetch_filing_body(pdf_url, allow_sec_exhibits=allow_sec_exhibits)
                    if pdf_body:
                        text = pdf_body
        elif _is_lse_rns_url(url):
            html = raw.decode("utf-8", errors="replace")
            pdf_url = resolve_lse_document_url(html)
            if pdf_url and pdf_url != url:
                pdf_body = fetch_filing_body(pdf_url, allow_sec_exhibits=allow_sec_exhibits)
                if pdf_body:
                    text = pdf_body
                else:
                    text = _strip_html(html)
            else:
                text = _strip_html(html)
        else:
            html = raw.decode("utf-8", errors="replace")
            text = _extract_ixbrl_html_text(html) if _is_ixbrl_html(html) else _strip_html(html)
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


def _merge_ir_url_lists(*groups: dict[str, list[str]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for group in groups:
        for key, urls in group.items():
            ticker = str(key).upper()
            seen = set(out.get(ticker) or [])
            merged = list(out.get(ticker) or [])
            for url in urls:
                cleaned = str(url).strip()
                if cleaned and cleaned not in seen:
                    merged.append(cleaned)
                    seen.add(cleaned)
            if merged:
                out[ticker] = merged
    return out


def _ir_allowlist_ticker_keys(ticker: str) -> list[str]:
    """Return lookup keys for IR URL allowlist (primary ticker + cross-listing aliases)."""
    upper = (ticker or "").strip().upper()
    keys: list[str] = []
    seen: set[str] = set()

    def _add(key: str) -> None:
        cleaned = str(key or "").strip().upper()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            keys.append(cleaned)

    _add(upper)
    base = _base_symbol(ticker)
    _add(base)
    for alias in _IR_ALLOWLIST_TICKER_ALIASES.get(upper, ()):
        _add(str(alias))
    return keys


def load_ir_url_allowlist(path: Path | None = None) -> dict[str, list[str]]:
    """Manual IR/results PDF URLs by Yahoo ticker (MVP until a generic crawler)."""
    path = path or DEFAULT_IR_URLS_PATH
    file_urls: dict[str, list[str]] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            data = {}
        urls = data.get("urls") if isinstance(data, dict) else data
        if isinstance(urls, dict):
            for key, value in urls.items():
                if isinstance(value, str) and value.strip():
                    file_urls[str(key).upper()] = [value.strip()]
                elif isinstance(value, list):
                    cleaned = [str(u).strip() for u in value if str(u).strip()]
                    if cleaned:
                        file_urls[str(key).upper()] = cleaned
    return _merge_ir_url_lists(file_urls, _BUILTIN_IR_URLS)


def fetch_filings_ir_allowlist(
    ticker: str,
    *,
    path: Path | None = None,
) -> list[dict[str, Any]]:
    """Build filing rows from the optional per-ticker IR URL allowlist."""
    mapping = load_ir_url_allowlist(path)
    urls: list[str] = []
    seen_urls: set[str] = set()
    for key in _ir_allowlist_ticker_keys(ticker):
        for url in mapping.get(key) or []:
            cleaned = str(url).strip()
            if cleaned and cleaned not in seen_urls:
                urls.append(cleaned)
                seen_urls.add(cleaned)
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
        elif any(token in lower for token in ("trading",)):
            period = "trading_update"
        elif any(
            token in lower for token in ("interim", "half", "h1", "q1", "q2", "q3", "10-q", "10q")
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
IR_BODY_MIN_CHARS = 200
_IR_ROW_TOKEN_SKIP = frozenset(
    {"pdf", "vfinal", "final", "allowlist", "document", "media", "files", "presentation"}
)
_IR_PERIOD_HEADLINE_CUES: dict[str, tuple[str, ...]] = {
    "annual": ("full year", "final results", "annual results", "annual report", "fy "),
    "interim": ("half year", "interim", "h1 ", "h2 "),
    "trading_update": ("trading update", "trading statement", "trading"),
}
_IR_WRONG_PERIOD_MARKERS: dict[str, tuple[str, ...]] = {
    "trading_update": (
        r"\bhalf[- ]year results\b",
        r"\binterim results\b",
        r"\bh1 results\b",
        r"\bsix months ended\b",
        r"\binterim report\b",
    ),
    "interim": (
        r"\bfull[- ]year results\b",
        r"\bfinal results\b",
        r"\bannual results\b",
        r"\bannual report\b",
    ),
    "annual": (
        r"\btrading update\b",
        r"\btrading statement\b",
        r"\bhalf[- ]year results\b",
        r"\binterim results\b",
        r"\bh1 results\b",
        r"\bsix months ended\b",
        r"\binterim report\b",
    ),
}


def _ir_body_content_hash(body: str) -> str:
    normalized = re.sub(r"\s+", " ", (body or "").strip().lower())[:8000]
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _filing_body_hashes_from_rows(
    filings: list[dict[str, Any]],
    *,
    bodies_dir: Path | None = None,
) -> dict[str, str]:
    """Map ``body_content_hash`` to row id for indexed filings that already have bodies."""
    out: dict[str, str] = {}
    for row in filings:
        if not row.get("has_body"):
            continue
        row_id = str(row.get("id") or "")
        if not row_id:
            continue
        content_hash = row.get("body_content_hash")
        if not content_hash and bodies_dir is not None:
            body_path = row.get("body_path")
            path = Path(str(body_path)) if body_path else bodies_dir / f"{row_id}.txt"
            if path.is_file():
                try:
                    content_hash = _ir_body_content_hash(
                        path.read_text(encoding="utf-8", errors="replace")
                    )
                except OSError:
                    content_hash = None
        if content_hash:
            out[str(content_hash)] = row_id
    return out


def _reject_duplicate_filing_body_hash(
    row_id: str,
    body: str,
    known_hashes: dict[str, str],
) -> tuple[str, str | None]:
    """Return ``(content_hash, reject_reason)`` when hash already belongs to another row."""
    content_hash = _ir_body_content_hash(body)
    owner = known_hashes.get(content_hash)
    if owner and owner != row_id:
        return content_hash, "duplicate_body"
    return content_hash, None


def _ir_body_title_tokens_match(row: dict[str, Any], body: str) -> bool:
    tokens = _ir_row_search_tokens(row)
    if not tokens:
        return True
    sample = (body or "")[:4000].lower()
    meaningful = [t for t in tokens if len(t) >= 4 or re.fullmatch(r"20\d{2}", t)]
    if not meaningful:
        return True
    return any(tok in sample for tok in meaningful)


def _validate_rns_html_headline_match(
    row: dict[str, Any],
    extracted_headline: str | None,
) -> tuple[bool, str | None]:
    """Reject Investegate HTML when the page ``<h1>`` period disagrees with the indexed row."""
    if not extracted_headline:
        return True, None
    expected = _infer_filing_period_from_row(row)
    if expected not in ("annual", "interim", "trading_update"):
        return True, None
    extracted_period = classify_filing_period(
        extracted_headline,
        category=row.get("category"),
    )
    if extracted_period != "other" and extracted_period != expected:
        return False, "headline_mismatch"
    return True, None


def _validate_filing_body_period_content(row: dict[str, Any], body: str) -> tuple[bool, str | None]:
    """Reject bodies whose period cues clearly mismatch the indexed row tag."""
    expected = _infer_filing_period_from_row(row)
    if expected not in ("annual", "interim", "trading_update"):
        return True, None
    sample = (body or "")[:4000].lower()
    wrong_markers = _IR_WRONG_PERIOD_MARKERS.get(expected, ())
    if wrong_markers and any(re.search(pat, sample) for pat in wrong_markers):
        expected_cues = _IR_PERIOD_HEADLINE_CUES.get(expected, ())
        if not any(cue in sample for cue in expected_cues):
            return False, "period_mismatch"
    return True, None


def _validate_rns_filing_body_content(
    row: dict[str, Any],
    body: str,
    *,
    company_name: str,
    ticker: str,
    extracted_headline: str | None = None,
) -> tuple[bool, str | None]:
    """
    Period/headline/issuer gate before marking UK RNS rows ``has_body``.

    Used by Investegate/LSE and ticker_rns_api refetch passes to reject
    misattributed or period-mismatched PDF/HTML extracts.
    """
    if not body or len(body) < IR_BODY_MIN_CHARS:
        return False, "too_short"
    if extracted_headline:
        valid, reason = _validate_rns_html_headline_match(row, extracted_headline)
        if not valid:
            return False, reason
    valid, reason = _validate_filing_body_period_content(row, body)
    if not valid:
        return False, reason
    if _body_clearly_misattributed(body[:4000], company_name, ticker):
        return False, "issuer_mismatch"
    return True, None


def _try_persist_rns_filing_body(
    item: dict[str, Any],
    body: str,
    *,
    company_name: str,
    ticker: str,
    bodies_dir: Path,
    extracted_headline: str | None = None,
    known_body_hashes: dict[str, str] | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Validate, reclassify ``period``, and persist an RNS body when the gate passes."""
    valid, reason = _validate_rns_filing_body_content(
        item,
        body,
        company_name=company_name,
        ticker=ticker,
        extracted_headline=extracted_headline,
    )
    if not valid:
        return item, reason
    updated = _apply_headline_period(item, body_snippet=body[:4000])
    row_id = str(updated.get("id") or "")
    content_hash, dup_reason = _reject_duplicate_filing_body_hash(
        row_id,
        body,
        known_body_hashes or {},
    )
    if dup_reason:
        return item, dup_reason
    filename = f"{updated['id']}.txt"
    path = bodies_dir / filename
    path.write_text(body, encoding="utf-8")
    updated["has_body"] = True
    updated["body_path"] = str(path)
    updated["body_content_hash"] = content_hash
    if known_body_hashes is not None and row_id:
        known_body_hashes[content_hash] = row_id
    return updated, None


def _validate_ir_allowlist_body_content(row: dict[str, Any], body: str) -> tuple[bool, str | None]:
    """
    Title/period/hash gate before marking IR allowlist rows ``has_body``.

    Rejects bodies whose period cues or URL title tokens clearly mismatch the row.
    """
    if not _filing_text_is_substantive(body, min_chars=IR_BODY_MIN_CHARS):
        return False, "too_short"

    valid, reason = _validate_filing_body_period_content(row, body)
    if not valid:
        return False, reason

    if not _ir_body_title_tokens_match(row, body):
        return False, "title_mismatch"

    url = str(row.get("url") or "")
    row_id = str(row.get("id") or "")
    if row_id.startswith("ir_") and url:
        url_digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        if row_id != f"ir_{url_digest}":
            return False, "id_hash_mismatch"

    return True, None


def _fetch_ir_pdf_alternate_candidates(url: str) -> list[tuple[str, str]]:
    """Try alternate PDF parsers (pymupdf, OCR) when the primary extract fails validation."""
    if not url or not url.startswith("http"):
        return []
    try:
        raw = _http_get(url, timeout=60)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.debug("IR PDF alternate download failed for %s: %s", url, exc)
        return []
    if raw[:4] != b"%PDF" and not str(url).lower().endswith(".pdf"):
        return []

    seen: set[str] = set()
    candidates: list[tuple[str, str]] = []

    def _add(text: str | None, parser: str) -> None:
        if not text or not _filing_text_is_substantive(text, min_chars=IR_BODY_MIN_CHARS):
            return
        key = text[:500]
        if key in seen:
            return
        seen.add(key)
        candidates.append((text, parser))

    _add(_extract_pdf_text_fitz(raw), "pymupdf")
    ocr_text = _ocr_pdf_text(raw)
    if ocr_text:
        _add(_compose_filing_body_with_depth_sections(ocr_text) or ocr_text, "ocr")
    return candidates


def _ir_row_search_tokens(row: dict[str, Any]) -> set[str]:
    """Tokens from an IR allowlist URL/headline for Investegate headline matching."""
    url = str(row.get("url") or "")
    headline = str(row.get("headline") or "")
    filename = url.rsplit("/", 1)[-1].lower()
    blob = f"{filename} {headline.lower()}"
    return {
        tok
        for tok in re.split(r"[^a-z0-9]+", blob)
        if len(tok) >= 3 and tok not in _IR_ROW_TOKEN_SKIP
    }


def _match_ir_row_to_investegate(
    row: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Pick the best Investegate RNS row for an IR allowlist PDF that failed extraction."""
    if not candidates:
        return None
    period = str(row.get("period") or "other")
    tokens = _ir_row_search_tokens(row)
    years = {tok for tok in tokens if re.fullmatch(r"20\d{2}", tok)}

    best: dict[str, Any] | None = None
    best_score = -1
    for candidate in candidates:
        headline = str(candidate.get("headline") or "").lower()
        cand_period = str(candidate.get("period") or classify_filing_period(headline))
        score = 0
        if period != "other" and cand_period == period:
            score += 50
        elif period != "other":
            cues = _IR_PERIOD_HEADLINE_CUES.get(period, ())
            if any(cue in headline for cue in cues):
                score += 30
        score += sum(10 for tok in tokens if tok in headline)
        if years and any(year in headline for year in years):
            score += 20
        if score > best_score:
            best_score = score
            best = candidate
    return best if best_score >= 20 else None


def _fetch_investegate_html_body(url: str) -> str | None:
    """Download Investegate RNS HTML narrative without upgrading to the LSE PDF."""
    if "investegate.co.uk/announcement/" not in url:
        return None
    try:
        raw = _http_get(url, headers={"User-Agent": _INVESTEGATE_USER_AGENT}, timeout=40)
        html = raw.decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.debug("Investegate HTML body fetch failed for %s: %s", url, exc)
        return None
    text = _extract_investegate_html_text(html)
    if not _filing_text_is_substantive(text, min_chars=IR_BODY_MIN_CHARS):
        return None
    if len(text) > FILINGS_BODY_MAX_CHARS:
        text = text[:FILINGS_BODY_MAX_CHARS] + "\n\n[truncated]"
    return text


def _fetch_rns_filing_body_for_refetch(url: str) -> tuple[str | None, str | None]:
    """
    Fetch an RNS body for indexed-without-body refetch.

    Tries the PDF/HTML primary path first, then Investegate HTML-only fallback.
    Returns ``(body, extracted_h1_headline)`` where ``extracted_h1_headline`` is set
    only for the HTML fallback path (used to reject period/headline mismatches).
    """
    body = fetch_filing_body(url)
    if body:
        return body, None
    if "investegate.co.uk/announcement/" not in url:
        return None, None
    try:
        raw = _http_get(url, headers={"User-Agent": _INVESTEGATE_USER_AGENT}, timeout=40)
        html = raw.decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.debug("Investegate HTML refetch failed for %s: %s", url, exc)
        return None, None
    extracted_headline = _extract_investegate_html_headline(html)
    text = _extract_investegate_html_text(html)
    if not _filing_text_is_substantive(text, min_chars=IR_BODY_MIN_CHARS):
        return None, extracted_headline
    if len(text) > FILINGS_BODY_MAX_CHARS:
        text = text[:FILINGS_BODY_MAX_CHARS] + "\n\n[truncated]"
    return text, extracted_headline


def _fetch_ir_allowlist_body(
    row: dict[str, Any],
    *,
    ticker: str,
    company_name: str = "",
    investegate_cache: list[dict[str, Any]] | None = None,
) -> tuple[str | None, str | None]:
    """
    Fetch IR allowlist text from the PDF URL, falling back to Investegate RNS HTML.

    Returns ``(body, source)`` where ``source`` is ``pdf``, ``pdf_pymupdf``, ``pdf_ocr``,
    ``investegate_html``, or ``None``. Bodies must pass title/period/hash validation before
    acceptance; alternate PDF parsers are tried when the primary extract fails validation.
    """
    url = str(row.get("url") or "")
    if not url:
        return None, None

    body = fetch_filing_body(url)
    if body:
        valid, reason = _validate_ir_allowlist_body_content(row, body)
        if valid:
            return body, "pdf"
        logger.debug(
            "IR allowlist primary PDF body rejected for %s: %s",
            row.get("id"),
            reason,
        )

    for alt_body, parser in _fetch_ir_pdf_alternate_candidates(url):
        valid, reason = _validate_ir_allowlist_body_content(row, alt_body)
        if valid:
            source = "pdf" if parser == "pypdf" else f"pdf_{parser}"
            return alt_body, source
        logger.debug(
            "IR allowlist alternate PDF body rejected for %s via %s: %s",
            row.get("id"),
            parser,
            reason,
        )

    if not str(ticker or "").upper().endswith(".L"):
        return None, None

    cache = investegate_cache
    if cache is None:
        cache = fetch_filings_investegate_company(ticker=ticker, company_name=company_name)
    matched = _match_ir_row_to_investegate(row, cache)
    if not matched:
        return None, None
    ig_url = str(matched.get("url") or "")
    html_body = _fetch_investegate_html_body(ig_url)
    if html_body:
        valid, reason = _validate_ir_allowlist_body_content(row, html_body)
        if valid:
            return html_body, "investegate_html"
        logger.debug(
            "IR allowlist Investegate body rejected for %s: %s",
            row.get("id"),
            reason,
        )
    return None, None


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
    company_name: str = "",
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
            "investegate_fallbacks": 0,
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
            "investegate_fallbacks": 0,
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
            "investegate_fallbacks": 0,
            "merge": merge_meta,
            "note": "no missing IR allowlist bodies",
        }

    investegate_cache: list[dict[str, Any]] | None = None
    if str(ticker or "").upper().endswith(".L"):
        investegate_cache = fetch_filings_investegate_company(
            ticker=ticker,
            company_name=company_name,
        )

    bodies_dir.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    retries_used = 0
    investegate_fallbacks = 0
    retry_log: list[dict[str, Any]] = []
    known_body_hashes = _filing_body_hashes_from_rows(filings, bodies_dir=bodies_dir)
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
            fetch_source: str | None = None
            row_url = str(item.get("url") or "")
            row_id = str(item.get("id") or "")
            for attempt in range(max_retries + 1):
                body, fetch_source = _fetch_ir_allowlist_body(
                    item,
                    ticker=ticker,
                    company_name=company_name,
                    investegate_cache=investegate_cache,
                )
                if body:
                    if fetch_source == "investegate_html":
                        outcome = "fetched_investegate"
                    elif fetch_source and fetch_source.startswith("pdf"):
                        outcome = "fetched_pdf"
                    else:
                        outcome = "fetched"
                    retry_log.append(
                        {
                            "filing_id": row_id,
                            "url": row_url,
                            "attempt": attempt + 1,
                            "outcome": outcome,
                            "source": fetch_source,
                        }
                    )
                    logger.info(
                        "IR allowlist body fetched for %s (%s) on attempt %d via %s",
                        ticker,
                        row_id,
                        attempt + 1,
                        fetch_source,
                    )
                    break
                if attempt < max_retries:
                    retries_used += 1
                    retry_log.append(
                        {
                            "filing_id": row_id,
                            "url": row_url,
                            "attempt": attempt + 1,
                            "outcome": "retry",
                            "source": None,
                        }
                    )
                    logger.info(
                        "IR allowlist body fetch retry for %s (%s) attempt %d/%d",
                        ticker,
                        row_id,
                        attempt + 1,
                        max_retries + 1,
                    )
            if not body:
                retry_log.append(
                    {
                        "filing_id": row_id,
                        "url": row_url,
                        "attempt": max_retries + 1,
                        "outcome": "failed",
                        "source": None,
                    }
                )
                logger.warning(
                    "IR allowlist body fetch failed for %s (%s) after %d attempt(s)",
                    ticker,
                    row_id,
                    max_retries + 1,
                )
            if body:
                content_hash, dup_reason = _reject_duplicate_filing_body_hash(
                    row_id,
                    body,
                    known_body_hashes,
                )
                if dup_reason:
                    logger.debug(
                        "IR allowlist body rejected for %s: %s",
                        row_id,
                        dup_reason,
                    )
                    body = None
                else:
                    filename = f"{item['id']}.txt"
                    path = bodies_dir / filename
                    path.write_text(body, encoding="utf-8")
                    item["has_body"] = True
                    item["body_path"] = str(path)
                    item["body_content_hash"] = content_hash
                    known_body_hashes[content_hash] = row_id
                    if fetch_source and fetch_source.startswith("pdf_"):
                        item["body_fetch_parser"] = fetch_source.removeprefix("pdf_")
                    if fetch_source == "investegate_html":
                        investegate_fallbacks += 1
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
        "retry_log": retry_log,
        "investegate_fallbacks": investegate_fallbacks,
        "merge": merge_meta,
        "mandatory": True,
        "note": "refetch_ir_allowlist_filing_bodies",
    }


_BRIDGE_HEADER_RE = re.compile(
    r"\b("
    r"net\s+cash\s+bridge|free\s+cash\s+flow\s+bridge|cash\s+flow\s+bridge|"
    r"adjusted\s+free\s+cash\s+flow"
    r")\b",
    re.IGNORECASE,
)
_CURRENCY_MILLIONS_RE = re.compile(r"£\s*(\d+(?:\.\d+)?)\s*m", re.IGNORECASE)
_SCRAMBLED_AMOUNT_RE = re.compile(r"\((\d+(?:\.\d+)?)\)|(?<![(\d.])(\d+(?:\.\d+)?)(?!\d)")
_MIDDLE_BRIDGE_LABELS = (
    "operating_cash_flow",
    "acquisitions",
    "sales_of_assets",
    "capex_infrastructure",
    "released_from_restricted_deposits",
    "tax",
    "dividends_paid",
    "interest_finance_lease",
)


def _parse_bridge_amount_millions(raw: str, *, negative: bool = False) -> float:
    value = float(raw)
    return -value if negative else value


def _currency_amounts_millions(section: str) -> list[float]:
    return [
        _parse_bridge_amount_millions(match.group(1))
        for match in _CURRENCY_MILLIONS_RE.finditer(section)
    ]


def _extract_bridge_section(text: str) -> tuple[str, str] | None:
    """Return (bridge_type, section_text) when a cash-bridge slide block is found."""
    match = _BRIDGE_HEADER_RE.search(text)
    if not match:
        return None
    start = match.start()
    tail = text[start : start + 3500]
    # Stop at the next major narrative section after label/amount cluster.
    stop = re.search(
        r"\n(?:Continental Europe|North America|United Kingdom|Group overview|"
        r"Appendix|Notes to|ME Group International plc\d+\n£\d)",
        tail,
        re.IGNORECASE,
    )
    section = tail[: stop.start()] if stop else tail
    bridge_type = re.sub(r"\s+", "_", match.group(1).strip().lower())
    return bridge_type, section


def _middle_bridge_amounts(section: str) -> list[float]:
    closing_idx = re.search(r"closing\s+net\s+cash", section, re.IGNORECASE)
    if not closing_idx:
        return []
    amount_blob = section[closing_idx.end() :]
    # Drop explicit opening/closing currency markers; keep the scrambled numeric cluster.
    amount_blob = _CURRENCY_MILLIONS_RE.sub(" ", amount_blob)
    amounts: list[float] = []
    for match in _SCRAMBLED_AMOUNT_RE.finditer(amount_blob):
        raw = match.group(1) or match.group(2)
        negative = bool(match.group(1))
        try:
            value = _parse_bridge_amount_millions(raw, negative=negative)
        except ValueError:
            continue
        # Skip chart-axis ticks, footnote markers, and calendar years from slide headers.
        if abs(value) >= 1900 or abs(value) > 200:
            continue
        if value in {28.0, 29.0, 30.0, 31.0} and value == int(value):
            continue
        if abs(value) < 2 and value not in {1.0, -1.6}:
            continue
        amounts.append(value)
    return amounts


def _map_middle_bridge_lines(amounts: list[float]) -> list[dict[str, Any]]:
    """Heuristically map scrambled slide amounts onto bridge line labels."""
    if not amounts:
        return []

    remaining = list(amounts)
    lines: list[dict[str, Any]] = []

    def _take(label: str, predicate, *, pick: str = "first") -> None:
        nonlocal remaining
        matches = [(idx, amount) for idx, amount in enumerate(remaining) if predicate(amount)]
        if not matches:
            return
        if pick == "min":
            idx, amount = min(matches, key=lambda row: row[1])
        elif pick == "max":
            idx, amount = max(matches, key=lambda row: row[1])
        else:
            idx, amount = matches[0]
        lines.append({"label": label, "amount_millions": amount})
        remaining.pop(idx)

    _take("operating_cash_flow", lambda value: 50 < value <= 200)
    _take("capex_infrastructure", lambda value: value <= -50)
    _take("dividends_paid", lambda value: -40 <= value <= -20, pick="min")
    _take("acquisitions", lambda value: -25 <= value <= -15)
    _take("interest_finance_lease", lambda value: -15 <= value <= -5)
    _take("sales_of_assets", lambda value: 0 < value <= 10)
    _take("released_from_restricted_deposits", lambda value: value == 1.0)
    _take("tax", lambda value: -5 <= value <= -1)

    label_cycle = [
        label for label in _MIDDLE_BRIDGE_LABELS if label not in {row["label"] for row in lines}
    ]
    for amount, label in zip(remaining, label_cycle, strict=False):
        lines.append({"label": label, "amount_millions": amount})
    return lines


def parse_ir_cash_bridge_slides(body_text: str) -> dict[str, Any] | None:
    """
    Parse IR presentation cash-bridge slides into structured bridge metrics.

    Handles PDF extraction noise where labels and amounts are interleaved
    (e.g. ME Group ``Net cash bridge`` deck).
    """
    if not body_text or not body_text.strip():
        return None
    extracted = _extract_bridge_section(body_text)
    if extracted is None:
        return None
    bridge_type, section = extracted
    currency_amounts = _currency_amounts_millions(section)
    opening = currency_amounts[0] if currency_amounts else None
    closing = currency_amounts[1] if len(currency_amounts) >= 2 else None
    middle_amounts = _middle_bridge_amounts(section)
    lines: list[dict[str, Any]] = []
    if opening is not None:
        lines.append({"label": "opening_net_cash", "amount_millions": opening})
    lines.extend(_map_middle_bridge_lines(middle_amounts))
    if closing is not None:
        lines.append({"label": "closing_net_cash", "amount_millions": closing})
    if len(lines) < 2:
        return None

    by_label = {row["label"]: row["amount_millions"] for row in lines}
    derived: dict[str, Any] = {}
    operating = by_label.get("operating_cash_flow")
    capex = by_label.get("capex_infrastructure")
    if operating is not None and capex is not None:
        derived["operating_minus_capex_millions"] = operating + capex
    dividends = by_label.get("dividends_paid")
    if operating is not None and capex is not None and dividends is not None:
        derived["fcf_minus_dividends_millions"] = operating + capex + dividends

    confidence = "high" if opening is not None and closing is not None else "medium"
    return {
        "bridge_type": bridge_type,
        "currency": "GBP",
        "lines": lines,
        "derived": derived,
        "parse_confidence": confidence,
    }


_FCF_DIVISION_SECTION_RE = re.compile(
    r"Appendix:\s*Cash flow by division",
    re.IGNORECASE,
)
_FCF_DIVISION_LABELS = (
    "open_access_other_rail",
    "dft_tocs",
    "first_bus",
    "group_items",
    "total",
)
_SEGMENT_REVENUE_HEADER_RE = re.compile(
    r"\b("
    r"Segmental core revenue|Segment revenue|Revenue by (?:business )?segment|"
    r"Total Studios revenue|Total M&E revenue"
    r")\b",
    re.IGNORECASE,
)
_SEGMENT_REVENUE_LINE_RE = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9 \.&'-]+?)\s+([\d,]+(?:\.\d+)?)\s+([\d,]+(?:\.\d+)?)\s*$"
)
_GEOGRAPHIC_REGION_NAMES = (
    "Island of Ireland",
    "Great Britain",
    "Northern Europe",
    "Continental Europe",
    "North America",
    "United Kingdom",
    "Iberia",
    "GB",
    "MENA",
)


def _split_geographic_region_line(line: str) -> list[str]:
    remaining = line.strip()
    regions: list[str] = []
    ordered = sorted(_GEOGRAPHIC_REGION_NAMES, key=len, reverse=True)
    while remaining:
        matched = False
        for name in ordered:
            if remaining.lower().startswith(name.lower()):
                regions.append(name if name != "GB" else "GB")
                remaining = remaining[len(name) :].strip()
                matched = True
                break
        if not matched:
            break
    return regions


def _recent_percentage_block(lines: list[str], end_index: int, count: int) -> list[float] | None:
    values: list[float] = []
    for line in reversed(lines[max(0, end_index - 15) : end_index]):
        match = re.search(r"(\d+(?:\.\d+)?)\s*%", line)
        if match is None:
            break
        value = float(match.group(1))
        if 0 < value < 100:
            values.append(value)
    if len(values) < count:
        return None
    values.reverse()
    return values[:count]


def parse_ir_geographic_revenue_share(body_text: str) -> dict[str, Any] | None:
    """Parse geographic revenue share percentages from IR deck region slides."""
    if not body_text or not body_text.strip():
        return None

    best: tuple[list[str], list[float]] | None = None
    lines = body_text.splitlines()
    for index, line in enumerate(lines):
        regions = _split_geographic_region_line(line)
        if len(regions) < 3:
            continue
        share_values = _recent_percentage_block(lines, index, len(regions))
        if share_values is None:
            continue
        if best is None or len(regions) > len(best[0]):
            best = (regions, share_values)

    if best is None:
        return None
    regions, share_values = best
    segments = [
        {"segment": region, "group_revenue_pct": pct}
        for region, pct in zip(regions, share_values, strict=True)
    ]
    return {
        "split_type": "geographic_revenue_share",
        "currency": "GBP",
        "segments": segments,
        "parse_confidence": "medium",
    }


_LEASE_MATURITY_SECTION_RE = re.compile(
    r"maturity profile of the Group.s financial liabilities",
    re.IGNORECASE,
)
_LEASES_MATURITY_ROW_RE = re.compile(
    r"^Leases\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d,–\-]+)\s+([\d,]+)",
    re.MULTILINE | re.IGNORECASE,
)
_IFRS16_LIABILITY_TOTAL_RE = re.compile(
    r"£\s*([\d,.]+)\s*m(?:illion)? of IFRS\s*16 lease liabilities",
    re.IGNORECASE,
)
_LEASE_MATURITY_BUCKETS = (
    "within_one_year",
    "year_2",
    "year_3",
    "year_4",
    "year_5",
    "over_5_years",
    "total",
)


def _parse_signed_bridge_amounts(blob: str) -> list[float]:
    amounts: list[float] = []
    for match in re.finditer(r"\((\d+(?:\.\d+)?)\)|(-?\d+(?:\.\d+)?)", blob):
        if match.group(1):
            amounts.append(-float(match.group(1)))
        else:
            amounts.append(float(match.group(2)))
    return amounts


def _parse_table_number(raw: str) -> float | None:
    cleaned = raw.strip().replace(",", "").replace("–", "").replace("-", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_ir_fcf_division_bridge(body_text: str) -> dict[str, Any] | None:
    """Parse divisional free-cash-flow bridge tables (e.g. FirstGroup appendix)."""
    if not body_text or not body_text.strip():
        return None
    match = _FCF_DIVISION_SECTION_RE.search(body_text)
    if match is None:
        return None
    section = body_text[match.start() : match.start() + 2500]
    for line in section.splitlines():
        if not re.match(r"^\s*Free cash flow\b", line, re.IGNORECASE):
            continue
        tail = re.split(r"Free cash flow", line, maxsplit=1, flags=re.IGNORECASE)[-1]
        amounts = _parse_signed_bridge_amounts(tail)
        if len(amounts) < 5:
            continue
        period_amounts = amounts[:5]
        bridge_lines = [
            {"label": label, "amount_millions": amount}
            for label, amount in zip(_FCF_DIVISION_LABELS, period_amounts, strict=True)
        ]
        return {
            "bridge_type": "fcf_by_division",
            "currency": "GBP",
            "lines": bridge_lines,
            "derived": {"total_fcf_millions": period_amounts[-1]},
            "parse_confidence": "high",
        }
    return None


def parse_ir_segment_revenue_splits(body_text: str) -> dict[str, Any] | None:
    """Parse segment revenue split tables from IR presentation PDF extracts."""
    if not body_text or not body_text.strip():
        return None
    match = _SEGMENT_REVENUE_HEADER_RE.search(body_text)
    if match is None:
        return None
    section = body_text[match.start() : match.start() + 900]
    currency = "USD" if "$" in section[:250] else "GBP"
    segments: list[dict[str, Any]] = []
    for line in section.splitlines()[1:]:
        if re.match(r"^\s*Total\b", line, re.IGNORECASE):
            break
        row_match = _SEGMENT_REVENUE_LINE_RE.match(line)
        if row_match is None:
            continue
        name = row_match.group(1).strip()
        if name.lower() in {"total", "group", "notes"}:
            continue
        current = _parse_table_number(row_match.group(2))
        prior = _parse_table_number(row_match.group(3))
        if current is None or prior is None:
            continue
        segments.append(
            {
                "segment": name,
                "revenue_current": current,
                "revenue_prior": prior,
            }
        )
        if len(segments) >= 8:
            break
    if len(segments) < 2:
        return None
    return {
        "split_type": re.sub(r"\s+", "_", match.group(1).strip().lower()),
        "currency": currency,
        "segments": segments,
        "parse_confidence": "high" if len(segments) >= 3 else "medium",
    }


def parse_ir_ifrs16_lease_maturity(body_text: str) -> dict[str, Any] | None:
    """Parse IFRS 16 lease maturity tables or headline lease liability totals."""
    if not body_text or not body_text.strip():
        return None

    section_match = _LEASE_MATURITY_SECTION_RE.search(body_text)
    if section_match is not None:
        section = body_text[section_match.start() : section_match.start() + 2500]
        date_markers = list(re.finditer(r"At\s+31\s+\w+\s+\d{4}", section, flags=re.IGNORECASE))
        search_from = date_markers[-1].start() if date_markers else 0
        leases_match = _LEASES_MATURITY_ROW_RE.search(section[search_from:])
        if leases_match is not None:
            values = [_parse_table_number(raw) for raw in leases_match.groups()]
            if all(value is not None for value in values):
                rows = [
                    {"bucket": bucket, "amount_thousands": value}
                    for bucket, value in zip(_LEASE_MATURITY_BUCKETS, values, strict=True)
                ]
                reporting_date = date_markers[-1].group(0) if date_markers else None
                return {
                    "table_type": "ifrs16_lease_maturity",
                    "currency": "GBP",
                    "unit": "thousands",
                    "reporting_date": reporting_date,
                    "buckets": rows,
                    "parse_confidence": "high",
                }

    total_match = _IFRS16_LIABILITY_TOTAL_RE.search(body_text)
    if total_match is not None:
        total = _parse_table_number(total_match.group(1))
        if total is not None:
            return {
                "table_type": "ifrs16_lease_liability_total",
                "currency": "GBP",
                "unit": "millions",
                "total_lease_liabilities": total,
                "parse_confidence": "medium",
            }
    return None


_OCF_HIGHLIGHT_SECTION_RE = re.compile(
    r"Cash flow,\s*capex,\s*and balance sheet",
    re.IGNORECASE,
)
_OCF_HIGHLIGHT_PAIR_RE = re.compile(
    r"Operating cash flow\s+([\d,]+)\s+([\d,]+)",
    re.IGNORECASE,
)
_SEGMENT_MARGIN_BLOCK_RE = re.compile(
    r"Core\s+operating\s+margin\s+((?:\d+(?:\.\d+)?%\s*){3,8})",
    re.IGNORECASE | re.DOTALL,
)
_INTERIM_SEGMENT_SLIDE_RE = re.compile(
    r"Three high quality businesses|Core\s+Op\s*\nProfit\s*\nCore\s*\nRevenue",
    re.IGNORECASE,
)
_INTERIM_PERIOD_MARKER_RE = re.compile(r"\b1H24\s+1H25\b", re.IGNORECASE)
_INTERIM_NUMBER_PAIR_RE = re.compile(r"^\s*([\d,]+)\s+([\d,]+)\s*$")
_HIKMA_SEGMENT_NAMES = ("Injectables", "Branded", "Hikma Rx")


def parse_ir_operating_cash_flow_highlights(body_text: str) -> dict[str, Any] | None:
    """Parse USD/GBP IR deck operating-cash-flow period pairs (e.g. Hikma H1 slides)."""
    if not body_text or not body_text.strip():
        return None
    section_match = _OCF_HIGHLIGHT_SECTION_RE.search(body_text)
    if section_match is None:
        return None
    section = body_text[section_match.start() : section_match.start() + 1200]
    pair_match = _OCF_HIGHLIGHT_PAIR_RE.search(section)
    if pair_match is None:
        return None
    prior = _parse_table_number(pair_match.group(1))
    current = _parse_table_number(pair_match.group(2))
    if prior is None or current is None:
        return None
    currency = "USD" if "$" in section[:400] else "GBP"
    lines = [
        {"label": "operating_cash_flow_prior", "amount_millions": prior},
        {"label": "operating_cash_flow_current", "amount_millions": current},
    ]
    return {
        "bridge_type": "operating_cash_flow_highlight",
        "currency": currency,
        "lines": lines,
        "derived": {"operating_cash_flow_change_millions": current - prior},
        "parse_confidence": "high",
    }


def parse_ir_segment_operating_margins(body_text: str) -> dict[str, Any] | None:
    """Parse segment core operating margin percentages from IR presentation decks."""
    if not body_text or not body_text.strip():
        return None
    margin_match = _SEGMENT_MARGIN_BLOCK_RE.search(body_text)
    if margin_match is None:
        return None
    percentages = [
        float(value)
        for value in re.findall(r"(\d+(?:\.\d+)?)\s*%", margin_match.group(1))
        if 0 < float(value) < 100
    ]
    if len(percentages) < 4 or len(percentages) % 2 != 0:
        return None
    segment_names = list(_HIKMA_SEGMENT_NAMES)
    if not re.search(r"\bInjectables\b", body_text, re.IGNORECASE):
        segment_names = [f"segment_{index + 1}" for index in range(len(percentages) // 2)]
    segments: list[dict[str, Any]] = []
    for index in range(len(percentages) // 2):
        name = segment_names[index] if index < len(segment_names) else f"segment_{index + 1}"
        segments.append(
            {
                "segment": name,
                "margin_prior_pct": percentages[index * 2],
                "margin_current_pct": percentages[index * 2 + 1],
            }
        )
    if len(segments) < 2:
        return None
    return {
        "split_type": "segment_operating_margin",
        "currency": "USD" if "$" in body_text else "GBP",
        "segments": segments,
        "parse_confidence": "high" if len(segments) >= 3 else "medium",
    }


def _interim_segment_number_pairs(section: str) -> list[tuple[float, float]]:
    pairs: list[tuple[float, float]] = []
    for line in section.splitlines():
        match = _INTERIM_NUMBER_PAIR_RE.match(line)
        if match is None:
            continue
        prior = _parse_table_number(match.group(1))
        current = _parse_table_number(match.group(2))
        if prior is None or current is None:
            continue
        if prior >= 900 or current >= 900:
            continue
        pairs.append((prior, current))
    return pairs


def parse_ir_interim_segment_revenue(body_text: str) -> dict[str, Any] | None:
    """Parse interim segment revenue and core operating profit pairs from IR decks."""
    if not body_text or not body_text.strip():
        return None
    slide_match = _INTERIM_SEGMENT_SLIDE_RE.search(body_text)
    if slide_match is None or not _INTERIM_PERIOD_MARKER_RE.search(body_text):
        return None
    section = body_text[max(0, slide_match.start() - 1200) : slide_match.start()]
    pairs = _interim_segment_number_pairs(section)
    if len(pairs) < 6:
        return None
    revenue_pairs = pairs[1::2][:3]
    profit_pairs = pairs[0::2][:3]
    if len(revenue_pairs) < 3 or len(profit_pairs) < 3:
        return None
    segment_names = list(_HIKMA_SEGMENT_NAMES)
    if not re.search(r"\bInjectables\b", body_text, re.IGNORECASE):
        segment_names = [f"segment_{index + 1}" for index in range(3)]
    segments = [
        {
            "segment": segment_names[index],
            "core_operating_profit_prior": profit_pairs[index][0],
            "core_operating_profit_current": profit_pairs[index][1],
            "revenue_prior": revenue_pairs[index][0],
            "revenue_current": revenue_pairs[index][1],
        }
        for index in range(3)
    ]
    return {
        "split_type": "interim_segment_revenue",
        "currency": "USD" if "$" in section else "GBP",
        "period_labels": ["1H24", "1H25"],
        "segments": segments,
        "parse_confidence": "high",
    }


def _write_ir_presentation_metrics_payload(
    payload: dict[str, Any],
    *,
    sources_dir: Path | None,
) -> None:
    from value_investor.storage import write_json

    payload["bridge_count"] = len(payload.get("bridges") or [])
    payload["segment_split_count"] = len(payload.get("segment_revenue_splits") or [])
    payload["lease_maturity_count"] = len(payload.get("ifrs_16_lease_maturity") or [])
    if sources_dir is not None:
        write_json(
            Path(sources_dir) / "ir_presentation_metrics.json",
            payload,
            compact=False,
            compress=False,
        )


def extract_ir_presentation_metrics(
    filings_dir: Path,
    ticker: str,
    *,
    sources_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Scan IR allowlist filing bodies and extract presentation-grade metrics.

    Parses cash-flow bridges, segment revenue splits, and IFRS 16 lease tables
    when present in IR PDF body extracts. Writes ``ir_presentation_metrics.json``
    under ``sources_dir`` when provided.
    """
    filings_dir = Path(filings_dir)
    index_path = filings_dir / "filings_index.json"
    payload: dict[str, Any] = {
        "ticker": ticker,
        "extracted_at": datetime.now(UTC).isoformat(),
        "bridges": [],
        "segment_revenue_splits": [],
        "ifrs_16_lease_maturity": [],
        "mandatory": bool(fetch_filings_ir_allowlist(ticker)),
    }
    if not index_path.exists():
        payload["note"] = "no filings_index.json"
        _write_ir_presentation_metrics_payload(payload, sources_dir=sources_dir)
        return payload

    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        payload["note"] = f"unreadable index: {exc}"
        _write_ir_presentation_metrics_payload(payload, sources_dir=sources_dir)
        return payload

    bodies_dir = filings_dir / "bodies"
    for row in index.get("filings") or []:
        if not _is_ir_allowlist_row(row) or not row.get("has_body"):
            continue
        body_path = row.get("body_path")
        path = Path(str(body_path)) if body_path else bodies_dir / f"{row['id']}.txt"
        if not path.is_file():
            continue
        try:
            body_text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        source_meta = {
            "source_body_id": row.get("id"),
            "headline": row.get("headline"),
            "period": row.get("period"),
        }
        cash_bridge = parse_ir_cash_bridge_slides(body_text)
        if cash_bridge:
            payload["bridges"].append({**source_meta, **cash_bridge})
        ocf_highlight = parse_ir_operating_cash_flow_highlights(body_text)
        if ocf_highlight:
            payload["bridges"].append({**source_meta, **ocf_highlight})
        fcf_division = parse_ir_fcf_division_bridge(body_text)
        if fcf_division:
            payload["bridges"].append({**source_meta, **fcf_division})
        segment_split = parse_ir_segment_revenue_splits(body_text)
        if segment_split:
            payload["segment_revenue_splits"].append({**source_meta, **segment_split})
        interim_segment = parse_ir_interim_segment_revenue(body_text)
        if interim_segment:
            payload["segment_revenue_splits"].append({**source_meta, **interim_segment})
        segment_margin = parse_ir_segment_operating_margins(body_text)
        if segment_margin:
            payload["segment_revenue_splits"].append({**source_meta, **segment_margin})
        geo_share = parse_ir_geographic_revenue_share(body_text)
        if geo_share:
            payload["segment_revenue_splits"].append({**source_meta, **geo_share})
        lease_table = parse_ir_ifrs16_lease_maturity(body_text)
        if lease_table:
            payload["ifrs_16_lease_maturity"].append({**source_meta, **lease_table})

    _write_ir_presentation_metrics_payload(payload, sources_dir=sources_dir)
    return payload


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
    attempted_ids: set[str] | None = None,
    ticker: str = "",
    company_name: str = "",
) -> list[dict[str, Any]]:
    """Fetch bodies for the highest-priority filings with direct URLs."""
    bodies_dir.mkdir(parents=True, exist_ok=True)
    # Prefer annual/interim first
    candidates = sorted(
        filings,
        key=lambda row: (-int(row.get("priority") or 0), row.get("published_at") or ""),
    )
    downloaded = 0
    known_body_hashes = _filing_body_hashes_from_rows(filings, bodies_dir=bodies_dir)
    updated: list[dict[str, Any]] = []
    for row in candidates:
        row = dict(row)
        if downloaded < max_bodies and not row.get("has_body"):
            period = row.get("period")
            if period in ("annual", "interim", "trading_update", "other"):
                # Always try annual/interim/trading updates; only try a few "other" if slots remain
                if period == "other" and downloaded >= max(4, max_bodies // 2):
                    updated.append(row)
                    continue
                row_id = str(row.get("id") or "").strip()
                if row_id and attempted_ids is not None:
                    attempted_ids.add(row_id)
                body = None
                if _is_ch_filing_row(row):
                    body = _fetch_companies_house_body(row)
                elif row.get("url"):
                    body = fetch_filing_body(str(row["url"]))
                if body:
                    if ticker and company_name and _is_rns_body_fetch_candidate(row):
                        row, _reject_reason = _try_persist_rns_filing_body(
                            row,
                            body,
                            company_name=company_name,
                            ticker=ticker,
                            bodies_dir=bodies_dir,
                            known_body_hashes=known_body_hashes,
                        )
                        if row.get("has_body"):
                            downloaded += 1
                    else:
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


def _load_prior_filings_rows(filings_dir: Path) -> list[dict[str, Any]]:
    """Return rows from an existing ``filings_index.json`` when re-ingesting."""
    index_path = Path(filings_dir) / "filings_index.json"
    if not index_path.exists():
        return []
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        logger.debug("Could not read prior filings index at %s: %s", index_path, exc)
        return []
    filings = payload.get("filings")
    return list(filings) if isinstance(filings, list) else []


def reconcile_filing_body_flags(
    filings: list[dict[str, Any]],
    bodies_dir: Path,
    *,
    company_name: str,
    ticker: str,
) -> list[dict[str, Any]]:
    """
    Re-link on-disk body files when index rows lost ``has_body`` during a rewrite.

    Refetch passes may download ``bodies/{id}.txt`` then a later ``ingest_filings``
    re-ingest clears flags without deleting the files. Book metrics use index
    ``summary.with_body``, so reconciliation prevents silent net-downgrades.
    """
    bodies_dir = Path(bodies_dir)
    reconciled: list[dict[str, Any]] = []
    restored = 0
    for row in filings:
        item = dict(row)
        if item.get("has_body"):
            reconciled.append(item)
            continue
        row_id = str(item.get("id") or "").strip()
        if not row_id:
            reconciled.append(item)
            continue
        candidate = bodies_dir / f"{row_id}.txt"
        if not candidate.is_file():
            reconciled.append(item)
            continue
        try:
            sample = candidate.read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            reconciled.append(item)
            continue
        if _body_clearly_misattributed(sample, company_name, ticker):
            reconciled.append(item)
            continue
        if not _filing_text_is_substantive(sample):
            reconciled.append(item)
            continue
        item["has_body"] = True
        item["body_path"] = str(candidate)
        restored += 1
        reconciled.append(item)
    if restored:
        logger.info(
            "Reconciled %d filing body flag(s) from disk for %s",
            restored,
            ticker,
        )
    return reconciled


def reconcile_filings_index_body_flags(
    filings_dir: Path,
    *,
    company_name: str,
    ticker: str,
) -> dict[str, Any]:
    """Reconcile ``filings_index.json`` body flags against on-disk ``bodies/*.txt``."""
    from value_investor.storage import read_json, write_json

    filings_dir = Path(filings_dir)
    index_path = filings_dir / "filings_index.json"
    if not index_path.exists():
        return {"restored": 0, "with_body_before": 0, "with_body_after": 0, "note": "no index"}
    try:
        payload = read_json(index_path)
    except (OSError, ValueError, TypeError) as exc:
        return {
            "restored": 0,
            "with_body_before": 0,
            "with_body_after": 0,
            "note": str(exc),
        }
    filings = list(payload.get("filings") or [])
    before = sum(1 for row in filings if row.get("has_body"))
    reconciled = reconcile_filing_body_flags(
        filings,
        filings_dir / "bodies",
        company_name=company_name,
        ticker=ticker,
    )
    after = sum(1 for row in reconciled if row.get("has_body"))
    restored = after - before
    if restored > 0:
        payload["filings"] = reconciled
        payload["summary"] = summarize_filings(reconciled)
        payload["reconciled_at"] = datetime.now(UTC).isoformat()
        write_json(index_path, payload, compact=True, compress=False)
    return {
        "restored": restored,
        "with_body_before": before,
        "with_body_after": after,
        "note": "reconcile_filings_index_body_flags",
    }


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
        logger.info(
            "Pruned %d orphaned filing body file(s) under %s", len(removed_paths), bodies_dir
        )
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
    bodies_dir.mkdir(parents=True, exist_ok=True)
    ch_rows = [row for row in filings if _is_ch_filing_row(row)]
    missing = [row for row in ch_rows if _ch_row_needs_body_refetch(row, bodies_dir)]
    if not missing:
        return {
            "attempted": 0,
            "fetched": 0,
            "with_body_before": before,
            "with_body_after": before,
            "note": "no missing CH bodies",
        }

    downloaded = 0
    updated: list[dict[str, Any]] = []
    for row in filings:
        item = dict(row)
        if downloaded < max_bodies and _ch_row_needs_body_refetch(item, bodies_dir):
            body = _fetch_companies_house_body(item)
            if body:
                filename = f"{item['id']}.txt"
                path = bodies_dir / filename
                path.write_text(body, encoding="utf-8")
                item["has_body"] = True
                item["body_path"] = str(path)
                downloaded += 1
            elif item.get("has_body"):
                item["has_body"] = False
                item["body_path"] = None
        updated.append(item)

    after = sum(1 for row in updated if row.get("has_body"))
    payload["filings"] = updated
    payload["summary"] = summarize_filings(updated)
    payload["ch_refetched_at"] = datetime.now(UTC).isoformat()
    index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {
        "attempted": len(missing),
        "fetched": downloaded,
        "with_body_before": before,
        "with_body_after": after,
        "note": "refetch_companies_house_filing_bodies",
    }


def refetch_investegate_filing_bodies(
    filings_dir: Path,
    *,
    ticker: str,
    company_name: str,
    max_bodies: int = 20,
) -> dict[str, Any]:
    """
    Resolve Google News wrappers to Investegate/LSE PDFs and download RNS bodies.

    Used by ingest-improvement and gap-fill when indexed UK RNS rows lack text.
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
    enriched = enrich_filing_rows(
        filings,
        ticker=ticker,
        company_name=company_name,
    )
    filtered = filter_misattributed_filings(
        enriched,
        company_name=company_name,
        ticker=ticker,
        regime="uk_rns",
    )
    misattributed_pruned = len(enriched) - len(filtered)
    if misattributed_pruned:
        logger.info(
            "Pruned %d misattributed filing row(s) for %s during Investegate refetch",
            misattributed_pruned,
            ticker,
        )
    enriched = filtered
    google_news_rejected = sum(
        1
        for row in enriched
        if not row.get("has_body") and "news.google.com" in str(row.get("url") or "")
    )
    missing = [row for row in enriched if _is_rns_body_fetch_candidate(row)]
    missing.sort(
        key=lambda row: (
            -_other_results_rns_priority(row),
            -(row.get("priority") or 0),
        )
    )
    other_results_candidates = sum(1 for row in missing if _is_other_results_rns_row(row))
    index_changed = enriched != filings or misattributed_pruned > 0
    if not missing:
        if index_changed:
            payload["filings"] = enriched
            payload["summary"] = summarize_filings(enriched)
            index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return {
            "attempted": 0,
            "fetched": 0,
            "with_body_before": before,
            "with_body_after": before,
            "google_news_rejected": google_news_rejected,
            "misattributed_pruned": misattributed_pruned,
            "note": "no missing Investegate/LSE bodies",
        }

    bodies_dir.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    body_rejected = 0
    html_fallbacks = 0
    known_body_hashes = _filing_body_hashes_from_rows(enriched, bodies_dir=bodies_dir)
    updated: list[dict[str, Any]] = []
    missing_ids = {row.get("id") for row in missing}
    enriched.sort(
        key=lambda row: (
            0 if row.get("id") in missing_ids else 1,
            -_other_results_rns_priority(row),
            -(row.get("priority") or 0),
        )
    )
    for row in enriched:
        item = dict(row)
        if (
            downloaded < max_bodies
            and item.get("id") in missing_ids
            and item.get("url")
            and not item.get("has_body")
        ):
            body, extracted_headline = _fetch_rns_filing_body_for_refetch(str(item["url"]))
            if body:
                if extracted_headline:
                    html_fallbacks += 1
                item, reject_reason = _try_persist_rns_filing_body(
                    item,
                    body,
                    company_name=company_name,
                    ticker=ticker,
                    bodies_dir=bodies_dir,
                    extracted_headline=extracted_headline,
                    known_body_hashes=known_body_hashes,
                )
                if reject_reason:
                    body_rejected += 1
                elif item.get("has_body"):
                    downloaded += 1
        updated.append(item)

    after = sum(1 for row in updated if row.get("has_body"))
    payload["filings"] = updated
    payload["summary"] = summarize_filings(updated)
    payload["investegate_refetched_at"] = datetime.now(UTC).isoformat()
    index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {
        "attempted": len(missing),
        "fetched": max(0, after - before),
        "with_body_before": before,
        "with_body_after": after,
        "google_news_rejected": google_news_rejected,
        "misattributed_pruned": misattributed_pruned,
        "body_rejected": body_rejected,
        "html_fallbacks": html_fallbacks,
        "other_results_candidates": other_results_candidates,
        "note": "refetch_investegate_filing_bodies",
    }


def refetch_indexed_without_body_filing_bodies(
    filings_dir: Path,
    *,
    ticker: str,
    company_name: str,
    max_bodies: int = 20,
) -> dict[str, Any]:
    """
    Universal pipeline for indexed rows lacking bodies on UK RNS tickers.

    Resolves Google News wrappers to Investegate/LSE direct HTML/PDF URLs,
    rejects unresolvable Google News wrappers, then downloads announcement text.
    """
    investegate = refetch_investegate_filing_bodies(
        filings_dir,
        ticker=ticker,
        company_name=company_name,
        max_bodies=max_bodies,
    )
    ticker_rns = refetch_ticker_rns_api_filing_bodies(
        filings_dir,
        ticker=ticker,
        company_name=company_name,
        max_bodies=max_bodies,
    )
    before = int(investegate.get("with_body_before") or 0)
    after = int(ticker_rns.get("with_body_after") or investegate.get("with_body_after") or before)
    return {
        "investegate": investegate,
        "ticker_rns": ticker_rns,
        "attempted": int(investegate.get("attempted") or 0) + int(ticker_rns.get("attempted") or 0),
        "fetched": int(investegate.get("fetched") or 0) + int(ticker_rns.get("fetched") or 0),
        "with_body_before": before,
        "with_body_after": after,
        "google_news_rejected": int(investegate.get("google_news_rejected") or 0),
        "note": "refetch_indexed_without_body_filing_bodies",
    }


def _prune_residual_index_rows(
    rows: list[dict[str, Any]],
    *,
    attempted_ids: set[str],
    prune_index_noise: bool,
    prune_unfetchable_after_attempt: bool,
) -> tuple[list[dict[str, Any]], int, int]:
    """Drop noise rows and (when intensive) rows that failed a residual body fetch."""
    kept: list[dict[str, Any]] = []
    pruned_noise = 0
    pruned_unfetchable = 0
    for row in rows:
        if row.get("has_body"):
            kept.append(row)
            continue
        row_id = str(row.get("id") or "").strip()
        if prune_index_noise and _is_index_noise_row(row):
            pruned_noise += 1
            continue
        if (
            prune_unfetchable_after_attempt
            and row_id
            and row_id in attempted_ids
            and not row.get("has_body")
        ):
            pruned_unfetchable += 1
            continue
        kept.append(row)
    return kept, pruned_noise, pruned_unfetchable


def refetch_residual_filing_bodies(
    filings_dir: Path,
    *,
    ticker: str,
    company_name: str,
    max_bodies: int = 20,
    prune_index_noise: bool = True,
    prune_unfetchable_after_attempt: bool = False,
) -> dict[str, Any]:
    """
    Final sweep for indexed rows still lacking bodies after source-specific pipelines.

    Covers SEC Edgar HTML, direct PDFs, and other URLs skipped by Investegate/CH
    refetch. Prunes index-noise rows (Google News wrappers, share-price headlines).
    When ``prune_unfetchable_after_attempt`` is set (ingest trials with intensive gap
    closure), also drops rows that were fetched in this pass but still lack bodies.
    """
    filings_dir = Path(filings_dir)
    index_path = filings_dir / "filings_index.json"
    bodies_dir = filings_dir / "bodies"
    empty = {
        "attempted": 0,
        "fetched": 0,
        "pruned": 0,
        "pruned_noise": 0,
        "pruned_unfetchable": 0,
        "with_body_before": 0,
        "with_body_after": 0,
    }
    if not index_path.exists():
        return {**empty, "note": "no filings_index.json"}
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        return {**empty, "note": f"unreadable index: {exc}"}

    filings = list(payload.get("filings") or [])
    before = sum(1 for row in filings if row.get("has_body"))
    enriched = enrich_filing_rows(
        filings,
        ticker=ticker,
        company_name=company_name,
    )
    missing = [row for row in enriched if row.get("url") and not row.get("has_body")]
    if not missing:
        return {
            **empty,
            "with_body_before": before,
            "with_body_after": before,
            "note": "no residual gaps",
        }

    bodies_dir.mkdir(parents=True, exist_ok=True)
    attempted_ids: set[str] = set()
    updated = _write_bodies(
        enriched,
        bodies_dir,
        max_bodies=max_bodies,
        attempted_ids=attempted_ids,
        ticker=ticker,
        company_name=company_name,
    )
    updated, pruned_noise, pruned_unfetchable = _prune_residual_index_rows(
        updated,
        attempted_ids=attempted_ids,
        prune_index_noise=prune_index_noise,
        prune_unfetchable_after_attempt=prune_unfetchable_after_attempt,
    )
    pruned = pruned_noise + pruned_unfetchable

    after = sum(1 for row in updated if row.get("has_body"))
    payload["filings"] = updated
    payload["summary"] = summarize_filings(updated)
    payload["residual_refetched_at"] = datetime.now(UTC).isoformat()
    index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if pruned:
        prune_orphaned_filing_bodies(filings_dir)
    return {
        "attempted": len(attempted_ids),
        "fetched": max(0, after - before),
        "pruned": pruned,
        "pruned_noise": pruned_noise,
        "pruned_unfetchable": pruned_unfetchable,
        "with_body_before": before,
        "with_body_after": after,
        "note": "refetch_residual_filing_bodies",
    }


def refetch_uk_primary_filing_bodies(
    filings_dir: Path,
    *,
    ticker: str,
    company_name: str,
    max_bodies: int = 20,
    prune_failed_residual_fetches: bool = False,
) -> dict[str, Any]:
    """
    UK primary-body pipeline: Companies House filed accounts + LSE/Investegate RNS.

    Resolves Google News wrappers to Investegate/LSE direct URLs, downloads CH
    PDF/iXBRL bodies (with page-range depth extract for pensions, covenants,
    adjusting items, and cash-flow statements), then fills remaining RNS rows.
    A residual sweep runs last for SEC Edgar and other direct URLs still lacking bodies.
    """
    ch = refetch_companies_house_filing_bodies(filings_dir, max_bodies=max_bodies)
    rns = refetch_indexed_without_body_filing_bodies(
        filings_dir,
        ticker=ticker,
        company_name=company_name,
        max_bodies=max_bodies,
    )
    residual = refetch_residual_filing_bodies(
        filings_dir,
        ticker=ticker,
        company_name=company_name,
        max_bodies=max_bodies,
        prune_unfetchable_after_attempt=prune_failed_residual_fetches,
    )
    before = int(ch.get("with_body_before") or 0)
    after = int(residual.get("with_body_after") or rns.get("with_body_after") or before)
    return {
        "companies_house": ch,
        "rns": rns,
        "residual": residual,
        "attempted": (
            int(ch.get("attempted") or 0)
            + int(rns.get("attempted") or 0)
            + int(residual.get("attempted") or 0)
        ),
        "fetched": (
            int(ch.get("fetched") or 0)
            + int(rns.get("fetched") or 0)
            + int(residual.get("fetched") or 0)
        ),
        "with_body_before": before,
        "with_body_after": after,
        "google_news_rejected": int(rns.get("google_news_rejected") or 0),
        "note": "refetch_uk_primary_filing_bodies",
    }


def refetch_ticker_rns_api_filing_bodies(
    filings_dir: Path,
    *,
    ticker: str,
    company_name: str,
    max_bodies: int = 20,
) -> dict[str, Any]:
    """
    Download PDF/text bodies for indexed ``ticker_rns_api`` rows (newswire URLs).

    Prunes mis-attributed global-feed headlines, then fetches direct PDF bodies.
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
            "pruned": 0,
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
            "pruned": 0,
            "note": f"unreadable index: {exc}",
        }

    filings = list(payload.get("filings") or [])
    before = sum(1 for row in filings if row.get("has_body"))
    filtered = filter_misattributed_filings(
        filings,
        company_name=company_name,
        ticker=ticker,
        regime="uk_rns",
    )
    pruned = len(filings) - len(filtered)
    missing = [
        row
        for row in filtered
        if str(row.get("source") or "") == "ticker_rns_api"
        and row.get("url")
        and not row.get("has_body")
    ]
    if not missing:
        if pruned:
            payload["filings"] = filtered
            payload["summary"] = summarize_filings(filtered)
            payload["ticker_rns_pruned_at"] = datetime.now(UTC).isoformat()
            index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return {
            "attempted": 0,
            "fetched": 0,
            "with_body_before": before,
            "with_body_after": before,
            "pruned": pruned,
            "note": "no missing ticker_rns_api bodies",
        }

    bodies_dir.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    body_rejected = 0
    known_body_hashes = _filing_body_hashes_from_rows(filtered, bodies_dir=bodies_dir)
    missing_ids = {row.get("id") for row in missing}
    updated: list[dict[str, Any]] = []
    for row in filtered:
        item = dict(row)
        if (
            downloaded < max_bodies
            and item.get("id") in missing_ids
            and item.get("url")
            and not item.get("has_body")
        ):
            body = fetch_filing_body(str(item["url"]))
            if body:
                item, reject_reason = _try_persist_rns_filing_body(
                    item,
                    body,
                    company_name=company_name,
                    ticker=ticker,
                    bodies_dir=bodies_dir,
                    known_body_hashes=known_body_hashes,
                )
                if reject_reason:
                    body_rejected += 1
                elif item.get("has_body"):
                    downloaded += 1
        updated.append(item)

    after = sum(1 for row in updated if row.get("has_body"))
    payload["filings"] = updated
    payload["summary"] = summarize_filings(updated)
    payload["ticker_rns_refetched_at"] = datetime.now(UTC).isoformat()
    index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {
        "attempted": len(missing),
        "fetched": max(0, after - before),
        "with_body_before": before,
        "with_body_after": after,
        "pruned": pruned,
        "body_rejected": body_rejected,
        "note": "refetch_ticker_rns_api_filing_bodies",
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
    bodies_dir.mkdir(parents=True, exist_ok=True)
    ch_result = refetch_companies_house_filing_bodies(filings_dir, max_bodies=max_bodies)
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        payload = {"filings": filings}
    filings = list(payload.get("filings") or filings)
    remaining = max(0, max_bodies - int(ch_result.get("fetched") or 0))
    mid = int(ch_result.get("with_body_after") or before)
    missing = [row for row in filings if row.get("url") and not row.get("has_body")]
    updated = _write_bodies(
        filings,
        bodies_dir,
        max_bodies=remaining,
        ticker=ticker,
        company_name=company_name,
    )
    after = sum(1 for row in updated if row.get("has_body"))
    payload["filings"] = updated
    payload["summary"] = summarize_filings(updated)
    payload["refetched_at"] = datetime.now(UTC).isoformat()
    index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {
        "attempted": int(ch_result.get("attempted") or 0) + len(missing),
        "fetched": int(ch_result.get("fetched") or 0) + max(0, after - mid),
        "with_body_before": before,
        "with_body_after": after,
        "note": "refetch_missing_filing_bodies",
    }


def _row_counts_toward_period_coverage(row: dict[str, Any]) -> bool:
    """Parent-only s.838 stubs must not satisfy interim/annual body-gap scoring."""
    entity = str(row.get("entity_type") or "other")
    return entity not in ("s838_holding", "holding_disclosure")


def period_body_coverage(filings: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Count indexed filings and downloaded bodies per ``period`` tag."""
    periods = ("annual", "interim", "trading_update", "other")
    coverage = {period: {"total": 0, "with_body": 0} for period in periods}
    for row in filings:
        if not _row_counts_toward_period_coverage(row):
            continue
        period = str(row.get("period") or "other")
        if period not in coverage:
            period = "other"
        coverage[period]["total"] += 1
        if row.get("has_body"):
            coverage[period]["with_body"] += 1
    return coverage


def summarize_filings(filings: list[dict[str, Any]]) -> dict[str, Any]:
    annual = sum(1 for f in filings if f.get("period") == "annual")
    interim = sum(1 for f in filings if f.get("period") == "interim")
    trading_update = sum(1 for f in filings if f.get("period") == "trading_update")
    other = sum(1 for f in filings if f.get("period") == "other")
    with_body = sum(1 for f in filings if f.get("has_body"))
    return {
        "total": len(filings),
        "annual": annual,
        "interim": interim,
        "trading_update": trading_update,
        "other": other,
        "with_body": with_body,
        "period_coverage": period_body_coverage(filings),
    }


def sanitize_filings_index(
    filings_dir: Path,
    *,
    company_name: str,
    ticker: str,
    regime: str = "uk_rns",
) -> dict[str, Any]:
    """
    Prune mis-attributed index rows and reclassify annual/interim/trading_update periods.

    Safe to call at the start of an ingest-improvement pass before refetching bodies.
    """
    from value_investor.storage import read_json, write_json

    filings_dir = Path(filings_dir)
    index_path = filings_dir / "filings_index.json"
    if not index_path.exists():
        return {
            "pruned": 0,
            "reclassified": 0,
            "with_body_before": 0,
            "with_body_after": 0,
            "note": "no filings_index.json",
        }
    try:
        payload = read_json(index_path)
    except (OSError, ValueError, TypeError) as exc:
        return {
            "pruned": 0,
            "reclassified": 0,
            "with_body_before": 0,
            "with_body_after": 0,
            "note": str(exc),
        }

    filings = list(payload.get("filings") or [])
    before = sum(1 for row in filings if row.get("has_body"))
    filtered = filter_misattributed_filings(
        filings,
        company_name=company_name,
        ticker=ticker,
        regime=regime,
    )
    reclassified = [
        _apply_headline_period(
            row,
            body_snippet=_body_snippet_for_row(row, filings_dir),
        )
        for row in filtered
    ]
    pruned = len(filings) - len(reclassified)
    changed = pruned > 0 or reclassified != filings
    if changed:
        payload["filings"] = reclassified
        payload["summary"] = summarize_filings(reclassified)
        payload["sanitized_at"] = datetime.now(UTC).isoformat()
        write_json(index_path, payload, compact=True, compress=False)
        prune_orphaned_filing_bodies(filings_dir)
        prune_misattributed_filing_bodies(
            filings_dir,
            company_name=company_name,
            ticker=ticker,
        )

    after = sum(1 for row in reclassified if row.get("has_body"))
    return {
        "pruned": pruned,
        "reclassified": len(reclassified),
        "with_body_before": before,
        "with_body_after": after,
        "note": "sanitize_filings_index",
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
    prior_filings = _load_prior_filings_rows(filings_dir)
    if prior_filings:
        groups.append(prior_filings)
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
        groups.append(fetch_filings_asx_direct(company_name=company_name, ticker=ticker))
        groups.append(fetch_filings_asx_news(company_name=company_name, ticker=ticker))
    elif regime == "euro_filings":
        groups.append(fetch_filings_esef_direct(company_name=company_name, ticker=ticker))
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
    merged = _write_bodies(
        merged,
        bodies_dir,
        max_bodies=max_bodies,
        ticker=ticker,
        company_name=company_name,
    )
    merged = _scrub_misattributed_filing_rows(
        merged,
        bodies_dir,
        company_name=company_name,
        ticker=ticker,
    )
    merged = reconcile_filing_body_flags(
        merged,
        bodies_dir,
        company_name=company_name,
        ticker=ticker,
    )
    merged = [
        _apply_headline_period(
            row,
            body_snippet=_body_snippet_for_row(row, filings_dir),
        )
        for row in merged
    ]

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
            "period=annual|interim|trading_update|other. Bodies from PDF/HTML/iXBRL when available."
        )
    elif regime == "asx_announcements":
        note = (
            "Primary ASX announcements via Markit Digital JSON feed (direct PDF URLs) "
            "plus Google News fallback (asx.com.au / marketindex.com.au). "
            "period=annual|interim|other. Bodies from downloadable PDF/HTML."
        )
    elif regime == "euro_filings":
        note = (
            "Euro-listed results discovery via ESEF (filings.xbrl.org when available), "
            "Google News, optional IR allowlist URLs, Investegate (when listed), "
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
        "sources_used": sorted({str(row.get("source")) for row in merged if row.get("source")}),
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
