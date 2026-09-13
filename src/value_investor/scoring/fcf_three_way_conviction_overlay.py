"""FCF three-way mismatch + profit-to-cash decline — conviction downgrade overlay."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.scoring.fcf import (
    PROFIT_TO_CASH_YOY_DECLINE_PP_THRESHOLD,
    fcf_three_way_mismatch_flagged,
    profit_to_cash_yoy_decline_for_ticker,
    reconcile_fcf_for_ticker,
    screen_ttm_from_row,
)

FCF_THREE_WAY_CONVICTION_MULTIPLIER = 0.85
FCF_THREE_WAY_CONVICTION_NOTE_MARKER = "fcf three-way mismatch"


def build_fcf_three_way_conviction_overlay(
    *,
    ticker: str,
    fcf_bundle: dict[str, Any],
    screen_ttm: float | None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Detect three-way FCF split with material profit-to-cash YoY decline."""
    overlay: dict[str, Any] = {
        "fcf_three_way_conviction_overlay": False,
        "profit_to_cash_current_pct": None,
        "profit_to_cash_prior_pct": None,
        "profit_to_cash_yoy_decline_pp": None,
    }
    three_way = fcf_three_way_mismatch_flagged(
        filing_aligned=fcf_bundle.get("filing_aligned"),
        screen_ttm=screen_ttm or fcf_bundle.get("screen_ttm"),
        company_adjusted=fcf_bundle.get("company_adjusted"),
        filing_currency=str(fcf_bundle.get("currency") or "USD"),
        company_adjusted_currency=fcf_bundle.get("company_adjusted_currency"),
    )
    if not three_way:
        return overlay

    current, prior, decline_pp = profit_to_cash_yoy_decline_for_ticker(
        ticker,
        output_dir=output_dir,
        min_decline_pp=PROFIT_TO_CASH_YOY_DECLINE_PP_THRESHOLD,
    )
    if decline_pp is None or current is None or prior is None:
        return overlay

    overlay["fcf_three_way_conviction_overlay"] = True
    overlay["profit_to_cash_current_pct"] = current
    overlay["profit_to_cash_prior_pct"] = prior
    overlay["profit_to_cash_yoy_decline_pp"] = decline_pp
    return overlay


def format_fcf_three_way_conviction_overlay_note(overlay: dict[str, Any]) -> str | None:
    """Compact action-note fragment when conviction downgrade overlay fires."""
    if not overlay.get("fcf_three_way_conviction_overlay"):
        return None
    current = overlay.get("profit_to_cash_current_pct")
    prior = overlay.get("profit_to_cash_prior_pct")
    decline = overlay.get("profit_to_cash_yoy_decline_pp")
    if current is None or prior is None or decline is None:
        return (
            f"{FCF_THREE_WAY_CONVICTION_NOTE_MARKER}: filing, company-adj, and screen TTM "
            "FCF diverge >15% with profit-to-cash YoY decline >15pp (conviction downgraded)."
        )
    return (
        f"{FCF_THREE_WAY_CONVICTION_NOTE_MARKER}: filing/company-adj/screen TTM FCF diverge "
        f">15% and profit-to-cash {current:.0f}% vs {prior:.0f}% "
        f"(−{decline:.0f}pp YoY; conviction downgraded)."
    )


def cap_conviction_for_fcf_three_way_overlay(conviction_score: float) -> float:
    """Reduce conviction when three-way FCF split coincides with weak cash conversion."""
    return max(0.0, float(conviction_score) * FCF_THREE_WAY_CONVICTION_MULTIPLIER)


def apply_fcf_three_way_conviction_overlay(
    *,
    conviction_score: float,
    overlay: dict[str, Any],
) -> tuple[bool, float]:
    """Return overlay flag and capped conviction when predicates fire."""
    base_conviction = float(conviction_score or 0.0)
    if not overlay.get("fcf_three_way_conviction_overlay"):
        return False, base_conviction
    return True, cap_conviction_for_fcf_three_way_overlay(base_conviction)


def enrich_signals_with_fcf_three_way_conviction_overlay(
    signals: pd.DataFrame,
    *,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    """Add three-way FCF conviction overlay flag and cap conviction when triggered."""
    if signals.empty:
        return signals

    out = signals.copy()
    flags: list[bool] = []
    convictions: list[float] = []
    current_pcts: list[float | None] = []
    prior_pcts: list[float | None] = []
    decline_pps: list[float | None] = []

    for _, row in out.iterrows():
        ticker = str(row["ticker"])
        screen_ttm = screen_ttm_from_row(row)
        fcf_bundle = reconcile_fcf_for_ticker(
            ticker,
            screen_ttm=screen_ttm,
            output_dir=output_dir,
        )
        overlay = build_fcf_three_way_conviction_overlay(
            ticker=ticker,
            fcf_bundle=fcf_bundle,
            screen_ttm=screen_ttm,
            output_dir=output_dir,
        )
        triggered, conviction = apply_fcf_three_way_conviction_overlay(
            conviction_score=float(row.get("conviction_score") or 0.0),
            overlay=overlay,
        )
        flags.append(triggered)
        convictions.append(conviction)
        current_pcts.append(overlay.get("profit_to_cash_current_pct"))
        prior_pcts.append(overlay.get("profit_to_cash_prior_pct"))
        decline_pps.append(overlay.get("profit_to_cash_yoy_decline_pp"))

    out["fcf_three_way_conviction_overlay"] = flags
    out["conviction_score"] = convictions
    out["profit_to_cash_current_pct"] = current_pcts
    out["profit_to_cash_prior_pct"] = prior_pcts
    out["profit_to_cash_yoy_decline_pp"] = decline_pps
    return out
