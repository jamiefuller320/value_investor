"""Companies House Public Data API — free statutory accounts for UK research.

Auth: HTTP Basic with API key as username and empty password.
Env: COMPANIES_HOUSE_API_KEY

Docs: https://developer.company-information.service.gov.uk/
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CH_API_BASE = "https://api.company-information.service.gov.uk"
CH_DOCUMENT_API_BASE = "https://document-api.company-information.service.gov.uk"
DEFAULT_COMPANY_MAP_PATH = Path("docs/data/companies_house_numbers.json")
USER_AGENT = "value-investor-research/0.1 (+companies-house)"
DEFAULT_MAX_ACCOUNTS = 2
DEEPEN_MAX_ACCOUNTS = 5  # historical depth for memo tickers
RATE_LIMIT_SLEEP_S = 0.6
# Group accounts PDFs can be tens of MB; allow room for the S3 hop.
DOCUMENT_DOWNLOAD_TIMEOUT_S = 300.0
MAX_DOCUMENT_BYTES = 80_000_000
# Image-only group accounts bury consolidated notes after the strategic report; OCR more pages.
CH_DEEPEN_OCR_MAX_PAGES = int(os.environ.get("COMPANIES_HOUSE_DEEPEN_OCR_MAX_PAGES", "48"))
_CH_DEEPEN_SECTION_MARKERS: tuple[tuple[str, int], ...] = (
    (r"\bNOTES TO THE (?:CONSOLIDATED )?(?:FINANCIAL|GROUP) STATEMENTS\b", 1),
    (r"\bCONSOLIDATED (?:STATEMENT OF )?CASH FLOW\b", 1),
    (r"\bCONSOLIDATED (?:INCOME|STATEMENT OF COMPREHENSIVE INCOME)\b", 1),
    (r"\b(?:NOTE|NOTES)\s+\d+[\.\s\-–—]*Contract assets\b", 2),
    (r"\bCONTRACT ASSETS\b", 2),
    (r"\b(?:NOTE|NOTES)\s+\d+[\.\s\-–—]*Joint ventures?\b", 2),
    (r"\bINVESTMENTS IN JOINT VENTURES\b", 2),
    (r"\bJOINT VENTURES?\b", 2),
    (r"\bTRADE AND OTHER RECEIVABLES\b", 2),
    (r"\b(?:NOTE|NOTES)\s+\d+[\.\s\-–—]*Borrowings\b", 2),
    (r"\b(?:DEFINED BENEFIT|PENSION)\b", 2),
    (r"\bRELATED PARTY TRANSACTIONS?\b", 3),
    (r"\bSEGMENT(?:AL)? (?:INFORMATION|ANALYSIS|REPORTING)\b", 3),
)
_CH_DEEPEN_SECTION_CHARS = 6_500
_CH_DEEPEN_MAX_SECTIONS = 10
_CH_IXBRL_DEEPEN_TAG_HINTS: tuple[str, ...] = (
    "contractasset",
    "contractassets",
    "jointventure",
    "jointventures",
    "investmentsinjointventures",
    "tradereceivables",
    "borrowings",
    "definedbenefit",
    "segment",
    "relatedparty",
    "consolidated",
    "cashflow",
)
_CH_IXBRL_NONNUMERIC_RE = re.compile(
    r"<(?:ix:)?nonNumeric\b[^>]*\bname=(['\"])([^'\"]+)\1[^>]*>"
    r"([\s\S]*?)</(?:ix:)?nonNumeric>",
    flags=re.I,
)


def companies_house_api_key(explicit: str | None = None) -> str | None:
    key = (explicit or os.environ.get("COMPANIES_HOUSE_API_KEY") or "").strip()
    return key or None


def _auth_header(api_key: str) -> str:
    token = base64.b64encode(f"{api_key}:".encode()).decode("ascii")
    return f"Basic {token}"


class _StripAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects but drop Authorization (CH content → signed S3 URLs).

    Ubuntu's urllib only strips Content-Length/Type on redirect; keeping Basic
    auth on the S3 hop yields ``Only one auth mechanism allowed``.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is None:
            return None
        # Request.headers keys are title-cased by urllib; remove both casings.
        for key in list(new_req.headers):
            if key.lower() == "authorization":
                del new_req.headers[key]
        unredirected = getattr(new_req, "unredirected_hdrs", None)
        if isinstance(unredirected, dict):
            for key in list(unredirected):
                if key.lower() == "authorization":
                    del unredirected[key]
        return new_req


_CH_OPENER = urllib.request.build_opener(_StripAuthOnRedirect)


def _ch_get(
    url: str,
    *,
    api_key: str,
    accept: str = "application/json",
    timeout: float = 60.0,
    retries: int = 2,
) -> bytes:
    headers = {
        "Authorization": _auth_header(api_key),
        "Accept": accept,
        "User-Agent": USER_AGENT,
    }
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with _CH_OPENER.open(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code == 429 and attempt < retries:
                retry_after = float(exc.headers.get("Retry-After") or 5)
                time.sleep(min(30.0, max(RATE_LIMIT_SLEEP_S, retry_after)))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(RATE_LIMIT_SLEEP_S * (attempt + 1))
                continue
            raise
    raise RuntimeError(f"Companies House GET failed for {url}: {last_exc}")


def load_company_number_map(path: Path | None = None) -> dict[str, str]:
    path = path or DEFAULT_COMPANY_MAP_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    numbers = data.get("numbers") if isinstance(data, dict) else data
    if not isinstance(numbers, dict):
        return {}
    return {str(k).upper(): str(v).strip() for k, v in numbers.items() if str(v).strip()}


def save_company_number_map(mapping: dict[str, str], path: Path | None = None) -> Path:
    path = path or DEFAULT_COMPANY_MAP_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            existing = {}
    numbers = dict(existing.get("numbers") or {})
    numbers.update({k.upper(): v for k, v in mapping.items()})
    payload = {
        "schema_version": 1,
        "updated_at": datetime.now(UTC).isoformat(),
        "note": (
            "Yahoo ticker → Companies House company number. "
            "Resolved via search API and cached; edit manually if wrong entity."
        ),
        "numbers": numbers,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _base_epic(ticker: str) -> str:
    t = (ticker or "").strip().upper()
    if t.endswith(".L"):
        return t[:-2]
    return t


def search_company_number(
    *,
    company_name: str,
    ticker: str,
    api_key: str,
) -> str | None:
    """Resolve a UK company number via Companies House search."""
    query = (company_name or _base_epic(ticker) or "").strip()
    if not query:
        return None
    url = f"{CH_API_BASE}/search/companies?" + urllib.parse.urlencode(
        {"q": query, "items_per_page": 10}
    )
    raw = _ch_get(url, api_key=api_key)
    payload = json.loads(raw.decode("utf-8"))
    items = payload.get("items") or []
    epic = _base_epic(ticker).lower()
    name_l = company_name.lower()
    # Prefer active companies whose title overlaps the issuer name / EPIC.
    ranked: list[tuple[int, str]] = []
    for item in items:
        number = str(item.get("company_number") or "").strip()
        title = str(item.get("title") or "")
        status = str(item.get("company_status") or "").lower()
        if not number:
            continue
        score = 0
        title_l = title.lower()
        if status == "active":
            score += 5
        elif status in {"dissolved", "dormant"}:
            score -= 8
        if epic and epic in title_l:
            score += 4
        # Token overlap
        tokens = [t for t in re.split(r"[^a-z0-9]+", name_l) if len(t) >= 4]
        score += sum(1 for t in tokens[:4] if t in title_l)
        ranked.append((score, number))
    if not ranked:
        return None
    ranked.sort(key=lambda row: row[0], reverse=True)
    return ranked[0][1] if ranked[0][0] > 0 else ranked[0][1]


def resolve_company_number(
    *,
    ticker: str,
    company_name: str,
    api_key: str | None = None,
    map_path: Path | None = None,
    persist: bool = True,
) -> str | None:
    """Lookup cached company number, else search and optionally cache."""
    key = companies_house_api_key(api_key)
    mapping = load_company_number_map(map_path)
    cached = mapping.get(ticker.upper()) or mapping.get(_base_epic(ticker))
    if cached:
        return cached
    if not key:
        return None
    try:
        number = search_company_number(company_name=company_name, ticker=ticker, api_key=key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Companies House search failed for %s: %s", ticker, exc)
        return None
    if number and persist:
        save_company_number_map({ticker.upper(): number}, map_path)
    time.sleep(RATE_LIMIT_SLEEP_S)
    return number


def _filing_id(company_number: str, transaction_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", f"ch_{company_number}_{transaction_id}")
    return safe[:120]


def ch_document_id_from_metadata_url(url: str | None) -> str | None:
    """Extract the document-api id segment from a Companies House metadata URL."""
    if not url or "document-api.company-information.service.gov.uk" not in url:
        return None
    path = urllib.parse.urlparse(str(url)).path.strip("/")
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "document":
        doc_id = parts[1].strip()
        return doc_id or None
    return None


# Reject downloads that stop well short of the declared content_length (truncated HTTP body).
_PARTIAL_DOWNLOAD_MIN_RATIO = 0.9


def fetch_accounts_filing_rows(
    *,
    company_number: str,
    api_key: str,
    max_accounts: int = DEFAULT_MAX_ACCOUNTS,
) -> list[dict[str, Any]]:
    """List recent accounts filings (metadata only) for a company number."""
    url = (
        f"{CH_API_BASE}/company/{urllib.parse.quote(company_number)}/filing-history?"
        + urllib.parse.urlencode(
            {
                "category": "accounts",
                "items_per_page": max(25, max_accounts * 5),
            }
        )
    )
    raw = _ch_get(url, api_key=api_key)
    payload = json.loads(raw.decode("utf-8"))
    rows: list[dict[str, Any]] = []
    for item in payload.get("items") or []:
        links = item.get("links") or {}
        meta = links.get("document_metadata")
        if not meta:
            continue
        tx = str(item.get("transaction_id") or item.get("barcode") or len(rows))
        description = str(item.get("description") or "accounts")
        if "dormant" in description.lower():
            continue
        date = str(item.get("date") or item.get("action_date") or "")
        meta_url = str(meta)
        doc_id = ch_document_id_from_metadata_url(meta_url)
        row_payload: dict[str, Any] = {
            "id": _filing_id(company_number, tx),
            "source": "companies_house",
            "headline": f"Companies House accounts — {description}",
            "published_at": f"{date}T00:00:00+00:00" if date and "T" not in date else date,
            "url": meta_url,
            "period": "annual",
            "category": "accounts",
            "summary": description,
            "has_body": False,
            "body_path": None,
            "priority": 140,
            "provider_id": tx,
            "company_number": company_number,
            "document_metadata_url": meta_url,
        }
        if doc_id:
            row_payload["ch_document_id"] = doc_id
        rows.append(row_payload)
        if len(rows) >= max_accounts:
            break
        time.sleep(RATE_LIMIT_SLEEP_S)
    return rows


MIME_PDF = "application/pdf"
MIME_XHTML = "application/xhtml+xml"
MIME_ZIP = "application/zip"
MIME_XML = "application/xml"
DOCUMENT_MIME_PRIORITY = (MIME_PDF, MIME_XHTML, MIME_ZIP, MIME_XML)


def fetch_document_metadata(
    document_metadata_url: str,
    *,
    api_key: str,
) -> dict[str, Any] | None:
    """Fetch Companies House document metadata JSON."""
    meta_url = document_metadata_url
    if meta_url.startswith("/"):
        meta_url = CH_DOCUMENT_API_BASE + meta_url
    try:
        meta_raw = _ch_get(meta_url, api_key=api_key)
        return json.loads(meta_raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.debug("CH document metadata failed for %s: %s", document_metadata_url, exc)
        return None


def _document_mime_candidates(
    resources: dict[str, Any],
    *,
    prefer: str | None = None,
) -> list[str]:
    if not isinstance(resources, dict):
        return []
    available = [mime for mime in DOCUMENT_MIME_PRIORITY if mime in resources]
    if prefer and prefer in available:
        return [prefer, *[mime for mime in available if mime != prefer]]
    return available


def fetch_document_bytes(
    document_metadata_url: str,
    *,
    api_key: str,
    prefer: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[bytes, str] | None:
    """
      Fetch filed document bytes.

      Returns (raw_bytes, content_type_hint) or None.
    When ``prefer`` is set, that MIME type is tried first if present in metadata.
    """
    meta = metadata or fetch_document_metadata(document_metadata_url, api_key=api_key)
    if not meta:
        return None

    links = meta.get("links") or {}
    doc_link = links.get("document") or links.get("self")
    resources = meta.get("resources") or {}
    candidates = _document_mime_candidates(resources, prefer=prefer)
    if not candidates:
        return None

    if not doc_link:
        return None
    if str(doc_link).startswith("/"):
        doc_url = CH_DOCUMENT_API_BASE + str(doc_link)
    else:
        doc_url = str(doc_link)

    for accept in candidates:
        if accept == MIME_PDF:
            length = int((resources.get(MIME_PDF) or {}).get("content_length") or 0)
            if length > MAX_DOCUMENT_BYTES:
                alternatives = [mime for mime in candidates if mime != MIME_PDF]
                if alternatives:
                    logger.info(
                        "Skipping oversized CH PDF (%s bytes > %s) for %s — trying %s",
                        length,
                        MAX_DOCUMENT_BYTES,
                        document_metadata_url,
                        ", ".join(alternatives),
                    )
                    continue
                logger.info(
                    "Attempting oversized CH PDF (%s bytes) — only format for %s",
                    length,
                    document_metadata_url,
                )
        try:
            raw = _ch_get(
                doc_url,
                api_key=api_key,
                accept=accept,
                timeout=DOCUMENT_DOWNLOAD_TIMEOUT_S,
            )
            expected = int((resources.get(accept) or {}).get("content_length") or 0)
            if (
                512 < expected <= MAX_DOCUMENT_BYTES
                and len(raw) < expected * _PARTIAL_DOWNLOAD_MIN_RATIO
            ):
                logger.info(
                    "CH document download looks truncated for %s (%s): got %s of %s bytes",
                    document_metadata_url,
                    accept,
                    len(raw),
                    expected,
                )
                continue
            time.sleep(RATE_LIMIT_SLEEP_S)
            return raw, accept
        except Exception as exc:  # noqa: BLE001
            logger.debug("CH document download failed for %s (%s): %s", doc_url, accept, exc)
            continue
    return None


def iter_ch_document_downloads(
    document_metadata_url: str,
    *,
    api_key: str,
) -> list[tuple[bytes, str]]:
    """Download each available MIME variant for a CH filing (PDF, then iXBRL)."""
    register_enhanced_ch_body_fetch()
    meta = fetch_document_metadata(document_metadata_url, api_key=api_key)
    if not meta:
        return []
    resources = meta.get("resources") or {}
    downloads: list[tuple[bytes, str]] = []
    seen: set[str] = set()
    for mime in _document_mime_candidates(resources):
        if mime in seen:
            continue
        fetched = fetch_document_bytes(
            document_metadata_url,
            api_key=api_key,
            prefer=mime,
            metadata=meta,
        )
        if not fetched:
            continue
        raw, content_type = fetched
        signature = f"{content_type}:{hash(raw[:4096])}"
        if signature in seen:
            continue
        seen.add(signature)
        seen.add(mime)
        downloads.append((raw, content_type))
    return downloads


def fetch_filings_companies_house(
    *,
    ticker: str,
    company_name: str,
    api_key: str | None = None,
    max_accounts: int = DEFAULT_MAX_ACCOUNTS,
    map_path: Path | None = None,
) -> list[dict[str, Any]]:
    """
    Return filing rows for recent Companies House accounts (with document URLs).

    Body download happens later via ``fetch_filing_body`` / CH-aware writer.
    """
    key = companies_house_api_key(api_key)
    if not key:
        logger.info("COMPANIES_HOUSE_API_KEY not set — skipping CH accounts for %s", ticker)
        return []
    number = resolve_company_number(
        ticker=ticker,
        company_name=company_name,
        api_key=key,
        map_path=map_path,
    )
    if not number:
        logger.info("No Companies House number for %s (%s)", ticker, company_name)
        return []
    try:
        return fetch_accounts_filing_rows(
            company_number=number, api_key=key, max_accounts=max_accounts
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Companies House filings failed for %s: %s", ticker, exc)
        return []


def _ixbrl_deeper_tag_rank(tag_name: str) -> int:
    normalized = re.sub(r"[^a-z0-9]", "", (tag_name or "").lower())
    for index, hint in enumerate(_CH_IXBRL_DEEPEN_TAG_HINTS):
        if hint in normalized:
            return index
    return len(_CH_IXBRL_DEEPEN_TAG_HINTS)


def _extract_ixbrl_deeper_tag_narrative(html: str) -> str:
    """Pull contractor-relevant note blocks from iXBRL ``ix:nonNumeric`` tags."""
    from value_investor.research.filings import _strip_html

    blocks: list[tuple[int, int, str]] = []
    for index, match in enumerate(_CH_IXBRL_NONNUMERIC_RE.finditer(html or "")):
        tag_name = match.group(2)
        inner = _strip_html(match.group(3))
        if len(inner) < 30:
            continue
        blocks.append((_ixbrl_deeper_tag_rank(tag_name), index, inner))
    if not blocks:
        return ""
    blocks.sort(key=lambda item: (item[0], item[1]))
    return "\n\n".join(block for _, _, block in blocks)


def _splice_ch_deepen_note_sections(full_text: str) -> str:
    """Splice consolidated note windows (contract assets, JVs) beyond OCR front-matter."""
    if not full_text.strip():
        return full_text
    sections: list[str] = []
    used_ranges: list[tuple[int, int]] = []
    skip_before = min(8_000, len(full_text) // 4)
    for pattern, _rank in _CH_DEEPEN_SECTION_MARKERS:
        for match in re.finditer(pattern, full_text, flags=re.I):
            if match.start() < skip_before:
                continue
            start = max(0, match.start() - 120)
            end = min(len(full_text), match.end() + _CH_DEEPEN_SECTION_CHARS)
            if any(start < used_end and end > used_start for used_start, used_end in used_ranges):
                continue
            chunk = full_text[start:end].strip()
            if len(chunk) < 60:
                continue
            sections.append(chunk)
            used_ranges.append((start, end))
            if len(sections) >= _CH_DEEPEN_MAX_SECTIONS:
                break
        if len(sections) >= _CH_DEEPEN_MAX_SECTIONS:
            break
    if not sections:
        return full_text
    lead = full_text[: min(12_000, len(full_text))].rstrip()
    return lead + "\n\n---\n\n" + "\n\n---\n\n".join(sections)


def _deepen_ch_document_text(
    raw: bytes,
    content_type: str,
    *,
    baseline: str | None,
) -> str | None:
    """Re-extract CH accounts when the first pass stops at strategic-report OCR front-matter."""
    from value_investor.research.filings import (
        _ch_body_lacks_financial_depth,
        _compose_filing_body_with_depth_sections,
        _extract_filing_document_text,
        _is_ixbrl_html,
        _ocr_pdf_text,
        _score_ch_body_text,
    )

    ct = (content_type or "").lower()
    candidates: list[str] = []

    if raw[:4] == b"%PDF" or "pdf" in ct:
        if baseline and not _ch_body_lacks_financial_depth(baseline):
            return None
        ocr_deep = _ocr_pdf_text(raw, max_pages=CH_DEEPEN_OCR_MAX_PAGES)
        if ocr_deep:
            merged = _splice_ch_deepen_note_sections(ocr_deep)
            merged = _compose_filing_body_with_depth_sections(merged) or merged
            candidates.append(merged)
    elif _is_ixbrl_html(raw) or "xhtml" in ct or "xml" in ct:
        html = raw.decode("utf-8", errors="replace")
        tag_narrative = _extract_ixbrl_deeper_tag_narrative(html)
        if tag_narrative:
            base = baseline or _extract_filing_document_text(raw, content_type) or ""
            merged = f"{tag_narrative}\n\n{base}".strip() if base else tag_narrative
            merged = _compose_filing_body_with_depth_sections(merged) or merged
            candidates.append(merged)
    elif ct == MIME_ZIP or raw[:2] == b"PK":
        zip_text = _extract_filing_document_text(raw, content_type)
        if zip_text and baseline and not _ch_body_lacks_financial_depth(zip_text):
            return None
        if zip_text:
            candidates.append(zip_text)

    if not candidates:
        return None
    best = max(candidates, key=_score_ch_body_text)
    if baseline and _score_ch_body_text(best) <= _score_ch_body_text(baseline):
        return None
    return best


def _ch_consolidated_note_depth(text: str) -> bool:
    """True when extract reaches consolidated note disclosures (MGNS-style contractor accounts)."""
    lower = (text or "").lower()
    if "notes to the consolidated" in lower or "notes to the group financial" in lower:
        return True
    if "contract asset" in lower and any(
        token in lower for token in ("joint venture", "joint ventures", "investments in joint")
    ):
        return True
    if "contract assets" in lower and "trade and other receivables" in lower:
        return True
    return False


def _filter_ch_candidates_prefer_ixbrl_over_shallow_pdf(
    candidates: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """When iXBRL is available, drop strategic-only or garbled PDF OCR (e.g. ITV group accounts)."""
    from value_investor.research.filings import (
        _ch_body_is_garbled_ocr,
        _ch_body_lacks_financial_depth,
        _is_ch_pdf_content_type,
    )

    ixbrl_like = [pair for pair in candidates if not _is_ch_pdf_content_type(pair[1])]
    if not ixbrl_like:
        return candidates
    kept = list(ixbrl_like)
    for text, content_type in candidates:
        if not _is_ch_pdf_content_type(content_type):
            continue
        if _ch_body_lacks_financial_depth(text) or _ch_body_is_garbled_ocr(text):
            continue
        kept.append((text, content_type))
    return kept


def _select_best_ch_deepened_body(candidates: list[tuple[str, str]]) -> str | None:
    """Pick CH body text; recover when PDF depth penalty hides consolidated note OCR."""
    from value_investor.research.filings import (
        _ch_body_lacks_financial_depth,
        _score_ch_body_text,
        _select_best_ch_body_text,
    )

    candidates = _filter_ch_candidates_prefer_ixbrl_over_shallow_pdf(candidates)
    best = _select_best_ch_body_text(candidates)
    if best:
        return best
    note_rich = [
        (text, content_type)
        for text, content_type in candidates
        if _ch_consolidated_note_depth(text) and len(text) >= 200
    ]
    if note_rich:
        return max(note_rich, key=lambda item: _score_ch_body_text(item[0]))[0]
    shallow_ok = [
        (text, content_type)
        for text, content_type in candidates
        if not _ch_body_lacks_financial_depth(text)
    ]
    if shallow_ok:
        return max(shallow_ok, key=lambda item: _score_ch_body_text(item[0]))[0]
    if candidates:
        return max(candidates, key=lambda item: _score_ch_body_text(item[0]))[0]
    return None


def fetch_companies_house_filing_body(row: dict[str, Any]) -> str | None:
    """
    Download and extract filed-accounts text, deepening shallow PDF OCR / iXBRL stubs.

    Used by the filings refetch path (via :func:`register_enhanced_ch_body_fetch`).
    """
    from value_investor.research.filings import (
        FILINGS_BODY_MAX_CHARS,
        _extract_filing_document_text,
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

    candidates: list[tuple[str, str]] = []
    for raw, content_type in downloads:
        text = _extract_filing_document_text(raw, content_type)
        deepen = _deepen_ch_document_text(raw, content_type, baseline=text)
        if deepen:
            text = deepen
        if text and len(text) >= 200:
            candidates.append((text, content_type))
    best_text = _select_best_ch_deepened_body(candidates)
    if not best_text:
        return None
    if len(best_text) > FILINGS_BODY_MAX_CHARS:
        best_text = best_text[:FILINGS_BODY_MAX_CHARS] + "\n\n[truncated]"
    return best_text


def register_enhanced_ch_body_fetch() -> None:
    """Route filings CH refetch through :func:`fetch_companies_house_filing_body`."""
    import value_investor.research.filings as filings_mod

    if getattr(filings_mod._fetch_companies_house_body, "_ch_deepened", False):
        return

    def _enhanced(row: dict[str, Any]) -> str | None:
        return fetch_companies_house_filing_body(row)

    _enhanced._ch_deepened = True  # type: ignore[attr-defined]
    filings_mod._fetch_companies_house_body = _enhanced
