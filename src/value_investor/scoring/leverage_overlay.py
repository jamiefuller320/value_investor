"""Lease-adjusted net debt override when Yahoo D/E exceeds 100% but filing net debt is modest."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from value_investor.scoring.fcf import (
    _iter_filing_bodies,
    load_cached_financials,
)

YAHOO_DE_HIGH_THRESHOLD = 100.0
FILING_ADJUSTED_NET_DEBT_POLICY_THRESHOLD_GBP = 200_000_000.0
EFFECTIVE_DE_FALLBACK = 50.0

_EQUITY_LABELS = (
    "Stockholders Equity",
    "Total Stockholder Equity",
    "Total Equity Gross Minority Interest",
)

_ADJUSTED_NET_DEBT_RES = (
    re.compile(
        r"Adjusted net debt(?:\/\(cash\))?(?:\s*\/\s*\(cash\))?"
        r"(?:\s+at period end)?(?:\s+of)?\s+[£$€]?\s*\(?([\d,.]+)\)?\s*m\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"year-end adjusted net debt(?:\/\(cash\))?(?:\s+of)?\s+[£$€]?\s*\(?([\d,.]+)\)?\s*m\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"Adjusted net debt(?:\/\(cash\))?\s+[£$€]?\s*\(?([\d,.]+)\)?\s*m\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"Adjusted net debt(?:\/\(cash\))?\s+([\d,.]+)\b",
        re.IGNORECASE,
    ),
)

_ADJUSTED_NET_CASH_RES = (
    re.compile(
        r"Adjusted net cash(?:\/\(cash\))?(?:\s+of)?\s+[£$€]?\s*([\d,.]+)\s*m\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"year-end adjusted net cash(?:\/\(cash\))?(?:\s+of)?\s+[£$€]?\s*([\d,.]+)\s*m\b",
        re.IGNORECASE,
    ),
)

_OCR_ADJUSTED_NET_DEBT_TABLE_RE = re.compile(
    r"Adjusted net debt\?\s+([\d,.]+)\s+[\d,.]+",
    re.IGNORECASE,
)


def _parse_amount_millions(raw: str) -> float | None:
    try:
        amount = float(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return None
    if amount < 0:
        return None
    return amount * 1_000_000.0


def _parse_ocr_table_millions(raw: str) -> float | None:
    """Parse OCR table values where the decimal separator is dropped (1377 -> £137.7m)."""
    try:
        amount = float(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    if amount >= 100:
        return (amount / 10.0) * 1_000_000.0
    return amount * 1_000_000.0


def parse_adjusted_net_debt_gbp(text: str) -> float | None:
    """Parse filing adjusted net debt (positive) or net cash (negative) in GBP."""
    if not text:
        return None

    for pattern in _ADJUSTED_NET_CASH_RES:
        match = pattern.search(text)
        if match:
            amount = _parse_amount_millions(match.group(1))
            if amount is not None:
                return -amount

    for pattern in _ADJUSTED_NET_DEBT_RES:
        match = pattern.search(text)
        if not match:
            continue
        amount = _parse_amount_millions(match.group(1))
        if amount is not None:
            return amount

    ocr_match = _OCR_ADJUSTED_NET_DEBT_TABLE_RE.search(text)
    if ocr_match:
        amount = _parse_ocr_table_millions(ocr_match.group(1))
        if amount is not None:
            return amount
    return None


def extract_stockholders_equity(financials: dict[str, Any]) -> float | None:
    """Latest reported stockholders' equity from cached annual financials."""
    balance_sheet = financials.get("balance_sheet") or {}
    if not balance_sheet:
        return None
    for year in sorted((str(y) for y in balance_sheet.keys()), reverse=True):
        row = balance_sheet.get(year) or {}
        for label in _EQUITY_LABELS:
            value = row.get(label)
            if value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if pd.notna(number) and number > 0:
                return number
    return None


def extract_adjusted_net_debt_for_ticker(
    ticker: str,
    *,
    output_dir: Any = None,
) -> float | None:
    """Return filing adjusted net debt (GBP) from cached annual then interim bodies."""
    for periods in (("annual",), ("interim",)):
        for body in _iter_filing_bodies(ticker, output_dir=output_dir, periods=periods):
            parsed = parse_adjusted_net_debt_gbp(body)
            if parsed is not None:
                return parsed
    return None


def leverage_override_triggered(
    *,
    yahoo_de: float | None,
    filing_adjusted_net_debt_gbp: float | None,
) -> bool:
    """True when Yahoo D/E is high but filing adjusted net debt is below policy."""
    if yahoo_de is None or filing_adjusted_net_debt_gbp is None:
        return False
    if float(yahoo_de) <= YAHOO_DE_HIGH_THRESHOLD:
        return False
    return float(filing_adjusted_net_debt_gbp) < FILING_ADJUSTED_NET_DEBT_POLICY_THRESHOLD_GBP


def compute_effective_debt_to_equity(
    *,
    filing_adjusted_net_debt_gbp: float,
    stockholders_equity: float | None,
) -> float:
    """Map filing adjusted net debt to a Yahoo-style D/E percentage for screening."""
    if filing_adjusted_net_debt_gbp <= 0:
        return 0.0
    if stockholders_equity is not None and stockholders_equity > 0:
        return max(0.0, (filing_adjusted_net_debt_gbp / stockholders_equity) * 100.0)
    return EFFECTIVE_DE_FALLBACK


def dual_leverage_display_triggered(
    *,
    yahoo_de: float | None,
    filing_adjusted_net_debt_gbp: float | None,
) -> bool:
    """True when Yahoo D/E and filing net debt should both be shown."""
    if yahoo_de is None or filing_adjusted_net_debt_gbp is None:
        return False
    return float(yahoo_de) > YAHOO_DE_HIGH_THRESHOLD


def enrich_universe_with_leverage_override(
    universe: pd.DataFrame,
    output_dir: Any = None,
) -> pd.DataFrame:
    """Extract filing net debt and override Yahoo D/E for model scoring when warranted."""
    if universe.empty:
        return universe

    out = universe.copy()
    for column in (
        "debt_to_equity_yahoo",
        "filing_adjusted_net_debt_gbp",
        "leverage_override",
        "dual_leverage_display",
    ):
        if column not in out.columns:
            out[column] = None

    for index, row in out.iterrows():
        ticker = str(row["ticker"])
        yahoo_de = row.get("debt_to_equity")
        if yahoo_de is None or (isinstance(yahoo_de, float) and pd.isna(yahoo_de)):
            continue

        filing_net_debt = extract_adjusted_net_debt_for_ticker(ticker, output_dir=output_dir)
        if filing_net_debt is None:
            continue

        out.at[index, "debt_to_equity_yahoo"] = float(yahoo_de)
        out.at[index, "filing_adjusted_net_debt_gbp"] = float(filing_net_debt)
        out.at[index, "dual_leverage_display"] = dual_leverage_display_triggered(
            yahoo_de=float(yahoo_de),
            filing_adjusted_net_debt_gbp=filing_net_debt,
        )

        if not leverage_override_triggered(
            yahoo_de=float(yahoo_de),
            filing_adjusted_net_debt_gbp=filing_net_debt,
        ):
            continue

        financials = load_cached_financials(ticker, output_dir=output_dir)
        equity = extract_stockholders_equity(financials) if financials else None
        effective_de = compute_effective_debt_to_equity(
            filing_adjusted_net_debt_gbp=filing_net_debt,
            stockholders_equity=equity,
        )
        out.at[index, "leverage_override"] = True
        out.at[index, "debt_to_equity"] = effective_de

    return out


def format_adjusted_net_debt_gbp(value: float | None) -> str | None:
    """Human-readable filing adjusted net debt for exports."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    amount = float(value)
    if amount < 0:
        return f"£{-amount / 1_000_000:.1f}m net cash"
    return f"£{amount / 1_000_000:.1f}m adj. net debt"
