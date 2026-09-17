"""Normalize screening snapshots and signal exports before persistence."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.research.verdict import compute_adjusted_signal
from value_investor.scoring.fcf import (
    _ticker_reporting_currency,
    enrich_screening_snapshot_fcf_dividend_coverage,
    fcf_action_note_mismatch,
    fcf_basis_definition_divergence,
    fcf_bundle_from_persisted_report,
    reconcile_fcf_for_ticker,
    screen_ttm_from_row,
)
from value_investor.scoring.fcf_basis_overlay import (
    action_note_has_fcf_basis_mismatch,
    apply_fcf_export_enforcement,
)

_SIGNAL_LABELS = {
    "strong_buy": "Strong Buy",
    "buy": "Buy",
    "hold": "Hold",
    "avoid": "Avoid",
    "insufficient_data": "Insufficient Data",
}

_FCF_BASIS_MISMATCH_SEGMENT = re.compile(
    r"FCF basis mismatch:[^|]*",
    re.IGNORECASE,
)
_RESEARCH_SEGMENT_PREFIX = re.compile(r"^\s*research\s*:", re.IGNORECASE)


def failed_models_from_results(
    model_results: pd.DataFrame | None,
    ticker: str,
) -> list[str]:
    if model_results is None or model_results.empty:
        return []
    rows = model_results[
        (model_results["ticker"] == ticker) & (model_results["passed"] == False)  # noqa: E712
    ]
    if rows.empty or "model_name" not in rows.columns:
        return []
    return rows["model_name"].astype(str).tolist()


def _research_headline_replacement(
    *,
    signal: str,
    research_verdict: str | None,
    adjusted_signal: str | None,
    research_risk_level: str | None = None,
) -> str | None:
    """Label for action_note/summary when research downgrades a buy-tier screen signal."""
    raw = str(signal or "").strip().lower()
    if raw not in ("strong_buy", "buy"):
        return None
    verdict = str(research_verdict or "").strip().lower()
    if verdict != "accumulate":
        return None
    adjusted = str(adjusted_signal or signal).strip().lower()
    risk = str(research_risk_level or "").strip().lower()
    if raw == "strong_buy":
        if adjusted == "strong_buy":
            return None
        return _SIGNAL_LABELS.get(adjusted, adjusted.replace("_", " ").title())
    if raw == "buy":
        if adjusted in ("hold", "avoid", "insufficient_data"):
            return _SIGNAL_LABELS.get(adjusted, adjusted.replace("_", " ").title())
        if risk == "high":
            return _SIGNAL_LABELS.get("hold", "Hold")
        return None
    return None


def _dedupe_pipe_segments(action_note: str) -> str:
    if not action_note or " | " not in action_note:
        return action_note
    seen: set[str] = set()
    kept: list[str] = []
    for segment in action_note.split(" | "):
        piece = segment.strip()
        if not piece:
            continue
        key = piece.lower()
        if _RESEARCH_SEGMENT_PREFIX.match(piece):
            key = re.sub(r"\s+", " ", key.split("—", 1)[0].split("-", 1)[0].strip())
        if key in seen:
            continue
        seen.add(key)
        kept.append(piece)
    return " | ".join(kept)


def _rewrite_action_note_headline(
    action_note: str,
    *,
    signal: str,
    research_verdict: str | None,
    adjusted_signal: str | None,
    research_risk_level: str | None = None,
) -> str:
    if not action_note:
        return action_note
    effective = _research_headline_replacement(
        signal=signal,
        research_verdict=research_verdict,
        adjusted_signal=adjusted_signal,
        research_risk_level=research_risk_level,
    )
    if effective is None:
        return action_note
    if signal == "strong_buy" and action_note.startswith("Strong Buy"):
        return action_note.replace("Strong Buy", effective, 1)
    if signal == "buy" and action_note.startswith("Buy"):
        return action_note.replace("Buy", effective, 1)
    return action_note


def _rewrite_summary_headline(
    summary: str | None,
    *,
    signal: str,
    research_verdict: str | None,
    adjusted_signal: str | None,
    research_risk_level: str | None = None,
) -> str | None:
    if not summary:
        return summary
    effective = _research_headline_replacement(
        signal=signal,
        research_verdict=research_verdict,
        adjusted_signal=adjusted_signal,
        research_risk_level=research_risk_level,
    )
    if effective is None:
        return summary
    if signal == "strong_buy" and summary.startswith("Strong Buy"):
        return summary.replace("Strong Buy", effective, 1)
    if signal == "buy" and summary.startswith("Buy"):
        return summary.replace("Buy", effective, 1)
    return summary


def _fix_sterling_fcf_symbols(action_note: str, currency: str) -> str:
    if currency.upper() != "GBP" or not action_note:
        return action_note
    match = _FCF_BASIS_MISMATCH_SEGMENT.search(action_note)
    if not match:
        return action_note
    fixed = match.group(0).replace("$", "£")
    return action_note[: match.start()] + fixed + action_note[match.end() :]


def _resolve_fcf_bundle_for_export(
    snapshot: dict[str, Any],
    *,
    output_dir: Path | None,
) -> dict[str, Any]:
    ticker = str(snapshot.get("ticker") or "")
    fcf_raw = snapshot.get("fcf") if isinstance(snapshot.get("fcf"), dict) else {}
    fcf = fcf_bundle_from_persisted_report(
        fcf_raw or None,
        action_note=str(snapshot.get("action_note") or ""),
        key_metrics=snapshot.get("key_metrics")
        if isinstance(snapshot.get("key_metrics"), dict)
        else None,
    )
    screen_ttm = fcf.get("screen_ttm")
    if screen_ttm is None:
        screen_ttm = screen_ttm_from_row(pd.Series(snapshot))
    if ticker and screen_ttm is not None:
        reconciled = reconcile_fcf_for_ticker(
            ticker,
            screen_ttm=screen_ttm,
            output_dir=output_dir,
        )
        for key, value in reconciled.items():
            if value is not None:
                fcf[key] = value
    return fcf


def _apply_export_fcf_flags(snapshot: dict[str, Any], fcf_bundle: dict[str, Any]) -> None:
    ticker = str(snapshot.get("ticker") or "")
    currency = str(fcf_bundle.get("currency") or _ticker_reporting_currency(ticker))
    screen_ttm = fcf_bundle.get("screen_ttm")
    if screen_ttm is None:
        screen_ttm = screen_ttm_from_row(pd.Series(snapshot))

    note_mismatch = action_note_has_fcf_basis_mismatch(str(snapshot.get("action_note") or ""))
    prior_definition = snapshot.get("fcf_definition_divergence")
    if prior_definition is not None and not (
        isinstance(prior_definition, float) and pd.isna(prior_definition)
    ):
        definition = bool(prior_definition)
    else:
        definition = False
    definition = definition or fcf_basis_definition_divergence(
        operating_cashflow=snapshot.get("operating_cashflow"),
        operating_cashflow_gross=snapshot.get("operating_cashflow_gross"),
        filing_aligned=fcf_bundle.get("filing_aligned"),
        screen_ttm=screen_ttm,
        company_adjusted=fcf_bundle.get("company_adjusted"),
        filing_currency=currency,
        company_adjusted_currency=fcf_bundle.get("company_adjusted_currency"),
    )
    if note_mismatch or bool(fcf_bundle.get("fcf_definition_divergence")):
        definition = True

    divergence = bool(fcf_bundle.get("fcf_divergence_flagged"))
    if not divergence:
        divergence = fcf_action_note_mismatch(
            filing_aligned=fcf_bundle.get("filing_aligned"),
            screen_ttm=screen_ttm,
            company_adjusted=fcf_bundle.get("company_adjusted"),
            filing_currency=currency,
            company_adjusted_currency=fcf_bundle.get("company_adjusted_currency"),
            divergence_flagged=bool(fcf_bundle.get("divergence_flagged")),
            fcf_definition_divergence=definition,
        )

    snapshot["fcf_definition_divergence"] = definition
    snapshot["fcf_divergence_flagged"] = divergence
    fcf_bundle["fcf_definition_divergence"] = definition
    fcf_bundle["fcf_divergence_flagged"] = divergence
    snapshot["fcf"] = fcf_bundle


def guard_screening_snapshot_export(
    snapshot: dict[str, Any],
    *,
    model_results: pd.DataFrame | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Repair persisted screening rows before write (FCF flags, models, research headline)."""
    if not isinstance(snapshot, dict) or not snapshot.get("ticker"):
        return snapshot

    updated = dict(snapshot)
    ticker = str(updated["ticker"])
    fcf_bundle = _resolve_fcf_bundle_for_export(updated, output_dir=output_dir)
    _apply_export_fcf_flags(updated, fcf_bundle)

    failed = failed_models_from_results(model_results, ticker)
    if failed:
        updated["failed_models"] = failed
    elif not updated.get("failed_models"):
        updated["failed_models"] = []

    research_verdict = updated.get("research_verdict")
    screen_signal = str(updated.get("signal") or "hold")
    adjusted = updated.get("adjusted_signal")
    adjusted_str = (
        str(adjusted)
        if adjusted is not None and not (isinstance(adjusted, float) and pd.isna(adjusted))
        else None
    )
    if research_verdict and not adjusted_str:
        adjusted_str = compute_adjusted_signal(screen_signal, research_verdict)  # type: ignore[arg-type]
        updated["adjusted_signal"] = adjusted_str

    currency = str(fcf_bundle.get("currency") or _ticker_reporting_currency(ticker))
    research_risk = updated.get("research_risk_level")
    action_note = _fix_sterling_fcf_symbols(str(updated.get("action_note") or ""), currency)
    action_note = _dedupe_pipe_segments(action_note)
    action_note = _rewrite_action_note_headline(
        action_note,
        signal=screen_signal,
        research_verdict=str(research_verdict) if research_verdict else None,
        adjusted_signal=adjusted_str,
        research_risk_level=str(research_risk) if research_risk is not None else None,
    )
    updated["action_note"] = action_note
    updated["summary"] = _rewrite_summary_headline(
        updated.get("summary"),
        signal=screen_signal,
        research_verdict=str(research_verdict) if research_verdict else None,
        adjusted_signal=adjusted_str,
        research_risk_level=str(research_risk) if research_risk is not None else None,
    )

    from value_investor.scoring.fcf import append_fcf_divergence_to_action_note
    from value_investor.scoring.snapshot import enforce_fcf_basis_in_snapshot

    if not action_note_has_fcf_basis_mismatch(action_note):
        screen_ttm = fcf_bundle.get("screen_ttm") or screen_ttm_from_row(pd.Series(updated))
        canonical = fcf_bundle.get("canonical") or fcf_bundle.get("filing_aligned")
        enriched_note = append_fcf_divergence_to_action_note(
            action_note,
            canonical=canonical,
            screen_ttm=screen_ttm,
            fcf_bundle=fcf_bundle,
            fcf_definition_divergence=bool(updated.get("fcf_definition_divergence")),
        )
        if enriched_note != action_note:
            updated["action_note"] = enriched_note

    merged = enforce_fcf_basis_in_snapshot(updated, adjusted_signal=adjusted_str)
    merged = enrich_screening_snapshot_fcf_dividend_coverage(merged)

    overlay, merged_adjusted, conviction = apply_fcf_export_enforcement(
        signal=screen_signal,
        adjusted_signal=str(merged.get("adjusted_signal") or adjusted_str or screen_signal),
        conviction_score=float(merged.get("conviction_score") or 0.0),
        action_note=str(merged.get("action_note") or ""),
        fcf_basis_overlay=bool(merged.get("fcf_basis_overlay")),
        fcf_bundle=fcf_bundle if fcf_bundle else None,
        screen_ttm=fcf_bundle.get("screen_ttm"),
    )
    merged["fcf_basis_overlay"] = overlay
    merged["adjusted_signal"] = merged_adjusted
    merged["conviction_score"] = conviction
    return merged


def guard_signals_dataframe(
    signals: pd.DataFrame,
    model_results: pd.DataFrame,
    *,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    """Apply export guard row-wise before run snapshots and latest_signals.csv."""
    if signals.empty:
        return signals
    out = signals.copy()
    for optional_col in (
        "failed_models",
        "fcf_definition_divergence",
        "fcf_divergence_flagged",
    ):
        if optional_col not in out.columns:
            out[optional_col] = None
    for index, row in out.iterrows():
        guarded = guard_screening_snapshot_export(
            row.to_dict(),
            model_results=model_results,
            output_dir=output_dir,
        )
        for key, value in guarded.items():
            if key in out.columns or key in (
                "failed_models",
                "fcf_definition_divergence",
                "fcf_divergence_flagged",
            ):
                out.at[index, key] = value
    return out


def install_screening_export_guard_hooks() -> None:
    """Extend publish-time report enforcement with screening export guard."""
    try:
        import value_investor.summary as summary_mod
    except ImportError:
        return
    if getattr(summary_mod, "_screening_export_guard_installed", False):
        return
    original = summary_mod.export_enforced_report_dicts

    def _export_with_screening_guard(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
        enforced = original(reports)
        return [guard_screening_snapshot_export(row) for row in enforced]

    summary_mod.export_enforced_report_dicts = _export_with_screening_guard
    summary_mod._screening_export_guard_installed = True  # type: ignore[attr-defined]
