"""Screening snapshot persistence and research verdict propagation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.research.verdict import compute_adjusted_signal
from value_investor.scoring.fcf import (
    _float_or_none,
    advertising_revenue_share_for_ticker,
    enrich_screening_snapshot_fcf_dividend_coverage,
    resolve_statutory_fcf_dividend_coverage,
    screen_ttm_from_row,
)
from value_investor.scoring.fcf_basis_overlay import (
    apply_dividend_sustainability_export_enforcement,
    apply_fcf_export_enforcement,
    apply_media_cyclical_thin_fcf_export_enforcement,
)
from value_investor.scoring.healthcare_overlay import piotroski_score_for_ticker
from value_investor.storage import read_json, write_json

_RUN_SNAPSHOT_OPTIONAL_SIGNAL_COLUMNS = (
    "name",
    "sector",
    "timing_signal",
    "timing_score",
    "action_note",
    "models_passed",
    "weighted_model_score",
    "research_verdict",
    "adjusted_signal",
    "research_as_of",
    "research_confidence",
    "fcf_basis_overlay",
    "media_cyclical_thin_fcf_overlay",
    "advertising_revenue_share",
    "dividend_sustainability_overlay",
    "interim_dividend_cut_flagged",
    "interim_dividend_cut_pct",
    "interim_quality_overlay",
    "earnings_basis_overlay",
    "interim_eps_decline_pct",
    "adjusted_eps_growth_pct",
    "yahoo_normalized_income_growth_pct",
    "signal_trend",
    "weeks_at_signal",
    "passed_families",
    "price_vs_sma200_pct",
    "core_order",
    "core_limit",
    "core_allocation_pct",
    "tactical_limit",
    "tactical_allocation_pct",
    "tactical_stop_loss",
    "tactical_take_profit",
    "trade_plan_summary",
    "atr_14",
    "volume_ratio_20",
    "operating_cashflow",
    "operating_cashflow_gross",
    "fcf_dividend_coverage_gross",
    "fcf_dividend_coverage_net",
    "fcf_definition_divergence",
    "fcf_divergence_flagged",
    "fcf_dividend_coverage",
    "research_prompts",
)


def save_run_snapshot(
    output_dir: Path,
    *,
    run_at: datetime,
    signals: pd.DataFrame,
) -> Path:
    """Persist run history with labelled dual FCF coverage and divergence flags."""
    from value_investor.backtest import HISTORY_DIR, RunSnapshot, snapshot_prices

    history_dir = output_dir / HISTORY_DIR
    history_dir.mkdir(parents=True, exist_ok=True)

    tickers = signals["ticker"].tolist()
    prices = snapshot_prices(tickers)

    signal_cols = ["ticker", "signal", "conviction_score", "data_quality_score"]
    for optional in _RUN_SNAPSHOT_OPTIONAL_SIGNAL_COLUMNS:
        if optional in signals.columns:
            signal_cols.append(optional)

    snapshot = RunSnapshot(
        run_at=run_at.isoformat(),
        prices=prices,
        signals=signals[signal_cols].to_dict(orient="records"),
    )

    stamp = run_at.strftime("%Y%m%d_%H%M%S")
    path = history_dir / f"run_{stamp}.json"
    write_json(path, snapshot.to_dict(), compact=True, compress=True)
    return path


def enforce_fcf_basis_in_snapshot(
    snapshot: dict[str, Any],
    *,
    adjusted_signal: str | None = None,
    model_results: pd.DataFrame | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Cap buy-tier signals when FCF basis mismatch notes or flags require overlay."""
    updated = dict(snapshot)
    screen_signal = str(updated.get("signal") or "hold")
    base_adjusted = adjusted_signal or str(updated.get("adjusted_signal") or screen_signal)
    fcf = updated.get("fcf") if isinstance(updated.get("fcf"), dict) else {}
    screen_ttm = fcf.get("screen_ttm")
    if screen_ttm is None:
        screen_ttm = screen_ttm_from_row(pd.Series(updated))

    overlay, merged_adjusted, conviction = apply_fcf_export_enforcement(
        signal=screen_signal,
        adjusted_signal=base_adjusted,
        conviction_score=float(updated.get("conviction_score") or 0.0),
        action_note=str(updated.get("action_note") or ""),
        fcf_basis_overlay=bool(updated.get("fcf_basis_overlay")),
        fcf_bundle=fcf if fcf else None,
        screen_ttm=screen_ttm,
    )
    updated["adjusted_signal"] = merged_adjusted
    updated["fcf_basis_overlay"] = overlay
    updated["conviction_score"] = conviction

    piotroski = updated.get("piotroski_f_score")
    piotroski_f_score = (
        int(piotroski)
        if piotroski is not None and not (isinstance(piotroski, float) and pd.isna(piotroski))
        else None
    )
    if piotroski_f_score is None and model_results is not None and not model_results.empty:
        ticker = str(updated.get("ticker") or "")
        piotroski_f_score = piotroski_score_for_ticker(
            model_results[model_results["ticker"] == ticker]
        )

    ad_raw = updated.get("advertising_revenue_share")
    advertising_revenue_share = (
        float(ad_raw)
        if ad_raw is not None and not (isinstance(ad_raw, float) and pd.isna(ad_raw))
        else None
    )
    if advertising_revenue_share is None:
        ticker = str(updated.get("ticker") or "")
        if ticker:
            advertising_revenue_share = advertising_revenue_share_for_ticker(
                ticker,
                output_dir=output_dir,
            )
    statutory_cover = resolve_statutory_fcf_dividend_coverage(
        fcf_dividend_coverage_net=_float_or_none(updated.get("fcf_dividend_coverage_net")),
        operating_cashflow=_float_or_none(updated.get("operating_cashflow")),
        capital_expenditure=_float_or_none(updated.get("capital_expenditure")),
        dividends_paid=_float_or_none(updated.get("dividends_paid")),
        free_cashflow=_float_or_none(updated.get("free_cashflow")),
    )
    media_overlay, media_adjusted, media_conviction = (
        apply_media_cyclical_thin_fcf_export_enforcement(
            signal=screen_signal,
            adjusted_signal=str(updated.get("adjusted_signal") or merged_adjusted),
            conviction_score=float(updated.get("conviction_score") or 0.0),
            media_cyclical_thin_fcf_overlay=bool(updated.get("media_cyclical_thin_fcf_overlay")),
            advertising_revenue_share=advertising_revenue_share,
            piotroski_f_score=piotroski_f_score,
            statutory_fcf_dividend_coverage=statutory_cover,
        )
    )
    if media_overlay:
        updated["media_cyclical_thin_fcf_overlay"] = True
        updated["adjusted_signal"] = media_adjusted
        updated["conviction_score"] = media_conviction
        if advertising_revenue_share is not None:
            updated["advertising_revenue_share"] = advertising_revenue_share

    ticker = str(updated.get("ticker") or "")
    ticker_models = pd.DataFrame()
    if model_results is not None and not model_results.empty and ticker:
        ticker_models = model_results[model_results["ticker"] == ticker]

    div_overlay, cut_flagged, div_adjusted, div_conviction = (
        apply_dividend_sustainability_export_enforcement(
            signal=screen_signal,
            adjusted_signal=str(updated.get("adjusted_signal") or merged_adjusted),
            conviction_score=float(updated.get("conviction_score") or 0.0),
            dividend_sustainability_overlay=bool(updated.get("dividend_sustainability_overlay")),
            ticker_models=ticker_models,
            fcf_dividend_coverage_net=_float_or_none(updated.get("fcf_dividend_coverage_net")),
            operating_cashflow=_float_or_none(updated.get("operating_cashflow")),
            capital_expenditure=_float_or_none(updated.get("capital_expenditure")),
            dividends_paid=_float_or_none(updated.get("dividends_paid")),
            free_cashflow=_float_or_none(updated.get("free_cashflow")),
            interim_dividend_cut_pct=_float_or_none(updated.get("interim_dividend_cut_pct")),
        )
    )
    updated["interim_dividend_cut_flagged"] = cut_flagged
    if div_overlay:
        updated["dividend_sustainability_overlay"] = True
        updated["adjusted_signal"] = div_adjusted
        updated["conviction_score"] = div_conviction
    return updated


def merge_research_verdict_into_snapshot(
    snapshot: dict[str, Any],
    *,
    research_verdict: str | None,
    research_risk_level: str | None = None,
    research_confidence: float | None = None,
    research_rationale: str | None = None,
) -> dict[str, Any]:
    """Overlay structured research verdict fields onto a screening snapshot dict."""
    if not research_verdict:
        return enforce_fcf_basis_in_snapshot(snapshot)

    updated = dict(snapshot)
    updated["research_verdict"] = research_verdict
    if research_risk_level is not None:
        updated["research_risk_level"] = research_risk_level
    if research_confidence is not None:
        updated["research_confidence"] = research_confidence
    if research_rationale is not None:
        updated["research_rationale"] = research_rationale

    screen_signal = str(updated.get("signal") or "hold")
    research_adjusted = compute_adjusted_signal(screen_signal, research_verdict)  # type: ignore[arg-type]
    return enforce_fcf_basis_in_snapshot(updated, adjusted_signal=research_adjusted)


def write_screening_snapshot(sources_dir: Path, snapshot: dict[str, Any]) -> Path:
    from value_investor.scoring.screening_export_guard import guard_screening_snapshot_export

    sources_dir.mkdir(parents=True, exist_ok=True)
    path = sources_dir / "screening_snapshot.json"
    output_dir = _output_dir_from_sources_dir(sources_dir)
    payload = guard_screening_snapshot_export(
        snapshot,
        output_dir=output_dir,
    )
    payload = enforce_fcf_basis_in_snapshot(payload, output_dir=output_dir)
    payload = enrich_screening_snapshot_fcf_dividend_coverage(payload, output_dir=output_dir)
    write_json(
        path,
        payload,
        compact=True,
        compress=False,
    )
    return path


def _output_dir_from_sources_dir(sources_dir: Path) -> Path | None:
    path = Path(sources_dir)
    if path.name != "sources":
        return None
    research_dir = path.parent.parent
    if research_dir.name != "research":
        return None
    return research_dir.parent


def refresh_snapshot_from_document(output_dir: Path, doc: Any) -> bool:
    """Merge gap-fill verdict fields into an on-disk ``screening_snapshot.json``."""
    if not doc.research_verdict:
        return False

    snapshot_path = output_dir / "research" / doc.ticker / "sources" / "screening_snapshot.json"
    if not snapshot_path.exists():
        return False

    snapshot = read_json(snapshot_path)
    if not isinstance(snapshot, dict):
        return False

    merged = merge_research_verdict_into_snapshot(
        snapshot,
        research_verdict=doc.research_verdict,
        research_risk_level=doc.research_risk_level,
        research_confidence=doc.research_confidence,
        research_rationale=doc.research_rationale,
    )
    write_screening_snapshot(snapshot_path.parent, merged)
    return True


def sync_research_verdict_snapshots(
    output_dir: Path,
    reports: list[Any],
    documents: list[Any],
) -> int:
    """Write research overlay fields back to per-ticker screening snapshots."""
    by_ticker = {doc.ticker: doc for doc in documents if doc.research_verdict}
    if not by_ticker:
        return 0

    report_by_ticker = {report.ticker: report for report in reports}
    updated = 0
    for ticker, doc in by_ticker.items():
        report = report_by_ticker.get(ticker)
        sources_dir = output_dir / "research" / ticker / "sources"
        if report is not None:
            snapshot = merge_research_verdict_into_snapshot(
                report.to_dict(),
                research_verdict=doc.research_verdict,
                research_risk_level=doc.research_risk_level,
                research_confidence=doc.research_confidence,
                research_rationale=doc.research_rationale,
            )
            write_screening_snapshot(sources_dir, snapshot)
            updated += 1
        elif refresh_snapshot_from_document(output_dir, doc):
            updated += 1
    return updated
