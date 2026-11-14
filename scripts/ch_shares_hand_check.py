#!/usr/bin/env python3
"""Sample shares_in_issue rows and compare stored values to PDF text on the cited page."""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from value_investor.ch_failed_name_statements import CACHE_VERSION, citation_supports


def candidates(store: dict) -> list[dict]:
    rows = []
    for name in store.get("names") or []:
        key = str(name.get("key"))
        for filing in name.get("filings") or []:
            year = filing.get("fiscal_year")
            blocks = [(year, filing.get("fields") or {})]
            comp = filing.get("comparative") or {}
            if comp.get("fields"):
                blocks.append((comp.get("fiscal_year"), comp["fields"]))
            for fy, fields in blocks:
                row = fields.get("shares_in_issue") or {}
                if row.get("value") in (None, ""):
                    continue
                cit = row.get("citation") or {}
                if not cit.get("line"):
                    continue
                rows.append(
                    {
                        "key": key,
                        "name": name.get("name"),
                        "year": fy,
                        "field": "shares_in_issue",
                        "stored": row.get("value"),
                        "scale": row.get("scale"),
                        "line": cit.get("line"),
                        "page": cit.get("page"),
                        "method": cit.get("method"),
                        "fiscal_year_end": filing.get("fiscal_year_end"),
                        "made_up": filing.get("made_up"),
                        "transaction_id": filing.get("transaction_id"),
                    }
                )
    return rows


def pdf_text(pdf: Path, page: int) -> str:
    import pymupdf

    doc = pymupdf.open(pdf)
    try:
        if page < 1 or page > doc.page_count:
            return ""
        return doc[page - 1].get_text("text") or ""
    finally:
        doc.close()


def ocr_page_text(cache_dir: Path, transaction_id: str, page: int) -> str:
    if not transaction_id or not isinstance(page, int) or page < 1:
        return ""
    for zoom in (2.2, 2.0, 1.6):
        base = cache_dir / f"ocr-v{CACHE_VERSION}-z{zoom:.1f}" / transaction_id
        for name in (f"share-p{page}.json", f"p{page}.json"):
            path = base / name
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            lines = data.get("lines")
            if isinstance(lines, list):
                return "\n".join(str(line) for line in lines)
    return ""


def pdf_path(sample: dict, cache_dir: Path) -> Path | None:
    key = str(sample["key"])
    for end in (sample.get("fiscal_year_end"), sample.get("made_up")):
        if not end:
            continue
        path = cache_dir / f"{key}_{end}.pdf"
        if path.is_file():
            return path
    return None


def compare(sample: dict, cache_dir: Path) -> dict:
    pdf = pdf_path(sample, cache_dir)
    page = sample.get("page")
    stored = str(sample["stored"])
    line = str(sample["line"])
    result = {"match": False, "detail": "no PDF" if pdf is None else ""}
    if pdf is None:
        return result
    if sample.get("method") == "ixbrl":
        ok, _, _ = citation_supports(Decimal(stored.replace(",", "")), line)
        result["match"] = ok
        result["detail"] = f"iXBRL tag {line[:80]}"
        return result
    if not isinstance(page, int):
        result["detail"] = "no page"
        return result
    shortened = _short_fragment(line)
    text = pdf_text(pdf, page)
    ocr = ""
    if len(text.strip()) < 40:
        ocr = ocr_page_text(cache_dir, str(sample.get("transaction_id") or ""), page)
        if ocr:
            text = ocr
    elif sample.get("transaction_id"):
        ocr = ocr_page_text(cache_dir, str(sample["transaction_id"]), page)
        if ocr and shortened and shortened not in _prepare(text):
            text = text + "\n" + ocr
    line_on_page = shortened and shortened in _prepare(text)
    ok, _, _ = citation_supports(Decimal(str(stored).replace(",", "")), line)
    if line_on_page and ok:
        result["match"] = True
        result["detail"] = "cited line on page" + (
            " (OCR)" if ocr and len(pdf_text(pdf, page).strip()) < 40 else ""
        )
    elif ok and shortened and shortened[:20] in _prepare(text):
        result["match"] = True
        result["detail"] = "label on page, digits match citation" + (" (OCR)" if ocr else "")
    elif ok and _citation_digits_on_page(stored, text):
        result["match"] = True
        result["detail"] = "digits on page/OCR match stored value"
    else:
        result["match"] = False
        result["detail"] = "cited line not on page" if not line_on_page else "digit mismatch"
    return result


def _citation_digits_on_page(stored: str, text: str) -> bool:
    prep = _prepare(text).replace(",", "")
    try:
        target = str(int(Decimal(str(stored).replace(",", ""))))
    except Exception:
        return False
    return target in prep or f"{target[:3]},{target[3:6]}" in text.replace(" ", "")


def _prepare(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


def _short_fragment(line: str) -> str:
    parts = re.split(r"\d", line, maxsplit=1)
    return parts[0].strip()[:48].lower()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--store", type=Path, default=Path("docs/data/ch_failed_name_statements.json")
    )
    parser.add_argument("--cache-dir", type=Path, default=Path("/tmp/ch-pdfs"))
    parser.add_argument("--seed", type=int, default=20261114)
    parser.add_argument("--count", type=int, default=20)
    args = parser.parse_args()
    store = json.loads(args.store.read_text(encoding="utf-8"))
    pool = [row for row in candidates(store) if pdf_path(row, args.cache_dir) is not None]
    if not pool:
        print("no candidates")
        return 1
    rng = random.Random(args.seed)
    draw = pool if len(pool) <= args.count else rng.sample(pool, args.count)
    matches = 0
    print("| Name | Year | Page | Stored | Result | Detail |")
    print("|------|------|------|--------|--------|--------|")
    for row in draw:
        cmp = compare(row, args.cache_dir)
        if cmp["match"]:
            matches += 1
        page = row.get("page") or "—"
        print(
            f"| {row['key']} | {row['year']} | {page} | {row['stored']} {row.get('scale') or ''} "
            f"| {'Match' if cmp['match'] else 'Miss'} | {cmp['detail']} |"
        )
    print(f"\n{matches}/{len(draw)} matched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
