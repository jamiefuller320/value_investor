"""Offline screen-lite over library metrics (no live FTSE path changes)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.data_library import market_dir
from value_investor.data_quality import add_data_quality_scores
from value_investor.model_weights import load_model_weights, save_model_snapshot
from value_investor.models.ranking import compute_derived_columns
from value_investor.scoring import evaluate_universe, summarize_by_ticker
from value_investor.sector_scoring import add_sector_scores
from value_investor.signal_stability import (
    append_signal_history,
    enrich_signals_with_stability,
    load_signal_history,
)
from value_investor.signals import build_signals
from value_investor.storage import read_json, write_json
from value_investor.summary import CompanyReport, build_company_reports

logger = logging.getLogger(__name__)


@dataclass
class LibraryScreenResult:
    market: str
    run_at: datetime
    screen_dir: Path
    universe: pd.DataFrame
    model_results: pd.DataFrame
    signals: pd.DataFrame
    shortlist: pd.DataFrame
    summary: dict[str, Any]


def load_library_metrics(root: Path, market_id: str) -> pd.DataFrame:
    path = market_dir(root, market_id) / "metrics" / "latest.json.gz"
    if not path.exists():
        # Allow uncompressed local tests
        alt = market_dir(root, market_id) / "metrics" / "latest.json"
        path = alt if alt.exists() else path
    if not path.exists():
        raise FileNotFoundError(
            f"No metrics for {market_id} at {path}. Run: ftse-library grow --markets {market_id}"
        )
    rows = read_json(path)
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    # Drop rows that failed fetch entirely (no usable fields)
    if "errors" in frame.columns and "trailing_pe" in frame.columns:
        usable = frame["trailing_pe"].notna() | frame.get("price_to_book", pd.Series(dtype=float)).notna()
        if "market_cap" in frame.columns:
            usable = usable | frame["market_cap"].notna()
        frame = frame.loc[usable].copy()
    return frame.reset_index(drop=True)


def screen_dir_for(root: Path, market_id: str) -> Path:
    return market_dir(root, market_id) / "screen"


def run_library_screen(
    root: Path,
    market_id: str,
    *,
    run_at: datetime | None = None,
) -> LibraryScreenResult:
    """
    Score library metrics with the same quant models/signals as the live screen,
    without Yahoo re-fetch, technicals, or trust track.
    """
    run_at = run_at or datetime.now(UTC)
    universe = load_library_metrics(root, market_id)
    if universe.empty:
        raise ValueError(f"Library metrics for {market_id} are empty — grow more tickers first")

    universe = compute_derived_columns(universe)
    # Fitted models expect these columns even when statement fields were sparse.
    for col in (
        "roic_proxy",
        "fcf_yield",
        "ev_ebitda",
        "ev_ebit",
        "earnings_yield_ebit",
        "earnings_yield_pe",
        "ncav_to_market",
        "asset_turnover",
        "total_assets",
        "total_current_liabilities",
        "ncav",
    ):
        if col not in universe.columns:
            universe[col] = pd.NA

    universe = add_data_quality_scores(universe)
    universe = add_sector_scores(universe)

    screen_dir = screen_dir_for(root, market_id)
    screen_dir.mkdir(parents=True, exist_ok=True)

    weight_state = load_model_weights(screen_dir)
    model_results = evaluate_universe(universe)
    summary = summarize_by_ticker(model_results, weights=weight_state.weights)
    signals = build_signals(universe, model_results, summary)

    history = load_signal_history(screen_dir)
    if history is not None and not history.empty:
        signals = enrich_signals_with_stability(signals, history, run_at=run_at)

    # Shortlist buy-tier for ladder layer C
    buy_mask = signals["signal"].isin(["strong_buy", "buy"])
    shortlist = signals.loc[buy_mask].copy()
    sort_cols = [c for c in ("conviction_score", "composite_score", "data_quality_score") if c in shortlist.columns]
    if sort_cols:
        shortlist = shortlist.sort_values(sort_cols, ascending=False)

    stamp = run_at.strftime("%Y%m%d_%H%M%S")
    universe.to_csv(screen_dir / f"universe_{stamp}.csv", index=False)
    universe.to_csv(screen_dir / "latest_universe.csv", index=False)
    model_results.to_csv(screen_dir / f"model_results_{stamp}.csv", index=False)
    model_results.to_csv(screen_dir / "latest_model_results.csv", index=False)
    signals.to_csv(screen_dir / f"signals_{stamp}.csv", index=False)
    signals.to_csv(screen_dir / "latest_signals.csv", index=False)
    shortlist.to_csv(screen_dir / "latest_shortlist.csv", index=False)

    save_model_snapshot(screen_dir, run_at=run_at, model_results=model_results)
    append_signal_history(screen_dir, signals, run_at=run_at)

    counts = signals["signal"].value_counts().to_dict() if not signals.empty else {}
    payload = {
        "market": market_id,
        "run_at": run_at.isoformat(),
        "ticker_count": int(len(universe)),
        "signal_counts": {str(k): int(v) for k, v in counts.items()},
        "shortlist_count": int(len(shortlist)),
        "strong_buy": int(counts.get("strong_buy", 0)),
        "buy": int(counts.get("buy", 0)),
        "paths": {
            "signals": "latest_signals.csv",
            "model_results": "latest_model_results.csv",
            "shortlist": "latest_shortlist.csv",
        },
        "note": "Screen-lite — offline library only; no technicals/backtest; not the live FTSE screen.",
    }
    write_json(screen_dir / f"summary_{stamp}.json", payload, compact=False)
    write_json(screen_dir / "latest_summary.json", payload, compact=False)

    return LibraryScreenResult(
        market=market_id,
        run_at=run_at,
        screen_dir=screen_dir,
        universe=universe,
        model_results=model_results,
        signals=signals,
        shortlist=shortlist,
        summary=payload,
    )


def library_research_reports(result: LibraryScreenResult) -> list[CompanyReport]:
    return build_company_reports(result.signals, result.model_results)


def research_cap_from_budget(
    *,
    remaining_usd: float,
    estimated_memo_usd: float = 0.40,
    hard_cap: int = 5,
    surplus: bool = False,
) -> int:
    """How many library research memos fit in remaining weekly budget."""
    if remaining_usd <= 0 and not surplus:
        return 0
    budget = remaining_usd if remaining_usd > 0 else estimated_memo_usd
    if surplus and remaining_usd <= 0:
        # Soft surplus: allow one memo to burn leftover first-party capacity
        budget = estimated_memo_usd
    unit = max(float(estimated_memo_usd), 0.01)
    # Avoid float quirks like 2.0 // 0.4 == 4.0
    cap = int((float(budget) + 1e-9) / unit)
    return max(0, min(hard_cap, cap))
