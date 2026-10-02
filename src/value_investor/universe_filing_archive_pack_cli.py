"""CLI for the gated universe filing archive pack lane (week-first pass).

Production path is the weekday 22:00 UTC workflow. This CLI is for ad-hoc
drill-down and local dry/apply runs. Always consults ``archive_lane_gate``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.universe_filing_archive_isolation import (
    DEFAULT_DISPATCH_PATH,
    DEFAULT_MARKET_STATUS_PATH,
)
from value_investor.universe_filing_archive_pack_order import DEFAULT_LOOKBACK_WEEKS
from value_investor.universe_filing_archive_pack_run import (
    DEFAULT_BOTTLENECK_PATH,
    DEFAULT_PACK_RUN_PATH,
    DEFAULT_POLICY_PATH,
    format_bottleneck_review_summary,
    run_universe_filing_archive_pack,
)
from value_investor.universe_filing_archive_writer import (
    DEFAULT_APPLY_MAX_UNITS,
    DEFAULT_MAX_HTTP_FETCHES,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Universe filing archive pack lane: gate → week-first plan → "
            "dry or thin apply assemble → bottleneck review. Fail-open suspend "
            "under focus fat."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Thin quiet cold-store writers (archive budgets, tiny max_units "
            f"default {DEFAULT_APPLY_MAX_UNITS}; not a fourth equal sprint)"
        ),
    )
    parser.add_argument(
        "--allow-outside-quiet",
        action="store_true",
        help="Pilot escape hatch for daytime dry runs (still suspends on focus pressure)",
    )
    parser.add_argument(
        "--no-require-quiet",
        action="store_true",
        help="Do not require quiet window (still suspends on focus pressure)",
    )
    parser.add_argument(
        "--lookback-weeks",
        type=int,
        default=DEFAULT_LOOKBACK_WEEKS,
        help=f"ISO weeks to plan backward from current (default {DEFAULT_LOOKBACK_WEEKS})",
    )
    parser.add_argument(
        "--max-units",
        type=int,
        default=None,
        help=(
            "Cap on week×market coverage units "
            f"(apply default {DEFAULT_APPLY_MAX_UNITS} when omitted)"
        ),
    )
    parser.add_argument(
        "--max-http-fetches",
        type=int,
        default=DEFAULT_MAX_HTTP_FETCHES,
        help=f"Hard archive-lane HTTP fetch cap (default {DEFAULT_MAX_HTTP_FETCHES})",
    )
    parser.add_argument(
        "--dispatch-path",
        type=Path,
        default=DEFAULT_DISPATCH_PATH,
    )
    parser.add_argument(
        "--market-status-path",
        type=Path,
        default=DEFAULT_MARKET_STATUS_PATH,
    )
    parser.add_argument(
        "--policy-path",
        type=Path,
        default=DEFAULT_POLICY_PATH,
    )
    parser.add_argument(
        "--pack-run-path",
        type=Path,
        default=DEFAULT_PACK_RUN_PATH,
    )
    parser.add_argument(
        "--bottleneck-path",
        type=Path,
        default=DEFAULT_BOTTLENECK_PATH,
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Do not write pack-run / bottleneck JSON",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full pack_run + bottleneck_review JSON",
    )
    args = parser.parse_args(argv)

    result = run_universe_filing_archive_pack(
        dry_run=not bool(args.apply),
        require_quiet_window=not bool(args.no_require_quiet),
        allow_outside_quiet_for_pilot=bool(args.allow_outside_quiet),
        lookback_weeks=int(args.lookback_weeks),
        max_units=args.max_units,
        max_http_fetches=int(args.max_http_fetches),
        dispatch_path=Path(args.dispatch_path),
        market_status_path=Path(args.market_status_path),
        policy_path=Path(args.policy_path),
        pack_run_path=Path(args.pack_run_path),
        bottleneck_path=Path(args.bottleneck_path),
        persist=not bool(args.no_persist),
    )
    review = result.get("bottleneck_review") or {}
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(format_bottleneck_review_summary(review))
        pack_run = result.get("pack_run") or {}
        print(f"Pack run path: {args.pack_run_path}")
        print(f"Bottleneck review path: {args.bottleneck_path}")
        print(f"Run id: {pack_run.get('run_id')}")
    # Fail-open for suspend/quiet_only — exit 0 so cron does not page.
    return int(result.get("exit_code") or 0)


if __name__ == "__main__":
    sys.exit(main())
