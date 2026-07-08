"""Shared ranking helpers for universe-relative models."""

from __future__ import annotations

import pandas as pd


def percentile_rank(series: pd.Series, value: float, *, higher_is_better: bool) -> float | None:
    """Return 0–1 percentile rank for value within series."""
    valid = series.dropna()
    if valid.empty or value is None or pd.isna(value):
        return None
    rank = (valid < value).sum() / len(valid)
    return rank if higher_is_better else 1.0 - rank


def compute_derived_columns(universe: pd.DataFrame) -> pd.DataFrame:
    """Add derived ratios used by multiple models."""
    df = universe.copy()

    if "market_cap" in df.columns and "free_cashflow" in df.columns:
        df["fcf_yield"] = df["free_cashflow"] / df["market_cap"].replace(0, pd.NA)

    if "enterprise_value" in df.columns and "ebitda" in df.columns:
        df["ev_ebitda"] = df["enterprise_value"] / df["ebitda"].replace(0, pd.NA)

    if "enterprise_value" in df.columns and "ebit" in df.columns:
        df["ev_ebit"] = df["enterprise_value"] / df["ebit"].replace(0, pd.NA)
        df["earnings_yield_ebit"] = df["ebit"] / df["enterprise_value"].replace(0, pd.NA)

    if "trailing_pe" in df.columns:
        df["earnings_yield_pe"] = 1.0 / df["trailing_pe"].replace(0, pd.NA)

    if "market_cap" in df.columns and "ncav" in df.columns:
        df["ncav_to_market"] = df["ncav"] / df["market_cap"].replace(0, pd.NA)

    if "total_assets" in df.columns and "ebit" in df.columns:
        invested_capital = df["total_assets"] - df.get("total_current_liabilities", 0)
        df["roic_proxy"] = df["ebit"] / invested_capital.replace(0, pd.NA)

    if "total_revenue" in df.columns and "total_assets" in df.columns:
        df["asset_turnover"] = df["total_revenue"] / df["total_assets"].replace(0, pd.NA)

    return df
