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
    compare_buffered_hold_across_tracks,
    compare_buffered_hold_counterfactual,
    compare_rebalance_counterfactual_previews,
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
        config = AutomationConfig.from_dict(json.loads(config_path.read_text(encoding="utf-8")))
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
            False if args.use_raw_signal else (True if args.use_adjusted_signal else None)
        ),
        require_research_accumulate=(
            True
            if args.require_research_accumulate
            else (False if args.no_research_accumulate else None)
        ),
        exit_confirm_screens=(
            int(args.exit_confirm_screens) if args.exit_confirm_screens is not None else None
        ),
        lookback_days=int(args.lookback_days) if args.lookback_days is not None else None,
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


def _cmd_archive_replay(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    config_path = output_dir / CONFIG_FILENAME
    fund_path = output_dir / FUND_FILENAME
    if config_path.exists():
        config = AutomationConfig.from_dict(json.loads(config_path.read_text(encoding="utf-8")))
    else:
        config = AutomationConfig()
    fund = ensure_automated_fund(fund_path, config) if fund_path.exists() else None

    comparison = compare_rebalance_counterfactual_previews(
        output_dir,
        max_positions=int(args.max_positions),
        skip_timing_wait=not args.allow_timing_wait,
        min_conviction=float(args.min_conviction),
        sector_cap=float(args.sector_cap),
        use_adjusted_signal=(
            False if args.use_raw_signal else (True if args.use_adjusted_signal else None)
        ),
        require_research_accumulate=(
            True
            if args.require_research_accumulate
            else (False if args.no_research_accumulate else None)
        ),
        candidate_source=str(args.candidate_source),
        archive_dir=args.archive_dir,
        fetch_prices=bool(args.fetch_prices),
        actual_fund=fund,
    )
    if comparison is None:
        print("No rebalance log entries or archives to replay.", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(comparison, indent=2))
    else:
        archive = comparison.get("archive_preview") or {}
        log = comparison.get("log_preview") or {}
        cmp = comparison.get("comparison") or {}
        print("Archive vs log rebalance counterfactual (observe-only)")
        print(f"  Knobs: {comparison.get('knobs')}")
        print(
            f"  Log replay: {cmp.get('log_entries_replayed', 0)} passes | "
            f"sim {cmp.get('log_simulated_return', 0):+.1%} | "
            f"Δ vs actual {cmp.get('log_return_delta_vs_actual', 0):+.1%}"
        )
        print(
            f"  Archive replay: {cmp.get('archive_passes_replayed', 0)} passes | "
            f"sim {cmp.get('archive_simulated_return', 0):+.1%} | "
            f"Δ vs actual {cmp.get('archive_return_delta_vs_actual', 0):+.1%}"
        )
        gap = cmp.get("return_delta_gap_archive_minus_log")
        if gap is not None:
            print(f"  Archive minus log return delta: {gap:+.1%}")
        if archive.get("limitations"):
            print(f"  Note: {archive.get('limitations')}")
        if log.get("limitations"):
            print(f"  Log note: {log.get('limitations')}")
    return 0


def _cmd_buffered_hold(args: argparse.Namespace) -> int:
    if args.paper_root is not None:
        comparison = compare_buffered_hold_across_tracks(
            Path(args.paper_root),
            track_ids=tuple(args.tracks.split(",")),
            lookback_days=int(args.lookback_days),
            exit_confirm_variants=tuple(int(v) for v in args.exit_confirm_variants.split(",")),
        )
    else:
        output_dir = Path(args.output_dir)
        config_path = output_dir / CONFIG_FILENAME
        fund_path = output_dir / FUND_FILENAME
        fund = None
        if fund_path.exists() and config_path.exists():
            config = AutomationConfig.from_dict(json.loads(config_path.read_text(encoding="utf-8")))
            fund = ensure_automated_fund(fund_path, config)
        comparison = compare_buffered_hold_counterfactual(
            output_dir,
            lookback_days=int(args.lookback_days),
            exit_confirm_variants=tuple(int(v) for v in args.exit_confirm_variants.split(",")),
            actual_fund=fund,
        )
    if comparison is None:
        print("No rebalance log entries in lookback window to replay.", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(comparison, indent=2))
    else:
        print("Buffered-hold counterfactual (observe-only)")
        print(f"  Scope: {comparison.get('scope')}")
        print(f"  Lookback: {comparison.get('lookback_days')}d")
        tracks = comparison.get("tracks")
        if isinstance(tracks, dict):
            for track_id, row in tracks.items():
                ctx = row.get("churn_context") or {}
                cmp = row.get("comparison") or {}
                print(
                    f"  [{track_id}] buffered={ctx.get('buffered_holdings')} "
                    f"full_exits={ctx.get('full_exits_in_window')} "
                    f"exit_streak={ctx.get('exit_streak')}"
                )
                delta = cmp.get("trade_count_delta_lower_minus_higher")
                drag = cmp.get("cost_drag_delta_lower_minus_higher")
                if delta is not None:
                    print(f"    screens=1 vs 2: trade_delta={delta:+d} cost_drag_delta={drag:+.1%}")
        else:
            ctx = comparison.get("churn_context") or {}
            cmp = comparison.get("comparison") or {}
            print(f"  Track: {comparison.get('track_id')}")
            print(f"  Buffered holdings: {ctx.get('buffered_holdings')}")
            print(f"  Full exits in window: {ctx.get('full_exits_in_window')}")
            print(f"  Exit streak: {ctx.get('exit_streak')}")
            delta = cmp.get("trade_count_delta_lower_minus_higher")
            drag = cmp.get("cost_drag_delta_lower_minus_higher")
            if delta is not None:
                print(f"  screens=1 vs 2: trade_delta={delta:+d} cost_drag_delta={drag:+.1%}")
        if comparison.get("limitations"):
            print(f"  Note: {comparison.get('limitations')}")
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
    replay.add_argument(
        "--exit-confirm-screens",
        type=int,
        default=None,
        help="Counterfactual: override hold-buffer exit_confirm_screens knob",
    )
    replay.add_argument(
        "--lookback-days",
        type=int,
        default=None,
        help="Replay only passes within the last N days",
    )
    replay.add_argument("--json", action="store_true")
    replay.set_defaults(func=_cmd_replay)

    buffered_hold = sub.add_parser(
        "buffered-hold",
        help="Compare exit_confirm_screens variants on recent log passes (observe-only)",
    )
    buffered_hold.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_AUTOMATION_DIR,
        help="Single paper automation track directory",
    )
    buffered_hold.add_argument(
        "--paper-root",
        type=Path,
        default=None,
        help="Paper automation root — compare rules and ai_judgment tracks",
    )
    buffered_hold.add_argument(
        "--tracks",
        default="rules,ai_judgment",
        help="Comma-separated track ids when --paper-root is set",
    )
    buffered_hold.add_argument("--lookback-days", type=int, default=7)
    buffered_hold.add_argument(
        "--exit-confirm-variants",
        default="1,2",
        help="Comma-separated exit_confirm_screens values to compare",
    )
    buffered_hold.add_argument("--json", action="store_true")
    buffered_hold.set_defaults(func=_cmd_buffered_hold)

    archive_replay = sub.add_parser(
        "archive-replay",
        help="Compare full archive-screen replay vs logged-pass replay",
    )
    archive_replay.add_argument("--max-positions", type=int, default=5)
    archive_replay.add_argument("--min-conviction", type=float, default=0.55)
    archive_replay.add_argument("--sector-cap", type=float, default=0.2)
    archive_replay.add_argument(
        "--archive-dir",
        type=Path,
        default=None,
        help="Dashboard archive directory (default: docs/data/archive)",
    )
    archive_replay.add_argument(
        "--fetch-prices",
        action="store_true",
        help="Fetch missing marks from yfinance when archives lack prices",
    )
    archive_replay.add_argument(
        "--allow-timing-wait",
        action="store_true",
        help="Do not skip timing_signal=wait on new buys",
    )
    archive_replay.add_argument("--use-raw-signal", action="store_true")
    archive_replay.add_argument("--use-adjusted-signal", action="store_true")
    archive_replay.add_argument("--require-research-accumulate", action="store_true")
    archive_replay.add_argument("--no-research-accumulate", action="store_true")
    archive_replay.add_argument(
        "--candidate-source",
        choices=("auto", "candidates", "screen_buy_tier"),
        default="auto",
    )
    archive_replay.add_argument("--json", action="store_true")
    archive_replay.set_defaults(func=_cmd_archive_replay)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
