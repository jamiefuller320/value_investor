"""Deepen historical filing sources for tickers that already have research memos.

Forward-only: enriches ``sources/filings`` (Companies House accounts years, RNS
bodies). Does **not** fabricate backdated research revisions for past paper
decisions (that would lookahead-poison the learning track).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.research.ingest import ingest_research_sources
from value_investor.research.store import ResearchStore
from value_investor.storage import write_json

logger = logging.getLogger(__name__)


@dataclass
class DeepenSourcesResult:
    tickers: list[str] = field(default_factory=list)
    deepened: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tickers": self.tickers,
            "deepened": self.deepened,
            "skipped": self.skipped,
            "errors": self.errors,
            "note": (
                "Historical source deepen for memo tickers — forward learning only; "
                "research revisions are not backdated."
            ),
        }


def deepen_sources_for_memo_tickers(
    *,
    output_dir: Path,
    tickers: list[str] | None = None,
    market: str = "ftse350",
) -> DeepenSourcesResult:
    """
    Re-ingest filings with ``deepen_history=True`` for existing memo tickers.

    Pulls up to five Companies House accounts filings (+ RNS/PDF bodies) so
    FINANCIAL REVIEW / gap-fill have multi-year statutory depth.
    """
    store = ResearchStore(output_dir)
    result = DeepenSourcesResult()
    if tickers:
        wanted = [t.strip().upper() for t in tickers if t.strip()]
    else:
        wanted = [doc.ticker.upper() for doc in store.list_documents()]
    result.tickers = wanted

    for ticker in wanted:
        doc = store.load(ticker)
        if doc is None:
            result.skipped.append(ticker)
            continue
        sources_dir = store.sources_dir(ticker)
        try:
            meta = ingest_research_sources(
                ticker=ticker,
                company_name=doc.name,
                screening_snapshot={
                    "ticker": ticker,
                    "name": doc.name,
                    "signal": doc.signal,
                },
                sources_dir=sources_dir,
                since=None,
                market=market,
                deepen_history=True,
            )
            filings = meta.get("filings_summary") or {}
            result.deepened.append(
                {
                    "ticker": ticker,
                    "filings_total": filings.get("total"),
                    "filings_with_body": filings.get("with_body"),
                    "filings_annual": filings.get("annual"),
                    "deepened_at": datetime.now(UTC).isoformat(),
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Deepen sources failed for %s: %s", ticker, exc)
            result.errors.append(f"{ticker}: {exc}")

    write_json(
        Path(output_dir) / "deepen_sources_summary.json",
        {"run_at": datetime.now(UTC).isoformat(), **result.to_dict()},
        compact=False,
    )
    return result
