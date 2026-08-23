"""CLI for deterministic loser-cohort snapshot cards."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.loser_snapshot_cards import (
    CARDS_FILENAME,
    CARDS_MD_FILENAME,
    run_loser_snapshot_cards,
)


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build deterministic loser-cohort snapshot cards from latest screen "
            "(avoid-tier + failed-buy alumni only — not the full index)."
        )
    )
    parser.add_argument("--data-dir", type=Path, default=Path("docs/data"))
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--no-avoid",
        action="store_true",
        help="Skip avoid-tier cards",
    )
    parser.add_argument(
        "--no-failed-buy-alumni",
        action="store_true",
        help="Skip failed-buy alumni cards",
    )
    args = parser.parse_args(argv)

    try:
        payload = run_loser_snapshot_cards(
            data_dir=args.data_dir,
            include_avoid=not args.no_avoid,
            include_failed_buy_alumni=not args.no_failed_buy_alumni,
        )
    except (FileNotFoundError, RuntimeError) as err:
        print(str(err), file=sys.stderr)
        return 1

    if args.json:
        _print_json(payload)
    else:
        print(f"Wrote {args.data_dir / CARDS_FILENAME}")
        print(f"Wrote {args.data_dir / CARDS_MD_FILENAME}")
        print(f"cards={payload['card_count']} cohorts={payload['cohort_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
