"""CLI for backtest history health checks and safe repairs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.backtest_health import (
    DEFAULT_STATUS_PATH,
    audit_history_dir,
    repair_history_dir,
    run_backtest_health,
)
from value_investor.storage import COMMITTED_HISTORY_DIR


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Monitor and safely repair archived backtest run history",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--history-dir",
        type=Path,
        default=COMMITTED_HISTORY_DIR,
        help="History directory to audit (default: docs/data/history)",
    )
    parser.add_argument(
        "--status-path",
        type=Path,
        default=DEFAULT_STATUS_PATH,
        help="Where to write backtest_health.json",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Quarantine corrupt/duplicate snapshots (never rewrites payload data)",
    )
    parser.add_argument(
        "--audit-only",
        action="store_true",
        help="List issues without writing status file or applying repairs",
    )
    args = parser.parse_args(argv)

    if args.audit_only:
        issues, stats = audit_history_dir(args.history_dir)
        payload = {
            "history_dir": str(args.history_dir),
            "issues": [row.to_dict() for row in issues],
            "stats": stats,
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"Backtest history audit — {args.history_dir}")
            print(f"  run_files={stats['run_files']} valid_runs={stats['valid_runs']}")
            for row in issues:
                print(f"  [{row.severity}] {row.code}: {row.summary}")
        return 1 if any(row.severity == "fail" for row in issues) else 0

    if args.apply:
        issues, _ = audit_history_dir(args.history_dir)
        repairs = repair_history_dir(args.history_dir, issues, apply=True)
        if repairs and not args.json:
            for row in repairs:
                print(f"repair: {row.action} — {row.detail}")

    report = run_backtest_health(
        history_dir=args.history_dir,
        apply_repairs=False,
        status_path=args.status_path,
    )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"Backtest health: {report.overall.upper()}")
        print(f"  valid_runs={report.valid_runs} run_files={report.run_files}")
        if report.readiness.get("note"):
            print(f"  {report.readiness['note']}")
        if report.issues:
            print(f"  issues: {len(report.issues)}")
    if report.overall == "fail":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
