"""CLI for weekly Learning Director synthesis."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.cursor_api_key import resolve_cursor_api_key
from value_investor.learning_director import (
    COMMITTED_REVIEW_PATH,
    COMMITTED_TASKS_PATH,
    DEFAULT_DATA_DIR,
    DEFAULT_OUTPUT_DIR,
    build_learning_director_payload,
    compile_horizon_fragments,
    compile_learning_director_tasks,
    has_enough_learning_director_inputs,
    parse_learning_director_review,
    parse_horizon_fragment_lines,
    run_learning_director,
)
from value_investor.learning_director_regime import VISION_PATH
from value_investor.review_policy import (
    DEFAULT_REVIEW_POLICY_PATH,
    learning_director_enabled,
    load_review_policy,
)
from value_investor.storage import read_json


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2))


def _cmd_status(args: argparse.Namespace) -> int:
    policy = load_review_policy(args.policy_path)
    payload = {
        "enabled": learning_director_enabled(args.policy_path),
        "policy": policy,
        "vision_path": str(args.vision_path),
        "review_path": str(COMMITTED_REVIEW_PATH),
        "tasks_path": str(COMMITTED_TASKS_PATH),
    }
    if args.json:
        _print_json(payload)
    else:
        enabled = payload["enabled"]
        print(f"learning_director enabled={enabled}")
        print(f"  policy: {args.policy_path}")
        print(f"  vision: {args.vision_path}")
        print(f"  review: {COMMITTED_REVIEW_PATH}")
        print(f"  tasks:  {COMMITTED_TASKS_PATH}")
    return 0


def _cmd_payload(args: argparse.Namespace) -> int:
    payload = build_learning_director_payload(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        vision_path=args.vision_path,
    )
    ok, note = has_enough_learning_director_inputs(payload)
    payload["ready"] = ok
    payload["readiness_note"] = note
    if args.json:
        _print_json(payload)
    else:
        print(f"ready={ok} history_runs={payload.get('history_run_count')} — {note}")
    return 0 if ok or args.allow_thin else 1


def _cmd_run(args: argparse.Namespace) -> int:
    if not learning_director_enabled(args.policy_path):
        print("learning_director disabled in review_policy.json", file=sys.stderr)
        return 0 if args.allow_disabled else 2
    api_key = (args.api_key or "").strip() or resolve_cursor_api_key()[0]
    if not api_key:
        print("CURSOR_API_KEY required for learning director run", file=sys.stderr)
        return 1
    review = run_learning_director(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        vision_path=args.vision_path,
        api_key=api_key,
        model=args.model,
        compile_tasks=not args.no_compile_tasks,
        compile_fragments=not args.no_compile_fragments,
        policy_path=args.policy_path,
    )
    if args.json:
        _print_json(
            {
                "review_path": str(COMMITTED_REVIEW_PATH),
                "tasks_path": str(COMMITTED_TASKS_PATH),
                "sections": {
                    "regime_assumption_check": review.regime_assumption_check,
                    "convergence": review.convergence,
                    "complexity_inventory": review.complexity_inventory,
                    "vision_roadmap_review": review.vision_roadmap_review,
                    "proposed_actions": review.proposed_actions,
                    "horizon_fragments": review.horizon_fragments,
                    "defer": review.defer,
                },
            }
        )
    else:
        print(review.full_text)
    return 0


def _cmd_compile(args: argparse.Namespace) -> int:
    text = args.review_file.read_text(encoding="utf-8")
    review = parse_learning_director_review(text)
    payload = compile_learning_director_tasks(
        review,
        run_stamp=args.run_stamp,
        tasks_path=args.tasks_path,
    )
    if args.json:
        _print_json(payload)
    else:
        print(f"Compiled {payload['task_count']} task(s) → {args.tasks_path}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    payload = read_json(args.tasks_path) or {"tasks": []}
    if args.json:
        _print_json(payload)
        return 0
    for row in payload.get("tasks") or []:
        print(
            f"{row.get('id')} [{row.get('status')}] "
            f"{row.get('area')}/{row.get('experiment_type')} → {row.get('promote_to')}"
        )
        print(f"  {row.get('title')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Weekly observe-only Learning Director synthesis. "
            "Disable via review_policy.json before live capital cutover."
        )
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--vision-path", type=Path, default=VISION_PATH)
    parser.add_argument(
        "--policy-path",
        type=Path,
        default=DEFAULT_REVIEW_POLICY_PATH,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="Show enable flag and artifact paths")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=_cmd_status)

    payload = sub.add_parser("payload", help="Build agent input payload")
    payload.add_argument("--json", action="store_true")
    payload.add_argument("--allow-thin", action="store_true")
    payload.set_defaults(func=_cmd_payload)

    run = sub.add_parser("run", help="Run agent synthesis when enabled")
    run.add_argument("--json", action="store_true")
    run.add_argument("--api-key", default="")
    run.add_argument("--model", default="composer-2.5")
    run.add_argument("--no-compile-tasks", action="store_true")
    run.add_argument("--no-compile-fragments", action="store_true")
    run.add_argument(
        "--allow-disabled",
        action="store_true",
        help="Exit 0 when disabled (for workflow gating)",
    )
    run.set_defaults(func=_cmd_run)

    compile_cmd = sub.add_parser("compile", help="Compile tasks from a review markdown/text file")
    compile_cmd.add_argument("review_file", type=Path)
    compile_cmd.add_argument("--run-stamp", default=None)
    compile_cmd.add_argument("--tasks-path", type=Path, default=COMMITTED_TASKS_PATH)
    compile_cmd.add_argument("--json", action="store_true")
    compile_cmd.set_defaults(func=_cmd_compile)

    list_cmd = sub.add_parser("list", help="List proposed learning-director tasks")
    list_cmd.add_argument("--tasks-path", type=Path, default=COMMITTED_TASKS_PATH)
    list_cmd.add_argument("--json", action="store_true")
    list_cmd.set_defaults(func=_cmd_list)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
