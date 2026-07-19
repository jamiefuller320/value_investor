"""Shared decreasing-resolution retention for offline library history."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Hashable, Literal, TypeVar

RetentionResolution = Literal["month", "quarter"]

# Dense window: keep every dated snapshot / run.
DEFAULT_RETENTION_DAYS = 400  # ~13 months
# After dense, keep one per calendar month until this age.
DEFAULT_MONTHLY_UNTIL_DAYS = DEFAULT_RETENTION_DAYS + 3 * 365  # ~4 years total
# Older: keep one per calendar quarter indefinitely.

T = TypeVar("T")


def retention_today(now: datetime | date | None = None) -> date:
    if isinstance(now, datetime):
        return now.astimezone(UTC).date() if now.tzinfo else now.date()
    if isinstance(now, date):
        return now
    return datetime.now(UTC).date()


def retention_period_key(file_date: date, resolution: RetentionResolution) -> str:
    if resolution == "month":
        return f"{file_date.year}-{file_date.month:02d}"
    if resolution == "quarter":
        return f"{file_date.year}-Q{(file_date.month - 1) // 3 + 1}"
    raise ValueError(f"Unsupported retention resolution {resolution!r}")


def dates_to_remove(
    dated_items: list[tuple[Hashable, date]],
    *,
    keep_days: int = DEFAULT_RETENTION_DAYS,
    monthly_until_days: int = DEFAULT_MONTHLY_UNTIL_DAYS,
    now: datetime | date | None = None,
) -> set[Hashable]:
    """
    Return item ids to drop under decreasing-resolution retention.

    ``dated_items`` is ``(item_id, item_date)``. Within each thinned period the
    newest date is kept; ties keep the first-seen id among that newest date.
    ``keep_days <= 0`` disables pruning (returns empty).
    """
    if keep_days <= 0 or not dated_items:
        return set()

    today = retention_today(now)
    dense_cutoff = today - timedelta(days=keep_days)
    monthly_until = max(int(monthly_until_days), int(keep_days))
    monthly_cutoff = today - timedelta(days=monthly_until)

    groups: dict[tuple[RetentionResolution, str], list[tuple[Hashable, date]]] = {}
    for item_id, item_date in dated_items:
        if item_date >= dense_cutoff:
            continue
        resolution: RetentionResolution = "month" if item_date >= monthly_cutoff else "quarter"
        key = (resolution, retention_period_key(item_date, resolution))
        groups.setdefault(key, []).append((item_id, item_date))

    remove: set[Hashable] = set()
    for entries in groups.values():
        if len(entries) <= 1:
            continue
        newest = max(item_date for _item_id, item_date in entries)
        keep_id = next(item_id for item_id, item_date in entries if item_date == newest)
        for item_id, _item_date in entries:
            if item_id != keep_id:
                remove.add(item_id)
    return remove
