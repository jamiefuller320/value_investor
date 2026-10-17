"""Fetch one missing FTSE annual statement through the existing Yahoo path.

``ingest_research_sources`` already writes ``financials_annual.json`` from
``fetch_annual_financials`` (yfinance). This module is that path for a single
ticker the gap scan says has no annual statement. It does not walk the list.

Pass ``sources_dir`` to write the file the same way ingest does. Omit it for a
dry run: the payload comes back and nothing is written. yfinance needs no API key.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from value_investor.storage import write_json

StatementFetcher = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class StatementFetch:
    ticker: str
    payload: dict[str, Any]
    written: Path | None
    dry_run: bool


def fetch_one_annual_statement(
    ticker: str,
    *,
    sources_dir: Path | None = None,
    fetcher: StatementFetcher | None = None,
) -> StatementFetch:
    """Fetch annual statements for one ticker.

    ``sources_dir`` None is a dry run. A path writes ``financials_annual.json``
    there, which is the file ``ingest_research_sources`` writes. The default
    fetcher is ``fetch_annual_financials`` (yfinance, no API key).
    """

    resolved = str(ticker).strip()
    if not resolved:
        raise ValueError("ticker is required; this fetch does not walk the FTSE list")
    if fetcher is None:
        from value_investor.research.ingest import fetch_annual_financials

        fetcher = fetch_annual_financials
    payload = fetcher(resolved)
    written: Path | None = None
    if sources_dir is not None:
        written = write_json(
            Path(sources_dir) / "financials_annual.json",
            payload,
            compact=True,
            compress=False,
        )
    return StatementFetch(
        ticker=resolved,
        payload=payload,
        written=written,
        dry_run=sources_dir is None,
    )


def statement_key_summary(payload: dict[str, Any]) -> dict[str, int]:
    """Count stored year keys. Does not add or rescale a figure."""

    summary: dict[str, int] = {}
    for key in ("income_statement", "balance_sheet", "cash_flow"):
        block = payload.get(key)
        summary[key] = len(block) if isinstance(block, dict) else 0
    return summary
