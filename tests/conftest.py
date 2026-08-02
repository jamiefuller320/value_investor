"""Shared pytest fixtures for stable, weekday-safe time pinning."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest


def weekday_noon_utc() -> datetime:
    """Pinned Wednesday noon UTC — stable for workflow expected_today checks."""
    return datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def pinned_weekday_noon_utc() -> datetime:
    return weekday_noon_utc()
