"""CLI for the observe-only signal-day memo job.

Drill-down only. The scheduled path is ops-monitor ``check_strategy_book_memo_job``.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from value_investor.strategy_book_memo_job import run_strategy_book_memo_job


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strategy book signal-day memo job (observe-only)")
    parser.add_argument("--repo-root", type=Path, default=Path())
    parser.add_argument(
        "--market", action="append", dest="markets", help="Limit to these market ids"
    )
    parser.add_argument(
        "--session",
        action="append",
        dest="sessions",
        help="Score this YYYY-MM-DD close for every selected market (repeatable)",
    )
    parser.add_argument(
        "--latest",
        type=int,
        default=0,
        help="Replay the last N qualified weekday closes per market, including stale charts",
    )
    parser.add_argument(
        "--allow-stale",
        action="store_true",
        help="Score closes more than 5 calendar days behind the decision date",
    )
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--now", help="Override the run timestamp (ISO-8601)")
    args = parser.parse_args(argv)
    now = None
    if args.now:
        now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
    sessions_by_market = None
    if args.sessions:
        markets = args.markets or ["ftse350"]
        sessions_by_market = {market: list(args.sessions) for market in markets}
    summary = run_strategy_book_memo_job(
        repo_root=args.repo_root,
        now=now,
        markets=args.markets,
        sessions_by_market=sessions_by_market,
        allow_stale=bool(args.allow_stale or args.latest),
        replay_limit=args.latest or None,
        persist=not args.no_persist,
    )
    view = {
        "spend_enabled": summary.get("spend_enabled"),
        "data_commit": summary.get("data_commit"),
        "new_log_rows": summary.get("new_log_rows"),
        "errors": summary.get("errors"),
        "markets": summary.get("markets"),
        "weeks": summary.get("weeks"),
        "logged": summary.get("logged"),
    }
    print(json.dumps(view, indent=2, default=str))
    return 1 if summary.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
