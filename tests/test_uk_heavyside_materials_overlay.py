"""Unit tests for UK heavyside construction-materials overlay helpers."""

from __future__ import annotations

import math

import pandas as pd

from value_investor.scoring.uk_heavyside_materials_overlay import (
    is_uk_heavyside_construction_materials,
)


def test_is_uk_heavyside_tolerates_nan_sector_and_name():
    """Screen rows often carry float NaN for missing sector/name — must not raise."""
    assert is_uk_heavyside_construction_materials("XYZ.L", float("nan"), float("nan")) is False
    assert is_uk_heavyside_construction_materials("XYZ.L", None, math.nan) is False
    assert is_uk_heavyside_construction_materials("XYZ.L", pd.NA, pd.NA) is False


def test_is_uk_heavyside_ticker_allowlist_ignores_nan_fields():
    assert is_uk_heavyside_construction_materials("BREE.L", float("nan"), float("nan")) is True


def test_is_uk_heavyside_basic_materials_sector_match():
    assert (
        is_uk_heavyside_construction_materials(
            "ACME.L",
            "Acme Materials plc",
            "Basic Materials",
        )
        is True
    )
