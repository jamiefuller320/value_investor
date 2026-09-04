"""Build GitHub Pages dashboard data from screening output artifacts."""

from __future__ import annotations

import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.constituents import DEFAULT_UNIVERSE, universe_label
from value_investor.deep_analysis import _parse_deep_analysis
from value_investor.price_charts import (
    chart_filename,
    copy_charts_to_dashboard,
    ensure_buy_tier_charts,
    slug_ticker,
)
from value_investor.research.market_store import resolve_research_documents
from value_investor.research.overlay import apply_research_overlay
from value_investor.storage import (
    DASHBOARD_ARCHIVE_KEEP,
    prune_dashboard_archives,
    read_json,
    summarize_text,
    write_json,
)
from value_investor.summary import CompanyReport, build_company_reports
from value_investor.trust_summary import build_trust_reports

logger = logging.getLogger(__name__)

COMMITTED_PAPER_AUTOMATION = Path("docs/data/paper_automation")


def _resolve_paper_automation_dir(output_dir: Path) -> Path:
    """Prefer fresh output/paper_automation; fall back to committed docs/data artifacts."""
    candidates = (
        output_dir / "paper_automation",
        COMMITTED_PAPER_AUTOMATION,
    )
    for path in candidates:
        if (path / "learning_tracks_review.json").exists() or (path / "last_run.json").exists():
            return path
    return output_dir / "paper_automation"


def _read_paper_automation_json(output_dir: Path, name: str) -> dict[str, Any] | list[Any] | None:
    root = _resolve_paper_automation_dir(output_dir)
    return _read_json(root / name)


def _read_json(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    return read_json(path)


def _signal_counts(reports: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for report in reports:
        signal = str(report.get("signal") or "unknown")
        counts[signal] = counts.get(signal, 0) + 1
    return counts


def _load_reports(output_dir: Path) -> tuple[list[dict[str, Any]], str | None]:
    reports_path = output_dir / "email_reports.json"
    if reports_path.exists():
        data = _read_json(reports_path)
        if isinstance(data, list):
            run_at = None
            signals_path = output_dir / "latest_signals.csv"
            if signals_path.exists():
                signals = pd.read_csv(signals_path)
                if "run_at" in signals.columns and not signals.empty:
                    run_at = str(signals["run_at"].iloc[0])
            return data, run_at

    signals_path = output_dir / "latest_signals.csv"
    model_results_path = output_dir / "latest_model_results.csv"
    if not signals_path.exists() or not model_results_path.exists():
        return [], None

    signals = pd.read_csv(signals_path)
    model_results = pd.read_csv(model_results_path)
    reports = [report.to_dict() for report in build_company_reports(signals, model_results)]
    run_at = (
        str(signals["run_at"].iloc[0])
        if "run_at" in signals.columns and not signals.empty
        else None
    )
    return reports, run_at


def _load_trust_reports(output_dir: Path) -> list[dict[str, Any]]:
    reports_path = output_dir / "email_trust_reports.json"
    if reports_path.exists():
        data = _read_json(reports_path)
        if isinstance(data, list):
            return data

    signals_path = output_dir / "latest_trust_signals.csv"
    model_results_path = output_dir / "latest_trust_model_results.csv"
    if not signals_path.exists() or not model_results_path.exists():
        return []

    signals = pd.read_csv(signals_path)
    model_results = pd.read_csv(model_results_path)
    return [report.to_dict() for report in build_trust_reports(signals, model_results)]


def _load_deep_analysis(output_dir: Path) -> dict[str, str] | None:
    path = output_dir / "deep_analysis.txt"
    if not path.exists():
        return None
    parsed = _parse_deep_analysis(path.read_text(encoding="utf-8"))
    return {
        "executive_intro": parsed.executive_intro,
        "top_picks_analysis": parsed.top_picks_analysis,
        "red_flags": parsed.red_flags,
    }


def _load_post_run_review(output_dir: Path) -> dict[str, str] | None:
    path = output_dir / "post_run_review.md"
    if not path.exists():
        return None
    from value_investor.post_run_review import _parse_post_run_review

    parsed = _parse_post_run_review(path.read_text(encoding="utf-8"))
    return {
        "executive_summary": parsed.executive_summary,
        "persistent_weaknesses": parsed.persistent_weaknesses,
        "this_week_findings": parsed.this_week_findings,
        "improvement_plan": parsed.improvement_plan,
        "defer": parsed.defer,
        "full_text": parsed.full_text,
    }


def _slug_ticker(ticker: str) -> str:
    return slug_ticker(ticker)


def _load_research_documents(output_dir: Path) -> list[Any]:
    """Load ResearchDocument objects from output/research/*/research.json when present."""
    from value_investor.research.document import ResearchDocument

    research_root = output_dir / "research"
    if not research_root.exists():
        return []
    docs: list[Any] = []
    for path in sorted(research_root.glob("*/research.json")):
        try:
            payload = read_json(path)
            if isinstance(payload, dict):
                docs.append(ResearchDocument.from_dict(payload))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skipping research doc %s: %s", path, exc)
    return docs


def _research_index_entry(ticker: str, meta: dict[str, Any], memo_rel: str) -> dict[str, Any]:
    raw_summary = str(meta.get("executive_summary") or "")
    return {
        "ticker": ticker,
        "name": meta.get("name") or ticker,
        "version": meta.get("version"),
        "updated_at": meta.get("updated_at"),
        "executive_summary": summarize_text(raw_summary),
        "research_verdict": meta.get("research_verdict"),
        "research_risk_level": meta.get("research_risk_level"),
        "research_confidence": meta.get("research_confidence"),
        "risk_tags": meta.get("risk_tags") or [],
        "question_outcomes": meta.get("question_outcomes") or [],
        "source_counts": meta.get("source_counts"),
        "memo_quality": meta.get("memo_quality"),
        "memo_path": memo_rel,
    }


def _copy_research_memos(
    output_dir: Path,
    dest_dir: Path,
    *,
    tickers: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Copy this-run memos and merge any committed store the dest already holds."""
    memo_dir = dest_dir / "research"
    memo_dir.mkdir(parents=True, exist_ok=True)
    by_ticker: dict[str, dict[str, Any]] = {}
    wanted = {str(t).strip().upper() for t in (tickers or []) if str(t).strip()} or None

    summary_path = output_dir / "research_summary.json"
    summary_docs: dict[str, dict[str, Any]] = {}
    if summary_path.exists():
        summary_data = _read_json(summary_path)
        if isinstance(summary_data, dict):
            for item in summary_data.get("documents", []):
                if isinstance(item, dict) and item.get("ticker"):
                    summary_docs[str(item["ticker"])] = item

    def _ingest_root(
        research_root: Path,
        *,
        overwrite_markdown: bool,
        restrict: set[str] | None = None,
    ) -> None:
        if not research_root.is_dir():
            return
        for metadata_path in sorted(research_root.glob("*/research.json")):
            ticker = metadata_path.parent.name
            key = ticker.strip().upper()
            if not key:
                continue
            if restrict is not None and key not in restrict:
                continue
            if key in by_ticker:
                continue
            markdown_src = metadata_path.parent / "research.md"
            if not markdown_src.exists():
                continue
            slug = _slug_ticker(ticker)
            memo_dest = memo_dir / f"{slug}.md"
            if overwrite_markdown or not memo_dest.exists():
                shutil.copy2(markdown_src, memo_dest)
            meta = summary_docs.get(ticker) if overwrite_markdown else None
            if meta is None:
                meta = read_json(metadata_path)
            if not isinstance(meta, dict):
                continue
            by_ticker[key] = _research_index_entry(ticker, meta, f"research/{slug}.md")

    _ingest_root(output_dir / "research", overwrite_markdown=True, restrict=wanted)
    _ingest_root(dest_dir / "data" / "research", overwrite_markdown=False)

    index = list(by_ticker.values())
    index.sort(key=lambda item: str(item.get("name")))
    return index


def _apply_resolved_research_overlay(
    bundle: dict[str, Any],
    *,
    output_dir: Path,
    dest_dir: Path,
) -> None:
    """Stamp report overlay fields from the full resolved memo set."""
    raw_reports = bundle.get("reports")
    if not isinstance(raw_reports, list) or not raw_reports:
        return
    documents = resolve_research_documents(
        output_dir=output_dir,
        bundle=bundle,
        committed_dir=dest_dir / "data" / "research",
    )
    if not documents:
        return
    reports = [CompanyReport.from_dict(row) for row in raw_reports if isinstance(row, dict)]
    updated = apply_research_overlay(reports, documents)
    bundle["reports"] = [report.to_dict() for report in updated]


def build_dashboard_bundle(output_dir: Path) -> dict[str, Any]:
    """Assemble a single JSON payload for the static dashboard."""
    reports, run_at = _load_reports(output_dir)
    run_diff = _read_json(output_dir / "run_diff.json")
    backtest = _read_json(output_dir / "backtest_summary.json")
    simulation = _read_json(output_dir / "simulation_summary.json")
    historical_analysis = _read_json(output_dir / "historical_analysis_summary.json")
    deep_analysis = _load_deep_analysis(output_dir)
    gap_fill = _read_json(output_dir / "gap_fill_summary.json")
    ingest_improvement = _read_json(output_dir / "ingest_improvement_summary.json")
    engineering_tasks = _read_json(output_dir / "engineering_tasks.json")
    post_run_review = _load_post_run_review(output_dir)
    research_model_suggestions = _read_json(Path("docs/data/research_model_suggestions.json"))
    if research_model_suggestions is None:
        research_model_suggestions = _read_json(output_dir / "research_model_suggestions.json")
    paper_automation = _read_paper_automation_json(output_dir, "last_run.json")
    learning_tracks_review = _read_paper_automation_json(output_dir, "learning_tracks_review.json")
    learning_tracks_summary = _read_paper_automation_json(
        output_dir, "learning_tracks_summary.json"
    )
    churn_health = _read_paper_automation_json(output_dir, "learning_tracks_churn_health.json")
    buffered_hold_counterfactual = _read_paper_automation_json(
        output_dir, "buffered_hold_counterfactual.json"
    )
    knob_calibration_priors = _read_paper_automation_json(
        output_dir, "knob_calibration_priors.json"
    )
    calibration_shadow_endurance = _read_paper_automation_json(
        output_dir, "calibration_shadow_endurance.json"
    )
    from value_investor.experiment_assessment import slim_experiment_assessment_for_review

    experiment_assessment = slim_experiment_assessment_for_review(
        _read_json(output_dir / "experiment_assessment.json")
        or _read_json(Path("docs/data/experiment_assessment.json"))
    )
    learning_track_funds: dict[str, Any] = {}
    learning_track_configs: dict[str, Any] = {}
    try:
        from value_investor.knob_calibration import load_calibration_provenance
        from value_investor.paper_automation import learning_track_dirs

        paper_root = _resolve_paper_automation_dir(output_dir)
        for track_id, track_dir in learning_track_dirs(paper_root).items():
            cfg_payload = _read_json(track_dir / "config.json")
            if cfg_payload:
                provenance = load_calibration_provenance(track_dir)
                learning_track_configs[track_id] = {
                    "track_label": cfg_payload.get("track_label"),
                    "is_primary_learning_track": bool(cfg_payload.get("is_primary_learning_track")),
                    "is_calibration_shadow": bool(cfg_payload.get("is_calibration_shadow")),
                    "calibration_parent_track": cfg_payload.get("calibration_parent_track"),
                    "selection": {
                        "max_positions": cfg_payload.get("max_positions"),
                        "min_conviction": cfg_payload.get("min_conviction"),
                        "sector_cap": cfg_payload.get("sector_cap"),
                        "skip_timing_wait": cfg_payload.get("skip_timing_wait"),
                        "exit_confirm_screens": cfg_payload.get("exit_confirm_screens"),
                    },
                    "calibration_provenance": provenance,
                }
            fund_payload = _read_json(track_dir / "automated_fund.json")
            if fund_payload:
                curve = fund_payload.get("equity_curve") or []
                last_nav = None
                if curve:
                    last_pt = curve[-1]
                    if isinstance(last_pt, dict):
                        last_nav = last_pt.get("portfolio_value") or last_pt.get("nav")
                learning_track_funds[track_id] = {
                    "nav": last_nav,
                    "total_return": fund_payload.get("total_return"),
                    "equity_curve": curve[-24:],
                    "holdings_count": len(fund_payload.get("holdings") or {}),
                }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Learning track fund snapshot skipped: %s", exc)

    trust_reports = _load_trust_reports(output_dir)
    signal_counts = _signal_counts(reports)
    trust_signal_counts = _signal_counts(trust_reports)
    strong_buy_count = signal_counts.get("strong_buy", 0)
    universe_name = DEFAULT_UNIVERSE
    excluded_investment_vehicles = 0
    include_investment_trusts = False
    screen_trusts = True

    summary_files = sorted(output_dir.glob("summary_*.json")) + sorted(
        output_dir.glob("summary_*.json.gz")
    )
    if summary_files:
        summary = _read_json(summary_files[-1])
        if isinstance(summary, dict):
            if run_at is None:
                run_at = summary.get("run_at")
            if summary.get("universe"):
                universe_name = str(summary["universe"])
            excluded_investment_vehicles = int(summary.get("excluded_investment_vehicles") or 0)
            include_investment_trusts = bool(summary.get("include_investment_trusts"))
            if "screen_trusts" in summary:
                screen_trusts = bool(summary.get("screen_trusts"))

    for report in reports:
        if report.get("signal") in ("strong_buy", "buy") and report.get("ticker"):
            report["chart_path"] = f"data/charts/{chart_filename(str(report['ticker']))}"

    # Advisory Trading 212 tradability overlay (catalogue + allowlist fallback).
    try:
        from value_investor.t212_coverage import annotate_dashboard_reports

        reports = annotate_dashboard_reports(reports, market_id=universe_name)
        trust_reports = annotate_dashboard_reports(trust_reports, market_id=universe_name)
    except Exception as exc:  # noqa: BLE001 — dashboard must still publish
        logger.warning("T212 overlay annotation skipped: %s", exc)

    try:
        from value_investor.decision_pack import attach_decision_packs

        attach_decision_packs(reports, _load_research_documents(output_dir))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Decision-pack attachment skipped: %s", exc)

    try:
        from value_investor.unavailable_watch import load_unavailable_watch

        unavailable_watch = load_unavailable_watch()
    except Exception:  # noqa: BLE001
        unavailable_watch = {"items": []}

    try:
        from value_investor.human_tasks_checklist import load_human_tasks_checklist

        human_tasks_checklist = load_human_tasks_checklist()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Human tasks checklist skipped: %s", exc)
        human_tasks_checklist = None

    try:
        from value_investor.automation_status import (
            build_automation_status,
            build_learning_track_epoch_datum,
        )

        automation = build_automation_status()
        learning_track_epoch_datum = build_learning_track_epoch_datum(
            paper_root=output_dir / "paper_automation"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Automation status assembly skipped: %s", exc)
        automation = None
        learning_track_epoch_datum = None

    try:
        from value_investor.project_progress import build_project_progress

        project_progress = build_project_progress()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Project progress assembly skipped: %s", exc)
        project_progress = None

    try:
        from value_investor.market_status import build_market_status

        live_ingest_stalled = bool(
            ((project_progress or {}).get("ingest_bottleneck") or {}).get("stalled")
        )
        market_status = build_market_status(
            live_meta={
                "company_count": len(reports),
                "signal_counts": signal_counts,
                "universe": universe_name,
            },
            live_signal_counts=signal_counts,
            live_run_at=run_at,
            live_ingest_stalled=live_ingest_stalled,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Market status assembly skipped: %s", exc)
        market_status = None

    try:
        from value_investor.system_gap_analysis import (
            COMMITTED_GAPS_PATH,
            build_system_gap_snapshot,
            slim_system_gaps_for_dashboard,
        )

        committed_gaps = _read_json(COMMITTED_GAPS_PATH)
        if isinstance(committed_gaps, dict) and committed_gaps.get("flags") is not None:
            system_gaps = slim_system_gaps_for_dashboard(committed_gaps)
        else:
            system_gaps = slim_system_gaps_for_dashboard(
                build_system_gap_snapshot(output_dir=output_dir)
            )
    except Exception as exc:  # noqa: BLE001 — dashboard must still publish
        logger.warning("System gaps assembly skipped: %s", exc)
        system_gaps = None

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "run_at": run_at,
        "meta": {
            "company_count": len(reports),
            "signal_counts": signal_counts,
            "strong_buy_count": strong_buy_count,
            "universe": universe_name,
            "universe_label": universe_label(universe_name),
            "excluded_investment_vehicles": excluded_investment_vehicles,
            "include_investment_trusts": include_investment_trusts,
            "screen_trusts": screen_trusts,
            "trust_count": len(trust_reports),
            "trust_signal_counts": trust_signal_counts,
            "broker_overlay": "trading212",
            "t212_overlay": True,
            "ii_overlay": True,
            "unavailable_watch_count": len(unavailable_watch.get("items") or []),
        },
        "reports": reports,
        "unavailable_watch": unavailable_watch,
        "trust_reports": trust_reports,
        "run_diff": run_diff,
        "backtest": backtest,
        "simulation": simulation,
        "historical_analysis": historical_analysis,
        "deep_analysis": deep_analysis,
        "gap_fill": gap_fill,
        "ingest_improvement": ingest_improvement,
        "engineering_tasks": engineering_tasks,
        "post_run_review": post_run_review,
        "research_model_suggestions": research_model_suggestions,
        "paper_automation": paper_automation,
        "learning_tracks_review": learning_tracks_review,
        "learning_tracks_summary": learning_tracks_summary,
        "learning_track_funds": learning_track_funds,
        "learning_track_configs": learning_track_configs,
        "learning_track_epoch_datum": learning_track_epoch_datum,
        "churn_health": churn_health,
        "buffered_hold_counterfactual": buffered_hold_counterfactual,
        "knob_calibration_priors": knob_calibration_priors,
        "calibration_shadow_endurance": calibration_shadow_endurance,
        "experiment_assessment": experiment_assessment,
        "automation": automation,
        "project_progress": project_progress,
        "human_tasks_checklist": human_tasks_checklist,
        "market_status": market_status,
        "system_gaps": system_gaps,
    }


def publish_dashboard(
    *,
    output_dir: Path,
    dest_dir: Path,
    include_research: bool = True,
    archive_keep: int = DASHBOARD_ARCHIVE_KEEP,
) -> Path:
    """
    Write dashboard JSON (and optional research memos) under dest_dir.

    Static site assets (index.html, app.js, styles.css) live in dest_dir in git;
    this function updates data/ and research/ only.

    Dashboard archives keep only the newest ``archive_keep`` dated snapshots to
    limit git growth; full memos live under research/*.md.
    """
    bundle = build_dashboard_bundle(output_dir)
    if include_research:
        bundle["research"] = _copy_research_memos(output_dir, dest_dir)
        _apply_resolved_research_overlay(bundle, output_dir=output_dir, dest_dir=dest_dir)
    else:
        bundle["research"] = []

    data_dir = dest_dir / "data"
    try:
        from value_investor.experiment_assessment import slim_experiment_assessment_for_review
        from value_investor.sunday_review_dashboard import build_sunday_review_dashboard

        bundle["sunday_review"] = build_sunday_review_dashboard(
            data_dir,
            paper_root=_resolve_paper_automation_dir(output_dir),
            output_dir=output_dir,
            archive_dir=data_dir / "archive",
            run_at=bundle.get("run_at"),
            persist_history=True,
            refresh_experiments=True,
        )
        refreshed_assessment = _read_json(data_dir / "experiment_assessment.json")
        if refreshed_assessment:
            bundle["experiment_assessment"] = slim_experiment_assessment_for_review(
                refreshed_assessment
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Sunday review dashboard assembly skipped: %s", exc)

    data_dir.mkdir(parents=True, exist_ok=True)
    charts_dest = data_dir / "charts"
    charts_source = output_dir / "charts"
    buy_tickers = [
        str(report["ticker"])
        for report in bundle.get("reports", [])
        if report.get("signal") in ("strong_buy", "buy") and report.get("ticker")
    ]
    # Refresh missing charts from price history so popups work after publish.
    ensure_buy_tier_charts(
        reports=[r for r in bundle.get("reports", []) if r.get("signal") in ("strong_buy", "buy")],
        chart_dir=charts_source,
        fetch=True,
    )
    copy_charts_to_dashboard(
        source_dir=charts_source,
        dest_dir=charts_dest,
        tickers=buy_tickers or None,
    )
    # Drop stale chart files for names no longer in the buy tier.
    if charts_dest.exists() and buy_tickers:
        keep = {chart_filename(ticker) for ticker in buy_tickers}
        for stale in charts_dest.glob("*.json"):
            if stale.name not in keep:
                stale.unlink(missing_ok=True)

    try:
        from value_investor.chart_outcome_review import (
            run_chart_outcome_review,
            slim_chart_outcome_review,
        )

        chart_review = run_chart_outcome_review(data_dir=data_dir, chart_dir=charts_dest)
        bundle["chart_outcome_review"] = slim_chart_outcome_review(chart_review)
    except Exception as exc:  # noqa: BLE001 — dashboard must still publish
        logger.warning("Chart outcome review skipped: %s", exc)

    latest_path = data_dir / "latest.json"
    write_json(latest_path, bundle, compact=True, compress=False)

    # Standalone automation snapshot so ladder/paper workflows can refresh it
    # without a full screen republish.
    if bundle.get("automation"):
        write_json(data_dir / "automation.json", bundle["automation"], compact=False)

    if bundle.get("project_progress"):
        write_json(data_dir / "project_progress.json", bundle["project_progress"], compact=False)

    if bundle.get("market_status"):
        write_json(data_dir / "market_status.json", bundle["market_status"], compact=False)

    if run_at := bundle.get("run_at"):
        stamp = str(run_at)[:10]
        archive_path = data_dir / "archive" / f"{stamp}.json"
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(archive_path, bundle, compact=True, compress=False)
        prune_dashboard_archives(archive_path.parent, keep=archive_keep)

    return latest_path


def empty_dashboard_bundle() -> dict[str, Any]:
    """Placeholder bundle shown before the first CI publish."""
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "run_at": None,
        "meta": {
            "company_count": 0,
            "signal_counts": {},
            "strong_buy_count": 0,
            "universe": DEFAULT_UNIVERSE,
            "universe_label": universe_label(DEFAULT_UNIVERSE),
            "excluded_investment_vehicles": 0,
            "include_investment_trusts": False,
            "screen_trusts": True,
            "trust_count": 0,
            "trust_signal_counts": {},
            "broker_overlay": "trading212",
            "t212_overlay": False,
            "ii_overlay": False,
            "unavailable_watch_count": 0,
        },
        "reports": [],
        "unavailable_watch": {"items": []},
        "trust_reports": [],
        "run_diff": None,
        "backtest": None,
        "simulation": None,
        "historical_analysis": None,
        "deep_analysis": None,
        "post_run_review": None,
        "paper_automation": None,
        "automation": None,
        "project_progress": None,
        "market_status": None,
        "system_gaps": None,
        "research": [],
        "note": "Dashboard data not published yet. Run ftse-screen and ftse-publish locally, or wait for the weekly workflow.",
    }
