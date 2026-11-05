"""Dispatcher named by registration section 12.

``--replay`` and ``--forward`` write different stores. ``--no-persist`` keeps
both in memory. ``--as-of`` sets the forward clock.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strategy book observe-only dispatcher")
    parser.add_argument("--repo-root", type=Path, default=Path())
    parser.add_argument("--fixture-dir", type=Path)
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--forward", action="store_true")
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--as-of", help="Forward clock (ISO-8601)")
    args = parser.parse_args(argv)
    if not args.replay and not args.forward:
        parser.error("pass --replay, --forward, or both")
    code = 0
    if args.replay:
        from value_investor.strategy_book_replay_cli import main as replay_main

        replay_args = ["--repo-root", str(args.repo_root)]
        if args.fixture_dir is not None:
            replay_args.extend(["--fixture-dir", str(args.fixture_dir)])
        if not args.no_persist:
            replay_args.append("--persist")
        code = max(code, replay_main(replay_args))
    if args.forward:
        from value_investor.strategy_book_forward_cli import main as forward_main

        forward_args = ["--repo-root", str(args.repo_root)]
        if args.as_of:
            forward_args.extend(["--as-of", args.as_of])
        if not args.no_persist:
            forward_args.append("--apply")
        code = max(code, forward_main(forward_args))
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
