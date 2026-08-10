"""Shared pytest fixtures for stable, weekday-safe time pinning."""

from __future__ import annotations

from datetime import datetime

import pytest
from pinned_time import weekday_noon_utc


@pytest.fixture
def pinned_weekday_noon_utc() -> datetime:
    return weekday_noon_utc()
