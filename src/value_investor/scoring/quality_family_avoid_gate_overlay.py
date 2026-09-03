"""Observe-only quality-family composite gate for the avoid cohort.

Simulates requiring quality family pass before any screen upgrade above avoid
for loser-card patterns (AAL.L / AML.L). Does not mutate live ``assign_signal()``
thresholds or ``adjusted_signal`` — exports parallel observe-only fields only.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from value_investor.model_families import MODEL_FAMILIES
from value_investor.scoring.interim_quality_overlay import quality_family_passed

AVOID_SIGNAL = "avoid"
OPINION_FLIP_CONVICTION = 0.35

QUALITY_MODEL_IDS = frozenset(MODEL_FAMILIES["quality"])
ALL_FAMILIES = tuple(MODEL_FAMILIES.keys())

# Archive prior from loser_snapshot_cards (ldr-20260901-03 / ana-20260903-02).
ARCHIVE_AVOID_QUALITY_FAIL_COUNT = 37
ARCHIVE_LOSER_CARD_COUNT = 53


def _parse_families(passed_families: str | None) -> set[str]:
    if not passed_families:
        return set()
    return {part.strip().lower() for part in str(passed_families).split(",") if part.strip()}


def failed_family_names(passed_families: str | None) -> list[str]:
    """Families that did not pass for one ticker."""
    passed = _parse_families(passed_families)
    return [name for name in ALL_FAMILIES if name not in passed]


def quality_family_failed(passed_families: str | None) -> bool:
    """True when the quality model family did not pass."""
    return not quality_family_passed(passed_families)


def compute_quality_family_composite_score(
    model_results: pd.DataFrame,
    *,
    ticker: str,
) -> float | None:
    """Mean score across quality-family models for one ticker."""
    if model_results.empty or "model_id" not in model_results.columns:
        return None

    ticker_rows = model_results[
        (model_results["ticker"] == ticker) & (model_results["model_id"].isin(QUALITY_MODEL_IDS))
    ]
    if ticker_rows.empty:
        return None

    scores = ticker_rows["score"].dropna()
    if scores.empty:
        return None
    return round(float(scores.mean()), 4)


def _float_or_none(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return float(value)


def build_quality_family_avoid_gate_overlay(
    row: pd.Series | dict[str, Any],
    *,
    quality_composite_score: float | None = None,
) -> dict[str, Any]:
    """Build observe-only quality-family avoid gate payload for one ticker."""
    if isinstance(row, dict):
        series = pd.Series(row)
    else:
        series = row

    signal = str(series.get("signal") or "hold").strip().lower()
    passed_families = series.get("passed_families")
    conviction = _float_or_none(series.get("conviction_score")) or 0.0
    co_failed = failed_family_names(str(passed_families) if passed_families is not None else None)

    overlay: dict[str, Any] = {
        "observe_only": True,
        "quality_family_avoid_gate": False,
        "quality_family_composite_score": quality_composite_score,
        "quality_family_failed": quality_family_failed(
            str(passed_families) if passed_families is not None else None
        ),
        "quality_family_avoid_gate_action": None,
        "quality_family_avoid_gate_observe_signal": None,
        "quality_family_avoid_gate_would_block_upgrade": False,
        "co_failed_families": co_failed,
        "archive_avoid_quality_fail_count": ARCHIVE_AVOID_QUALITY_FAIL_COUNT,
        "archive_loser_card_count": ARCHIVE_LOSER_CARD_COUNT,
    }

    if signal != AVOID_SIGNAL or not overlay["quality_family_failed"]:
        return overlay

    would_block = conviction >= OPINION_FLIP_CONVICTION
    action = "block_upgrade" if would_block else "cohort_watch"

    overlay["quality_family_avoid_gate"] = True
    overlay["quality_family_avoid_gate_action"] = action
    overlay["quality_family_avoid_gate_observe_signal"] = AVOID_SIGNAL
    overlay["quality_family_avoid_gate_would_block_upgrade"] = would_block
    return overlay


def format_quality_family_avoid_gate_note(overlay: dict[str, Any]) -> str | None:
    """Compact summary fragment when the observe-only gate fires."""
    if not overlay.get("quality_family_avoid_gate"):
        return None

    composite = overlay.get("quality_family_composite_score")
    composite_text = f"composite {composite:.0%}" if composite is not None else "composite n/a"
    co_failed = overlay.get("co_failed_families") or []
    co_text = f", co-failed {','.join(co_failed)}" if co_failed else ""

    if overlay.get("quality_family_avoid_gate_would_block_upgrade"):
        return (
            "Quality-family avoid gate (observe-only): would block upgrade above avoid "
            f"({composite_text}{co_text})."
        )

    return (
        "Quality-family avoid gate (observe-only): avoid cohort with quality failure "
        f"({composite_text}{co_text})."
    )


def enrich_signals_with_quality_family_avoid_gate(
    signals: pd.DataFrame,
    model_results: pd.DataFrame,
) -> pd.DataFrame:
    """Attach observe-only quality-family avoid gate columns."""
    if signals.empty:
        return signals

    out = signals.copy()
    overlays: list[dict[str, Any]] = []
    for _, row in out.iterrows():
        ticker = str(row["ticker"])
        composite = compute_quality_family_composite_score(model_results, ticker=ticker)
        overlays.append(
            build_quality_family_avoid_gate_overlay(row, quality_composite_score=composite)
        )

    out["quality_family_failed"] = [bool(item["quality_family_failed"]) for item in overlays]
    out["quality_family_composite_score"] = [
        item.get("quality_family_composite_score") for item in overlays
    ]
    out["quality_family_avoid_gate"] = [
        bool(item["quality_family_avoid_gate"]) for item in overlays
    ]
    out["quality_family_avoid_gate_action"] = [
        item.get("quality_family_avoid_gate_action") for item in overlays
    ]
    out["quality_family_avoid_gate_observe_signal"] = [
        item.get("quality_family_avoid_gate_observe_signal") for item in overlays
    ]
    out["quality_family_avoid_gate_would_block_upgrade"] = [
        bool(item["quality_family_avoid_gate_would_block_upgrade"]) for item in overlays
    ]
    out["co_failed_families"] = [
        ",".join(item.get("co_failed_families") or []) for item in overlays
    ]
    return out
