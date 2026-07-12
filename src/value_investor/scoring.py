"""Run all value models and aggregate scores."""

from __future__ import annotations

from typing import Any

import pandas as pd

from value_investor.models import ALL_MODELS
from value_investor.model_families import summarize_by_family
from value_investor.model_weights import apply_weights_to_results
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


def _weighted_mean_score(group: pd.DataFrame) -> float:
    weight_sum = group["model_weight"].sum()
    if weight_sum <= 0:
        return float(group["score"].mean())
    return float(group["weighted_score"].sum() / weight_sum)


def _weighted_pass_rate(group: pd.DataFrame) -> float:
    weight_sum = group["model_weight"].sum()
    if weight_sum <= 0:
        return float(group["passed"].mean())
    return float(group["weighted_pass"].sum() / weight_sum)


def summarize_by_ticker(
    model_results: pd.DataFrame,
    *,
    weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Pivot model results into per-ticker summary with pass counts and scores."""
    if model_results.empty:
        return pd.DataFrame()

    weighted = apply_weights_to_results(model_results, weights or {})
    weighted["weighted_score"] = weighted["score"] * weighted["model_weight"]
    weighted["weighted_pass"] = weighted["passed"].astype(float) * weighted["model_weight"]

    summary = (
        weighted.groupby("ticker")
        .apply(
            lambda group: pd.Series(
                {
                    "models_passed": int(group["passed"].sum()),
                    "model_count": int(len(group)),
                    "mean_model_score": float(group["score"].mean()),
                    "weighted_model_score": _weighted_mean_score(group),
                    "weighted_pass_score": _weighted_pass_rate(group),
                    "min_model_score": float(group["score"].min()),
                    "max_model_score": float(group["score"].max()),
                }
            ),
            include_groups=False,
        )
        .reset_index()
    )
    summary["pass_rate"] = summary["models_passed"] / summary["model_count"]

    if weights:
        weight_series = weighted.groupby("ticker")["model_weight"].sum()
        summary["weight_sum"] = summary["ticker"].map(weight_series)

    family_summary = summarize_by_family(model_results)
    if not family_summary.empty:
        summary = summary.merge(family_summary, on="ticker", how="left")

    return summary


def format_model_weights_text(weights: dict[str, float], *, top_n: int = 5) -> str:
    if not weights:
        return "Model weights: equal (no history yet)."

    ranked = sorted(weights.items(), key=lambda item: item[1], reverse=True)
    leaders = ", ".join(f"{model_id} ({weight:.2f})" for model_id, weight in ranked[:top_n])
    laggards = ", ".join(f"{model_id} ({weight:.2f})" for model_id, weight in ranked[-top_n:])
    return f"Top weighted models: {leaders}. Lowest: {laggards}."
