"""CLI for trajectory evidence (transitions, boundary watch, loser cards, outcomes)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.trajectory_evidence import (
    BOUNDARY_FILENAME,
    REVIEW_FILENAME,
    REVIEW_MD_FILENAME,
    TRANSITIONS_FILENAME,
    run_trajectory_evidence,
)


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build trajectory evidence: transition ledger, boundary watch panel, "
            "loser snapshot cards, and stratified outcome labels."
        )
    )
    parser.add_argument("--data-dir", type=Path, default=Path("docs/data"))
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--no-loser-cards",
        action="store_true",
        help="Skip loser snapshot card generation",
    )
    args = parser.parse_args(argv)

    try:
        payload = run_trajectory_evidence(
            data_dir=args.data_dir,
            include_loser_cards=not args.no_loser_cards,
        )
    except (FileNotFoundError, RuntimeError) as err:
        print(str(err), file=sys.stderr)
        return 1

    if args.json:
        _print_json(payload)
    else:
        print(f"Wrote {args.data_dir / TRANSITIONS_FILENAME}")
        print(f"Wrote {args.data_dir / BOUNDARY_FILENAME}")
        print(f"Wrote {args.data_dir / REVIEW_FILENAME}")
        print(f"Wrote {args.data_dir / REVIEW_MD_FILENAME}")
        if not args.no_loser_cards:
            print(f"Wrote {args.data_dir / 'loser_snapshot_cards.json'}")
        print(
            f"transitions={payload.get('transition_event_count')} "
            f"boundary={payload.get('boundary_watch_count')} "
            f"losers={payload.get('loser_card_count')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
