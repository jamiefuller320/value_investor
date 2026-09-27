"""Dual-suite learning-track scoreboard for dashboard publish (observe / presentation).

Suite A = live 3% stress books (churn / defensive lab).
Suite B = fair T212 twins + cohort labs (adoption truth for excess vs ^FTSE).

Does **not** flip ``is_primary_learning_track``, rewrite capital books, or promote
on stress excess alone (N145 / primary-learning-track.md).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from value_investor.fair_cost_lab import (
    AI_JUDGMENT_FAIR_TRACK_ID,
    RULES_FAIR_TRACK_ID,
    is_cohort_lab_track_id,
    is_fair_cost_lab_track_id,
    is_suite_b_track_id,
)
from value_investor.market_trading_costs import (
    LIVE_PAPER_MARKET_ID,
    assess_paper_tracks_under_fair_costs,
)
from value_investor.paper_automation import AI_JUDGMENT_TRACK_ID, RULES_TRACK_ID

SCHEMA_VERSION = 1

# Presentation contract (dashboard / humans) — not a learning-book rewrite.
SUCCESS_DEFINITION_FAIR_ADOPTION = "fair_ai_excess_vs_ftse_and_rules_control"
STRESS_LAB_ROLE = "churn_defensive_lab"
FAIR_LAB_ROLE = "adoption_truth"

SUITE_A_CORE_ORDER: tuple[str, ...] = (
    "technical",
    RULES_TRACK_ID,
    AI_JUDGMENT_TRACK_ID,
    "momentum_grace",
)
SUITE_B_CORE_ORDER: tuple[str, ...] = (
    AI_JUDGMENT_FAIR_TRACK_ID,
    RULES_FAIR_TRACK_ID,
    "buy_tier_level",
    "buy_tier_level_dca",
)


def _metrics(row: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    metrics = row.get("metrics")
    return metrics if isinstance(metrics, dict) else {}


def _track_row_summary(track_id: str, row: dict[str, Any] | None) -> dict[str, Any]:
    metrics = _metrics(row)
    epoch = metrics.get("epoch") if isinstance(metrics.get("epoch"), dict) else {}
    return {
        "track_id": track_id,
        "excess_after_costs": metrics.get("excess_after_costs"),
        "total_return": metrics.get("total_return"),
        "cost_drag": metrics.get("cost_drag"),
        "trade_count": metrics.get("trade_count"),
        "positions": metrics.get("positions"),
        "portfolio_value": metrics.get("portfolio_value"),
        "epoch_excess_after_costs": epoch.get("excess_after_costs"),
        "epoch_total_return": epoch.get("total_return"),
        "is_primary_learning_track": bool((row or {}).get("is_primary_learning_track")),
        "beat_market": (row or {}).get("beat_market"),
        "beat_control": (row or {}).get("beat_control"),
    }


def classify_suite(
    track_id: str,
    *,
    track_configs: dict[str, Any] | None = None,
) -> str:
    """Return ``A``, ``B``, or ``other`` for presentation grouping."""
    tid = str(track_id or "").strip()
    cfg = (track_configs or {}).get(tid) if isinstance(track_configs, dict) else None
    if isinstance(cfg, dict):
        if cfg.get("is_fair_cost_lab") or cfg.get("is_suite_b") or cfg.get("is_cohort_lab"):
            return "B"
    if is_suite_b_track_id(tid):
        return "B"
    if is_fair_cost_lab_track_id(tid) or is_cohort_lab_track_id(tid):
        return "B"
    return "A"


def _ordered_ids(preferred: tuple[str, ...], available: list[str]) -> list[str]:
    ordered: list[str] = []
    for tid in preferred:
        if tid in available and tid not in ordered:
            ordered.append(tid)
    for tid in available:
        if tid not in ordered:
            ordered.append(tid)
    return ordered


def _slim_fair_assess(
    paper_root: Path | None,
    *,
    market_id: str,
    track_ids: list[str],
) -> dict[str, Any] | None:
    """Read-only fair friction recompute for Suite A books (does not rebuild excess)."""
    if paper_root is None or not track_ids:
        return None
    root = Path(paper_root)
    if not root.is_dir():
        return None
    try:
        payload = assess_paper_tracks_under_fair_costs(
            root,
            market_id=market_id,
            track_ids=track_ids,
        )
    except Exception:  # noqa: BLE001 — dashboard publish must stay resilient
        return None
    tracks_out: dict[str, Any] = {}
    for tid, row in (payload.get("tracks") or {}).items():
        if not isinstance(row, dict) or not row.get("ok"):
            continue
        tracks_out[tid] = {
            "recorded_costs": row.get("recorded_costs"),
            "fair_costs": row.get("fair_costs"),
            "recorded_cost_drag": row.get("recorded_cost_drag"),
            "fair_cost_drag": row.get("fair_cost_drag"),
            "cost_drag_relief": row.get("cost_drag_relief"),
            "trade_count": row.get("trade_count"),
            "note": (
                "Friction recompute only — does not rebuild fills or excess vs ^FTSE. "
                "Adoption truth stays on Suite B fair twin books."
            ),
        }
    if not tracks_out:
        return None
    return {
        "market_id": payload.get("market_id") or market_id,
        "assumptions": payload.get("assumptions"),
        "tracks": tracks_out,
        "note": payload.get("note"),
    }


def build_learning_tracks_dual_suite(
    learning_tracks_review: dict[str, Any] | None,
    *,
    track_configs: dict[str, Any] | None = None,
    paper_root: Path | None = None,
    market_id: str = LIVE_PAPER_MARKET_ID,
    include_fair_assess: bool = True,
) -> dict[str, Any] | None:
    """
    Slim dual-suite scoreboard for dashboard / publish JSON.

    Presentation-only: never mutates configs or primary flags.
    """
    if not isinstance(learning_tracks_review, dict):
        return None
    reviews = learning_tracks_review.get("reviews")
    if not isinstance(reviews, dict) or not reviews:
        return None

    suite_a_ids: list[str] = []
    suite_b_ids: list[str] = []
    for tid in reviews:
        bucket = classify_suite(str(tid), track_configs=track_configs)
        if bucket == "B":
            suite_b_ids.append(str(tid))
        else:
            suite_a_ids.append(str(tid))

    suite_a_ids = _ordered_ids(SUITE_A_CORE_ORDER, suite_a_ids)
    suite_b_ids = _ordered_ids(SUITE_B_CORE_ORDER, suite_b_ids)

    primary_id = str(learning_tracks_review.get("primary_learning_track") or AI_JUDGMENT_TRACK_ID)
    fair_ai = reviews.get(AI_JUDGMENT_FAIR_TRACK_ID)
    fair_rules = reviews.get(RULES_FAIR_TRACK_ID)
    fair_ai_metrics = _metrics(fair_ai if isinstance(fair_ai, dict) else None)
    fair_rules_metrics = _metrics(fair_rules if isinstance(fair_rules, dict) else None)
    fair_ai_excess = fair_ai_metrics.get("excess_after_costs")
    fair_rules_excess = fair_rules_metrics.get("excess_after_costs")
    fair_beat_market = (
        bool(fair_ai_excess is not None and float(fair_ai_excess) > 0)
        if fair_ai_excess is not None
        else None
    )
    fair_beat_control = None
    if fair_ai_excess is not None and fair_rules_excess is not None:
        fair_beat_control = float(fair_ai_excess) > float(fair_rules_excess)

    stress_ai = reviews.get(AI_JUDGMENT_TRACK_ID) or reviews.get(primary_id)
    stress_metrics = _metrics(stress_ai if isinstance(stress_ai, dict) else None)

    assess = None
    if include_fair_assess:
        assess_ids = [
            tid
            for tid in (AI_JUDGMENT_TRACK_ID, RULES_TRACK_ID)
            if tid in reviews and classify_suite(tid, track_configs=track_configs) == "A"
        ]
        assess = _slim_fair_assess(paper_root, market_id=market_id, track_ids=assess_ids)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "success_definition": SUCCESS_DEFINITION_FAIR_ADOPTION,
        "adoption_suite": "B",
        "stress_lab_suite": "A",
        "primary_learning_track_unchanged": True,
        "primary_learning_track": primary_id,
        "note": (
            "Suite B fair excess is adoption truth for promotion talk. "
            "Suite A 3% stress books stay the primary learning track and churn lab "
            "(N145 / N48) — do not promote on stress excess alone."
        ),
        "suite_a": {
            "role": STRESS_LAB_ROLE,
            "cost_basis": "3pct_per_side_stress",
            "label": "Suite A — stress / churn lab",
            "blurb": (
                "Live FTSE books at 3% per-side stress. Optimize cost drag, trade count, "
                "and hold stability — not absolute beat-^FTSE promotion truth."
            ),
            "track_ids": suite_a_ids,
            "tracks": {
                tid: _track_row_summary(
                    tid, reviews.get(tid) if isinstance(reviews.get(tid), dict) else None
                )
                for tid in suite_a_ids
            },
            "primary_excess_after_costs": stress_metrics.get("excess_after_costs")
            if stress_metrics
            else learning_tracks_review.get("primary_excess_after_costs"),
            "beat_market": learning_tracks_review.get("beat_market"),
            "beat_control": learning_tracks_review.get("beat_control"),
            "verdict": learning_tracks_review.get("verdict"),
            "headline_not_adoption_truth": True,
        },
        "suite_b": {
            "role": FAIR_LAB_ROLE,
            "cost_basis": "t212_shaped_fair",
            "label": "Suite B — fair adoption scoreboard",
            "blurb": (
                "Fair T212-shaped twins and cohort labs. Success = AI fair excess vs ^FTSE "
                "and vs fair rules control before any promotion talk."
            ),
            "track_ids": suite_b_ids,
            "tracks": {
                tid: _track_row_summary(
                    tid, reviews.get(tid) if isinstance(reviews.get(tid), dict) else None
                )
                for tid in suite_b_ids
            },
            "ai_track_id": AI_JUDGMENT_FAIR_TRACK_ID,
            "control_track_id": RULES_FAIR_TRACK_ID,
            "ai_excess_after_costs": fair_ai_excess,
            "control_excess_after_costs": fair_rules_excess,
            "beat_market": fair_beat_market,
            "beat_control": fair_beat_control,
            "available": bool(suite_b_ids),
        },
        "fair_assess_suite_a": assess,
        "promotion_gate": {
            "do_not_flip_primary_on_stress_excess": True,
            "requires_suite_b_endurance": True,
            "refs": [
                "docs/ops/primary-learning-track.md",
                "docs/ops/market-trading-costs.md#test-and-adoption-strategy-dual-suite",
                "N145",
                "N48",
            ],
        },
    }


__all__ = [
    "SCHEMA_VERSION",
    "SUCCESS_DEFINITION_FAIR_ADOPTION",
    "build_learning_tracks_dual_suite",
    "classify_suite",
]
