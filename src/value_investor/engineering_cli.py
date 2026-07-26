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
    DEFAULT_MAX_COMPILE_TASKS,
    DEFAULT_MAX_RUN_TASKS,
    DEFAULT_TASKS_PATH,
    compile_engineering_tasks,
    load_engineering_tasks,
    mark_task_status,
    select_engineering_tasks,
)


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2))


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
    payload = load_engineering_tasks(args.tasks_path)
    tasks = payload.get("tasks") or []
    if args.json:
        _print_json(payload)
        return 0
    print(f"Engineering tasks ({len(tasks)}) — {args.tasks_path}")
    for row in tasks:
        print(
            f"  {row.get('id')} [{row.get('status')}] "
            f"{row.get('area')}/{row.get('priority')} — {str(row.get('title') or '')[:100]}"
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

    tasks = select_engineering_tasks(
        path=args.tasks_path,
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
            mark_task_status(task.id, "failed", path=args.tasks_path)
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

        mark_task_status(
            task.id,
            "completed",
            path=args.tasks_path,
            result_path=str(result.result_path),
        )
        print(f"Completed {task.id} → {result.result_path}")

        if args.create_branch:
            slug = task.id.replace("eng-", "eng-")
            branch = f"cursor/{slug}-1de3"
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
    parser.add_argument("--tasks-path", type=Path, default=DEFAULT_TASKS_PATH)
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
    run_p.set_defaults(func=_cmd_run)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
