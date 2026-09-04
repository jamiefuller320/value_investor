"""Refresh research overlay fields on screen reports before paper automation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.research.document import ResearchDocument
from value_investor.research.market_store import resolve_research_documents
from value_investor.research.overlay import apply_research_overlay, enrich_signals_with_research
from value_investor.research.store import ResearchStore
from value_investor.storage import read_json, write_json
from value_investor.summary import CompanyReport, build_company_reports
from value_investor.technical_analysis import trade_plan_from_row

logger = logging.getLogger(__name__)


def _company_report_from_dict(data: dict[str, Any]) -> CompanyReport:
    row = pd.Series(data)
    trade_plan = trade_plan_from_row(row)
    composite = row.get("composite_score")
    sector_score = row.get("sector_composite_score")
    rsi = row.get("rsi_14")
    vs_sma = row.get("price_vs_sma200_pct")
    research_conf = row.get("research_confidence")

    return CompanyReport(
        ticker=str(data["ticker"]),
        name=str(data.get("name") or data["ticker"]),
        sector=data.get("sector"),
        signal=str(data.get("signal") or "hold"),
        models_passed=int(data.get("models_passed") or 0),
        model_count=int(data.get("model_count") or 0),
        composite_score=float(composite)
        if composite is not None and not pd.isna(composite)
        else None,
        sector_composite_score=(
            float(sector_score) if sector_score is not None and not pd.isna(sector_score) else None
        ),
        families_passed=int(data.get("families_passed") or 0),
        passed_families=data.get("passed_families"),
        family_count=int(data.get("family_count") or 5),
        data_quality_score=float(data.get("data_quality_score") or 0),
        metrics_present=int(data.get("metrics_present") or 0),
        metrics_total=int(data.get("metrics_total") or 20),
        weeks_at_signal=int(data.get("weeks_at_signal") or 1),
        signal_trend=str(data.get("signal_trend") or "new"),
        conviction_score=float(data.get("conviction_score") or 0),
        stability_label=str(data.get("stability_label") or "new"),
        signal_since=data.get("signal_since"),
        timing_signal=str(data.get("timing_signal") or "insufficient_data"),
        timing_score=float(data.get("timing_score") or 0),
        rsi_14=float(rsi) if rsi is not None and not pd.isna(rsi) else None,
        price_vs_sma200_pct=float(vs_sma) if vs_sma is not None and not pd.isna(vs_sma) else None,
        action_note=str(data.get("action_note") or ""),
        trade_plan=trade_plan,
        summary=str(data.get("summary") or ""),
        passed_models=list(data.get("passed_models") or []),
        key_metrics=dict(data.get("key_metrics") or {}),
        adjusted_signal=data.get("adjusted_signal"),
        fcf_basis_overlay=bool(data.get("fcf_basis_overlay")),
        research_verdict=data.get("research_verdict"),
        research_risk_level=data.get("research_risk_level"),
        research_confidence=(
            float(research_conf)
            if research_conf is not None
            and not (isinstance(research_conf, float) and pd.isna(research_conf))
            else None
        ),
        research_rationale=data.get("research_rationale"),
    )


def _load_research_documents(
    output_dir: Path,
    bundle: dict[str, Any],
    *,
    committed_dir: Path | None = None,
) -> list[ResearchDocument]:
    return resolve_research_documents(
        output_dir=output_dir,
        bundle=bundle,
        committed_dir=committed_dir,
    )


def refresh_research_overlay(output_dir: Path) -> int:
    """
    Re-apply research fields to ``output/latest_signals.csv`` and ``email_reports.json``.

    Used locally when ``output/`` screen artifacts exist (post ``ftse-screen``).
    """
    output_dir = Path(output_dir)
    signals_path = output_dir / "latest_signals.csv"
    models_path = output_dir / "latest_model_results.csv"
    if not signals_path.exists() or not models_path.exists():
        raise FileNotFoundError(f"Missing screen outputs under {output_dir}")

    signals = pd.read_csv(signals_path)
    signals = enrich_signals_with_research(signals, output_dir)
    signals.to_csv(signals_path, index=False)

    model_results = pd.read_csv(models_path)
    reports = build_company_reports(signals, model_results)
    documents = ResearchStore(output_dir).list_documents()
    reports = apply_research_overlay(reports, documents)
    write_json(output_dir / "email_reports.json", [r.to_dict() for r in reports], compact=True)
    return len(documents)


def refresh_dashboard_bundle(
    bundle_path: Path,
    *,
    output_dir: Path | None = None,
    committed_dir: Path | None = None,
) -> int:
    """
    Re-apply memo verdicts to ``reports`` inside a published dashboard bundle.

    Unions this-run ``output/research``, the committed FTSE store
    (``docs/data/research/``), and the bundle ``research[]`` index so weekday
    paper-auto sees every written memo, not only the last publish snapshot.
    """
    bundle_path = Path(bundle_path)
    bundle = read_json(bundle_path)
    if not isinstance(bundle, dict):
        raise ValueError(f"Expected object JSON at {bundle_path}")

    raw_reports = bundle.get("reports")
    if not isinstance(raw_reports, list) or not raw_reports:
        logger.warning("No reports in dashboard bundle — skipping overlay refresh")
        return 0

    output_dir = Path(output_dir or Path("output"))
    inferred = bundle_path.parent / "research"
    resolved_committed = committed_dir
    if resolved_committed is None and inferred.is_dir():
        resolved_committed = inferred
    documents = _load_research_documents(output_dir, bundle, committed_dir=resolved_committed)
    if not documents:
        logger.warning("No research documents available — skipping overlay refresh")
        return 0

    reports = [_company_report_from_dict(item) for item in raw_reports if isinstance(item, dict)]
    updated = apply_research_overlay(reports, documents)
    bundle["reports"] = [report.to_dict() for report in updated]
    write_json(bundle_path, bundle, compact=True)
    return len(documents)


def refresh_paper_auto_reports(
    *,
    bundle_path: Path = Path("docs/data/latest.json"),
    output_dir: Path = Path("output"),
) -> Path:
    """
    Refresh research overlay for weekday paper automation.

    Updates the dashboard bundle when present; also writes ``email_reports.json``
    under ``output_dir`` when screen CSVs exist.
    """
    bundle_path = Path(bundle_path)
    output_dir = Path(output_dir)

    doc_count = 0
    if bundle_path.exists():
        doc_count = refresh_dashboard_bundle(bundle_path, output_dir=output_dir)

    signals_path = output_dir / "latest_signals.csv"
    if signals_path.exists():
        doc_count = max(doc_count, refresh_research_overlay(output_dir))

    return bundle_path if bundle_path.exists() else output_dir / "email_reports.json"
