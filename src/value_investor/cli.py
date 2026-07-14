"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from value_investor.constituents import DEFAULT_UNIVERSE, VALID_UNIVERSES, universe_label
from value_investor.pipeline import run_screen, write_outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Screen FTSE companies for value signals")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Directory for CSV/JSON artifacts (default: output/)",
    )
    parser.add_argument(
        "--universe",
        choices=VALID_UNIVERSES,
        default=DEFAULT_UNIVERSE,
        help=f"Screening universe (default: {DEFAULT_UNIVERSE} = FTSE 100 + FTSE 250)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of companies (useful for dry runs)",
    )
    parser.add_argument(
        "--include-investment-trusts",
        action="store_true",
        help=(
            "Merge investment trusts into the operating-company Graham screen "
            "(disables the separate trust track)"
        ),
    )
    parser.add_argument(
        "--skip-trust-screen",
        action="store_true",
        help="Skip the separate investment-trust discount/income track",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=15,
        help="Print top N signals to stdout (default: 15)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print summary JSON to stdout instead of a table",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    result = run_screen(
        limit=args.limit,
        universe=args.universe,
        include_investment_trusts=args.include_investment_trusts,
        screen_trusts=not args.skip_trust_screen,
    )
    paths = write_outputs(result, args.output_dir)

    top = result.signals.head(args.top)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        cols = ["ticker", "name", "signal", "models_passed", "composite_score", "trailing_pe", "dividend_yield"]
        display_cols = [c for c in cols if c in top.columns]
        print(top[display_cols].to_string(index=False))
        print(f"\nUniverse: {universe_label(args.universe)} ({len(result.universe)} companies)")
        if result.trust_signals is not None and not result.trust_signals.empty:
            trust_top = result.trust_signals.head(min(args.top, 10))
            tcols = [
                c
                for c in (
                    "ticker",
                    "name",
                    "signal",
                    "models_passed",
                    "discount_to_nav",
                    "dividend_yield",
                    "price_to_book",
                )
                if c in trust_top.columns
            ]
            print(f"\nTrust track ({len(result.trust_signals)} names):")
            print(trust_top[tcols].to_string(index=False))
        elif result.excluded_investment_vehicles:
            print(
                f"Excluded {result.excluded_investment_vehicles} investment trusts/funds "
                "(trust track skipped or empty)"
            )
        print(f"Wrote {paths['latest']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
