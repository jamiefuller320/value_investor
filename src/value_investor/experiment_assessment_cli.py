"""CLI for unified experiment assessment ledger."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.experiment_assessment import (
    ASSESSMENT_FILENAME,
    ack_experiment_tasks,
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
        sync_task_status=bool(args.sync_task_status),
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



def _cmd_ack(args: argparse.Namespace) -> int:
    ids = list(args.experiment_id or [])
    if args.ids:
        ids.extend(x.strip() for x in str(args.ids).split(",") if x.strip())
    # de-dupe preserve order
    seen: set[str] = set()
    experiment_ids: list[str] = []
    for item in ids:
        if item not in seen:
            seen.add(item)
            experiment_ids.append(item)
    if not experiment_ids:
        print("Provide --experiment-id and/or --ids", file=sys.stderr)
        return 2
    result = ack_experiment_tasks(
        Path(args.data_dir),
        experiment_ids,
        note=str(args.note),
        modifications=args.modifications,
        refresh=not args.no_refresh,
        sync_task_status=bool(args.sync_task_status),
    )
    if args.json:
        _print_json(result)
        return 0 if not result.get("missing") else 1
    print(f"Acked {len(result.get('updated') or [])} task(s): {', '.join(result.get('updated') or []) or '(none)'}")
    if result.get("missing"):
        print(f"Missing ids: {', '.join(result['missing'])}", file=sys.stderr)
    summary = result.get("summary") or {}
    if summary:
        print(
            f"Ledger summary: recommend={summary.get('recommend', 0)} "
            f"human_ack_pending={summary.get('human_ack_pending', 0)} "
            f"continue={summary.get('continue', 0)}"
        )
    for exp_id in result.get("recommendations") or []:
        print(f"  still RECOMMEND {exp_id}")
    return 0 if not result.get("missing") else 1



def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    common.add_argument("--paper-root", default=None)
    common.add_argument("--json", action="store_true")

    parser = argparse.ArgumentParser(description="Unified experiment assessment ledger")
    sub = parser.add_subparsers(dest="command", required=True)

    refresh_p = sub.add_parser(
        "refresh", parents=[common], help="Rebuild experiment assessment ledger"
    )
    refresh_p.add_argument("--min-marks", default="4")
    refresh_p.add_argument("--min-excess", default="0.0")
    refresh_p.add_argument("--min-excess-vs-parent", default="0.0")
    refresh_p.add_argument("--fetch-benchmark", action="store_true")
    refresh_p.add_argument("--sync-task-status", action="store_true")
    refresh_p.add_argument("--output", default=None)
    refresh_p.set_defaults(func=_cmd_refresh)

    status_p = sub.add_parser("status", parents=[common], help="Show committed assessment ledger")
    status_p.set_defaults(func=_cmd_status)

    ack_p = sub.add_parser(
        "ack",
        parents=[common],
        help="Human-ack recommend-gated task experiments (monitoring/observe plans)",
    )
    ack_p.add_argument(
        "--experiment-id",
        action="append",
        default=[],
        help="Experiment/task id to accept (repeatable)",
    )
    ack_p.add_argument(
        "--ids",
        default="",
        help="Comma-separated experiment ids (alternative to repeating --experiment-id)",
    )
    ack_p.add_argument("--note", required=True, help="Why this recommendation is accepted")
    ack_p.add_argument(
        "--modifications",
        default=None,
        help="Optional acceptance modifications (e.g. dual-suite scoring rules)",
    )
    ack_p.add_argument(
        "--no-refresh",
        action="store_true",
        help="Write task ack only; do not rebuild experiment_assessment.json",
    )
    ack_p.add_argument(
        "--sync-task-status",
        action="store_true",
        default=True,
        help="After refresh, sync assessment evidence into task stores (default on)",
    )
    ack_p.add_argument(
        "--no-sync-task-status",
        action="store_false",
        dest="sync_task_status",
        help="Skip task-store evidence sync after refresh",
    )
    ack_p.set_defaults(func=_cmd_ack)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
