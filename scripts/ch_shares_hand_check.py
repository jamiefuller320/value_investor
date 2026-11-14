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

from value_investor.ch_failed_name_statements import _significant_digits, citation_supports


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


def compare(sample: dict, cache_dir: Path) -> dict:
    end = str(sample.get("fiscal_year_end") or "")
    pdf = cache_dir / f"{sample['key']}_{end}.pdf"
    page = sample.get("page")
    stored = str(sample["stored"])
    line = str(sample["line"])
    result = {"match": False, "detail": "no PDF" if not pdf.is_file() else ""}
    if not pdf.is_file():
        return result
    if sample.get("method") == "ixbrl":
        ok, _, _ = citation_supports(Decimal(stored.replace(",", "")), line)
        result["match"] = ok
        result["detail"] = f"iXBRL tag {line[:80]}"
        return result
    if not isinstance(page, int):
        result["detail"] = "no page"
        return result
    text = pdf_text(pdf, page)
    shortened = _short_fragment(line)
    line_on_page = shortened and shortened in _prepare(text)
    ok, _, _ = citation_supports(Decimal(str(stored).replace(",", "")), line)
    if line_on_page and ok:
        result["match"] = True
        result["detail"] = "cited line on page"
    elif ok and shortened and any(ok for _ in [1] if shortened[:20] in _prepare(text)):
        result["match"] = True
        result["detail"] = "label on page, digits match citation"
    else:
        result["match"] = False
        result["detail"] = "cited line not on page" if not line_on_page else "digit mismatch"
    return result


def _prepare(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


def _short_fragment(line: str) -> str:
    parts = re.split(r"\d", line, maxsplit=1)
    return parts[0].strip()[:48].lower()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", type=Path, default=Path("docs/data/ch_failed_name_statements.json"))
    parser.add_argument("--cache-dir", type=Path, default=Path("/tmp/ch-pdfs"))
    parser.add_argument("--seed", type=int, default=20261114)
    parser.add_argument("--count", type=int, default=20)
    args = parser.parse_args()
    store = json.loads(args.store.read_text(encoding="utf-8"))
    pool = candidates(store)
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