"""Library grow health log and stall detection for the engineering loop."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.agent_model_policy import DEFAULT_POLICY_PATH, load_policy
from value_investor.data_library import (
    DEFAULT_LIBRARY_ROOT,
    load_manifest,
    summarize_manifest_fetch_health,
)
from value_investor.library_screen import assess_library_metrics_health
from value_investor.storage import read_json, write_json

logger = logging.getLogger(__name__)

DEFAULT_GROW_HEALTH_LOG = Path("docs/data/library/grow_health_log.json")
DEFAULT_STALL_RUNS = 2


def load_grow_health_log(path: Path = DEFAULT_GROW_HEALTH_LOG) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "entries": []}
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError):
        return {"schema_version": 1, "entries": []}
    if not isinstance(payload, dict):
        return {"schema_version": 1, "entries": []}
    payload.setdefault("schema_version", 1)
    payload.setdefault("entries", [])
    return payload


def snapshot_focus_market_health(
    *,
    root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    market_id: str | None = None,
) -> dict[str, Any]:
    """Honest health snapshot for the library focus market (fetch ok vs usable metrics)."""
    policy = load_policy(policy_path)
    market = market_id or str(policy.get("focus_market") or "").strip()
    if not market:
        return {"market": "", "error": "no focus_market in policy"}

    manifest = load_manifest(root, market)
    fetch = summarize_manifest_fetch_health(manifest)
    metrics = assess_library_metrics_health(root, market)
    ticker_count = int(fetch.get("ticker_count") or 0)
    usable_rows = int(metrics.get("usable_rows") or 0)
    ok_fetch = int(fetch.get("ok_fetch_count") or 0)
    latent_gap = bool(ticker_count > 0 and ok_fetch == 0 and usable_rows == 0)
    manifest_inflated = bool(
        ticker_count > 0
        and int(manifest.get("coverage_count") or 0) >= ticker_count
        and usable_rows == 0
    )

    return {
        "snapshot_at": datetime.now(UTC).isoformat(),
        "market": market,
        "ticker_count": ticker_count,
        "ok_fetch_count": ok_fetch,
        "failed_fetch_count": int(fetch.get("failed_fetch_count") or 0),
        "manifest_coverage_count": int(manifest.get("coverage_count") or 0),
        "honest_coverage_count": int(fetch.get("honest_coverage_count") or 0),
        "honest_coverage_pct": fetch.get("honest_coverage_pct"),
        "usable_metrics_rows": usable_rows,
        "total_metrics_rows": int(metrics.get("total_rows") or 0),
        "latent_failure": latent_gap or manifest_inflated,
        "manifest_inflated": manifest_inflated,
        "sample_errors": list(metrics.get("sample_errors") or [])[:5],
        "sample_tickers": list(metrics.get("sample_tickers") or [])[:5],
    }


def append_grow_health_log(
    entry: dict[str, Any],
    *,
    path: Path = DEFAULT_GROW_HEALTH_LOG,
    keep: int = 52,
) -> dict[str, Any]:
    payload = load_grow_health_log(path)
    entries = list(payload.get("entries") or [])
    entries.append(entry)
    payload["entries"] = entries[-max(1, int(keep)) :]
    payload["updated_at"] = datetime.now(UTC).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, payload, compact=False)
    return payload


def record_library_grow_health(
    *,
    root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    market_id: str | None = None,
    source: str = "library_ladder",
    log_path: Path = DEFAULT_GROW_HEALTH_LOG,
) -> dict[str, Any]:
    """Append a focus-market health row and include deltas vs the previous entry."""
    after = snapshot_focus_market_health(root=root, policy_path=policy_path, market_id=market_id)
    payload = load_grow_health_log(log_path)
    entries = list(payload.get("entries") or [])
    market = str(after.get("market") or "")
    prev = next(
        (row for row in reversed(entries) if str(row.get("market") or "") == market),
        None,
    )
    before = prev.get("health_after") if isinstance(prev, dict) else None
    if isinstance(before, dict):
        delta_ok = int(after.get("ok_fetch_count") or 0) - int(before.get("ok_fetch_count") or 0)
        delta_usable = int(after.get("usable_metrics_rows") or 0) - int(
            before.get("usable_metrics_rows") or 0
        )
        delta_failed = int(after.get("failed_fetch_count") or 0) - int(
            before.get("failed_fetch_count") or 0
        )
    else:
        delta_ok = 0
        delta_usable = 0
        delta_failed = 0

    entry = {
        "run_at": datetime.now(UTC).isoformat(),
        "source": source,
        "market": market,
        "health_before": before or {},
        "health_after": after,
        "delta_ok_fetch": delta_ok,
        "delta_usable_metrics": delta_usable,
        "delta_failed_fetch": delta_failed,
    }
    append_grow_health_log(entry, path=log_path)
    return entry


def library_grow_stalled(
    *,
    log_path: Path = DEFAULT_GROW_HEALTH_LOG,
    min_runs: int = DEFAULT_STALL_RUNS,
    market_id: str | None = None,
) -> bool:
    """
    True when focus-market grow shows no progress across recent ladder runs.

    Detects latent failures: failed fetches persist and usable metrics do not improve.
    """
    payload = load_grow_health_log(log_path)
    entries = list(payload.get("entries") or [])
    if market_id:
        entries = [row for row in entries if str(row.get("market") or "") == market_id]
    if len(entries) < max(2, int(min_runs)):
        return False

    recent = entries[-max(2, int(min_runs)) :]
    usable_counts = [
        int((row.get("health_after") or {}).get("usable_metrics_rows") or 0) for row in recent
    ]
    ok_counts = [
        int((row.get("health_after") or {}).get("ok_fetch_count") or 0) for row in recent
    ]
    failed_counts = [
        int((row.get("health_after") or {}).get("failed_fetch_count") or 0) for row in recent
    ]
    latent_flags = [
        bool((row.get("health_after") or {}).get("latent_failure")) for row in recent
    ]

    if not any(failed_counts) and not any(latent_flags):
        return False
    if len(set(usable_counts)) != 1 or len(set(ok_counts)) != 1:
        return False
    if usable_counts[-1] > 0:
        return False

    for row in recent:
        if int(row.get("delta_ok_fetch") or 0) > 0 or int(row.get("delta_usable_metrics") or 0) > 0:
            return False
    return True


def has_open_library_coverage_tasks(
    tasks_path: Path = Path("docs/data/engineering_tasks.json"),
    *,
    market_id: str | None = None,
) -> bool:
    from value_investor.engineering_tasks import (
        _open_library_metrics_task_for_market,
        load_engineering_tasks,
    )

    rows = list(load_engineering_tasks(tasks_path).get("tasks") or [])
    if market_id:
        return _open_library_metrics_task_for_market(rows, market_id)
    for row in rows:
        status = str(row.get("status") or "open")
        if status in {"open", "pr_open"} and str(row.get("area") or "").lower() == "coverage":
            return True
    return False


def compile_library_stall_engineering_task(
    *,
    root: Path = DEFAULT_LIBRARY_ROOT,
    policy_path: Path = DEFAULT_POLICY_PATH,
    log_path: Path = DEFAULT_GROW_HEALTH_LOG,
    tasks_path: Path = Path("docs/data/engineering_tasks.json"),
    min_runs: int = DEFAULT_STALL_RUNS,
) -> dict[str, Any]:
    """Queue a coverage engineering task when library grow health is stalled."""
    health = snapshot_focus_market_health(root=root, policy_path=policy_path)
    market = str(health.get("market") or "")
    if not market:
        return {"compiled_count": 0, "reason": "no focus market"}

    if not library_grow_stalled(log_path=log_path, min_runs=min_runs, market_id=market):
        return {"compiled_count": 0, "reason": "library grow health not stalled"}

    if has_open_library_coverage_tasks(tasks_path, market_id=market):
        return {
            "compiled_count": 0,
            "reason": f"open library coverage task already exists for {market}",
        }

    ladder_result = {
        "run_at": datetime.now(UTC).isoformat(),
        "focus_market": market,
        "layers": {
            "fundamentals": {"status": [{"market": market}]},
            "screen_lite": {
                "skipped": True,
                "reason": "library_grow_stall_detected",
                "usable_metrics_rows": health.get("usable_metrics_rows"),
                "manifest_coverage_count": health.get("manifest_coverage_count"),
            },
        },
    }
    from value_investor.engineering_tasks import draft_library_ladder_engineering_tasks

    drafted = draft_library_ladder_engineering_tasks(
        ladder_result,
        root=root,
        policy_path=policy_path,
        tasks_path=tasks_path,
        committed_path=tasks_path,
    )
    return {
        "compiled_count": int(drafted.get("drafted_count") or 0),
        "task_ids": list(drafted.get("task_ids") or []),
        "market": market,
        "health": health,
        "stall_runs": min_runs,
        "source": "library_grow_stall",
    }


__all__ = [
    "DEFAULT_GROW_HEALTH_LOG",
    "DEFAULT_STALL_RUNS",
    "append_grow_health_log",
    "compile_library_stall_engineering_task",
    "has_open_library_coverage_tasks",
    "library_grow_stalled",
    "load_grow_health_log",
    "record_library_grow_health",
    "snapshot_focus_market_health",
]
