"""CLI for unified experiment assessment ledger."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.experiment_assessment import (
    ASSESSMENT_FILENAME,
    refresh_experiment_assessment,
    slim_experiment_assessment_for_review,
)
from value_investor.storage import read_json

DEFAULT_DATA_DIR = Path("docs/data")


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _cmd_refresh(args: argparse.Namespace) -> int:
    payload = refresh_experiment_assessment(
        Path(args.data_dir),
        paper_root=Path(args.paper_root) if args.paper_root else None,
        min_marks=int(args.min_marks),
        min_excess_vs_market=float(args.min_excess),
        min_excess_vs_parent=float(args.min_excess_vs_parent),
        fetch_benchmark=bool(args.fetch_benchmark),
        output_path=Path(args.output) if args.output else None,
    )
    if args.json:
        _print_json(payload)
        return 0
    print(f"Experiment assessment: {payload.get('path') or ASSESSMENT_FILENAME}")
    summary = payload.get("summary") or {}
    print(f"  Total: {summary.get('total', 0)}")
    for status in ("proposed", "observing", "continue", "fail", "recommend"):
        count = summary.get(status, 0)
        if count:
            print(f"  {status}: {count}")
    if summary.get("human_ack_pending"):
        print(f"  human_ack_pending: {summary['human_ack_pending']}")
    for row in payload.get("recommendations") or []:
        print(
            f"  RECOMMEND [{row.get('kind')}] {row.get('experiment_id')} "
            f"marks={row.get('gate_marks')}"
        )
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    path = Path(args.data_dir) / ASSESSMENT_FILENAME
    if not path.exists():
        print(f"Missing {path}", file=sys.stderr)
        return 1
    payload = read_json(path)
    if args.json:
        _print_json(slim_experiment_assessment_for_review(payload))
        return 0
    slim = slim_experiment_assessment_for_review(payload)
    print(f"Experiment assessment: {path}")
    print(f"  Updated: {slim.get('updated_at')}")
    summary = slim.get("summary") or {}
    print(f"  Total: {summary.get('total', 0)}")
    for row in slim.get("recommendations") or []:
        print(f"  RECOMMEND {row.get('experiment_id')} ({row.get('pipeline')})")
    return 0


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    common.add_argument("--paper-root", default=None)
    common.add_argument("--json", action="store_true")

    parser = argparse.ArgumentParser(description="Unified experiment assessment ledger")
    sub = parser.add_subparsers(dest="command", required=True)

    refresh_p = sub.add_parser("refresh", parents=[common], help="Rebuild experiment assessment ledger")
    refresh_p.add_argument("--min-marks", default="4")
    refresh_p.add_argument("--min-excess", default="0.0")
    refresh_p.add_argument("--min-excess-vs-parent", default="0.0")
    refresh_p.add_argument("--fetch-benchmark", action="store_true")
    refresh_p.add_argument("--output", default=None)
    refresh_p.set_defaults(func=_cmd_refresh)

    status_p = sub.add_parser("status", parents=[common], help="Show committed assessment ledger")
    status_p.set_defaults(func=_cmd_status)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
