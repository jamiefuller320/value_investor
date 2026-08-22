#!/usr/bin/env python3
"""Enable/disable euro_depth ingest + weekday ladder crons from dispatch state."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.euro_depth_ingest_dispatch import (
    DEFAULT_DISPATCH_PATH,
    evaluate_euro_ingest_dispatch,
    load_euro_ingest_dispatch,
    refresh_euro_ingest_dispatch,
)
from value_investor.euro_ingest_cron_sync import sync_euro_ingest_cron_jobs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync euro_depth cron jobs from dispatch gate")
    parser.add_argument(
        "--dispatch-path",
        type=Path,
        default=DEFAULT_DISPATCH_PATH,
        help="Path to persisted dispatch JSON",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-evaluate completion gate before syncing",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.refresh:
        evaluation = refresh_euro_ingest_dispatch(
            dispatch_path=args.dispatch_path,
            sync_cron=not args.dry_run,
        )
        result = evaluation.get("cron_sync") or sync_euro_ingest_cron_jobs(
            evaluation, dry_run=args.dry_run
        )
    else:
        evaluation = load_euro_ingest_dispatch(path=args.dispatch_path)
        if evaluation is None:
            evaluation = evaluate_euro_ingest_dispatch()
        result = sync_euro_ingest_cron_jobs(evaluation, dry_run=args.dry_run)
    if args.json:
        print(json.dumps({"evaluation": evaluation, "sync": result}, indent=2))
    else:
        print(f"mode={evaluation.get('mode')} reason={evaluation.get('reason')}")
        for row in result.get("results") or []:
            print(f"  {row}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
