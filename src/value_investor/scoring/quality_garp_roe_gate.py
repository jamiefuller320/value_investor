"""Suppress quality/GARP passes when Buffett and Moat fail on the same ROE."""

from __future__ import annotations

import ast
from typing import Any

import pandas as pd

BUFFETT_MODEL_ID = "buffett_quality"
MOAT_MODEL_ID = "economic_moat"
QUALITY_GARP_MODEL_IDS = frozenset({"quality_value", "lynch_peg", "neff_pegy"})


def _parse_failed_criteria(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str) and value.strip():
        try:
            parsed = ast.literal_eval(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except (SyntaxError, ValueError):
            return [value]
    return []


def _append_failed_criterion(existing: Any, message: str) -> list[str]:
    failed = _parse_failed_criteria(existing)
    if message not in failed:
        failed.append(message)
    return failed


def quality_garp_roe_gate_triggered(
    model_results: pd.DataFrame,
    *,
    ticker: str,
) -> bool:
    """True when quality/GARP screens pass despite Buffett and Moat both failing."""
    if model_results.empty:
        return False

    ticker_rows = model_results[model_results["ticker"] == ticker]
    if ticker_rows.empty:
        return False

    buffett = ticker_rows[ticker_rows["model_id"] == BUFFETT_MODEL_ID]
    moat = ticker_rows[ticker_rows["model_id"] == MOAT_MODEL_ID]
    if buffett.empty or moat.empty:
        return False
    if bool(buffett.iloc[0]["passed"]) or bool(moat.iloc[0]["passed"]):
        return False

    gated = ticker_rows[
        ticker_rows["model_id"].isin(QUALITY_GARP_MODEL_IDS) & (ticker_rows["passed"] == True)  # noqa: E712
    ]
    return not gated.empty


def suppress_quality_garp_inconsistent_passes(model_results: pd.DataFrame) -> pd.DataFrame:
    """Flip quality/GARP passes when Buffett and Moat both fail without documented exception."""
    if model_results.empty:
        return model_results

    out = model_results.copy()
    for ticker in out["ticker"].dropna().unique():
        if not quality_garp_roe_gate_triggered(out, ticker=str(ticker)):
            continue

        mask = (
            (out["ticker"] == ticker)
            & (out["model_id"].isin(QUALITY_GARP_MODEL_IDS))
            & (out["passed"] == True)  # noqa: E712
        )
        if not mask.any():
            continue
        out.loc[mask, "passed"] = False
        for index in out.index[mask]:
            out.at[index, "failed_criteria"] = _append_failed_criterion(
                out.at[index, "failed_criteria"],
                "Quality/GARP suppressed: Buffett and Moat fail on same ROE",
            )
    return out
