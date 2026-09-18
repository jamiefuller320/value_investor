"""Statutory-first dividend sustainability overlay — thin statutory cover and interim dividend cuts."""

from __future__ import annotations

import pandas as pd

from value_investor.scoring.cash_conversion_overlay import dividend_screen_passed
from value_investor.scoring.fcf import resolve_free_cashflow
from value_investor.scoring.healthcare_overlay import piotroski_score_for_ticker

STATUTORY_DIVIDEND_COVERAGE_MAX = 1.05
PIOTROSKI_WEAK_FOR_DIVIDEND_SUSTAINABILITY = 4
DIVIDEND_SUSTAINABILITY_CONVICTION_MULTIPLIER = 0.85
HIGH_DIVIDEND_MODEL_ID = "high_dividend"

_SIGNAL_RANK = {
    "strong_buy": 4,
    "buy": 3,
    "hold": 2,
    "avoid": 1,
    "insufficient_data": 0,
}


def _high_dividend_yield_passed(ticker_models: pd.DataFrame) -> bool:
    if ticker_models.empty or "model_id" not in ticker_models.columns:
        return False
    rows = ticker_models[ticker_models["model_id"] == HIGH_DIVIDEND_MODEL_ID]
    if rows.empty:
        return False
    return bool(rows.iloc[0]["passed"])


def resolve_statutory_dividend_coverage_for_overlay(
    *,
    fcf_dividend_coverage_net: float | None,
    operating_cashflow: float | None = None,
    capital_expenditure: float | None = None,
    dividends_paid: float | None = None,
    free_cashflow: float | None = None,
) -> float | None:
    """Statutory OCF−CapEx dividend cover (never management/company-adjusted FCF)."""
    if fcf_dividend_coverage_net is not None and not (
        isinstance(fcf_dividend_coverage_net, float) and pd.isna(fcf_dividend_coverage_net)
    ):
        return float(fcf_dividend_coverage_net)
    from value_investor.scoring.fcf import fcf_dividend_coverage, filing_aligned_fcf

    statutory_fcf = filing_aligned_fcf(
        operating_cashflow,
        capital_expenditure,
        free_cashflow=free_cashflow,
    )
    return fcf_dividend_coverage(statutory_fcf, dividends_paid)


def interim_dividend_cut_flagged(
    *,
    ticker_models: pd.DataFrame,
    interim_dividend_cut_pct: float | None,
) -> bool:
    """High Dividend Yield passes on trailing data but the latest interim cut the dividend."""
    if not _high_dividend_yield_passed(ticker_models):
        return False
    if interim_dividend_cut_pct is None or (
        isinstance(interim_dividend_cut_pct, float) and pd.isna(interim_dividend_cut_pct)
    ):
        return False
    return float(interim_dividend_cut_pct) > 0


def dividend_sustainability_overlay_triggered(
    *,
    ticker_models: pd.DataFrame,
    fcf_dividend_coverage_net: float | None,
    operating_cashflow: float | None = None,
    capital_expenditure: float | None = None,
    dividends_paid: float | None = None,
    free_cashflow: float | None = None,
) -> bool:
    """Dividend family passes with statutory cover ≤1.05× and weak Piotroski (ITV pattern)."""
    if not dividend_screen_passed(ticker_models):
        return False
    statutory_cover = resolve_statutory_dividend_coverage_for_overlay(
        fcf_dividend_coverage_net=fcf_dividend_coverage_net,
        operating_cashflow=operating_cashflow,
        capital_expenditure=capital_expenditure,
        dividends_paid=dividends_paid,
        free_cashflow=free_cashflow,
    )
    if statutory_cover is None or statutory_cover > STATUTORY_DIVIDEND_COVERAGE_MAX:
        return False
    piotroski = piotroski_score_for_ticker(ticker_models)
    if piotroski is None or piotroski > PIOTROSKI_WEAK_FOR_DIVIDEND_SUSTAINABILITY:
        return False
    return True


def cap_signal_for_dividend_sustainability_overlay(signal: str) -> str:
    """Cap at research-equivalent caution: strong_buy -> buy, buy -> hold."""
    if signal == "strong_buy":
        return "buy"
    if signal == "buy":
        return "hold"
    return signal


def cap_conviction_for_dividend_sustainability_overlay(conviction_score: float) -> float:
    """Reduce conviction when dividend screens pass on unsustainable statutory cover."""
    return max(0.0, float(conviction_score) * DIVIDEND_SUSTAINABILITY_CONVICTION_MULTIPLIER)


def _more_conservative_signal(current: str, candidate: str) -> str:
    current_rank = _SIGNAL_RANK.get(current, 0)
    candidate_rank = _SIGNAL_RANK.get(candidate, 0)
    return current if current_rank <= candidate_rank else candidate


def apply_dividend_sustainability_overlay_to_signal(
    signal: str,
    *,
    ticker_models: pd.DataFrame,
    fcf_dividend_coverage_net: float | None,
    operating_cashflow: float | None = None,
    capital_expenditure: float | None = None,
    dividends_paid: float | None = None,
    free_cashflow: float | None = None,
    interim_dividend_cut_pct: float | None = None,
    conviction_score: float,
    adjusted_signal: str | None = None,
) -> tuple[bool, bool, str, float]:
    """Return overlay flag, interim-cut flag, conservative adjusted signal, and capped conviction."""
    base_adjusted = adjusted_signal or signal
    base_conviction = float(conviction_score or 0.0)
    cut_flagged = interim_dividend_cut_flagged(
        ticker_models=ticker_models,
        interim_dividend_cut_pct=interim_dividend_cut_pct,
    )
    triggered = dividend_sustainability_overlay_triggered(
        ticker_models=ticker_models,
        fcf_dividend_coverage_net=fcf_dividend_coverage_net,
        operating_cashflow=operating_cashflow,
        capital_expenditure=capital_expenditure,
        dividends_paid=dividends_paid,
        free_cashflow=free_cashflow,
    )
    if not triggered:
        return False, cut_flagged, base_adjusted, base_conviction
    capped_signal = cap_signal_for_dividend_sustainability_overlay(signal)
    return (
        True,
        cut_flagged,
        _more_conservative_signal(base_adjusted, capped_signal),
        cap_conviction_for_dividend_sustainability_overlay(base_conviction),
    )


def enrich_signals_with_dividend_sustainability_overlay(
    signals: pd.DataFrame,
    model_results: pd.DataFrame,
) -> pd.DataFrame:
    """Add dividend-sustainability overlay flags and cap conviction when triggered."""
    out = signals.copy()
    overlay_flags: list[bool] = []
    cut_flags: list[bool] = []
    adjusted: list[str] = []
    convictions: list[float] = []

    for _, row in out.iterrows():
        ticker = str(row["ticker"])
        ticker_models = model_results[model_results["ticker"] == ticker]

        existing = row.get("adjusted_signal")
        existing_adjusted = (
            str(existing)
            if existing is not None and not (isinstance(existing, float) and pd.isna(existing))
            else None
        )

        coverage_net = row.get("fcf_dividend_coverage_net")
        fcf_dividend_coverage_net = (
            float(coverage_net)
            if coverage_net is not None
            and not (isinstance(coverage_net, float) and pd.isna(coverage_net))
            else None
        )
        ocf = row.get("operating_cashflow")
        operating_cashflow = (
            float(ocf)
            if ocf is not None and not (isinstance(ocf, float) and pd.isna(ocf))
            else None
        )
        capex = row.get("capital_expenditure")
        capital_expenditure = (
            float(capex)
            if capex is not None and not (isinstance(capex, float) and pd.isna(capex))
            else None
        )
        dividends = row.get("dividends_paid")
        dividends_paid = (
            float(dividends)
            if dividends is not None and not (isinstance(dividends, float) and pd.isna(dividends))
            else None
        )
        cut_raw = row.get("interim_dividend_cut_pct")
        interim_dividend_cut_pct = (
            float(cut_raw)
            if cut_raw is not None and not (isinstance(cut_raw, float) and pd.isna(cut_raw))
            else None
        )

        triggered, cut_flagged, new_adjusted, new_conviction = (
            apply_dividend_sustainability_overlay_to_signal(
                str(row.get("signal") or "hold"),
                ticker_models=ticker_models,
                fcf_dividend_coverage_net=fcf_dividend_coverage_net,
                operating_cashflow=operating_cashflow,
                capital_expenditure=capital_expenditure,
                dividends_paid=dividends_paid,
                free_cashflow=resolve_free_cashflow(row),
                interim_dividend_cut_pct=interim_dividend_cut_pct,
                conviction_score=float(row.get("conviction_score") or 0.0),
                adjusted_signal=existing_adjusted,
            )
        )
        overlay_flags.append(triggered)
        cut_flags.append(cut_flagged)
        adjusted.append(new_adjusted)
        convictions.append(new_conviction)

    out["dividend_sustainability_overlay"] = overlay_flags
    out["interim_dividend_cut_flagged"] = cut_flags
    out["adjusted_signal"] = adjusted
    out["conviction_score"] = convictions
    return out
