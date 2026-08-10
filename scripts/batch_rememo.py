#!/usr/bin/env python3
"""Force-initial research memos for all tickers in output/research/."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from value_investor.cursor_api_key import resolve_cursor_api_key
from value_investor.research.runner import _process_ticker
from value_investor.research.store import ResearchStore
from value_investor.summary import build_company_reports

TICKERS = sorted(
    p.name for p in Path("output/research").iterdir() if p.is_dir() and p.name.endswith(".L")
)


def main() -> int:
    signals = pd.read_csv("output/latest_signals.csv")
    model_results = pd.read_csv("output/latest_model_results.csv")
    reports = {r.ticker: r for r in build_company_reports(signals, model_results)}
    api_key, _ = resolve_cursor_api_key()
    if not api_key:
        raise SystemExit("No CURSOR API key")

    store = ResearchStore(Path("output"))
    errors: list[str] = []
    for ticker in TICKERS:
        report = reports.get(ticker)
        if not report:
            print(f"SKIP {ticker}: not in screen")
            continue
        print(f"=== {ticker} ===", flush=True)
        try:
            doc, action = _process_ticker(
                report=report,
                store=store,
                api_key=api_key,
                model="composer-2.5",
                cwd=None,
                force_initial=True,
                run_at=datetime.now(UTC),
                market="ftse350",
            )
            print(
                f"  {action} v{doc.version} bodies={doc.source_counts.get('filings_with_body')}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            msg = f"{ticker}: {exc}"
            print(f"  ERROR {msg}", flush=True)
            errors.append(msg)
    print(f"DONE errors={len(errors)}", flush=True)
    for err in errors:
        print(f"  ! {err}", flush=True)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
