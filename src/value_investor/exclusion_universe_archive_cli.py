"""CLI for observe-only exclusion-universe archive simulation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.exclusion_universe_archive_sim import (
    UNIVERSE_BUY_TIER_ONLY,
    UNIVERSE_FULL_SCREENED,
    ExclusionStep,
    ExclusionUniverseArchiveConfig,
    default_exclusion_ladder,
    format_exclusion_universe_text,
    run_exclusion_universe_archive_sim,
)


def _parse_conviction_ladder(raw: str | None) -> tuple[ExclusionStep, ...] | None:
    if not raw or not str(raw).strip():
        return None
    values = [float(part.strip()) for part in str(raw).split(",") if part.strip()]
    if not values:
        return None
    steps: list[ExclusionStep] = [
        ExclusionStep("u0", "Baseline universe"),
        ExclusionStep("u1", "Exclude avoid", exclude_signals=frozenset({"avoid"})),
        ExclusionStep(
            "u2",
            "Exclude avoid + timing wait",
            exclude_signals=frozenset({"avoid"}),
            exclude_timing_wait=True,
        ),
    ]
    for index, floor in enumerate(values, start=3):
        steps.append(
            ExclusionStep(
                f"u{index}",
                f"… + conviction >= {floor:.2f}",
                exclude_signals=frozenset({"avoid"}),
                exclude_timing_wait=True,
                min_conviction=floor,
            )
        )
    return tuple(steps)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Observe-only exclusion-universe lab: equal-weight universe vs "
            "universe-minus-exclusions across graduated tightening ladders."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/data"),
        help="Data root containing history/run_*.json.gz snapshots",
    )
    parser.add_argument(
        "--universe",
        choices=("buy_tier", "full_screened"),
        default="buy_tier",
        help="Baseline pool: buy-tier only (default) or full screened universe",
    )
    parser.add_argument(
        "--use-adjusted-signal",
        action="store_true",
        help="Use adjusted_signal / PIT research overlay for effective buy-tier gates",
    )
    parser.add_argument(
        "--no-research-pit",
        action="store_true",
        help="Do not resolve research overlay from memo store when adjusted_signal missing",
    )
    parser.add_argument(
        "--conviction-ladder",
        type=str,
        default="",
        help=(
            "Comma-separated min_conviction rungs after avoid/timing-wait steps "
            "(default: built-in 0.25,0.35,0.45 + optional AI overlay steps)"
        ),
    )
    parser.add_argument(
        "--no-ai-overlay-steps",
        action="store_true",
        help="Omit effective buy-tier and research-accumulate ladder rungs",
    )
    parser.add_argument(
        "--max-positions",
        type=int,
        default=5,
        help="Top-N conviction book overlay per week (default: 5)",
    )
    parser.add_argument(
        "--min-filtered-pool",
        type=int,
        default=15,
        help="Minimum avg filtered pool size for recommended step (default: 15)",
    )
    parser.add_argument(
        "--min-week-pairs",
        type=int,
        default=4,
        help="Minimum week pairs for readiness / recommendation (default: 4)",
    )
    parser.add_argument("--json", action="store_true", help="Print full review JSON")
    args = parser.parse_args(argv)

    universe_mode = (
        UNIVERSE_BUY_TIER_ONLY if args.universe == "buy_tier" else UNIVERSE_FULL_SCREENED
    )
    custom_ladder = _parse_conviction_ladder(args.conviction_ladder)
    if custom_ladder is not None:
        ladder = custom_ladder
    else:
        include_overlay = bool(args.use_adjusted_signal) and not args.no_ai_overlay_steps
        ladder = default_exclusion_ladder(include_ai_overlay_steps=include_overlay)

    config = ExclusionUniverseArchiveConfig(
        universe_mode=universe_mode,
        ladder=ladder,
        use_adjusted_signal=bool(args.use_adjusted_signal),
        resolve_research_pit=not args.no_research_pit,
        max_positions=int(args.max_positions),
        min_filtered_pool=int(args.min_filtered_pool),
        min_week_pairs=int(args.min_week_pairs),
    )
    review = run_exclusion_universe_archive_sim(args.output_dir, config=config)

    if args.json:
        # Review JSON can be large when weekly rows are included — store is slim on disk.
        slim = {key: value for key, value in review.items() if key != "weekly"}
        print(json.dumps(slim, indent=2))
    else:
        print(format_exclusion_universe_text(review))
    return 0


if __name__ == "__main__":
    sys.exit(main())
