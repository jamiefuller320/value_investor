"""CLI for per-track rebalance decision logs and knob counterfactual replay."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.paper_automation import (
    CONFIG_FILENAME,
    DEFAULT_AUTOMATION_DIR,
    FUND_FILENAME,
    AutomationConfig,
    ensure_automated_fund,
)
from value_investor.rebalance_log import (
    REBALANCE_LOG_FILENAME,
    acted_log_entries,
    load_rebalance_log,
    replay_counterfactual_from_log,
)


def _cmd_summary(args: argparse.Namespace) -> int:
    entries = load_rebalance_log(Path(args.output_dir))
    acted = acted_log_entries(entries)
    print(f"Rebalance log: {Path(args.output_dir) / REBALANCE_LOG_FILENAME}")
    print(f"  Total entries: {len(entries)}")
    print(f"  Acted entries: {len(acted)}")
    if acted:
        print(f"  First acted: {acted[0].get('gate', {}).get('local_time')}")
        print(f"  Last acted: {acted[-1].get('gate', {}).get('local_time')}")
    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    config_path = output_dir / CONFIG_FILENAME
    fund_path = output_dir / FUND_FILENAME
    if config_path.exists():
        config = AutomationConfig.from_dict(
            json.loads(config_path.read_text(encoding="utf-8"))
        )
    else:
        config = AutomationConfig()
    fund = ensure_automated_fund(fund_path, config) if fund_path.exists() else None

    entries = load_rebalance_log(output_dir)
    replay = replay_counterfactual_from_log(
        entries,
        max_positions=int(args.max_positions),
        skip_timing_wait=not args.allow_timing_wait,
        min_conviction=float(args.min_conviction),
        sector_cap=float(args.sector_cap),
        use_adjusted_signal=(
            False
            if args.use_raw_signal
            else (True if args.use_adjusted_signal else None)
        ),
        require_research_accumulate=(
            True
            if args.require_research_accumulate
            else (False if args.no_research_accumulate else None)
        ),
        candidate_source=str(args.candidate_source),
        actual_fund=fund,
    )
    if replay is None:
        print("No acted rebalance log entries to replay.", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(replay, indent=2))
    else:
        print("Knob counterfactual replay")
        print(f"  Scope: {replay.get('scope')}")
        print(f"  Replayed: {replay.get('log_entries_replayed')} passes")
        print(f"  Window: {replay.get('replay_from')} → {replay.get('replay_to')}")
        print(f"  Knobs: {replay.get('knobs')}")
        print(
            f"  Simulated return: {replay.get('simulated_return'):+.1%} "
            f"(NAV £{replay.get('simulated_nav')})"
        )
        if replay.get("actual_return_over_window") is not None:
            print(
                f"  Actual return: {replay.get('actual_return_over_window'):+.1%} "
                f"(NAV £{replay.get('actual_nav')})"
            )
            print(f"  Return delta: {replay.get('return_delta_vs_actual'):+.1%}")
            print(f"  Cost drag delta: {replay.get('cost_drag_delta_vs_actual'):+.1%}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect rebalance decision logs and replay knob counterfactuals."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_AUTOMATION_DIR,
        help="Paper automation track directory",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    summary = sub.add_parser("summary", help="Show rebalance log stats")
    summary.set_defaults(func=_cmd_summary)

    replay = sub.add_parser("replay", help="Replay logged passes with alternate knobs")
    replay.add_argument("--max-positions", type=int, default=5)
    replay.add_argument("--min-conviction", type=float, default=0.0)
    replay.add_argument("--sector-cap", type=float, default=0.3)
    replay.add_argument(
        "--allow-timing-wait",
        action="store_true",
        help="Do not skip timing_signal=wait on new buys",
    )
    replay.add_argument(
        "--use-raw-signal",
        action="store_true",
        help="Counterfactual: ignore adjusted_signal overlay (use raw screen signal)",
    )
    replay.add_argument(
        "--use-adjusted-signal",
        action="store_true",
        help="Counterfactual: gate on adjusted_signal overlay",
    )
    replay.add_argument(
        "--require-research-accumulate",
        action="store_true",
        help="Counterfactual: only buy when research_verdict=accumulate",
    )
    replay.add_argument(
        "--no-research-accumulate",
        action="store_true",
        help="Counterfactual: do not require research accumulate verdict",
    )
    replay.add_argument(
        "--candidate-source",
        choices=("auto", "candidates", "screen_buy_tier"),
        default="auto",
        help="Candidate pool for replay (default: auto — widens when AI gates change)",
    )
    replay.add_argument("--json", action="store_true")
    replay.set_defaults(func=_cmd_replay)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
