"""CLI for human-task board refresh and observe-only ack."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.human_task_ack import run_human_task_ack
from value_investor.human_task_cards import write_human_tasks_board


def _cmd_refresh(args: argparse.Namespace) -> int:
    board = write_human_tasks_board(data_dir=Path(args.data_dir))
    if args.json:
        print(json.dumps(board, indent=2, sort_keys=True, default=str))
    else:
        counts = board.get("counts") or {}
        print(
            f"human_tasks_board: human={counts.get('human')} "
            f"new_info={counts.get('new_info')} unacked={counts.get('unacked')} "
            f"acked={counts.get('acked')} automated={counts.get('automated')} "
            f"→ {board.get('path')}"
        )
    return 0


def _cmd_ack(args: argparse.Namespace) -> int:
    result = run_human_task_ack(
        Path(args.data_dir),
        task_id=args.task_id,
        decision=args.decision,
        note=args.note or "",
        finding_fingerprint=args.fingerprint or "",
        source=args.source or "cli",
        acked_by=args.acked_by or "human",
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Human tasks board + observe-only ack")
    parser.add_argument(
        "--data-dir",
        default="docs/data",
        help="Committed data directory (default: docs/data)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    refresh = sub.add_parser("refresh", help="Rebuild human_tasks_board.json")
    refresh.add_argument("--json", action="store_true")
    refresh.set_defaults(func=_cmd_refresh)

    ack = sub.add_parser("ack", help="Record observe-only ack / approval")
    ack.add_argument("--task-id", required=True)
    ack.add_argument(
        "--decision",
        default="ack_observe",
        choices=["ack_observe", "approve", "defer"],
    )
    ack.add_argument("--note", default="")
    ack.add_argument("--fingerprint", default="")
    ack.add_argument("--source", default="cli")
    ack.add_argument("--acked-by", default="human")
    ack.set_defaults(func=_cmd_ack)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
