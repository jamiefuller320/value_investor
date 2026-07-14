"""Filters that remove names the value models are not designed to score."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

# ICB / Wikipedia sectors that are closed-end funds, trusts, or similar vehicles.
_VEHICLE_SECTOR_FRAGMENTS = (
    "investment trust",
    "collective investment",
    "equity investment",
    "real estate investment trust",
)

_TRUST_WORD = re.compile(r"\btrust\b", re.IGNORECASE)
_FUND_WORD = re.compile(r"\bfund\b", re.IGNORECASE)
_ORD_SUFFIX = re.compile(r"(?:^|\s)ord(?:\s|$|\.)", re.IGNORECASE)
_VENTURES_WORD = re.compile(r"\bventures\b", re.IGNORECASE)

# Infrastructure / renewable listed funds often mis-tagged into Utilities/Energy.
_VEHICLE_NAME_FRAGMENTS = (
    "greencoat",
    "renewables infrastructure",
    "the renewables",
)


def is_investment_vehicle(
    *,
    name: str | None = None,
    sector: str | None = None,
) -> bool:
    """
    Return True when a constituent looks like a closed-end fund, investment trust,
    REIT sleeve, or similar vehicle rather than an operating company.

    Graham-style operating metrics (ROE, margins, FCF, etc.) are usually absent or
    misleading for these names, so they inflate ``insufficient_data`` counts.
    """
    sector_l = (sector or "").strip().lower()
    name_l = (name or "").strip().lower()

    if any(fragment in sector_l for fragment in _VEHICLE_SECTOR_FRAGMENTS):
        return True

    if _TRUST_WORD.search(name_l):
        return True

    # Asset managers such as "Jupiter Fund Management" stay in the universe.
    if _FUND_WORD.search(name_l) and "fund management" not in name_l:
        return True

    # Wikipedia often lists investment trusts with an "Ord" share-class suffix.
    if _ORD_SUFFIX.search(name_l):
        return True

    if _VENTURES_WORD.search(name_l):
        return True

    if any(fragment in name_l for fragment in _VEHICLE_NAME_FRAGMENTS):
        return True

    return False


def partition_investment_vehicles(
    constituents: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Split constituents into (operating companies, investment vehicles).

    Expects optional ``name`` / ``sector`` columns; rows without both are kept.
    """
    if constituents.empty:
        empty = constituents.copy()
        return empty, empty

    names = constituents["name"] if "name" in constituents.columns else [None] * len(constituents)
    sectors = constituents["sector"] if "sector" in constituents.columns else [None] * len(constituents)
    mask = [
        is_investment_vehicle(name=name, sector=sector)
        for name, sector in zip(names, sectors, strict=True)
    ]
    flags = pd.Series(mask, index=constituents.index)
    kept = constituents.loc[~flags].reset_index(drop=True)
    excluded = constituents.loc[flags].reset_index(drop=True)
    return kept, excluded


def excluded_vehicle_records(excluded: pd.DataFrame, *, limit: int = 40) -> list[dict[str, Any]]:
    """Compact records for run summaries / email footnotes."""
    if excluded.empty:
        return []
    cols = [c for c in ("ticker", "name", "sector", "index") if c in excluded.columns]
    records = excluded[cols].head(limit).to_dict(orient="records")
    return [{k: (None if pd.isna(v) else v) for k, v in row.items()} for row in records]
