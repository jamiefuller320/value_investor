"""Healthcare sector cash-quality overlay — cap adjusted signals on weak FCF + Piotroski."""

from __future__ import annotations

import ast
from typing import Any

import pandas as pd

from value_investor.models.piotroski import piotroski_snapshot_from_result

_SIGNAL_RANK = {
    "strong_buy": 4,
    "buy": 3,
    "hold": 2,
    "avoid": 1,
    "insufficient_data": 0,
}

HEALTHCARE_SECTOR_FRAGMENTS = ("healthcare", "health care")
PIOTROSKI_WEAK_THRESHOLD = 4


def is_healthcare_sector(sector: str | None) -> bool:
    if not sector:
        return False
    norm = str(sector).strip().lower()
    return any(fragment in norm for fragment in HEALTHCARE_SECTOR_FRAGMENTS)


def _parse_list_field(value: Any) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        text = value.strip()
        if not text or text == "[]":
            return []
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, list):
                return [str(v) for v in parsed]
        except (SyntaxError, ValueError):
            return [text]
    return []


def piotroski_score_from_model_row(model_row: pd.Series) -> int | None:
    details = model_row.get("details")
    if isinstance(details, str) and details.strip():
        try:
            parsed = ast.literal_eval(details)
            details = parsed if isinstance(parsed, dict) else None
        except (SyntaxError, ValueError):
            details = None
    elif not isinstance(details, dict):
        details = None

    snapshot = piotroski_snapshot_from_result(
        passed=bool(model_row.get("passed")),
        score=float(model_row.get("score") or 0),
        reasons=_parse_list_field(model_row.get("reasons")),
        failed_criteria=_parse_list_field(model_row.get("failed_criteria")),
        details=details,
    )
    score = snapshot.get("score")
    return int(score) if score is not None else None


def piotroski_score_for_ticker(ticker_models: pd.DataFrame) -> int | None:
    if ticker_models.empty or "model_id" not in ticker_models.columns:
        return None
    piotroski = ticker_models[ticker_models["model_id"] == "piotroski_f"]
    if piotroski.empty:
        return None
    return piotroski_score_from_model_row(piotroski.iloc[0])


def healthcare_overlay_triggered(
    *,
    sector: str | None,
    free_cashflow: float | None,
    piotroski_f_score: int | None,
) -> bool:
    if not is_healthcare_sector(sector):
        return False
    if free_cashflow is None or (isinstance(free_cashflow, float) and pd.isna(free_cashflow)):
        return False
    if float(free_cashflow) >= 0:
        return False
    if piotroski_f_score is None:
        return False
    return int(piotroski_f_score) <= PIOTROSKI_WEAK_THRESHOLD


def cap_signal_for_healthcare_overlay(signal: str) -> str:
    """Cap at research-equivalent caution: strong_buy -> buy, buy -> hold."""
    if signal == "strong_buy":
        return "buy"
    if signal == "buy":
        return "hold"
    return signal


def _more_conservative_signal(current: str, candidate: str) -> str:
    current_rank = _SIGNAL_RANK.get(current, 0)
    candidate_rank = _SIGNAL_RANK.get(candidate, 0)
    return current if current_rank <= candidate_rank else candidate


def apply_healthcare_overlay_to_signal(
    signal: str,
    *,
    sector: str | None,
    free_cashflow: float | None,
    piotroski_f_score: int | None,
    adjusted_signal: str | None = None,
) -> tuple[bool, str]:
    """Return overlay flag and conservative adjusted signal."""
    base_adjusted = adjusted_signal or signal
    if not healthcare_overlay_triggered(
        sector=sector,
        free_cashflow=free_cashflow,
        piotroski_f_score=piotroski_f_score,
    ):
        return False, base_adjusted
    capped = cap_signal_for_healthcare_overlay(signal)
    return True, _more_conservative_signal(base_adjusted, capped)


def enrich_signals_with_healthcare_overlay(
    signals: pd.DataFrame,
    model_results: pd.DataFrame,
) -> pd.DataFrame:
    """Add healthcare overlay flag and cap ``adjusted_signal`` when triggered."""
    out = signals.copy()
    flags: list[bool] = []
    adjusted: list[str] = []

    for _, row in out.iterrows():
        ticker = str(row["ticker"])
        ticker_models = model_results[model_results["ticker"] == ticker]
        fcf = row.get("free_cashflow")
        free_cashflow = (
            float(fcf) if fcf is not None and not (isinstance(fcf, float) and pd.isna(fcf)) else None
        )
        existing = row.get("adjusted_signal")
        existing_adjusted = (
            str(existing)
            if existing is not None and not (isinstance(existing, float) and pd.isna(existing))
            else None
        )
        triggered, new_adjusted = apply_healthcare_overlay_to_signal(
            str(row.get("signal") or "hold"),
            sector=row.get("sector"),
            free_cashflow=free_cashflow,
            piotroski_f_score=piotroski_score_for_ticker(ticker_models),
            adjusted_signal=existing_adjusted,
        )
        flags.append(triggered)
        adjusted.append(new_adjusted)

    out["healthcare_overlay"] = flags
    out["adjusted_signal"] = adjusted
    return out
