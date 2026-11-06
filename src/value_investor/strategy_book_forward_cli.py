"""CLI for the strategy-book forward job. Stdout is counts only."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from value_investor.strategy_book_forward import counts_view, run_forward_job


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strategy book forward job (observe-only)")
    parser.add_argument("--repo-root", type=Path, default=Path())
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist the counts status. Scores are written only when forward_live is true.",
    )
    parser.add_argument("--as-of", help="Override the run timestamp (ISO-8601)")
    args = parser.parse_args(argv)
    now = None
    if args.as_of:
        now = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
    summary = run_forward_job(repo_root=args.repo_root, now=now, apply=args.apply)
    view = counts_view(summary)
    print(json.dumps(view, indent=2))
    return 1 if view.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
