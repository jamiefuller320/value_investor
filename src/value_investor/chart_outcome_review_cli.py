"""CLI for observe-only buy-tier chart outcome review."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.chart_outcome_review import (
    REVIEW_FILENAME,
    REVIEW_MD_FILENAME,
    run_chart_outcome_review,
)


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Score buy-tier dashboard charts against frozen initial recommendation "
            "levels (observe-only — no knob applies)."
        )
    )
    parser.add_argument("--data-dir", type=Path, default=Path("docs/data"))
    parser.add_argument(
        "--chart-dir",
        type=Path,
        default=None,
        help="Chart JSON directory (default: <data-dir>/charts)",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        payload = run_chart_outcome_review(data_dir=args.data_dir, chart_dir=args.chart_dir)
    except (FileNotFoundError, RuntimeError) as err:
        print(str(err), file=sys.stderr)
        return 1

    if args.json:
        slim = {
            "verdict": payload.get("verdict"),
            "verdict_label": payload.get("verdict_label"),
            "headline": payload.get("headline"),
            "counts": payload.get("counts"),
            "stats": payload.get("stats"),
            "well_timed": payload.get("well_timed"),
            "weakest": payload.get("weakest"),
        }
        _print_json(slim)
    else:
        print(f"Wrote {args.data_dir / REVIEW_FILENAME}")
        print(f"Wrote {args.data_dir / REVIEW_MD_FILENAME}")
        print(payload.get("headline") or "")
        counts = payload.get("counts") or {}
        print(
            f"charts={counts.get('chart_count', 0)} "
            f"well_timed={counts.get('well_timed', 0)} "
            f"giveback={counts.get('giveback', 0)} "
            f"stop_hit={counts.get('stop_hit', 0)} "
            f"terrible={counts.get('terrible', 0)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
