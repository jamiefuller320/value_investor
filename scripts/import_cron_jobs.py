#!/usr/bin/env python3
"""Import production cron-job.org schedules for FTSE Value Investor workflows.

Creates or updates HTTP jobs that POST to GitHub ``workflow_dispatch`` endpoints.
Idempotent by job title.

Required env:
  CRONJOB_API_KEY  — cron-job.org API key (Settings → API)
  WORKFLOW_DISPATCH_PAT — fine-grained PAT with Actions: Read and write on the repo

Examples:
  WORKFLOW_DISPATCH_PAT=… CRONJOB_API_KEY=… ./scripts/import_cron_jobs.py --all
  WORKFLOW_DISPATCH_PAT=… CRONJOB_API_KEY=… ./scripts/import_cron_jobs.py --job data-backup
  ./scripts/import_cron_jobs.py --all --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from value_investor.paper_auto_scheduling import (
    WEEKDAY_PAPER_UTC_HOUR,
    WEEKDAY_PAPER_UTC_MINUTE,
)
from value_investor.workflow_pat import require_workflow_dispatch_pat, resolve_workflow_dispatch_pat

REPO = os.environ.get("REPO", "jamiefuller320/value_investor")
REF = os.environ.get("REF", "main")
CRONJOB_ENDPOINT = "https://api.cron-job.org"
REQUEST_METHOD_POST = 1


@dataclass(frozen=True)
class CronJobSpec:
    key: str
    title: str
    workflow: str
    body: dict[str, Any]
    hours: list[int]
    minutes: list[int]
    wdays: list[int]
    mdays: list[int] = (-1,)
    months: list[int] = (-1,)

    @property
    def url(self) -> str:
        return (
            f"https://api.github.com/repos/{REPO}/actions/workflows/"
            f"{self.workflow}/dispatches"
        )


_INGEST_LOOP_INPUTS = {"inputs": {"max_targets": "8"}}


def _job_specs() -> list[CronJobSpec]:
    return [
        CronJobSpec(
            key="orchestrator-sunday",
            title="FTSE orchestrator (Sunday)",
            workflow="automation-orchestrator.yml",
            body={"ref": REF, "inputs": {"suite": "sunday", "force": "false"}},
            hours=[6],
            minutes=[20],
            wdays=[0],
        ),
        CronJobSpec(
            key="orchestrator-weekday-paper",
            title="FTSE orchestrator (weekday paper)",
            workflow="automation-orchestrator.yml",
            body={"ref": REF, "inputs": {"suite": "weekday_paper", "force": "false"}},
            hours=[WEEKDAY_PAPER_UTC_HOUR],
            minutes=[WEEKDAY_PAPER_UTC_MINUTE],
            wdays=[1, 2, 3, 4, 5],
        ),
        CronJobSpec(
            key="ingest-loop-morning",
            title="FTSE ingest loop (Mon/Wed/Fri morning)",
            workflow="ingest-loop.yml",
            body={"ref": REF, **_INGEST_LOOP_INPUTS},
            hours=[7],
            minutes=[5],
            wdays=[1, 3, 5],
        ),
        CronJobSpec(
            key="ingest-loop-afternoon",
            title="FTSE ingest loop (Mon/Wed/Fri afternoon)",
            workflow="ingest-loop.yml",
            body={"ref": REF, **_INGEST_LOOP_INPUTS},
            hours=[10],
            minutes=[5],
            wdays=[1, 3, 5],
        ),
        CronJobSpec(
            key="analysis-review",
            title="FTSE analysis review (Sunday)",
            workflow="analysis-review.yml",
            body={"ref": REF},
            hours=[10],
            minutes=[35],
            wdays=[0],
        ),
        CronJobSpec(
            key="paper-learning-review",
            title="FTSE paper learning review (Sunday)",
            workflow="paper-learning-review.yml",
            body={"ref": REF},
            hours=[10],
            minutes=[45],
            wdays=[0],
        ),
        CronJobSpec(
            key="ops-monitor",
            title="FTSE ops monitor (daily)",
            workflow="ops-monitor.yml",
            body={"ref": REF},
            hours=[7],
            minutes=[45],
            wdays=[-1],
        ),
        CronJobSpec(
            key="ci-main-nightly",
            title="FTSE CI main nightly (daily)",
            workflow="ci-main-nightly.yml",
            body={"ref": REF},
            hours=[7],
            minutes=[30],
            wdays=[-1],
        ),
        CronJobSpec(
            key="data-backup",
            title="FTSE data backup (Sunday)",
            workflow="data-backup.yml",
            body={"ref": REF},
            hours=[12],
            minutes=[30],
            wdays=[0],
        ),
        CronJobSpec(
            key="engineering-queue",
            title="FTSE engineering queue (hourly weekdays)",
            workflow="engineering-queue.yml",
            body={"ref": REF},
            hours=list(range(24)),
            minutes=[15],
            wdays=[1, 2, 3, 4, 5],
        ),
    ]


def _cronjob_request(
    method: str,
    path: str,
    *,
    api_key: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{CRONJOB_ENDPOINT}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed ({exc.code}): {detail}") from exc


def _list_jobs(api_key: str) -> list[dict[str, Any]]:
    payload = _cronjob_request("GET", "/jobs", api_key=api_key)
    return list(payload.get("jobs") or [])


def _build_job_payload(spec: CronJobSpec, gh_pat: str) -> dict[str, Any]:
    return {
        "job": {
            "title": spec.title,
            "url": spec.url,
            "enabled": True,
            "saveResponses": True,
            "requestMethod": REQUEST_METHOD_POST,
            "schedule": {
                "timezone": "UTC",
                "expiresAt": 0,
                "hours": list(spec.hours),
                "minutes": list(spec.minutes),
                "mdays": list(spec.mdays),
                "months": list(spec.months),
                "wdays": list(spec.wdays),
            },
            "extendedData": {
                "headers": {
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {gh_pat}",
                },
                "body": json.dumps(spec.body),
            },
        }
    }


def import_job(
    spec: CronJobSpec,
    *,
    api_key: str,
    gh_pat: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    payload = _build_job_payload(spec, gh_pat)
    if dry_run:
        return {"action": "upsert", "title": spec.title, "payload": payload}

    existing = {job.get("title"): job for job in _list_jobs(api_key)}
    current = existing.get(spec.title)
    if current and current.get("jobId"):
        _cronjob_request(
            "PATCH",
            f"/jobs/{current['jobId']}",
            api_key=api_key,
            payload=payload,
        )
        return {"action": "updated", "title": spec.title, "jobId": current["jobId"]}

    created = _cronjob_request("PUT", "/jobs", api_key=api_key, payload=payload)
    return {"action": "created", "title": spec.title, "jobId": created.get("jobId")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import cron-job.org production schedules")
    parser.add_argument("--all", action="store_true", help="Import every production job")
    parser.add_argument("--job", action="append", dest="jobs", help="Import one job key (repeatable)")
    parser.add_argument("--dry-run", action="store_true", help="Print payloads without calling cron-job.org")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable results")
    args = parser.parse_args(argv)

    api_key = os.environ.get("CRONJOB_API_KEY", "").strip()
    if not args.dry_run and not api_key:
        print("CRONJOB_API_KEY is required (cron-job.org → Settings → API)", file=sys.stderr)
        return 1
    if args.dry_run:
        gh_pat = resolve_workflow_dispatch_pat() or "github_pat_dry_run_placeholder"
    else:
        try:
            gh_pat = require_workflow_dispatch_pat()
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    specs = {spec.key: spec for spec in _job_specs()}
    selected: list[CronJobSpec]
    if args.all:
        selected = list(specs.values())
    elif args.jobs:
        missing = [key for key in args.jobs if key not in specs]
        if missing:
            print(f"Unknown job key(s): {', '.join(missing)}", file=sys.stderr)
            print(f"Known keys: {', '.join(sorted(specs))}", file=sys.stderr)
            return 1
        selected = [specs[key] for key in args.jobs]
    else:
        parser.error("pass --all or at least one --job")

    results = [
        import_job(spec, api_key=api_key, gh_pat=gh_pat, dry_run=args.dry_run)
        for spec in selected
    ]
    if args.json or args.dry_run:
        print(json.dumps(results, indent=2))
    else:
        for row in results:
            print(f"{row['action']}: {row['title']} (jobId={row.get('jobId', '?')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
