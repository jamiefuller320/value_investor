"""CLI for supervised engineering tasks and dev-agent runs."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from value_investor.accelerated_review import (
    evaluate_accelerated_email_only_dispatch,
    evaluate_accelerated_ladder_dispatch,
    evaluate_wednesday_anchor_dispatch,
    record_midweek_email_only_run,
    record_midweek_ladder_run,
)
from value_investor.agent_model_policy import (
    load_policy,
    spend_checkpoint_usd,
    spend_since_checkpoint_usd,
)
from value_investor.ci_fix_tasks import (
    draft_ci_fix_task,
    parse_pytest_failures_from_log,
    task_eligible_for_auto_merge,
)
from value_investor.cli_args import apply_parsed_globals
from value_investor.cursor_api_key import resolve_cursor_api_key
from value_investor.engineering_agent import (
    DEFAULT_ESTIMATED_USD,
    record_engineering_spend,
    run_engineering_agent,
)
from value_investor.engineering_auto_merge import evaluate_auto_merge, perform_auto_merge
from value_investor.engineering_pr_notify import (
    EngineeringPrNotification,
    collect_queue_block_alerts,
    send_engineering_pr_email,
    send_engineering_queue_block_email,
)
from value_investor.engineering_queue import (
    evaluate_engineering_dispatch,
    is_engineering_branch,
    is_safe_to_clear_stale_branch,
    reconcile_orphaned_pr_open_tasks,
    refresh_engineering_queue_ui,
    reprioritize_queue_after_ingest_merge,
    summarize_queue,
    task_id_from_branch,
)
from value_investor.engineering_recovery import (
    record_agent_no_diff_run,
    recover_engineering_queue,
    summarize_parked_tasks,
)
from value_investor.engineering_tasks import (
    COMMITTED_TASKS_PATH,
    DEFAULT_MAX_COMPILE_TASKS,
    DEFAULT_MAX_RUN_TASKS,
    DEFAULT_TASKS_PATH,
    compile_engineering_tasks,
    draft_library_ladder_engineering_tasks,
    find_engineering_task,
    load_engineering_tasks,
    mark_task_merged_for_branch,
    mark_task_status,
    select_engineering_tasks,
    sync_committed_engineering_tasks,
    validate_engineering_pr_paths_for_task_id,
)
from value_investor.storage import read_json


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
            print(f"  {row['id']} [{row['area']}/{row['priority']}] {row['title'][:100]}")
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
        agent_running_count=args.agent_running_count,
        max_parallel=args.max_parallel,
        force=args.force,
    )
    if args.json:
        _print_json(decision.to_dict())
    else:
        status = decision.status
        print(f"Dispatch: {decision.should_dispatch} — {decision.reason}")
        print(
            f"Queue open={status.open_count} pr_open={status.pr_open_count} "
            f"parked={status.parked_count} merged={status.merged_count} "
            f"failed={status.failed_count}"
        )
        if status.next_task:
            print(f"Next task: {status.next_task.id} — {status.next_task.title[:100]}")
        if decision.next_task_ids:
            print(f"Dispatch task ids: {', '.join(decision.next_task_ids)}")
        if status.in_flight_pr:
            print(f"In-flight PR: #{status.in_flight_pr} ({status.in_flight_branch})")
    return 0 if decision.should_dispatch or not args.require_dispatch else 1


def _cmd_refresh_queue_ui(args: argparse.Namespace) -> int:
    result = refresh_engineering_queue_ui()
    if args.json:
        _print_json(result)
    else:
        print(
            f"Refreshed engineering queue UI → {result['automation_path']} "
            f"(open={result.get('open_count')}, pr_open={result.get('pr_open_count')})"
        )
    return 0


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


def _cmd_recover_queue(args: argparse.Namespace) -> int:
    tasks_path = _resolve_tasks_path(args.tasks_path)
    open_prs: list[dict] = []
    if args.open_prs_json:
        open_prs = json.loads(Path(args.open_prs_json).read_text(encoding="utf-8"))
    result = recover_engineering_queue(
        tasks_path=tasks_path,
        open_prs=open_prs,
        apply=not args.dry_run,
        max_agent_retries=args.max_agent_retries,
        retry_cooldown_hours=args.retry_cooldown_hours,
        ci_red_park_hours=args.ci_red_park_hours,
    )
    if args.json:
        _print_json(result.to_dict())
    else:
        if result.merged:
            print(f"Marked merged from GitHub: {', '.join(result.merged)}")
        if result.reconciled:
            print(f"Reconciled orphaned pr_open: {', '.join(result.reconciled)}")
        if result.reopened:
            print(f"Reopened failed tasks: {', '.join(result.reopened)}")
        for action in result.parked:
            print(f"Parked {action.task_id}: {action.reason}")
        if not result.to_dict()["action_count"]:
            print("No queue recovery actions needed")
    return 0


def _cmd_list_parked(args: argparse.Namespace) -> int:
    rows = summarize_parked_tasks(_resolve_tasks_path(args.tasks_path))
    if args.json:
        _print_json({"parked": rows, "count": len(rows)})
    elif not rows:
        print("No parked engineering tasks")
    else:
        for row in rows:
            print(f"{row['id']}: {row.get('parked_reason')}")
    return 0


def _cmd_record_no_diff(args: argparse.Namespace) -> int:
    result = record_agent_no_diff_run(
        str(args.task_id).strip(),
        tasks_path=_resolve_tasks_path(args.tasks_path),
        max_runs=args.max_runs,
    )
    if args.json:
        _print_json(result)
    elif result.get("skipped"):
        print(result.get("reason") or "Skipped no-diff record")
    elif result.get("parked"):
        print(f"Parked {result.get('task_id')} after {result.get('no_diff_count')} no-diff run(s)")
    else:
        print(
            f"Recorded no-diff run for {result.get('task_id')} "
            f"({result.get('no_diff_count')}/{args.max_runs}; "
            f"{result.get('remaining_before_park')} before park)"
        )
    return 0 if result.get("recorded") or result.get("skipped") else 1


def _load_open_prs_json(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return list(payload) if isinstance(payload, list) else []


def _cmd_try_accelerated_email(args: argparse.Namespace) -> int:
    open_prs = _load_open_prs_json(args.open_prs_json)
    status = summarize_queue(
        tasks_path=_resolve_tasks_path(args.tasks_path),
        open_prs=open_prs,
    )
    decision = evaluate_accelerated_email_only_dispatch(
        queue_status=status,
        tasks_path=_resolve_tasks_path(args.tasks_path),
        policy_path=args.policy,
        merged_task_id=str(args.merged_task_id).strip() if args.merged_task_id else None,
    )
    if args.json:
        _print_json(decision.to_dict())
    else:
        print(decision.reason)
    return 0 if decision.should_dispatch or args.allow_skip else 1


def _cmd_record_accelerated_email(args: argparse.Namespace) -> int:
    entry = record_midweek_email_only_run(
        source=str(args.source).strip(),
        merged_task_id=str(args.merged_task_id).strip() if args.merged_task_id else None,
        note=str(args.note).strip() if args.note else None,
    )
    if args.json:
        _print_json({"recorded": entry})
    else:
        print(f"Recorded mid-week email_only run ({entry.get('source')})")
    return 0


def _load_ingest_loop_json(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def _cmd_try_wednesday_anchor(args: argparse.Namespace) -> int:
    open_prs = _load_open_prs_json(args.open_prs_json)
    status = summarize_queue(
        tasks_path=_resolve_tasks_path(args.tasks_path),
        open_prs=open_prs,
    )
    decision = evaluate_wednesday_anchor_dispatch(
        queue_status=status,
        tasks_path=_resolve_tasks_path(args.tasks_path),
        policy_path=args.policy,
        latest_path=Path(args.latest_path),
        ingest_loop=_load_ingest_loop_json(args.ingest_loop_json),
    )
    if args.json:
        _print_json(decision.to_dict())
    else:
        print(decision.reason)
    return 0 if decision.should_dispatch or args.allow_skip else 1


def _cmd_try_accelerated_ladder(args: argparse.Namespace) -> int:
    open_prs = _load_open_prs_json(args.open_prs_json)
    status = summarize_queue(
        tasks_path=_resolve_tasks_path(args.tasks_path),
        open_prs=open_prs,
    )
    decision = evaluate_accelerated_ladder_dispatch(
        queue_status=status,
        tasks_path=_resolve_tasks_path(args.tasks_path),
        policy_path=args.policy,
        merged_task_id=str(args.merged_task_id).strip() if args.merged_task_id else None,
    )
    if args.json:
        _print_json(decision.to_dict())
    else:
        print(decision.reason)
    return 0 if decision.should_dispatch or args.allow_skip else 1


def _cmd_record_accelerated_ladder(args: argparse.Namespace) -> int:
    entry = record_midweek_ladder_run(
        source=str(args.source).strip(),
        merged_task_id=str(args.merged_task_id).strip() if args.merged_task_id else None,
        note=str(args.note).strip() if args.note else None,
    )
    if args.json:
        _print_json({"recorded": entry})
    else:
        print(f"Recorded mid-week ladder_only run ({entry.get('source')})")
    return 0


def _cmd_branch_is_stale(args: argparse.Namespace) -> int:
    open_prs: list[dict] = []
    if args.open_prs_json:
        open_prs = json.loads(Path(args.open_prs_json).read_text(encoding="utf-8"))
    safe = is_safe_to_clear_stale_branch(args.branch, open_prs)
    payload = {"branch": args.branch, "safe_to_clear": safe}
    if args.json:
        _print_json(payload)
    else:
        print(f"{args.branch}: safe_to_clear={safe}")
    return 0 if safe else 1


def _cmd_next_open_id(args: argparse.Namespace) -> int:
    tasks = select_engineering_tasks(path=_resolve_tasks_path(args.tasks_path), max_tasks=1)
    if not tasks:
        print("No open engineering tasks", file=sys.stderr)
        return 1
    print(tasks[0].id)
    return 0


def _cmd_task_title(args: argparse.Namespace) -> int:
    data = load_engineering_tasks(_resolve_tasks_path(args.tasks_path))
    wanted = str(args.task_id).strip()
    for row in data.get("tasks") or []:
        if str(row.get("id")) == wanted:
            title = str(row.get("title") or "Engineering task")
            print(title[: max(1, int(args.max_len))])
            return 0
    print(f"No engineering task matched id {wanted}", file=sys.stderr)
    return 1


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


def _cmd_check_pr_paths(args: argparse.Namespace) -> int:
    branch = str(args.branch or "").strip()
    if branch and not is_engineering_branch(branch):
        if args.json:
            _print_json({"ok": True, "skipped": True, "reason": "not an engineering task branch"})
        else:
            print(f"Skip path guard: {branch} is not an engineering task branch")
        return 0

    task_id = str(args.task_id or "").strip() or (task_id_from_branch(branch) if branch else "")
    if not task_id:
        print("task_id or engineering branch is required", file=sys.stderr)
        return 2

    changed_path = Path(args.changed_files)
    changed_files = [
        line.strip()
        for line in changed_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    result = validate_engineering_pr_paths_for_task_id(
        task_id,
        changed_files,
        tasks_path=_resolve_tasks_path(args.tasks_path),
    )
    if args.json:
        _print_json(result.to_dict())
    elif result.violations:
        print(f"Engineering path guard failed for {task_id}:", file=sys.stderr)
        for violation in result.violations:
            print(f"  - {violation}", file=sys.stderr)
    else:
        print(f"Engineering path guard passed for {task_id} ({len(changed_files)} file(s))")
    return 0 if result.ok else 1


def _cmd_draft_ci_fix(args: argparse.Namespace) -> int:
    log_text = ""
    if args.log_file:
        log_text = Path(args.log_file).read_text(encoding="utf-8", errors="replace")
    elif args.run_id:
        result = subprocess.run(
            ["gh", "run", "view", str(args.run_id), "--log-failed"],
            check=False,
            capture_output=True,
            text=True,
        )
        log_text = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0 and not log_text.strip():
            print(result.stderr or result.stdout or "gh run view failed", file=sys.stderr)
            return 1
    else:
        print("Provide --run-id or --log-file", file=sys.stderr)
        return 2

    failures = parse_pytest_failures_from_log(log_text)
    if not failures and getattr(args, "workflow_file", None):
        from value_investor.workflow_failure_tasks import draft_workflow_failure_task

        drafted = draft_workflow_failure_task(
            workflow_file=str(args.workflow_file),
            log_text=log_text,
            run_id=args.run_id,
            run_url=args.run_url,
            tasks_path=_resolve_tasks_path(args.tasks_path),
        )
        if args.json:
            _print_json({"drafted": drafted, "reason": "workflow_failure_signature"})
        elif drafted:
            print(f"Drafted workflow-failure task(s): {', '.join(drafted)}")
        else:
            print("No workflow-failure signature matched log")
        return 0 if drafted or not args.require_draft else 1

    if not failures:
        if args.json:
            _print_json({"drafted": [], "reason": "no pytest failures parsed"})
        else:
            print("No pytest failures found in log")
        return 0

    drafted = draft_ci_fix_task(
        failures,
        run_id=args.run_id,
        run_url=args.run_url,
        tasks_path=_resolve_tasks_path(args.tasks_path),
    )
    if args.json:
        _print_json({"drafted": drafted, "failures": failures})
    elif drafted:
        print(f"Drafted CI fix task(s): {', '.join(drafted)}")
    else:
        print("No new CI fix task drafted (duplicate open task or empty scope)")
    return 0 if drafted or not args.require_draft else 1


def _cmd_draft_workflow_failure(args: argparse.Namespace) -> int:
    log_text = ""
    if args.log_file:
        log_text = Path(args.log_file).read_text(encoding="utf-8", errors="replace")
    elif args.run_id:
        result = subprocess.run(
            ["gh", "run", "view", str(args.run_id), "--log-failed"],
            check=False,
            capture_output=True,
            text=True,
        )
        log_text = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0 and not log_text.strip():
            print(result.stderr or result.stdout or "gh run view failed", file=sys.stderr)
            return 1
    else:
        print("Provide --run-id or --log-file", file=sys.stderr)
        return 2

    from value_investor.workflow_failure_tasks import draft_workflow_failure_task

    drafted = draft_workflow_failure_task(
        workflow_file=str(args.workflow_file),
        log_text=log_text,
        run_id=args.run_id,
        run_url=args.run_url,
        tasks_path=_resolve_tasks_path(args.tasks_path),
    )
    if args.json:
        _print_json({"drafted": drafted, "workflow": args.workflow_file})
    elif drafted:
        print(f"Drafted workflow-failure task(s): {', '.join(drafted)}")
    else:
        print("No workflow-failure signature matched log")
    return 0 if drafted or not args.require_draft else 1


def _cmd_respond_library_ladder(args: argparse.Namespace) -> int:
    log_text = ""
    if args.log_file:
        log_text = Path(args.log_file).read_text(encoding="utf-8", errors="replace")
    elif args.run_id:
        result = subprocess.run(
            ["gh", "run", "view", str(args.run_id), "--log-failed"],
            check=False,
            capture_output=True,
            text=True,
        )
        log_text = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0 and not log_text.strip():
            print(result.stderr or result.stdout or "gh run view failed", file=sys.stderr)
            return 1
    else:
        print("Provide --run-id or --log-file", file=sys.stderr)
        return 2

    from value_investor.library_ladder_responder import (
        ACTION_RERUN,
        respond_to_library_ladder_failure,
    )
    from value_investor.workflow_failure_tasks import draft_workflow_failure_task

    library_root = Path(args.library_root)
    payload = respond_to_library_ladder_failure(
        log_text,
        run_id=args.run_id,
        run_url=args.run_url,
        ladder_json_path=library_root / "last_ladder.json",
        log_path=library_root / "ladder_responder_log.json",
    )
    drafted: list[str] = []
    if payload.get("should_draft_task"):
        classification = payload.get("classification") or {}
        if classification.get("kind") == "metrics_stall" and (library_root / "last_ladder.json").exists():
            ladder_result = read_json(library_root / "last_ladder.json")
            policy_path = library_root / "policy.json"
            draft_result = draft_library_ladder_engineering_tasks(
                ladder_result,
                root=library_root,
                policy_path=policy_path if policy_path.exists() else None,
                tasks_path=_resolve_tasks_path(args.tasks_path),
            )
            drafted = list(draft_result.get("task_ids") or [])
        if not drafted:
            drafted = draft_workflow_failure_task(
                workflow_file="library-grow.yml",
                log_text=log_text,
                run_id=args.run_id,
                run_url=args.run_url,
                tasks_path=_resolve_tasks_path(args.tasks_path),
            )

    if args.json:
        _print_json({**payload, "drafted": drafted})
    else:
        print(f"Classification: {payload.get('classification', {}).get('kind')}")
        print(f"Action: {payload.get('action')} — {payload.get('reason')}")
        if drafted:
            print(f"Drafted task(s): {', '.join(drafted)}")
    if payload.get("action") == ACTION_RERUN and payload.get("should_rerun"):
        return 0
    if payload.get("action") == ACTION_DRAFT_TASK and drafted:
        return 0
    if payload.get("action") == "noop_already_recovered":
        return 0
    return 0 if not args.require_action else 1


def _cmd_draft_library_ladder(args: argparse.Namespace) -> int:
    ladder_path = (
        Path(args.ladder_json) if args.ladder_json else Path(args.library_root) / "last_ladder.json"
    )
    if not ladder_path.exists():
        print(f"Ladder JSON not found: {ladder_path}", file=sys.stderr)
        return 1
    ladder_result = read_json(ladder_path)
    policy_arg = getattr(args, "library_policy_path", None)
    policy_path = Path(policy_arg) if policy_arg else Path(args.library_root) / "policy.json"
    result = draft_library_ladder_engineering_tasks(
        ladder_result,
        root=Path(args.library_root),
        policy_path=policy_path if policy_path.exists() else None,
        tasks_path=_resolve_tasks_path(args.tasks_path),
    )
    if args.json:
        _print_json(result)
    elif int(result.get("drafted_count") or 0) > 0:
        print(f"Drafted library ladder task(s): {', '.join(result.get('task_ids') or [])}")
    else:
        print(f"No new library ladder task: {result.get('reason')}")
    return 0


def _cmd_task_auto_merge(args: argparse.Namespace) -> int:
    task = find_engineering_task(args.task_id, path=_resolve_tasks_path(args.tasks_path))
    if task is None:
        print(f"No engineering task matched id {args.task_id}", file=sys.stderr)
        return 1
    eligible = task_eligible_for_auto_merge(task)
    if args.json:
        _print_json({"task_id": args.task_id, "auto_merge": eligible})
    else:
        print("true" if eligible else "false")
    return 0 if eligible else 1


def _cmd_try_auto_merge(args: argparse.Namespace) -> int:
    branch = str(args.branch or "").strip()
    if not branch:
        print("--branch is required", file=sys.stderr)
        return 2
    decision = evaluate_auto_merge(
        branch=branch,
        tasks_path=_resolve_tasks_path(args.tasks_path),
    )
    if args.json:
        payload = decision.to_dict()
        if decision.should_merge and not args.dry_run:
            ok, detail = perform_auto_merge(decision)
            payload["merged"] = ok
            payload["merge_detail"] = detail
        _print_json(payload)
    elif decision.should_merge:
        if args.dry_run:
            print(f"Would auto-merge PR #{decision.pr_number} for {decision.task_id}")
        else:
            ok, detail = perform_auto_merge(decision)
            print(detail)
            if not ok:
                return 1
    else:
        print(f"No auto-merge: {decision.reason}")
    return 0 if decision.should_merge or args.allow_skip else 1


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


def _cmd_notify_pr_open(args: argparse.Namespace) -> int:
    note = EngineeringPrNotification(
        task_id=str(args.task_id).strip(),
        branch=str(args.branch).strip(),
        pr_url=str(args.pr_url).strip(),
        pr_number=int(args.pr_number) if args.pr_number is not None else None,
        is_draft=bool(args.is_draft),
        auto_merge=bool(args.auto_merge),
        used_pat=bool(args.used_pat),
        ci_approval_hint=not args.no_ci_hint,
    )
    if args.json:
        _print_json({"sent": send_engineering_pr_email(note), **note.to_dict()})
        return 0
    sent = send_engineering_pr_email(note)
    if sent:
        print(f"Engineering PR email sent for {note.task_id}")
    else:
        print("Engineering PR email skipped (SMTP not configured)", file=sys.stderr)
    return 0


def _load_optional_json(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def _cmd_notify_queue_blocked(args: argparse.Namespace) -> int:
    alerts = collect_queue_block_alerts(
        recovery=_load_optional_json(args.recovery_json),
        sync=_load_optional_json(args.sync_json),
        dispatch=_load_optional_json(args.queue_status_json),
    )
    sent = send_engineering_queue_block_email(alerts)
    payload = {
        "alert_count": len(alerts),
        "alerts": [row.to_dict() for row in alerts],
        "sent": sent,
    }
    if args.json:
        _print_json(payload)
    elif not alerts:
        print("No engineering queue block alerts")
    elif sent:
        print(f"Engineering queue-block email sent ({len(alerts)} alert(s))")
    else:
        print("Engineering queue-block email skipped (SMTP not configured)", file=sys.stderr)
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
    common = argparse.ArgumentParser(add_help=False)

    def _add_shared_flags(target: argparse.ArgumentParser) -> None:
        target.add_argument("--output-dir", type=Path, default=Path("output"))
        target.add_argument("--tasks-path", type=Path, default=COMMITTED_TASKS_PATH)
        target.add_argument(
            "--suggestions-path",
            type=Path,
            default=Path("docs/data/research_model_suggestions.json"),
        )
        target.add_argument(
            "--policy",
            type=Path,
            default=Path("docs/data/library/policy.json"),
            help="Library policy JSON for ad-hoc spend checkpoint",
        )
        target.add_argument("--json", action="store_true")

    _add_shared_flags(common)
    sub = parser.add_subparsers(dest="command", required=True)

    compile_p = sub.add_parser(
        "compile", parents=[common], help="Build engineering_tasks.json from run artifacts"
    )
    compile_p.add_argument("--max-tasks", type=int, default=DEFAULT_MAX_COMPILE_TASKS)
    compile_p.set_defaults(func=_cmd_compile)

    list_p = sub.add_parser("list", parents=[common], help="List compiled engineering tasks")
    list_p.set_defaults(func=_cmd_list)

    queue_p = sub.add_parser(
        "queue-status", parents=[common], help="Evaluate whether to auto-dispatch the next task"
    )
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
        "--agent-running-count",
        type=int,
        default=None,
        help="Count of engineering-agent workflows queued or in progress",
    )
    queue_p.add_argument(
        "--max-parallel",
        type=int,
        default=None,
        help="Max concurrent engineering agents (default: policy or 2)",
    )
    queue_p.add_argument(
        "--require-dispatch",
        action="store_true",
        help="Exit 1 unless dispatch is recommended (for workflow gates)",
    )
    queue_p.add_argument("--force", action="store_true")
    queue_p.set_defaults(func=_cmd_queue_status)

    refresh_ui_p = sub.add_parser(
        "refresh-queue-ui",
        parents=[common],
        help="Publish engineering queue status to automation.json and latest.json",
    )
    refresh_ui_p.set_defaults(func=_cmd_refresh_queue_ui)

    sync_p = sub.add_parser(
        "sync-queue",
        parents=[common],
        help="Copy output/engineering_tasks.json to committed queue path",
    )
    sync_p.set_defaults(func=_cmd_sync_queue)

    reconcile_p = sub.add_parser(
        "reconcile-queue",
        parents=[common],
        help="Reset pr_open tasks that have no matching open engineering PR",
    )
    reconcile_p.add_argument(
        "--open-prs-json",
        default=None,
        help="Path to JSON array of open PRs from gh pr list --json ...",
    )
    reconcile_p.set_defaults(func=_cmd_reconcile_queue)

    recover_p = sub.add_parser(
        "recover-queue",
        parents=[common],
        help="Self-repair queue: reconcile orphans, retry failed, park blocked tasks",
    )
    recover_p.add_argument("--open-prs-json", default=None)
    recover_p.add_argument("--dry-run", action="store_true")
    recover_p.add_argument("--max-agent-retries", type=int, default=2)
    recover_p.add_argument("--retry-cooldown-hours", type=int, default=24)
    recover_p.add_argument("--ci-red-park-hours", type=int, default=48)
    recover_p.set_defaults(func=_cmd_recover_queue)

    try_accel_p = sub.add_parser(
        "try-accelerated-email",
        parents=[common],
        help="Decide whether to chain orchestrator email_only after queue drain (L97)",
    )
    try_accel_p.add_argument("--open-prs-json", default=None)
    try_accel_p.add_argument("--merged-task-id", default=None)
    try_accel_p.add_argument(
        "--allow-skip",
        action="store_true",
        help="Exit 0 when dispatch is not applicable (for workflow conditions)",
    )
    try_accel_p.set_defaults(func=_cmd_try_accelerated_email)

    record_accel_p = sub.add_parser(
        "record-accelerated-email",
        parents=[common],
        help="Record a mid-week email_only orchestrator dispatch in the log",
    )
    record_accel_p.add_argument("--source", required=True)
    record_accel_p.add_argument("--merged-task-id", default=None)
    record_accel_p.add_argument("--note", default=None)
    record_accel_p.set_defaults(func=_cmd_record_accelerated_email)

    try_wed_anchor_p = sub.add_parser(
        "try-wednesday-anchor",
        parents=[common],
        help="Decide whether to chain email_only after Wed afternoon ingest (L97b)",
    )
    try_wed_anchor_p.add_argument("--open-prs-json", default=None)
    try_wed_anchor_p.add_argument(
        "--ingest-loop-json",
        default=None,
        help="Path to ingest-loop run JSON for materiality checks",
    )
    try_wed_anchor_p.add_argument(
        "--latest-path",
        default="docs/data/latest.json",
        help="Path to latest.json for screen staleness",
    )
    try_wed_anchor_p.add_argument(
        "--allow-skip",
        action="store_true",
        help="Exit 0 when dispatch is not applicable (for workflow conditions)",
    )
    try_wed_anchor_p.set_defaults(func=_cmd_try_wednesday_anchor)

    try_accel_ladder_p = sub.add_parser(
        "try-accelerated-ladder",
        parents=[common],
        help="Decide whether to chain orchestrator ladder_only after coverage merge",
    )
    try_accel_ladder_p.add_argument("--open-prs-json", default=None)
    try_accel_ladder_p.add_argument("--merged-task-id", default=None)
    try_accel_ladder_p.add_argument(
        "--allow-skip",
        action="store_true",
        help="Exit 0 when dispatch is not applicable (for workflow conditions)",
    )
    try_accel_ladder_p.set_defaults(func=_cmd_try_accelerated_ladder)

    record_accel_ladder_p = sub.add_parser(
        "record-accelerated-ladder",
        parents=[common],
        help="Record a mid-week ladder_only orchestrator dispatch in the log",
    )
    record_accel_ladder_p.add_argument("--source", required=True)
    record_accel_ladder_p.add_argument("--merged-task-id", default=None)
    record_accel_ladder_p.add_argument("--note", default=None)
    record_accel_ladder_p.set_defaults(func=_cmd_record_accelerated_ladder)

    parked_p = sub.add_parser(
        "list-parked", parents=[common], help="List tasks parked for manual review"
    )
    parked_p.set_defaults(func=_cmd_list_parked)

    record_no_diff_p = sub.add_parser(
        "record-no-diff",
        parents=[common],
        help="Record an agent run that produced no committable code changes",
    )
    record_no_diff_p.add_argument("--task-id", required=True)
    record_no_diff_p.add_argument(
        "--max-runs",
        type=int,
        default=2,
        help="Park after this many consecutive no-diff runs (default: 2)",
    )
    record_no_diff_p.set_defaults(func=_cmd_record_no_diff)

    branch_stale_p = sub.add_parser(
        "branch-is-stale",
        parents=[common],
        help="Exit 0 when an engineering branch has no open PR and may be deleted",
    )
    branch_stale_p.add_argument("--branch", required=True)
    branch_stale_p.add_argument(
        "--open-prs-json",
        default=None,
        help="Path to JSON array of open PRs from gh pr list --json ...",
    )
    branch_stale_p.set_defaults(func=_cmd_branch_is_stale)

    next_open_p = sub.add_parser(
        "next-open-id", parents=[common], help="Print the top-priority open engineering task id"
    )
    next_open_p.set_defaults(func=_cmd_next_open_id)

    task_title_p = sub.add_parser(
        "task-title", parents=[common], help="Print an engineering task title"
    )
    task_title_p.add_argument("--task-id", required=True)
    task_title_p.add_argument("--max-len", type=int, default=120)
    task_title_p.set_defaults(func=_cmd_task_title)

    mark_pr_open_p = sub.add_parser(
        "mark-pr-open",
        parents=[common],
        help="Mark an engineering task pr_open after a draft PR is created",
    )
    mark_pr_open_p.add_argument("--task-id", required=True)
    mark_pr_open_p.add_argument("--branch", required=True)
    mark_pr_open_p.add_argument("--result-path", required=True)
    mark_pr_open_p.set_defaults(func=_cmd_mark_pr_open)

    merged_p = sub.add_parser(
        "mark-merged", parents=[common], help="Mark an engineering task merged from a branch name"
    )
    merged_p.add_argument("--branch", required=True)
    merged_p.add_argument("--pr-url", default=None)
    merged_p.add_argument("--pr-number", type=int, default=None)
    merged_p.set_defaults(func=_cmd_mark_merged)

    reprioritize_p = sub.add_parser(
        "reprioritize",
        parents=[common],
        help="Deterministically adjust open queue priorities after an ingest merge",
    )
    reprioritize_p.add_argument("--merged-task-id", required=True)
    reprioritize_p.add_argument(
        "--latest-path",
        type=Path,
        default=Path("docs/data/latest.json"),
    )
    reprioritize_p.set_defaults(func=_cmd_reprioritize)

    check_paths_p = sub.add_parser(
        "check-pr-paths",
        parents=[common],
        help="Fail when changed files are outside task allowed_paths or touch blocked_paths",
    )
    check_paths_p.add_argument(
        "--branch",
        default=None,
        help="Engineering PR branch (cursor/eng-YYYYMMDD-NN-1de3); non-task branches are skipped",
    )
    check_paths_p.add_argument(
        "--task-id", default=None, help="Override task id parsed from branch"
    )
    check_paths_p.add_argument(
        "--changed-files",
        required=True,
        help="Path to a newline-delimited list of changed repo paths",
    )
    check_paths_p.set_defaults(func=_cmd_check_pr_paths)

    draft_ci_p = sub.add_parser(
        "draft-ci-fix",
        parents=[common],
        help="Draft a scoped CI-fix engineering task from a failed Actions run log",
    )
    draft_ci_p.add_argument(
        "--run-id", default=None, help="GitHub Actions run id (uses gh run view --log-failed)"
    )
    draft_ci_p.add_argument("--log-file", default=None, help="Path to saved failed CI log text")
    draft_ci_p.add_argument("--run-url", default=None, help="Optional link stored in task evidence")
    draft_ci_p.add_argument(
        "--workflow-file",
        default=None,
        help="When set and no pytest failures match, try workflow_failure signature drafting",
    )
    draft_ci_p.add_argument(
        "--require-draft",
        action="store_true",
        help="Exit 1 when no new task is drafted",
    )
    draft_ci_p.set_defaults(func=_cmd_draft_ci_fix)

    draft_wf_p = sub.add_parser(
        "draft-workflow-failure",
        parents=[common],
        help="Draft a scoped engineering task from a failed workflow log signature",
    )
    draft_wf_p.add_argument("--workflow-file", required=True)
    draft_wf_p.add_argument("--run-id", default=None)
    draft_wf_p.add_argument("--log-file", default=None)
    draft_wf_p.add_argument("--run-url", default=None)
    draft_wf_p.add_argument("--require-draft", action="store_true")
    draft_wf_p.set_defaults(func=_cmd_draft_workflow_failure)

    respond_ladder_p = sub.add_parser(
        "respond-library-ladder",
        parents=[common],
        help="Classify a failed library-grow run and choose rerun vs engineering draft",
    )
    respond_ladder_p.add_argument("--run-id", default=None)
    respond_ladder_p.add_argument("--log-file", default=None)
    respond_ladder_p.add_argument("--run-url", default=None)
    respond_ladder_p.add_argument(
        "--library-root",
        default="docs/data/library",
        help="Library root for last_ladder.json and responder log",
    )
    respond_ladder_p.add_argument(
        "--require-action",
        action="store_true",
        help="Exit 1 when no rerun or draft action is taken",
    )
    respond_ladder_p.set_defaults(func=_cmd_respond_library_ladder)

    draft_ladder_p = sub.add_parser(
        "draft-library-ladder",
        parents=[common],
        help="Draft a coverage engineering task when library ladder cannot screen focus market",
    )
    draft_ladder_p.add_argument(
        "--library-root",
        default="docs/data/library",
        help="Library root containing last_ladder.json (default: docs/data/library)",
    )
    draft_ladder_p.add_argument(
        "--ladder-json",
        default=None,
        help="Path to ladder result JSON (default: <library-root>/last_ladder.json)",
    )
    draft_ladder_p.add_argument(
        "--library-policy-path",
        default=None,
        help="Library policy JSON (default: <library-root>/policy.json)",
    )
    draft_ladder_p.set_defaults(func=_cmd_draft_library_ladder)

    task_auto_p = sub.add_parser(
        "task-auto-merge",
        parents=[common],
        help="Exit 0 when a task is eligible for scoped auto-merge",
    )
    task_auto_p.add_argument("--task-id", required=True)
    task_auto_p.set_defaults(func=_cmd_task_auto_merge)

    try_merge_p = sub.add_parser(
        "try-auto-merge",
        parents=[common],
        help="Merge an engineering PR when CI is green and diff stays in scope",
    )
    try_merge_p.add_argument("--branch", required=True)
    try_merge_p.add_argument("--dry-run", action="store_true")
    try_merge_p.add_argument(
        "--allow-skip",
        action="store_true",
        help="Exit 0 when auto-merge is not applicable (for workflow conditions)",
    )
    try_merge_p.set_defaults(func=_cmd_try_auto_merge)

    notify_pr_p = sub.add_parser(
        "notify-pr-open",
        parents=[common],
        help="Email alert when the engineering agent opens a supervised PR",
    )
    notify_pr_p.add_argument("--task-id", required=True)
    notify_pr_p.add_argument("--branch", required=True)
    notify_pr_p.add_argument("--pr-url", required=True)
    notify_pr_p.add_argument("--pr-number", type=int, default=None)
    notify_pr_p.add_argument("--is-draft", action="store_true")
    notify_pr_p.add_argument("--auto-merge", action="store_true")
    notify_pr_p.add_argument(
        "--used-pat",
        action="store_true",
        help="Set when PR was opened with WORKFLOW_DISPATCH_PAT",
    )
    notify_pr_p.add_argument(
        "--no-ci-hint",
        action="store_true",
        help="Omit backup note about approving action_required CI runs",
    )
    notify_pr_p.set_defaults(func=_cmd_notify_pr_open)

    notify_block_p = sub.add_parser(
        "notify-queue-blocked",
        parents=[common],
        help="Email when the engineering queue is blocked (checkpoint, failures, reconcile, park)",
    )
    notify_block_p.add_argument(
        "--recovery-json",
        default=None,
        help="JSON from ftse-engineering recover-queue --json",
    )
    notify_block_p.add_argument(
        "--sync-json",
        default=None,
        help="JSON from engineering sync report",
    )
    notify_block_p.add_argument(
        "--queue-status-json",
        default=None,
        help="JSON from ftse-engineering queue-status --json",
    )
    notify_block_p.set_defaults(func=_cmd_notify_queue_blocked)

    run_p = sub.add_parser(
        "run", parents=[common], help="Run the supervised dev agent for open task(s)"
    )
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

    argv_list = list(argv or sys.argv[1:])
    pre, remaining = common.parse_known_args(argv_list)
    args = parser.parse_args(remaining)
    apply_parsed_globals(
        args,
        pre,
        argv_list,
        ["json", "output_dir", "tasks_path", "suggestions_path", "policy"],
    )
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
