"""Re-extract shares-in-issue and retry weighted-average share counts only."""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

from value_investor.ch_failed_name_statements import (
    DEFAULT_STORE_PATH,
    ensure_pdf,
    extract_eps_note_pages,
    extract_share_capital_pages,
    list_aa_filings,
    load_eodhd_report,
    load_store,
    merge_share_supplement,
    parse_share_supplement,
    write_store,
)
from value_investor.ch_leaver_statements import (
    LEAVER_OCR_ZOOM,
    LEAVER_PAGE_ZOOM,
    PRESERVED_KEYS,
    annotate_name,
    assemble_store,
    extraction_rank,
    fetch_ixbrl_html,
    filing_in_leaver_window,
    parse_ixbrl_html,
)

logger = logging.getLogger(__name__)


def _share_reextract_applicable(row: dict[str, Any]) -> bool:
    status = str(row.get("extraction_status") or "")
    if status in {"not_applicable", "unresolved", "error"}:
        return False
    # Preserved and complete leavers; retry needs_ocr when OCR is allowed by the caller.
    return status in {"complete", "preserved", "needs_ocr"}


def _ixbrl_share_supplement(
    html: str,
    *,
    made_up_date: str,
    filing_date: str,
    transaction_id: str,
) -> dict[str, Any] | None:
    parsed = parse_ixbrl_html(
        html,
        made_up_date=made_up_date,
        filing_date=filing_date,
        transaction_id=transaction_id,
    )
    if not parsed:
        return None
    fields = parsed.get("fields") or {}
    supplement: dict[str, Any] = {
        "primary": {
            "shares_in_issue": fields.get("shares_in_issue"),
            "weighted_average_basic_shares": fields.get("weighted_average_basic_shares"),
        }
    }
    comp = parsed.get("comparative") or {}
    comp_fields = comp.get("fields") or {}
    if comp_fields.get("shares_in_issue"):
        supplement["comparative"] = {
            "fiscal_year": comp.get("fiscal_year"),
            "fields": {"shares_in_issue": comp_fields.get("shares_in_issue")},
        }
    return supplement


def refresh_filing_share_fields(
    filing: dict[str, Any],
    meta: dict[str, Any],
    *,
    key: str,
    api_key: str,
    cache_dir: Path,
    allow_ocr: bool,
) -> None:
    """Update only share-related fields on an existing filing dict."""
    transaction_id = str(meta.get("transaction_id") or filing.get("transaction_id") or "")
    made_up = str(meta.get("made_up_date") or filing.get("fiscal_year_end") or "")
    filing_date = str(meta.get("filing_date") or filing.get("filing_date") or "")
    html = None
    try:
        html = fetch_ixbrl_html(meta["document_metadata_url"], api_key=api_key)
    except Exception as exc:  # noqa: BLE001
        logger.info("ixbrl fetch failed %s %s: %s", key, made_up, exc)
    supplement = None
    if html:
        supplement = _ixbrl_share_supplement(
            html,
            made_up_date=made_up,
            filing_date=filing_date,
            transaction_id=transaction_id,
        )
    if supplement is None:
        pdf = ensure_pdf(
            cache_dir,
            key=key,
            made_up=made_up,
            document_metadata_url=meta["document_metadata_url"],
            api_key=api_key,
        )
        if pdf is None:
            return
        share_pages = extract_share_capital_pages(
            pdf,
            transaction_id=transaction_id,
            cache_dir=cache_dir,
            zoom=LEAVER_OCR_ZOOM,
            page_zoom=LEAVER_PAGE_ZOOM,
        )
        stmt_pages = extract_eps_note_pages(
            pdf,
            transaction_id=transaction_id,
            cache_dir=cache_dir,
            zoom=LEAVER_OCR_ZOOM,
            page_zoom=LEAVER_PAGE_ZOOM,
        )
        by_page = {page.page: page for page in share_pages + stmt_pages}
        pages = list(by_page.values())
        supplement = parse_share_supplement(
            pages,
            fiscal_year_end=made_up,
            filing_date=filing_date,
            transaction_id=transaction_id,
        )
    merge_share_supplement(filing, supplement)


def run_share_reextraction(
    *,
    leaver_path: Path,
    out_path: Path,
    api_key: str,
    cache_dir: Path,
    allow_ocr: bool,
    only: set[str] | None = None,
    limit: int | None = None,
    eodhd_path: Path | None = None,
) -> dict[str, Any]:
    listing = json.loads(leaver_path.read_text(encoding="utf-8"))
    records = list(listing.get("names") or [])
    records_by_key = {row["key"]: row for row in records}
    done: dict[str, dict[str, Any]] = {}
    if out_path.is_file():
        current = json.loads(out_path.read_text(encoding="utf-8"))
        done = {str(row.get("key")): row for row in current.get("names") or [] if row.get("key")}
    original = load_store(DEFAULT_STORE_PATH)
    for row in original.get("names") or []:
        key = str(row.get("key") or "")
        if key in PRESERVED_KEYS and key not in done:
            done[key] = row
    pending_rows = [
        row
        for row in done.values()
        if _share_reextract_applicable(row) and (not only or str(row.get("key")) in only)
    ]
    pending_rows.sort(
        key=lambda row: extraction_rank(
            records_by_key.get(str(row.get("key")))
            or {
                "reason_class": "takeover",
                "leaving_date": "9999-99-99",
                "key": row.get("key"),
            }
        )
    )
    if limit is not None:
        pending_rows = pending_rows[:limit]
    eodhd_payload = load_eodhd_report(eodhd_path or Path("docs/data/eodhd_coverage_check.json"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    logger.info("share re-extraction pending %s (ocr=%s)", len(pending_rows), allow_ocr)
    write_store(assemble_store(done, records, eodhd_payload=eodhd_payload), out_path)
    for index, row in enumerate(pending_rows, start=1):
        key = str(row.get("key"))
        work = copy.deepcopy(row)
        if not work.get("filings"):
            continue
        if work.get("extraction_status") == "needs_ocr" and not allow_ocr:
            continue
        record = records_by_key.get(key) or {}
        company_number = work.get("company_number") or record.get("company_number")
        if not company_number:
            continue
        metas = list_aa_filings(str(company_number), api_key)
        if record.get("leaving_date"):
            metas = [
                meta for meta in metas if filing_in_leaver_window(meta, str(record["leaving_date"]))
            ]
        by_tx = {str(meta.get("transaction_id")): meta for meta in metas}
        logger.info("shares %s/%s %s", index, len(pending_rows), key)
        for filing in work.get("filings") or []:
            meta = by_tx.get(str(filing.get("transaction_id")))
            if meta is None:
                continue
            try:
                refresh_filing_share_fields(
                    filing,
                    meta,
                    key=key,
                    api_key=api_key,
                    cache_dir=cache_dir,
                    allow_ocr=allow_ocr,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("share re-extract %s %s: %s", key, filing.get("fiscal_year"), exc)
        preserved = key in PRESERVED_KEYS or work.get("extraction_status") == "preserved"
        if preserved:
            done[key] = work
        else:
            done[key] = annotate_name(work, record or None)
            done[key]["extraction_status"] = work.get("extraction_status") or "complete"
        payload = assemble_store(done, records, eodhd_payload=eodhd_payload)
        write_store(payload, out_path)
    return assemble_store(done, records, eodhd_payload=eodhd_payload)
