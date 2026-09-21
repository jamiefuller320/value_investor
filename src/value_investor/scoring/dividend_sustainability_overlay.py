"""Statutory-first dividend sustainability overlay — thin statutory cover and interim dividend cuts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.scoring.cash_conversion_overlay import dividend_screen_passed
from value_investor.scoring.dividend_yield_overlay import (
    dividend_yield_family_fcf_basis_suppressed,
    high_dividend_screen_passed,
)
from value_investor.scoring.fcf import resolve_free_cashflow
from value_investor.scoring.healthcare_overlay import piotroski_score_for_ticker

STATUTORY_DIVIDEND_COVERAGE_MAX = 1.05
THIN_FCF_DIVIDEND_COVERAGE_MAX = 1.0
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
    from value_investor.scoring.fcf import fcf_dividend_coverage, filing_aligned_fcf

    if (
        operating_cashflow is not None
        and capital_expenditure is not None
        and dividends_paid is not None
    ):
        statutory_fcf = filing_aligned_fcf(
            operating_cashflow,
            capital_expenditure,
            free_cashflow=free_cashflow,
        )
        computed = fcf_dividend_coverage(statutory_fcf, dividends_paid)
        if computed is not None and not (isinstance(computed, float) and pd.isna(computed)):
            return float(computed)
    if fcf_dividend_coverage_net is not None and not (
        isinstance(fcf_dividend_coverage_net, float) and pd.isna(fcf_dividend_coverage_net)
    ):
        return float(fcf_dividend_coverage_net)
    statutory_fcf = filing_aligned_fcf(
        operating_cashflow,
        capital_expenditure,
        free_cashflow=free_cashflow,
    )
    return fcf_dividend_coverage(statutory_fcf, dividends_paid)


def _float_coverage(fcf_dividend_coverage_net: float | None) -> float | None:
    if fcf_dividend_coverage_net is None or (
        isinstance(fcf_dividend_coverage_net, float) and pd.isna(fcf_dividend_coverage_net)
    ):
        return None
    return float(fcf_dividend_coverage_net)


def neutral_watchlist_dividend_caution_triggered(
    *,
    research_verdict: str | None,
    interim_dividend_cut_flagged: bool,
    fcf_dividend_coverage_net: float | None,
) -> bool:
    """Email watchlist (neutral research) with interim cut and thin statutory cover."""
    if not interim_dividend_cut_flagged:
        return False
    coverage = _float_coverage(fcf_dividend_coverage_net)
    if coverage is None or coverage >= THIN_FCF_DIVIDEND_COVERAGE_MAX:
        return False
    from value_investor.research.verdict import coerce_research_verdict

    return coerce_research_verdict(research_verdict) == "neutral"


def apply_neutral_watchlist_dividend_caution_overlay(
    signal: str,
    adjusted_signal: str,
    conviction_score: float,
    *,
    research_verdict: str | None,
    interim_dividend_cut_flagged: bool,
    fcf_dividend_coverage_net: float | None,
) -> tuple[str, float, bool]:
    """Treat neutral/watchlist research as caution when interim cut meets thin cover."""
    if not neutral_watchlist_dividend_caution_triggered(
        research_verdict=research_verdict,
        interim_dividend_cut_flagged=interim_dividend_cut_flagged,
        fcf_dividend_coverage_net=fcf_dividend_coverage_net,
    ):
        return adjusted_signal, float(conviction_score or 0.0), False
    from value_investor.research.verdict import (
        adjust_conviction_for_research,
        compute_adjusted_signal,
    )

    cautioned = compute_adjusted_signal(signal, "caution")
    merged = _more_conservative_signal(adjusted_signal, cautioned)
    conviction = float(conviction_score or 0.0)
    if merged != adjusted_signal:
        conviction = adjust_conviction_for_research(conviction, "caution")
    return merged, conviction, True


def enforce_neutral_watchlist_dividend_caution_in_snapshot(
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Export path: upgrade watchlist research to caution overlay when dividend flags fire."""
    updated = dict(snapshot)
    cut_raw = updated.get("interim_dividend_cut_flagged")
    cut_flagged = bool(cut_raw) if cut_raw is not None else False
    merged, conviction, applied = apply_neutral_watchlist_dividend_caution_overlay(
        str(updated.get("signal") or "hold"),
        str(updated.get("adjusted_signal") or updated.get("signal") or "hold"),
        float(updated.get("conviction_score") or 0.0),
        research_verdict=updated.get("research_verdict"),
        interim_dividend_cut_flagged=cut_flagged,
        fcf_dividend_coverage_net=_float_or_none(updated.get("fcf_dividend_coverage_net")),
    )
    if applied:
        updated["adjusted_signal"] = merged
        updated["conviction_score"] = conviction
        updated["research_verdict"] = "caution"
    return updated


def _float_or_none(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _row_as_series(row: pd.Series | dict[str, Any] | None) -> pd.Series:
    if row is None:
        return pd.Series(dtype=object)
    if isinstance(row, pd.Series):
        return row
    return pd.Series(row)


def _parse_research_prompts(raw: Any) -> list[str]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    text = str(raw).strip()
    return [text] if text else []


def dividend_family_passed_for_dual_fcf_research_prompt(
    *,
    passed_families: Any = None,
    ticker_models: pd.DataFrame,
    row: pd.Series | dict[str, Any] | None = None,
    output_dir: Path | None = None,
) -> bool:
    """True when dividend-family screens pass (model rows or ``passed_families`` text)."""
    series = _row_as_series(row)
    ticker = str(series.get("ticker") or "").strip().upper()
    if dividend_yield_family_fcf_basis_suppressed(
        ticker=ticker,
        row=series if not series.empty else {"passed_families": passed_families},
        output_dir=output_dir,
    ):
        return False
    if dividend_screen_passed(ticker_models) or high_dividend_screen_passed(ticker_models):
        return True
    if passed_families is not None and not (
        isinstance(passed_families, float) and pd.isna(passed_families)
    ):
        return "dividend" in str(passed_families)
    return False


def merge_dual_fcf_dividend_cover_research_prompts(
    existing: list[str],
    *,
    ticker: str,
    fcf_definition_divergence: bool,
    fcf_dividend_coverage_net: float | None,
    fcf_dividend_coverage_gross: float | None,
    dividend_family_passed: bool,
    output_dir: Path | None = None,
) -> list[str]:
    """Append the dual statutory vs management dividend-cover research prompt when eligible."""
    if not fcf_definition_divergence or not dividend_family_passed:
        return existing
    from value_investor.scoring.fcf import (
        format_dual_fcf_dividend_cover_research_prompt,
        load_ir_presentation_metrics,
    )

    ir_primary = bool(ticker and load_ir_presentation_metrics(ticker, output_dir=output_dir))
    prompt = format_dual_fcf_dividend_cover_research_prompt(
        fcf_dividend_coverage_net=fcf_dividend_coverage_net,
        fcf_dividend_coverage_gross=fcf_dividend_coverage_gross,
        ir_presentation_primary=ir_primary,
    )
    merged = list(existing)
    if prompt not in merged:
        merged.append(prompt)
    return merged


def enrich_screening_snapshot_dividend_dual_fcf_research_prompts(
    snapshot: dict[str, Any],
    *,
    output_dir: Path | None = None,
    model_results: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Ensure dividend-family snapshots carry dual FCF/dividend-cover research prompts."""
    updated = dict(snapshot)
    ticker = str(updated.get("ticker") or "").strip().upper()
    divergence_raw = updated.get("fcf_definition_divergence")
    if divergence_raw is None or (isinstance(divergence_raw, float) and pd.isna(divergence_raw)):
        return updated
    if not bool(divergence_raw):
        return updated

    ticker_models = pd.DataFrame()
    if model_results is not None and not model_results.empty and ticker:
        ticker_models = model_results[model_results["ticker"] == ticker]

    dividend_passed = dividend_family_passed_for_dual_fcf_research_prompt(
        passed_families=updated.get("passed_families"),
        ticker_models=ticker_models,
        row=updated,
        output_dir=output_dir,
    )
    if not dividend_passed:
        return updated

    from value_investor.scoring.fcf import labelled_fcf_dividend_coverage_for_snapshot

    net_raw = updated.get("fcf_dividend_coverage_net")
    fcf_dividend_coverage_net = (
        float(net_raw)
        if net_raw is not None and not (isinstance(net_raw, float) and pd.isna(net_raw))
        else None
    )
    gross_raw = updated.get("fcf_dividend_coverage_gross")
    fcf_dividend_coverage_gross = (
        float(gross_raw)
        if gross_raw is not None and not (isinstance(gross_raw, float) and pd.isna(gross_raw))
        else None
    )
    existing_label = updated.get("fcf_dividend_coverage")
    if not isinstance(existing_label, dict):
        labelled = labelled_fcf_dividend_coverage_for_snapshot(
            fcf_definition_divergence=True,
            fcf_dividend_coverage_net=fcf_dividend_coverage_net,
            fcf_dividend_coverage_gross=fcf_dividend_coverage_gross,
        )
        if labelled is not None:
            updated["fcf_dividend_coverage"] = labelled

    updated["research_prompts"] = merge_dual_fcf_dividend_cover_research_prompts(
        _parse_research_prompts(updated.get("research_prompts")),
        ticker=ticker,
        fcf_definition_divergence=True,
        fcf_dividend_coverage_net=fcf_dividend_coverage_net,
        fcf_dividend_coverage_gross=fcf_dividend_coverage_gross,
        dividend_family_passed=True,
        output_dir=output_dir,
    )
    return updated


def enrich_signals_with_dividend_dual_fcf_research_prompts(
    signals: pd.DataFrame,
    model_results: pd.DataFrame,
    *,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    """Attach dual FCF/dividend-cover prompts on pipeline signals when definitions diverge."""
    out = signals.copy()
    prompts: list[list[str]] = []
    for _, row in out.iterrows():
        ticker = str(row["ticker"])
        ticker_models = model_results[model_results["ticker"] == ticker]
        divergence_raw = row.get("fcf_definition_divergence")
        fcf_definition_divergence = (
            bool(divergence_raw)
            if divergence_raw is not None
            and not (isinstance(divergence_raw, float) and pd.isna(divergence_raw))
            else False
        )
        dividend_passed = dividend_family_passed_for_dual_fcf_research_prompt(
            passed_families=row.get("passed_families"),
            ticker_models=ticker_models,
            row=row,
            output_dir=output_dir,
        )
        net_raw = row.get("fcf_dividend_coverage_net")
        fcf_dividend_coverage_net = (
            float(net_raw)
            if net_raw is not None and not (isinstance(net_raw, float) and pd.isna(net_raw))
            else None
        )
        gross_raw = row.get("fcf_dividend_coverage_gross")
        fcf_dividend_coverage_gross = (
            float(gross_raw)
            if gross_raw is not None and not (isinstance(gross_raw, float) and pd.isna(gross_raw))
            else None
        )
        merged = merge_dual_fcf_dividend_cover_research_prompts(
            _parse_research_prompts(row.get("research_prompts")),
            ticker=ticker,
            fcf_definition_divergence=fcf_definition_divergence,
            fcf_dividend_coverage_net=fcf_dividend_coverage_net,
            fcf_dividend_coverage_gross=fcf_dividend_coverage_gross,
            dividend_family_passed=dividend_passed,
            output_dir=output_dir,
        )
        prompts.append(merged)
    out["research_prompts"] = prompts
    return out


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


def apply_dividend_sustainability_export_enforcement(
    *,
    signal: str,
    adjusted_signal: str,
    conviction_score: float,
    ticker_models: pd.DataFrame,
    dividend_sustainability_overlay: bool = False,
    fcf_dividend_coverage_net: float | None = None,
    operating_cashflow: float | None = None,
    capital_expenditure: float | None = None,
    dividends_paid: float | None = None,
    free_cashflow: float | None = None,
    interim_dividend_cut_pct: float | None = None,
    research_verdict: str | None = None,
) -> tuple[bool, bool, str, float]:
    """Re-apply statutory dividend-sustainability caps on export/snapshot paths."""
    cut_flagged = interim_dividend_cut_flagged(
        ticker_models=ticker_models,
        interim_dividend_cut_pct=interim_dividend_cut_pct,
    )
    if dividend_sustainability_overlay:
        capped = cap_signal_for_dividend_sustainability_overlay(signal)
        merged = _more_conservative_signal(adjusted_signal, capped)
        conviction_out = cap_conviction_for_dividend_sustainability_overlay(
            float(conviction_score or 0.0),
        )
        merged, conviction_out, _ = apply_neutral_watchlist_dividend_caution_overlay(
            signal,
            merged,
            conviction_out,
            research_verdict=research_verdict,
            interim_dividend_cut_flagged=cut_flagged,
            fcf_dividend_coverage_net=fcf_dividend_coverage_net,
        )
        return True, cut_flagged, merged, conviction_out

    triggered, cut_flagged, merged, conviction = apply_dividend_sustainability_overlay_to_signal(
        signal,
        ticker_models=ticker_models,
        fcf_dividend_coverage_net=fcf_dividend_coverage_net,
        operating_cashflow=operating_cashflow,
        capital_expenditure=capital_expenditure,
        dividends_paid=dividends_paid,
        free_cashflow=free_cashflow,
        interim_dividend_cut_pct=interim_dividend_cut_pct,
        conviction_score=conviction_score,
        adjusted_signal=adjusted_signal,
    )
    if not triggered:
        merged, conviction, _ = apply_neutral_watchlist_dividend_caution_overlay(
            signal,
            adjusted_signal,
            float(conviction_score or 0.0),
            research_verdict=research_verdict,
            interim_dividend_cut_flagged=cut_flagged,
            fcf_dividend_coverage_net=fcf_dividend_coverage_net,
        )
        return False, cut_flagged, merged, conviction
    merged, conviction, _ = apply_neutral_watchlist_dividend_caution_overlay(
        signal,
        merged,
        conviction,
        research_verdict=research_verdict,
        interim_dividend_cut_flagged=cut_flagged,
        fcf_dividend_coverage_net=fcf_dividend_coverage_net,
    )
    return True, cut_flagged, merged, conviction


def enrich_signals_with_dividend_sustainability_overlay(
    signals: pd.DataFrame,
    model_results: pd.DataFrame,
    *,
    output_dir: Path | None = None,
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
    return enrich_signals_with_dividend_dual_fcf_research_prompts(
        out,
        model_results,
        output_dir=output_dir,
    )
