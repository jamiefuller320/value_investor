"""CLI for entry_revisit review queue refresh + Accept/Comment (observe-only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.entry_revisit_review import (
    DEFAULT_DATA_DIR,
    DEFAULT_STORE_PATH,
    refresh_entry_revisit_review_queue,
)
from value_investor.entry_revisit_review_actions import run_entry_revisit_review_action


def _print(payload: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    if "active_count" in payload:
        print(
            f"active={payload.get('active_count')} "
            f"new={payload.get('new_count')} reply={payload.get('reply_count')} "
            f"actioned={payload.get('actioned_count')} "
            f"path={payload.get('path') or DEFAULT_STORE_PATH}"
        )
        return
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ftse-entry-revisit-review",
        description=(
            "Entry-revisit review queue (Package M). Fixed buy+28d outcome after "
            "entry_blind. Observe-only — never influences fills or knobs; never "
            "rewrites blind Accept/Comment."
        ),
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Dashboard data directory (default: docs/data)",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON")
    sub = parser.add_subparsers(dest="cmd", required=True)

    refresh = sub.add_parser("refresh", help="Rebuild active entry_revisit queue")
    refresh.add_argument(
        "--store",
        type=Path,
        default=DEFAULT_STORE_PATH,
        help="Output path for entry_revisit_review_queue.json",
    )

    accept = sub.add_parser("accept", help="Accept framing (clears active item)")
    accept.add_argument("--review-id", required=True)
    accept.add_argument("--tag", default="new", help="new | reply")
    accept.add_argument("--note", default="")

    comment = sub.add_parser(
        "comment",
        help="Comment missed entry-lens calibration (clears; spawns reply stub)",
    )
    comment.add_argument("--review-id", required=True)
    comment.add_argument("--text", required=True)
    comment.add_argument("--tag", default="new", help="new | reply")

    duplicate = sub.add_parser(
        "duplicate",
        help="Mark duplicate pattern (clears item; no reply card)",
    )
    duplicate.add_argument("--review-id", required=True)
    duplicate.add_argument("--tag", default="new", help="new | reply")
    duplicate.add_argument("--note", default="")

    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir)

    if args.cmd == "refresh":
        payload = refresh_entry_revisit_review_queue(
            data_dir=data_dir, store_path=Path(args.store), persist=True
        )
        _print(payload, as_json=args.json)
        return 0

    decision = {"accept": "accept", "comment": "comment", "duplicate": "duplicate"}[args.cmd]
    text = getattr(args, "text", "") or getattr(args, "note", "") or ""
    result = run_entry_revisit_review_action(
        data_dir,
        review_id=str(args.review_id),
        decision=decision,
        text=text,
        tag_at_action=str(args.tag),
        source="cli",
        acted_by="cli",
    )
    _print(result, as_json=args.json)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
