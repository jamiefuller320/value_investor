"""CLI for monthly horizon scan synthesis and manual defer/fragment actions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.cursor_api_key import resolve_cursor_api_key
from value_investor.deferred_ideas import DEFAULT_STORE, write_markdown
from value_investor.horizon_scan import (
    COMMITTED_REVIEW_MD_PATH,
    COMMITTED_REVIEW_PATH,
    COMMITTED_TASKS_PATH,
    DEFAULT_DATA_DIR,
    DEFAULT_OUTPUT_DIR,
    apply_fragment_actions,
    apply_park_proposals,
    build_horizon_payload,
    compile_horizon_tasks,
    has_enough_horizon_inputs,
    load_horizon_tasks,
    parse_horizon_scan,
    parse_park_proposals,
    promote_horizon_engineering_tasks,
    run_horizon_scan,
)

DEFAULT_MARKDOWN = Path("docs/deferred-review.md")


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2))


def _cmd_payload(args: argparse.Namespace) -> int:
    payload = build_horizon_payload(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        deferred_path=args.deferred_store,
    )
    ok, note = has_enough_horizon_inputs(payload)
    payload["ready"] = ok
    payload["readiness_note"] = note
    if args.json:
        _print_json(payload)
    else:
        print(
            f"ready={ok} fragments={len(payload.get('open_fragments') or [])} "
            f"deferred={len(payload.get('open_deferred_ideas') or [])} — {note}"
        )
    return 0 if ok or args.allow_thin else 1


def _cmd_run(args: argparse.Namespace) -> int:
    api_key = (args.api_key or "").strip() or resolve_cursor_api_key()[0]
    if not api_key:
        print("CURSOR_API_KEY required for horizon scan run", file=sys.stderr)
        return 1
    review = run_horizon_scan(
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        deferred_path=args.deferred_store,
        api_key=api_key,
        model=args.model,
        compile_tasks=not args.no_compile_tasks,
        apply_park=args.apply_park,
        apply_fragments=args.apply_fragments,
    )
    if args.apply_park or args.apply_fragments:
        write_markdown(store_path=args.deferred_store, markdown_path=args.markdown)
    if args.json:
        _print_json(
            {
                "review_path": str(COMMITTED_REVIEW_PATH),
                "tasks_path": str(COMMITTED_TASKS_PATH),
                "sections": {
                    "stage_readiness": review.stage_readiness,
                    "evidence_strands": review.evidence_strands,
                    "automation_risks": review.automation_risks,
                    "counterfactual_gaps": review.counterfactual_gaps,
                    "fragment_clustering": review.fragment_clustering,
                    "park": review.park,
                    "accelerate": review.accelerate,
                },
            }
        )
    else:
        print(review.full_text)
    return 0


def _cmd_compile(args: argparse.Namespace) -> int:
    text = args.review_file.read_text(encoding="utf-8")
    review = parse_horizon_scan(text)
    payload = compile_horizon_tasks(review, tasks_path=args.tasks_path)
    if args.json:
        _print_json(payload)
    else:
        print(f"Compiled {payload['task_count']} horizon task(s) → {args.tasks_path}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    payload = load_horizon_tasks(args.tasks_path)
    if args.json:
        _print_json(payload)
        return 0
    tasks = payload.get("tasks") or []
    print(f"Horizon tasks ({len(tasks)}) — {args.tasks_path}")
    for row in tasks:
        print(
            f"  {row.get('id')} [{row.get('status')}] "
            f"{row.get('area')}/{row.get('experiment_type')} → {row.get('promote_to')}"
        )
    return 0


def _cmd_apply_defer(args: argparse.Namespace) -> int:
    text = args.review_file.read_text(encoding="utf-8")
    review = parse_horizon_scan(text)
    proposals = parse_park_proposals(review.park)
    if args.dry_run:
        _print_json({"proposals": proposals})
        return 0
    added = apply_park_proposals(proposals, store_path=args.deferred_store)
    write_markdown(store_path=args.deferred_store, markdown_path=args.markdown)
    if args.json:
        _print_json({"added": added})
    else:
        print(f"Added deferred ideas: {', '.join(added) or '(none — all duplicates)'}")
    return 0


def _cmd_promote_engineering(args: argparse.Namespace) -> int:
    if not args.task_ids and not args.all_engineering:
        print(
            "Pass horizon task id(s) or --all-engineering",
            file=sys.stderr,
        )
        return 1
    result = promote_horizon_engineering_tasks(
        list(args.task_ids) if args.task_ids else None,
        horizon_tasks_path=args.tasks_path,
        engineering_tasks_path=args.engineering_tasks_path,
        promote_all_engineering=args.all_engineering,
    )
    if args.json:
        _print_json(result)
    else:
        print(f"Promoted: {', '.join(result['promoted']) or '(none)'}")
        for row in result["skipped"]:
            print(f"  skipped {row['id']}: {row['reason']}")
        print(f"Engineering tasks → {result['engineering_tasks_path']}")
    return 0


def _cmd_apply_fragments(args: argparse.Namespace) -> int:
    text = args.review_file.read_text(encoding="utf-8")
    review = parse_horizon_scan(text)
    if args.dry_run:
        from value_investor.horizon_scan import parse_fragment_actions

        drops, promotes = parse_fragment_actions(review.fragment_clustering)
        _print_json({"drops": drops, "promotes": promotes})
        return 0
    result = apply_fragment_actions(
        review.fragment_clustering,
        store_path=args.deferred_store,
        promote_to_defer=not args.no_promote_defer,
    )
    write_markdown(store_path=args.deferred_store, markdown_path=args.markdown)
    if args.json:
        _print_json(result)
    else:
        print(f"Dropped fragments: {', '.join(result['dropped_fragments']) or '(none)'}")
        print(f"Promoted fragments: {', '.join(result['promoted_fragments']) or '(none)'}")
        print(f"New deferred ids: {', '.join(result['deferred_ids']) or '(none)'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Monthly strategic horizon scan (read-only; manual defer/fragment apply)"
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--deferred-store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_json_flags(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--json", action="store_true")

    payload = sub.add_parser("payload", help="Show deterministic horizon inputs")
    add_json_flags(payload)
    payload.add_argument("--allow-thin", action="store_true")
    payload.set_defaults(func=_cmd_payload)

    run = sub.add_parser("run", help="Run horizon scan agent")
    add_json_flags(run)
    run.add_argument("--api-key", default=None)
    run.add_argument("--model", default="composer-2.5")
    run.add_argument("--no-compile-tasks", action="store_true")
    run.add_argument(
        "--apply-park",
        action="store_true",
        help="Auto-add PARK bullets to deferred-ideas (default: manual apply-defer)",
    )
    run.add_argument(
        "--apply-fragments",
        action="store_true",
        help="Apply FRAGMENT CLUSTERING DROP/PROMOTE actions (default: manual)",
    )
    run.set_defaults(func=_cmd_run)

    compile_cmd = sub.add_parser("compile", help="Compile ACCELERATE from review markdown")
    add_json_flags(compile_cmd)
    compile_cmd.add_argument("--review-file", type=Path, default=COMMITTED_REVIEW_MD_PATH)
    compile_cmd.add_argument("--tasks-path", type=Path, default=COMMITTED_TASKS_PATH)
    compile_cmd.set_defaults(func=_cmd_compile)

    list_cmd = sub.add_parser("list", help="List horizon tasks")
    add_json_flags(list_cmd)
    list_cmd.add_argument("--tasks-path", type=Path, default=COMMITTED_TASKS_PATH)
    list_cmd.set_defaults(func=_cmd_list)

    apply_defer = sub.add_parser("apply-defer", help="Apply PARK section to deferred-ideas.json")
    add_json_flags(apply_defer)
    apply_defer.add_argument("--review-file", type=Path, default=COMMITTED_REVIEW_MD_PATH)
    apply_defer.add_argument("--dry-run", action="store_true")
    apply_defer.set_defaults(func=_cmd_apply_defer)

    apply_frag = sub.add_parser(
        "apply-fragments",
        help="Apply FRAGMENT CLUSTERING DROP/PROMOTE actions",
    )
    add_json_flags(apply_frag)
    apply_frag.add_argument("--review-file", type=Path, default=COMMITTED_REVIEW_MD_PATH)
    apply_frag.add_argument("--dry-run", action="store_true")
    apply_frag.add_argument(
        "--no-promote-defer",
        action="store_true",
        help="Mark PROMOTE fragments done without creating deferred ideas",
    )
    apply_frag.set_defaults(func=_cmd_apply_fragments)

    promote_eng = sub.add_parser(
        "promote-engineering",
        help="Promote horizon ACCELERATE tasks into engineering_tasks.json",
    )
    add_json_flags(promote_eng)
    promote_eng.add_argument(
        "task_ids",
        nargs="*",
        help="Horizon task ids (e.g. hor-20260811-01). Omit with --all-engineering.",
    )
    promote_eng.add_argument(
        "--all-engineering",
        action="store_true",
        help="Promote all proposed offline_sim/monitoring/paper_churn tasks",
    )
    promote_eng.add_argument("--tasks-path", type=Path, default=COMMITTED_TASKS_PATH)
    promote_eng.add_argument(
        "--engineering-tasks-path",
        type=Path,
        default=Path("docs/data/engineering_tasks.json"),
    )
    promote_eng.set_defaults(func=_cmd_promote_engineering)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
