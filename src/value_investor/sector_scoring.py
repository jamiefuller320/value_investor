"""Sector-relative valuation and quality scoring."""

from __future__ import annotations

from typing import Any

import pandas as pd

from value_investor.models.ranking import compute_derived_columns, percentile_rank

SECTOR_METRICS = {
    "trailing_pe": False,
    "price_to_book": False,
    "dividend_yield": True,
    "fcf_yield": True,
    "ev_ebitda": False,
    "return_on_equity": True,
}

SECTOR_WEIGHTS = {
    "trailing_pe": 0.25,
    "price_to_book": 0.20,
    "dividend_yield": 0.15,
    "fcf_yield": 0.20,
    "ev_ebitda": 0.10,
    "return_on_equity": 0.10,
}

MIN_SECTOR_SIZE = 3


def _sector_percentile(
    universe: pd.DataFrame,
    *,
    metric: str,
    value: float | None,
    sector: str | None,
    higher_is_better: bool,
) -> float | None:
    if value is None or pd.isna(value):
        return None

    if sector and sector in universe["sector"].values:
        sector_slice = universe[universe["sector"] == sector]
        if len(sector_slice) >= MIN_SECTOR_SIZE and metric in sector_slice.columns:
            rank = percentile_rank(sector_slice[metric], value, higher_is_better=higher_is_better)
            if rank is not None:
                return rank

    if metric not in universe.columns:
        return None
    return percentile_rank(universe[metric], value, higher_is_better=higher_is_better)


def sector_composite_score(universe: pd.DataFrame, row: dict[str, Any]) -> float | None:
    """Weighted blend of sector-relative percentile ranks (0–1)."""
    if universe.empty:
        return None

    prepared = compute_derived_columns(universe)
    sector = row.get("sector")

    scores: list[float] = []
    weights: list[float] = []
    for metric, higher_is_better in SECTOR_METRICS.items():
        rank = _sector_percentile(
            prepared,
            metric=metric,
            value=row.get(metric),
            sector=sector,
            higher_is_better=higher_is_better,
        )
        if rank is None:
            continue
        weight = SECTOR_WEIGHTS[metric]
        scores.append(rank * weight)
        weights.append(weight)

    if not weights:
        return None
    return sum(scores) / sum(weights)


def add_sector_scores(universe: pd.DataFrame) -> pd.DataFrame:
    """Add sector_composite_score column to universe DataFrame."""
    out = universe.copy()
    out["sector_composite_score"] = [
        sector_composite_score(out, row.to_dict()) for _, row in out.iterrows()
    ]
    return out
