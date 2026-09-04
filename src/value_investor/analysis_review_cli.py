"""CLI for modelling/analysis review synthesis and manual promotion."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.analysis_review import (
    COMMITTED_REVIEW_PATH,
    COMMITTED_TASKS_PATH,
    DEFAULT_DATA_DIR,
    DEFAULT_OUTPUT_DIR,
    build_analysis_payload,
    compile_analysis_tasks,
    compile_and_maybe_promote_system_gaps,
    has_enough_analysis_inputs,
    load_analysis_tasks,
    parse_analysis_review,
    promote_analysis_tasks,
    run_analysis_review,
)
from value_investor.cursor_api_key import resolve_cursor_api_key
from value_investor.system_gap_analysis import (
    COMMITTED_GAPS_PATH,
    build_system_gap_snapshot,
    write_system_gap_snapshot,
)


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2))


def _cmd_payload(args: argparse.Namespace) -> int:
    payload = build_analysis_payload(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
    )
    ok, note = has_enough_analysis_inputs(payload)
    payload["ready"] = ok
    payload["readiness_note"] = note
    if args.json:
        _print_json(payload)
    else:
        print(f"ready={ok} history_runs={payload.get('history_run_count')} — {note}")
    return 0 if ok or args.allow_thin else 1


def _cmd_run(args: argparse.Namespace) -> int:
    api_key = (args.api_key or "").strip() or resolve_cursor_api_key()[0]
    if not api_key:
        print("CURSOR_API_KEY required for analysis review run", file=sys.stderr)
        return 1
    review = run_analysis_review(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        api_key=api_key,
        model=args.model,
        compile_tasks=not args.no_compile_tasks,
    )
    if args.json:
        _print_json(
            {
                "review_path": str(COMMITTED_REVIEW_PATH),
                "tasks_path": str(COMMITTED_TASKS_PATH),
                "sections": {
                    "executive_summary": review.executive_summary,
                    "performance_diagnosis": review.performance_diagnosis,
                    "signal_backtest_findings": review.signal_backtest_findings,
                    "paper_track_comparison": review.paper_track_comparison,
                    "system_gaps": review.system_gaps,
                    "proposed_experiments": review.proposed_experiments,
                    "defer": review.defer,
                },
            }
        )
    else:
        print(review.full_text)
    return 0


def _cmd_compile(args: argparse.Namespace) -> int:
    text = args.review_file.read_text(encoding="utf-8")
    review = parse_analysis_review(text)
    payload = compile_analysis_tasks(
        review,
        tasks_path=args.tasks_path,
    )
    if args.json:
        _print_json(payload)
    else:
        print(f"Compiled {payload['task_count']} analysis task(s) → {args.tasks_path}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    payload = load_analysis_tasks(args.tasks_path)
    if args.json:
        _print_json(payload)
        return 0
    tasks = payload.get("tasks") or []
    print(f"Analysis tasks ({len(tasks)}) — {args.tasks_path}")
    for row in tasks:
        print(
            f"  {row.get('id')} [{row.get('status')}] "
            f"{row.get('area')}/{row.get('experiment_type')} → {row.get('promote_to')}"
        )
    return 0


def _cmd_system_gaps(args: argparse.Namespace) -> int:
    snapshot = build_system_gap_snapshot(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
    )
    path = args.write_path or (args.data_dir / COMMITTED_GAPS_PATH.name)
    if args.write:
        write_system_gap_snapshot(snapshot, path=path)
    if args.json:
        _print_json(snapshot)
    else:
        flags = snapshot.get("flags") or []
        print(
            f"system_gaps flags={snapshot.get('flag_count', 0)} "
            f"high={snapshot.get('high_flag_count', 0)}"
        )
        for row in flags:
            print(
                f"  [{row.get('severity')}] {row.get('id')} "
                f"({row.get('layer')}) — {row.get('title')}"
            )
        if args.write:
            print(f"wrote {path}")
    return 0


def _cmd_compile_system_gaps(args: argparse.Namespace) -> int:
    snapshot = None
    if args.gaps_path and Path(args.gaps_path).exists():
        from value_investor.storage import read_json

        snapshot = read_json(args.gaps_path)
    result = compile_and_maybe_promote_system_gaps(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        tasks_path=args.tasks_path,
        engineering_tasks_path=args.engineering_tasks_path,
        promote=args.promote,
        snapshot=snapshot,
    )
    if args.json:
        _print_json(result)
        return 0
    compiled = result.get("compiled") or {}
    print(
        f"Compiled system-gap tasks: {len(compiled.get('compiled') or [])} new, "
        f"{len(compiled.get('refreshed') or [])} refreshed, "
        f"{len(compiled.get('closed') or [])} closed → {args.tasks_path}"
    )
    promoted = result.get("promoted")
    if promoted:
        print(f"Auto-promoted: {', '.join(promoted.get('promoted') or []) or '(none)'}")
        for row in promoted.get("skipped") or []:
            print(f"  skipped {row.get('id')}: {row.get('reason')}")
    return 0


def _cmd_promote(args: argparse.Namespace) -> int:
    if not args.task_id:
        print("At least one --task-id is required", file=sys.stderr)
        return 1
    result = promote_analysis_tasks(
        args.task_id,
        analysis_tasks_path=args.tasks_path,
        engineering_tasks_path=args.engineering_tasks_path,
    )
    if args.json:
        _print_json(result)
    else:
        print(f"Promoted: {', '.join(result['promoted']) or '(none)'}")
        for row in result["skipped"]:
            print(f"  skipped {row['id']}: {row['reason']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Modelling/analysis review synthesis (read-only; manual promotion to engineering)"
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_json_flags(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--json", action="store_true")

    payload = sub.add_parser("payload", help="Show deterministic analysis inputs")
    add_json_flags(payload)
    payload.add_argument("--allow-thin", action="store_true")
    payload.set_defaults(func=_cmd_payload)

    gaps = sub.add_parser(
        "system-gaps",
        help="Write or print the learning-path integrity snapshot (no agent)",
    )
    add_json_flags(gaps)
    gaps.add_argument(
        "--write",
        action="store_true",
        help="Persist docs/data/system_gaps.json (or --write-path)",
    )
    gaps.add_argument("--write-path", type=Path, default=None)
    gaps.set_defaults(func=_cmd_system_gaps)

    run = sub.add_parser("run", help="Run analysis synthesis agent")
    add_json_flags(run)
    run.add_argument("--api-key", default=None)
    run.add_argument("--model", default="composer-2.5")
    run.add_argument("--no-compile-tasks", action="store_true")
    run.set_defaults(func=_cmd_run)

    compile_cmd = sub.add_parser("compile", help="Compile experiments from review markdown")
    add_json_flags(compile_cmd)
    compile_cmd.add_argument(
        "--review-file",
        type=Path,
        default=Path("docs/data/analysis_review.md"),
    )
    compile_cmd.add_argument("--tasks-path", type=Path, default=COMMITTED_TASKS_PATH)
    compile_cmd.set_defaults(func=_cmd_compile)

    list_cmd = sub.add_parser("list", help="List analysis tasks")
    add_json_flags(list_cmd)
    list_cmd.add_argument("--tasks-path", type=Path, default=COMMITTED_TASKS_PATH)
    list_cmd.set_defaults(func=_cmd_list)

    promote = sub.add_parser(
        "promote",
        help="Manually promote analysis tasks into engineering_tasks.json",
    )
    add_json_flags(promote)
    promote.add_argument("--task-id", action="append", default=[])
    promote.add_argument("--tasks-path", type=Path, default=COMMITTED_TASKS_PATH)
    promote.add_argument(
        "--engineering-tasks-path",
        type=Path,
        default=Path("docs/data/engineering_tasks.json"),
    )
    promote.set_defaults(func=_cmd_promote)

    compile_gaps = sub.add_parser(
        "compile-system-gaps",
        help="Compile high system_gaps flags into analysis tasks; optionally auto-promote persist/publish/apply",
    )
    add_json_flags(compile_gaps)
    compile_gaps.add_argument(
        "--promote",
        action="store_true",
        help="Auto-promote persist/publish/apply high flags into engineering_tasks.json (no agent dispatch)",
    )
    compile_gaps.add_argument("--gaps-path", type=Path, default=None)
    compile_gaps.add_argument("--tasks-path", type=Path, default=COMMITTED_TASKS_PATH)
    compile_gaps.add_argument(
        "--engineering-tasks-path",
        type=Path,
        default=Path("docs/data/engineering_tasks.json"),
    )
    compile_gaps.set_defaults(func=_cmd_compile_system_gaps)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
