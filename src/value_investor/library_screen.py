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
from value_investor.library_maintenance import prune_screen_dir
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

DEFAULT_MIN_METRICS_FOR_SCREEN = 25


def effective_min_metrics_for_screen(
    ticker_count: int,
    policy_min: int = DEFAULT_MIN_METRICS_FOR_SCREEN,
) -> int:
    """Tail markets smaller than the global floor screen when fully covered."""
    floor = max(1, int(policy_min))
    if ticker_count > 0:
        return min(floor, ticker_count)
    return floor


def _normalize_metrics_frame_tickers(frame: pd.DataFrame, market_id: str) -> pd.DataFrame:
    from value_investor.fetch import repair_mangled_yahoo_ticker

    if frame.empty or "ticker" not in frame.columns:
        return frame
    out = frame.copy()
    out["ticker"] = out["ticker"].map(
        lambda t: repair_mangled_yahoo_ticker(str(t or "")) if t else t
    )
    return out


def dedupe_library_metrics_frame(
    frame: pd.DataFrame,
    *,
    market_id: str,
    manifest_tickers: list[str] | None = None,
) -> pd.DataFrame:
    """
    Collapse legacy duplicate rows (e.g. ``A5G-IR.L`` vs ``A5G.IR``) to one row per manifest ticker.
    """
    if frame.empty:
        return frame
    normalized = _normalize_metrics_frame_tickers(frame, market_id)
    allowed = [str(t) for t in (manifest_tickers or [])]
    if allowed:
        allowed_set = set(allowed)
        normalized = normalized.loc[normalized["ticker"].isin(allowed_set)].copy()
    if normalized.empty:
        return normalized

    def _row_score(row: pd.Series) -> tuple[int, int]:
        payload = row.to_dict()
        fields = sum(
            1
            for key, value in payload.items()
            if key not in {"ticker", "name", "sector", "errors", "data_sources"}
            and value is not None
            and value != ""
        )
        usable = 1 if metrics_row_is_usable(payload) else 0
        return (usable, fields)

    best_rows: dict[str, pd.Series] = {}
    for _, row in normalized.iterrows():
        ticker = str(row.get("ticker") or "")
        if not ticker:
            continue
        existing = best_rows.get(ticker)
        if existing is None or _row_score(row) > _row_score(existing):
            best_rows[ticker] = row
    if not best_rows:
        return normalized.iloc[0:0].copy()
    order = allowed or sorted(best_rows)
    rows = [best_rows[t] for t in order if t in best_rows]
    return pd.DataFrame(rows).reset_index(drop=True)


def _screen_lite_gate_usable_rows(
    honest_usable: int,
    *,
    manifest_usable: int,
    ticker_count: int,
    policy_min: int = DEFAULT_MIN_METRICS_FOR_SCREEN,
) -> int:
    """
    Usable count for ladder gating.

    Fully covered tail markets (e.g. ISEQ 20) meet the global floor even when
    ``ticker_count < policy_min`` — ``run_library_screen`` still scores the
    honest universe size.
    """
    if (
        ticker_count > 0
        and manifest_usable >= ticker_count
        and honest_usable >= ticker_count
        and ticker_count < policy_min
    ):
        return policy_min
    return honest_usable


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


def _metrics_latest_path(root: Path, market_id: str) -> Path:
    path = market_dir(root, market_id) / "metrics" / "latest.json.gz"
    if not path.exists():
        alt = market_dir(root, market_id) / "metrics" / "latest.json"
        path = alt if alt.exists() else path
    return path


def _metric_value_present(value: Any) -> bool:
    if value is None:
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return True
    if number != number:
        return False
    return True


def metrics_row_is_usable(row: dict[str, Any]) -> bool:
    """Whether a metrics dict has enough fields for library screen-lite."""
    return any(
        _metric_value_present(row.get(key))
        for key in ("trailing_pe", "price_to_book", "market_cap")
    )


def _usable_metrics_mask(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=bool)
    if "errors" in frame.columns and (
        "trailing_pe" in frame.columns
        or "price_to_book" in frame.columns
        or "market_cap" in frame.columns
    ):
        return frame.apply(lambda row: metrics_row_is_usable(row.to_dict()), axis=1)
    return pd.Series([True] * len(frame), index=frame.index)


def assess_library_metrics_health(root: Path, market_id: str) -> dict[str, Any]:
    """
    Summarise raw vs usable metrics rows for ladder gating and engineering drafting.

    Usable rows match ``load_library_metrics`` — at least one of trailing_pe,
    price_to_book, or market_cap is present.
    """
    path = _metrics_latest_path(root, market_id)
    if not path.exists():
        return {
            "market": market_id,
            "metrics_path": str(path),
            "total_rows": 0,
            "usable_rows": 0,
            "honest_usable_rows": 0,
            "sample_tickers": [],
            "sample_errors": [],
        }
    rows = read_json(path)
    if not rows:
        return {
            "market": market_id,
            "metrics_path": str(path),
            "total_rows": 0,
            "usable_rows": 0,
            "honest_usable_rows": 0,
            "sample_tickers": [],
            "sample_errors": [],
        }
    from value_investor.data_library import load_manifest

    manifest = load_manifest(root, market_id)
    manifest_tickers = list(manifest.get("tickers") or [])
    ticker_count = int(manifest.get("ticker_count") or len(manifest_tickers))
    frame = dedupe_library_metrics_frame(
        pd.DataFrame(rows),
        market_id=market_id,
        manifest_tickers=manifest_tickers,
    )
    usable_mask = _usable_metrics_mask(frame)
    honest_usable = int(usable_mask.sum())
    manifest_usable = honest_usable
    if manifest_tickers and "ticker" in frame.columns:
        manifest_set = set(manifest_tickers)
        manifest_usable = int(frame.loc[frame["ticker"].isin(manifest_set) & usable_mask].shape[0])
    usable_rows = _screen_lite_gate_usable_rows(
        honest_usable,
        manifest_usable=manifest_usable,
        ticker_count=ticker_count,
    )
    failed = frame.loc[~usable_mask] if len(frame) else frame
    sample_tickers: list[str] = []
    sample_errors: list[str] = []
    ticker_col = "ticker" if "ticker" in frame.columns else None
    errors_col = "errors" if "errors" in frame.columns else None
    for _, row in failed.head(5).iterrows():
        if ticker_col:
            ticker = str(row.get(ticker_col) or "").strip().upper()
            if ticker:
                sample_tickers.append(ticker)
        if errors_col and row.get(errors_col):
            err = str(row.get(errors_col))
            if err and err not in sample_errors:
                sample_errors.append(err[:200])
    return {
        "market": market_id,
        "metrics_path": str(path),
        "total_rows": int(len(frame)),
        "usable_rows": usable_rows,
        "honest_usable_rows": honest_usable,
        "effective_min_metrics_for_screen": effective_min_metrics_for_screen(ticker_count),
        "sample_tickers": sample_tickers,
        "sample_errors": sample_errors[:5],
    }


def load_library_metrics(root: Path, market_id: str) -> pd.DataFrame:
    path = _metrics_latest_path(root, market_id)
    if not path.exists():
        raise FileNotFoundError(
            f"No metrics for {market_id} at {path}. Run: ftse-library grow --markets {market_id}"
        )
    rows = read_json(path)
    if not rows:
        return pd.DataFrame()
    from value_investor.data_library import load_manifest

    manifest = load_manifest(root, market_id)
    frame = dedupe_library_metrics_frame(
        pd.DataFrame(rows),
        market_id=market_id,
        manifest_tickers=list(manifest.get("tickers") or []),
    )
    usable_mask = _usable_metrics_mask(frame)
    if usable_mask.any():
        frame = frame.loc[usable_mask].copy()
    else:
        frame = frame.iloc[0:0].copy()
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
    sort_cols = [
        c
        for c in ("conviction_score", "composite_score", "data_quality_score")
        if c in shortlist.columns
    ]
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

    # Same decreasing-resolution retention as fundamentals PIT history.
    try:
        prune_screen_dir(screen_dir, now=run_at)
    except Exception as exc:  # noqa: BLE001 — retention must not fail the screen
        logger.warning("Screen retention prune failed for %s: %s", market_id, exc)

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
