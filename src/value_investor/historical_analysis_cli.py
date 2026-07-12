"""CLI for point-in-time historical recommendation analysis."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.historical_analysis import (
    HistoricalAnalysisConfig,
    format_historical_analysis_text,
    run_historical_analysis,
    save_historical_analysis,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Replay archived weekly runs with point-in-time models and research "
            "(up to 3 years, smoothed weekly cohorts)"
        )
    )
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--max-years", type=int, default=3, help="Analysis window in years")
    parser.add_argument(
        "--smoothing-weeks",
        type=int,
        default=4,
        help="Rolling window for weekly excess-return smoothing",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON summary")
    args = parser.parse_args(argv)

    config = HistoricalAnalysisConfig(
        max_years=args.max_years,
        smoothing_weeks=args.smoothing_weeks,
    )
    summary = run_historical_analysis(args.output_dir, config=config)
    path = save_historical_analysis(args.output_dir, summary)

    if args.json:
        print(json.dumps(summary.to_dict(), indent=2))
    else:
        print(format_historical_analysis_text(summary))
        print(f"\nWrote {path}")

    return 0 if summary.has_results() or summary.note else 1


if __name__ == "__main__":
    sys.exit(main())
