"""Healthcare reimbursement / sub-sector overlay for orthopaedics and wound bioactives."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from value_investor.scoring.fcf import load_filing_bodies_for_ticker
from value_investor.scoring.healthcare_overlay import (
    is_healthcare_sector,
    orthopaedic_or_wound_bioactive_profile,
)
from value_investor.scoring.healthcare_price_erosion_overlay import (
    _more_conservative_signal,
    cap_signal_for_healthcare_price_erosion_overlay,
)

REIMBURSEMENT_FRAGMENTS = (
    "reimbursement",
    "payer pressure",
    "reimbursement pressure",
    "medicare",
    "cms ",
)

_REIMBURSEMENT_RES = tuple(
    re.compile(re.escape(fragment), re.IGNORECASE) for fragment in REIMBURSEMENT_FRAGMENTS
)


def reimbursement_language_detected(text: str) -> bool:
    if not text:
        return False
    return any(pattern.search(text) for pattern in _REIMBURSEMENT_RES)


def reimbursement_risk_for_ticker(
    ticker: str,
    *,
    output_dir: Path | None = None,
) -> bool:
    bodies = load_filing_bodies_for_ticker(ticker, output_dir=output_dir)
    return any(reimbursement_language_detected(body) for body in bodies)


def healthcare_reimbursement_overlay_triggered(
    *,
    sector: str | None,
    name: str | None,
    reimbursement_detected: bool,
) -> bool:
    if orthopaedic_or_wound_bioactive_profile(sector, name):
        return True
    if not is_healthcare_sector(sector):
        return False
    return reimbursement_detected


def apply_healthcare_reimbursement_overlay_to_signal(
    signal: str,
    *,
    sector: str | None,
    name: str | None,
    reimbursement_detected: bool,
    adjusted_signal: str | None = None,
) -> tuple[bool, str]:
    base_adjusted = adjusted_signal or signal
    if not healthcare_reimbursement_overlay_triggered(
        sector=sector,
        name=name,
        reimbursement_detected=reimbursement_detected,
    ):
        return False, base_adjusted
    capped = cap_signal_for_healthcare_price_erosion_overlay(signal)
    return True, _more_conservative_signal(base_adjusted, capped)


def enrich_signals_with_healthcare_reimbursement_overlay(
    signals: pd.DataFrame,
    *,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    """Cap buy-tier signals for orthopaedics / wound-bioactives and reimbursement prose."""
    out = signals.copy()
    flags: list[bool] = []
    detected_flags: list[bool] = []
    adjusted: list[str] = []

    for _, row in out.iterrows():
        ticker = str(row["ticker"])
        existing = row.get("adjusted_signal")
        existing_adjusted = (
            str(existing)
            if existing is not None and not (isinstance(existing, float) and pd.isna(existing))
            else None
        )

        explicit = row.get("healthcare_reimbursement_detected")
        if explicit is not None and not (isinstance(explicit, float) and pd.isna(explicit)):
            reimbursement_detected = bool(explicit)
        else:
            reimbursement_detected = reimbursement_risk_for_ticker(ticker, output_dir=output_dir)

        triggered, new_adjusted = apply_healthcare_reimbursement_overlay_to_signal(
            str(row.get("signal") or "hold"),
            sector=row.get("sector"),
            name=row.get("name"),
            reimbursement_detected=reimbursement_detected,
            adjusted_signal=existing_adjusted,
        )
        flags.append(triggered)
        detected_flags.append(reimbursement_detected)
        adjusted.append(new_adjusted)

    out["healthcare_reimbursement_detected"] = detected_flags
    out["healthcare_reimbursement_overlay"] = flags
    out["adjusted_signal"] = adjusted
    return out
