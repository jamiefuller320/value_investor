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

from value_investor.euro_depth_ingest_dispatch import (
    cron_enabled_for_dispatch,
    evaluate_euro_ingest_dispatch,
    load_euro_ingest_dispatch,
)
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
        return f"https://api.github.com/repos/{REPO}/actions/workflows/{self.workflow}/dispatches"


# Learning-phase FTSE live deepen: full buy-tier slot + higher body budget.
# Revisit when GHA minutes become scarce (see deferred-ideas / ingest docs).
_INGEST_LOOP_INPUTS = {
    "inputs": {
        "max_targets": "62",
        "max_bodies": "40",
        "max_runtime_seconds": "3600",
    }
}
_LEGACY_INGEST_TITLES_TO_DISABLE = (
    "FTSE ingest loop (Mon/Wed/Fri morning)",
    "FTSE ingest loop (Mon/Wed/Fri afternoon)",
    "FTSE ingest loop (Mon/Wed/Fri)",
)
_EURO_INGEST_LOOP_INPUTS = {
    "inputs": {
        "market": "euro_depth",
        "max_targets": "24",
    }
}


def _euro_dispatch_enabled() -> dict[str, bool]:
    evaluation = load_euro_ingest_dispatch() or evaluate_euro_ingest_dispatch()
    return cron_enabled_for_dispatch(evaluation)


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
            title="FTSE ingest loop (weekday morning)",
            workflow="ingest-loop.yml",
            body={"ref": REF, **_INGEST_LOOP_INPUTS},
            hours=[7],
            minutes=[5],
            wdays=[1, 2, 3, 4, 5],
        ),
        CronJobSpec(
            key="ingest-loop-afternoon",
            title="FTSE ingest loop (weekday afternoon)",
            workflow="ingest-loop.yml",
            body={"ref": REF, **_INGEST_LOOP_INPUTS},
            hours=[10],
            minutes=[5],
            wdays=[1, 2, 3, 4, 5],
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
        CronJobSpec(
            key="euro-ingest-loop-morning",
            title="Euro ingest loop (weekday morning)",
            workflow="euro-ingest-loop.yml",
            body={"ref": REF, **_EURO_INGEST_LOOP_INPUTS},
            hours=[7],
            minutes=[15],
            wdays=[1, 2, 3, 4, 5],
        ),
        CronJobSpec(
            key="euro-ingest-loop-afternoon",
            title="Euro ingest loop (weekday afternoon)",
            workflow="euro-ingest-loop.yml",
            body={"ref": REF, **_EURO_INGEST_LOOP_INPUTS},
            hours=[10],
            minutes=[15],
            wdays=[1, 2, 3, 4, 5],
        ),
        CronJobSpec(
            key="euro-ingest-loop-midafternoon",
            title="Euro ingest loop (weekday mid-afternoon)",
            workflow="euro-ingest-loop.yml",
            body={"ref": REF, **_EURO_INGEST_LOOP_INPUTS},
            hours=[13],
            minutes=[15],
            wdays=[1, 2, 3, 4, 5],
        ),
        CronJobSpec(
            key="euro-ingest-loop-evening",
            title="Euro ingest loop (weekday evening)",
            workflow="euro-ingest-loop.yml",
            body={"ref": REF, **_EURO_INGEST_LOOP_INPUTS},
            hours=[16],
            minutes=[15],
            wdays=[1, 2, 3, 4, 5],
        ),
        CronJobSpec(
            key="orchestrator-ladder-weekday",
            title="FTSE orchestrator (weekday ladder)",
            workflow="automation-orchestrator.yml",
            body={"ref": REF, "inputs": {"suite": "ladder_only", "force": "false"}},
            hours=[6],
            minutes=[50],
            wdays=[1, 2, 3, 4, 5],
        ),
        CronJobSpec(
            key="library-ingest-maintenance",
            title="Library ingest maintenance (parity markets)",
            workflow="library-ingest-maintenance.yml",
            body={"ref": REF, "inputs": {"max_targets": "4"}},
            hours=[7],
            minutes=[30],
            wdays=[1, 2, 3, 4, 5],
        ),
        CronJobSpec(
            key="library-ingest-sprint-morning",
            title="Library ingest sprint (parallel morning)",
            workflow="library-ingest-sprint.yml",
            body={"ref": REF, "inputs": {"max_targets": "24"}},
            hours=[7],
            minutes=[45],
            wdays=[1, 2, 3, 4, 5],
        ),
        CronJobSpec(
            key="library-ingest-sprint-afternoon",
            title="Library ingest sprint (parallel afternoon)",
            workflow="library-ingest-sprint.yml",
            body={"ref": REF, "inputs": {"max_targets": "24"}},
            hours=[10],
            minutes=[45],
            wdays=[1, 2, 3, 4, 5],
        ),
        CronJobSpec(
            key="library-ingest-sprint-midafternoon",
            title="Library ingest sprint (parallel mid-afternoon)",
            workflow="library-ingest-sprint.yml",
            body={"ref": REF, "inputs": {"max_targets": "24"}},
            hours=[13],
            minutes=[45],
            wdays=[1, 2, 3, 4, 5],
        ),
        CronJobSpec(
            key="library-ingest-sprint-evening",
            title="Library ingest sprint (parallel evening)",
            workflow="library-ingest-sprint.yml",
            body={"ref": REF, "inputs": {"max_targets": "24"}},
            hours=[16],
            minutes=[45],
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


def _parallel_sprint_dispatch_enabled() -> bool:
    """True when any ingest_parallel_sprint market still needs sprint ingest."""
    from value_investor.agent_model_policy import load_policy
    from value_investor.library_ingest_dispatch import (
        evaluate_library_ingest_dispatch,
        list_library_ingest_parallel_sprint_markets,
    )

    policy = load_policy()
    parallel = list_library_ingest_parallel_sprint_markets(policy=policy)
    for market_id in parallel:
        evaluation = evaluate_library_ingest_dispatch(market_id, policy=policy)
        if evaluation.get("should_run_sprint_ingest"):
            return True
    return False


def _job_enabled(spec: CronJobSpec) -> bool:
    if spec.key.startswith("library-ingest-sprint-"):
        return _parallel_sprint_dispatch_enabled()
    euro_keys = {
        "euro-ingest-loop-morning": "morning",
        "euro-ingest-loop-afternoon": "afternoon",
        "euro-ingest-loop-midafternoon": "midafternoon",
        "euro-ingest-loop-evening": "evening",
        "orchestrator-ladder-weekday": "ladder_weekday",
        "library-ingest-maintenance": "maintenance",
        "library-ingest-sprint-morning": "morning",
        "library-ingest-sprint-afternoon": "afternoon",
        "library-ingest-sprint-midafternoon": "midafternoon",
        "library-ingest-sprint-evening": "evening",
    }
    slot = euro_keys.get(spec.key)
    if slot is None:
        return True
    return bool(_euro_dispatch_enabled().get(slot))


def _build_job_payload(spec: CronJobSpec, gh_pat: str) -> dict[str, Any]:
    return {
        "job": {
            "title": spec.title,
            "url": spec.url,
            "enabled": _job_enabled(spec),
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


def disable_legacy_ingest_jobs(
    *,
    api_key: str,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Disable superseded Mon/Wed/Fri ingest crons that double-fire with weekday jobs."""
    results: list[dict[str, Any]] = []
    if dry_run and not api_key:
        return [
            {"action": "would_disable", "title": title, "jobId": None}
            for title in _LEGACY_INGEST_TITLES_TO_DISABLE
        ]
    existing = {job.get("title"): job for job in _list_jobs(api_key)}
    for title in _LEGACY_INGEST_TITLES_TO_DISABLE:
        current = existing.get(title)
        if not current or not current.get("jobId"):
            results.append({"action": "missing", "title": title})
            continue
        if not current.get("enabled", True):
            results.append(
                {"action": "already_disabled", "title": title, "jobId": current["jobId"]}
            )
            continue
        if dry_run:
            results.append({"action": "would_disable", "title": title, "jobId": current["jobId"]})
            continue
        # Preserve URL/schedule; only flip enabled off.
        payload = {
            "job": {
                "title": title,
                "url": current.get("url"),
                "enabled": False,
                "saveResponses": bool(current.get("saveResponses", True)),
                "requestMethod": int(current.get("requestMethod") or REQUEST_METHOD_POST),
                "schedule": current.get("schedule") or {},
                "extendedData": current.get("extendedData") or {},
            }
        }
        _cronjob_request(
            "PATCH",
            f"/jobs/{current['jobId']}",
            api_key=api_key,
            payload=payload,
        )
        results.append({"action": "disabled", "title": title, "jobId": current["jobId"]})
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import cron-job.org production schedules")
    parser.add_argument("--all", action="store_true", help="Import every production job")
    parser.add_argument(
        "--job", action="append", dest="jobs", help="Import one job key (repeatable)"
    )
    parser.add_argument(
        "--disable-legacy-ingest",
        action="store_true",
        help="Disable superseded Mon/Wed/Fri FTSE ingest cron jobs",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print payloads without calling cron-job.org"
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable results")
    args = parser.parse_args(argv)

    api_key = os.environ.get("CRONJOB_API_KEY", "").strip()
    if not args.dry_run and not api_key:
        print("CRONJOB_API_KEY is required (cron-job.org → Settings → API)", file=sys.stderr)
        return 1

    specs = {spec.key: spec for spec in _job_specs()}
    selected: list[CronJobSpec] = []
    if args.all:
        selected = list(specs.values())
    elif args.jobs:
        missing = [key for key in args.jobs if key not in specs]
        if missing:
            print(f"Unknown job key(s): {', '.join(missing)}", file=sys.stderr)
            print(f"Known keys: {', '.join(sorted(specs))}", file=sys.stderr)
            return 1
        selected = [specs[key] for key in args.jobs]
    elif not args.disable_legacy_ingest:
        parser.error("pass --all, --disable-legacy-ingest, or at least one --job")

    gh_pat = ""
    if selected:
        if args.dry_run:
            gh_pat = resolve_workflow_dispatch_pat() or "github_pat_dry_run_placeholder"
        else:
            try:
                gh_pat = require_workflow_dispatch_pat()
            except RuntimeError as exc:
                print(str(exc), file=sys.stderr)
                return 1

    results: list[dict[str, Any]] = [
        import_job(spec, api_key=api_key, gh_pat=gh_pat, dry_run=args.dry_run)
        for spec in selected
    ]
    if args.all or args.disable_legacy_ingest:
        results.extend(
            disable_legacy_ingest_jobs(api_key=api_key, dry_run=args.dry_run)
        )
    if args.json or args.dry_run:
        print(json.dumps(results, indent=2))
    else:
        for row in results:
            title = row.get("title", "?")
            print(f"{row['action']}: {title} (jobId={row.get('jobId', '?')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
