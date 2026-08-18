"""CLI for walk-forward knob calibration (observe-only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.knob_calibration import (
    KNOB_CALIBRATION_PRIORS_FILENAME,
    calibrate_learning_tracks,
    calibrate_track,
    grid_axes_from_cli,
    spawn_calibrated_shadow_track,
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
    }
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
        spawn_result = spawn_calibrated_shadow_track(
            Path(args.paper_root),
            force_respawn=bool(args.force_respawn),
        )
    if args.json:
        out = payload if spawn_result is None else {"calibration": payload, "shadow_spawn": spawn_result}
        _print_json(out)
    else:
        if spawn_result is not None:
            if spawn_result.get("spawned"):
                print(
                    f"\nShadow track: {spawn_result.get('shadow_track_id')} "
                    f"at {spawn_result.get('shadow_dir')} "
                    f"(confidence={spawn_result.get('confidence')})"
                )
            else:
                print(f"\nShadow spawn skipped: {spawn_result.get('reason')}", file=sys.stderr)
        if payload.get("scope") == "knob_calibration_multi":
            print("Knob calibration (multi-track, observe-only)")
            for track_id, row in (payload.get("tracks") or {}).items():
                prior = row.get("recommended_prior") or {}
                print(
                    f"  [{track_id}] acted={row.get('readiness', {}).get('acted_entries')} "
                    f"top_score={prior.get('composite_score')} "
                    f"confidence={prior.get('confidence')}"
                )
        else:
            prior = payload.get("recommended_prior") or {}
            print("Knob calibration (observe-only)")
            print(f"  Track: {payload.get('track_id')}")
            print(f"  Acted entries: {payload.get('readiness', {}).get('acted_entries')}")
            print(f"  Grid size: {payload.get('readiness', {}).get('grid_size')}")
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
    result = spawn_calibrated_shadow_track(
        Path(args.paper_root),
        force_respawn=bool(args.force_respawn),
    )
    if args.json:
        _print_json(result)
    elif result.get("spawned"):
        print(f"Spawned {result.get('shadow_track_id')} at {result.get('shadow_dir')}")
        print(f"  Confidence: {result.get('confidence')}")
        print(f"  Changed vs parent: {result.get('changed_vs_parent')}")
        print(f"  Provenance: {result.get('provenance_path')}")
    else:
        print(f"Shadow spawn failed: {result.get('reason')}", file=sys.stderr)
        return 1
    return 0


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
                f"  [{track_id}] confidence={prior.get('confidence')} "
                f"knobs={prior.get('knobs')}"
            )
    else:
        prior = payload.get("recommended_prior") or {}
        print(f"  Track: {payload.get('track_id')}")
        print(f"  Confidence: {prior.get('confidence')}")
        print(f"  Recommended: {prior.get('knobs')}")
    return 0


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
            "Walk-forward knob calibration on rebalance logs (observe-only). "
            "Writes ranked priors for manual seeding — does not auto-apply knobs."
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
        help="Spawn ai_judgment_calibrated shadow track from recommended_prior",
    )
    run.add_argument(
        "--force-respawn",
        action="store_true",
        help="With --spawn-shadow, reset fund and recreate shadow config",
    )
    run.set_defaults(func=_cmd_run)

    spawn = sub.add_parser(
        "spawn-shadow",
        parents=[common],
        help="Spawn ai_judgment calibrated shadow track from priors artifact",
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

    args = parser.parse_args(argv)
    if args.command == "run" and args.track_dir is None:
        dirs = learning_track_dirs(Path(args.paper_root))
        if not any(dirs.get(track_id) for track_id in args.tracks.split(",")):
            print(f"No track directories under {args.paper_root}", file=sys.stderr)
            return 1
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
