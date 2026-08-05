"""Interim quality overlay — cap signals when quality passes but interim EPS falls and FCF cover is thin."""

from __future__ import annotations

import pandas as pd

from value_investor.scoring.fcf import resolve_free_cashflow

INTERIM_EPS_DECLINE_THRESHOLD = 0.03
FCF_DIVIDEND_COVERAGE_MAX = 1.0

_SIGNAL_RANK = {
    "strong_buy": 4,
    "buy": 3,
    "hold": 2,
    "avoid": 1,
    "insufficient_data": 0,
}


def quality_family_passed(passed_families: str | None) -> bool:
    """True when the trailing quality model family passes."""
    if not passed_families:
        return False
    return "quality" in {part.strip() for part in str(passed_families).split(",") if part.strip()}


def fcf_dividend_coverage(
    free_cashflow: float | None,
    dividends_paid: float | None,
) -> float | None:
    """Return FCF divided by annual cash dividends when both are available."""
    if free_cashflow is None or (isinstance(free_cashflow, float) and pd.isna(free_cashflow)):
        return None
    if dividends_paid is None or (isinstance(dividends_paid, float) and pd.isna(dividends_paid)):
        return None
    dividends = abs(float(dividends_paid))
    if dividends <= 0:
        return None
    return float(free_cashflow) / dividends


def interim_quality_overlay_triggered(
    *,
    passed_families: str | None,
    interim_eps_decline_pct: float | None,
    free_cashflow: float | None,
    dividends_paid: float | None,
) -> bool:
    """Quality passes, interim EPS decline exceeds 3%, and FCF/dividend coverage is below 1.0×."""
    if not quality_family_passed(passed_families):
        return False
    if interim_eps_decline_pct is None or (
        isinstance(interim_eps_decline_pct, float) and pd.isna(interim_eps_decline_pct)
    ):
        return False
    if float(interim_eps_decline_pct) <= INTERIM_EPS_DECLINE_THRESHOLD:
        return False
    coverage = fcf_dividend_coverage(free_cashflow, dividends_paid)
    if coverage is None or coverage >= FCF_DIVIDEND_COVERAGE_MAX:
        return False
    return True


def cap_signal_for_interim_quality_overlay(signal: str) -> str:
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


def apply_interim_quality_overlay_to_signal(
    signal: str,
    *,
    passed_families: str | None,
    interim_eps_decline_pct: float | None,
    free_cashflow: float | None,
    dividends_paid: float | None,
    adjusted_signal: str | None = None,
) -> tuple[bool, str]:
    """Return overlay flag and conservative adjusted signal."""
    base_adjusted = adjusted_signal or signal
    if not interim_quality_overlay_triggered(
        passed_families=passed_families,
        interim_eps_decline_pct=interim_eps_decline_pct,
        free_cashflow=free_cashflow,
        dividends_paid=dividends_paid,
    ):
        return False, base_adjusted
    capped = cap_signal_for_interim_quality_overlay(signal)
    return True, _more_conservative_signal(base_adjusted, capped)


def enrich_signals_with_interim_quality_overlay(
    signals: pd.DataFrame,
    model_results: pd.DataFrame,
) -> pd.DataFrame:
    """Add interim-quality overlay flag and cap ``adjusted_signal`` when triggered."""
    _ = model_results
    out = signals.copy()
    flags: list[bool] = []
    adjusted: list[str] = []

    for _, row in out.iterrows():
        existing = row.get("adjusted_signal")
        existing_adjusted = (
            str(existing)
            if existing is not None and not (isinstance(existing, float) and pd.isna(existing))
            else None
        )

        interim_decline = row.get("interim_eps_decline_pct")
        interim_eps_decline_pct = (
            float(interim_decline)
            if interim_decline is not None and not (isinstance(interim_decline, float) and pd.isna(interim_decline))
            else None
        )

        dividends = row.get("dividends_paid")
        dividends_paid = (
            float(dividends)
            if dividends is not None and not (isinstance(dividends, float) and pd.isna(dividends))
            else None
        )

        triggered, new_adjusted = apply_interim_quality_overlay_to_signal(
            str(row.get("signal") or "hold"),
            passed_families=row.get("passed_families"),
            interim_eps_decline_pct=interim_eps_decline_pct,
            free_cashflow=resolve_free_cashflow(row),
            dividends_paid=dividends_paid,
            adjusted_signal=existing_adjusted,
        )
        flags.append(triggered)
        adjusted.append(new_adjusted)

    out["interim_quality_overlay"] = flags
    out["adjusted_signal"] = adjusted
    return out
