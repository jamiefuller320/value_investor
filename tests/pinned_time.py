"""Pinned UTC timestamps for weekday-stable workflow tests."""

from __future__ import annotations

from datetime import UTC, datetime


def weekday_noon_utc() -> datetime:
    """Pinned Wednesday noon UTC — stable for workflow expected_today checks."""
    return datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)
