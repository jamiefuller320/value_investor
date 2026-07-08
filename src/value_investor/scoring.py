"""Run all value models and aggregate scores."""

from __future__ import annotations

from typing import Any

import pandas as pd

from value_investor.models import ALL_MODELS
from value_investor.models.base import ValueModel
from value_investor.models.fitted import UniverseFittedModel


def evaluate_universe(universe: pd.DataFrame, models: list[ValueModel] | None = None) -> pd.DataFrame:
    """
    Evaluate every company against all models.

    Returns a long-form DataFrame: one row per (ticker, model).
    """
    models = list(models or ALL_MODELS)

    for model in models:
        if isinstance(model, UniverseFittedModel):
            model.fit(universe)

    rows: list[dict[str, Any]] = []
    for _, company in universe.iterrows():
        row = company.to_dict()
        for model in models:
            result = model.evaluate(row)
            rows.append({"ticker": row["ticker"], **result.to_dict()})

    return pd.DataFrame(rows)


def summarize_by_ticker(model_results: pd.DataFrame) -> pd.DataFrame:
    """Pivot model results into per-ticker summary with pass counts and mean score."""
    if model_results.empty:
        return pd.DataFrame()

    summary = (
        model_results.groupby("ticker")
        .agg(
            models_passed=("passed", "sum"),
            model_count=("passed", "count"),
            mean_model_score=("score", "mean"),
            min_model_score=("score", "min"),
            max_model_score=("score", "max"),
        )
        .reset_index()
    )
    summary["pass_rate"] = summary["models_passed"] / summary["model_count"]
    return summary
