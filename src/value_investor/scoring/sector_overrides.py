"""Sector classification overrides for peer-relative scoring."""

from __future__ import annotations

import pandas as pd

# Yahoo often labels palm-oil and plantation operators as Consumer Defensive (FMCG).
# Remap them to a commodity/agriculture bucket so sector-relative scores are not
# inflated against stable consumer peers.
AGRICULTURE_COMMODITIES_SECTOR = "Agriculture/Commodities"

TICKER_SECTOR_OVERRIDES: dict[str, str] = {
    "AEP.L": AGRICULTURE_COMMODITIES_SECTOR,
}

MISCLASSIFIED_DEFENSIVE_SECTORS = frozenset({"Consumer Defensive"})

PLANTATION_NAME_FRAGMENTS = (
    "plantation",
    "plantations",
    "palm oil",
    "palm-oil",
)


def _scoring_field_text(value: object | None) -> str:
    """Coerce pandas/NaN-safe text from screen rows (sector/name may be float)."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return ""
    return text


def resolve_scoring_sector(
    ticker: str | None,
    sector: str | None,
    name: str | None = None,
) -> str | None:
    """Return the sector label used for peer-relative scoring."""
    if ticker:
        override = TICKER_SECTOR_OVERRIDES.get(str(ticker).upper())
        if override:
            return override

    sector_norm = _scoring_field_text(sector)
    if sector_norm in MISCLASSIFIED_DEFENSIVE_SECTORS:
        name_l = _scoring_field_text(name).lower()
        if any(fragment in name_l for fragment in PLANTATION_NAME_FRAGMENTS):
            return AGRICULTURE_COMMODITIES_SECTOR

    return sector_norm or None


def apply_sector_overrides(universe: pd.DataFrame) -> pd.DataFrame:
    """Rewrite ``sector`` for issuers that need a scoring peer group override."""
    if universe.empty or "ticker" not in universe.columns:
        return universe

    out = universe.copy()
    out["sector"] = [
        resolve_scoring_sector(row.get("ticker"), row.get("sector"), row.get("name"))
        for row in out.to_dict(orient="records")
    ]
    return out
