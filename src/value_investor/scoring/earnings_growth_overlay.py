"""Earnings-growth and Lynch PEG overlays from filing EPS with statutory fallback."""

from __future__ import annotations

from typing import Any

import pandas as pd

from value_investor.scoring.fcf import (
    compute_lynch_peg,
    earnings_growth_bps_diverge,
    resolve_model_earnings_growth,
    resolve_statutory_earnings_growth,
)


def _float_or_none(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return float(value)


def build_earnings_growth_overlay(row: pd.Series | dict[str, Any]) -> dict[str, Any]:
    """
    Compute Lynch PEG and earnings-growth overlay from filing EPS.

    Model growth prefers core/adjusted EPS where disclosed, then basic EPS, then
    screen TTM, then Yahoo statutory. Statutory growth prefers filing basic EPS
    with Yahoo fallback. Flags >300 bps divergence between the two bases.
    """
    if isinstance(row, dict):
        series = pd.Series(row)
    else:
        series = row

    statutory_growth = resolve_statutory_earnings_growth(series)
    adjusted_growth = _float_or_none(series.get("adjusted_eps_growth_pct"))
    model_growth = resolve_model_earnings_growth(series)
    trailing_pe = _float_or_none(series.get("trailing_pe"))

    core_growth = adjusted_growth if adjusted_growth is not None else model_growth
    bps_divergence = earnings_growth_bps_diverge(statutory_growth, core_growth)

    overlay: dict[str, Any] = {
        "statutory_earnings_growth_pct": statutory_growth,
        "model_earnings_growth_pct": model_growth,
        "adjusted_eps_growth_pct": adjusted_growth,
        "bps_divergence_warning": bps_divergence,
        "lynch_peg_statutory": compute_lynch_peg(trailing_pe, statutory_growth),
        "lynch_peg_model": compute_lynch_peg(trailing_pe, model_growth),
    }
    if bps_divergence and statutory_growth is not None and core_growth is not None:
        overlay["bps_divergence_pp"] = round(
            abs(float(statutory_growth) - float(core_growth)) * 100,
            1,
        )
    return overlay


def format_earnings_growth_bps_warning(overlay: dict[str, Any]) -> str | None:
    """Compact action-note fragment when statutory and core growth diverge >300 bps."""
    if not overlay.get("bps_divergence_warning"):
        return None
    statutory = overlay.get("statutory_earnings_growth_pct")
    model = overlay.get("model_earnings_growth_pct")
    if statutory is None or model is None:
        return "Earnings growth basis divergence >300 bps between statutory and filing core EPS"
    return (
        f"Earnings growth basis divergence >300 bps: statutory {statutory:.1%} vs "
        f"filing core {model:.1%}"
    )


def enrich_signals_with_earnings_growth_overlay(signals: pd.DataFrame) -> pd.DataFrame:
    """Add filing-based Lynch PEG and >300 bps earnings-growth warning columns."""
    if signals.empty:
        return signals

    out = signals.copy()
    warnings: list[bool] = []
    lynch_model: list[float | None] = []
    lynch_statutory: list[float | None] = []

    for _, row in out.iterrows():
        overlay = build_earnings_growth_overlay(row)
        warnings.append(bool(overlay.get("bps_divergence_warning")))
        lynch_model.append(overlay.get("lynch_peg_model"))
        lynch_statutory.append(overlay.get("lynch_peg_statutory"))

    out["earnings_growth_bps_divergence_warning"] = warnings
    out["lynch_peg_model"] = lynch_model
    out["lynch_peg_statutory"] = lynch_statutory
    return out
