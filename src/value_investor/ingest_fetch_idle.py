"""Decide whether a predecessor run is actually fetching.

Stream 2 used to treat any queued, waiting, or pending workflow run as busy.
A later wave sitting in the concurrency queue then burned the 2400s cap and
the spare fetch never started. This check looks only at in-progress runs, and
only at the step that fetches.

An empty jobs payload, or an API payload that is not a job list, is treated as
busy so a missing answer does not skip the wait.
"""

from __future__ import annotations

import json
import sys
from typing import Any

EURO_WORKFLOW = "euro-ingest-loop.yml"
SPRINT_WORKFLOW = "library-ingest-sprint.yml"
FETCH_STEP = "Run parallel library ingest sprint"


def _job_name(job: dict[str, Any]) -> str:
    return str(job.get("name") or "").strip()


def euro_jobs_fetching(jobs: list[dict[str, Any]]) -> bool:
    """Euro is busy while its gate is undecided or its ingest job is about to run."""
    by_name = {_job_name(job): job for job in jobs}
    check = by_name.get("check")
    ingest = by_name.get("euro-ingest-loop")
    if check is not None and str(check.get("status") or "") == "in_progress":
        return True
    if ingest is not None and str(ingest.get("status") or "") in {"in_progress", "queued"}:
        return True
    return False


def sprint_jobs_fetching(jobs: list[dict[str, Any]]) -> bool:
    """Stream 1 is busy only while its fetch step is running or about to run.

    A fetch step that is still queued because the wait step has not finished
    is not a fetch. A fetch step queued after that wait completed is the next
    thing the runner will do, so stream 2 keeps waiting.
    """
    job = next((row for row in jobs if _job_name(row) == "library-ingest-sprint"), None)
    if job is None:
        return True
    status = str(job.get("status") or "")
    if status == "queued":
        return True
    if status != "in_progress":
        return False
    steps = [row for row in (job.get("steps") or []) if isinstance(row, dict)]
    fetch = next(
        (step for step in steps if str(step.get("name") or "") == FETCH_STEP),
        None,
    )
    if fetch is None:
        return True
    fetch_status = str(fetch.get("status") or "")
    if fetch_status == "in_progress":
        return True
    if fetch_status != "queued":
        return False
    wait = next(
        (step for step in steps if str(step.get("name") or "").startswith("Wait for")),
        None,
    )
    return bool(wait is not None and str(wait.get("status") or "") == "completed")


def jobs_are_fetching(workflow: str, jobs: list[dict[str, Any]] | None) -> bool:
    """Return True when this in-progress run should hold stream 2."""
    if not jobs:
        return True
    name = str(workflow or "").rsplit("/", 1)[-1]
    if name.startswith("euro-ingest"):
        return euro_jobs_fetching(jobs)
    if "sprint-2" in name:
        return False
    return sprint_jobs_fetching(jobs)


def _jobs_from_payload(payload: Any) -> list[dict[str, Any]] | None:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get("jobs")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return None


def main(argv: list[str] | None = None) -> int:
    """Read a jobs payload on stdin. Exit 0 when the run is fetching, else 1.

    A payload that is not JSON is fetching (fail closed). ``--workflow`` selects
    the euro gate or the stream-1 fetch step.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    workflow = SPRINT_WORKFLOW
    if "--workflow" in args:
        idx = args.index("--workflow")
        if idx + 1 >= len(args):
            print("ingest_fetch_idle: --workflow needs a file name", file=sys.stderr)
            return 2
        workflow = args[idx + 1]
    if "--decide" not in args:
        print("ingest_fetch_idle: --decide is required", file=sys.stderr)
        return 2
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0
    jobs = _jobs_from_payload(payload)
    if jobs is None:
        return 0
    return 0 if jobs_are_fetching(workflow, jobs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
