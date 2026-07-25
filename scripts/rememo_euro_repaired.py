#!/usr/bin/env python3
"""Re-memo Euro tickers after filing body repair."""

from __future__ import annotations

from pathlib import Path

from value_investor.cursor_api_key import resolve_cursor_api_key
from value_investor.library_maintenance import (
    _company_name_for_memo,
    _filings_body_count,
    deepen_library_research_memos,
)
from value_investor.data_library import market_dir


def main() -> int:
    root = Path("docs/data/library")
    market = "euro_stoxx50"
    tickers = ["TTE.PA", "MC.PA", "SAP.DE"]
    targets = []
    for ticker in tickers:
        ticker_dir = market_dir(root, market) / "screen" / "research" / ticker
        sources_dir = ticker_dir / "sources"
        targets.append(
            {
                "market": market,
                "ticker": ticker,
                "company_name": _company_name_for_memo(ticker_dir, ticker),
                "sources_dir": sources_dir,
                "screen_dir": market_dir(root, market) / "screen",
                "bodies_before": _filings_body_count(sources_dir),
                "reasons": ["euro_body_repair"],
            }
        )

    key = resolve_cursor_api_key()[0]
    if not key:
        raise SystemExit("CURSOR_API_KEY_V2 / CURSOR_API_KEY required")

    payload = deepen_library_research_memos(root, targets, api_key=key, rememo_all=True)
    print(
        f"targets={payload['target_count']} rememoed={payload['rememoed']} "
        f"errors={len(payload.get('errors') or [])}"
    )
    for row in payload.get("results") or []:
        print(
            f"  {row['ticker']}: bodies {row.get('bodies_before')}→{row.get('bodies_after')} "
            f"rememo_action={row.get('rememo_action')} version={row.get('rememo_version')}"
        )
        if row.get("error"):
            print(f"    ERROR: {row['error']}")
    return 0 if not payload.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())
