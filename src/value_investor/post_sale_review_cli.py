"""CLI for post-sale review queue refresh + Accept/Comment (observe-only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.post_sale_review import (
    DEFAULT_DATA_DIR,
    DEFAULT_STORE_PATH,
    refresh_post_sale_review_queue,
)
from value_investor.post_sale_review_actions import run_post_sale_review_action


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
        prog="ftse-post-sale-review",
        description=(
            "Post-sale review queue (Package M). Observe-only — "
            "never influences fills or knobs."
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

    refresh = sub.add_parser("refresh", help="Rebuild active queue from sealed + control")
    refresh.add_argument(
        "--store",
        type=Path,
        default=DEFAULT_STORE_PATH,
        help="Output path for post_sale_review_queue.json",
    )

    accept = sub.add_parser("accept", help="Accept framing (clears active item)")
    accept.add_argument("--review-id", required=True)
    accept.add_argument("--tag", default="new", help="new | reply")
    accept.add_argument("--note", default="")

    comment = sub.add_parser(
        "comment",
        help="Comment missed pattern (clears item; spawns factory reply stub)",
    )
    comment.add_argument("--review-id", required=True)
    comment.add_argument("--text", required=True)
    comment.add_argument("--tag", default="new", help="new | reply")

    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir)

    if args.cmd == "refresh":
        payload = refresh_post_sale_review_queue(
            data_dir=data_dir,
            store_path=Path(args.store),
            persist=True,
        )
        _print(payload, as_json=args.json)
        return 0

    if args.cmd == "accept":
        result = run_post_sale_review_action(
            data_dir,
            review_id=args.review_id,
            decision="accept",
            text=args.note,
            tag_at_action=args.tag,
            source="cli",
            acted_by="cli",
        )
        _print(result, as_json=True)
        return 0

    if args.cmd == "comment":
        result = run_post_sale_review_action(
            data_dir,
            review_id=args.review_id,
            decision="comment",
            text=args.text,
            tag_at_action=args.tag,
            source="cli",
            acted_by="cli",
        )
        _print(result, as_json=True)
        return 0

    parser.error(f"unknown command {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
