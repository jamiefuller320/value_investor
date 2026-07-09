"""Build GitHub Pages dashboard data from screening output artifacts."""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.deep_analysis import _parse_deep_analysis
from value_investor.summary import build_company_reports


def _read_json(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


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
    return re.sub(r"[^A-Za-z0-9._-]+", "_", ticker)


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
            meta = json.loads(metadata_path.read_text(encoding="utf-8"))

        index.append(
            {
                "ticker": ticker,
                "name": meta.get("name") or ticker,
                "version": meta.get("version"),
                "updated_at": meta.get("updated_at"),
                "executive_summary": meta.get("executive_summary") or "",
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
    deep_analysis = _load_deep_analysis(output_dir)

    signal_counts = _signal_counts(reports)
    strong_buy_count = signal_counts.get("strong_buy", 0)

    if run_at is None:
        summary_files = sorted(output_dir.glob("summary_*.json"))
        if summary_files:
            summary = _read_json(summary_files[-1])
            if isinstance(summary, dict):
                run_at = summary.get("run_at")

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "run_at": run_at,
        "meta": {
            "company_count": len(reports),
            "signal_counts": signal_counts,
            "strong_buy_count": strong_buy_count,
        },
        "reports": reports,
        "run_diff": run_diff,
        "backtest": backtest,
        "simulation": simulation,
        "deep_analysis": deep_analysis,
    }


def publish_dashboard(
    *,
    output_dir: Path,
    dest_dir: Path,
    include_research: bool = True,
) -> Path:
    """
    Write dashboard JSON (and optional research memos) under dest_dir.

    Static site assets (index.html, app.js, styles.css) live in dest_dir in git;
    this function updates data/ and research/ only.
    """
    bundle = build_dashboard_bundle(output_dir)
    if include_research:
        bundle["research"] = _copy_research_memos(output_dir, dest_dir)
    else:
        bundle["research"] = []

    data_dir = dest_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    latest_path = data_dir / "latest.json"
    latest_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")

    if run_at := bundle.get("run_at"):
        stamp = str(run_at)[:10]
        archive_path = data_dir / "archive" / f"{stamp}.json"
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")

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
        },
        "reports": [],
        "run_diff": None,
        "backtest": None,
        "simulation": None,
        "deep_analysis": None,
        "research": [],
        "note": "Dashboard data not published yet. Run ftse-screen and ftse-publish locally, or wait for the weekly workflow.",
    }
