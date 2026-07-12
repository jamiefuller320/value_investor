"""CLI for portfolio simulation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.simulator import (
    DEFAULT_INITIAL_CAPITAL,
    DEFAULT_TRADE_COST_PCT,
    SimulatorConfig,
    format_simulation_comparison_text,
    run_simulation_from_dir,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Simulate portfolio performance from archived screening runs"
    )
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument(
        "--capital",
        type=float,
        default=DEFAULT_INITIAL_CAPITAL,
        help="Starting cash in GBP (default: 1000)",
    )
    parser.add_argument(
        "--trade-cost",
        type=float,
        default=DEFAULT_TRADE_COST_PCT,
        help="Transaction cost per trade as decimal (default: 0.03 = 3%%)",
    )
    parser.add_argument(
        "--max-positions",
        type=int,
        default=5,
        help="Maximum holdings at each rebalance (default: 5)",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON summary")
    args = parser.parse_args(argv)

    config = SimulatorConfig(
        initial_capital=args.capital,
        trade_cost_pct=args.trade_cost,
        max_positions=args.max_positions,
    )
    comparison = run_simulation_from_dir(args.output_dir, config=config)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.output_dir / "simulation_summary.json"
    out_path.write_text(json.dumps(comparison.to_dict(), indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(comparison.to_dict(), indent=2))
    else:
        print(format_simulation_comparison_text(comparison))
        print(f"\nWrote {out_path}")

    return 0 if comparison.has_results() or comparison.screen.note else 1


if __name__ == "__main__":
    sys.exit(main())
