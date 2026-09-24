"""CLI for buy-tier ingest fragment utilization audit (+ flip→usable lag pin).

Also hosts the observe-only FTSE holdings ∪ buy-tier decision-input inventory
(``--decision-inputs``) — steady-state P1 utilization, not flip-lag.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from value_investor.buy_tier_flip_lag import (
    DEFAULT_FLIP_LOOKBACK_DAYS,
    DEFAULT_LIBRARY_ROOT,
    DEFAULT_POLICY_PATH,
    DEFAULT_STORE_PATH,
    DEFAULT_WARN_AFTER_HOURS,
    format_flip_lag_summary,
    update_buy_tier_flip_lag,
)
from value_investor.decision_input_inventory import (
    DEFAULT_GREEN_ENOUGH_MAX_GAPS,
    DEFAULT_MEMO_MAX_AGE_DAYS,
    DEFAULT_PAPER_FUND_PATH,
    format_decision_input_summary,
    run_decision_input_inventory,
)
from value_investor.decision_input_inventory import (
    DEFAULT_STORE_PATH as DEFAULT_DECISION_INPUT_STORE,
)
from value_investor.ingest_utilization_audit import (
    DEFAULT_LATEST_PATH,
    DEFAULT_MEMO_DIR,
    DEFAULT_OUTPUT_PATH,
    DEFAULT_RESEARCH_ROOT,
    format_audit_summary,
    run_ingest_utilization_audit,
    write_ingest_utilization_audit,
)

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit buy-tier ingest fragment utilization vs screen overlay and paper gates"
        ),
    )
    parser.add_argument("--latest-path", type=Path, default=DEFAULT_LATEST_PATH)
    parser.add_argument("--research-root", type=Path, default=DEFAULT_RESEARCH_ROOT)
    parser.add_argument("--memo-dir", type=Path, default=DEFAULT_MEMO_DIR)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Write full JSON audit (default: output/ingest_utilization_audit.json)",
    )
    parser.add_argument(
        "--flip-lag",
        action="store_true",
        help=(
            "Observe-only: refresh docs/data/buy_tier_flip_lag.json for recent "
            "buy-tier flips across FTSE live + admitted learning markets "
            "(index → key bodies → memo; FTSE also tracks ai_track_buy_eligible)"
        ),
    )
    parser.add_argument(
        "--flip-lag-store",
        type=Path,
        default=DEFAULT_STORE_PATH,
        help="Flip-lag observe store path (default: docs/data/buy_tier_flip_lag.json)",
    )
    parser.add_argument(
        "--flip-lookback-days",
        type=int,
        default=DEFAULT_FLIP_LOOKBACK_DAYS,
        help=f"Cohort window for signal_since (default: {DEFAULT_FLIP_LOOKBACK_DAYS})",
    )
    parser.add_argument(
        "--flip-warn-after-hours",
        type=float,
        default=DEFAULT_WARN_AFTER_HOURS,
        help=f"Hours after flip before ops warn (default: {DEFAULT_WARN_AFTER_HOURS})",
    )
    parser.add_argument(
        "--library-root",
        type=Path,
        default=DEFAULT_LIBRARY_ROOT,
        help="Library root for admitted-market screens/research",
    )
    parser.add_argument(
        "--policy-path",
        type=Path,
        default=DEFAULT_POLICY_PATH,
        help="Library policy.json (admitted_learning_markets roster)",
    )
    parser.add_argument(
        "--markets",
        default="",
        help="Comma-separated market ids (default: FTSE live + admitted set)",
    )
    parser.add_argument(
        "--ftse-only",
        action="store_true",
        help="Restrict flip-lag refresh to the FTSE live path only",
    )
    parser.add_argument(
        "--decision-inputs",
        action="store_true",
        help=(
            "Observe-only: refresh docs/data/decision_input_inventory.json for "
            "FTSE AI-judgment holdings ∪ buy-tier (key bodies, FCF basis bind, "
            "overlay bind, memo recency) — not flip-lag"
        ),
    )
    parser.add_argument(
        "--decision-inputs-store",
        type=Path,
        default=DEFAULT_DECISION_INPUT_STORE,
        help=(
            "Decision-input inventory store path "
            f"(default: {DEFAULT_DECISION_INPUT_STORE})"
        ),
    )
    parser.add_argument(
        "--paper-fund",
        type=Path,
        default=DEFAULT_PAPER_FUND_PATH,
        help=f"AI-judgment paper fund path (default: {DEFAULT_PAPER_FUND_PATH})",
    )
    parser.add_argument(
        "--memo-max-age-days",
        type=float,
        default=DEFAULT_MEMO_MAX_AGE_DAYS,
        help=f"Memo considered recent within N days (default: {DEFAULT_MEMO_MAX_AGE_DAYS})",
    )
    parser.add_argument(
        "--green-enough-max-gaps",
        type=int,
        default=DEFAULT_GREEN_ENOUGH_MAX_GAPS,
        help=(
            "Max dominant-field gaps still called P1 green-enough "
            f"(default: {DEFAULT_GREEN_ENOUGH_MAX_GAPS})"
        ),
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON to stdout")
    parser.add_argument("--no-write", action="store_true", help="Skip writing output file")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if args.flip_lag and args.decision_inputs:
        parser.error("Use only one of --flip-lag or --decision-inputs")

    if args.flip_lag:
        market_ids = [m.strip() for m in str(args.markets or "").split(",") if m.strip()]
        payload = update_buy_tier_flip_lag(
            latest_path=args.latest_path,
            research_root=args.research_root,
            memo_dir=args.memo_dir,
            store_path=args.flip_lag_store,
            library_root=args.library_root,
            policy_path=args.policy_path,
            include_admitted=not args.ftse_only,
            markets=market_ids or None,
            include_ftse=True,
            lookback_days=int(args.flip_lookback_days),
            warn_after_hours=float(args.flip_warn_after_hours),
            persist=not args.no_write,
        )
        if not args.no_write:
            logger.info("Wrote %s", args.flip_lag_store)
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(format_flip_lag_summary(payload))
        return 0

    if args.decision_inputs:
        payload = run_decision_input_inventory(
            latest_path=args.latest_path,
            research_root=args.research_root,
            memo_dir=args.memo_dir,
            paper_fund_path=args.paper_fund,
            store_path=args.decision_inputs_store,
            memo_max_age_days=float(args.memo_max_age_days),
            green_enough_max_gaps=int(args.green_enough_max_gaps),
            persist=not args.no_write,
        )
        if not args.no_write:
            logger.info("Wrote %s", args.decision_inputs_store)
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(format_decision_input_summary(payload))
        return 0

    payload = run_ingest_utilization_audit(
        latest_path=args.latest_path,
        research_root=args.research_root,
        memo_dir=args.memo_dir,
    )

    if not args.no_write:
        written = write_ingest_utilization_audit(payload, args.output)
        logger.info("Wrote %s", written)

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(format_audit_summary(payload))

    return 0


if __name__ == "__main__":
    sys.exit(main())
