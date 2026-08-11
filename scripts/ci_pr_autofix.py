#!/usr/bin/env python3
"""Apply scoped ruff autofix after a failed PR CI run."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.ci_pr_autofix import attempt_pr_ci_autofix, write_autofix_result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        required=True,
        help="Git base ref for changed-file scope (e.g. origin/main)",
    )
    parser.add_argument("--head", default="HEAD", help="Git head ref (default: HEAD)")
    parser.add_argument(
        "--log-file",
        type=Path,
        help="CI failed job log text (default: stdin if piped)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print result JSON (always written when --out is set)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write result JSON to this path",
    )
    args = parser.parse_args(argv)

    log_text = ""
    if args.log_file is not None:
        log_text = args.log_file.read_text(encoding="utf-8", errors="replace")
    elif not sys.stdin.isatty():
        log_text = sys.stdin.read()

    result = attempt_pr_ci_autofix(
        base_ref=args.base,
        head_ref=args.head,
        log_text=log_text,
    )

    if args.out is not None:
        write_autofix_result(args.out, result)

    if args.json or args.out is not None:
        print(json.dumps(result.to_dict(), indent=2))

    if result.fixed:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
