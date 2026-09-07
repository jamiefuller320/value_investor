"""Point-in-time near-miss watch from a library screen (observe-only)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from value_investor.library_screen import screen_dir_for
from value_investor.storage import write_json

NEAR_MISS_FILENAME = "near_miss_watch.json"
DEFAULT_PRE_BUY_CONVICTION = 0.28
BUY_TIER = frozenset({"buy", "strong_buy"})


def write_library_near_miss_watch(
    library_root: Path,
    market_id: str,
    *,
    min_conviction: float = DEFAULT_PRE_BUY_CONVICTION,
) -> dict[str, Any]:
    """Snapshot buy-tier-but-not-now and hold-near-buy names from latest_signals."""
    screen_dir = screen_dir_for(Path(library_root), market_id)
    signals_path = screen_dir / "latest_signals.csv"
    if not signals_path.exists():
        return {
            "skipped": True,
            "reason": "missing latest_signals.csv",
            "market_id": market_id,
        }
    frame = pd.read_csv(signals_path)
    if frame.empty or "ticker" not in frame.columns:
        return {
            "skipped": True,
            "reason": "empty signals",
            "market_id": market_id,
        }
    signal_col = "signal" if "signal" in frame.columns else None
    timing_col = "timing_signal" if "timing_signal" in frame.columns else None
    conv_col = "conviction_score" if "conviction_score" in frame.columns else None
    if conv_col is None and "composite_score" in frame.columns:
        conv_col = "composite_score"

    buy_not_now: list[dict[str, Any]] = []
    hold_near_buy: list[dict[str, Any]] = []
    for row in frame.to_dict(orient="records"):
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue
        signal = str(row.get(signal_col) or "").strip().lower() if signal_col else ""
        timing = str(row.get(timing_col) or "").strip().lower() if timing_col else ""
        try:
            conviction = float(row.get(conv_col) or 0.0) if conv_col else 0.0
        except (TypeError, ValueError):
            conviction = 0.0
        item = {
            "ticker": ticker,
            "signal": signal,
            "timing_signal": timing,
            "conviction_score": conviction,
        }
        if signal in BUY_TIER and timing == "wait":
            buy_not_now.append(item)
        elif signal == "hold" and conviction >= min_conviction:
            hold_near_buy.append(item)

    buy_not_now.sort(key=lambda r: r["conviction_score"], reverse=True)
    hold_near_buy.sort(key=lambda r: r["conviction_score"], reverse=True)
    payload = {
        "schema_version": 1,
        "scope": "library_near_miss_watch",
        "market_id": market_id,
        "observe_only": True,
        "generated_at": datetime.now(UTC).isoformat(),
        "min_conviction": min_conviction,
        "timing_signal_present": timing_col is not None,
        "buy_tier_not_now_count": len(buy_not_now),
        "hold_near_buy_count": len(hold_near_buy),
        "buy_tier_not_now": buy_not_now,
        "hold_near_buy": hold_near_buy,
        "note": (
            "Watch groups only — not an AI-judgment track. "
            "buy_tier_not_now is timing_signal=wait on buy/strong_buy; "
            "hold_near_buy is hold names at or above the pre-buy conviction floor. "
            "Library screen-lite often lacks timing_signal, so buy_tier_not_now "
            "stays empty until screens carry timing or a later Yahoo refresh."
        ),
    }
    path = screen_dir / NEAR_MISS_FILENAME
    write_json(path, payload, compact=False)
    payload["path"] = str(path)
    return payload


__all__ = ["NEAR_MISS_FILENAME", "write_library_near_miss_watch"]
