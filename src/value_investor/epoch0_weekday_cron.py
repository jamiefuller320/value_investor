"""Ensure cron-job.org local-open slots exist for admitted epoch-0 markets.

Timezone-bucket jobs (ASX / EU / US EDT / US EST) fire ``library-epoch0-weekday.yml``.
One market does not get its own cron — admitting a market upserts the bucket(s)
for its session timezone. Soft-skips when secrets are missing so unit tests and
secret-less runners stay safe.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from value_investor.market_paper_shard import session_defaults_for_market
from value_investor.market_shard_admission import admitted_learning_markets_for_policy
from value_investor.workflow_pat import resolve_workflow_dispatch_pat

logger = logging.getLogger(__name__)

CRONJOB_ENDPOINT = "https://api.cron-job.org"
REQUEST_METHOD_POST = 1
EPOCH0_WEEKDAY_WORKFLOW = "library-epoch0-weekday.yml"
DEFAULT_REPO = "jamiefuller320/value_investor"
DEFAULT_REF = "main"

# Shared UTC slots — keys match scripts/import_cron_jobs.py.
EPOCH0_WEEKDAY_SLOTS: dict[str, dict[str, Any]] = {
    "library-epoch0-weekday-asx": {
        "title": "Library epoch-0 weekday (ASX local-open)",
        "hours": [0],
        "minutes": [45],
        "wdays": [1, 2, 3, 4, 5],
        "timezones": ("Australia/Sydney",),
    },
    "library-epoch0-weekday-euro": {
        "title": "Library epoch-0 weekday (EU local-open)",
        "hours": [8],
        "minutes": [45],
        "wdays": [1, 2, 3, 4, 5],
        # London (ftse_smallcap default) settles before this slot on weekdays.
        "timezones": ("Europe/Paris", "Europe/London", "Europe/Berlin", "Europe/Amsterdam"),
    },
    "library-epoch0-weekday-us-edt": {
        "title": "Library epoch-0 weekday (US EDT local-open)",
        "hours": [14],
        "minutes": [15],
        "wdays": [1, 2, 3, 4, 5],
        "timezones": ("America/New_York",),
    },
    "library-epoch0-weekday-us-est": {
        "title": "Library epoch-0 weekday (US EST local-open)",
        "hours": [15],
        "minutes": [15],
        "wdays": [1, 2, 3, 4, 5],
        "timezones": ("America/New_York",),
    },
}


def _repo() -> str:
    return (os.environ.get("REPO") or DEFAULT_REPO).strip() or DEFAULT_REPO


def _ref() -> str:
    return (os.environ.get("REF") or DEFAULT_REF).strip() or DEFAULT_REF


def cron_keys_for_timezone(timezone: str) -> list[str]:
    """Return epoch-0 weekday cron keys that cover ``timezone``."""
    tz = str(timezone or "").strip()
    if not tz:
        return []
    keys: list[str] = []
    for key, spec in EPOCH0_WEEKDAY_SLOTS.items():
        if tz in (spec.get("timezones") or ()):
            keys.append(key)
    return keys


def cron_keys_for_market(market_id: str) -> list[str]:
    """Map a market's session timezone to shared epoch-0 weekday cron keys."""
    session = session_defaults_for_market(str(market_id or "").strip())
    return cron_keys_for_timezone(str(session.get("timezone") or ""))


def cron_keys_for_markets(markets: list[str] | tuple[str, ...] | None) -> list[str]:
    keys: list[str] = []
    for market_id in markets or []:
        for key in cron_keys_for_market(str(market_id)):
            if key not in keys:
                keys.append(key)
    return keys


def cron_keys_for_policy(policy: dict[str, Any] | None) -> list[str]:
    return cron_keys_for_markets(admitted_learning_markets_for_policy(policy))


def unmapped_admitted_markets(policy: dict[str, Any] | None) -> list[str]:
    """Admitted markets whose session timezone has no epoch-0 cron bucket."""
    out: list[str] = []
    for market_id in admitted_learning_markets_for_policy(policy):
        if not cron_keys_for_market(market_id):
            out.append(market_id)
    return out


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


def _job_payload(key: str, *, gh_pat: str) -> dict[str, Any]:
    spec = EPOCH0_WEEKDAY_SLOTS[key]
    repo = _repo()
    return {
        "job": {
            "title": spec["title"],
            "url": (
                f"https://api.github.com/repos/{repo}/actions/workflows/"
                f"{EPOCH0_WEEKDAY_WORKFLOW}/dispatches"
            ),
            "enabled": True,
            "saveResponses": True,
            "requestMethod": REQUEST_METHOD_POST,
            "schedule": {
                "timezone": "UTC",
                "expiresAt": 0,
                "hours": list(spec["hours"]),
                "minutes": list(spec["minutes"]),
                "mdays": [-1],
                "months": [-1],
                "wdays": list(spec["wdays"]),
            },
            "extendedData": {
                "headers": {
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {gh_pat}",
                },
                "body": json.dumps(
                    {"ref": _ref(), "inputs": {"force": "false"}},
                ),
            },
        }
    }


def ensure_epoch0_weekday_crons(
    *,
    keys: list[str] | None = None,
    markets: list[str] | None = None,
    policy: dict[str, Any] | None = None,
    api_key: str | None = None,
    gh_pat: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Upsert epoch-0 weekday cron-job.org slots for the given keys/markets/policy.

    Soft-skips when ``CRONJOB_API_KEY`` or ``WORKFLOW_DISPATCH_PAT`` is unset
    (unless ``dry_run``).
    """
    if keys is None:
        if markets is not None:
            keys = cron_keys_for_markets(markets)
        elif policy is not None:
            keys = cron_keys_for_policy(policy)
        else:
            keys = []
    wanted = [k for k in keys if k in EPOCH0_WEEKDAY_SLOTS]
    unknown = [k for k in (keys or []) if k not in EPOCH0_WEEKDAY_SLOTS]
    unmapped = unmapped_admitted_markets(policy) if policy is not None else []
    if markets:
        for mid in markets:
            if mid and not cron_keys_for_market(mid) and mid not in unmapped:
                unmapped.append(mid)

    if not wanted:
        return {
            "skipped": True,
            "reason": "no epoch0 weekday cron keys in scope",
            "keys": [],
            "unknown_keys": unknown,
            "unmapped_markets": unmapped,
            "dry_run": dry_run,
        }

    api_key = (api_key or os.environ.get("CRONJOB_API_KEY") or "").strip()
    gh_pat = (gh_pat or resolve_workflow_dispatch_pat() or "").strip()
    if dry_run:
        return {
            "skipped": False,
            "dry_run": True,
            "keys": wanted,
            "unknown_keys": unknown,
            "unmapped_markets": unmapped,
            "results": [
                {
                    "action": "upsert",
                    "key": key,
                    "title": EPOCH0_WEEKDAY_SLOTS[key]["title"],
                    "payload": _job_payload(key, gh_pat=gh_pat or "github_pat_dry_run_placeholder"),
                }
                for key in wanted
            ],
        }
    if not api_key:
        return {
            "skipped": True,
            "reason": "CRONJOB_API_KEY not set",
            "keys": wanted,
            "unmapped_markets": unmapped,
        }
    if not gh_pat:
        return {
            "skipped": True,
            "reason": "WORKFLOW_DISPATCH_PAT not set",
            "keys": wanted,
            "unmapped_markets": unmapped,
        }

    existing = {job.get("title"): job for job in _list_jobs(api_key)}
    results: list[dict[str, Any]] = []
    for key in wanted:
        payload = _job_payload(key, gh_pat=gh_pat)
        title = EPOCH0_WEEKDAY_SLOTS[key]["title"]
        current = existing.get(title)
        if current and current.get("jobId"):
            _cronjob_request(
                "PATCH",
                f"/jobs/{current['jobId']}",
                api_key=api_key,
                payload=payload,
            )
            results.append(
                {"action": "updated", "key": key, "title": title, "jobId": current["jobId"]}
            )
            continue
        created = _cronjob_request("PUT", "/jobs", api_key=api_key, payload=payload)
        results.append(
            {
                "action": "created",
                "key": key,
                "title": title,
                "jobId": created.get("jobId"),
            }
        )
    return {
        "skipped": False,
        "keys": wanted,
        "unknown_keys": unknown,
        "unmapped_markets": unmapped,
        "results": results,
    }


def ensure_epoch0_weekday_crons_for_markets(
    markets: list[str],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    return ensure_epoch0_weekday_crons(markets=markets, dry_run=dry_run)


def ensure_epoch0_weekday_crons_for_policy(
    policy: dict[str, Any],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    return ensure_epoch0_weekday_crons(policy=policy, dry_run=dry_run)


__all__ = [
    "EPOCH0_WEEKDAY_SLOTS",
    "EPOCH0_WEEKDAY_WORKFLOW",
    "cron_keys_for_market",
    "cron_keys_for_markets",
    "cron_keys_for_policy",
    "cron_keys_for_timezone",
    "ensure_epoch0_weekday_crons",
    "ensure_epoch0_weekday_crons_for_markets",
    "ensure_epoch0_weekday_crons_for_policy",
    "unmapped_admitted_markets",
]
