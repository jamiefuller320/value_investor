"""Healthcare price-erosion overlay — cap signals when filings cite pricing pressure."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from value_investor.scoring.fcf import load_filing_bodies_for_ticker
from value_investor.scoring.healthcare_overlay import is_healthcare_sector

YIELD_MODEL_IDS = (
    "high_dividend",
    "fcf_yield",
    "earnings_yield",
    "low_pe_high_yield",
)

PRICE_EROSION_FRAGMENTS = (
    "price erosion",
    "competition on higher margin products",
    "pricing pressure",
)

_PRICE_EROSION_RES = tuple(
    re.compile(re.escape(fragment), re.IGNORECASE) for fragment in PRICE_EROSION_FRAGMENTS
)

_SIGNAL_RANK = {
    "strong_buy": 4,
    "buy": 3,
    "hold": 2,
    "avoid": 1,
    "insufficient_data": 0,
}


def price_erosion_language_detected(text: str) -> bool:
    """True when filing prose cites generic pricing or margin competition headwinds."""
    if not text:
        return False
    return any(pattern.search(text) for pattern in _PRICE_EROSION_RES)


def price_erosion_for_ticker(
    ticker: str,
    *,
    output_dir: Path | None = None,
) -> bool:
    """Scan cached filing bodies for healthcare pricing-pressure language."""
    bodies = load_filing_bodies_for_ticker(ticker, output_dir=output_dir)
    return any(price_erosion_language_detected(body) for body in bodies)


def quality_or_income_family_passed(passed_families: str | None) -> bool:
    if not passed_families:
        return False
    families = {part.strip() for part in str(passed_families).split(",") if part.strip()}
    return bool(families.intersection({"quality", "dividend"}))


def all_yield_cheapness_models_failed(ticker_models: pd.DataFrame) -> bool:
    """True when every yield-based cheapness screen is present and fails."""
    if ticker_models.empty or "model_id" not in ticker_models.columns:
        return False
    rows = ticker_models[ticker_models["model_id"].isin(YIELD_MODEL_IDS)]
    if rows.empty or len(rows) < len(YIELD_MODEL_IDS):
        return False
    return not bool(rows["passed"].any())


def healthcare_price_erosion_overlay_triggered(
    *,
    sector: str | None,
    passed_families: str | None,
    ticker_models: pd.DataFrame,
    price_erosion_detected: bool,
) -> bool:
    if not is_healthcare_sector(sector):
        return False
    if not quality_or_income_family_passed(passed_families):
        return False
    if not all_yield_cheapness_models_failed(ticker_models):
        return False
    return price_erosion_detected


def cap_signal_for_healthcare_price_erosion_overlay(signal: str) -> str:
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


def apply_healthcare_price_erosion_overlay_to_signal(
    signal: str,
    *,
    sector: str | None,
    passed_families: str | None,
    ticker_models: pd.DataFrame,
    price_erosion_detected: bool,
    adjusted_signal: str | None = None,
) -> tuple[bool, str]:
    """Return overlay flag and conservative adjusted signal."""
    base_adjusted = adjusted_signal or signal
    if not healthcare_price_erosion_overlay_triggered(
        sector=sector,
        passed_families=passed_families,
        ticker_models=ticker_models,
        price_erosion_detected=price_erosion_detected,
    ):
        return False, base_adjusted
    capped = cap_signal_for_healthcare_price_erosion_overlay(signal)
    return True, _more_conservative_signal(base_adjusted, capped)


def enrich_signals_with_healthcare_price_erosion_overlay(
    signals: pd.DataFrame,
    model_results: pd.DataFrame,
    *,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    """Add healthcare price-erosion overlay flag and cap ``adjusted_signal`` when triggered."""
    out = signals.copy()
    flags: list[bool] = []
    detected_flags: list[bool] = []
    adjusted: list[str] = []

    for _, row in out.iterrows():
        ticker = str(row["ticker"])
        ticker_models = model_results[model_results["ticker"] == ticker]
        existing = row.get("adjusted_signal")
        existing_adjusted = (
            str(existing)
            if existing is not None and not (isinstance(existing, float) and pd.isna(existing))
            else None
        )

        erosion_flag = row.get("healthcare_price_erosion_detected")
        if erosion_flag is not None and not (
            isinstance(erosion_flag, float) and pd.isna(erosion_flag)
        ):
            erosion_detected = bool(erosion_flag)
        else:
            erosion_detected = price_erosion_for_ticker(ticker, output_dir=output_dir)

        triggered, new_adjusted = apply_healthcare_price_erosion_overlay_to_signal(
            str(row.get("signal") or "hold"),
            sector=row.get("sector"),
            passed_families=row.get("passed_families"),
            ticker_models=ticker_models,
            price_erosion_detected=erosion_detected,
            adjusted_signal=existing_adjusted,
        )
        flags.append(triggered)
        detected_flags.append(erosion_detected)
        adjusted.append(new_adjusted)

    out["healthcare_price_erosion_detected"] = detected_flags
    out["healthcare_price_erosion_overlay"] = flags
    out["adjusted_signal"] = adjusted
    return out
