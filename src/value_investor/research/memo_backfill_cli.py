"""CLI for batched buy-tier memo backfill."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from value_investor.cursor_api_key import resolve_cursor_api_key
from value_investor.research.memo_backfill import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_LATEST_PATH,
    DEFAULT_STATE_PATH,
    list_missing_memo_reports,
    load_backfill_state,
    load_buy_tier_reports,
    run_missing_memo_backfill,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Batch-create initial research memos for buy-tier names with ingest "
            "but no published memo (docs/research/*.md)"
        ),
    )
    parser.add_argument("--latest-path", type=Path, default=DEFAULT_LATEST_PATH)
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--dest-dir", type=Path, default=Path("docs"))
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Max new memos per invocation (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--api-key",
        default=(resolve_cursor_api_key()[0] or None),
        help="Cursor API key (default: CURSOR_API_KEY_V2 then CURSOR_API_KEY)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Cursor model (default: CURSOR_RESEARCH_MODEL or composer-2.5)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true", help="Show remaining missing memos")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--no-publish",
        action="store_true",
        help="Skip docs/research + latest.json merge after creating memos",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    reports = load_buy_tier_reports(args.latest_path)
    missing = list_missing_memo_reports(
        reports,
        memo_dir=args.dest_dir / "research",
        committed_dir=Path("docs/data/research"),
        output_dir=args.output_dir,
    )

    if args.status:
        payload = {
            "buy_tier": len(reports),
            "missing_memos": len(missing),
            "remaining_tickers": [report.ticker for report in missing],
            "state": load_backfill_state(args.state_path),
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"Buy-tier: {payload['buy_tier']}")
            print(f"Missing memos: {payload['missing_memos']}")
            if missing:
                print("Remaining:", ", ".join(payload["remaining_tickers"][:20]))
                if len(missing) > 20:
                    print(f"  … and {len(missing) - 20} more")
        return 0

    if args.dry_run:
        summary = run_missing_memo_backfill(
            latest_path=args.latest_path,
            output_dir=args.output_dir,
            state_path=args.state_path,
            batch_size=args.batch_size,
            api_key=args.api_key or "",
            dry_run=True,
            dest_dir=args.dest_dir,
        )
        if args.json:
            print(json.dumps(summary.to_dict(), indent=2))
        else:
            print(f"Would create {len(summary.selected)} memo(s): {', '.join(summary.selected)}")
            print(f"Remaining after batch: {len(summary.remaining)}")
        return 0

    if not args.api_key:
        print("CURSOR_API_KEY required for memo backfill", file=sys.stderr)
        return 1

    model = args.model or os.environ.get("CURSOR_RESEARCH_MODEL") or "composer-2.5"
    print(f"Research model: {model}")
    print(f"Missing memos before batch: {len(missing)}")

    summary = run_missing_memo_backfill(
        latest_path=args.latest_path,
        output_dir=args.output_dir,
        state_path=args.state_path,
        batch_size=args.batch_size,
        api_key=args.api_key,
        model=model,
        publish=not args.no_publish,
        dest_dir=args.dest_dir,
    )

    if args.json:
        print(json.dumps(summary.to_dict(), indent=2))
    else:
        print(
            f"Created {len(summary.created)} memo(s): {', '.join(summary.created) or '—'}"
        )
        if summary.skipped:
            print(f"Skipped: {', '.join(summary.skipped)}")
        if summary.errors:
            print("Errors:")
            for err in summary.errors:
                print(f"  ! {err}")
        print(f"Remaining: {len(summary.remaining)}")
        if summary.published:
            print(f"Published: {summary.published}")

    return 2 if summary.errors and not summary.created else 0


if __name__ == "__main__":
    sys.exit(main())
