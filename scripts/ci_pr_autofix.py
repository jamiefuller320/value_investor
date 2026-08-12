#!/usr/bin/env python3
"""Apply scoped CI autofixes after a failed PR CI run."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.ci_pr_autofix import (
    AUTOFIX_COMMIT_PREFIX,
    PATH_EXPAND_COMMIT_PREFIX,
    run_pr_ci_autofix_pipeline,
    write_autofix_result,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        required=True,
        help="Git base ref for changed-file scope (e.g. origin/main)",
    )
    parser.add_argument("--head", default="HEAD", help="Git head ref (default: HEAD)")
    parser.add_argument(
        "--branch",
        required=True,
        help="PR head branch name (e.g. cursor/eng-20260812-03-1de3)",
    )
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
    parser.add_argument(
        "--diagnosis-out",
        type=Path,
        default=None,
        help="Write diagnosis JSON to this path",
    )
    args = parser.parse_args(argv)

    log_text = ""
    if args.log_file is not None:
        log_text = args.log_file.read_text(encoding="utf-8", errors="replace")
    elif not sys.stdin.isatty():
        log_text = sys.stdin.read()

    result, diagnosis = run_pr_ci_autofix_pipeline(
        branch=args.branch,
        base_ref=args.base,
        head_ref=args.head,
        log_text=log_text,
    )

    payload = {
        **result.to_dict(),
        "diagnosis": diagnosis.to_dict(),
        "commit_message": None,
    }
    if result.fixed and result.actions == ["ruff"]:
        payload["commit_message"] = f"{AUTOFIX_COMMIT_PREFIX} ruff on changed Python files"
    elif result.fixed and "path_guard_expand" in result.actions:
        payload["commit_message"] = PATH_EXPAND_COMMIT_PREFIX

    if args.out is not None:
        args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if args.diagnosis_out is not None:
        args.diagnosis_out.write_text(
            json.dumps(diagnosis.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )

    if args.json or args.out is not None:
        print(json.dumps(payload, indent=2))

    if result.fixed:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
