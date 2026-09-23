"""Task / PR completion monitor for the Automation dashboard.

Combines engineering merge history (auto vs manual) with PR-fix intervention
occasions into a compact today / yesterday + multi-day series for queue_health.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from value_investor.engineering_narrow_merge import (
    list_engineering_merges_on_day,
    summarize_engineering_merges_by_day,
)
from value_investor.engineering_tasks import COMMITTED_TASKS_PATH
from value_investor.pr_fix_occasions import (
    DEFAULT_PR_FIX_OCCASIONS_PATH,
    summarize_pr_fix_occasions_by_day,
)

DEFAULT_HISTORY_DAYS = 14


def _empty_day_counts(date_key: str) -> dict[str, Any]:
    return {
        "date": date_key,
        "merged_total": 0,
        "merged_auto": 0,
        "merged_manual": 0,
        "verified": 0,
        "fix_interventions": 0,
        "fix_ci_check": 0,
        "fix_merge_conflict": 0,
        "fix_ci_and_merge": 0,
    }


def _day_summary_from_merges(
    *,
    day: str,
    merge_row: dict[str, Any] | None,
    fix_row: dict[str, Any] | None,
) -> dict[str, Any]:
    out = _empty_day_counts(day)
    if merge_row:
        out["merged_total"] = int(merge_row.get("merged_total") or 0)
        out["merged_auto"] = int(merge_row.get("merged_auto") or 0)
        out["merged_manual"] = int(merge_row.get("merged_manual") or 0)
        out["verified"] = int(merge_row.get("verified") or 0)
    if fix_row:
        out["fix_interventions"] = int(fix_row.get("fix_interventions") or 0)
        out["fix_ci_check"] = int(fix_row.get("fix_ci_check") or 0)
        out["fix_merge_conflict"] = int(fix_row.get("fix_merge_conflict") or 0)
        out["fix_ci_and_merge"] = int(fix_row.get("fix_ci_and_merge") or 0)
    return out


def build_task_completion_monitor(
    *,
    tasks_path: Path | None = None,
    pr_fix_path: Path | None = None,
    days: int = DEFAULT_HISTORY_DAYS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build today/yesterday readouts + history for the completion monitor."""
    now = now or datetime.now(UTC)
    today_dt = now.astimezone(UTC).date()
    yesterday_dt = today_dt - timedelta(days=1)
    today = today_dt.isoformat()
    yesterday = yesterday_dt.isoformat()
    window = max(2, int(days))

    path = Path(tasks_path) if tasks_path is not None else COMMITTED_TASKS_PATH
    fix_path = Path(pr_fix_path) if pr_fix_path is not None else DEFAULT_PR_FIX_OCCASIONS_PATH

    merge_history = summarize_engineering_merges_by_day(tasks_path=path, days=window, now=now)
    fix_history = summarize_pr_fix_occasions_by_day(path=fix_path, days=window, now=now)
    merge_by_day = {str(row.get("date")): row for row in merge_history}
    fix_by_day = {str(row.get("date")): row for row in fix_history}

    history: list[dict[str, Any]] = []
    for day_key in sorted(set(merge_by_day) | set(fix_by_day)):
        history.append(
            _day_summary_from_merges(
                day=day_key,
                merge_row=merge_by_day.get(day_key),
                fix_row=fix_by_day.get(day_key),
            )
        )

    today_rows = list_engineering_merges_on_day(day=today, tasks_path=path)
    yesterday_rows = list_engineering_merges_on_day(day=yesterday, tasks_path=path)

    return {
        "timezone": "UTC",
        "history_days": window,
        "today": _day_summary_from_merges(
            day=today,
            merge_row=merge_by_day.get(today),
            fix_row=fix_by_day.get(today),
        ),
        "yesterday": _day_summary_from_merges(
            day=yesterday,
            merge_row=merge_by_day.get(yesterday),
            fix_row=fix_by_day.get(yesterday),
        ),
        "history": history,
        "merges_today": today_rows,
        "merges_yesterday": yesterday_rows,
    }


__all__ = [
    "DEFAULT_HISTORY_DAYS",
    "build_task_completion_monitor",
]
