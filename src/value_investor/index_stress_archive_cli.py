"""CLI for observe-only index stress archive simulation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.index_stress import IndexStressThresholds
from value_investor.index_stress_archive_sim import (
    IndexStressArchiveConfig,
    format_index_stress_archive_text,
    run_index_stress_archive_sim,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Observe-only index stress lab: daily ROC/drawdown triggers and "
            "stop-out counterfactuals on archived weekly screens."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/data"),
        help="Data root containing history/run_*.json.gz snapshots",
    )
    parser.add_argument(
        "--symbol",
        default="^FTSE",
        help="Benchmark symbol for daily stress bars (default: ^FTSE)",
    )
    parser.add_argument(
        "--abs-1d",
        type=float,
        default=-0.03,
        help="Primary absolute 1-day return trigger (default: -0.03)",
    )
    parser.add_argument(
        "--abs-5d",
        type=float,
        default=-0.05,
        help="Primary absolute 5-day return trigger (default: -0.05)",
    )
    parser.add_argument(
        "--drawdown",
        type=float,
        default=-0.06,
        help="Drawdown-from-peak trigger (default: -0.06)",
    )
    parser.add_argument(
        "--vol-z",
        type=float,
        default=2.5,
        help="Vol-adjusted 1d z-score trigger magnitude (default: 2.5)",
    )
    parser.add_argument(
        "--min-data-quality",
        type=float,
        default=0.0,
        help="Minimum data_quality_score for buy-tier stop counterfactual (default: 0)",
    )
    parser.add_argument(
        "--no-hourly",
        action="store_true",
        help="Skip hourly intraday fetch/merge (daily triggers only)",
    )
    parser.add_argument(
        "--abs-1h",
        type=float,
        default=-0.015,
        help="Hourly intraday ROC trigger (default: -0.015)",
    )
    parser.add_argument(
        "--abs-session",
        type=float,
        default=-0.03,
        help="Session open-to-close trigger (default: -0.03; use 0 to disable)",
    )
    parser.add_argument(
        "--exit-confirm-screens",
        type=int,
        default=2,
        help="Hold buffer before screen-rotation exit in policy replay (default: 2)",
    )
    parser.add_argument(
        "--no-momentum-grace",
        action="store_true",
        help="Disable momentum-grace overlay in exit-policy replay",
    )
    parser.add_argument("--json", action="store_true", help="Print full review JSON")
    args = parser.parse_args(argv)

    thresholds = IndexStressThresholds(
        abs_1d=float(args.abs_1d),
        abs_5d=float(args.abs_5d),
        drawdown_from_peak=float(args.drawdown),
        vol_z=float(args.vol_z),
        abs_1h=float(args.abs_1h),
        abs_session=float(args.abs_session) if float(args.abs_session) != 0 else None,
        use_intraday=not args.no_hourly,
    )
    config = IndexStressArchiveConfig(
        symbol=str(args.symbol),
        thresholds=thresholds,
        min_data_quality=float(args.min_data_quality),
        fetch_hourly=not args.no_hourly,
        exit_confirm_screens=int(args.exit_confirm_screens),
        use_momentum_grace=not args.no_momentum_grace,
    )
    review = run_index_stress_archive_sim(args.output_dir, config=config)

    if args.json:
        print(json.dumps(review, indent=2))
    else:
        print(format_index_stress_archive_text(review))
    return 0


if __name__ == "__main__":
    sys.exit(main())
