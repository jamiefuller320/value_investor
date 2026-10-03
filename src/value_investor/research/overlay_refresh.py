"""Refresh research overlay fields on screen reports before paper automation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.buy_tier_flip_lag import _index_meta
from value_investor.research.document import ResearchDocument
from value_investor.research.market_store import resolve_research_documents
from value_investor.research.overlay import apply_research_overlay, enrich_signals_with_research
from value_investor.research.store import ResearchStore
from value_investor.storage import read_json, write_json
from value_investor.summary import CompanyReport, build_company_reports

logger = logging.getLogger(__name__)

# Keys paper-auto slim / marks still need that CompanyReport.to_dict() omits.
_PASSTHROUGH_KEYS = ("price", "last")


def _company_report_from_dict(data: dict[str, Any]) -> CompanyReport:
    """Rebuild a report from a published bundle row without dropping overlay fields."""
    return CompanyReport.from_dict(data)


def _overlay_bound(report: dict[str, Any]) -> bool:
    verdict = report.get("research_verdict")
    adjusted = report.get("adjusted_signal")
    return bool(str(verdict or "").strip()) and bool(str(adjusted or "").strip())


def stamp_p1_live_inputs(
    original: dict[str, Any],
    updated: dict[str, Any],
    *,
    research_root: Path | None,
) -> dict[str, Any]:
    """Join filing-index presence onto the live report the weekday pass reads.

    Observe-only: does not fetch bodies or rememo. Index meta is what is on disk
    at refresh time (decision-time *t*), not a later backfill into old log rows.
    """
    ticker = str(updated.get("ticker") or original.get("ticker") or "").strip().upper()
    if research_root is not None and ticker:
        meta = _index_meta(ticker, research_root=research_root)
        updated["has_index"] = bool(meta.get("has_index"))
        updated["filings_total"] = int(meta.get("filings_total") or 0)
        updated["filings_with_body"] = int(meta.get("filings_with_body") or 0)
        updated["key_filing_bodies"] = bool(meta.get("key_bodies"))
    else:
        for key in ("has_index", "filings_total", "filings_with_body", "key_filing_bodies"):
            if key in original and key not in updated:
                updated[key] = original[key]

    updated["overlay_bound"] = _overlay_bound(updated)
    if "fcf_basis_overlay" not in updated and "fcf_basis_overlay" in original:
        updated["fcf_basis_overlay"] = original.get("fcf_basis_overlay")

    for key in _PASSTHROUGH_KEYS:
        if updated.get(key) is None and original.get(key) is not None:
            updated[key] = original[key]
    return updated


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
    research_root = output_dir / "research"
    stamped: list[dict[str, Any]] = []
    for report in reports:
        payload = report.to_dict()
        stamped.append(
            stamp_p1_live_inputs(
                payload,
                payload,
                research_root=research_root if research_root.is_dir() else None,
            )
        )
    write_json(output_dir / "email_reports.json", stamped, compact=True)
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

    Uses ``CompanyReport.from_dict`` so Sunday filing-derived EPS / FCF / overlay
    flags survive the weekday rebuild instead of being zeroed.
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

    originals = [item for item in raw_reports if isinstance(item, dict)]
    reports = [_company_report_from_dict(item) for item in originals]
    updated = apply_research_overlay(reports, documents)
    research_root = resolved_committed if resolved_committed is not None else inferred
    stamped: list[dict[str, Any]] = []
    for original, report in zip(originals, updated, strict=False):
        payload = report.to_dict()
        stamped.append(
            stamp_p1_live_inputs(
                original,
                payload,
                research_root=research_root if Path(research_root).is_dir() else None,
            )
        )
    bundle["reports"] = stamped
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
