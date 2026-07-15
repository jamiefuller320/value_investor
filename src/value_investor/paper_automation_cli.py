"""CLI for independent daily paper-fund automation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.paper_automation import (
    DEFAULT_AUTOMATION_DIR,
    AutomationConfig,
    format_automation_text,
    run_daily_automation,
    save_watchlist,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run independent automated paper-fund decisions after London open settle, "
            "with surveillance of paper + owned watchlist holdings"
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_AUTOMATION_DIR,
        help="Directory for fund state, watchlist, and last-run report",
    )
    parser.add_argument(
        "--reports",
        type=Path,
        default=None,
        help="Path to latest.json (or bundle) with screen reports",
    )
    parser.add_argument(
        "--settle-minutes",
        type=int,
        default=None,
        help="Minutes after 08:00 Europe/London before acting (default: 75 ≈ 09:15)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Act even before settle / on non-trading days (for testing)",
    )
    parser.add_argument(
        "--surveillance-only",
        action="store_true",
        help="Do not rebalance; only refresh marks and emit alerts",
    )
    parser.add_argument(
        "--add-watch",
        action="append",
        default=[],
        metavar="TICKER",
        help="Add a real/live owned ticker to the surveillance watchlist (repeatable)",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON result")
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.add_watch:
        watch_path = output_dir / "owned_watchlist.json"
        existing = []
        if watch_path.exists():
            payload = json.loads(watch_path.read_text(encoding="utf-8"))
            existing = payload.get("holdings") or []
        have = {str(row.get("ticker") if isinstance(row, dict) else row) for row in existing}
        for ticker in args.add_watch:
            if ticker not in have:
                existing.append({"ticker": ticker, "name": ticker, "source": "live"})
                have.add(ticker)
        save_watchlist(watch_path, existing)

    config = AutomationConfig()
    config_path = output_dir / "config.json"
    if config_path.exists():
        config = AutomationConfig.from_dict(json.loads(config_path.read_text(encoding="utf-8")))
    if args.settle_minutes is not None:
        config.settle_minutes_after_open = args.settle_minutes
    if args.surveillance_only:
        config.auto_rebalance = False

    result = run_daily_automation(
        output_dir=output_dir,
        config=config,
        reports_path=args.reports,
        force=args.force,
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(format_automation_text(result))
        print(f"\nWrote {output_dir / 'last_run.json'}")
        print(f"Fund state: {output_dir / 'automated_fund.json'}")

    return 0 if result.gate.get("can_act") or args.force or result.alerts else 1


if __name__ == "__main__":
    sys.exit(main())
