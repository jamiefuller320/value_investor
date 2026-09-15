"""UK-listed contractor overlays — public-capex cyclicality and revenue/FCF quality warnings."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.scoring.fcf import (
    compute_yoy_growth_rate,
    load_cached_financials,
    load_filing_bodies_for_ticker,
)
from value_investor.scoring.interim_quality_overlay import quality_family_passed

_REVENUE_LABELS = (
    "Total Revenue",
    "Operating Revenue",
    "Revenue",
)

REVENUE_DECLINE_THRESHOLD = 0.03
FCF_RISE_THRESHOLD = 0.03
FRAMEWORK_BACKLOG_GROWTH_FLOOR = 0.0

UK_CONTRACTOR_NAME_FRAGMENTS = (
    "construction",
    "contractor",
    "civil engineering",
    "infrastructure group",
    "building group",
    "fit out",
    "fit-out",
    "costain",
    "balfour",
    "kier",
    "morgan sindall",
    "galliford",
    "interserve",
)

PUBLIC_CAPEX_KEYWORD_FRAGMENTS = (
    "spending review",
    "national highways",
    "regulated water",
    "amp7",
    "amp8",
    "framework agreement",
    "public sector",
    "public infrastructure",
    "infrastructure investment",
    "nuclear new build",
    "hs2",
    "transport for london",
    "tfl",
    "national grid",
)

_MIX_NOTES_FRAGMENTS = (
    "mix of work",
    "segment mix",
    "consultancy",
    "completion of contracts",
    "revenue from contracts which are partially",
    "preferred bidder",
    "forward work",
    "unsatisfied performance obligations",
)

_PUBLIC_CAPEX_RES = tuple(
    re.compile(re.escape(fragment), re.IGNORECASE) for fragment in PUBLIC_CAPEX_KEYWORD_FRAGMENTS
)
_MIX_NOTES_RES = tuple(
    re.compile(re.escape(fragment), re.IGNORECASE) for fragment in _MIX_NOTES_FRAGMENTS
)


def _as_text(value: object | None) -> str:
    """Coerce overlay text fields; pandas NaN floats are truthy and break ``.lower()``."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def is_uk_listed_contractor(
    ticker: str | None,
    name: str | None,
    sector: str | None = None,
) -> bool:
    """True for LSE contractors where sector overlays should apply."""
    if not ticker or not str(ticker).strip().upper().endswith(".L"):
        return False
    name_l = _as_text(name).lower()
    if any(fragment in name_l for fragment in UK_CONTRACTOR_NAME_FRAGMENTS):
        return True
    sector_l = _as_text(sector).lower()
    if "industrial" in sector_l and "infrastructure" in name_l:
        return True
    return False


def public_capex_exposure_detected(text: str) -> bool:
    if not text:
        return False
    return any(pattern.search(text) for pattern in _PUBLIC_CAPEX_RES)


def public_capex_exposure_for_ticker(
    ticker: str,
    *,
    output_dir: Path | None = None,
) -> bool:
    bodies = load_filing_bodies_for_ticker(ticker, output_dir=output_dir)
    return any(public_capex_exposure_detected(body) for body in bodies)


def filing_mix_notes_confirm(text: str) -> bool:
    """Filing prose explains revenue/FCF divergence (mix, completion, forward-work definitions)."""
    if not text:
        return False
    return any(pattern.search(text) for pattern in _MIX_NOTES_RES)


def filing_mix_notes_for_ticker(
    ticker: str,
    *,
    output_dir: Path | None = None,
) -> bool:
    bodies = load_filing_bodies_for_ticker(ticker, output_dir=output_dir)
    return any(filing_mix_notes_confirm(body) for body in bodies)


def _annual_label_value(year_rows: dict[str, Any], labels: tuple[str, ...]) -> float | None:
    for label in labels:
        value = year_rows.get(label)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def extract_filing_revenue_growth_pct(
    financials: dict[str, Any] | None,
) -> float | None:
    income_statement = (financials or {}).get("income_statement") or {}
    if not income_statement:
        return None
    years = sorted((str(year) for year in income_statement.keys()), reverse=True)
    if len(years) < 2:
        return None
    latest = _annual_label_value(income_statement.get(years[0]) or {}, _REVENUE_LABELS)
    prior = _annual_label_value(income_statement.get(years[1]) or {}, _REVENUE_LABELS)
    return compute_yoy_growth_rate(latest, prior)


def revenue_fcf_divergence_warning(
    *,
    revenue_growth_pct: float | None,
    free_cashflow: float | None,
    free_cashflow_prev: float | None,
    mix_notes_confirmed: bool,
) -> bool:
    """Falling revenue with rising FCF is a quality warning until mix notes confirm."""
    if mix_notes_confirmed:
        return False
    if revenue_growth_pct is None or (
        isinstance(revenue_growth_pct, float) and pd.isna(revenue_growth_pct)
    ):
        return False
    if float(revenue_growth_pct) > -REVENUE_DECLINE_THRESHOLD:
        return False
    if free_cashflow is None or free_cashflow_prev is None:
        return False
    if isinstance(free_cashflow, float) and pd.isna(free_cashflow):
        return False
    if isinstance(free_cashflow_prev, float) and pd.isna(free_cashflow_prev):
        return False
    fcf_growth = compute_yoy_growth_rate(float(free_cashflow), float(free_cashflow_prev))
    if fcf_growth is None or fcf_growth < FCF_RISE_THRESHOLD:
        return False
    return True


def framework_backlog_inflates_growth(
    *,
    revenue_growth_pct: float | None,
    earnings_growth: float | None,
) -> bool:
    """Yahoo-style growth can treat framework/order-book wins as revenue momentum."""
    if revenue_growth_pct is None or earnings_growth is None:
        return False
    if float(revenue_growth_pct) >= FRAMEWORK_BACKLOG_GROWTH_FLOOR:
        return False
    return float(earnings_growth) > float(revenue_growth_pct)


def suppress_framework_backlog_earnings_growth(
    earnings_growth: float | None,
    revenue_growth_pct: float | None,
) -> tuple[float | None, bool]:
    if not framework_backlog_inflates_growth(
        revenue_growth_pct=revenue_growth_pct,
        earnings_growth=earnings_growth,
    ):
        return earnings_growth, False
    capped = min(float(earnings_growth), float(revenue_growth_pct))
    return capped, True


def enrich_universe_with_uk_contractor_adjustments(
    universe: pd.DataFrame,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    """Cap filing-inconsistent earnings growth for UK contractors; attach revenue YoY."""
    if universe.empty:
        return universe

    out = universe.copy()
    for col in (
        "revenue_growth_filing_pct",
        "framework_backlog_growth_suppressed",
        "uk_contractor",
        "public_capex_exposure_detected",
        "filing_mix_notes_confirmed",
    ):
        if col not in out.columns:
            out[col] = None

    for index, row in out.iterrows():
        ticker = str(row["ticker"])
        contractor = is_uk_listed_contractor(
            ticker,
            row.get("name"),
            row.get("sector"),
        )
        out.at[index, "uk_contractor"] = contractor
        if not contractor:
            continue

        financials = load_cached_financials(ticker, output_dir=output_dir)
        revenue_growth = extract_filing_revenue_growth_pct(financials)
        if revenue_growth is None:
            existing_revenue_growth = row.get("revenue_growth_filing_pct")
            if existing_revenue_growth is not None and not (
                isinstance(existing_revenue_growth, float) and pd.isna(existing_revenue_growth)
            ):
                revenue_growth = float(existing_revenue_growth)
        if revenue_growth is not None:
            out.at[index, "revenue_growth_filing_pct"] = revenue_growth

        out.at[index, "public_capex_exposure_detected"] = public_capex_exposure_for_ticker(
            ticker,
            output_dir=output_dir,
        )
        mix_confirmed = filing_mix_notes_for_ticker(ticker, output_dir=output_dir)
        out.at[index, "filing_mix_notes_confirmed"] = mix_confirmed

        earnings_growth = row.get("earnings_growth")
        if earnings_growth is not None and not (
            isinstance(earnings_growth, float) and pd.isna(earnings_growth)
        ):
            capped, suppressed = suppress_framework_backlog_earnings_growth(
                float(earnings_growth),
                revenue_growth,
            )
            if suppressed and capped is not None:
                out.at[index, "earnings_growth"] = capped
                out.at[index, "framework_backlog_growth_suppressed"] = True

    return out


def enrich_signals_with_uk_contractor_detection(
    signals: pd.DataFrame,
    *,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    """Pre-set cyclical detection for UK public-capex contractors before cyclical enrich."""
    if signals.empty:
        return signals

    out = signals.copy()
    detected_flags: list[bool] = []
    public_capex_flags: list[bool] = []
    mix_flags: list[bool] = []
    revenue_fcf_warnings: list[bool] = []

    for _, row in out.iterrows():
        ticker = str(row["ticker"])
        contractor = bool(row.get("uk_contractor")) or is_uk_listed_contractor(
            ticker,
            row.get("name"),
            row.get("sector"),
        )

        public_capex = row.get("public_capex_exposure_detected")
        if public_capex is not None and not (
            isinstance(public_capex, float) and pd.isna(public_capex)
        ):
            public_capex_detected = bool(public_capex)
        elif contractor:
            public_capex_detected = public_capex_exposure_for_ticker(
                ticker,
                output_dir=output_dir,
            )
        else:
            public_capex_detected = False

        mix_flag = row.get("filing_mix_notes_confirmed")
        if mix_flag is not None and not (isinstance(mix_flag, float) and pd.isna(mix_flag)):
            mix_confirmed = bool(mix_flag)
        elif contractor:
            mix_confirmed = filing_mix_notes_for_ticker(ticker, output_dir=output_dir)
        else:
            mix_confirmed = False

        revenue_growth = row.get("revenue_growth_filing_pct")
        revenue_growth_pct = (
            float(revenue_growth)
            if revenue_growth is not None
            and not (isinstance(revenue_growth, float) and pd.isna(revenue_growth))
            else None
        )

        fcf = row.get("free_cashflow")
        fcf_prev = row.get("free_cashflow_prev")
        free_cashflow = (
            float(fcf)
            if fcf is not None and not (isinstance(fcf, float) and pd.isna(fcf))
            else None
        )
        free_cashflow_prev = (
            float(fcf_prev)
            if fcf_prev is not None and not (isinstance(fcf_prev, float) and pd.isna(fcf_prev))
            else None
        )

        rev_fcf_warning = contractor and revenue_fcf_divergence_warning(
            revenue_growth_pct=revenue_growth_pct,
            free_cashflow=free_cashflow,
            free_cashflow_prev=free_cashflow_prev,
            mix_notes_confirmed=mix_confirmed,
        )

        existing_cyclical = row.get("cyclical_exposure_detected")
        cyclical_detected = False
        if existing_cyclical is not None and not (
            isinstance(existing_cyclical, float) and pd.isna(existing_cyclical)
        ):
            cyclical_detected = bool(existing_cyclical)
        if contractor and public_capex_detected:
            cyclical_detected = True

        detected_flags.append(cyclical_detected)
        public_capex_flags.append(public_capex_detected)
        mix_flags.append(mix_confirmed)
        revenue_fcf_warnings.append(rev_fcf_warning)

    out["cyclical_exposure_detected"] = detected_flags
    out["public_capex_exposure_detected"] = public_capex_flags
    out["filing_mix_notes_confirmed"] = mix_flags
    out["uk_contractor_revenue_fcf_warning"] = revenue_fcf_warnings
    return out


def uk_contractor_cyclical_overlay_triggered(
    *,
    uk_contractor: bool,
    public_capex_detected: bool,
    passed_families: str | None,
    revenue_fcf_warning: bool,
) -> bool:
    if not uk_contractor or not public_capex_detected:
        return False
    if not quality_family_passed(passed_families):
        return False
    return revenue_fcf_warning


def uk_contractor_cash_conversion_overlay_triggered(
    *,
    uk_contractor: bool,
    passed_families: str | None,
    revenue_fcf_warning: bool,
) -> bool:
    if not uk_contractor:
        return False
    if not quality_family_passed(passed_families):
        return False
    return revenue_fcf_warning
