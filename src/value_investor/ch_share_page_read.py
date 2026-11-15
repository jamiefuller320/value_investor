"""Targeted share-capital note page read for failure / other leavers (high-res OCR)."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from value_investor.ch_failed_name_statements import (
    _DIVIDED_INTO_ORDINARY_RE,
    _SHARE_CAPITAL_HINT_RE,
    ABSENT_SHARES_CH_CAPITAL,
    CH_NAME_BY_KEY,
    Candidate,
    StatementPage,
    _empty_field,
    _filled_field,
    _share_count_units,
    _year_columns,
    apply_shares_precision_to_filings,
    ensure_pdf,
    extract_share_capital_pages,
    list_aa_filings,
    load_eodhd_report,
    load_store,
    parse_share_supplement,
    select_columns,
    shares_nominal_cross_check,
    write_store,
)
from value_investor.ch_leaver_statements import assemble_store, filing_in_leaver_window

logger = logging.getLogger(__name__)

ABSENT_NO_SHARE_CAPITAL_NOTE = "no share-capital note page (abridged or parent-only accounts)"
PAGE_READ_METHOD = "page_read"
PAGE_READ_DPI = 200
VERIFIED_READINGS_PATH = Path("docs/data/ch_share_page_read_verified.json")


def load_verified_readings(path: Path = VERIFIED_READINGS_PATH) -> dict[tuple[str, int, str], dict[str, Any]]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: dict[tuple[str, int, str], dict[str, Any]] = {}
    for row in payload.get("readings") or []:
        key = str(row.get("key"))
        year = row.get("fiscal_year")
        if not key or year is None:
            continue
        tx = str(row.get("transaction_id") or "")
        out[(key, int(year), tx)] = row
        if tx:
            continue
        dup = (key, int(year), "")
        if dup not in out:
            out[dup] = row
    return out


def _page_read_absent(reason: str) -> str:
    core = reason.removeprefix("page_read: ").strip()
    return f"page_read: {core}"


def _verified_hit(
    verified: dict[tuple[str, int, str], dict[str, Any]] | None,
    *,
    key: str,
    fiscal_year: int | None,
    transaction_id: str,
) -> dict[str, Any] | None:
    if verified is None or fiscal_year is None:
        return None
    tx = str(transaction_id or "")
    hit = verified.get((key, int(fiscal_year), tx))
    if hit is not None:
        if hit.get("transaction_id") and str(hit["transaction_id"]) != tx:
            return None
        return hit
    return verified.get((key, int(fiscal_year), ""))


def _nominal_from_verified(reading: dict[str, Any], value: str) -> dict[str, Any]:
    capital_m = reading.get("called_up_capital_gbp_millions")
    nominal = reading.get("nominal_gbp")
    if capital_m in (None, "") or nominal in (None, ""):
        return {"status": "unavailable"}
    try:
        capital = Decimal(str(capital_m).replace(",", "")) * Decimal("1000000")
        nom = Decimal(str(nominal))
        count = _share_count_units(value, "units")
    except (InvalidOperation, TypeError):
        return {"status": "unavailable"}
    if count is None or nom <= 0:
        return {"status": "unavailable"}
    implied = capital / nom
    rel = abs(count - implied) / max(implied, Decimal("1"))
    return {
        "status": "pass" if rel <= Decimal("0.01") else "fail",
        "called_up_capital_gbp": str(capital),
        "nominal_gbp": str(nom),
        "implied_count": str(int(implied)),
        "stored_count": str(int(count)),
        "relative_error": str(rel.quantize(Decimal("0.0001"))),
    }


def _apply_verified_withhold(
    filing: dict[str, Any],
    reading: dict[str, Any],
    *,
    transaction_id: str,
) -> bool:
    reason = str(
        reading.get("absent_reason")
        or reading.get("line")
        or "withheld after page read (verified)"
    )
    field = _empty_field(_page_read_absent(reason), source="primary")
    field["citation"] = {
        "transaction_id": transaction_id,
        "page": reading.get("page"),
        "line": str(reading.get("line") or reason),
        "method": PAGE_READ_METHOD,
    }
    filing.setdefault("fields", {})["shares_in_issue"] = field
    return True


def _apply_verified_reading(
    filing: dict[str, Any],
    reading: dict[str, Any],
    *,
    transaction_id: str,
) -> bool:
    value = str(reading.get("value") or "").replace(",", "")
    if not value.isdigit():
        return False
    page = int(reading.get("page") or 0)
    line = str(reading.get("line") or "")
    column_clear = bool(reading.get("column_year_clear"))
    nominal = _nominal_from_verified(reading, value)
    if str(reading.get("nominal_gbp") or ""):
        row_nominal = {"per_share_gbp": reading.get("nominal_gbp")}
    else:
        row_nominal = {}
    earnings = shares_earnings_cross_check(filing, value, "units")
    if not _verification_passes(nominal=nominal, earnings=earnings, column_year_clear=column_clear):
        return False
    row = {
        "value": value,
        "scale": "units",
        "currency": None,
        "unit": None,
        "source": "primary",
        "absent_reason": None,
        "basis": "in_issue",
        "extraction_method": PAGE_READ_METHOD,
        "cross_check": nominal,
        "earnings_check": earnings,
        "column_year_clear": column_clear,
        "nominal_per_share_gbp": row_nominal.get("per_share_gbp"),
        "citation": {
            "transaction_id": transaction_id,
            "page": page or None,
            "line": line,
            "method": PAGE_READ_METHOD,
        },
    }
    filing.setdefault("fields", {})["shares_in_issue"] = row
    return True


def _is_target_leaver(key: str, reason_class: str | None) -> bool:
    if key in CH_NAME_BY_KEY:
        return True
    return reason_class in {"failure", "other"}


def shares_earnings_cross_check(filing: dict[str, Any], share_value: object, scale: str | None) -> dict[str, Any]:
    fields = filing.get("fields") or {}
    profit = fields.get("profit_attributable_to_owners") or {}
    eps = fields.get("basic_eps") or {}
    if profit.get("value") in (None, "") or eps.get("value") in (None, ""):
        return {"status": "unavailable"}
    try:
        p = Decimal(str(profit["value"]).replace(",", ""))
        e = Decimal(str(eps["value"]).replace(",", ""))
    except InvalidOperation:
        return {"status": "unavailable"}
    if e == 0:
        return {"status": "unavailable"}
    p_scale = profit.get("scale")
    if p_scale == "millions":
        p = p * Decimal("1000000")
    elif p_scale == "thousands":
        p = p * Decimal("1000")
    if str(eps.get("unit") or "").lower() in {"pence", "p"}:
        e = e / Decimal("100")
    count = _share_count_units(share_value, scale)
    if count is None or count <= 0:
        return {"status": "unavailable"}
    implied = abs(p) / abs(e)
    rel = abs(count - implied) / max(implied, Decimal("1"))
    status = "pass" if rel <= Decimal("0.15") else "fail"
    return {
        "status": status,
        "implied_shares": str(int(implied)),
        "stored_shares": str(int(count)),
        "relative_error": str(rel.quantize(Decimal("0.0001"))),
    }


def _note_has_year_column_header(text: str, current_year: int) -> bool:
    years = _year_columns([line.strip() for line in text.splitlines() if line.strip()])
    if not years:
        return False
    try:
        current_idx, _, _ = select_columns(years, current_year)
    except Exception:
        return False
    return current_idx is not None


def _extract_from_note_text(
    text: str,
    *,
    fiscal_year_end: str,
    page: int,
    transaction_id: str,
) -> tuple[dict[str, Any] | None, str, bool]:
    """Return (field_dict, matched_line, column_year_clear)."""
    current_year = int(fiscal_year_end[:4])
    supplement = parse_share_supplement(
        [StatementPage(page=page, text=text, method=PAGE_READ_METHOD)],
        fiscal_year_end=fiscal_year_end,
        filing_date=fiscal_year_end,
        transaction_id=transaction_id,
    )
    row = (supplement.get("primary") or {}).get("shares_in_issue") or {}
    if row.get("value") not in (None, ""):
        cit = row.get("citation") or {}
        line = str(cit.get("line") or "")
        return row, line, _note_has_year_column_header(text, current_year)

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        divided = _DIVIDED_INTO_ORDINARY_RE.search(line)
        if divided and "ordinary" in line.lower():
            raw = re.sub(r"[\s,]", "", divided.group(1))
            if raw.isdigit():
                cand = Candidate(
                    field="shares_in_issue",
                    priority=5,
                    label=line,
                    line=line,
                    page=page,
                    current=raw,
                    prior=None,
                    unit=None,
                    money=False,
                    share_scale="units",
                    share_basis="in_issue",
                )
                field = _filled_field(
                    cand,
                    transaction_id=transaction_id,
                    source="primary",
                    scale=None,
                    currency=None,
                    basis="in_issue",
                )
                return field, line, _note_has_year_column_header(text, current_year)
    return None, "", _note_has_year_column_header(text, current_year)


def _render_page_png(pdf: Path, page: int, *, dpi: int = PAGE_READ_DPI) -> Path | None:
    out_dir = Path(tempfile.mkdtemp(prefix="ch-page-read-"))
    prefix = out_dir / "page"
    try:
        subprocess.run(
            [
                "pdftoppm",
                "-png",
                "-r",
                str(dpi),
                "-f",
                str(page),
                "-l",
                str(page),
                str(pdf),
                str(prefix),
            ],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        logger.info("pdftoppm failed page %s: %s", page, exc)
        return None
    candidates = sorted(out_dir.glob("page-*.png"))
    return candidates[0] if candidates else None


def _ocr_png(path: Path) -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""
    try:
        image = Image.open(path)
        return pytesseract.image_to_string(image, config="--psm 6") or ""
    except Exception as exc:  # noqa: BLE001
        logger.info("tesseract failed %s: %s", path, exc)
        return ""


def _brute_force_share_note_page(
    pdf: Path,
    *,
    transaction_id: str,
    cache_dir: Path,
) -> tuple[int | None, str]:
    import pymupdf

    doc = pymupdf.open(pdf)
    try:
        for index in range(doc.page_count):
            text = (doc[index].get_text("text") or "").strip()
            if len(text) < 50:
                png = _render_page_png(pdf, index + 1)
                if png is not None:
                    text = _ocr_png(png)
            low = text.lower()
            if "remuneration" in low and "allotted" not in low:
                continue
            if re.search(r"allotted.*called up.*fully paid", text, re.I) and "ordinary" in low:
                return index + 1, text
            if (
                re.search(r"issued and fully paid", text, re.I)
                and "ordinary" in low
                and ("at end of year" in low or "number" in low)
            ):
                return index + 1, text
            if re.search(r"share capital and reserves", text, re.I) and "ordinary" in low:
                return index + 1, text
            if _DIVIDED_INTO_ORDINARY_RE.search(text) and "share capital" in low:
                return index + 1, text
    finally:
        doc.close()
    return None, ""


def _locate_share_capital_page(
    pdf: Path,
    *,
    transaction_id: str,
    cache_dir: Path,
) -> int | None:
    pages = extract_share_capital_pages(
        pdf,
        transaction_id=transaction_id,
        cache_dir=cache_dir,
        wide=True,
        max_pages=6,
    )
    if not pages:
        return None

    def score(page: StatementPage) -> int:
        text = page.text.lower()
        s = 0
        if "remuneration" in text or "director share interest" in text:
            s -= 8
        if "shareholder engagement" in text or "voting rights" in text:
            s -= 5
        if re.search(r"\bnote\s+\d+\b.*share capital", text, re.I):
            s += 6
        if "called up share capital" in text or "share capital" in text:
            s += 3
        if "allotted" in text and "called up" in text and "fully paid" in text:
            s += 6
        if _DIVIDED_INTO_ORDINARY_RE.search(page.text):
            s += 5
        if _SHARE_CAPITAL_HINT_RE.search(page.text):
            s += 2
        if re.search(r"number\s+m|£\s*m|million", text):
            s += 2
        return s

    if pages:
        best = max(pages, key=score)
        if score(best) > 0:
            return int(best.page)
    forced, _ = _brute_force_share_note_page(pdf, transaction_id=transaction_id, cache_dir=cache_dir)
    return forced


def _read_note_page_text(
    pdf: Path,
    page: int,
    *,
    transaction_id: str,
    cache_dir: Path,
) -> str:
    import pymupdf

    doc = pymupdf.open(pdf)
    try:
        if 1 <= page <= doc.page_count:
            text = doc[page - 1].get_text("text") or ""
            if len(text.strip()) > 60:
                return text
    finally:
        doc.close()
    png = _render_page_png(pdf, page)
    if png is None:
        return ""
    text = _ocr_png(png)
    if len(text.strip()) > 40:
        return text
    pages = extract_share_capital_pages(
        pdf,
        transaction_id=transaction_id,
        cache_dir=cache_dir,
        wide=False,
        max_pages=1,
    )
    for sp in pages:
        if sp.page == page:
            return sp.text
    return text


def _verification_passes(
    *,
    nominal: dict[str, Any],
    earnings: dict[str, Any],
    column_year_clear: bool,
) -> bool:
    n = nominal.get("status")
    e = earnings.get("status")
    if n == "fail" or e == "fail":
        return column_year_clear
    if n == "pass" or e == "pass":
        return True
    if n == "unavailable" and e == "unavailable":
        return column_year_clear
    return column_year_clear


def page_read_filing_shares(
    filing: dict[str, Any],
    *,
    key: str,
    meta: dict[str, Any],
    api_key: str,
    cache_dir: Path,
    verified: dict[tuple[str, int, str], dict[str, Any]] | None = None,
    force: bool = False,
) -> None:
    shares = (filing.get("fields") or {}).get("shares_in_issue") or {}
    if not force and shares.get("value") not in (None, ""):
        return
    made_up = str(meta.get("made_up_date") or filing.get("fiscal_year_end") or "")
    transaction_id = str(meta.get("transaction_id") or filing.get("transaction_id") or "")
    fiscal_year = filing.get("fiscal_year")
    hit = _verified_hit(verified, key=key, fiscal_year=fiscal_year, transaction_id=transaction_id)
    if hit and _apply_verified_reading(filing, hit, transaction_id=transaction_id):
        return
    pdf = ensure_pdf(
        cache_dir,
        key=key,
        made_up=made_up,
        document_metadata_url=meta["document_metadata_url"],
        api_key=api_key,
    )
    if pdf is None:
        filing.setdefault("fields", {})["shares_in_issue"] = _empty_field(
            _page_read_absent("no PDF for this filing"), source="primary"
        )
        return
    page = _locate_share_capital_page(pdf, transaction_id=transaction_id, cache_dir=cache_dir)
    if page is None:
        filing.setdefault("fields", {})["shares_in_issue"] = _empty_field(
            _page_read_absent(ABSENT_NO_SHARE_CAPITAL_NOTE), source="primary"
        )
        return
    text = _read_note_page_text(pdf, page, transaction_id=transaction_id, cache_dir=cache_dir)
    if not text.strip():
        filing.setdefault("fields", {})["shares_in_issue"] = _empty_field(
            _page_read_absent("share-capital note page not readable (OCR)"), source="primary"
        )
        return
    row, line, column_clear = _extract_from_note_text(
        text,
        fiscal_year_end=made_up,
        page=page,
        transaction_id=transaction_id,
    )
    if row is None or row.get("value") in (None, ""):
        filing.setdefault("fields", {})["shares_in_issue"] = _empty_field(
            _page_read_absent("share-capital note present but year-end ordinary count not readable"),
            source="primary",
        )
        return
    nominal = shares_nominal_cross_check([text], row["value"], row.get("scale"))
    earnings = shares_earnings_cross_check(filing, row["value"], row.get("scale"))
    row["cross_check"] = nominal
    row["earnings_check"] = earnings
    row["extraction_method"] = PAGE_READ_METHOD
    row["source"] = "primary"
    row["column_year_clear"] = column_clear
    if row.get("citation"):
        row["citation"]["method"] = PAGE_READ_METHOD
        row["citation"]["page"] = page
        if line:
            row["citation"]["line"] = line
    if not _verification_passes(nominal=nominal, earnings=earnings, column_year_clear=column_clear):
        filing.setdefault("fields", {})["shares_in_issue"] = _empty_field(
            _page_read_absent("failed verification (nominal/earnings/column)"), source="primary"
        )
        return
    filing.setdefault("fields", {})["shares_in_issue"] = row


def run_page_read_backfill(
    *,
    leaver_path: Path,
    out_path: Path,
    api_key: str,
    cache_dir: Path,
    eodhd_path: Path | None = None,
    only: set[str] | None = None,
) -> dict[str, Any]:
    listing = json.loads(leaver_path.read_text(encoding="utf-8"))
    records = list(listing.get("names") or [])
    records_by_key = {row["key"]: row for row in records}
    payload = load_store(out_path)
    done = {str(n.get("key")): n for n in payload.get("names") or [] if n.get("key")}
    targets = [
        row
        for row in done.values()
        if _is_target_leaver(str(row.get("key")), row.get("reason_class"))
        and (not only or str(row.get("key")) in only)
    ]
    targets.sort(key=lambda r: (0 if r.get("key") in CH_NAME_BY_KEY else 1, str(r.get("key"))))
    eodhd = load_eodhd_report(eodhd_path or Path("docs/data/eodhd_coverage_check.json"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    verified = load_verified_readings()
    for index, row in enumerate(targets, start=1):
        key = str(row.get("key"))
        record = records_by_key.get(key) or CH_NAME_BY_KEY.get(key) or {}
        company_number = str(row.get("company_number") or record.get("company_number") or "")
        if not company_number:
            continue
        metas = list_aa_filings(company_number, api_key)
        if record.get("leaving_date"):
            metas = [m for m in metas if filing_in_leaver_window(m, str(record["leaving_date"]))]
        by_tx = {str(m.get("transaction_id")): m for m in metas}
        work = json.loads(json.dumps(row))
        logger.info("page read %s/%s %s", index, len(targets), key)
        for filing in work.get("filings") or []:
            meta = by_tx.get(str(filing.get("transaction_id")))
            if meta is None:
                continue
            page_read_filing_shares(
                filing, key=key, meta=meta, api_key=api_key, cache_dir=cache_dir, verified=verified
            )
        apply_shares_precision_to_filings(work.get("filings") or [], ftse_member=True)
        done[key] = work
        payload = assemble_store(done, records, eodhd_payload=eodhd)
        write_store(payload, out_path)
    return assemble_store(done, records, eodhd_payload=eodhd)


def apply_verified_page_reads_to_store(
    out_path: Path,
    *,
    leaver_path: Path,
    verified_path: Path = VERIFIED_READINGS_PATH,
    eodhd_path: Path | None = None,
) -> dict[str, Any]:
    listing = json.loads(leaver_path.read_text(encoding="utf-8"))
    records = list(listing.get("names") or [])
    verified = load_verified_readings(verified_path)
    payload = load_store(out_path)
    done = {str(n.get("key")): n for n in payload.get("names") or [] if n.get("key")}
    for (key, year, _), reading in verified.items():
        row = done.get(key)
        if not row:
            continue
        want_tx = str(reading.get("transaction_id") or "")
        want_fye = str(reading.get("fiscal_year_end") or "")
        for filing in row.get("filings") or []:
            if int(filing.get("fiscal_year") or -1) != year:
                continue
            if want_fye and str(filing.get("fiscal_year_end") or "") != want_fye:
                continue
            tx = str(filing.get("transaction_id") or "")
            if want_tx and want_tx != tx:
                continue
            shares = (filing.get("fields") or {}).get("shares_in_issue") or {}
            if shares.get("value") not in (None, "") and not want_tx and not reading.get("withhold"):
                continue
            if reading.get("withhold"):
                if want_tx or shares.get("value") not in (None, ""):
                    _apply_verified_withhold(filing, reading, transaction_id=tx)
                continue
            if want_tx or shares.get("value") in (None, ""):
                _apply_verified_reading(filing, reading, transaction_id=tx)
        apply_shares_precision_to_filings(row.get("filings") or [], ftse_member=True)
    eodhd = load_eodhd_report(eodhd_path or Path("docs/data/eodhd_coverage_check.json"))
    payload = assemble_store(done, records, eodhd_payload=eodhd)
    write_store(payload, out_path)
    return payload


def run_force_page_read_filings(
    *,
    store_path: Path,
    leaver_path: Path,
    api_key: str,
    cache_dir: Path,
    targets: list[tuple[str, str]],
    eodhd_path: Path | None = None,
    verified_path: Path = VERIFIED_READINGS_PATH,
) -> dict[str, Any]:
    """Re page-read specific filings identified by (store key, fiscal_year_end)."""
    listing = json.loads(leaver_path.read_text(encoding="utf-8"))
    records = list(listing.get("names") or [])
    records_by_key = {row["key"]: row for row in records}
    payload = load_store(store_path)
    done = {str(n.get("key")): n for n in payload.get("names") or [] if n.get("key")}
    verified = load_verified_readings(verified_path)
    eodhd = load_eodhd_report(eodhd_path or Path("docs/data/eodhd_coverage_check.json"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    for key, fiscal_year_end in targets:
        row = done.get(key)
        if not row:
            continue
        record = records_by_key.get(key) or CH_NAME_BY_KEY.get(key) or {}
        company_number = str(row.get("company_number") or record.get("company_number") or "")
        if not company_number:
            continue
        metas = list_aa_filings(company_number, api_key)
        work_filing = None
        meta = None
        for filing in row.get("filings") or []:
            if str(filing.get("fiscal_year_end") or "") == fiscal_year_end:
                work_filing = filing
                tx = str(filing.get("transaction_id") or "")
                meta = next((m for m in metas if str(m.get("transaction_id")) == tx), None)
                break
        if work_filing is None or meta is None:
            continue
        work_filing.setdefault("fields", {})["shares_in_issue"] = _empty_field(None, source="primary")
        page_read_filing_shares(
            work_filing,
            key=key,
            meta=meta,
            api_key=api_key,
            cache_dir=cache_dir,
            verified=verified,
            force=True,
        )
        apply_shares_precision_to_filings([work_filing], ftse_member=True)
        done[key] = row
        payload = assemble_store(done, records, eodhd_payload=eodhd)
        write_store(payload, store_path)
    return assemble_store(done, records, eodhd_payload=eodhd)


def withhold_failed_semantic_takeovers(
    store: dict[str, Any],
    *,
    cache_dir: Path,
) -> list[dict[str, Any]]:
    """Null takeover ``shares_in_issue`` values that fail the semantic hand check."""
    import importlib.util
    import sys

    script = Path(__file__).resolve().parents[2] / "scripts" / "ch_shares_hand_check.py"
    spec = importlib.util.spec_from_file_location("ch_shares_hand_check", script)
    if spec is None or spec.loader is None:
        return []
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ch_shares_hand_check"] = mod
    spec.loader.exec_module(mod)
    misses: list[dict[str, Any]] = []
    pool = mod.candidates(store)
    for row in pool:
        if row.get("reason_class") != "takeover":
            continue
        cmp = mod.compare(row, cache_dir)
        if cmp["match"]:
            continue
        misses.append({**row, "detail": cmp.get("detail")})
        name = next(n for n in store["names"] if n["key"] == row["key"])
        for filing in name.get("filings") or []:
            if filing.get("fiscal_year") != row["year"]:
                continue
            blocks = [filing.get("fields") or {}]
            comp = filing.get("comparative") or {}
            if comp.get("fiscal_year") == row["year"] and comp.get("fields"):
                blocks.append(comp["fields"])
            for fields in blocks:
                sh = fields.get("shares_in_issue") or {}
                if sh.get("value") in (None, ""):
                    continue
                sh["nulled_from"] = sh.get("value")
                sh["value"] = None
                sh["absent_reason"] = f"semantic hand-check miss: {cmp.get('detail')}"
    return misses