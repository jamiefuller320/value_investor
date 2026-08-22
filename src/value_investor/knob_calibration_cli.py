"""CLI for walk-forward knob calibration (observe-only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.calibration_endurance import (
    ENDURANCE_FILENAME,
    refresh_calibration_endurance,
)
from value_investor.calibration_warm_start import (
    warm_start_calibration_shadow,
    warm_start_calibration_shadows,
)
from value_investor.knob_calibration import (
    DEFAULT_BOOTSTRAP_TOP_N,
    KNOB_CALIBRATION_PRIORS_FILENAME,
    RANKING_BLENDED,
    RANKING_FULL_PERIOD,
    RANKING_WALK_FORWARD,
    VALID_RANKING_MODES,
    calibrate_learning_tracks,
    calibrate_track,
    grid_axes_from_cli,
    spawn_calibrated_shadow_track,
    spawn_calibration_shadow_tracks,
    write_knob_calibration_priors,
)
from value_investor.paper_automation import DEFAULT_AUTOMATION_DIR, learning_track_dirs
from value_investor.storage import read_json


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2))


def _cmd_run(args: argparse.Namespace) -> int:
    axes = grid_axes_from_cli(
        max_positions=args.max_positions_grid,
        min_conviction=args.min_conviction_grid,
        sector_cap=args.sector_cap_grid,
        skip_timing_wait=args.skip_timing_wait_grid,
        exit_confirm_screens=args.exit_confirm_screens_grid,
        include_churn_knobs=bool(args.include_churn_knobs),
    )
    kwargs = {
        "axes": axes,
        "include_churn_knobs": bool(args.include_churn_knobs),
        "n_folds": int(args.n_folds),
        "cost_drag_lambda": float(args.cost_drag_lambda),
        "stability_penalty": float(args.stability_penalty),
        "archive_dir": Path(args.archive_dir) if args.archive_dir else None,
        "fetch_prices": bool(args.fetch_prices),
        "use_cohort_fitness": False if args.no_cohort_fitness else None,
        "ranking_mode": str(args.ranking_mode),
        "bootstrap_top_n": int(args.bootstrap_top_n),
    }
    if args.cohort_weight is not None:
        kwargs["cohort_weight"] = float(args.cohort_weight)
    if args.track_dir is not None:
        payload = calibrate_track(Path(args.track_dir), **kwargs)
    else:
        payload = calibrate_learning_tracks(
            Path(args.paper_root),
            track_ids=tuple(part.strip() for part in args.tracks.split(",") if part.strip()),
            **kwargs,
        )
    if args.write:
        write_knob_calibration_priors(Path(args.paper_root), payload)
    spawn_result = None
    if args.spawn_shadow:
        spawn_result = spawn_calibration_shadow_tracks(
            Path(args.paper_root),
            top_n=int(args.bootstrap_top_n),
            force_respawn=bool(args.force_respawn),
            require_ready=bool(args.require_ready_for_shadow),
        )
    if args.json:
        out = (
            payload
            if spawn_result is None
            else {"calibration": payload, "shadow_spawn": spawn_result}
        )
        _print_json(out)
    else:
        if spawn_result is not None:
            shadows = spawn_result.get("shadows") or []
            if spawn_result.get("spawned"):
                print(f"\nSpawned {len(shadows)} calibrated shadow track(s):")
                for row in shadows:
                    if not row.get("spawned"):
                        print(f"  skip rank={row.get('rank')}: {row.get('reason')}")
                        continue
                    print(
                        f"  [{row.get('rank')}] {row.get('shadow_track_id')} "
                        f"at {row.get('shadow_dir')} "
                        f"(confidence={row.get('confidence')})"
                    )
            else:
                print(f"\nShadow spawn skipped: {spawn_result.get('reason')}", file=sys.stderr)
        if payload.get("scope") == "knob_calibration_multi":
            print("Knob calibration (multi-track, observe-only)")
            for track_id, row in (payload.get("tracks") or {}).items():
                prior = row.get("recommended_prior") or {}
                ready = (row.get("readiness") or {}).get("ready_for_shadow_bootstrap")
                print(
                    f"  [{track_id}] mode={row.get('ranking_mode')} "
                    f"acted={row.get('readiness', {}).get('acted_entries')} "
                    f"top={prior.get('full_period_score') or prior.get('blended_score') or prior.get('composite_score')} "
                    f"gap={row.get('readiness', {}).get('score_gap_vs_runner_up')} "
                    f"bootstrap_ready={ready} confidence={prior.get('confidence')}"
                )
        else:
            prior = payload.get("recommended_prior") or {}
            print("Knob calibration (observe-only)")
            print(f"  Track: {payload.get('track_id')}")
            print(f"  Ranking mode: {payload.get('ranking_mode')}")
            print(f"  Acted entries: {payload.get('readiness', {}).get('acted_entries')}")
            print(f"  Grid size: {payload.get('readiness', {}).get('grid_size')}")
            print(
                f"  Shadow bootstrap ready: "
                f"{payload.get('readiness', {}).get('ready_for_shadow_bootstrap')}"
            )
            print(f"  Bootstrap priors: {len(payload.get('bootstrap_priors') or [])}")
            print(f"  Recommended prior: {prior.get('knobs')}")
            print(f"  Confidence: {prior.get('confidence')}")
        if args.write:
            print(f"\nWrote {Path(args.paper_root) / KNOB_CALIBRATION_PRIORS_FILENAME}")
    ready = False
    if payload.get("scope") == "knob_calibration_multi":
        ready = any(
            bool((row or {}).get("candidates_ranked"))
            for row in (payload.get("tracks") or {}).values()
        )
    else:
        ready = bool(payload.get("candidates_ranked"))
    return 0 if ready or args.allow_empty else 1


def _cmd_spawn_shadow(args: argparse.Namespace) -> int:
    if int(args.top_n) <= 1 and not args.require_ready:
        result = spawn_calibrated_shadow_track(
            Path(args.paper_root),
            force_respawn=bool(args.force_respawn),
        )
    else:
        result = spawn_calibration_shadow_tracks(
            Path(args.paper_root),
            top_n=int(args.top_n),
            force_respawn=bool(args.force_respawn),
            require_ready=bool(args.require_ready),
        )
    if args.json:
        _print_json(result)
        return 0 if result.get("spawned") else 1
    shadows = result.get("shadows")
    if shadows is not None:
        if result.get("spawned"):
            print(f"Spawned {len([s for s in shadows if s.get('spawned')])} shadow track(s)")
            for row in shadows:
                if row.get("spawned"):
                    print(
                        f"  [{row.get('rank')}] {row.get('shadow_track_id')} "
                        f"knobs={row.get('knobs')}"
                    )
                else:
                    print(f"  [{row.get('rank')}] skipped: {row.get('reason')}")
            return 0
        print(f"Shadow spawn failed: {result.get('reason')}", file=sys.stderr)
        return 1
    if result.get("spawned"):
        print(f"Spawned {result.get('shadow_track_id')} at {result.get('shadow_dir')}")
        print(f"  Confidence: {result.get('confidence')}")
        print(f"  Changed vs parent: {result.get('changed_vs_parent')}")
        print(f"  Provenance: {result.get('provenance_path')}")
        return 0
    print(f"Shadow spawn failed: {result.get('reason')}", file=sys.stderr)
    return 1


def _cmd_status(args: argparse.Namespace) -> int:
    path = Path(args.paper_root) / KNOB_CALIBRATION_PRIORS_FILENAME
    if not path.exists():
        print(f"No calibration artifact at {path}", file=sys.stderr)
        return 1
    payload = read_json(path)
    if args.json:
        _print_json(payload)
        return 0
    print(f"Knob calibration priors: {path}")
    print(f"  Calibrated at: {payload.get('calibrated_at')}")
    if payload.get("scope") == "knob_calibration_multi":
        for track_id, row in (payload.get("tracks") or {}).items():
            prior = row.get("recommended_prior") or {}
            print(
                f"  [{track_id}] mode={row.get('ranking_mode')} "
                f"bootstrap_ready={(row.get('readiness') or {}).get('ready_for_shadow_bootstrap')} "
                f"confidence={prior.get('confidence')} knobs={prior.get('knobs')}"
            )
            for prior_row in row.get("bootstrap_priors") or []:
                print(
                    f"    bootstrap r{prior_row.get('rank')}: "
                    f"{prior_row.get('shadow_track_id')} knobs={prior_row.get('knobs')}"
                )
    else:
        prior = payload.get("recommended_prior") or {}
        print(f"  Track: {payload.get('track_id')}")
        print(f"  Ranking mode: {payload.get('ranking_mode')}")
        print(f"  Confidence: {prior.get('confidence')}")
        print(f"  Recommended: {prior.get('knobs')}")
    return 0


def _cmd_endurance(args: argparse.Namespace) -> int:
    payload = refresh_calibration_endurance(
        Path(args.paper_root),
        min_marks_for_survivor=int(args.min_marks),
        min_excess_vs_market=float(args.min_excess),
        fetch_benchmark=bool(getattr(args, "fetch_benchmark", False)),
    )
    if args.json:
        _print_json(payload)
        return 0
    print(f"Calibration shadow endurance: {payload.get('path') or ENDURANCE_FILENAME}")
    print(f"  Shadows: {len(payload.get('shadows') or [])}")
    for row in payload.get("shadows") or []:
        metrics = row.get("metrics") or {}
        gate_excess = metrics.get("gate_excess_after_costs")
        if gate_excess is None:
            gate_excess = metrics.get("excess_after_costs")
        gate_marks = metrics.get("gate_equity_marks")
        if gate_marks is None:
            gate_marks = metrics.get("equity_marks")
        post = "post-seed" if row.get("gate_uses_post_seed") else "lifetime"
        print(
            f"  [{row.get('rank')}] {row.get('shadow_track_id')} "
            f"status={row.get('status')} gate={post} "
            f"excess={gate_excess} marks={gate_marks} "
            f"vs_primary={row.get('excess_vs_primary')} "
            f"vs_rules={row.get('excess_vs_rules')}"
        )
    survivors = payload.get("survivors") or []
    if survivors:
        print(f"  Survivors ({len(survivors)}):")
        for row in survivors:
            print(f"    - {row.get('shadow_track_id')} knobs={row.get('knobs')}")
    else:
        print("  Survivors: none yet (keep observing forward marks)")
    return 0


def _cmd_warm_start_shadow(args: argparse.Namespace) -> int:
    paper_root = Path(args.paper_root)
    sim_start = str(args.sim_start).strip() if args.sim_start else None
    if args.rank is not None:
        result = warm_start_calibration_shadow(
            paper_root,
            rank=int(args.rank),
            parent_track_id=str(args.parent_track),
            sim_start=sim_start,
            source=str(args.source),
            force=bool(args.force),
        )
        results = [result]
        payload = {"shadows": results, "warm_started": bool(result.get("warm_started"))}
    else:
        payload = warm_start_calibration_shadows(
            paper_root,
            parent_track_id=str(args.parent_track),
            sim_start=sim_start,
            source=str(args.source),
            force=bool(args.force),
        )
        results = list(payload.get("shadows") or [])

    if args.json:
        _print_json(payload)
        return 0 if payload.get("warm_started") or any(r.get("skipped") for r in results) else 1

    if not results:
        print(f"Warm-start failed: {payload.get('reason')}", file=sys.stderr)
        return 1

    ok = 0
    for row in results:
        if row.get("warm_started"):
            ok += 1
            zero = row.get("endurance_zero_datum") or {}
            print(
                f"Warm-started [{row.get('rank')}] {row.get('shadow_track_id')} "
                f"positions={row.get('positions')} "
                f"zero_at={zero.get('started_at')} "
                f"replayed={((row.get('seed_stats') or {}).get('log_entries_replayed'))}"
            )
        elif row.get("skipped"):
            print(f"Skipped [{row.get('rank')}] {row.get('shadow_track_id')}: {row.get('reason')}")
        else:
            print(
                f"Failed [{row.get('rank')}] {row.get('shadow_track_id')}: {row.get('reason')}",
                file=sys.stderr,
            )
    return 0 if ok or any(r.get("skipped") for r in results) else 1


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--paper-root",
        type=Path,
        default=DEFAULT_AUTOMATION_DIR,
        help="Paper automation root (default: output/paper_automation)",
    )

    parser = argparse.ArgumentParser(
        description=(
            "Walk-forward / full-period knob calibration on rebalance logs (observe-only). "
            "Writes ranked priors and optional competing shadow sims — does not auto-apply knobs."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", parents=[common], help="Run calibration grid search")
    run.add_argument(
        "--track-dir",
        type=Path,
        default=None,
        help="Single track directory (overrides --tracks)",
    )
    run.add_argument(
        "--tracks",
        default="rules,ai_judgment",
        help="Comma-separated track ids when calibrating from --paper-root",
    )
    run.add_argument("--max-positions-grid", default=None)
    run.add_argument("--min-conviction-grid", default=None)
    run.add_argument("--sector-cap-grid", default=None)
    run.add_argument("--skip-timing-wait-grid", default=None)
    run.add_argument("--exit-confirm-screens-grid", default=None)
    run.add_argument(
        "--include-churn-knobs",
        action="store_true",
        help="Sweep exit_confirm_screens in addition to decision-review knobs",
    )
    run.add_argument("--n-folds", type=int, default=3)
    run.add_argument("--cost-drag-lambda", type=float, default=0.5)
    run.add_argument("--stability-penalty", type=float, default=0.25)
    run.add_argument("--archive-dir", type=Path, default=None)
    run.add_argument("--fetch-prices", action="store_true")
    run.add_argument(
        "--no-cohort-fitness",
        action="store_true",
        help="Disable cohort-selection fitness (portfolio replay only)",
    )
    run.add_argument(
        "--cohort-weight",
        type=float,
        default=None,
        help="Blend weight for cohort fitness when enabled (default 0.6 for AI tracks)",
    )
    run.add_argument(
        "--ranking-mode",
        default=RANKING_WALK_FORWARD,
        choices=sorted(VALID_RANKING_MODES),
        help=(
            f"{RANKING_WALK_FORWARD} (default), {RANKING_FULL_PERIOD} for shadow bootstrap, "
            f"or {RANKING_BLENDED}"
        ),
    )
    run.add_argument(
        "--bootstrap-top-n",
        type=int,
        default=DEFAULT_BOOTSTRAP_TOP_N,
        help="How many top priors to keep for competing shadow sims (default 3)",
    )
    run.add_argument(
        "--write",
        action="store_true",
        help=f"Write {KNOB_CALIBRATION_PRIORS_FILENAME} under --paper-root",
    )
    run.add_argument("--json", action="store_true")
    run.add_argument(
        "--allow-empty",
        action="store_true",
        help="Exit 0 even when no candidates were scored",
    )
    run.add_argument(
        "--spawn-shadow",
        action="store_true",
        help="Spawn competing calibrated shadow tracks from bootstrap_priors",
    )
    run.add_argument(
        "--require-ready-for-shadow",
        action="store_true",
        help="With --spawn-shadow, require ready_for_shadow_bootstrap",
    )
    run.add_argument(
        "--force-respawn",
        action="store_true",
        help="With --spawn-shadow, reset funds and recreate shadow configs",
    )
    run.set_defaults(func=_cmd_run)

    spawn = sub.add_parser(
        "spawn-shadow",
        parents=[common],
        help="Spawn ai_judgment calibrated shadow track(s) from priors artifact",
    )
    spawn.add_argument(
        "--top-n",
        type=int,
        default=1,
        help="Spawn top N competing shadows from bootstrap_priors (default 1)",
    )
    spawn.add_argument(
        "--require-ready",
        action="store_true",
        help="Require ready_for_shadow_bootstrap before spawning",
    )
    spawn.add_argument(
        "--force-respawn",
        action="store_true",
        help="Reset fund and recreate shadow config",
    )
    spawn.add_argument("--json", action="store_true")
    spawn.set_defaults(func=_cmd_spawn_shadow)

    status = sub.add_parser("status", parents=[common], help="Show last calibration artifact")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=_cmd_status)

    endurance = sub.add_parser(
        "endurance",
        parents=[common],
        help="Refresh forward endurance ledger for calibrated shadows",
    )
    endurance.add_argument("--min-marks", type=int, default=4)
    endurance.add_argument("--min-excess", type=float, default=0.0)
    endurance.add_argument(
        "--fetch-benchmark",
        action="store_true",
        help="Fetch ^FTSE for post-seed excess when decision_review epoch is thin",
    )
    endurance.add_argument("--json", action="store_true")
    endurance.set_defaults(func=_cmd_endurance)

    warm = sub.add_parser(
        "warm-start-shadow",
        parents=[common],
        help=(
            "PIT warm-start calibrated shadows from parent rebalance_log replay, "
            "then freeze a forward-only endurance zero datum (Sunday / manual only)"
        ),
    )
    warm.add_argument(
        "--rank",
        type=int,
        default=None,
        help="Single shadow rank (default: all discovered calibrated shadows)",
    )
    warm.add_argument(
        "--parent-track",
        default="ai_judgment",
        help="Parent track whose rebalance_log is replayed (default: ai_judgment)",
    )
    warm.add_argument(
        "--sim-start",
        default=None,
        help="ISO timestamp — only replay acted log passes on/after this time",
    )
    warm.add_argument(
        "--source",
        default="log",
        choices=["log"],
        help="Seed source (log = PIT rebalance_log materialize; archive later)",
    )
    warm.add_argument(
        "--force",
        action="store_true",
        help="Re-seed even when endurance_zero_datum already exists",
    )
    warm.add_argument("--json", action="store_true")
    warm.set_defaults(func=_cmd_warm_start_shadow)

    args = parser.parse_args(argv)
    if args.command == "run" and args.track_dir is None:
        dirs = learning_track_dirs(Path(args.paper_root))
        if not any(dirs.get(track_id) for track_id in args.tracks.split(",")):
            print(f"No track directories under {args.paper_root}", file=sys.stderr)
            return 1
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
