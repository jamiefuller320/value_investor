"""Group screening models into independent families for aggregation."""

from __future__ import annotations

from typing import Any

import pandas as pd

# Families are designed to reduce double-counting correlated value screens.
MODEL_FAMILIES: dict[str, list[str]] = {
    "cheapness": [
        "graham_defensive",
        "graham_enterprising",
        "graham_net_net",
        "schloss",
        "deep_value",
        "earnings_yield",
        "fcf_yield",
        "low_pe_high_yield",
        "magic_formula",
        "acquirers_multiple",
        "dreman_contrarian",
        "composite_value",
    ],
    "quality": [
        "quality_value",
        "buffett_quality",
        "economic_moat",
        "piotroski_f",
    ],
    "dividend": [
        "high_dividend",
        "dividend_growth",
    ],
    "garp": [
        "lynch_peg",
        "neff_pegy",
    ],
}

MODEL_TO_FAMILY: dict[str, str] = {
    model_id: family for family, model_ids in MODEL_FAMILIES.items() for model_id in model_ids
}


def summarize_by_family(model_results: pd.DataFrame) -> pd.DataFrame:
    """Per-ticker family pass counts and mean scores."""
    if model_results.empty:
        return pd.DataFrame()

    tagged = model_results.copy()
    tagged["family"] = tagged["model_id"].map(MODEL_TO_FAMILY)
    tagged = tagged.dropna(subset=["family"])

    family_summary = (
        tagged.groupby(["ticker", "family"])
        .agg(
            family_models_passed=("passed", "sum"),
            family_model_count=("passed", "count"),
            family_mean_score=("score", "mean"),
        )
        .reset_index()
    )
    family_summary["family_passed"] = family_summary["family_models_passed"] > 0

    pivot_passed = family_summary.pivot(index="ticker", columns="family", values="family_passed").fillna(False)
    pivot_scores = family_summary.pivot(index="ticker", columns="family", values="family_mean_score")

    rows: list[dict[str, Any]] = []
    for ticker in pivot_passed.index:
        passed_families = [
            family
            for family in MODEL_FAMILIES
            if family in pivot_passed.columns and bool(pivot_passed.loc[ticker, family])
        ]
        family_scores = {
            family: float(pivot_scores.loc[ticker, family])
            for family in MODEL_FAMILIES
            if family in pivot_scores.columns and pd.notna(pivot_scores.loc[ticker, family])
        }
        rows.append(
            {
                "ticker": ticker,
                "families_passed": len(passed_families),
                "family_count": len(MODEL_FAMILIES),
                "passed_families": ",".join(passed_families),
                "family_mean_score": sum(family_scores.values()) / len(family_scores) if family_scores else 0.0,
            }
        )

    return pd.DataFrame(rows)


def format_family_summary(passed_families: str | None) -> str:
    if not passed_families:
        return "no model families"
    labels = {
        "cheapness": "cheapness",
        "quality": "quality",
        "dividend": "dividend",
        "garp": "GARP",
    }
    parts = [labels.get(f, f) for f in passed_families.split(",") if f]
    return ", ".join(parts)
