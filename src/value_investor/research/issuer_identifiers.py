"""Durable Yahoo-ticker → official issuer identifiers.

Companies House already caches ticker → company number. Euro last-mile needs the
same shape for LEI: find the entity once, then query official registers by id.

The identifier is long-lived (edit the cache if GLEIF picked the wrong legal
entity). Filing recency stays time-bounded in the register fetch (lookback +
official-annual floor), so one old hit does not freeze coverage.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.storage import write_json

logger = logging.getLogger(__name__)

DEFAULT_ISSUER_IDENTIFIERS_PATH = Path("docs/data/library/issuer_identifiers.json")
GLEIF_LEI_RECORDS_URL = "https://api.gleif.org/api/v1/lei-records"
GLEIF_PAGE_SIZE = 8
HttpGet = Callable[..., bytes]

# Verified last-mile identity (Yahoo ticker / base symbol). Same role as builtin IR URLs.
# Bare ABI is omitted — it collides with the US ticker alias used for SEC 20-F.
_BUILTIN_ISSUERS: dict[str, dict[str, str]] = {
    "AED.BR": {
        "lei": "529900DTKNXL0AXQFN28",
        "lei_name": "AEDIFICA",
        "lei_country": "BE",
        "isin": "BE0003851681",
        "cbe": "0877248501",
        "mic": "XBRU",
    },
    "AED": {
        "lei": "529900DTKNXL0AXQFN28",
        "lei_name": "AEDIFICA",
        "lei_country": "BE",
        "isin": "BE0003851681",
        "cbe": "0877248501",
        "mic": "XBRU",
    },
    "ABI.BR": {
        "lei": "5493008H3828EMEXB082",
        "lei_name": "ANHEUSER-BUSCH INBEV",
        "lei_country": "BE",
        "isin": "BE0974293251",
        "cbe": "0417497106",
        "mic": "XBRU",
    },
}
_BUILTIN_LEIS: dict[str, str] = {
    key: str(row.get("lei") or "") for key, row in _BUILTIN_ISSUERS.items() if row.get("lei")
}

_LEI_RE = re.compile(r"^[A-Z0-9]{20}$")
_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_MIC_RE = re.compile(r"^[A-Z]{4}$")
_ISSUER_STOPWORDS = frozenset(
    {
        "sa",
        "nv",
        "ag",
        "se",
        "plc",
        "ltd",
        "limited",
        "group",
        "holdings",
        "the",
        "and",
        "publ",
        "srl",
        "gmbh",
    }
)


def _ticker_keys(ticker: str) -> list[str]:
    upper = (ticker or "").strip().upper()
    if not upper:
        return []
    keys = [upper]
    if "." in upper:
        base = upper.rsplit(".", 1)[0]
        if base and base not in keys:
            keys.append(base)
    return keys


def _normalize_lei(value: str | None) -> str | None:
    lei = re.sub(r"[^A-Z0-9]", "", (value or "").strip().upper())
    if _LEI_RE.match(lei):
        return lei
    return None


def _normalize_isin(value: str | None) -> str | None:
    isin = re.sub(r"[^A-Z0-9]", "", (value or "").strip().upper())
    if _ISIN_RE.match(isin):
        return isin
    return None


def _normalize_cbe(value: str | None) -> str | None:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 9:
        digits = digits.zfill(10)
    if len(digits) == 10:
        return digits
    return None


def _normalize_mic(value: str | None) -> str | None:
    mic = re.sub(r"[^A-Z]", "", (value or "").strip().upper())
    if _MIC_RE.match(mic):
        return mic
    return None


def load_issuer_identifiers(path: Path | None = None) -> dict[str, Any]:
    path = Path(path or DEFAULT_ISSUER_IDENTIFIERS_PATH)
    empty = {
        "schema_version": 1,
        "updated_at": None,
        "note": (
            "Yahoo ticker → official identifiers (LEI via GLEIF; ISIN / CBE / MIC "
            "for national registers). Identity is durable; edit manually if the "
            "wrong entity was cached. Filing recency is enforced by the register "
            "fetch, not by expiring identifiers."
        ),
        "issuers": {},
    }
    if not path.exists():
        return empty
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return empty
    if not isinstance(payload, dict):
        return empty
    issuers = payload.get("issuers")
    if not isinstance(issuers, dict):
        issuers = {}
    cleaned: dict[str, dict[str, Any]] = {}
    for key, row in issuers.items():
        if not isinstance(row, dict):
            continue
        cleaned[str(key).upper()] = dict(row)
    return {
        "schema_version": int(payload.get("schema_version") or 1),
        "updated_at": payload.get("updated_at"),
        "note": payload.get("note") or empty["note"],
        "issuers": cleaned,
    }


def _merge_issuer_rows(*rows: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        for field, raw in row.items():
            if raw in (None, ""):
                continue
            if field == "lei":
                value = _normalize_lei(str(raw))
            elif field == "isin":
                value = _normalize_isin(str(raw))
            elif field == "cbe":
                value = _normalize_cbe(str(raw))
            elif field == "mic":
                value = _normalize_mic(str(raw))
            elif field == "lei_country":
                value = str(raw).strip().upper()
            else:
                value = str(raw).strip() if isinstance(raw, str) else raw
            if value not in (None, ""):
                merged[field] = value
    return merged


def cached_issuer_identity(ticker: str, *, path: Path | None = None) -> dict[str, Any]:
    """Return builtin + cached official identifiers for a Yahoo ticker."""
    issuers = load_issuer_identifiers(path).get("issuers") or {}
    merged: dict[str, Any] = {}
    for key in reversed(_ticker_keys(ticker)):
        builtin = _BUILTIN_ISSUERS.get(key)
        cached = issuers.get(key) if isinstance(issuers.get(key), dict) else None
        merged = _merge_issuer_rows(merged, builtin, cached)
    return merged


def cached_lei(ticker: str, *, path: Path | None = None) -> str | None:
    """Return a builtin or cached LEI without calling GLEIF."""
    return _normalize_lei(str(cached_issuer_identity(ticker, path=path).get("lei") or ""))


def cached_isin(ticker: str, *, path: Path | None = None) -> str | None:
    """Return a builtin or cached equity ISIN."""
    return _normalize_isin(str(cached_issuer_identity(ticker, path=path).get("isin") or ""))


def cached_cbe(ticker: str, *, path: Path | None = None) -> str | None:
    """Return a builtin or cached Belgian CBE / enterprise number (10 digits)."""
    return _normalize_cbe(str(cached_issuer_identity(ticker, path=path).get("cbe") or ""))


def save_issuer_lei(
    ticker: str,
    lei: str,
    *,
    path: Path | None = None,
    lei_name: str = "",
    lei_country: str = "",
    source: str = "gleif",
) -> Path:
    path = Path(path or DEFAULT_ISSUER_IDENTIFIERS_PATH)
    payload = load_issuer_identifiers(path)
    issuers = dict(payload.get("issuers") or {})
    key = (ticker or "").strip().upper()
    if not key:
        raise ValueError("ticker is required")
    normalized = _normalize_lei(lei)
    if not normalized:
        raise ValueError(f"invalid LEI for {ticker}: {lei!r}")
    previous = issuers.get(key) if isinstance(issuers.get(key), dict) else {}
    issuers[key] = {
        **previous,
        "lei": normalized,
        "lei_name": (lei_name or previous.get("lei_name") or "").strip(),
        "lei_country": (lei_country or previous.get("lei_country") or "").strip().upper(),
        "source": source or "gleif",
        "resolved_at": datetime.now(UTC).isoformat(),
    }
    payload["issuers"] = issuers
    payload["updated_at"] = datetime.now(UTC).isoformat()
    payload["schema_version"] = 1
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, payload)
    return path


def save_issuer_identity(
    ticker: str,
    *,
    path: Path | None = None,
    lei: str = "",
    lei_name: str = "",
    lei_country: str = "",
    isin: str = "",
    cbe: str = "",
    mic: str = "",
    source: str = "manual",
) -> Path:
    """Persist durable official identifiers without dropping previously cached fields."""
    path = Path(path or DEFAULT_ISSUER_IDENTIFIERS_PATH)
    payload = load_issuer_identifiers(path)
    issuers = dict(payload.get("issuers") or {})
    key = (ticker or "").strip().upper()
    if not key:
        raise ValueError("ticker is required")
    previous = issuers.get(key) if isinstance(issuers.get(key), dict) else {}
    row = _merge_issuer_rows(
        previous,
        {
            "lei": lei,
            "lei_name": lei_name,
            "lei_country": lei_country,
            "isin": isin,
            "cbe": cbe,
            "mic": mic,
        },
    )
    if lei:
        normalized = _normalize_lei(lei)
        if not normalized:
            raise ValueError(f"invalid LEI for {ticker}: {lei!r}")
        row["lei"] = normalized
    if isin:
        normalized_isin = _normalize_isin(isin)
        if not normalized_isin:
            raise ValueError(f"invalid ISIN for {ticker}: {isin!r}")
        row["isin"] = normalized_isin
    if cbe:
        normalized_cbe = _normalize_cbe(cbe)
        if not normalized_cbe:
            raise ValueError(f"invalid CBE for {ticker}: {cbe!r}")
        row["cbe"] = normalized_cbe
    row["source"] = source or previous.get("source") or "manual"
    row["resolved_at"] = datetime.now(UTC).isoformat()
    issuers[key] = row
    payload["issuers"] = issuers
    payload["updated_at"] = datetime.now(UTC).isoformat()
    payload["schema_version"] = 1
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, payload)
    return path


def _name_tokens(value: str) -> set[str]:
    return {
        tok
        for tok in re.split(r"[^a-z0-9]+", (value or "").lower())
        if len(tok) >= 3 and tok not in _ISSUER_STOPWORDS
    }


def _gleif_record_name(record: dict[str, Any]) -> str:
    attrs = record.get("attributes") if isinstance(record, dict) else {}
    entity = attrs.get("entity") if isinstance(attrs, dict) else {}
    legal = entity.get("legalName") if isinstance(entity, dict) else {}
    if isinstance(legal, dict):
        return str(legal.get("name") or "").strip()
    return str(legal or "").strip()


def _gleif_record_country(record: dict[str, Any]) -> str:
    attrs = record.get("attributes") if isinstance(record, dict) else {}
    entity = attrs.get("entity") if isinstance(attrs, dict) else {}
    if not isinstance(entity, dict):
        return ""
    for field in ("legalAddress", "headquartersAddress"):
        addr = entity.get(field)
        if isinstance(addr, dict):
            country = str(addr.get("country") or "").strip().upper()
            if country:
                return country
    return ""


def _score_gleif_record(
    record: dict[str, Any],
    *,
    query_name: str,
    country_hint: str | None,
) -> int:
    lei = _normalize_lei(str(record.get("id") or ""))
    if not lei:
        return -1
    name = _gleif_record_name(record)
    country = _gleif_record_country(record)
    hint = (country_hint or "").strip().upper()
    if hint and country and country != hint:
        return -1
    score = 0
    if hint and country == hint:
        score += 10
    q = (query_name or "").strip().lower()
    n = name.lower()
    if q and n == q:
        score += 12
    elif q and (n.startswith(q) or q.startswith(n)):
        score += 8
    query_tokens = _name_tokens(query_name)
    name_tokens = _name_tokens(name)
    if query_tokens and name_tokens:
        overlap = query_tokens & name_tokens
        if overlap:
            score += min(6, 2 * len(overlap))
        elif query_tokens:
            return -1
    return score


def search_lei_gleif(
    *,
    company_name: str,
    ticker: str = "",
    country_hint: str | None = None,
    name_variants: list[str] | None = None,
    http_get: HttpGet | None = None,
) -> dict[str, str] | None:
    """Return ``{lei, lei_name, lei_country}`` from GLEIF, or None."""
    getter = http_get
    if getter is None:
        from value_investor.research.filings import _http_get

        getter = _http_get

    variants: list[str] = []
    seen: set[str] = set()
    for raw in [company_name, *(name_variants or ())]:
        cleaned = " ".join(str(raw or "").split()).strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            variants.append(cleaned)
    if not variants:
        return None

    hint = (country_hint or "").strip().upper() or None
    best: tuple[int, dict[str, str]] | None = None
    for name in variants[:6]:
        params: dict[str, str] = {
            "filter[entity.legalName]": name,
            "page[size]": str(GLEIF_PAGE_SIZE),
        }
        if hint:
            params["filter[entity.legalAddress.country]"] = hint
        url = f"{GLEIF_LEI_RECORDS_URL}?{urllib.parse.urlencode(params)}"
        try:
            payload = json.loads(
                getter(
                    url,
                    headers={"Accept": "application/vnd.api+json"},
                    timeout=30,
                ).decode("utf-8")
            )
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            json.JSONDecodeError,
            UnicodeDecodeError,
        ) as exc:
            logger.debug("GLEIF LEI search failed for %r (%s): %s", name, ticker, exc)
            continue
        for record in payload.get("data") or []:
            if not isinstance(record, dict):
                continue
            score = _score_gleif_record(record, query_name=name, country_hint=hint)
            if score < 5:
                continue
            lei = _normalize_lei(str(record.get("id") or ""))
            if not lei:
                continue
            candidate = {
                "lei": lei,
                "lei_name": _gleif_record_name(record),
                "lei_country": _gleif_record_country(record),
            }
            if best is None or score > best[0]:
                best = (score, candidate)
        if best and best[0] >= 15:
            break
    if not best:
        return None
    return best[1]


def resolve_lei(
    ticker: str,
    *,
    company_name: str = "",
    country_hint: str | None = None,
    path: Path | None = None,
    search: bool = True,
    persist: bool = True,
    name_variants: list[str] | None = None,
    http_get: HttpGet | None = None,
) -> str | None:
    """Return a LEI from builtins/cache, optionally searching GLEIF once."""
    cached = cached_lei(ticker, path=path)
    if cached:
        return cached
    if not search:
        return None
    found = search_lei_gleif(
        company_name=company_name,
        ticker=ticker,
        country_hint=country_hint,
        name_variants=name_variants,
        http_get=http_get,
    )
    if not found:
        return None
    lei = found["lei"]
    if persist:
        try:
            save_issuer_lei(
                ticker,
                lei,
                path=path,
                lei_name=found.get("lei_name") or "",
                lei_country=found.get("lei_country") or "",
                source="gleif",
            )
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Persist LEI for %s failed: %s", ticker, exc)
    return lei


__all__ = [
    "DEFAULT_ISSUER_IDENTIFIERS_PATH",
    "cached_cbe",
    "cached_isin",
    "cached_issuer_identity",
    "cached_lei",
    "load_issuer_identifiers",
    "resolve_lei",
    "save_issuer_identity",
    "save_issuer_lei",
    "search_lei_gleif",
]
