"""CLI for operational health monitoring, auto-fixes, and daily email summaries."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from value_investor.ops_monitor import (
    DEFAULT_MONITOR_LOG_PATH,
    DEFAULT_STATUS_PATH,
    OpsFinding,
    OpsMonitorReport,
    append_monitor_log_entry,
    run_ops_monitor,
    send_ops_monitor_email,
    workflow_stale_only_failures,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Monitor cron/workflows, apply safe fixes, draft engineering tasks, email summary",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true")
    common.add_argument("--status-path", type=Path, default=DEFAULT_STATUS_PATH)
    common.add_argument("--monitor-log-path", type=Path, default=DEFAULT_MONITOR_LOG_PATH)
    common.add_argument(
        "--no-apply",
        action="store_true",
        help="Detect issues only — do not apply auto-fixes or draft tasks",
    )
    common.add_argument(
        "--no-draft",
        action="store_true",
        help="Do not queue ops engineering tasks for unresolved failures",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser(
        "run",
        parents=[common],
        help="Run checks, optional auto-fixes, write ops_status.json",
    )
    run_p.add_argument(
        "--email",
        action="store_true",
        help=(
            "Send SMTP summary only when unfixed warn/fail remain after heal/re-verify "
            "and are not deferred for later-day catch-up"
        ),
    )
    run_p.add_argument(
        "--email-always",
        action="store_true",
        help="Send SMTP summary even when overall ok or email would be deferred",
    )
    run_p.add_argument(
        "--allow-workflow-stale-exit-zero",
        action="store_true",
        help="Exit 0 when overall fail is only due to workflow-overdue findings",
    )
    run_p.set_defaults(func=_cmd_run)

    email_p = sub.add_parser(
        "email",
        parents=[common],
        help="Email the latest ops_status.json summary",
    )
    email_p.add_argument(
        "--always",
        action="store_true",
        help="Send even when the saved report is overall ok or email_deferred",
    )
    email_p.set_defaults(func=_cmd_email)

    args = parser.parse_args(argv)
    return int(args.func(args))


def _report_from_status(payload: dict) -> OpsMonitorReport:
    return OpsMonitorReport(
        run_at=str(payload.get("run_at") or ""),
        overall=str(payload.get("overall") or "warn"),
        findings=[OpsFinding(**row) for row in payload.get("findings") or []],
        auto_fixes=list(payload.get("auto_fixes") or []),
        drafted_task_ids=list(payload.get("drafted_task_ids") or []),
        workflow_checks=list(payload.get("workflow_checks") or []),
        queue_status=dict(payload.get("queue_status") or {}),
        should_dispatch_engineering=bool(payload.get("should_dispatch_engineering")),
        email_deferred=bool(payload.get("email_deferred")),
        email_defer_reasons=list(payload.get("email_defer_reasons") or []),
    )


def _cmd_run(args: argparse.Namespace) -> int:
    report = run_ops_monitor(
        status_path=args.status_path,
        apply_fixes=not args.no_apply,
        draft_tasks=not args.no_draft,
    )
    append_monitor_log_entry(report, path=args.monitor_log_path)
    if args.email or args.email_always:
        try:
            send_ops_monitor_email(
                report,
                only_if_not_ok=not args.email_always,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"Ops monitor: {report.overall}")
        print(f"  findings: {len(report.findings)}")
        print(f"  auto-fixes: {len(report.auto_fixes)}")
        if report.email_deferred:
            print(f"  email deferred: {len(report.email_defer_reasons)} reason(s)")
        if report.drafted_task_ids:
            print(f"  drafted tasks: {', '.join(report.drafted_task_ids)}")
        if report.should_dispatch_engineering:
            print("  engineering queue ready to dispatch")
    if report.overall == "fail":
        if args.allow_workflow_stale_exit_zero and workflow_stale_only_failures(report.findings):
            return 0
        if report.email_deferred:
            # Pending today's slots — do not fail the Actions job; catch-up will re-check.
            return 0
        return 1
    return 0


def _cmd_email(args: argparse.Namespace) -> int:
    from value_investor.storage import read_json

    if not args.status_path.exists():
        print(
            f"No ops status at {args.status_path} — run ftse-ops-monitor run first", file=sys.stderr
        )
        return 1
    payload = read_json(args.status_path)
    report = _report_from_status(payload)
    try:
        send_ops_monitor_email(report, only_if_not_ok=not args.always)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"sent": True, "overall": report.overall}, indent=2))
    else:
        print("Ops monitor email sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
