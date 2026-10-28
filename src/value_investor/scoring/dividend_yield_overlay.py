"""Dividend-yield overlay — cap signals when yield passes but FCF and earnings quality fail."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.scoring.fcf import (
    _float_or_none,
    build_fcf_basis_registry,
    fcf_yield_pass_suppressed,
    finalize_fcf_basis_bundle,
    high_dividend_yield_pass_suppressed,
    reconcile_fcf_for_ticker,
    screen_ttm_from_row,
)

HIGH_DIVIDEND_MODEL_ID = "high_dividend"
FCF_YIELD_MODEL_ID = "fcf_yield"
EARNINGS_QUALITY_MODEL_ID = "earnings_quality"

_SIGNAL_RANK = {
    "strong_buy": 4,
    "buy": 3,
    "hold": 2,
    "avoid": 1,
    "insufficient_data": 0,
}


def _row_as_series(row: pd.Series | dict[str, Any] | None) -> pd.Series:
    if row is None:
        return pd.Series(dtype=object)
    if isinstance(row, pd.Series):
        return row
    return pd.Series(row)


def _hydrate_fcf_bundle_from_basis_registry(bundle: dict[str, Any]) -> dict[str, Any]:
    """Merge canonical ``fcf_basis_registry`` fields into overlay suppression inputs."""
    out = dict(bundle)
    registry = out.get("fcf_basis_registry")
    if not isinstance(registry, dict):
        registry = build_fcf_basis_registry(out)
        if registry.get("selected_fcf") is not None or registry.get("filing_aligned") is not None:
            out["fcf_basis_registry"] = registry
    else:
        registry = dict(registry)

    for key in ("filing_aligned", "screen_ttm", "company_adjusted"):
        if out.get(key) is None and registry.get(key) is not None:
            out[key] = registry[key]
    selected = _float_or_none(registry.get("selected_fcf"))
    if selected is not None:
        out["canonical"] = selected
    elif out.get("canonical") is None and out.get("filing_aligned") is not None:
        out["canonical"] = out["filing_aligned"]
    primary = _float_or_none(registry.get("primary_fcf"))
    if primary is not None and out.get("primary_fcf") is None:
        out["primary_fcf"] = primary
    basis = registry.get("primary_fcf_basis") or registry.get("selected_basis")
    if basis and not out.get("primary_fcf_basis"):
        out["primary_fcf_basis"] = basis
    if registry.get("currency") and not out.get("currency"):
        out["currency"] = registry["currency"]
    return out


def _fcf_bundle_from_row(
    row: pd.Series,
    *,
    ticker: str,
    output_dir: Path | None,
) -> dict[str, Any]:
    nested = row.get("fcf")
    if isinstance(nested, dict) and nested:
        return _hydrate_fcf_bundle_from_basis_registry(dict(nested))
    screen_ttm = screen_ttm_from_row(row)
    if ticker and output_dir is not None:
        bundle = reconcile_fcf_for_ticker(
            ticker,
            screen_ttm=screen_ttm,
            output_dir=output_dir,
        )
        return _hydrate_fcf_bundle_from_basis_registry(bundle)
    filing_aligned = _float_or_none(row.get("free_cashflow"))
    key_metrics = row.get("key_metrics")
    if filing_aligned is None and isinstance(key_metrics, dict):
        filing_aligned = _float_or_none(key_metrics.get("FCF"))
    bundle = {
        "filing_aligned": filing_aligned,
        "screen_ttm": screen_ttm,
        "canonical": filing_aligned,
        "company_adjusted": _float_or_none(row.get("company_adjusted_fcf")),
        "company_adjusted_currency": row.get("company_adjusted_fcf_currency"),
        "currency": row.get("reporting_currency") or "GBP",
        "divergence_flagged": bool(row.get("fcf_divergence_flagged")),
        "fcf_divergence_flagged": bool(row.get("fcf_divergence_flagged")),
        "fcf_definition_divergence": bool(row.get("fcf_definition_divergence")),
        "ttm_suppressed_screen_filing_mismatch": bool(
            row.get("ttm_suppressed_screen_filing_mismatch")
        ),
    }
    return _hydrate_fcf_bundle_from_basis_registry(bundle)


def dividend_yield_family_fcf_basis_suppressed(
    *,
    ticker: str = "",
    row: pd.Series | dict[str, Any] | None = None,
    output_dir: Path | None = None,
) -> bool:
    """Fail-closed when dividend / FCF yield families lack a labelled FCF basis (JSG-style)."""
    series = _row_as_series(row)
    ticker = ticker or str(series.get("ticker") or "").strip().upper()
    bundle = _fcf_bundle_from_row(series, ticker=ticker, output_dir=output_dir)
    screen_ttm = bundle.get("screen_ttm")
    if screen_ttm is None and not series.empty:
        screen_ttm = screen_ttm_from_row(series)
    filing_aligned = bundle.get("filing_aligned")
    if filing_aligned is None and not series.empty:
        filing_aligned = _float_or_none(series.get("free_cashflow"))
    if filing_aligned is None or screen_ttm is None:
        return bool(bundle.get("ttm_suppressed_screen_filing_mismatch"))

    filing_currency = str(bundle.get("currency") or "GBP")
    company_adjusted = bundle.get("company_adjusted")
    company_adjusted_currency = bundle.get("company_adjusted_currency")
    definition = bool(bundle.get("fcf_definition_divergence")) or bool(
        series.get("fcf_definition_divergence")
    )
    if high_dividend_yield_pass_suppressed(
        filing_aligned=filing_aligned,
        screen_ttm=screen_ttm,
        company_adjusted=company_adjusted,
        filing_currency=filing_currency,
        company_adjusted_currency=company_adjusted_currency,
        fcf_definition_divergence=definition,
    ):
        return True
    return fcf_yield_pass_suppressed(
        divergence_flagged=bool(bundle.get("divergence_flagged")),
        canonical=bundle.get("canonical"),
        company_adjusted=company_adjusted,
        company_adjusted_currency=company_adjusted_currency,
        filing_currency=filing_currency,
        fcf_yield_unit_fx_error=bool(series.get("fcf_yield_unit_fx_error")),
        fcf_divergence_flagged=bool(bundle.get("fcf_divergence_flagged")),
        fcf_definition_divergence=definition,
        filing_aligned=filing_aligned,
        screen_ttm=screen_ttm,
    )


def strip_dividend_from_passed_families(passed_families: Any) -> str | None:
    """Remove dividend from comma-separated family labels when yield basis is unresolved."""
    if passed_families is None or (isinstance(passed_families, float) and pd.isna(passed_families)):
        return None
    parts = [part.strip() for part in str(passed_families).split(",") if part.strip()]
    kept = [part for part in parts if part.lower() != "dividend"]
    if len(kept) == len(parts):
        return str(passed_families)
    return ", ".join(kept) if kept else ""


def _strip_dual_fcf_dividend_research_prompts(raw: Any) -> list[str]:
    prefix = "Report dual FCF/dividend cover explicitly"
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return []
    items = raw if isinstance(raw, list) else [raw]
    kept: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and not text.startswith(prefix):
            kept.append(text)
    return kept


def enforce_neutral_watchlist_dividend_caution_after_yield_export(
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Re-apply watchlist→caution dividend overlay after yield-family export cleanup."""
    from value_investor.scoring.dividend_sustainability_overlay import (
        enforce_neutral_watchlist_dividend_caution_in_snapshot,
    )

    return enforce_neutral_watchlist_dividend_caution_in_snapshot(snapshot)


def enforce_dividend_yield_family_in_snapshot(
    snapshot: dict[str, Any],
    *,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Drop dividend-family credit when FCF yield basis is unresolved on export rows."""
    updated = dict(snapshot)
    fcf_raw = updated.get("fcf")
    if isinstance(fcf_raw, dict):
        from value_investor.scoring.fcf import surface_primary_fcf_on_overlay_record

        hydrated = finalize_fcf_basis_bundle(
            _hydrate_fcf_bundle_from_basis_registry(dict(fcf_raw)),
        )
        updated = surface_primary_fcf_on_overlay_record(updated, fcf_bundle=hydrated)
    if not dividend_yield_family_fcf_basis_suppressed(
        ticker=str(updated.get("ticker") or ""),
        row=updated,
        output_dir=output_dir,
    ):
        return updated
    updated["research_prompts"] = _strip_dual_fcf_dividend_research_prompts(
        updated.get("research_prompts")
    )
    updated["fcf_dividend_coverage"] = None
    updated["fcf_dividend_coverage_net"] = None
    updated["fcf_dividend_coverage_gross"] = None
    revised = strip_dividend_from_passed_families(updated.get("passed_families"))
    if revised != updated.get("passed_families"):
        updated["passed_families"] = revised
        families_passed = updated.get("families_passed")
        if families_passed is not None and not (
            isinstance(families_passed, float) and pd.isna(families_passed)
        ):
            try:
                updated["families_passed"] = max(0, int(families_passed) - 1)
            except (TypeError, ValueError):
                pass
    return updated


def high_dividend_screen_passed(ticker_models: pd.DataFrame) -> bool:
    """True when the High Dividend Yield screen passes for the ticker."""
    return _model_passed(ticker_models, HIGH_DIVIDEND_MODEL_ID) is True


def _model_passed(ticker_models: pd.DataFrame, model_id: str) -> bool | None:
    """Return pass/fail for ``model_id``, or None when the model row is absent."""
    if ticker_models.empty or "model_id" not in ticker_models.columns:
        return None
    rows = ticker_models[ticker_models["model_id"] == model_id]
    if rows.empty:
        return None
    return bool(rows.iloc[0]["passed"])


def _ticker_from_row(row: pd.Series | dict[str, Any] | None) -> str:
    if row is None:
        return ""
    if isinstance(row, pd.Series):
        return str(row.get("ticker") or "").strip().upper()
    return str(row.get("ticker") or "").strip().upper()


def dividend_yield_overlay_triggered(
    ticker_models: pd.DataFrame,
    *,
    row: pd.Series | dict[str, Any] | None = None,
    output_dir: Path | None = None,
) -> bool:
    """High Dividend Yield passes while FCF Yield and Earnings Quality both fail."""
    high_dividend = _model_passed(ticker_models, HIGH_DIVIDEND_MODEL_ID)
    fcf_yield = _model_passed(ticker_models, FCF_YIELD_MODEL_ID)
    earnings_quality = _model_passed(ticker_models, EARNINGS_QUALITY_MODEL_ID)
    if dividend_yield_family_fcf_basis_suppressed(
        ticker=_ticker_from_row(row),
        row=row,
        output_dir=output_dir,
    ):
        if high_dividend is True:
            high_dividend = False
        if fcf_yield is True:
            fcf_yield = False
    if high_dividend is not True:
        return False
    if fcf_yield is not False:
        return False
    return earnings_quality is False


def cap_signal_for_dividend_yield_overlay(signal: str) -> str:
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


def apply_dividend_yield_overlay_to_signal(
    signal: str,
    *,
    ticker_models: pd.DataFrame,
    adjusted_signal: str | None = None,
    row: pd.Series | dict[str, Any] | None = None,
    output_dir: Path | None = None,
) -> tuple[bool, str]:
    """Return overlay flag and conservative adjusted signal."""
    base_adjusted = adjusted_signal or signal
    if not dividend_yield_overlay_triggered(
        ticker_models,
        row=row,
        output_dir=output_dir,
    ):
        return False, base_adjusted
    capped = cap_signal_for_dividend_yield_overlay(signal)
    return True, _more_conservative_signal(base_adjusted, capped)


def enrich_signals_with_dividend_yield_overlay(
    signals: pd.DataFrame,
    model_results: pd.DataFrame,
    *,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    """Add dividend-yield overlay flag and cap ``adjusted_signal`` when triggered."""
    out = signals.copy()
    flags: list[bool] = []
    adjusted: list[str] = []

    for _, row in out.iterrows():
        ticker = str(row["ticker"])
        ticker_models = model_results[model_results["ticker"] == ticker]

        existing = row.get("adjusted_signal")
        existing_adjusted = (
            str(existing)
            if existing is not None and not (isinstance(existing, float) and pd.isna(existing))
            else None
        )

        triggered, new_adjusted = apply_dividend_yield_overlay_to_signal(
            str(row.get("signal") or "hold"),
            ticker_models=ticker_models,
            adjusted_signal=existing_adjusted,
            row=row,
            output_dir=output_dir,
        )
        flags.append(triggered)
        adjusted.append(new_adjusted)

    out["dividend_yield_overlay"] = flags
    out["adjusted_signal"] = adjusted
    from value_investor.scoring.dividend_sustainability_overlay import (
        enrich_signals_with_dividend_dual_fcf_research_prompts,
    )

    return enrich_signals_with_dividend_dual_fcf_research_prompts(
        out,
        model_results,
        output_dir=output_dir,
    )
