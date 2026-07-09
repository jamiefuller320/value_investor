"""Data completeness scoring for screening inputs."""

from __future__ import annotations

from typing import Any

import pandas as pd

# Metrics that materially affect model coverage and signal reliability.
KEY_SCREENING_METRICS = [
    "market_cap",
    "trailing_pe",
    "price_to_book",
    "dividend_yield",
    "current_ratio",
    "debt_to_equity",
    "return_on_equity",
    "return_on_assets",
    "profit_margins",
    "free_cashflow",
    "enterprise_value",
    "ebitda",
    "ebit",
    "total_revenue",
    "total_assets",
    "net_income",
    "operating_cashflow",
    "book_value",
    "shares_outstanding",
    "total_current_assets",
]

MIN_QUALITY_FOR_ANALYSIS = 0.5
MIN_QUALITY_FOR_STRONG_BUY = 0.65
MIN_QUALITY_FOR_BUY = 0.5


def _metric_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and pd.isna(value):
        return False
    if isinstance(value, list) and not value:
        return False
    return True


def score_data_quality(row: dict[str, Any]) -> tuple[float, int, int]:
    """
    Return (score 0–1, metrics_present, metrics_total) for a company row.
    Penalises fetch errors and missing fundamentals.
    """
    present = sum(1 for key in KEY_SCREENING_METRICS if _metric_present(row.get(key)))
    total = len(KEY_SCREENING_METRICS)
    score = present / total if total else 0.0

    errors = row.get("errors")
    if errors:
        if isinstance(errors, str) and errors not in ("[]", ""):
            score *= 0.75
        elif isinstance(errors, list) and errors:
            score *= 0.75

    return round(max(0.0, min(1.0, score)), 4), present, total


def add_data_quality_scores(universe: pd.DataFrame) -> pd.DataFrame:
    """Add data_quality_score, metrics_present, metrics_total columns."""
    out = universe.copy()
    scores: list[float] = []
    present_counts: list[int] = []
    totals: list[int] = []

    for _, row in out.iterrows():
        score, present, total = score_data_quality(row.to_dict())
        scores.append(score)
        present_counts.append(present)
        totals.append(total)

    out["data_quality_score"] = scores
    out["metrics_present"] = present_counts
    out["metrics_total"] = totals
    return out


def quality_label(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.6:
        return "adequate"
    if score >= 0.4:
        return "partial"
    return "low"
