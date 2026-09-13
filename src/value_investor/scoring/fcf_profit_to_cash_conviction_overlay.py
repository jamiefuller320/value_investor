"""Conviction downgrade when three-way FCF bases diverge and profit-to-cash falls YoY."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.scoring.fcf import (
    extract_profit_to_cash_yoy_drop_for_ticker,
    fcf_three_way_universe_divergence_flagged,
    profit_to_cash_drop_triggered,
    reconcile_fcf_for_ticker,
    screen_ttm_from_row,
)

FCF_PROFIT_TO_CASH_CONVICTION_MULTIPLIER = 0.85
CONVICTION_DOWNGRADE_NOTE_MARKER = "three-way FCF mismatch with profit-to-cash decline"


def cap_conviction_for_fcf_profit_to_cash_overlay(conviction_score: float) -> float:
    """Reduce conviction when FCF bases disagree alongside falling profit-to-cash."""
    return max(0.0, float(conviction_score) * FCF_PROFIT_TO_CASH_CONVICTION_MULTIPLIER)


def fcf_profit_to_cash_conviction_overlay_triggered(
    *,
    fcf_bundle: dict[str, Any],
    profit_to_cash_yoy_drop_pp: float | None,
) -> bool:
    """Three-way >15% FCF divergence plus >15pp profit-to-cash YoY drop (ITV pattern)."""
    if not profit_to_cash_drop_triggered(profit_to_cash_yoy_drop_pp):
        return False
    return fcf_three_way_universe_divergence_flagged(
        filing_aligned=fcf_bundle.get("filing_aligned"),
        screen_ttm=fcf_bundle.get("screen_ttm"),
        company_adjusted=fcf_bundle.get("company_adjusted"),
        filing_currency=str(fcf_bundle.get("currency") or "USD"),
        company_adjusted_currency=fcf_bundle.get("company_adjusted_currency"),
    )


def format_fcf_profit_to_cash_conviction_note(
    *,
    profit_to_cash_pct: float | None,
    profit_to_cash_pct_prev: float | None,
    profit_to_cash_yoy_drop_pp: float | None,
) -> str:
    """Human-readable action-note fragment for export paths."""
    if profit_to_cash_pct is not None and profit_to_cash_pct_prev is not None:
        ratio_text = f"{profit_to_cash_pct:.0f}% vs {profit_to_cash_pct_prev:.0f}%"
    elif profit_to_cash_yoy_drop_pp is not None:
        ratio_text = f"−{profit_to_cash_yoy_drop_pp:.0f}pp YoY"
    else:
        ratio_text = "profit-to-cash decline"
    return f"Conviction downgrade: {CONVICTION_DOWNGRADE_NOTE_MARKER} ({ratio_text})"


def apply_fcf_profit_to_cash_conviction_overlay(
    *,
    conviction_score: float,
    fcf_bundle: dict[str, Any],
    profit_to_cash_yoy_drop_pp: float | None,
) -> tuple[bool, float]:
    """Return overlay flag and capped conviction (signal unchanged for strong-buy confirmation)."""
    base_conviction = float(conviction_score or 0.0)
    if not fcf_profit_to_cash_conviction_overlay_triggered(
        fcf_bundle=fcf_bundle,
        profit_to_cash_yoy_drop_pp=profit_to_cash_yoy_drop_pp,
    ):
        return False, base_conviction
    return True, cap_conviction_for_fcf_profit_to_cash_overlay(base_conviction)


def enrich_signals_with_fcf_profit_to_cash_conviction_overlay(
    signals: pd.DataFrame,
    *,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    """Flag conviction downgrade and cap conviction when FCF/profit-to-cash predicates fire."""
    if signals.empty:
        return signals

    out = signals.copy()
    flags: list[bool] = []
    convictions: list[float] = []
    drop_pps: list[float | None] = []

    for _, row in out.iterrows():
        ticker = str(row["ticker"])
        screen_ttm = screen_ttm_from_row(row)
        fcf_bundle = reconcile_fcf_for_ticker(
            ticker,
            screen_ttm=screen_ttm,
            output_dir=output_dir,
        )
        if fcf_bundle.get("screen_ttm") is None and screen_ttm is not None:
            fcf_bundle["screen_ttm"] = screen_ttm

        drop_raw = row.get("profit_to_cash_yoy_drop_pp")
        profit_drop = (
            float(drop_raw)
            if drop_raw is not None and not (isinstance(drop_raw, float) and pd.isna(drop_raw))
            else None
        )
        if profit_drop is None:
            profit_drop = extract_profit_to_cash_yoy_drop_for_ticker(
                ticker,
                output_dir=output_dir,
            )

        triggered, new_conviction = apply_fcf_profit_to_cash_conviction_overlay(
            conviction_score=float(row.get("conviction_score") or 0.0),
            fcf_bundle=fcf_bundle,
            profit_to_cash_yoy_drop_pp=profit_drop,
        )
        flags.append(triggered)
        convictions.append(new_conviction)
        drop_pps.append(profit_drop)

        if triggered:
            note = format_fcf_profit_to_cash_conviction_note(
                profit_to_cash_pct=_float_or_none(row.get("profit_to_cash_pct")),
                profit_to_cash_pct_prev=_float_or_none(row.get("profit_to_cash_pct_prev")),
                profit_to_cash_yoy_drop_pp=profit_drop,
            )
            existing = str(row.get("action_note") or "")
            if note not in existing:
                out.at[row.name, "action_note"] = f"{existing} | {note}" if existing else note

    out["conviction_downgrade_flagged"] = flags
    out["conviction_score"] = convictions
    out["profit_to_cash_yoy_drop_pp"] = drop_pps
    return out


def _float_or_none(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
