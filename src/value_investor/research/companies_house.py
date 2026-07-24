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


def companies_house_api_key(explicit: str | None = None) -> str | None:
    key = (explicit or os.environ.get("COMPANIES_HOUSE_API_KEY") or "").strip()
    return key or None


def _auth_header(api_key: str) -> str:
    token = base64.b64encode(f"{api_key}:".encode("utf-8")).decode("ascii")
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
    return {
        str(k).upper(): str(v).strip()
        for k, v in numbers.items()
        if str(v).strip()
    }


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
    url = (
        f"{CH_API_BASE}/search/companies?"
        + urllib.parse.urlencode({"q": query, "items_per_page": 10})
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
        number = search_company_number(
            company_name=company_name, ticker=ticker, api_key=key
        )
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
        date = str(item.get("date") or item.get("action_date") or "")
        rows.append(
            {
                "id": _filing_id(company_number, tx),
                "source": "companies_house",
                "headline": f"Companies House accounts — {description}",
                "published_at": f"{date}T00:00:00+00:00" if date and "T" not in date else date,
                "url": str(meta),
                "period": "annual",
                "category": "accounts",
                "summary": description,
                "has_body": False,
                "body_path": None,
                "priority": 140,
                "provider_id": tx,
                "company_number": company_number,
                "document_metadata_url": str(meta),
            }
        )
        if len(rows) >= max_accounts:
            break
        time.sleep(RATE_LIMIT_SLEEP_S)
    return rows


MIME_PDF = "application/pdf"
MIME_XHTML = "application/xhtml+xml"
MIME_XML = "application/xml"
DOCUMENT_MIME_PRIORITY = (MIME_PDF, MIME_XHTML, MIME_XML)


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
                logger.info(
                    "Skipping oversized CH PDF (%s bytes > %s) for %s",
                    length,
                    MAX_DOCUMENT_BYTES,
                    document_metadata_url,
                )
                continue
        try:
            raw = _ch_get(
                doc_url,
                api_key=api_key,
                accept=accept,
                timeout=DOCUMENT_DOWNLOAD_TIMEOUT_S,
            )
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
