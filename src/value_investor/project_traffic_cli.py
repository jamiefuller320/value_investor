"""CLI for project traffic controller (pause / unstick / EOD digest)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from value_investor.pr_fix_occasions import (
    DEFAULT_PR_FIX_OCCASIONS_PATH,
    KIND_BOTH,
    KIND_CI,
    KIND_MERGE,
    SOURCE_HUMAN,
    format_common_issues_markdown,
    load_pr_fix_occasions,
    record_pr_fix_occasion,
    summarize_common_failure_reasons,
)
from value_investor.project_traffic import (
    COMMITTED_TASKS_PATH,
    DEFAULT_DIGEST_MARKDOWN_PATH,
    DEFAULT_DIGEST_PATH,
    build_daily_digest,
    format_daily_digest_markdown,
    get_traffic_control_state,
    is_traffic_pause_active,
    run_project_traffic,
    write_daily_digest,
)


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=str))


def _load_open_prs(path: str | None) -> list[dict[str, Any]] | None:
    if not path:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("prs"), list):
        return list(data["prs"])
    raise ValueError("--open-prs-json must be a JSON array of PRs")


def _cmd_status(args: argparse.Namespace) -> int:
    state = get_traffic_control_state(tasks_path=args.tasks_path)
    payload = {
        "pause_active": is_traffic_pause_active(tasks_path=args.tasks_path),
        "state": state,
    }
    if args.json:
        _print_json(payload)
    else:
        print(f"pause_active={payload['pause_active']}")
        if state:
            print(json.dumps(state, indent=2, default=str))
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    open_prs = _load_open_prs(args.open_prs_json)
    report = run_project_traffic(
        tasks_path=args.tasks_path,
        open_prs=open_prs,
        apply=not args.dry_run,
        write_digest=args.write_digest and not args.no_digest,
    )
    payload = report.to_dict()
    if args.json:
        _print_json(payload)
    else:
        print(
            f"pause_active={report.pause_active} stuck={len(report.stuck_prs)} "
            f"actions={len(report.actions)}"
        )
        for pr in report.stuck_prs:
            print(f"  PR #{pr.number} {pr.branch} reasons={pr.reasons}")
        for action in report.actions:
            print(f"  action {action.kind}: {action.detail}")
        if report.should_dispatch_conflict_agent:
            print("conflict_dispatches:")
            for row in report.should_dispatch_conflict_agent:
                print(f"  {row}")
    if args.require_clear and report.stuck_prs:
        return 1
    return 0


def _cmd_digest(args: argparse.Namespace) -> int:
    state = get_traffic_control_state(tasks_path=args.tasks_path)
    digest = build_daily_digest(
        stuck_prs=[],
        traffic_state=state,
        actions=[],
    )
    if args.write:
        paths = write_daily_digest(
            digest,
            json_path=args.json_path,
            markdown_path=args.markdown_path,
        )
        if args.json:
            _print_json({"digest": digest, **paths})
        else:
            print(f"wrote {paths['json_path']} and {paths['markdown_path']}")
        return 0
    if args.json:
        _print_json(digest)
    else:
        print(format_daily_digest_markdown(digest), end="")
    return 0


def _cmd_record_fix(args: argparse.Namespace) -> int:
    """Record a human-requested PR check / merge fix occasion."""
    kind = str(args.kind)
    if args.ci and args.merge:
        kind = KIND_BOTH
    elif args.ci:
        kind = KIND_CI
    elif args.merge:
        kind = KIND_MERGE

    check_names = [s.strip() for s in (args.failed_checks or "").split(",") if s.strip()]
    result = record_pr_fix_occasion(
        source=SOURCE_HUMAN,
        kind=kind,
        failure_reason=args.reason,
        pr_number=args.pr,
        branch=args.branch,
        title=args.title,
        url=args.url,
        task_id=args.task_id,
        head_sha=args.head_sha,
        mergeable_state=args.mergeable_state,
        failed_check_names=check_names,
        notes=args.notes,
        path=args.log_path,
        apply=not args.dry_run,
    )
    entry = result["entry"]
    if args.json:
        _print_json(result)
    else:
        print(
            f"recorded {entry['id']} source={entry['source']} kind={entry['kind']} "
            f"reason={entry['failure_reason']!r} path={result['path']}"
        )
    return 0


def _cmd_common_issues(args: argparse.Namespace) -> int:
    payload = load_pr_fix_occasions(args.log_path)
    summary = summarize_common_failure_reasons(
        list(payload.get("occasions") or []),
        limit=args.limit,
    )
    if args.json:
        _print_json({"summary": summary, "updated_at": payload.get("updated_at")})
    else:
        print(format_common_issues_markdown(summary), end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Project traffic controller: pause stuck PR queues and EOD digest"
    )
    parser.add_argument(
        "--tasks-path",
        type=Path,
        default=COMMITTED_TASKS_PATH,
        help="Engineering tasks JSON path",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    status_p = sub.add_parser("status", help="Show traffic pause state")
    status_p.add_argument("--json", action="store_true")
    status_p.set_defaults(func=_cmd_status)

    run_p = sub.add_parser("run", help="Classify stuck PRs, pause/resume, request fixes")
    run_p.add_argument("--open-prs-json", default=None)
    run_p.add_argument("--dry-run", action="store_true", help="Do not write state or post comments")
    run_p.add_argument(
        "--write-digest",
        action="store_true",
        default=True,
        help="Write daily digest artifacts (default on)",
    )
    run_p.add_argument("--no-digest", action="store_true", help="Skip digest write")
    run_p.add_argument("--json", action="store_true")
    run_p.add_argument(
        "--require-clear",
        action="store_true",
        help="Exit 1 when any stuck PR remains",
    )
    run_p.set_defaults(func=_cmd_run)

    digest_p = sub.add_parser("digest", help="Build grounded EOD digest from committed artifacts")
    digest_p.add_argument("--write", action="store_true")
    digest_p.add_argument("--json-path", type=Path, default=DEFAULT_DIGEST_PATH)
    digest_p.add_argument("--markdown-path", type=Path, default=DEFAULT_DIGEST_MARKDOWN_PATH)
    digest_p.add_argument("--json", action="store_true")
    digest_p.set_defaults(func=_cmd_digest)

    record_p = sub.add_parser(
        "record-fix",
        help="Record a human-requested PR check/merge fix occasion + failure reason",
    )
    record_p.add_argument("--pr", type=int, default=None, help="Pull request number")
    record_p.add_argument(
        "--kind",
        choices=sorted({KIND_CI, KIND_MERGE, KIND_BOTH}),
        default=KIND_CI,
        help="Fix request kind (default: ci_check)",
    )
    record_p.add_argument("--ci", action="store_true", help="Shorthand for --kind ci_check")
    record_p.add_argument("--merge", action="store_true", help="Shorthand for --kind merge_conflict")
    record_p.add_argument(
        "--reason",
        required=True,
        help="Failure reason (normalized bucket label for common-issue aggregation)",
    )
    record_p.add_argument("--branch", default=None)
    record_p.add_argument("--title", default=None)
    record_p.add_argument("--url", default=None)
    record_p.add_argument("--task-id", default=None)
    record_p.add_argument("--head-sha", default=None)
    record_p.add_argument("--mergeable-state", default=None)
    record_p.add_argument(
        "--failed-checks",
        default=None,
        help="Comma-separated failing check names",
    )
    record_p.add_argument("--notes", default=None)
    record_p.add_argument("--log-path", type=Path, default=DEFAULT_PR_FIX_OCCASIONS_PATH)
    record_p.add_argument("--dry-run", action="store_true")
    record_p.add_argument("--json", action="store_true")
    record_p.set_defaults(func=_cmd_record_fix)

    common_p = sub.add_parser(
        "common-issues",
        help="Summarize common PR fix-request failure reasons",
    )
    common_p.add_argument("--log-path", type=Path, default=DEFAULT_PR_FIX_OCCASIONS_PATH)
    common_p.add_argument("--limit", type=int, default=20)
    common_p.add_argument("--json", action="store_true")
    common_p.set_defaults(func=_cmd_common_issues)

    args = parser.parse_args(argv)
    # Ensure tasks_path is available on all subcommands
    if not hasattr(args, "tasks_path"):
        args.tasks_path = COMMITTED_TASKS_PATH
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
