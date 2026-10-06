"""AMF regulated-information feed for French issuers (``euro_filings`` regime).

France's officially appointed mechanism (OAM) publishes every regulated filing
on the DILA open-data portal ``info-financiere.gouv.fr`` (Opendatasoft v2.1,
dataset ``flux-amf-new-prod``): no key, JSON records with a direct PDF URL.

One query per issuer, keyed by the AMF ticker for ``.PA`` names (exact; cached
LEIs for some ``.PA`` names point at a subsidiary) or by LEI for French issuers
listed elsewhere. Kept:

* periodic reports — annual (``002002``/``003000``) and half-year
  (``002003``/``004000``; some issuers file annual consolidated statements
  here, so the headline decides) and quarterly information (``005xxx``);
* results press releases — inside-information subtype ``001007`` always, other
  inside-information subtypes only when the headline is a results release.

Most items are filed in French and English; English wins per (day, subtype).
Own-share, voting-rights, liquidity-contract, prospectus and governance
filings are not queried.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

HttpGet = Callable[..., bytes]

SOURCE = "amf_direct"
USER_AGENT = "value-investor-research/0.1 (+filings)"
AMF_RECORDS_URL = (
    "https://www.info-financiere.gouv.fr/api/explore/v2.1/catalog/datasets/"
    "flux-amf-new-prod/records"
)
AMF_LOOKBACK_DAYS = 800
AMF_ROW_LIMIT = 100
REFILING_WINDOW_DAYS = 10

ANNUAL_REPORT_CODES = frozenset({"002002", "003000"})
HALF_YEAR_REPORT_CODES = frozenset({"002003", "004000"})
QUARTERLY_CODES = frozenset({"005000", "005001", "005002"})
RESULTS_RELEASE_CODE = "001007"
INSIDE_INFORMATION_CODES = frozenset({"001001", "001002", "001006", "001008", "015000"})
QUERIED_CODES: tuple[str, ...] = tuple(
    sorted(
        ANNUAL_REPORT_CODES
        | HALF_YEAR_REPORT_CODES
        | QUARTERLY_CODES
        | INSIDE_INFORMATION_CODES
        | {RESULTS_RELEASE_CODE}
    )
)

# Newest rows kept per kind. Sum (10) stays under the 12-body ingest cap so
# the feed never leaves its own rows indexed-without-body.
AMF_KIND_QUOTAS: dict[str, int] = {
    "final_results": 2,
    "annual_report": 2,
    "interim_results": 2,
    "half_year_report": 2,
    "quarterly_update": 2,
}
AMF_MAX_ITEMS = sum(AMF_KIND_QUOTAS.values())

_KIND_PERIOD_PRIORITY: dict[str, tuple[str, int]] = {
    "final_results": ("annual", 120),
    "annual_report": ("annual", 110),
    "interim_results": ("interim", 100),
    "half_year_report": ("interim", 90),
    "quarterly_update": ("trading_update", 80),
}

# Availability / publication notices are one-page pointers to a document filed
# elsewhere (often the ESEF package esef_direct already indexes).
_NOTICE_RE = re.compile(
    r"availability|mise en ligne|mise [àa] disposition|modalit[ée]s de mise|"
    r"\bpublication (?:of|du|de|des)\b|filing of|d[ée]p[ôo]t (?:d.un|du|de)\b|"
    r"aide[- ]m[ée]moire|registration document|enregistrement universel|form 20-f",
    re.I,
)
_NOT_RESULTS_RE = re.compile(
    r"webcast|invitation|conference call|dividend|prospectus|assembl[ée]e|"
    r"general meeting|shareholders.? meeting|\bvotes?\b|tender offer|offre publique|"
    r"hybrid|\bbonds?\b|obligat|operations of the issuer|"
    r"phase\s*(?:[123]|i{1,3})\b|\btrial\b|\bstud(?:y|ies)\b|[ée]tude|essai|\bdata\b|"
    r"positive results|new results",
    re.I,
)
# Server-side title filter for the high-volume inside-information subtypes.
RESULTS_SEARCH_TERMS: tuple[str, ...] = (
    "results",
    "résultats",
    "resultats",
    "revenue",
    "revenues",
    "sales",
    "earnings",
    "chiffre",
    "financial report",
    "rapport financier",
    "semestriel",
    "half-year",
    "full-year",
    "Q1",
    "Q2",
    "Q3",
    "Q4",
    "T1",
    "T3",
    "H1",
    "EPS",
)
_STRONG_RESULTS_RE = re.compile(
    r"\bresults?\b|r[ée]sultats?|\brevenues?\b|chiffre d.affaires|\bsales\b|\bearnings\b|"
    r"\bEPS\b|financial report|rapport financier|\b[QT][1-4]\b|\bH[12]\b|"
    r"half[- ]year|full[- ]year|semestriel",
    re.I,
)
# Explicit full-year results wording beats a quarter/half mention elsewhere.
_FULL_YEAR_RESULTS_RE = re.compile(
    r"full[- ]year(?:\s+20\d{2})?\s+(?:results|earnings)|\bFY[- ]?20\d{2}\b|"
    r"annual results|r[ée]sultats annuels|r[ée]sultats de l.ann[ée]e|"
    r"fourth[- ]quarter|4[eè](?:me)?\s+trimestre|\b[QT]4\b",
    re.I,
)
# Checked before the annual cue: "Q1 results, outlook for the full-year" is a Q1.
_QUARTER_CUE_RE = re.compile(
    r"\b[QT][13]\b|first[- ]quarter|third[- ]quarter|nine[- ]months?|9 mois|"
    r"(?:1er|premier|3[eè](?:me)?|troisi[eè]me)\s+trimestre|quarterly",
    re.I,
)
_HALF_CUE_RE = re.compile(
    r"half|semestr|\bH1\b|first[- ]six|six months|\binterim\b|second[- ]quarter|"
    r"2[eè](?:me)?\s+trimestre|\b[QT]2\b",
    re.I,
)
_ANNUAL_CUE_RE = re.compile(
    r"full[- ]year|\bannual\b|\bannuel|ann[ée]e\s+20\d{2}|\bexercice\b|\bFY\b|"
    r"comptes consolid[ée]s|consolidated financial st\w*",
    re.I,
)
_DOC_EXTENSIONS = (".pdf", ".htm", ".html", ".xhtml")


def amf_ticker(ticker: str) -> str | None:
    """``CAP.PA`` → ``CAP`` (AMF ticker); ``None`` for non-Paris tickers."""
    text = str(ticker or "").strip().upper()
    if not text.endswith(".PA"):
        return None
    base = text[: -len(".PA")]
    return base or None


def amf_issuer_filter(ticker: str, identity: dict[str, Any] | None = None) -> str | None:
    """ODSQL issuer clause: AMF ticker for ``.PA``, else LEI when the LEI is French."""
    tkr = amf_ticker(ticker)
    if tkr:
        return f'identificationsociete_iso_code_tkr_iso_cd_tkr="{tkr}"'
    ident = identity or {}
    lei = str(ident.get("lei") or "").strip().upper()
    if lei and str(ident.get("lei_country") or "").strip().upper() == "FR":
        if re.fullmatch(r"[A-Z0-9]{20}", lei):
            return f'identificationsociete_iso_cd_lei="{lei}"'
    return None


def is_amf_issuer(ticker: str, identity: dict[str, Any] | None = None) -> bool:
    return amf_issuer_filter(ticker, identity) is not None


def _cached_identity(ticker: str) -> dict[str, Any] | None:
    from value_investor.research.issuer_identifiers import cached_issuer_identity

    try:
        return cached_issuer_identity(ticker)
    except (OSError, ValueError):
        return None


def amf_eligible(ticker: str) -> bool:
    """True for ``.PA`` tickers and cached French LEIs (no network)."""
    if amf_ticker(ticker):
        return True
    return is_amf_issuer(ticker, _cached_identity(ticker))


def _http_get(url: str, *, timeout: int = 30) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _filing_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def _codes_clause(codes: frozenset[str] | set[str]) -> str:
    quoted = ",".join(f'"{code}"' for code in sorted(codes))
    return f"informationdeposee_inf_stp_inf in ({quoted})"


def amf_query_clauses() -> tuple[str, ...]:
    """Two record queries: low-volume periodic/results subtypes, then searched inside info."""
    periodic = _codes_clause(
        ANNUAL_REPORT_CODES | HALF_YEAR_REPORT_CODES | QUARTERLY_CODES | {RESULTS_RELEASE_CODE}
    )
    search = " or ".join(
        f'search(informationdeposee_inf_tit_inf,"{term}")' for term in RESULTS_SEARCH_TERMS
    )
    inside = f"{_codes_clause(INSIDE_INFORMATION_CODES)} and ({search})"
    return periodic, inside


def amf_records_url(issuer_filter: str, *, since: datetime, clause: str) -> str:
    where = (
        f"{issuer_filter} and informationdeposee_inf_dat_emt>="
        f'"{since.strftime("%Y-%m-%d")}" and {clause}'
    )
    params = {
        "where": where,
        "order_by": "informationdeposee_inf_dat_emt desc",
        "limit": str(AMF_ROW_LIMIT),
    }
    return f"{AMF_RECORDS_URL}?{urllib.parse.urlencode(params)}"


def parse_records_payload(payload: bytes | str) -> list[dict[str, Any]]:
    text = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else payload
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return []
    rows = data.get("results") if isinstance(data, dict) else None
    return [row for row in rows or [] if isinstance(row, dict)]


def _results_kind(title: str, published: datetime | None) -> str | None:
    """Period from headline cues, else from the release month (FY Jan–Mar, H1 Jul–Sep)."""
    if _FULL_YEAR_RESULTS_RE.search(title):
        return "final_results"
    if _QUARTER_CUE_RE.search(title):
        return "quarterly_update"
    if _HALF_CUE_RE.search(title):
        return "interim_results"
    if _ANNUAL_CUE_RE.search(title):
        return "final_results"
    if published is None:
        return None
    if published.month <= 3:
        return "final_results"
    if 7 <= published.month <= 9:
        return "interim_results"
    return "quarterly_update"


def classify_amf_record(
    code: str, title: str, published: datetime | None = None
) -> tuple[str, str, int] | None:
    """Map an AMF subtype code + headline to ``(kind, period, priority)``; ``None`` drops it."""
    code = str(code or "").strip()
    title = " ".join(str(title or "").split())
    if not title or _NOTICE_RE.search(title):
        return None
    kind: str | None = None
    if code in ANNUAL_REPORT_CODES:
        kind = "annual_report"
    elif code in HALF_YEAR_REPORT_CODES:
        annual = _ANNUAL_CUE_RE.search(title) and not _HALF_CUE_RE.search(title)
        kind = "annual_report" if annual else "half_year_report"
    elif code in QUARTERLY_CODES:
        kind = "quarterly_update"
    elif _NOT_RESULTS_RE.search(title):
        return None
    elif code == RESULTS_RELEASE_CODE:
        kind = _results_kind(title, published)
    elif code in INSIDE_INFORMATION_CODES and _STRONG_RESULTS_RE.search(title):
        kind = _results_kind(title, published)
    if kind is None:
        return None
    period, priority = _KIND_PERIOD_PRIORITY[kind]
    return kind, period, priority


def _parse_amf_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _is_english(raw: dict[str, Any]) -> bool:
    return str(raw.get("informationdeposee_inf_lng_inf") or "").strip().lower().startswith("ang")


_CODE_PREFERENCE: tuple[str, ...] = (
    *sorted(ANNUAL_REPORT_CODES),
    *sorted(HALF_YEAR_REPORT_CODES),
    *sorted(QUARTERLY_CODES),
    RESULTS_RELEASE_CODE,
    *sorted(INSIDE_INFORMATION_CODES),
)


def record_subtype_code(value: Any) -> str:
    """Subtype code; multi-tagged records (list or JSON list string) keep the most specific."""
    codes: list[str]
    if isinstance(value, list):
        codes = [str(v).strip() for v in value]
    else:
        text = str(value or "").strip()
        codes = re.findall(r"\d{6}", text) if text.startswith("[") else [text]
    for preferred in _CODE_PREFERENCE:
        if preferred in codes:
            return preferred
    return codes[0] if codes else ""


def amf_record_to_filing(
    raw: dict[str, Any], *, cutoff: datetime | None = None
) -> dict[str, Any] | None:
    code = record_subtype_code(raw.get("informationdeposee_inf_stp_inf"))
    title = " ".join(str(raw.get("informationdeposee_inf_tit_inf") or "").split())
    published = _parse_amf_datetime(raw.get("informationdeposee_inf_dat_emt"))
    if cutoff is not None and published is not None and published < cutoff:
        return None
    url = str(raw.get("url_de_recuperation") or "").strip()
    if not url.startswith("http") or not url.lower().endswith(_DOC_EXTENSIONS):
        return None
    classified = classify_amf_record(code, title, published)
    if classified is None:
        return None
    kind, period, priority = classified
    uin = str(raw.get("uin_idt_uin") or "").strip()
    category = str(raw.get("subtype_of_information") or "").strip()
    return {
        "id": _filing_id(SOURCE, uin or url),
        "source": SOURCE,
        "headline": title,
        "published_at": published.isoformat() if published else None,
        "url": url,
        "period": period,
        "amf_period": period,
        "amf_kind": kind,
        "amf_subtype": code or None,
        "amf_language": "en" if _is_english(raw) else "fr",
        "amf_issuer_lei": str(raw.get("identificationsociete_iso_cd_lei") or "").strip() or None,
        "category": category or None,
        "summary": title,
        "has_body": False,
        "body_path": None,
        "priority": priority,
    }


def _dominant_issuer_rows(raws: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the most frequent LEI when a reused AMF ticker returns several issuers."""
    leis = Counter(
        str(r.get("identificationsociete_iso_cd_lei") or "").strip()
        for r in raws
        if str(r.get("identificationsociete_iso_cd_lei") or "").strip()
    )
    if len(leis) <= 1:
        return raws
    dominant = leis.most_common(1)[0][0]
    return [
        r
        for r in raws
        if str(r.get("identificationsociete_iso_cd_lei") or "").strip() in {"", dominant}
    ]


def prefer_english_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop French twins when an English filing exists for the same day + subtype.

    Keyed without ``amf_kind``: twin headlines can classify differently (a typo in
    one language), and the English row is the one kept either way.
    """
    english_keys = {
        (str(r.get("published_at") or "")[:10], r.get("amf_subtype"))
        for r in rows
        if r.get("amf_language") == "en"
    }
    return [
        r
        for r in rows
        if r.get("amf_language") == "en"
        or (str(r.get("published_at") or "")[:10], r.get("amf_subtype")) not in english_keys
    ]


def _is_refiling(row: dict[str, Any], kept: list[dict[str, Any]]) -> bool:
    """Same URL, or same kind + headline within ``REFILING_WINDOW_DAYS`` (corrected PDF).

    The window keeps generic headlines ("News release on accounts, results")
    reused every quarter by some issuers.
    """
    published = _parse_amf_datetime(row.get("published_at"))
    headline = str(row.get("headline") or "").lower()
    for other in kept:
        if other.get("url") == row.get("url"):
            return True
        if other.get("amf_kind") != row.get("amf_kind"):
            continue
        if str(other.get("headline") or "").lower() != headline:
            continue
        other_published = _parse_amf_datetime(other.get("published_at"))
        if published is None or other_published is None:
            return True
        if abs((other_published - published).days) <= REFILING_WINDOW_DAYS:
            return True
    return False


def select_rows_by_kind_quota(
    rows: list[dict[str, Any]], quotas: dict[str, int] | None = None
) -> list[dict[str, Any]]:
    """Newest rows per ``amf_kind`` up to its quota, returned newest first."""
    quotas = AMF_KIND_QUOTAS if quotas is None else quotas
    newest_first = sorted(rows, key=lambda r: r.get("published_at") or "", reverse=True)
    taken: dict[str, int] = {}
    kept: list[dict[str, Any]] = []
    for row in newest_first:
        kind = str(row.get("amf_kind") or "")
        if taken.get(kind, 0) >= int(quotas.get(kind, 0)):
            continue
        taken[kind] = taken.get(kind, 0) + 1
        kept.append(row)
    return kept


def fetch_filings_amf_direct(
    *,
    ticker: str,
    company_name: str = "",
    identity: dict[str, Any] | None = None,
    max_items: int = AMF_MAX_ITEMS,
    lookback_days: int = AMF_LOOKBACK_DAYS,
    http_get: HttpGet | None = None,
) -> list[dict[str, Any]]:
    """Periodic reports and results releases for one French issuer."""
    del company_name  # Issuer-scoped by AMF ticker / LEI.
    ident = identity if identity is not None else _cached_identity(ticker)
    issuer_filter = amf_issuer_filter(ticker, ident)
    if issuer_filter is None:
        return []
    getter = http_get or _http_get
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    raws: list[dict[str, Any]] = []
    for clause in amf_query_clauses():
        url = amf_records_url(issuer_filter, since=cutoff, clause=clause)
        try:
            payload = getter(url, timeout=40)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            logger.warning("AMF open-data query failed for %s: %s", ticker, exc)
            continue
        raws.extend(parse_records_payload(payload))
    raws.sort(key=lambda r: str(r.get("informationdeposee_inf_dat_emt") or ""), reverse=True)
    rows: list[dict[str, Any]] = []
    for raw in _dominant_issuer_rows(raws):
        row = amf_record_to_filing(raw, cutoff=cutoff)
        if row is not None and not _is_refiling(row, rows):
            rows.append(row)
    rows = select_rows_by_kind_quota(prefer_english_rows(rows))[:max_items]
    if rows:
        logger.info("AMF direct: %s → %d filings", ticker, len(rows))
    return rows


__all__ = [
    "AMF_KIND_QUOTAS",
    "AMF_MAX_ITEMS",
    "SOURCE",
    "amf_eligible",
    "amf_issuer_filter",
    "amf_record_to_filing",
    "amf_ticker",
    "classify_amf_record",
    "fetch_filings_amf_direct",
    "is_amf_issuer",
    "parse_records_payload",
    "prefer_english_rows",
    "select_rows_by_kind_quota",
]
