#!/usr/bin/env python3
"""Backfill memo_quality scores on existing research memos without re-running agents."""

from __future__ import annotations

from pathlib import Path

from value_investor.research.source_quality import attach_memo_quality
from value_investor.research.store import ResearchStore


def main() -> int:
    store = ResearchStore(Path("output"))
    docs = store.list_documents()
    if not docs:
        print("No research memos found under output/research/")
        return 0

    updated = 0
    for doc in docs:
        attach_memo_quality(doc, sources_dir=store.sources_dir(doc.ticker))
        store.save(doc)
        score = (doc.memo_quality or {}).get("source_quality_score")
        grade = (doc.memo_quality or {}).get("grade")
        print(f"{doc.ticker}: {grade} ({score})")
        updated += 1

    print(f"Backfilled memo_quality for {updated} memos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
