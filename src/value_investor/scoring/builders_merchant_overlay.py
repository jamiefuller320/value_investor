"""Builders-merchant overlays — housing/RMI cyclicality and FCF-basis cash conversion."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from value_investor.scoring.fcf import load_filing_bodies_for_ticker
from value_investor.scoring.interim_quality_overlay import quality_family_passed

BUILDERS_MERCHANT_TICKERS = frozenset({"GFTU.L"})

BUILDERS_MERCHANT_NAME_FRAGMENTS = (
    "builders merchant",
    "builders' merchant",
    "building materials",
    "building merchant",
    "grafton group",
    "grafton plc",
    "selco",
)

HOUSING_RMI_KEYWORD_FRAGMENTS = (
    "repair, maintenance and improvement",
    "repair maintenance and improvement",
    "housing market",
    "residential construction",
    "new build",
    "new-build",
    "rmi",
    "merchanting",
    "merchant market",
)

_HOUSING_RMI_RES = tuple(
    re.compile(re.escape(fragment), re.IGNORECASE) for fragment in HOUSING_RMI_KEYWORD_FRAGMENTS
)


def is_builders_merchant(
    ticker: str | None,
    name: str | None,
    sector: str | None = None,
) -> bool:
    """True for UK/Irish builders-merchants where housing/RMI overlays apply."""
    if ticker and str(ticker).upper() in BUILDERS_MERCHANT_TICKERS:
        return True
    if not ticker or not str(ticker).strip().upper().endswith(".L"):
        return False
    name_l = (name or "").lower()
    if any(fragment in name_l for fragment in BUILDERS_MERCHANT_NAME_FRAGMENTS):
        return True
    sector_l = (sector or "").lower()
    return "industrial" in sector_l and "merchant" in name_l


def housing_rmi_cyclical_detected(text: str) -> bool:
    """True when filing prose cites housing/RMI cyclical demand."""
    if not text:
        return False
    return any(pattern.search(text) for pattern in _HOUSING_RMI_RES)


def housing_rmi_cyclical_for_ticker(
    ticker: str,
    *,
    output_dir: Path | None = None,
) -> bool:
    bodies = load_filing_bodies_for_ticker(ticker, output_dir=output_dir)
    return any(housing_rmi_cyclical_detected(body) for body in bodies)


def builders_merchant_cyclical_overlay_triggered(
    *,
    builders_merchant: bool,
    housing_rmi_detected: bool,
    passed_families: str | None,
) -> bool:
    if not builders_merchant or not housing_rmi_detected:
        return False
    return quality_family_passed(passed_families)


def builders_merchant_cash_conversion_overlay_triggered(
    *,
    builders_merchant: bool,
    passed_families: str | None,
    fcf_definition_divergence: bool,
    fcf_divergence_flagged: bool,
) -> bool:
    if not builders_merchant:
        return False
    if not quality_family_passed(passed_families):
        return False
    return fcf_definition_divergence or fcf_divergence_flagged


def enrich_signals_with_builders_merchant_detection(
    signals: pd.DataFrame,
    *,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    """Tag builders-merchants and housing/RMI cyclical exposure before downstream overlays."""
    if signals.empty:
        return signals

    out = signals.copy()
    merchant_flags: list[bool] = []
    housing_flags: list[bool] = []

    for _, row in out.iterrows():
        ticker = str(row["ticker"])
        merchant = bool(row.get("builders_merchant")) or is_builders_merchant(
            ticker,
            row.get("name"),
            row.get("sector"),
        )
        housing_raw = row.get("housing_rmi_cyclical_detected")
        if housing_raw is not None and not (
            isinstance(housing_raw, float) and pd.isna(housing_raw)
        ):
            housing_detected = bool(housing_raw)
        elif merchant:
            housing_detected = housing_rmi_cyclical_for_ticker(ticker, output_dir=output_dir)
        else:
            housing_detected = False

        merchant_flags.append(merchant)
        housing_flags.append(housing_detected)

    out["builders_merchant"] = merchant_flags
    out["housing_rmi_cyclical_detected"] = housing_flags
    if "cyclical_exposure_detected" in out.columns:
        out["cyclical_exposure_detected"] = [
            bool(existing) or housing
            for existing, housing in zip(
                out["cyclical_exposure_detected"].tolist(),
                housing_flags,
                strict=True,
            )
        ]
    else:
        out["cyclical_exposure_detected"] = housing_flags

    return out
