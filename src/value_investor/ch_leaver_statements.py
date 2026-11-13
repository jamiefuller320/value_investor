"""Companies House statements for FTSE 350 delisting leavers.

The seven hand-verified names in ``ch_failed_name_statements`` stay as they
were extracted. Every other leaver with a UK plc company number is read from
iXBRL when the filing has it, otherwise from the PDF text layer, otherwise by
OCR. A missing year is left missing.

PDFs are cached under ``/tmp/ch-pdfs`` (outside the repo). The store is rewritten
after each name so a stopped run can resume.
"""

from __future__ import annotations

import copy
import io
import json
import logging
import re
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any

from value_investor.ch_failed_name_statements import (
    FAILED_UK_NAMES,
    FIELD_NAMES,
    StatementPage,
    _empty_field,
    _trim_number,
    apply_value_gate,
    extract_statement_pages,
    is_financial_name,
    leaver_year_coverage,
    list_aa_filings,
    merge_ocr_readings,
    parse_statement_pages,
    plausibility_flags,
    summarise_leaver_coverage,
)
from value_investor.research.companies_house import (
    _CH_IXBRL_ATTR_NAME_RE,
    _CH_IXBRL_ATTR_SCALE_RE,
    _CH_IXBRL_ATTR_SIGN_RE,
    _CH_IXBRL_ATTR_UNIT_RE,
    _CH_IXBRL_NONFRACTION_RE,
    MIME_XHTML,
    MIME_XML,
    MIME_ZIP,
    fetch_document_bytes,
    fetch_document_metadata,
)

logger = logging.getLogger(__name__)

PRESERVED_KEYS = {row["key"] for row in FAILED_UK_NAMES}
# Header OCR at 2.2 made three parallel Tesseract processes stall. Leaver scans
# use one process and a slightly smaller header render.
LEAVER_OCR_WORKERS = 1
LEAVER_OCR_ZOOM = 1.6
# Statement pages (not the header scan) are rendered larger. Zoom 1.6 read
# (310.1) as (10.1). Headers stay at 1.6 so the scan remains one process.
LEAVER_PAGE_ZOOM = 2.2

_CONTEXT_RE = re.compile(
    r"<(?:[\w.-]+:)?context\b([^>]*)>(.*?)</(?:[\w.-]+:)?context>",
    re.I | re.S,
)
_CONTEXT_ID_RE = re.compile(r"""\bid=(['"])([^'"]+)\1""", re.I)
_END_DATE_RE = re.compile(r"<(?:[\w.-]+:)?endDate>(\d{4}-\d{2}-\d{2})", re.I)
_EXPLICIT_MEMBER_RE = re.compile(r"explicitMember", re.I)
_CONTEXTREF_RE = re.compile(r"""\bcontextRef=(['"])([^'"]+)\1""", re.I)

# Local tag names, most specific first. Diluted, underlying, adjusted, headline
# and segment tags are skipped even if they contain one of these words.
_FIELD_TAGS: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue", "turnover", "revenuefromcontractswithcustomers"),
    "operating_profit": ("profitlossfromoperatingactivities", "operatingprofitloss"),
    "profit_attributable_to_owners": (
        "profitlossattributabletoownersofparent",
        "profitlossattributabletoowneroftheparent",
        "profitlossattributabletoequityholdersoftheparent",
    ),
    "basic_eps": ("basicearningslosspershare", "basicearningspershare"),
    "weighted_average_basic_shares": (
        "weightedaveragenumberofordinarysharesoutstanding",
        "weightedaveragenumberofshares",
        "weightedaverageshares",
    ),
    "net_cash_from_operating_activities": (
        "cashflowsfromusedinoperatingactivities",
        "netcashflowsfromoperatingactivities",
    ),
    "dividends_per_share": ("dividendspershare",),
    "shares_in_issue": (
        "numbersharesallottedcalledupandfullypaid",
        "numberofsharesissuedfullypaid",
        "numbersharesissuedfullypaid",
        "numberofsharesissued",
        "numberordinarysharesinissue",
        "numberofordinarysharesinissue",
    ),
}
_CAPEX_TAGS = (
    "purchaseofpropertyplantandequipment",
    "purchaseofpropertyplantandequipmentclassedasinfinanceactivities",
    "purchaseofintangibleassets",
    "purchaseofintangibleassetsclassedasinfinanceactivities",
)
_SKIP_TAG_RE = re.compile(
    r"dilut|underlying|adjusted|headline|exceptional|segment|discontinued",
    re.I,
)


def filing_in_leaver_window(meta: dict[str, Any], leaving_date: str) -> bool:
    """Fiscal years 2012 through the leaving year.

    Group accounts are kept when the period-end year is the leaving year, even
    if the period end itself is after the delisting day. A non-group (subsidiary
    full) set of accounts made up after the delisting day is not the listed
    group's year and is skipped.
    """
    made = str(meta.get("made_up_date") or "")
    if len(made) < 10 or made < "2012-01-01":
        return False
    leaving_year = int(leaving_date[:4])
    if int(made[:4]) > leaving_year:
        return False
    description = str(meta.get("description") or "")
    if any(word in description for word in ("interim", "initial", "dormant", "micro")):
        return False
    is_group = "group" in description
    if not is_group and made > leaving_date:
        return False
    return True


def _local_tag(name: str) -> str:
    local = name.split(":")[-1]
    return re.sub(r"[^a-z0-9]", "", local.lower())


def _contexts(html: str) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for match in _CONTEXT_RE.finditer(html):
        ident = _CONTEXT_ID_RE.search(match.group(1))
        if not ident:
            continue
        body = match.group(2)
        end = _END_DATE_RE.search(body)
        found[ident.group(2)] = {
            "end": end.group(1) if end else None,
            "dimensioned": bool(_EXPLICIT_MEMBER_RE.search(body)),
        }
    return found


def _number(raw: str, sign: str | None) -> str | None:
    text = (raw or "").replace(",", "").replace(" ", "").strip()
    if not text:
        return None
    negative = text.startswith("(") or (sign or "").strip() in {"-", "−"}
    text = text.strip("()£$€")
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return None
    if negative and not text.startswith("-"):
        text = "-" + text
    return _trim_number(text)


def _scale_name(scale_attr: str | None) -> str | None:
    if scale_attr in (None, "", "0"):
        return None
    try:
        power = int(scale_attr)
    except ValueError:
        return None
    if power >= 6:
        return "millions"
    if power >= 3:
        return "thousands"
    return None


def _currency(unit_ref: str) -> str | None:
    ref = unit_ref.lower()
    if "gbp" in ref or "gbx" in ref or "pence" in ref:
        return "GBP"
    if "usd" in ref:
        return "USD"
    if "eur" in ref:
        return "EUR"
    return None


def _eps_unit(unit_ref: str) -> str | None:
    ref = unit_ref.lower()
    if "gbx" in ref or "pence" in ref or "penny" in ref:
        return "pence"
    if "gbp" in ref or "usd" in ref or "eur" in ref:
        return "pounds"
    return None


def _ixbrl_facts(html: str) -> list[dict[str, Any]]:
    contexts = _contexts(html)
    facts: list[dict[str, Any]] = []
    for match in _CH_IXBRL_NONFRACTION_RE.finditer(html or ""):
        attrs = match.group(1) or ""
        raw = match.group(2) if match.lastindex and match.lastindex >= 2 else ""
        name_match = _CH_IXBRL_ATTR_NAME_RE.search(attrs)
        ctx_match = _CONTEXTREF_RE.search(attrs)
        if not name_match or not ctx_match:
            continue
        tag = _local_tag(name_match.group(2))
        if _SKIP_TAG_RE.search(tag):
            continue
        context = contexts.get(ctx_match.group(2)) or {}
        sign_match = _CH_IXBRL_ATTR_SIGN_RE.search(attrs)
        scale_match = _CH_IXBRL_ATTR_SCALE_RE.search(attrs)
        unit_match = _CH_IXBRL_ATTR_UNIT_RE.search(attrs)
        value = _number(raw or "", sign_match.group(2) if sign_match else None)
        if value is None:
            continue
        facts.append(
            {
                "tag": tag,
                "value": value,
                "raw": (raw or "").strip(),
                "end": context.get("end"),
                "dimensioned": bool(context.get("dimensioned")),
                "scale": _scale_name(scale_match.group(2) if scale_match else None),
                "unit_ref": unit_match.group(2) if unit_match else "",
            }
        )
    return facts


def _pick_fact(
    facts: list[dict[str, Any]], tags: tuple[str, ...], year: int
) -> dict[str, Any] | None:
    year_facts = [fact for fact in facts if str(fact.get("end") or "").startswith(str(year))]
    plain = [fact for fact in year_facts if not fact["dimensioned"]]
    pool = plain or year_facts
    for tag in tags:
        for fact in pool:
            if fact["tag"] == tag:
                return fact
    return None


def _field_from_fact(fact: dict[str, Any], *, field: str, transaction_id: str) -> dict[str, Any]:
    unit_ref = str(fact.get("unit_ref") or "")
    money = field in {
        "revenue",
        "operating_profit",
        "profit_attributable_to_owners",
        "net_cash_from_operating_activities",
        "capital_expenditure",
    }
    per_share = field in {"basic_eps", "dividends_per_share"}
    unit = _eps_unit(unit_ref) if per_share else None
    currency = _currency(unit_ref) if money or per_share else None
    scale = None if per_share else fact.get("scale")
    if field == "weighted_average_basic_shares":
        scale = fact.get("scale")
        currency = None
    row: dict[str, Any] = {
        "value": fact["value"],
        "scale": scale,
        "currency": currency,
        "unit": unit,
        "source": "primary",
        "absent_reason": None,
        "citation": {
            "transaction_id": transaction_id,
            "page": None,
            "line": f"{fact['tag']} {fact['raw']}",
            "method": "ixbrl",
        },
    }
    if field == "shares_in_issue":
        row["basis"] = "in_issue"
        row["scale"] = fact.get("scale") or "units"
        row["currency"] = None
    return row


def parse_ixbrl_html(
    html: str,
    *,
    made_up_date: str,
    filing_date: str,
    transaction_id: str,
) -> dict[str, Any] | None:
    """Read one accounts filing from inline XBRL. None when EPS and revenue are both absent."""
    facts = _ixbrl_facts(html)
    if not facts:
        return None
    year = int(made_up_date[:4])
    fields: dict[str, Any] = {}
    for field, tags in _FIELD_TAGS.items():
        fact = _pick_fact(facts, tags, year)
        if fact is None:
            fields[field] = _empty_field("not in the iXBRL filing")
        else:
            fields[field] = _field_from_fact(fact, field=field, transaction_id=transaction_id)
    capex_parts = []
    for tag in _CAPEX_TAGS:
        fact = _pick_fact(facts, (tag,), year)
        if fact is not None:
            capex_parts.append(fact)
    if capex_parts:
        total = sum((abs(Decimal(part["value"])) for part in capex_parts), Decimal("0"))
        first = capex_parts[0]
        fields["capital_expenditure"] = _field_from_fact(
            {
                **first,
                "value": _trim_number(str(total)),
                "raw": " + ".join(p["raw"] for p in capex_parts),
            },
            field="capital_expenditure",
            transaction_id=transaction_id,
        )
        fields["capital_expenditure"]["note"] = "purchase of PPE and intangibles, sign dropped"
    else:
        fields["capital_expenditure"] = _empty_field(
            "purchase of property, plant and equipment not in the iXBRL filing"
        )
    currency_fact = _pick_fact(facts, _FIELD_TAGS["revenue"], year)
    currency = _currency(str(currency_fact.get("unit_ref") or "")) if currency_fact else None
    fields["reporting_currency"] = {
        "value": currency,
        "scale": None,
        "currency": currency,
        "unit": None,
        "source": "primary",
        "absent_reason": None if currency else "no currency unit on revenue",
        "citation": None,
    }
    fields["fiscal_year_end"] = {
        "value": made_up_date,
        "scale": None,
        "currency": None,
        "unit": None,
        "source": "primary",
        "absent_reason": None,
        "citation": {
            "transaction_id": transaction_id,
            "page": None,
            "line": made_up_date,
            "method": "ixbrl",
        },
    }
    if fields["revenue"].get("value") in (None, "") and fields["basic_eps"].get("value") in (
        None,
        "",
    ):
        return None
    comparative = _comparative_from_facts(
        facts, year=year, filing_date=filing_date, transaction_id=transaction_id
    )
    return {
        "fiscal_year_end": made_up_date,
        "fiscal_year": year,
        "filing_date": filing_date,
        "transaction_id": transaction_id,
        "source": "primary",
        "fields": fields,
        "comparative": comparative,
        "methods": ["ixbrl"],
        "warnings": [],
        "pages": [],
    }


def _comparative_from_facts(
    facts: list[dict[str, Any]],
    *,
    year: int,
    filing_date: str,
    transaction_id: str,
) -> dict[str, Any] | None:
    prior = year - 1
    fields: dict[str, Any] = {}
    for field, tags in _FIELD_TAGS.items():
        fact = _pick_fact(facts, tags, prior)
        if fact is None:
            continue
        row = _field_from_fact(fact, field=field, transaction_id=transaction_id)
        row["source"] = "comparative"
        fields[field] = row
    if not fields:
        return None
    return {
        "source": "comparative",
        "fiscal_year": prior,
        "fiscal_year_end": None,
        "filing_date": filing_date,
        "transaction_id": transaction_id,
        "fields": fields,
    }


def html_from_document(raw: bytes, content_type: str) -> str | None:
    """Xhtml, xml, or the first html member of a zip package."""
    kind = (content_type or "").lower()
    if "zip" in kind or raw[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as package:
                names = [
                    name
                    for name in package.namelist()
                    if name.lower().endswith((".html", ".htm", ".xhtml", ".xml"))
                ]
                if not names:
                    return None
                return package.read(names[0]).decode("utf-8", errors="replace")
        except zipfile.BadZipFile:
            return None
    if "html" in kind or "xml" in kind or raw.lstrip()[:1] == b"<":
        return raw.decode("utf-8", errors="replace")
    return None


def fetch_ixbrl_html(document_metadata_url: str, *, api_key: str) -> str | None:
    meta = fetch_document_metadata(document_metadata_url, api_key=api_key)
    if not meta:
        return None
    resources = meta.get("resources") or {}
    for mime in (MIME_XHTML, MIME_XML, MIME_ZIP):
        if mime not in resources:
            continue
        fetched = fetch_document_bytes(
            document_metadata_url, api_key=api_key, prefer=mime, metadata=meta
        )
        if not fetched:
            continue
        html = html_from_document(fetched[0], fetched[1])
        if html and "nonfraction" in html.lower():
            return html
    return None


def extract_filing(
    meta: dict[str, Any],
    *,
    key: str,
    api_key: str,
    cache_dir: Path,
    allow_ocr: bool,
) -> dict[str, Any]:
    """One annual filing: iXBRL, then the PDF text layer, then OCR."""
    from value_investor.ch_failed_name_statements import ensure_pdf

    html = None
    try:
        html = fetch_ixbrl_html(meta["document_metadata_url"], api_key=api_key)
    except Exception as exc:  # noqa: BLE001
        logger.info("ixbrl fetch failed %s %s: %s", key, meta.get("made_up_date"), exc)
    if html:
        parsed = parse_ixbrl_html(
            html,
            made_up_date=meta["made_up_date"],
            filing_date=meta["filing_date"],
            transaction_id=meta["transaction_id"],
        )
        if parsed is not None:
            parsed["description"] = meta.get("description")
            parsed["pdf_pages"] = meta.get("pdf_pages")
            return parsed
    pdf = None
    try:
        pdf = ensure_pdf(
            cache_dir,
            key=key,
            made_up=meta["made_up_date"],
            document_metadata_url=meta["document_metadata_url"],
            api_key=api_key,
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("pdf fetch failed %s %s: %s", key, meta.get("made_up_date"), exc)
    if pdf is None:
        return _unavailable(meta, "no iXBRL facts and no PDF")
    import pymupdf

    doc = pymupdf.open(pdf)
    try:
        sample = [
            i for i in (0, doc.page_count // 2, max(0, doc.page_count - 1)) if i < doc.page_count
        ]
        has_text = any(len((doc[i].get_text("text") or "").strip()) > 80 for i in sample)
    finally:
        doc.close()
    if not has_text and not allow_ocr:
        return _unavailable(meta, "image-only PDF; OCR not run in this pass")
    if not has_text:
        # One Tesseract at a time. The zoom stays local to this call.
        pages = extract_statement_pages(
            pdf,
            transaction_id=meta["transaction_id"],
            cache_dir=cache_dir,
            zoom=LEAVER_OCR_ZOOM,
            page_zoom=LEAVER_PAGE_ZOOM,
        )
    else:
        pages = extract_statement_pages(
            pdf, transaction_id=meta["transaction_id"], cache_dir=cache_dir
        )
    parsed = parse_statement_pages(
        pages,
        fiscal_year_end=meta["made_up_date"],
        filing_date=meta["filing_date"],
        transaction_id=meta["transaction_id"],
    )
    alt_pages = [
        StatementPage(page=page.page, text=page.alt_text, method="ocr_embedded")
        for page in pages
        if page.alt_text.strip()
    ]
    if alt_pages:
        alt_parsed = parse_statement_pages(
            alt_pages,
            fiscal_year_end=meta["made_up_date"],
            filing_date=meta["filing_date"],
            transaction_id=meta["transaction_id"],
        )
        parsed = merge_ocr_readings(parsed, alt_parsed)
    parsed["description"] = meta.get("description")
    parsed["pdf_pages"] = meta.get("pdf_pages")
    return parsed


def _unavailable(meta: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "transaction_id": meta.get("transaction_id"),
        "filing_date": meta.get("filing_date"),
        "fiscal_year": int(str(meta.get("made_up_date") or "0")[:4] or 0),
        "fiscal_year_end": meta.get("made_up_date"),
        "description": meta.get("description"),
        "source": "primary",
        "error": reason,
        "fields": {name: _empty_field(reason) for name in FIELD_NAMES},
        "comparative": None,
        "pages": [],
        "methods": [],
        "warnings": [reason],
    }


def _coverage_for(record: dict[str, Any], filings: list[dict[str, Any]]) -> dict[str, Any]:
    expected = record.get("expected_years") or []
    first = int(expected[0]) if expected else int(record.get("first_year_in_window") or 2013)
    leaving = int(record.get("leaving_year") or first)
    return leaver_year_coverage(filings, first_year=first, leaving_year=leaving)


def extraction_rank(record: dict[str, Any]) -> tuple[int, str, str]:
    """Failures first, then applicable listing-moves, then takeovers by leaving date.

    Failures are the names a survivorship check is most likely to miss.
    """
    reason = record.get("reason_class")
    applicable = record.get("ch_applicable") is True
    if reason == "failure":
        group = 0
    elif reason == "other" and applicable:
        group = 1
    elif reason == "takeover":
        group = 2
    else:
        group = 3
    return (group, str(record.get("leaving_date") or "9999-99-99"), str(record.get("key") or ""))


def annotate_name(row: dict[str, Any], record: dict[str, Any] | None) -> dict[str, Any]:
    """Add coverage and the value gate. The seven hand-verified filings are not gated."""
    annotated = dict(row)
    filings = list(row.get("filings") or [])
    preserved = row.get("extraction_status") == "preserved" or str(row.get("key") or "") in (
        PRESERVED_KEYS
    )
    if not preserved and filings:
        filings = copy.deepcopy(filings)
        for filing in filings:
            pages = []
            for page in filing.get("pages") or []:
                if not isinstance(page, dict):
                    continue
                pages.append(
                    {
                        "page": page.get("page"),
                        "method": page.get("method"),
                        "kinds": page.get("kinds"),
                    }
                )
            filing["pages"] = pages
        counts = apply_value_gate(filings, financial=is_financial_name(str(row.get("name") or "")))
        annotated["filings"] = filings
        annotated["values_nulled"] = counts
    if record:
        annotated["reason_class"] = record.get("reason_class")
        annotated["leaving_date"] = record.get("leaving_date")
        annotated["epic"] = record.get("epic")
        annotated["ch_applicable"] = record.get("ch_applicable")
        annotated["company_number_status"] = record.get("company_number_status")
        annotated["leaver_coverage"] = _coverage_for(record, annotated.get("filings") or filings)
    annotated["plausibility_flags"] = plausibility_flags(annotated.get("filings") or filings)
    return annotated


def placeholder_name(record: dict[str, Any], *, status: str, reason: str) -> dict[str, Any]:
    row = {
        "key": record["key"],
        "name": record["name"],
        "company_number": record.get("company_number"),
        "company_number_verified": record.get("company_number_reason"),
        "reason_class": record.get("reason_class"),
        "leaving_date": record.get("leaving_date"),
        "epic": record.get("epic"),
        "ch_applicable": record.get("ch_applicable"),
        "company_number_status": record.get("company_number_status"),
        "extraction_status": status,
        "extraction_note": reason,
        "filing_count": 0,
        "filings": [],
        "plausibility_flags": [],
        "leaver_coverage": _coverage_for(record, []),
    }
    return row


def name_is_complete(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    return row.get("extraction_status") in {"complete", "not_applicable", "unresolved", "preserved"}


def iter_pending(
    records: list[dict[str, Any]],
    done: dict[str, dict[str, Any]],
    *,
    refresh: set[str] | None = None,
) -> list[dict[str, Any]]:
    refresh = refresh or set()
    pending = []
    for record in records:
        key = str(record.get("key") or "")
        row = done.get(key)
        if row and row.get("extraction_status") == "preserved":
            continue
        if key in refresh or not name_is_complete(row):
            pending.append(record)
    return sorted(pending, key=extraction_rank)


def extract_leaver_name(
    record: dict[str, Any],
    *,
    api_key: str,
    cache_dir: Path,
    allow_ocr: bool,
) -> dict[str, Any]:
    if record.get("ch_applicable") is False:
        return placeholder_name(
            record,
            status="not_applicable",
            reason=str(record.get("company_number_reason") or "no UK Companies House accounts"),
        )
    if record.get("company_number_status") != "resolved" or not record.get("company_number"):
        return placeholder_name(
            record,
            status="unresolved",
            reason=str(record.get("company_number_reason") or "company number unresolved"),
        )
    metas = [
        meta
        for meta in list_aa_filings(str(record["company_number"]), api_key)
        if filing_in_leaver_window(meta, str(record["leaving_date"]))
    ]
    filings = [
        extract_filing(
            meta, key=record["key"], api_key=api_key, cache_dir=cache_dir, allow_ocr=allow_ocr
        )
        for meta in metas
    ]
    needs_ocr = any("OCR not run" in " ".join(filing.get("warnings") or []) for filing in filings)
    from value_investor.ch_failed_name_statements import _summarise_name

    summary = _summarise_name(
        {
            "key": record["key"],
            "name": record["name"],
            "company_number": str(record["company_number"]),
            "verified": str(record.get("company_number_reason") or ""),
        },
        filings,
    )
    summary["extraction_status"] = "needs_ocr" if needs_ocr else "complete"
    return annotate_name(summary, record)


def seed_preserved(
    existing_names: list[dict[str, Any]],
    records_by_key: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Keep the seven hand-verified filings and attach coverage where they are leavers."""
    seeded: dict[str, dict[str, Any]] = {}
    for row in existing_names:
        key = str(row.get("key") or "")
        if key not in PRESERVED_KEYS:
            continue
        if row.get("extraction_status") == "preserved" and row.get("filings"):
            seeded[key] = row
            continue
        # Drop any annotation a previous partial run may have added, then re-attach
        # from the filings so the filing objects stay the ones that were verified.
        bare = {
            field: row[field]
            for field in row
            if field
            not in {
                "reason_class",
                "leaving_date",
                "epic",
                "ch_applicable",
                "company_number_status",
                "leaver_coverage",
                "plausibility_flags",
                "extraction_status",
                "extraction_note",
            }
        }
        annotated = annotate_name(bare, records_by_key.get(key))
        annotated["extraction_status"] = "preserved"
        seeded[key] = annotated
    return seeded


def assemble_store(
    done: dict[str, dict[str, Any]],
    records: list[dict[str, Any]],
    *,
    eodhd_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    from value_investor.ch_failed_name_statements import FAILED_UK_NAMES as preserved
    from value_investor.ch_failed_name_statements import build_store

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for spec in preserved:
        row = done.get(spec["key"])
        if row:
            rows.append(row)
            seen.add(spec["key"])
    for record in records:
        key = record["key"]
        if key in seen:
            continue
        row = done.get(key)
        if row:
            rows.append(row)
            seen.add(key)
    payload = build_store(rows, eodhd_payload=eodhd_payload)
    payload["leaver_list"] = "docs/data/ftse350_leavers_2013_2025.json"
    payload["leaver_coverage"] = summarise_leaver_coverage(rows)
    from value_investor.ch_failed_name_statements import summarise_share_coverage

    payload["share_coverage"] = summarise_share_coverage(rows)
    pending = iter_pending(records, done)
    payload["leaver_cursor"] = {
        "ocr_workers": LEAVER_OCR_WORKERS,
        "ocr_zoom": LEAVER_OCR_ZOOM,
        "page_zoom": LEAVER_PAGE_ZOOM,
        "order": "failure, other, takeover by leaving date",
        "pending_keys": [record["key"] for record in pending],
        "pending_count": len(pending),
    }
    return payload


def run_leaver_extraction(
    *,
    leaver_path: Path,
    out_path: Path,
    api_key: str,
    cache_dir: Path,
    allow_ocr: bool,
    only: set[str] | None = None,
    limit: int | None = None,
    eodhd_path: Path | None = None,
    refresh: set[str] | None = None,
) -> dict[str, Any]:
    """Extract leaver statements, resuming from ``out_path`` when names are already complete."""
    from value_investor.ch_failed_name_statements import (
        DEFAULT_STORE_PATH,
        load_eodhd_report,
        load_store,
        write_store,
    )

    listing = json.loads(leaver_path.read_text(encoding="utf-8"))
    records = list(listing.get("names") or [])
    records_by_key = {row["key"]: row for row in records}
    done: dict[str, dict[str, Any]] = {}
    if out_path.is_file():
        current = json.loads(out_path.read_text(encoding="utf-8"))
        done = {str(row.get("key")): row for row in current.get("names") or [] if row.get("key")}
    original = load_store(DEFAULT_STORE_PATH)
    preserved = seed_preserved(list(original.get("names") or []), records_by_key)
    for key, row in preserved.items():
        existing = done.get(key)
        if not existing or existing.get("extraction_status") != "preserved":
            done[key] = row
        elif not existing.get("leaver_coverage") and key in records_by_key:
            done[key] = annotate_name(existing, records_by_key[key])
            done[key]["extraction_status"] = "preserved"
    eodhd_payload = load_eodhd_report(eodhd_path or Path("docs/data/eodhd_coverage_check.json"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    for key, row in list(done.items()):
        if key in PRESERVED_KEYS or row.get("extraction_status") == "preserved":
            continue
        gated = annotate_name(row, records_by_key.get(key))
        gated["extraction_status"] = row.get("extraction_status")
        done[key] = gated
    pending = iter_pending(records, done, refresh=refresh)
    if only:
        pending = [record for record in pending if record["key"] in only]
    if limit is not None:
        pending = pending[:limit]
    logger.info("leaver extraction pending %s (ocr=%s)", len(pending), allow_ocr)
    write_store(assemble_store(done, records, eodhd_payload=eodhd_payload), out_path)
    for index, record in enumerate(pending, start=1):
        logger.info("leaver %s/%s %s", index, len(pending), record["key"])
        try:
            done[record["key"]] = extract_leaver_name(
                record, api_key=api_key, cache_dir=cache_dir, allow_ocr=allow_ocr
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("leaver %s failed: %s", record["key"], exc)
            failed = placeholder_name(record, status="error", reason=str(exc))
            done[record["key"]] = failed
        payload = assemble_store(done, records, eodhd_payload=eodhd_payload)
        write_store(payload, out_path)
    return assemble_store(done, records, eodhd_payload=eodhd_payload)
