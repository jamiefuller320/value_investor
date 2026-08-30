#!/usr/bin/env python3
"""Force-initial rememo for published adequate-grade tickers using thickened sources."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from value_investor.cursor_api_key import resolve_cursor_api_key
from value_investor.research.memo_backfill import publish_memo_backfill_batch
from value_investor.research.runner import _process_ticker
from value_investor.research.store import ResearchStore
from value_investor.storage import write_json
from value_investor.summary import CompanyReport

LOG = logging.getLogger("rememo_adequate")


def _load_reports(latest_path: Path) -> list[CompanyReport]:
    payload = json.loads(latest_path.read_text(encoding="utf-8"))
    reports: list[CompanyReport] = []
    for row in payload.get("reports") or []:
        if not isinstance(row, dict):
            continue
        try:
            reports.append(CompanyReport.from_dict(row))
        except Exception:  # noqa: BLE001
            continue
    if reports:
        return reports
    # Fallback: research entries alone lack full report fields — load screening from sources.
    return []


def _report_for_ticker(ticker: str, latest_path: Path, sources_dir: Path) -> CompanyReport | None:
    payload = json.loads(latest_path.read_text(encoding="utf-8"))
    for row in payload.get("reports") or []:
        if isinstance(row, dict) and str(row.get("ticker") or "") == ticker:
            return CompanyReport.from_dict(row)
    snap = sources_dir / "screening_snapshot.json"
    if snap.exists():
        data = json.loads(snap.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("ticker"):
            return CompanyReport.from_dict(data)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest-path", type=Path, default=Path("docs/data/latest.json"))
    parser.add_argument("--committed-dir", type=Path, default=Path("docs/data/research"))
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--dest-dir", type=Path, default=Path("docs"))
    parser.add_argument("--market", default="ftse350")
    parser.add_argument("--model", default="composer-2.5")
    parser.add_argument("--tickers", default="", help="Comma-separated override; default=adequate in latest")
    parser.add_argument("--summary-path", type=Path, default=Path("docs/data/rememo_adequate_summary.json"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    api_key, _source = resolve_cursor_api_key()
    if not api_key and not args.dry_run:
        LOG.error("CURSOR_API_KEY / CURSOR_API_KEY_V2 required")
        return 2

    latest = json.loads(args.latest_path.read_text(encoding="utf-8"))
    if args.tickers.strip():
        tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = [
            str(row["ticker"])
            for row in latest.get("research") or []
            if (row.get("memo_quality") or {}).get("grade") == "adequate"
        ]

    summary: dict = {
        "run_at": datetime.now(UTC).isoformat(),
        "tickers": tickers,
        "rememoed": [],
        "errors": [],
        "grades_before": {},
        "grades_after": {},
        "dry_run": bool(args.dry_run),
    }
    for row in latest.get("research") or []:
        if row.get("ticker") in tickers:
            mq = row.get("memo_quality") or {}
            summary["grades_before"][row["ticker"]] = {
                "grade": mq.get("grade"),
                "score": mq.get("source_quality_score"),
                "bodies": f"{mq.get('filings_with_body')}/{mq.get('filings_total')}",
            }

    if args.dry_run:
        write_json(args.summary_path, summary)
        print(json.dumps(summary, indent=2))
        return 0

    store = ResearchStore(args.output_dir)
    run_at = datetime.now(UTC)

    for ticker in tickers:
        committed = args.committed_dir / ticker
        out_ticker = args.output_dir / "research" / ticker
        if not committed.exists():
            summary["errors"].append(f"{ticker}: missing committed research dir")
            continue
        if out_ticker.exists():
            shutil.rmtree(out_ticker)
        shutil.copytree(committed, out_ticker)
        # Drop existing memo so force_initial path is clean, keep sources.
        for name in ("research.json", "research.md", "agent_id.txt"):
            path = out_ticker / name
            if path.exists():
                path.unlink()

        report = _report_for_ticker(ticker, args.latest_path, out_ticker / "sources")
        if report is None:
            summary["errors"].append(f"{ticker}: could not build CompanyReport")
            continue

        LOG.info("Rememoing %s …", ticker)
        try:
            doc, action = _process_ticker(
                report=report,
                store=store,
                api_key=api_key or "",
                model=args.model,
                cwd=str(Path.cwd()),
                force_initial=True,
                run_at=run_at,
                market=args.market,
            )
            mq = doc.memo_quality or {}
            summary["rememoed"].append(ticker)
            summary["grades_after"][ticker] = {
                "grade": mq.get("grade"),
                "score": mq.get("source_quality_score"),
                "bodies": f"{mq.get('filings_with_body')}/{mq.get('filings_total')}",
                "action": action,
                "thin_gaps": mq.get("thin_gaps"),
            }
            LOG.info(
                "Done %s grade=%s score=%s bodies=%s",
                ticker,
                mq.get("grade"),
                mq.get("source_quality_score"),
                summary["grades_after"][ticker]["bodies"],
            )
            # Persist partial summary after each ticker.
            write_json(args.summary_path, summary)
            # Sync committed store + published markdown / latest overlay.
            publish_memo_backfill_batch(
                args.output_dir,
                dest_dir=args.dest_dir,
                latest_path=args.dest_dir / "data" / "latest.json",
            )
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Rememo failed for %s", ticker)
            summary["errors"].append(f"{ticker}: {exc}")
            write_json(args.summary_path, summary)

    write_json(args.summary_path, summary)
    print(json.dumps(summary, indent=2))
    return 1 if summary["errors"] and not summary["rememoed"] else 0


if __name__ == "__main__":
    sys.exit(main())
