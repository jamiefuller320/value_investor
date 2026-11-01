"""CLI: L632 one-shot lifecycle exit_reason / entry trail backfill."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.lifecycle_exit_reason_backfill import run_l632_backfill


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "L632: refresh N200/N201/N206 observe stores so lifecycle_episodes "
            "rewrite exit_reason (closed) and entry_detail/entry_reason (open+closed). "
            "Observe-only — no live capital writes."
        )
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("docs/data"),
        help="Committed data root (default: docs/data)",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Score/refresh without writing observe stores",
    )
    parser.add_argument(
        "--ftse-only",
        action="store_true",
        help="Skip admitted-market panels on N201/N206 (faster)",
    )
    parser.add_argument("--json", action="store_true", help="Print coverage JSON")
    args = parser.parse_args(argv)

    report = run_l632_backfill(
        args.data_dir,
        persist=not args.no_persist,
        include_admitted_markets=not args.ftse_only,
    )
    if args.json:
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
    else:
        for row in report.get("strands") or []:
            before = row.get("before") or {}
            after = row.get("after") or {}
            sys.stdout.write(
                f"{row.get('strand')}: closed_blank_exit "
                f"{before.get('closed_blank_exit_reason')}→{after.get('closed_blank_exit_reason')}; "
                f"open_missing_entry "
                f"{before.get('open_missing_entry_trail')}→{after.get('open_missing_entry_trail')}; "
                f"lifecycle_n {after.get('lifecycle_n')}\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
