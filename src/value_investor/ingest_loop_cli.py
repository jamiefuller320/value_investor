"""CLI for the weekday ingest-assess-improve loop."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from value_investor.ingest_loop import (
    DEFAULT_DATA_DIR,
    DEFAULT_HEALTH_LOG_PATH,
    DEFAULT_LATEST_PATH,
    DEFAULT_STALL_RUNS,
    DEFAULT_WEEKDAY_MAX_RUNTIME_SECONDS,
    ingest_health_stalled,
    run_weekday_ingest_loop,
)
from value_investor.research.gap_fill import DEFAULT_SUGGESTIONS_PATH
from value_investor.research.ingest_improvement import (
    DEFAULT_INGEST_REFETCH_MAX_BODIES,
    DEFAULT_WEEKDAY_BATCH_MAX_TARGETS,
    DEFAULT_WEEKDAY_BOOTSTRAP_SEED_CAP,
)

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Weekday ingest-assess loop for live FTSE buy-tier filing coverage",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true")
    common.add_argument(
        "--json-path",
        type=Path,
        default=None,
        help="Write run JSON to this path (for CI; avoids stdout redirect buffering)",
    )
    common.add_argument("--latest-path", type=Path, default=DEFAULT_LATEST_PATH)
    common.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    common.add_argument("--health-log-path", type=Path, default=DEFAULT_HEALTH_LOG_PATH)
    common.add_argument("--suggestions-path", type=Path, default=DEFAULT_SUGGESTIONS_PATH)
    common.add_argument("--max-targets", type=int, default=DEFAULT_WEEKDAY_BATCH_MAX_TARGETS)
    common.add_argument("--stall-runs", type=int, default=DEFAULT_STALL_RUNS)
    common.add_argument("--micro-compile-max-tasks", type=int, default=3)
    common.add_argument(
        "--bootstrap-seed-cap",
        type=int,
        default=DEFAULT_WEEKDAY_BOOTSTRAP_SEED_CAP,
        help="Max buy-tier canonical indexes to seed per run (weekday default is lower than Sunday)",
    )
    common.add_argument(
        "--max-runtime-seconds",
        type=float,
        default=DEFAULT_WEEKDAY_MAX_RUNTIME_SECONDS,
        help="Stop ingest-improvement targets after this many seconds (partial run)",
    )
    common.add_argument(
        "--max-bodies",
        type=int,
        default=DEFAULT_INGEST_REFETCH_MAX_BODIES,
        help="Max filing bodies to refetch per ticker (backfill bursts: 40)",
    )
    common.add_argument(
        "--record-gap-closure",
        action="store_true",
        help="Record this run in docs/data/ingest_gap_closure_runs.json for horizon/analysis review",
    )
    common.add_argument(
        "--record-trial",
        action="store_true",
        help="Deprecated alias for --record-gap-closure",
    )
    common.add_argument(
        "--gap-closure-title",
        type=str,
        default="",
        help="Title when --record-gap-closure is set",
    )
    common.add_argument(
        "--trial-title",
        type=str,
        default="",
        help="Deprecated alias for --gap-closure-title",
    )
    common.add_argument(
        "--gap-closure-summary",
        type=str,
        default="",
        help="Summary when --record-gap-closure is set",
    )
    common.add_argument(
        "--trial-summary",
        type=str,
        default="",
        help="Deprecated alias for --gap-closure-summary",
    )
    common.add_argument(
        "--gap-closure-review-trigger",
        type=str,
        default="horizon_scan",
        choices=("horizon_scan", "analysis_review", "both"),
        help="Which review cadence should surface this run",
    )
    common.add_argument(
        "--trial-review-trigger",
        type=str,
        default="horizon_scan",
        choices=("horizon_scan", "analysis_review", "both"),
        help="Deprecated alias for --gap-closure-review-trigger",
    )
    common.add_argument(
        "--pin-ticker",
        type=str,
        default="",
        help="Restrict ingest-improvement to this buy-tier ticker (gap-closure reruns)",
    )
    common.add_argument(
        "--gap-closure-parent-id",
        type=str,
        default="",
        help="Parent gap-closure run id when recording a verification rerun",
    )
    common.add_argument(
        "--trial-parent-id",
        type=str,
        default="",
        help="Deprecated alias for --gap-closure-parent-id",
    )
    common.add_argument(
        "--gap-closure-trigger",
        type=str,
        default="",
        help="Orchestration trigger label (weekly_followup, eng_idle, verification_rerun, manual)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser(
        "run",
        parents=[common],
        help="Run ingest improvement, log health, maybe micro-compile tasks",
    )
    run_p.set_defaults(func=_cmd_run)

    status_p = sub.add_parser(
        "status",
        parents=[common],
        help="Report whether ingest health is stalled",
    )
    status_p.set_defaults(func=_cmd_status)

    args = parser.parse_args(argv)
    return int(args.func(args))


def _emit_json(payload: dict[str, Any], args: argparse.Namespace) -> None:
    text = json.dumps(payload, indent=2)
    if args.json_path is not None:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    if args.json:
        print(text)
        sys.stdout.flush()


def _gap_closure_spec(args: argparse.Namespace) -> dict[str, Any] | None:
    if not (args.record_gap_closure or args.record_trial):
        return None
    title = args.gap_closure_title or args.trial_title or "Ingest gap-closure run"
    summary = args.gap_closure_summary or args.trial_summary or ""
    review_trigger = args.gap_closure_review_trigger or args.trial_review_trigger
    parent_id = args.gap_closure_parent_id or args.trial_parent_id or ""
    spec: dict[str, Any] = {
        "title": title,
        "summary": summary,
        "review_trigger": review_trigger,
        "parent_run_id": parent_id,
    }
    if args.gap_closure_trigger:
        spec["trigger"] = args.gap_closure_trigger
    return spec


def _cmd_run(args: argparse.Namespace) -> int:
    exit_code = 0
    result = None
    error: str | None = None
    try:
        pin_tickers = (
            [args.pin_ticker.strip().upper()] if str(args.pin_ticker or "").strip() else None
        )
        result = run_weekday_ingest_loop(
            latest_path=args.latest_path,
            data_dir=args.data_dir,
            health_log_path=args.health_log_path,
            suggestions_path=args.suggestions_path,
            max_targets=args.max_targets,
            stall_runs=args.stall_runs,
            micro_compile_max_tasks=args.micro_compile_max_tasks,
            bootstrap_seed_cap=args.bootstrap_seed_cap,
            max_runtime_seconds=args.max_runtime_seconds,
            max_bodies=args.max_bodies,
            pin_tickers=pin_tickers,
            record_gap_closure=_gap_closure_spec(args),
        )
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        logger.exception("Weekday ingest loop failed")
        exit_code = 1

    if args.json or args.json_path is not None:
        if result is not None:
            payload = result.to_dict()
        else:
            payload = {
                "health_before": {},
                "health_after": {},
                "ingest_summary": None,
                "micro_compiled": False,
                "micro_compile": {},
                "gap_closure_compiled": False,
                "gap_closure_compile": {},
                "stalled": False,
                "partial": False,
            }
        if error:
            payload["error"] = error
        _emit_json(payload, args)
    elif result is not None:
        before = result.health_before.get("zero_body_buy_tier")
        after = result.health_after.get("zero_body_buy_tier")
        print(
            f"Ingest loop complete: zero_body_buy_tier {before} → {after}; "
            f"stalled={result.stalled}; micro_compiled={result.micro_compiled}; "
            f"gap_closure_compiled={result.gap_closure_compiled}; partial={result.partial}"
        )
        if result.micro_compiled:
            print(f"  added tasks: {', '.join(result.micro_compile.get('task_ids') or [])}")
        if result.gap_closure_compiled:
            print(
                f"  gap-closure tasks: {', '.join(result.gap_closure_compile.get('task_ids') or [])}"
            )
    elif error:
        print(f"Ingest loop failed: {error}", file=sys.stderr)

    if result is not None and result.partial and exit_code == 0:
        logger.warning("Ingest loop finished partial run (runtime budget or cutoff)")
    return exit_code


def _cmd_status(args: argparse.Namespace) -> int:
    stalled = ingest_health_stalled(args.health_log_path, min_runs=args.stall_runs)
    payload = {"stalled": stalled, "stall_runs": args.stall_runs}
    if args.json or args.json_path is not None:
        _emit_json(payload, args)
    else:
        print(f"Ingest health stalled={stalled} (window={args.stall_runs} runs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
