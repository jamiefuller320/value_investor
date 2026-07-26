"""CLI for supervised engineering tasks and dev-agent runs."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from value_investor.agent_model_policy import load_policy, spend_since_checkpoint_usd, spend_checkpoint_usd
from value_investor.cursor_api_key import resolve_cursor_api_key
from value_investor.engineering_agent import (
    DEFAULT_ESTIMATED_USD,
    record_engineering_spend,
    run_engineering_agent,
)
from value_investor.engineering_tasks import (
    COMMITTED_TASKS_PATH,
    DEFAULT_MAX_COMPILE_TASKS,
    DEFAULT_MAX_RUN_TASKS,
    DEFAULT_TASKS_PATH,
    compile_engineering_tasks,
    load_engineering_tasks,
    mark_task_merged_for_branch,
    mark_task_status,
    select_engineering_tasks,
    sync_committed_engineering_tasks,
)
from value_investor.engineering_queue import (
    evaluate_engineering_dispatch,
    reconcile_orphaned_pr_open_tasks,
    reprioritize_queue_after_ingest_merge,
)


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2))


def _resolve_tasks_path(explicit: Path) -> Path:
    if explicit != DEFAULT_TASKS_PATH:
        return explicit
    if COMMITTED_TASKS_PATH.exists():
        return COMMITTED_TASKS_PATH
    return explicit


def _cmd_compile(args: argparse.Namespace) -> int:
    payload = compile_engineering_tasks(
        output_dir=args.output_dir,
        suggestions_path=args.suggestions_path,
        max_tasks=args.max_tasks,
        tasks_path=args.tasks_path,
    )
    if args.json:
        _print_json(payload)
    else:
        print(f"Compiled {payload['task_count']} engineering task(s) → {args.tasks_path}")
        for row in payload.get("tasks") or []:
            print(
                f"  {row['id']} [{row['area']}/{row['priority']}] "
                f"{row['title'][:100]}"
            )
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    tasks_path = _resolve_tasks_path(args.tasks_path)
    payload = load_engineering_tasks(tasks_path)
    tasks = payload.get("tasks") or []
    if args.json:
        _print_json(payload)
        return 0
    print(f"Engineering tasks ({len(tasks)}) — {tasks_path}")
    for row in tasks:
        print(
            f"  {row.get('id')} [{row.get('status')}] "
            f"{row.get('area')}/{row.get('priority')} — {str(row.get('title') or '')[:100]}"
        )
    return 0


def _cmd_queue_status(args: argparse.Namespace) -> int:
    tasks_path = _resolve_tasks_path(args.tasks_path)
    open_prs: list[dict] = []
    if args.open_prs_json:
        open_prs = json.loads(Path(args.open_prs_json).read_text(encoding="utf-8"))
    decision = evaluate_engineering_dispatch(
        tasks_path=tasks_path,
        policy_path=args.policy,
        open_prs=open_prs,
        engineering_agent_running=args.agent_running,
        force=args.force,
    )
    if args.json:
        _print_json(decision.to_dict())
    else:
        status = decision.status
        print(f"Dispatch: {decision.should_dispatch} — {decision.reason}")
        print(
            f"Queue open={status.open_count} pr_open={status.pr_open_count} "
            f"merged={status.merged_count} failed={status.failed_count}"
        )
        if status.next_task:
            print(f"Next task: {status.next_task.id} — {status.next_task.title[:100]}")
        if status.in_flight_pr:
            print(f"In-flight PR: #{status.in_flight_pr} ({status.in_flight_branch})")
    return 0 if decision.should_dispatch or not args.require_dispatch else 1


def _cmd_mark_merged(args: argparse.Namespace) -> int:
    updated = mark_task_merged_for_branch(
        args.branch,
        path=_resolve_tasks_path(args.tasks_path),
        pr_url=args.pr_url,
        pr_number=args.pr_number,
    )
    if updated is None:
        print(f"No engineering task matched branch {args.branch}", file=sys.stderr)
        return 1
    if args.json:
        _print_json(updated.to_dict())
    else:
        print(f"Marked {updated.id} as merged")
    return 0


def _cmd_sync_queue(args: argparse.Namespace) -> int:
    payload = sync_committed_engineering_tasks(
        output_path=args.output_dir / "engineering_tasks.json",
        committed_path=args.tasks_path,
    )
    if payload is None:
        print("No engineering queue to sync", file=sys.stderr)
        return 1
    if args.json:
        _print_json({"task_count": payload.get("task_count"), "path": str(args.tasks_path)})
    else:
        print(f"Synced {payload.get('task_count')} task(s) → {args.tasks_path}")
    return 0


def _cmd_reconcile_queue(args: argparse.Namespace) -> int:
    tasks_path = _resolve_tasks_path(args.tasks_path)
    open_prs: list[dict] = []
    if args.open_prs_json:
        open_prs = json.loads(Path(args.open_prs_json).read_text(encoding="utf-8"))
    result = reconcile_orphaned_pr_open_tasks(tasks_path=tasks_path, open_prs=open_prs)
    if args.json:
        _print_json(result)
    else:
        if result["count"]:
            print(f"Reset orphaned pr_open task(s): {', '.join(result['reset'])}")
        else:
            print("No orphaned pr_open tasks")
    return 0


def _cmd_mark_pr_open(args: argparse.Namespace) -> int:
    updated = mark_task_status(
        args.task_id,
        "pr_open",
        path=_resolve_tasks_path(args.tasks_path),
        result_path=args.result_path,
        branch_name=args.branch,
    )
    if updated is None:
        print(f"No engineering task matched id {args.task_id}", file=sys.stderr)
        return 1
    if args.json:
        _print_json(updated.to_dict())
    else:
        print(f"Marked {updated.id} as pr_open on {args.branch}")
    return 0


def _cmd_reprioritize(args: argparse.Namespace) -> int:
    tasks_path = _resolve_tasks_path(args.tasks_path)
    result = reprioritize_queue_after_ingest_merge(
        merged_task_id=args.merged_task_id,
        tasks_path=tasks_path,
        latest_path=args.latest_path,
    )
    if args.json:
        _print_json(result)
    else:
        if result.get("skipped"):
            print(f"Skipped reprioritize: {result.get('reason')}")
        else:
            print(
                f"Reprioritized after {result.get('merged_task_id')} "
                f"(improved={result.get('improved')}, "
                f"adjustments={len(result.get('adjustments') or [])})"
            )
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    if not args.api_key:
        print("CURSOR_API_KEY required for engineering run", file=sys.stderr)
        return 1

    policy = load_policy(args.policy)
    since = spend_since_checkpoint_usd(policy)
    limit = spend_checkpoint_usd(policy)
    if since >= limit and not args.force:
        print(
            f"Ad-hoc spend checkpoint reached (${since:.2f} / ${limit:.2f}). "
            "Approve checkpoint or pass --force.",
            file=sys.stderr,
        )
        return 2

    tasks_path = _resolve_tasks_path(args.tasks_path)
    tasks = select_engineering_tasks(
        path=tasks_path,
        task_id=args.task_id,
        max_tasks=args.max_tasks,
    )
    if not tasks:
        print("No open engineering tasks. Run `ftse-engineering compile` first.", file=sys.stderr)
        return 1

    if args.dry_run:
        if args.json:
            _print_json({"tasks": [task.to_dict() for task in tasks]})
        else:
            for task in tasks:
                print(f"Would run {task.id}: {task.title}")
        return 0

    exit_code = 0
    for task in tasks:
        try:
            result = run_engineering_agent(
                task=task,
                output_dir=args.output_dir,
                api_key=args.api_key,
                model=args.model,
            )
        except RuntimeError as err:
            print(str(err), file=sys.stderr)
            mark_task_status(task.id, "failed", path=tasks_path)
            exit_code = 2
            continue

        if not args.no_record_spend:
            spend_status = record_engineering_spend(
                path=args.policy,
                estimated_usd=args.estimated_usd,
            )
            print(
                "Ad-hoc spend recorded: "
                f"${spend_status['spend_since_checkpoint_usd']:.2f} / "
                f"${spend_status['spend_checkpoint_usd']:.2f}"
            )

        branch = f"cursor/{task.id}-1de3"
        if not args.defer_pr_open:
            mark_task_status(
                task.id,
                "pr_open",
                path=tasks_path,
                result_path=str(result.result_path),
                branch_name=branch,
            )
        print(f"Completed {task.id} → {result.result_path}")

        if args.create_branch:
            subprocess.run(["git", "checkout", "-b", branch], check=False)
            subprocess.run(["git", "add", "-A"], check=False)
            subprocess.run(
                [
                    "git",
                    "commit",
                    "-m",
                    f"feat(engineering): {task.title[:72]}",
                ],
                check=False,
            )
            print(f"Committed on branch {branch} (push and open PR manually or via workflow)")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compile and run supervised engineering tasks from weekly run artifacts"
    )
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--tasks-path", type=Path, default=COMMITTED_TASKS_PATH)
    parser.add_argument(
        "--suggestions-path",
        type=Path,
        default=Path("docs/data/research_model_suggestions.json"),
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("docs/data/library/policy.json"),
        help="Library policy JSON for ad-hoc spend checkpoint",
    )
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    compile_p = sub.add_parser("compile", help="Build engineering_tasks.json from run artifacts")
    compile_p.add_argument("--max-tasks", type=int, default=DEFAULT_MAX_COMPILE_TASKS)
    compile_p.set_defaults(func=_cmd_compile)

    list_p = sub.add_parser("list", help="List compiled engineering tasks")
    list_p.set_defaults(func=_cmd_list)

    queue_p = sub.add_parser("queue-status", help="Evaluate whether to auto-dispatch the next task")
    queue_p.add_argument(
        "--open-prs-json",
        default=None,
        help="Path to JSON array of open PRs from gh pr list --json ...",
    )
    queue_p.add_argument(
        "--agent-running",
        action="store_true",
        help="Set when engineering-agent workflow is already in progress",
    )
    queue_p.add_argument(
        "--require-dispatch",
        action="store_true",
        help="Exit 1 unless dispatch is recommended (for workflow gates)",
    )
    queue_p.add_argument("--force", action="store_true")
    queue_p.set_defaults(func=_cmd_queue_status)

    sync_p = sub.add_parser("sync-queue", help="Copy output/engineering_tasks.json to committed queue path")
    sync_p.set_defaults(func=_cmd_sync_queue)

    reconcile_p = sub.add_parser(
        "reconcile-queue",
        help="Reset pr_open tasks that have no matching open engineering PR",
    )
    reconcile_p.add_argument(
        "--open-prs-json",
        default=None,
        help="Path to JSON array of open PRs from gh pr list --json ...",
    )
    reconcile_p.set_defaults(func=_cmd_reconcile_queue)

    mark_pr_open_p = sub.add_parser(
        "mark-pr-open",
        help="Mark an engineering task pr_open after a draft PR is created",
    )
    mark_pr_open_p.add_argument("--task-id", required=True)
    mark_pr_open_p.add_argument("--branch", required=True)
    mark_pr_open_p.add_argument("--result-path", required=True)
    mark_pr_open_p.set_defaults(func=_cmd_mark_pr_open)

    merged_p = sub.add_parser("mark-merged", help="Mark an engineering task merged from a branch name")
    merged_p.add_argument("--branch", required=True)
    merged_p.add_argument("--pr-url", default=None)
    merged_p.add_argument("--pr-number", type=int, default=None)
    merged_p.set_defaults(func=_cmd_mark_merged)

    reprioritize_p = sub.add_parser(
        "reprioritize",
        help="Deterministically adjust open queue priorities after an ingest merge",
    )
    reprioritize_p.add_argument("--merged-task-id", required=True)
    reprioritize_p.add_argument(
        "--latest-path",
        type=Path,
        default=Path("docs/data/latest.json"),
    )
    reprioritize_p.set_defaults(func=_cmd_reprioritize)

    run_p = sub.add_parser("run", help="Run the supervised dev agent for open task(s)")
    run_p.add_argument("--task-id", default=None, help="Specific task id (default: top priority)")
    run_p.add_argument("--max-tasks", type=int, default=DEFAULT_MAX_RUN_TASKS)
    run_p.add_argument("--model", default="composer-2.5")
    run_p.add_argument(
        "--api-key",
        default=(resolve_cursor_api_key()[0] or None),
        help="Cursor API key (default: CURSOR_API_KEY_V2 then CURSOR_API_KEY)",
    )
    run_p.add_argument("--dry-run", action="store_true")
    run_p.add_argument("--force", action="store_true", help="Run even if ad-hoc checkpoint reached")
    run_p.add_argument("--no-record-spend", action="store_true")
    run_p.add_argument(
        "--estimated-usd",
        type=float,
        default=DEFAULT_ESTIMATED_USD,
        help="Estimated Cursor spend to record against ad-hoc checkpoint",
    )
    run_p.add_argument(
        "--create-branch",
        action="store_true",
        help="After agent run, git checkout -b cursor/<task-id>-1de3 and commit changes",
    )
    run_p.add_argument(
        "--defer-pr-open",
        action="store_true",
        help="Do not mark task pr_open until workflow creates the draft PR",
    )
    run_p.set_defaults(func=_cmd_run)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
