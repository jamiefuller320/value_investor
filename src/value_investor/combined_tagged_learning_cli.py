"""CLI for the observe-only combined tagged exit_shadow join (drill-down)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.combined_tagged_learning import (
    DEFAULT_PAPER_ROOT,
    DEFAULT_POLICY_PATH,
    DEFAULT_STORE_PATH,
    update_combined_tagged_learning,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Observe-only combined vs per-market exit_shadow rollup tagged by "
            "market_id. Does not merge books or apply knobs."
        )
    )
    parser.add_argument(
        "--paper-root",
        type=Path,
        default=DEFAULT_PAPER_ROOT,
        help="Live paper automation root (default: docs/data/paper_automation)",
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=DEFAULT_POLICY_PATH,
        help="Library policy.json for admitted learning markets",
    )
    parser.add_argument(
        "--store",
        type=Path,
        default=DEFAULT_STORE_PATH,
        help="Output store path (default: docs/data/combined_tagged_learning.json)",
    )
    parser.add_argument(
        "--markets",
        default="",
        help="Comma-separated market ids (default: live ftse350 + admitted + shard dirs)",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Print only; do not write the store",
    )
    parser.add_argument("--json", action="store_true", help="Print payload JSON")
    args = parser.parse_args(argv)
    markets = [m.strip() for m in str(args.markets).split(",") if m.strip()] or None
    payload = update_combined_tagged_learning(
        store_path=args.store,
        paper_root=args.paper_root,
        policy_path=args.policy,
        markets=markets,
        persist=not args.no_persist,
    )
    if args.json:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    summary = payload.get("summary") or {}
    print(
        f"markets={summary.get('market_count')} "
        f"open={summary.get('open_count')} closed={summary.get('closed_count')} "
        f"first_episode_closed={summary.get('first_episode_closed_count')} "
        f"missing_market_id={summary.get('source_records_missing_market_id')}"
    )
    print(payload.get("note") or "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
