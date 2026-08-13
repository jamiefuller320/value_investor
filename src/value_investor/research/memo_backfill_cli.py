"""CLI for batched buy-tier memo backfill and legacy re-memo."""

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
    DEFAULT_LEGACY_REMEMO_STATE_PATH,
    DEFAULT_LATEST_PATH,
    DEFAULT_STATE_PATH,
    list_legacy_rememo_reports,
    list_missing_memo_reports,
    load_backfill_state,
    load_buy_tier_reports,
    run_legacy_rememo_pass,
    run_missing_memo_backfill,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Batch-create initial research memos for buy-tier names with ingest "
            "but no published memo, or re-memo legacy markdown without canonical JSON"
        ),
    )
    parser.add_argument("--latest-path", type=Path, default=DEFAULT_LATEST_PATH)
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--dest-dir", type=Path, default=Path("docs"))
    parser.add_argument("--state-path", type=Path, default=None)
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Max memos per invocation (default: {DEFAULT_BATCH_SIZE})",
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
    parser.add_argument("--rememo-legacy", action="store_true", help="Re-memo markdown-only legacy names")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true", help="Show backlog counts")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--no-publish",
        action="store_true",
        help="Skip docs/research + latest.json merge after creating memos",
    )
    parser.add_argument(
        "--rebuild-index",
        action="store_true",
        help="When legacy backlog empties, rebuild full research index from committed stores",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    committed = Path("docs/data/research")
    memo_dir = args.dest_dir / "research"
    reports = load_buy_tier_reports(args.latest_path)
    missing = list_missing_memo_reports(
        reports,
        memo_dir=memo_dir,
        committed_dir=committed,
        output_dir=args.output_dir,
    )
    legacy = list_legacy_rememo_reports(
        reports,
        memo_dir=memo_dir,
        committed_dir=committed,
        output_dir=args.output_dir,
    )

    state_path = args.state_path or (
        DEFAULT_LEGACY_REMEMO_STATE_PATH if args.rememo_legacy else DEFAULT_STATE_PATH
    )

    if args.status:
        payload = {
            "buy_tier": len(reports),
            "missing_memos": len(missing),
            "legacy_rememo": len(legacy),
            "missing_tickers": [report.ticker for report in missing],
            "legacy_tickers": [report.ticker for report in legacy],
            "state": load_backfill_state(state_path),
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"Buy-tier: {payload['buy_tier']}")
            print(f"Missing memos: {payload['missing_memos']}")
            print(f"Legacy re-memo needed: {payload['legacy_rememo']}")
            if legacy:
                print("Legacy:", ", ".join(payload["legacy_tickers"][:20]))
                if len(legacy) > 20:
                    print(f"  … and {len(legacy) - 20} more")
        return 0

    if args.dry_run:
        if args.rememo_legacy:
            summary = run_legacy_rememo_pass(
                latest_path=args.latest_path,
                output_dir=args.output_dir,
                state_path=state_path,
                batch_size=args.batch_size,
                api_key=args.api_key or "",
                dry_run=True,
                dest_dir=args.dest_dir,
            )
        else:
            summary = run_missing_memo_backfill(
                latest_path=args.latest_path,
                output_dir=args.output_dir,
                state_path=state_path,
                batch_size=args.batch_size,
                api_key=args.api_key or "",
                dry_run=True,
                dest_dir=args.dest_dir,
            )
        if args.json:
            print(json.dumps(summary.to_dict(), indent=2))
        else:
            label = "Re-memo" if args.rememo_legacy else "Create"
            print(f"Would {label.lower()} {len(summary.selected)}: {', '.join(summary.selected)}")
            print(f"Remaining after batch: {len(summary.remaining)}")
        return 0

    if not args.api_key:
        print("CURSOR_API_KEY required for memo backfill", file=sys.stderr)
        return 1

    model = args.model or os.environ.get("CURSOR_RESEARCH_MODEL") or "composer-2.5"
    print(f"Research model: {model}")

    if args.rememo_legacy:
        print(f"Legacy re-memo before batch: {len(legacy)}")
        summary = run_legacy_rememo_pass(
            latest_path=args.latest_path,
            output_dir=args.output_dir,
            state_path=state_path,
            batch_size=args.batch_size,
            api_key=args.api_key,
            model=model,
            publish=not args.no_publish,
            dest_dir=args.dest_dir,
            rebuild_index=args.rebuild_index,
        )
        created_label = "Re-memoed"
    else:
        print(f"Missing memos before batch: {len(missing)}")
        summary = run_missing_memo_backfill(
            latest_path=args.latest_path,
            output_dir=args.output_dir,
            state_path=state_path,
            batch_size=args.batch_size,
            api_key=args.api_key,
            model=model,
            publish=not args.no_publish,
            dest_dir=args.dest_dir,
        )
        created_label = "Created"

    if args.json:
        print(json.dumps(summary.to_dict(), indent=2))
    else:
        print(f"{created_label} {len(summary.created)}: {', '.join(summary.created) or '—'}")
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
