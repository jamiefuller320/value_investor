"""Enable/disable euro_depth ingest + weekday ladder crons on cron-job.org."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from value_investor.euro_depth_ingest_dispatch import (
    EURO_INGEST_CRON_TITLES,
    cron_enabled_for_dispatch,
    evaluate_euro_ingest_dispatch,
    load_euro_ingest_dispatch,
)

CRONJOB_ENDPOINT = "https://api.cron-job.org"


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


def _set_job_enabled(
    job: dict[str, Any],
    *,
    enabled: bool,
    api_key: str,
) -> dict[str, Any]:
    job_id = job.get("jobId")
    if not job_id:
        return {"title": job.get("title"), "skipped": True, "reason": "missing jobId"}
    payload = {"job": {"enabled": bool(enabled)}}
    _cronjob_request("PATCH", f"/jobs/{job_id}", api_key=api_key, payload=payload)
    return {
        "title": job.get("title"),
        "jobId": job_id,
        "enabled": enabled,
        "action": "updated",
    }


def sync_euro_ingest_cron_jobs(
    evaluation: dict[str, Any] | None = None,
    *,
    api_key: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    api_key = (api_key or os.environ.get("CRONJOB_API_KEY") or "").strip()
    if evaluation is None:
        evaluation = load_euro_ingest_dispatch() or evaluate_euro_ingest_dispatch()
    desired = cron_enabled_for_dispatch(evaluation)
    title_map = {
        EURO_INGEST_CRON_TITLES["morning"]: desired["morning"],
        EURO_INGEST_CRON_TITLES["afternoon"]: desired["afternoon"],
        EURO_INGEST_CRON_TITLES["midafternoon"]: desired["midafternoon"],
        EURO_INGEST_CRON_TITLES["evening"]: desired["evening"],
        EURO_INGEST_CRON_TITLES["ladder_weekday"]: desired["ladder_weekday"],
        EURO_INGEST_CRON_TITLES["maintenance"]: desired["maintenance"],
        EURO_INGEST_CRON_TITLES["maintenance_afternoon"]: desired["maintenance_afternoon"],
        EURO_INGEST_CRON_TITLES["maintenance_midafternoon"]: desired[
            "maintenance_midafternoon"
        ],
        EURO_INGEST_CRON_TITLES["maintenance_evening"]: desired["maintenance_evening"],
    }
    if dry_run:
        return {
            "mode": evaluation.get("mode"),
            "desired": desired,
            "titles": title_map,
            "dry_run": True,
        }
    if not api_key:
        return {"skipped": True, "reason": "CRONJOB_API_KEY not set", "desired": desired}

    jobs_by_title = {job.get("title"): job for job in _list_jobs(api_key)}
    results: list[dict[str, Any]] = []
    for title, enabled in title_map.items():
        job = jobs_by_title.get(title)
        if not job:
            results.append({"title": title, "skipped": True, "reason": "job not registered"})
            continue
        results.append(_set_job_enabled(job, enabled=enabled, api_key=api_key))
    return {
        "mode": evaluation.get("mode"),
        "desired": desired,
        "results": results,
    }


__all__ = ["sync_euro_ingest_cron_jobs"]
