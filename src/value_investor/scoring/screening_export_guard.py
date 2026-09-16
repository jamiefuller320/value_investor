"""Export-time guards for screening snapshots and published report rows."""

from __future__ import annotations

import re
from typing import Any

from value_investor.technical_analysis import TradePlan

_PRIOR_MEMO_MARKERS = (
    "partially confirms",
    "prior memo",
    "research: accumulate",
    "research: caution",
    "medium risk —",
    "low risk —",
)

_TIMING_ACTION_PREFIX = re.compile(
    r"^(Strong Buy|Buy|Hold|Avoid)\s[—–-]\s",
    re.IGNORECASE,
)

_SPARSE_MODEL_PASS_MAX_RATE = 0.45
_TRADE_PLAN_LIMIT_RATIO_MAX = 50.0
_TRADE_PLAN_LIMIT_RATIO_MIN = 0.02


def isolate_timing_action_note(action_note: str | None) -> str:
    """Drop prior-memo / research rationale tails spliced into timing action notes."""
    text = str(action_note or "").strip()
    if not text:
        return ""
    if not any(marker in text.lower() for marker in _PRIOR_MEMO_MARKERS):
        return text

    segments = [part.strip() for part in text.split("|") if part.strip()]
    if not segments:
        return text

    kept: list[str] = []
    for segment in segments:
        lower = segment.lower()
        if segment.startswith("Research:"):
            continue
        if any(marker in lower for marker in _PRIOR_MEMO_MARKERS):
            continue
        if len(segment) > 180 and _TIMING_ACTION_PREFIX.match(segment) is None:
            continue
        kept.append(segment)

    if kept:
        return " | ".join(kept)
    first = segments[0]
    if _TIMING_ACTION_PREFIX.match(first):
        return first
    return ""


def sparse_model_pass_detected(
    *,
    models_passed: int,
    model_count: int,
    failed_models: list[str] | None,
) -> bool:
    """True when export rows claim few model passes but ship an empty failed_models list."""
    if model_count <= 0:
        return False
    failed = list(failed_models or [])
    if failed:
        return False
    rate = models_passed / model_count
    return models_passed < model_count and rate <= _SPARSE_MODEL_PASS_MAX_RATE


def format_sparse_model_pass_family_clause(
    *,
    families_passed: int,
    family_count: int,
    passed_families: str | None,
    models_passed: int,
    model_count: int,
) -> str | None:
    if not sparse_model_pass_detected(
        models_passed=models_passed,
        model_count=model_count,
        failed_models=[],
    ):
        return None
    family_text = passed_families or "—"
    return (
        f"Families: {families_passed}/{family_count} ({family_text}) "
        f"— sparse model pass ({models_passed}/{model_count}; failed_models empty)."
    )


def trade_plan_limit_unit_mismatch(
    *,
    spot: float | None,
    trade_plan: TradePlan | None,
) -> bool:
    """Detect pence/pounds or ADS-style unit errors when limits are orders of magnitude off spot."""
    if spot is None or spot <= 0 or trade_plan is None:
        return False
    for limit in (trade_plan.tactical_limit, trade_plan.core_limit):
        if limit is None or limit <= 0:
            continue
        ratio = float(limit) / float(spot)
        if ratio > _TRADE_PLAN_LIMIT_RATIO_MAX or ratio < _TRADE_PLAN_LIMIT_RATIO_MIN:
            return True
    return False


def adjust_stability_for_trade_plan_sanity(
    *,
    stability_label: str,
    weeks_at_signal: int,
    spot: float | None,
    trade_plan: TradePlan | None,
) -> tuple[str, bool]:
    """Do not label cheapness persistent when trade-plan limits disagree with live spot."""
    if stability_label != "persistent":
        return stability_label, False
    if not trade_plan_limit_unit_mismatch(spot=spot, trade_plan=trade_plan):
        return stability_label, False
    if weeks_at_signal >= 4:
        return "building", True
    return stability_label, False


def apply_screening_export_guard(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize export/snapshot dicts before persistence or email publish."""
    updated = dict(payload)
    updated["action_note"] = isolate_timing_action_note(str(updated.get("action_note") or ""))

    models_passed = int(updated.get("models_passed") or 0)
    model_count = int(updated.get("model_count") or 0)
    failed_models = list(updated.get("failed_models") or [])
    sparse = sparse_model_pass_detected(
        models_passed=models_passed,
        model_count=model_count,
        failed_models=failed_models,
    )
    if sparse:
        updated["sparse_model_pass"] = True
        summary = str(updated.get("summary") or "")
        family_clause = format_sparse_model_pass_family_clause(
            families_passed=int(updated.get("families_passed") or 0),
            family_count=int(updated.get("family_count") or 5),
            passed_families=updated.get("passed_families"),
            models_passed=models_passed,
            model_count=model_count,
        )
        if family_clause and family_clause not in summary:
            updated["summary"] = f"{summary} {family_clause}".strip()

    spot_raw = updated.get("close")
    spot = float(spot_raw) if spot_raw is not None else None
    trade_plan_raw = updated.get("trade_plan")
    trade_plan: TradePlan | None = None
    if isinstance(trade_plan_raw, dict):
        trade_plan = TradePlan(
            core_limit=trade_plan_raw.get("core_limit"),
            tactical_limit=trade_plan_raw.get("tactical_limit"),
        )
    elif isinstance(trade_plan_raw, TradePlan):
        trade_plan = trade_plan_raw

    new_label, downgraded = adjust_stability_for_trade_plan_sanity(
        stability_label=str(updated.get("stability_label") or "new"),
        weeks_at_signal=int(updated.get("weeks_at_signal") or 0),
        spot=spot,
        trade_plan=trade_plan,
    )
    if downgraded:
        updated["stability_label"] = new_label
        updated["trade_plan_unit_warning"] = True

    return updated
