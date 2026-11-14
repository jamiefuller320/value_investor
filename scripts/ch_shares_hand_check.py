#!/usr/bin/env python3
"""Sample shares_in_issue and verify year-end issued ordinary share totals."""

from __future__ import annotations

import argparse
import json
import random
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import re

from value_investor.ch_failed_name_statements import (
    _DIVIDED_INTO_ORDINARY_RE,
    CACHE_VERSION,
    StatementPage,
    _share_count_units,
    citation_supports,
    parse_share_supplement,
    shares_context_accepted,
    shares_context_rejected,
)


def candidates(store: dict) -> list[dict]:
    rows = []
    reasons = {str(n.get("key")): n.get("reason_class") for n in store.get("names") or []}
    for name in store.get("names") or []:
        key = str(name.get("key"))
        for filing in name.get("filings") or []:
            year = filing.get("fiscal_year")
            blocks = [(year, filing.get("fields") or {}, filing)]
            comp = filing.get("comparative") or {}
            if comp.get("fields"):
                blocks.append((comp.get("fiscal_year"), comp["fields"], filing))
            for fy, fields, parent in blocks:
                row = fields.get("shares_in_issue") or {}
                if row.get("value") in (None, ""):
                    continue
                cit = row.get("citation") or {}
                if str(row.get("source")) == "ch_statement_of_capital":
                    rows.append(
                        {
                            "key": key,
                            "reason_class": reasons.get(key),
                            "year": fy,
                            "stored": row.get("value"),
                            "scale": row.get("scale"),
                            "line": cit.get("line"),
                            "page": cit.get("page"),
                            "method": cit.get("method"),
                            "fiscal_year_end": parent.get("fiscal_year_end"),
                            "made_up": parent.get("made_up"),
                            "transaction_id": parent.get("transaction_id"),
                            "source": row.get("source"),
                        }
                    )
                    continue
                if not cit.get("line"):
                    continue
                rows.append(
                    {
                        "key": key,
                        "reason_class": reasons.get(key),
                        "year": fy,
                        "stored": row.get("value"),
                        "scale": row.get("scale"),
                        "line": cit.get("line"),
                        "page": cit.get("page"),
                        "method": cit.get("method"),
                        "fiscal_year_end": parent.get("fiscal_year_end"),
                        "made_up": parent.get("made_up"),
                        "transaction_id": parent.get("transaction_id"),
                        "source": row.get("source"),
                    }
                )
    return rows


def pdf_path(sample: dict, cache_dir: Path) -> Path | None:
    key = str(sample["key"])
    for end in (sample.get("fiscal_year_end"), sample.get("made_up")):
        if not end:
            continue
        path = cache_dir / f"{key}_{end}.pdf"
        if path.is_file():
            return path
    return None


def pdf_page_text(pdf: Path, page: int) -> str:
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


def page_text_for_sample(sample: dict, cache_dir: Path) -> str:
    if sample.get("source") == "ch_statement_of_capital":
        return str(sample.get("line") or "")
    pdf = pdf_path(sample, cache_dir)
    page = sample.get("page")
    if pdf is None or not isinstance(page, int):
        return ""
    text = pdf_page_text(pdf, page)
    if len(text.strip()) < 40:
        ocr = ocr_page_text(cache_dir, str(sample.get("transaction_id") or ""), page)
        if ocr:
            return ocr
    if text.strip():
        return text
    return ocr_page_text(cache_dir, str(sample.get("transaction_id") or ""), page)


def year_end_unit_counts_on_page(text: str, sample: dict) -> list[Decimal]:
    """All year-end ordinary share totals the note parser accepts on this page."""
    end = str(sample.get("fiscal_year_end") or f"{sample.get('year')}-12-31")
    found: list[Decimal] = []
    supplement = parse_share_supplement(
        [StatementPage(page=int(sample.get("page") or 1), text=text, method="hand_check")],
        fiscal_year_end=end,
        filing_date=end,
        transaction_id=str(sample.get("transaction_id") or "hand-check"),
    )
    row = (supplement.get("primary") or {}).get("shares_in_issue") or {}
    if row.get("value") not in (None, ""):
        units = _share_count_units(row["value"], row.get("scale"))
        if units is not None:
            found.append(units)
    for match in _DIVIDED_INTO_ORDINARY_RE.finditer(text):
        raw = re.sub(r"[\s,]", "", match.group(1))
        if raw.isdigit():
            found.append(Decimal(raw))
    return list(dict.fromkeys(found))


def semantic_year_end_count(sample: dict, text: str) -> dict | None:
    if sample.get("source") == "ch_statement_of_capital":
        return {
            "value": str(sample.get("stored")),
            "scale": sample.get("scale") or "units",
        }
    if not text.strip():
        return None
    counts = year_end_unit_counts_on_page(text, sample)
    if counts:
        return {"value": str(int(counts[0])), "scale": "units"}
    return None


def compare(sample: dict, cache_dir: Path) -> dict:
    text = page_text_for_sample(sample, cache_dir)
    try:
        stored_u = _share_count_units(sample["stored"], sample.get("scale"))
    except Exception:
        return {"match": False, "detail": "scale parse error"}
    if stored_u is None:
        return {"match": False, "detail": "missing units"}
    counts = year_end_unit_counts_on_page(text, sample)
    if not counts and not text.strip():
        line = str(sample.get("line") or "")
        if (
            line
            and not shares_context_rejected("", line)
            and shares_context_accepted("", line, line)
        ):
            try:
                ok, _, _ = citation_supports(Decimal(str(sample["stored"]).replace(",", "")), line)
            except Exception:
                ok = False
            if ok:
                return {
                    "match": True,
                    "detail": "citation is year-end ordinary (page text unavailable)",
                }
    if not counts:
        return {"match": False, "detail": "no year-end issued ordinary total on page"}
    if stored_u in counts:
        detail = "year-end issued ordinary shares"
        return {"match": True, "detail": detail}
    return {
        "match": False,
        "detail": f"stored {stored_u} not among note totals {[str(int(c)) for c in counts[:3]]}",
    }


def stratified_draw(
    pool: list[dict], *, count: int, seed: int, min_non_takeover: int = 5
) -> list[dict]:
    failure_other = [row for row in pool if row.get("reason_class") in {"failure", "other"}]
    takeover = [row for row in pool if row.get("reason_class") == "takeover"]
    rng = random.Random(seed)
    need = min(min_non_takeover, count, len(failure_other))
    picked = rng.sample(failure_other, need) if len(failure_other) >= need else list(failure_other)
    rest = count - len(picked)
    if rest > 0 and takeover:
        picked.extend(rng.sample(takeover, rest) if len(takeover) >= rest else takeover[:rest])
    if len(picked) < count:
        remainder = [row for row in pool if row not in picked]
        extra = count - len(picked)
        picked.extend(rng.sample(remainder, extra) if len(remainder) >= extra else remainder)
    return picked[:count]


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
    pool = [
        row
        for row in candidates(store)
        if row.get("source") == "ch_statement_of_capital" or pdf_path(row, args.cache_dir)
    ]
    if not pool:
        print("no candidates")
        return 1
    draw = stratified_draw(pool, count=args.count, seed=args.seed)
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
