"""CLI for the strategy-book close refresh. A dry run does not download."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from value_investor.strategy_book_prices import NAMES_PER_RUN, run_close_refresh


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strategy book close refresh (observe-only)")
    parser.add_argument("--repo-root", type=Path, default=Path())
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Download due charts and write closes_through. Default is a dry run.",
    )
    parser.add_argument("--as-of", help="Override the run timestamp (ISO-8601)")
    parser.add_argument("--budget", type=int, default=None)
    args = parser.parse_args(argv)
    now = _as_of(args.as_of)
    payload = run_close_refresh(
        repo_root=args.repo_root,
        now=now,
        apply=args.apply,
        budget=args.budget if args.budget is not None else NAMES_PER_RUN,
    )
    print(json.dumps(payload, indent=2))
    return 1 if payload.get("errors") else 0


def _as_of(text: str | None) -> datetime | None:
    if not text:
        return None
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
