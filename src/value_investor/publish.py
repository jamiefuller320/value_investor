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
from value_investor.storage import (
    DASHBOARD_ARCHIVE_KEEP,
    prune_dashboard_archives,
    read_json,
    summarize_text,
    write_json,
)
from value_investor.summary import build_company_reports
from value_investor.trust_summary import build_trust_reports

logger = logging.getLogger(__name__)


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
    run_at = str(signals["run_at"].iloc[0]) if "run_at" in signals.columns and not signals.empty else None
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


def _copy_research_memos(output_dir: Path, dest_dir: Path) -> list[dict[str, Any]]:
    research_root = output_dir / "research"
    if not research_root.exists():
        return []

    memo_dir = dest_dir / "research"
    memo_dir.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, Any]] = []

    summary_path = output_dir / "research_summary.json"
    summary_docs: dict[str, dict[str, Any]] = {}
    if summary_path.exists():
        summary_data = _read_json(summary_path)
        if isinstance(summary_data, dict):
            for item in summary_data.get("documents", []):
                if isinstance(item, dict) and item.get("ticker"):
                    summary_docs[str(item["ticker"])] = item

    for metadata_path in sorted(research_root.glob("*/research.json")):
        ticker = metadata_path.parent.name
        markdown_src = metadata_path.parent / "research.md"
        if not markdown_src.exists():
            continue

        slug = _slug_ticker(ticker)
        memo_dest = memo_dir / f"{slug}.md"
        shutil.copy2(markdown_src, memo_dest)

        meta = summary_docs.get(ticker)
        if meta is None:
            meta = read_json(metadata_path)

        raw_summary = str(meta.get("executive_summary") or "")
        index.append(
            {
                "ticker": ticker,
                "name": meta.get("name") or ticker,
                "version": meta.get("version"),
                "updated_at": meta.get("updated_at"),
                "executive_summary": summarize_text(raw_summary),
                "research_verdict": meta.get("research_verdict"),
                "research_risk_level": meta.get("research_risk_level"),
                "research_confidence": meta.get("research_confidence"),
                "memo_path": f"research/{slug}.md",
            }
        )

    index.sort(key=lambda item: str(item.get("name")))
    return index


def build_dashboard_bundle(output_dir: Path) -> dict[str, Any]:
    """Assemble a single JSON payload for the static dashboard."""
    reports, run_at = _load_reports(output_dir)
    run_diff = _read_json(output_dir / "run_diff.json")
    backtest = _read_json(output_dir / "backtest_summary.json")
    simulation = _read_json(output_dir / "simulation_summary.json")
    historical_analysis = _read_json(output_dir / "historical_analysis_summary.json")
    deep_analysis = _load_deep_analysis(output_dir)
    gap_fill = _read_json(output_dir / "gap_fill_summary.json")
    research_model_suggestions = _read_json(
        Path("docs/data/research_model_suggestions.json")
    )
    if research_model_suggestions is None:
        research_model_suggestions = _read_json(
            output_dir / "research_model_suggestions.json"
        )
    paper_automation = _read_json(output_dir / "paper_automation" / "last_run.json")

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

    # Advisory II tradability overlay (exchange allowlist / optional FIRDS MICs).
    try:
        from value_investor.ii_coverage import annotate_dashboard_reports

        reports = annotate_dashboard_reports(reports, market_id=universe_name)
        trust_reports = annotate_dashboard_reports(trust_reports, market_id=universe_name)
    except Exception as exc:  # noqa: BLE001 — dashboard must still publish
        logger.warning("II overlay annotation skipped: %s", exc)

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
        from value_investor.automation_status import build_automation_status

        automation = build_automation_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Automation status assembly skipped: %s", exc)
        automation = None

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
        "research_model_suggestions": research_model_suggestions,
        "paper_automation": paper_automation,
        "automation": automation,
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
    else:
        bundle["research"] = []

    data_dir = dest_dir / "data"
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

    latest_path = data_dir / "latest.json"
    write_json(latest_path, bundle, compact=True, compress=False)

    # Standalone automation snapshot so ladder/paper workflows can refresh it
    # without a full screen republish.
    if bundle.get("automation"):
        write_json(data_dir / "automation.json", bundle["automation"], compact=False)

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
        "paper_automation": None,
        "automation": None,
        "research": [],
        "note": "Dashboard data not published yet. Run ftse-screen and ftse-publish locally, or wait for the weekly workflow.",
    }
