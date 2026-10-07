"""Investor net yield for non-UK library screens (L563).

Gross dividend yield is what the models score. This module adds two observe
columns for a UK individual: ISA (withholding only; foreign tax is not
reclaimed) and taxable (basic-rate dividend tax, with foreign withholding
credited so the drag is the larger of the two). It does not change FTSE
signals or the composite.

Rates are ranking assumptions, not a tax computation. Unknown countries stay
blank rather than inventing a rate.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.data_library import MARKET_REGISTRY

# UK treaty portfolio dividend withholding used for ranking.
WITHHOLDING_BY_COUNTRY: dict[str, float] = {
    "GB": 0.0,
    "US": 0.15,
    "AU": 0.15,
    "CA": 0.15,
    "JP": 0.10,
    "FR": 0.15,
    "DE": 0.15,
    "NL": 0.15,
    "CH": 0.15,
}
# Basic-rate dividend ordinary rate. Ranking assumption for the taxable column.
UK_DIVIDEND_ORDINARY_RATE = 0.0875

MARKET_COUNTRY: dict[str, str] = {
    "sp500": "US",
    "nasdaq100": "US",
    "asx200": "AU",
    "tsx60": "CA",
    "dax": "DE",
    "cac40": "FR",
}
SUFFIX_COUNTRY: dict[str, str] = {
    ".L": "GB",
    ".AX": "AU",
    ".TO": "CA",
    ".V": "CA",
    ".T": "JP",
    ".PA": "FR",
    ".DE": "DE",
    ".AS": "NL",
    ".SW": "CH",
}

ISA = "isa"
TAXABLE = "taxable"
FINDING_TITLE = "Non-UK library screen has no investor net yield"
NET_YIELD_COLUMN = "investor_net_yield_isa"


def is_uk_listing_market(market_id: str) -> bool:
    spec = MARKET_REGISTRY.get(market_id)
    return bool(spec and spec.exchange == "LSE")


def country_for_ticker(ticker: str, market_id: str) -> str | None:
    symbol = str(ticker or "")
    for suffix, country in SUFFIX_COUNTRY.items():
        if symbol.upper().endswith(suffix):
            return country
    return MARKET_COUNTRY.get(market_id)


def net_yield(gross: float | None, country: str | None, wrapper: str) -> float | None:
    """Net-of-drag yield. None when the gross yield or the country rate is unknown."""
    if gross is None or country is None:
        return None
    try:
        gross_value = float(gross)
    except (TypeError, ValueError):
        return None
    if gross_value < 0 or gross_value != gross_value:  # NaN
        return None
    withholding = WITHHOLDING_BY_COUNTRY.get(country)
    if withholding is None:
        return None
    if wrapper == ISA:
        drag = withholding
    elif wrapper == TAXABLE:
        drag = (
            UK_DIVIDEND_ORDINARY_RATE
            if country == "GB"
            else max(withholding, UK_DIVIDEND_ORDINARY_RATE)
        )
    else:
        raise ValueError(f"Unknown wrapper: {wrapper}")
    return round(gross_value * (1.0 - drag), 6)


def attach_investor_yield(signals: pd.DataFrame, market_id: str) -> pd.DataFrame:
    """Add observe columns. UK listing markets are returned unchanged."""
    if signals.empty or is_uk_listing_market(market_id):
        return signals
    out = signals.copy()
    countries = [country_for_ticker(str(ticker), market_id) for ticker in out.get("ticker", [])]
    gross = out["dividend_yield"] if "dividend_yield" in out.columns else [None] * len(out)
    out["investor_yield_country"] = countries
    out[NET_YIELD_COLUMN] = [
        net_yield(value, country, ISA) for value, country in zip(gross, countries, strict=True)
    ]
    out["investor_net_yield_taxable"] = [
        net_yield(value, country, TAXABLE) for value, country in zip(gross, countries, strict=True)
    ]
    return out


def markets_missing_investor_yield(library_root: Path) -> list[str]:
    """Non-UK screens whose latest signals file has no net-yield column."""
    from value_investor.library_screen import screen_dir_for

    missing: list[str] = []
    root = Path(library_root)
    for market_id in sorted(MARKET_REGISTRY):
        if is_uk_listing_market(market_id):
            continue
        path = screen_dir_for(root, market_id) / "latest_signals.csv"
        if not path.exists():
            continue
        try:
            header = path.open(encoding="utf-8").readline()
        except OSError:
            continue
        if NET_YIELD_COLUMN not in header:
            missing.append(market_id)
    return missing


def finding_for_library(library_root: Path) -> dict[str, Any] | None:
    missing = markets_missing_investor_yield(library_root)
    if not missing:
        return None
    shown = ", ".join(missing[:8])
    extra = "" if len(missing) <= 8 else f" (+{len(missing) - 8} more)"
    return {
        "severity": "warn",
        "category": "research",
        "title": FINDING_TITLE,
        "summary": (
            "These non-UK library screens still have no investor_net_yield column, so a "
            "later total-return judgement would be looking at gross yield: "
            f"{shown}{extra}. The next library screen writes the column. "
            "Live FTSE signals are unchanged. See docs/ops/investor-yield.md."
        ),
        "auto_fixable": False,
    }
