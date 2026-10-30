"""Optional CLI drill-down for L650 entry news polarity (observe-only).

Production path is ops-monitor → entry_blind refresh (binds polarity on cards +
writes ``docs/data/entry_news_polarity.json``). This CLI is for ad-hoc show/refresh.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.entry_news_polarity import (
    DEFAULT_DATA_DIR,
    DEFAULT_LOOKBACK_DAYS,
    STORE_FILENAME,
    build_entry_news_polarity_panel,
    derive_entry_news_polarity,
    persist_entry_news_polarity_panel,
)
from value_investor.storage import read_json


def _print(payload: dict, *, as_json: bool) -> None:
    if as_json or not isinstance(payload, dict):
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    label = payload.get("label")
    if label:
        cites = payload.get("cites") or []
        print(
            f"label={label} join_ok={payload.get('join_ok')} "
            f"asof={payload.get('asof')} cites={len(cites)} "
            f"lookback_days={DEFAULT_LOOKBACK_DAYS} influences_live=false"
        )
        return
    print(
        f"cards={payload.get('card_count')} usable={payload.get('cards_with_usable_news')} "
        f"no_usable={payload.get('no_usable_news')} path={STORE_FILENAME}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ftse-entry-news-polarity",
        description=(
            "L650 entry news polarity (observe-only). Hard 90d PIT lookback; "
            "no fade into labels; never influences fills."
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

    show = sub.add_parser("show", help="Derive polarity for one ticker as-of buy day")
    show.add_argument("--ticker", required=True)
    show.add_argument("--asof", required=True, help="Buy day YYYY-MM-DD")
    show.add_argument("--name", default="", help="Issuer name for headline filter")
    show.add_argument(
        "--lookback-days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help=f"Hard PIT lookback ending asof (default {DEFAULT_LOOKBACK_DAYS})",
    )

    sub.add_parser(
        "refresh",
        help="Rebuild panel from entry_blind_review_queue.json active cards",
    )

    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir)

    if args.cmd == "show":
        payload = derive_entry_news_polarity(
            ticker=args.ticker,
            entry_at=args.asof,
            name=args.name or None,
            data_dir=data_dir,
            lookback_days=int(args.lookback_days),
        )
        _print(payload, as_json=args.json)
        return 0

    if args.cmd == "refresh":
        queue_path = data_dir / "entry_blind_review_queue.json"
        try:
            queue = read_json(queue_path)
        except (OSError, FileNotFoundError, ValueError, TypeError):
            queue = {}
        cards = list(queue.get("active") or []) if isinstance(queue, dict) else []
        panel = build_entry_news_polarity_panel(data_dir=data_dir, cards=cards)
        path = persist_entry_news_polarity_panel(panel, data_dir=data_dir)
        panel["path"] = str(path)
        _print(panel, as_json=args.json)
        return 0

    parser.error(f"unknown command {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
