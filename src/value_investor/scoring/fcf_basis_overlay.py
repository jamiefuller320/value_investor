"""FCF basis overlay — cap conviction when FCF bases diverge (esp. vs yield screens)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.scoring.fcf import (
    fcf_action_note_mismatch,
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
) -> bool:
    """Flag when the mismatch note would fire, or 50% divergence with a yield pass.

    Filing/screen mismatch (25%), universe divergence (15%, same predicate as
    ``FCF basis mismatch`` action notes), and the shared action-note mismatch
    predicate always trigger the overlay so buy-tier signals cannot persist beside
    a cosmetic note. The legacy 50% divergence path still requires a yield-dependent
    model pass.
    """
    if filing_screen_mismatch or universe_divergence_flagged or action_note_mismatch:
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
    bundle = fcf_bundle or {}
    numeric_mismatch = fcf_basis_action_note_mismatch(
        bundle,
        screen_ttm=screen_ttm,
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
    if not fcf_export_enforcement_active(
        fcf_basis_overlay=fcf_basis_overlay,
        action_note=action_note,
        fcf_bundle=fcf_bundle,
        screen_ttm=screen_ttm,
    ):
        return bool(fcf_basis_overlay), adjusted_signal, float(conviction_score or 0.0)

    capped = cap_signal_for_fcf_basis_overlay(signal)
    merged = _more_conservative_signal(adjusted_signal, capped)
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
