"""Companies House statement-of-capital filings (CS01 / AR01 / SH01) for share counts."""

from __future__ import annotations

import io
import json
import logging
import re
import time
import urllib.parse
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from value_investor.ch_failed_name_statements import _trim_number, ensure_pdf
from value_investor.ch_leaver_statements import _ixbrl_facts, html_from_document
from value_investor.research.companies_house import (
    CH_API_BASE,
    MIME_PDF,
    MIME_XHTML,
    MIME_XML,
    MIME_ZIP,
    RATE_LIMIT_SLEEP_S,
    _ch_get,
    fetch_document_bytes,
    fetch_document_metadata,
)

logger = logging.getLogger(__name__)

_CAPITAL_TYPES = frozenset({"CS01", "AR01", "SH01", "NEWINC"})
_ORDINARY_SHARE_TOTAL_RE = re.compile(
    r"(?:total\s+number\s+of\s+)?(?:ordinary\s+shares?|equity\s+shares?)"
    r"[^0-9]{0,40}(\d[\d,\s]{4,})",
    re.I,
)
_SHARE_CLASS_ORDINARY_RE = re.compile(r"\bordinary\b", re.I)


def list_capital_filings(company_number: str, api_key: str) -> list[dict[str, Any]]:
    """Filing-history rows for capital / confirmation-statement forms."""
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        url = (
            f"{CH_API_BASE}/company/{urllib.parse.quote(company_number)}/filing-history?"
            + urllib.parse.urlencode({"items_per_page": 100, "start_index": start})
        )
        payload = json.loads(_ch_get(url, api_key=api_key).decode("utf-8"))
        time.sleep(RATE_LIMIT_SLEEP_S)
        items = payload.get("items") or []
        total = int(payload.get("total_count") or 0)
        for item in items:
            form = str(item.get("type") or "")
            if form not in _CAPITAL_TYPES:
                continue
            meta = (item.get("links") or {}).get("document_metadata")
            if not meta:
                continue
            rows.append(
                {
                    "transaction_id": str(item.get("transaction_id") or ""),
                    "filing_date": str(item.get("date") or ""),
                    "type": form,
                    "description": str(item.get("description") or ""),
                    "document_metadata_url": str(meta),
                }
            )
        start += len(items)
        if not items or start >= total:
            break
    rows.sort(key=lambda row: row["filing_date"])
    return rows


def _parse_plain_capital_text(text: str) -> str | None:
    best: tuple[int, str] | None = None
    for match in _ORDINARY_SHARE_TOTAL_RE.finditer(text):
        raw = re.sub(r"[\s,]", "", match.group(1))
        if not raw.isdigit():
            continue
        try:
            magnitude = int(raw)
        except ValueError:
            continue
        if magnitude < 100_000:
            continue
        if best is None or magnitude > best[0]:
            best = (magnitude, _trim_number(raw))
    return best[1] if best else None


def _pdf_text(raw: bytes) -> str:
    try:
        import fitz  # pymupdf
    except ImportError:
        fitz = None
    if fitz is not None:
        try:
            doc = fitz.open(stream=raw, filetype="pdf")
            parts = [page.get_text("text") for page in doc]
            doc.close()
            return "\n".join(parts)
        except Exception:  # noqa: BLE001
            pass
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:  # noqa: BLE001
        return ""


def _ocr_pdf_text(raw: bytes, *, max_pages: int = 4) -> str:
    try:
        import fitz  # pymupdf
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""
    try:
        doc = fitz.open(stream=raw, filetype="pdf")
        parts: list[str] = []
        for index, page in enumerate(doc):
            if index >= max_pages:
                break
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            parts.append(pytesseract.image_to_string(image, config="--psm 6"))
        doc.close()
        return "\n".join(parts)
    except Exception:  # noqa: BLE001
        return ""


def fetch_capital_document_body(
    document_metadata_url: str,
    *,
    api_key: str,
    cache_dir: Path,
    cache_key: str,
    transaction_id: str,
    allow_ocr: bool,
) -> tuple[str | None, str]:
    """Return (text or html, method) from xhtml, PDF text layer, or OCR."""
    meta = fetch_document_metadata(document_metadata_url, api_key=api_key)
    if meta:
        for mime in (MIME_XHTML, MIME_XML, MIME_ZIP):
            if mime not in (meta.get("resources") or {}):
                continue
            fetched = fetch_document_bytes(
                document_metadata_url, api_key=api_key, prefer=mime, metadata=meta
            )
            if not fetched:
                continue
            html = html_from_document(fetched[0], fetched[1])
            if html:
                return html, "xhtml"
    raw: bytes | None = None
    pdf_path = ensure_pdf(
        cache_dir,
        key=cache_key,
        made_up=transaction_id,
        document_metadata_url=document_metadata_url,
        api_key=api_key,
    )
    if pdf_path is not None:
        raw = pdf_path.read_bytes()
    else:
        fetched = fetch_document_bytes(
            document_metadata_url, api_key=api_key, prefer=MIME_PDF, metadata=meta
        )
        if fetched and (fetched[1].endswith("pdf") or fetched[0][:4] == b"%PDF"):
            raw = fetched[0]
            path = cache_dir / f"{cache_key}_{transaction_id}.pdf"
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_bytes(raw)
    if not raw:
        return None, "missing"
    text = _pdf_text(raw)
    if text.strip():
        return text, "pdf_text"
    if allow_ocr:
        ocr = _ocr_pdf_text(raw)
        if ocr.strip():
            return ocr, "ocr"
    return None, "unreadable"


def parse_capital_statement_html(
    html: str | None,
    *,
    transaction_id: str,
    filing_date: str,
    method: str = "ch_capital_form",
) -> dict[str, Any] | None:
    """Read total ordinary shares from a CS01 / AR01 / SH01 body."""
    if not html or not str(html).strip():
        return None
    facts = _ixbrl_facts(html)
    ordinary_totals: list[tuple[int, str]] = []
    for fact in facts:
        tag = str(fact.get("tag") or "")
        if "share" not in tag or "number" not in tag:
            continue
        if not _SHARE_CLASS_ORDINARY_RE.search(tag) and "fullypaid" not in tag:
            continue
        try:
            magnitude = abs(int(Decimal(str(fact["value"]).replace(",", ""))))
        except (InvalidOperation, ValueError):
            continue
        if magnitude < 100_000:
            continue
        ordinary_totals.append((magnitude, str(fact["value"]).replace(",", "")))
    value: str | None = None
    if ordinary_totals:
        value = max(ordinary_totals, key=lambda item: item[0])[1]
    if value is None:
        value = _parse_plain_capital_text(re.sub(r"<[^>]+>", " ", str(html)))
    if value is None:
        return None
    return {
        "value": _trim_number(value),
        "scale": "units",
        "currency": None,
        "unit": None,
        "source": "ch_statement_of_capital",
        "absent_reason": None,
        "basis": "in_issue",
        "cross_check": {"status": "unavailable"},
        "citation": {
            "transaction_id": transaction_id,
            "filing_date": filing_date,
            "page": None,
            "line": f"statement of capital ordinary shares total {value}",
            "method": method,
        },
    }


def _pick_capital_in_window(
    filings: list[dict[str, Any]],
    *,
    period: datetime,
    within_days: int,
) -> dict[str, Any] | None:
    in_window: list[tuple[tuple[int, int], dict[str, Any]]] = []
    for row in filings:
        try:
            filed = datetime.strptime(str(row["filing_date"])[:10], "%Y-%m-%d").replace(tzinfo=UTC)
        except (KeyError, ValueError):
            continue
        if filed < period:
            continue
        delta = (filed - period).days
        if delta > within_days:
            continue
        form = str(row.get("type") or "")
        priority = 0 if form in {"CS01", "AR01"} else 1 if form == "SH01" else 2
        in_window.append(((priority, delta), row))
    if not in_window:
        return None
    in_window.sort(key=lambda item: item[0])
    return in_window[0][1]


def pick_capital_filing_after_period(
    filings: list[dict[str, Any]],
    period_end: str,
    *,
    within_days: int = 90,
    extended_within_days: int = 220,
    accounts_filing_date: str | None = None,
) -> dict[str, Any] | None:
    """Nearest CS01 / AR01 after period end, else SH01, within ``within_days``.

    When nothing matches (common for non-December year-ends), fall back to
    ``extended_within_days`` but not later than 45 days after the annual
    accounts filing date when that date is known.
    """
    try:
        period = datetime.strptime(period_end[:10], "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None
    picked = _pick_capital_in_window(filings, period=period, within_days=within_days)
    if picked is not None:
        return picked
    cap = extended_within_days
    if accounts_filing_date:
        try:
            filed = datetime.strptime(accounts_filing_date[:10], "%Y-%m-%d").replace(tzinfo=UTC)
            cap = min(cap, max(within_days, (filed - period).days + 75))
        except ValueError:
            pass
    return _pick_capital_in_window(filings, period=period, within_days=cap)
