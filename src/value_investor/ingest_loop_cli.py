"""CLI for the weekday ingest-assess-improve loop."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.ingest_loop import (
    DEFAULT_DATA_DIR,
    DEFAULT_HEALTH_LOG_PATH,
    DEFAULT_LATEST_PATH,
    DEFAULT_STALL_RUNS,
    ingest_health_stalled,
    run_weekday_ingest_loop,
)
from value_investor.research.gap_fill import DEFAULT_SUGGESTIONS_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Weekday ingest-assess loop for live FTSE buy-tier filing coverage",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true")
    common.add_argument("--latest-path", type=Path, default=DEFAULT_LATEST_PATH)
    common.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    common.add_argument("--health-log-path", type=Path, default=DEFAULT_HEALTH_LOG_PATH)
    common.add_argument("--suggestions-path", type=Path, default=DEFAULT_SUGGESTIONS_PATH)
    common.add_argument("--max-targets", type=int, default=5)
    common.add_argument("--stall-runs", type=int, default=DEFAULT_STALL_RUNS)
    common.add_argument("--micro-compile-max-tasks", type=int, default=3)
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser(
        "run",
        parents=[common],
        help="Run ingest improvement, log health, maybe micro-compile tasks",
    )
    run_p.set_defaults(func=_cmd_run)

    status_p = sub.add_parser(
        "status",
        parents=[common],
        help="Report whether ingest health is stalled",
    )
    status_p.set_defaults(func=_cmd_status)

    args = parser.parse_args(argv)
    return int(args.func(args))


def _cmd_run(args: argparse.Namespace) -> int:
    result = run_weekday_ingest_loop(
        latest_path=args.latest_path,
        data_dir=args.data_dir,
        health_log_path=args.health_log_path,
        suggestions_path=args.suggestions_path,
        max_targets=args.max_targets,
        stall_runs=args.stall_runs,
        micro_compile_max_tasks=args.micro_compile_max_tasks,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        before = result.health_before.get("zero_body_buy_tier")
        after = result.health_after.get("zero_body_buy_tier")
        print(
            f"Ingest loop complete: zero_body_buy_tier {before} → {after}; "
            f"stalled={result.stalled}; micro_compiled={result.micro_compiled}"
        )
        if result.micro_compiled:
            print(f"  added tasks: {', '.join(result.micro_compile.get('task_ids') or [])}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    stalled = ingest_health_stalled(args.health_log_path, min_runs=args.stall_runs)
    payload = {"stalled": stalled, "stall_runs": args.stall_runs}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Ingest health stalled={stalled} (window={args.stall_runs} runs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
