"""Library screen-lite → latest.json-shaped bundle for market paper shards."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.library_screen import (
    LibraryScreenResult,
    library_research_reports,
    screen_dir_for,
)
from value_investor.library_sim import benchmark_for_market
from value_investor.research.market_store import resolve_research_documents
from value_investor.research.overlay import apply_research_overlay
from value_investor.storage import read_json, write_json
from value_investor.summary import CompanyReport


def _default_conviction(signals: pd.DataFrame) -> pd.DataFrame:
    if "conviction_score" in signals.columns:
        return signals
    out = signals.copy()
    if "composite_score" in out.columns:
        out["conviction_score"] = pd.to_numeric(out["composite_score"], errors="coerce").fillna(0.0)
    else:
        out["conviction_score"] = 0.0
    return out


def load_library_screen_result(
    library_root: Path,
    market_id: str,
) -> LibraryScreenResult:
    """Rebuild a screen result from committed latest_* CSV artifacts."""
    screen_dir = screen_dir_for(library_root, market_id)
    signals_path = screen_dir / "latest_signals.csv"
    models_path = screen_dir / "latest_model_results.csv"
    if not signals_path.exists() or not models_path.exists():
        raise FileNotFoundError(
            f"Missing screen-lite artifacts for {market_id} under {screen_dir.as_posix()}"
        )
    signals = _default_conviction(pd.read_csv(signals_path))
    model_results = pd.read_csv(models_path)
    summary_path = screen_dir / "latest_summary.json"
    run_at = datetime.now(UTC)
    summary: dict[str, Any] = {"market": market_id}
    if summary_path.exists():
        try:
            summary = read_json(summary_path)
            run_at = datetime.fromisoformat(str(summary.get("run_at") or run_at.isoformat()))
            if run_at.tzinfo is None:
                run_at = run_at.replace(tzinfo=UTC)
        except (OSError, ValueError, TypeError):
            pass
    shortlist_path = screen_dir / "latest_shortlist.csv"
    shortlist = pd.read_csv(shortlist_path) if shortlist_path.exists() else signals.iloc[0:0].copy()
    universe_cols = ["ticker", "last_price"] if "last_price" in signals.columns else ["ticker"]
    universe = (
        signals[universe_cols].copy()
        if "last_price" in signals.columns
        else signals[["ticker"]].copy()
    )
    return LibraryScreenResult(
        market=market_id,
        run_at=run_at,
        screen_dir=screen_dir,
        universe=universe,
        model_results=model_results,
        signals=signals,
        shortlist=shortlist,
        summary=summary,
    )


def build_market_reports_bundle(
    library_root: Path,
    market_id: str,
    *,
    screen_result: LibraryScreenResult | None = None,
) -> dict[str, Any]:
    """Produce a latest.json-shaped bundle for ftse-paper-auto --reports."""
    library_root = Path(library_root)
    result = screen_result or load_library_screen_result(library_root, market_id)
    reports = library_research_reports(result)
    documents = resolve_research_documents(
        market_id=market_id,
        output_dir=result.screen_dir,
        library_root=library_root,
    )
    if documents:
        reports = apply_research_overlay(reports, documents)

    from value_investor.library_ingest_exhaustion import learning_pool_excluded_tickers

    excluded = learning_pool_excluded_tickers(market_id, library_root=library_root)
    if excluded:
        reports = [row for row in reports if row.ticker not in excluded]

    signal_counts: dict[str, int] = {}
    if not result.signals.empty and "signal" in result.signals.columns:
        for key, value in result.signals["signal"].value_counts().to_dict().items():
            signal_counts[str(key)] = int(value)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "run_at": result.run_at.isoformat(),
        "meta": {
            "universe": market_id,
            "universe_label": market_id,
            "company_count": len(reports),
            "signal_counts": signal_counts,
            "shard": True,
            "benchmark_ticker": benchmark_for_market(market_id),
            "source": "library_screen_lite",
        },
        "reports": [report.to_dict() for report in reports],
    }


def write_market_screen_bundle(
    library_root: Path,
    market_id: str,
    shard_root: Path,
    *,
    screen_result: LibraryScreenResult | None = None,
    filename: str = "screen_latest.json",
) -> Path:
    bundle = build_market_reports_bundle(
        library_root,
        market_id,
        screen_result=screen_result,
    )
    shard_root = Path(shard_root)
    shard_root.mkdir(parents=True, exist_ok=True)
    path = shard_root / filename
    write_json(path, bundle, compact=False)
    return path


def reports_from_bundle(bundle: dict[str, Any]) -> list[CompanyReport]:
    from value_investor.summary import CompanyReport

    rows = bundle.get("reports") or []
    return [CompanyReport.from_dict(row) for row in rows if isinstance(row, dict)]
