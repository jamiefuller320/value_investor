"""FCF basis overlay — cap conviction when FCF bases diverge (esp. vs yield screens)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.scoring.fcf import (
    ADVERTISING_REVENUE_SHARE_MEDIA_THRESHOLD,
    MEDIA_THIN_STATUTORY_FCF_DIVIDEND_COVERAGE_MAX,
    _float_or_none,
    fcf_action_note_mismatch,
    fcf_basis_definition_divergence,
    fcf_filing_screen_mismatch,
    reconcile_fcf_for_ticker,
    screen_ttm_from_row,
)

FCF_YIELD_DEPENDENT_MODEL_IDS = ("fcf_yield", "composite_value", "quality_value")
FCF_BASIS_CONVICTION_MULTIPLIER = 0.85
FCF_BASIS_MISMATCH_NOTE_MARKER = "fcf basis mismatch"

_SIGNAL_RANK = {
    "strong_buy": 4,
    "buy": 3,
    "hold": 2,
    "avoid": 1,
    "insufficient_data": 0,
}


def fcf_yield_dependent_model_passed(ticker_models: pd.DataFrame) -> bool:
    """True when an FCF-yield-dependent screen passes for the ticker."""
    if ticker_models.empty or "model_id" not in ticker_models.columns:
        return False
    dependent = ticker_models[ticker_models["model_id"].isin(FCF_YIELD_DEPENDENT_MODEL_IDS)]
    if dependent.empty:
        return False
    return bool(dependent["passed"].any())


def action_note_has_fcf_basis_mismatch(action_note: str | None) -> bool:
    """True when an action note already surfaces an FCF basis mismatch."""
    return FCF_BASIS_MISMATCH_NOTE_MARKER in str(action_note or "").strip().lower()


def fcf_basis_enforcement_needed(
    *,
    action_note_mismatch: bool,
    action_note: str | None = None,
) -> bool:
    """True when numeric predicates or persisted note text require FCF basis overlay."""
    return action_note_mismatch or action_note_has_fcf_basis_mismatch(action_note)


def fcf_basis_action_note_mismatch(
    fcf_bundle: dict[str, Any],
    *,
    screen_ttm: float | None,
    canonical: float | None = None,
    fcf_definition_divergence: bool = False,
) -> bool:
    """True when run-history would append an FCF divergence action note."""
    filing_aligned = fcf_bundle.get("filing_aligned", canonical)
    filing_for_mismatch = filing_aligned if filing_aligned is not None else canonical
    return fcf_action_note_mismatch(
        filing_aligned=filing_for_mismatch,
        screen_ttm=screen_ttm,
        company_adjusted=fcf_bundle.get("company_adjusted"),
        filing_currency=str(fcf_bundle.get("currency") or "USD"),
        company_adjusted_currency=fcf_bundle.get("company_adjusted_currency"),
        divergence_flagged=bool(fcf_bundle.get("divergence_flagged")),
        fcf_definition_divergence=fcf_definition_divergence
        or bool(fcf_bundle.get("fcf_definition_divergence")),
    )


def fcf_basis_overlay_triggered(
    *,
    divergence_flagged: bool,
    ticker_models: pd.DataFrame,
    filing_screen_mismatch: bool = False,
    universe_divergence_flagged: bool = False,
    action_note_mismatch: bool = False,
    fcf_yield_unit_fx_error: bool = False,
) -> bool:
    """Flag when the mismatch note would fire, or 50% divergence with a yield pass.

    Filing/screen mismatch (25%), universe divergence (15%, same predicate as
    ``FCF basis mismatch`` action notes), and the shared action-note mismatch
    predicate always trigger the overlay so buy-tier signals cannot persist beside
    a cosmetic note. The legacy 50% divergence path still requires a yield-dependent
    model pass.
    """
    if (
        filing_screen_mismatch
        or universe_divergence_flagged
        or action_note_mismatch
        or fcf_yield_unit_fx_error
    ):
        return True
    if not divergence_flagged:
        return False
    return fcf_yield_dependent_model_passed(ticker_models)


def cap_signal_for_fcf_basis_overlay(signal: str) -> str:
    """Cap at research-equivalent caution: strong_buy -> buy, buy -> hold."""
    if signal == "strong_buy":
        return "buy"
    if signal == "buy":
        return "hold"
    return signal


def cap_conviction_for_fcf_basis_overlay(conviction_score: float) -> float:
    """Reduce conviction when FCF basis mismatch inflates yield-dependent screens."""
    return max(0.0, float(conviction_score) * FCF_BASIS_CONVICTION_MULTIPLIER)


def _fcf_bundle_for_enforcement(
    fcf_bundle: dict[str, Any] | None,
    *,
    action_note: str | None = None,
    screen_ttm: float | None = None,
) -> dict[str, Any]:
    """Rebuild filing/screen FCF bases from persisted rows or action-note text."""
    from value_investor.scoring.fcf import fcf_bundle_from_persisted_report

    bundle = dict(fcf_bundle) if fcf_bundle else {}
    if bundle.get("filing_aligned") is None or bundle.get("screen_ttm") is None:
        from_note = fcf_bundle_from_persisted_report(
            bundle if bundle else None,
            action_note=action_note,
        )
        for key, value in from_note.items():
            bundle.setdefault(key, value)
    if screen_ttm is not None and bundle.get("screen_ttm") is None:
        bundle["screen_ttm"] = screen_ttm
    return bundle


def fcf_export_enforcement_active(
    *,
    fcf_basis_overlay: bool = False,
    action_note: str | None = None,
    fcf_bundle: dict[str, Any] | None = None,
    screen_ttm: float | None = None,
) -> bool:
    """True when export/snapshot paths must cap buy-tier signals for FCF basis notes."""
    if fcf_basis_overlay:
        return True
    bundle = _fcf_bundle_for_enforcement(
        fcf_bundle,
        action_note=action_note,
        screen_ttm=screen_ttm,
    )
    numeric_mismatch = fcf_basis_action_note_mismatch(
        bundle,
        screen_ttm=screen_ttm or bundle.get("screen_ttm"),
    )
    return fcf_basis_enforcement_needed(
        action_note_mismatch=numeric_mismatch,
        action_note=action_note,
    )


def apply_fcf_export_enforcement(
    *,
    signal: str,
    adjusted_signal: str,
    conviction_score: float,
    action_note: str | None = None,
    fcf_basis_overlay: bool = False,
    fcf_bundle: dict[str, Any] | None = None,
    screen_ttm: float | None = None,
) -> tuple[bool, str, float]:
    """Re-apply FCF basis caps after research merge or stale overlay flags."""
    bundle = _fcf_bundle_for_enforcement(
        fcf_bundle,
        action_note=action_note,
        screen_ttm=screen_ttm,
    )
    resolved_screen_ttm = screen_ttm or bundle.get("screen_ttm")
    if not fcf_export_enforcement_active(
        fcf_basis_overlay=fcf_basis_overlay,
        action_note=action_note,
        fcf_bundle=bundle,
        screen_ttm=resolved_screen_ttm,
    ):
        return bool(fcf_basis_overlay), adjusted_signal, float(conviction_score or 0.0)

    capped = cap_signal_for_fcf_basis_overlay(signal)
    merged = _more_conservative_signal(adjusted_signal, capped)
    if fcf_basis_overlay and merged == adjusted_signal:
        return True, merged, float(conviction_score or 0.0)
    return (
        True,
        merged,
        cap_conviction_for_fcf_basis_overlay(float(conviction_score or 0.0)),
    )


def _more_conservative_signal(current: str, candidate: str) -> str:
    current_rank = _SIGNAL_RANK.get(current, 0)
    candidate_rank = _SIGNAL_RANK.get(candidate, 0)
    return current if current_rank <= candidate_rank else candidate


def apply_fcf_basis_overlay_to_signal(
    signal: str,
    *,
    divergence_flagged: bool,
    ticker_models: pd.DataFrame,
    conviction_score: float,
    adjusted_signal: str | None = None,
    filing_screen_mismatch: bool = False,
    universe_divergence_flagged: bool = False,
    action_note_mismatch: bool = False,
    fcf_yield_unit_fx_error: bool = False,
) -> tuple[bool, str, float]:
    """Return overlay flag, conservative adjusted signal, and capped conviction."""
    base_adjusted = adjusted_signal or signal
    base_conviction = float(conviction_score or 0.0)
    if not fcf_basis_overlay_triggered(
        divergence_flagged=divergence_flagged,
        ticker_models=ticker_models,
        filing_screen_mismatch=filing_screen_mismatch,
        universe_divergence_flagged=universe_divergence_flagged,
        action_note_mismatch=action_note_mismatch,
        fcf_yield_unit_fx_error=fcf_yield_unit_fx_error,
    ):
        return False, base_adjusted, base_conviction
    capped_signal = cap_signal_for_fcf_basis_overlay(signal)
    return (
        True,
        _more_conservative_signal(base_adjusted, capped_signal),
        cap_conviction_for_fcf_basis_overlay(base_conviction),
    )


def enrich_signals_with_fcf_basis_overlay(
    signals: pd.DataFrame,
    model_results: pd.DataFrame,
    *,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    """Add FCF basis overlay flag and cap yield-inflated conviction when triggered."""
    out = signals.copy()
    flags: list[bool] = []
    adjusted: list[str] = []
    convictions: list[float] = []

    for _, row in out.iterrows():
        ticker = str(row["ticker"])
        ticker_models = model_results[model_results["ticker"] == ticker]
        screen_ttm = screen_ttm_from_row(row)
        fcf_bundle = reconcile_fcf_for_ticker(
            ticker,
            screen_ttm=screen_ttm,
            output_dir=output_dir,
        )
        mismatch = bool(fcf_bundle.get("filing_screen_mismatch")) or fcf_filing_screen_mismatch(
            filing_aligned=fcf_bundle.get("filing_aligned"),
            screen_ttm=screen_ttm,
            divergence_flagged=bool(fcf_bundle.get("divergence_flagged")),
        )
        action_note_mismatch = fcf_basis_enforcement_needed(
            action_note_mismatch=fcf_basis_action_note_mismatch(
                fcf_bundle,
                screen_ttm=screen_ttm,
            ),
            action_note=str(row.get("action_note") or ""),
        )
        unit_fx_raw = row.get("fcf_yield_unit_fx_error")
        fcf_yield_unit_fx_error = (
            bool(unit_fx_raw)
            if unit_fx_raw is not None
            and not (isinstance(unit_fx_raw, float) and pd.isna(unit_fx_raw))
            else False
        )

        existing = row.get("adjusted_signal")
        existing_adjusted = (
            str(existing)
            if existing is not None and not (isinstance(existing, float) and pd.isna(existing))
            else None
        )

        triggered, new_adjusted, new_conviction = apply_fcf_basis_overlay_to_signal(
            str(row.get("signal") or "hold"),
            divergence_flagged=bool(fcf_bundle.get("divergence_flagged")),
            filing_screen_mismatch=mismatch,
            universe_divergence_flagged=bool(fcf_bundle.get("fcf_divergence_flagged")),
            action_note_mismatch=action_note_mismatch,
            fcf_yield_unit_fx_error=fcf_yield_unit_fx_error,
            ticker_models=ticker_models,
            conviction_score=float(row.get("conviction_score") or 0.0),
            adjusted_signal=existing_adjusted,
        )
        flags.append(triggered)
        adjusted.append(new_adjusted)
        convictions.append(new_conviction)

    out["fcf_basis_overlay"] = flags
    out["adjusted_signal"] = adjusted
    out["conviction_score"] = convictions
    return out


def honour_fcf_action_notes_on_signals(signals: pd.DataFrame) -> pd.DataFrame:
    """Re-sync signal columns when persisted action notes require FCF basis overlay."""
    if signals.empty:
        return signals

    out = signals.copy()
    for index, row in out.iterrows():
        action_note = str(row.get("action_note") or "")
        screen_ttm = screen_ttm_from_row(row)
        row_fcf = row.get("fcf") if isinstance(row.get("fcf"), dict) else None
        fcf_bundle = _fcf_bundle_for_enforcement(
            row_fcf,
            action_note=action_note,
            screen_ttm=screen_ttm,
        )
        filing = fcf_bundle.get("filing_aligned")
        if filing is None:
            from value_investor.scoring.fcf import _float_or_none

            row_filing = _float_or_none(row.get("free_cashflow"))
            if row_filing is not None:
                fcf_bundle["filing_aligned"] = row_filing
        if not fcf_basis_enforcement_needed(
            action_note_mismatch=fcf_basis_action_note_mismatch(
                fcf_bundle,
                screen_ttm=screen_ttm,
            ),
            action_note=action_note,
        ):
            continue

        signal = str(row.get("signal") or "hold")
        existing = row.get("adjusted_signal")
        existing_adjusted = (
            str(existing)
            if existing is not None and not (isinstance(existing, float) and pd.isna(existing))
            else None
        )
        overlay, merged_adjusted, conviction = apply_fcf_export_enforcement(
            signal=signal,
            adjusted_signal=existing_adjusted or signal,
            conviction_score=float(row.get("conviction_score") or 0.0),
            action_note=action_note,
            fcf_basis_overlay=bool(row.get("fcf_basis_overlay")),
            fcf_bundle=fcf_bundle if fcf_bundle else None,
            screen_ttm=fcf_bundle.get("screen_ttm"),
        )
        if not overlay:
            continue
        out.at[index, "fcf_basis_overlay"] = overlay
        out.at[index, "adjusted_signal"] = merged_adjusted
        out.at[index, "conviction_score"] = conviction

    return out


_BUY_TIER_RUN_HISTORY_SIGNALS = frozenset({"strong_buy", "buy"})


def enrich_signals_with_run_history_fcf_action_notes(
    signals: pd.DataFrame,
    *,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    """Persist FCF divergence flags for buy-tier rows; append notes on ``strong_buy`` only."""
    if signals.empty:
        return signals

    from value_investor.scoring.earnings_growth_overlay import (
        build_earnings_growth_overlay,
        format_earnings_growth_bps_warning,
    )
    from value_investor.scoring.fcf import (
        append_fcf_divergence_to_action_note,
        compute_dual_fcf_dividend_coverage,
        extract_cashflow_metrics_from_annual_financials,
        extract_dividends_paid_from_annual_financials,
        extract_gross_cash_from_operations_for_ticker,
        labelled_fcf_dividend_coverage_for_snapshot,
        load_cached_financials,
        overlay_free_cashflow_from_bundle,
        reconcile_fcf_for_ticker,
    )

    out = signals.copy()
    if "action_note" not in out.columns:
        out["action_note"] = ""
    for index, row in out.iterrows():
        signal = str(row.get("signal") or "")
        if signal not in _BUY_TIER_RUN_HISTORY_SIGNALS:
            continue

        ticker = str(row["ticker"])
        screen_ttm = screen_ttm_from_row(row)
        fcf_bundle = reconcile_fcf_for_ticker(
            ticker,
            screen_ttm=screen_ttm,
            output_dir=output_dir,
        )
        canonical = overlay_free_cashflow_from_bundle(row, fcf_bundle)

        coverage_gross_raw = row.get("fcf_dividend_coverage_gross")
        fcf_dividend_coverage_gross = (
            float(coverage_gross_raw)
            if coverage_gross_raw is not None
            and not (isinstance(coverage_gross_raw, float) and pd.isna(coverage_gross_raw))
            else None
        )
        coverage_net_raw = row.get("fcf_dividend_coverage_net")
        fcf_dividend_coverage_net = (
            float(coverage_net_raw)
            if coverage_net_raw is not None
            and not (isinstance(coverage_net_raw, float) and pd.isna(coverage_net_raw))
            else None
        )
        definition_div_raw = row.get("fcf_definition_divergence")
        gross_ocf_raw = row.get("operating_cashflow_gross")
        operating_cashflow_gross = (
            float(gross_ocf_raw)
            if gross_ocf_raw is not None
            and not (isinstance(gross_ocf_raw, float) and pd.isna(gross_ocf_raw))
            else None
        )
        operating_cashflow_raw = row.get("operating_cashflow")
        operating_cashflow = (
            float(operating_cashflow_raw)
            if operating_cashflow_raw is not None
            and not (isinstance(operating_cashflow_raw, float) and pd.isna(operating_cashflow_raw))
            else None
        )
        if operating_cashflow_gross is None:
            operating_cashflow_gross = extract_gross_cash_from_operations_for_ticker(
                ticker,
                output_dir=output_dir,
            )
        if (
            operating_cashflow is None
            or fcf_dividend_coverage_net is None
            or fcf_dividend_coverage_gross is None
        ):
            financials = load_cached_financials(ticker, output_dir=output_dir)
            if financials:
                cash_metrics = extract_cashflow_metrics_from_annual_financials(financials)
                if operating_cashflow is None:
                    operating_cashflow = cash_metrics.get("operating_cashflow")
                dividends_paid = extract_dividends_paid_from_annual_financials(financials)
                coverage = compute_dual_fcf_dividend_coverage(
                    operating_cashflow=operating_cashflow,
                    operating_cashflow_gross=operating_cashflow_gross,
                    capital_expenditure=cash_metrics.get("capital_expenditure"),
                    dividends_paid=dividends_paid,
                    free_cashflow=cash_metrics.get("free_cashflow"),
                )
                if fcf_dividend_coverage_net is None:
                    fcf_dividend_coverage_net = coverage.get("fcf_dividend_coverage_net")
                if fcf_dividend_coverage_gross is None:
                    fcf_dividend_coverage_gross = coverage.get("fcf_dividend_coverage_gross")

        filing_currency = str(fcf_bundle.get("currency") or "GBP")
        computed_definition = fcf_basis_definition_divergence(
            operating_cashflow=operating_cashflow,
            operating_cashflow_gross=operating_cashflow_gross,
            filing_aligned=_float_or_none(fcf_bundle.get("filing_aligned")),
            screen_ttm=screen_ttm,
            company_adjusted=_float_or_none(fcf_bundle.get("company_adjusted")),
            filing_currency=filing_currency,
            company_adjusted_currency=fcf_bundle.get("company_adjusted_currency"),
        )
        fcf_definition_divergence = computed_definition or bool(
            fcf_bundle.get("fcf_definition_divergence")
        )
        if (
            definition_div_raw is not None
            and not (isinstance(definition_div_raw, float) and pd.isna(definition_div_raw))
            and bool(definition_div_raw)
        ):
            fcf_definition_divergence = True
        divergence_flag_raw = row.get("fcf_divergence_flagged")
        fcf_divergence_flagged = (
            bool(divergence_flag_raw)
            if divergence_flag_raw is not None
            and not (isinstance(divergence_flag_raw, float) and pd.isna(divergence_flag_raw))
            else bool(fcf_bundle.get("fcf_divergence_flagged"))
        )
        if fcf_action_note_mismatch(
            filing_aligned=fcf_bundle.get("filing_aligned"),
            screen_ttm=screen_ttm,
            company_adjusted=fcf_bundle.get("company_adjusted"),
            filing_currency=filing_currency,
            company_adjusted_currency=fcf_bundle.get("company_adjusted_currency"),
            divergence_flagged=bool(fcf_bundle.get("divergence_flagged")),
            fcf_definition_divergence=fcf_definition_divergence,
        ):
            fcf_divergence_flagged = True

        for col in (
            "fcf_definition_divergence",
            "fcf_divergence_flagged",
            "fcf_dividend_coverage_net",
            "fcf_dividend_coverage_gross",
            "fcf_dividend_coverage",
        ):
            if col not in out.columns:
                out[col] = None
        if fcf_definition_divergence:
            out.loc[index, "fcf_definition_divergence"] = True
        if fcf_divergence_flagged:
            out.loc[index, "fcf_divergence_flagged"] = True
        if fcf_dividend_coverage_net is not None:
            out.loc[index, "fcf_dividend_coverage_net"] = fcf_dividend_coverage_net
        if fcf_dividend_coverage_gross is not None:
            out.loc[index, "fcf_dividend_coverage_gross"] = fcf_dividend_coverage_gross
        labelled_coverage = labelled_fcf_dividend_coverage_for_snapshot(
            fcf_definition_divergence=fcf_definition_divergence,
            fcf_dividend_coverage_net=fcf_dividend_coverage_net,
            fcf_dividend_coverage_gross=fcf_dividend_coverage_gross,
        )
        if labelled_coverage is not None:
            out.at[index, "fcf_dividend_coverage"] = labelled_coverage

        if signal != "strong_buy":
            continue

        action_note = append_fcf_divergence_to_action_note(
            str(row.get("action_note") or ""),
            canonical=canonical,
            screen_ttm=screen_ttm,
            fcf_bundle=fcf_bundle,
            fcf_dividend_coverage_net=fcf_dividend_coverage_net,
            fcf_dividend_coverage_gross=fcf_dividend_coverage_gross,
            fcf_definition_divergence=fcf_definition_divergence,
        )
        bps_warning = format_earnings_growth_bps_warning(build_earnings_growth_overlay(row))
        if bps_warning and bps_warning not in action_note:
            action_note = f"{action_note} | {bps_warning}" if action_note else bps_warning

        if action_note != str(row.get("action_note") or ""):
            out.at[index, "action_note"] = action_note

    return out


MEDIA_CYCLICAL_FCF_CONVICTION_MULTIPLIER = 0.85
MEDIA_CYCLICAL_FCF_NOTE_MARKER = "media cyclicality thin fcf cover"
PIOTROSKI_WEAK_FOR_MEDIA_CYCLICAL_FCF = 4


def media_cyclical_thin_fcf_overlay_triggered(
    *,
    advertising_revenue_share: float | None,
    piotroski_f_score: int | None,
    statutory_fcf_dividend_coverage: float | None,
) -> bool:
    """Advertising-heavy media with weak Piotroski and thin statutory FCF/dividend cover."""
    if advertising_revenue_share is None or (
        isinstance(advertising_revenue_share, float) and pd.isna(advertising_revenue_share)
    ):
        return False
    if float(advertising_revenue_share) <= ADVERTISING_REVENUE_SHARE_MEDIA_THRESHOLD:
        return False
    if piotroski_f_score is None:
        return False
    if int(piotroski_f_score) > PIOTROSKI_WEAK_FOR_MEDIA_CYCLICAL_FCF:
        return False
    if statutory_fcf_dividend_coverage is None or (
        isinstance(statutory_fcf_dividend_coverage, float)
        and pd.isna(statutory_fcf_dividend_coverage)
    ):
        return False
    return float(statutory_fcf_dividend_coverage) <= MEDIA_THIN_STATUTORY_FCF_DIVIDEND_COVERAGE_MAX


def cap_signal_for_media_cyclical_thin_fcf_overlay(signal: str) -> str:
    """Cap at research-equivalent caution: strong_buy -> buy, buy -> hold."""
    if signal == "strong_buy":
        return "buy"
    if signal == "buy":
        return "hold"
    return signal


def cap_conviction_for_media_cyclical_thin_fcf_overlay(conviction_score: float) -> float:
    """Reduce conviction when cyclical ad revenue meets thin statutory FCF cover."""
    return max(0.0, float(conviction_score) * MEDIA_CYCLICAL_FCF_CONVICTION_MULTIPLIER)


def apply_media_cyclical_thin_fcf_overlay_to_signal(
    signal: str,
    *,
    advertising_revenue_share: float | None,
    piotroski_f_score: int | None,
    statutory_fcf_dividend_coverage: float | None,
    conviction_score: float,
    adjusted_signal: str | None = None,
) -> tuple[bool, str, float, float | None]:
    """Return overlay flag, conservative adjusted signal, capped conviction, and ad share."""
    base_adjusted = adjusted_signal or signal
    base_conviction = float(conviction_score or 0.0)
    if not media_cyclical_thin_fcf_overlay_triggered(
        advertising_revenue_share=advertising_revenue_share,
        piotroski_f_score=piotroski_f_score,
        statutory_fcf_dividend_coverage=statutory_fcf_dividend_coverage,
    ):
        return False, base_adjusted, base_conviction, advertising_revenue_share
    capped_signal = cap_signal_for_media_cyclical_thin_fcf_overlay(signal)
    return (
        True,
        _more_conservative_signal(base_adjusted, capped_signal),
        cap_conviction_for_media_cyclical_thin_fcf_overlay(base_conviction),
        advertising_revenue_share,
    )


def apply_media_cyclical_thin_fcf_export_enforcement(
    *,
    signal: str,
    adjusted_signal: str,
    conviction_score: float,
    media_cyclical_thin_fcf_overlay: bool = False,
    advertising_revenue_share: float | None = None,
    piotroski_f_score: int | None = None,
    statutory_fcf_dividend_coverage: float | None = None,
) -> tuple[bool, str, float]:
    """Re-apply media cyclical FCF caps on export/snapshot paths."""
    if media_cyclical_thin_fcf_overlay:
        capped = cap_signal_for_media_cyclical_thin_fcf_overlay(signal)
        merged = _more_conservative_signal(adjusted_signal, capped)
        if merged == adjusted_signal:
            return True, merged, float(conviction_score or 0.0)
        return (
            True,
            merged,
            cap_conviction_for_media_cyclical_thin_fcf_overlay(float(conviction_score or 0.0)),
        )
    triggered, merged, conviction, _ = apply_media_cyclical_thin_fcf_overlay_to_signal(
        signal,
        advertising_revenue_share=advertising_revenue_share,
        piotroski_f_score=piotroski_f_score,
        statutory_fcf_dividend_coverage=statutory_fcf_dividend_coverage,
        conviction_score=conviction_score,
        adjusted_signal=adjusted_signal,
    )
    if not triggered:
        return False, adjusted_signal, float(conviction_score or 0.0)
    return True, merged, conviction


def enrich_signals_with_media_cyclical_thin_fcf_overlay(
    signals: pd.DataFrame,
    model_results: pd.DataFrame,
    *,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    """Flag ad-heavy media with thin statutory FCF cover and cap buy-tier conviction."""
    from value_investor.scoring.fcf import (
        ADVERTISING_REVENUE_SHARE_MEDIA_THRESHOLD,
        advertising_revenue_share_for_ticker,
        resolve_free_cashflow,
        resolve_statutory_fcf_dividend_coverage,
    )
    from value_investor.scoring.healthcare_overlay import piotroski_score_for_ticker

    if signals.empty:
        return signals

    out = signals.copy()
    overlay_flags: list[bool] = []
    ad_shares: list[float | None] = []
    adjusted: list[str] = []
    convictions: list[float] = []
    cyclical_detected: list[bool] = []

    for _, row in out.iterrows():
        ticker = str(row["ticker"])
        ticker_models = model_results[model_results["ticker"] == ticker]

        share_raw = row.get("advertising_revenue_share")
        if share_raw is not None and not (isinstance(share_raw, float) and pd.isna(share_raw)):
            advertising_revenue_share = float(share_raw)
        else:
            advertising_revenue_share = advertising_revenue_share_for_ticker(
                ticker,
                output_dir=output_dir,
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
        statutory_cover = resolve_statutory_fcf_dividend_coverage(
            fcf_dividend_coverage_net=fcf_dividend_coverage_net,
            operating_cashflow=operating_cashflow,
            capital_expenditure=capital_expenditure,
            dividends_paid=dividends_paid,
            free_cashflow=resolve_free_cashflow(row),
        )
        piotroski = piotroski_score_for_ticker(ticker_models)

        existing = row.get("adjusted_signal")
        existing_adjusted = (
            str(existing)
            if existing is not None and not (isinstance(existing, float) and pd.isna(existing))
            else None
        )

        triggered, new_adjusted, new_conviction, resolved_share = (
            apply_media_cyclical_thin_fcf_overlay_to_signal(
                str(row.get("signal") or "hold"),
                advertising_revenue_share=advertising_revenue_share,
                piotroski_f_score=piotroski,
                statutory_fcf_dividend_coverage=statutory_cover,
                conviction_score=float(row.get("conviction_score") or 0.0),
                adjusted_signal=existing_adjusted,
            )
        )
        overlay_flags.append(triggered)
        ad_shares.append(resolved_share)
        adjusted.append(new_adjusted)
        convictions.append(new_conviction)

        prior_cyclical = row.get("cyclical_exposure_detected")
        cyclical = (
            bool(prior_cyclical)
            if (
                prior_cyclical is not None
                and not (isinstance(prior_cyclical, float) and pd.isna(prior_cyclical))
            )
            else False
        )
        if triggered and (
            resolved_share is not None
            and resolved_share > ADVERTISING_REVENUE_SHARE_MEDIA_THRESHOLD
        ):
            cyclical = True
        cyclical_detected.append(cyclical)

    out["media_cyclical_thin_fcf_overlay"] = overlay_flags
    out["advertising_revenue_share"] = ad_shares
    out["adjusted_signal"] = adjusted
    out["conviction_score"] = convictions
    out["cyclical_exposure_detected"] = cyclical_detected
    return out


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
) -> tuple[bool, bool, str, float]:
    """Re-apply statutory dividend-sustainability caps on export/snapshot paths."""
    from value_investor.scoring.dividend_sustainability_overlay import (
        apply_dividend_sustainability_overlay_to_signal,
        cap_conviction_for_dividend_sustainability_overlay,
        cap_signal_for_dividend_sustainability_overlay,
        interim_dividend_cut_flagged,
    )

    cut_flagged = interim_dividend_cut_flagged(
        ticker_models=ticker_models,
        interim_dividend_cut_pct=interim_dividend_cut_pct,
    )
    if dividend_sustainability_overlay:
        capped = cap_signal_for_dividend_sustainability_overlay(signal)
        merged = _more_conservative_signal(adjusted_signal, capped)
        if merged == adjusted_signal:
            return True, cut_flagged, merged, float(conviction_score or 0.0)
        return (
            True,
            cut_flagged,
            merged,
            cap_conviction_for_dividend_sustainability_overlay(float(conviction_score or 0.0)),
        )

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
        return False, cut_flagged, adjusted_signal, float(conviction_score or 0.0)
    return True, cut_flagged, merged, conviction


def enrich_signals_with_dividend_sustainability_overlay(
    signals: pd.DataFrame,
    model_results: pd.DataFrame,
) -> pd.DataFrame:
    """Add dividend-sustainability overlay flags and cap conviction when triggered."""
    from value_investor.scoring.dividend_sustainability_overlay import (
        enrich_signals_with_dividend_sustainability_overlay as _enrich,
    )

    return _enrich(signals, model_results)
