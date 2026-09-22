"""Learning / analysis data completeness score (not narrative cleanliness)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

LIVE_MARKET_ID = "ftse350"


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _ratio(num: int, denom: int) -> float:
    if denom <= 0:
        return 1.0 if num <= 0 else 0.0
    return max(0.0, min(1.0, num / denom))


def _filing_body_ratio(market_status: dict[str, Any] | None) -> float | None:
    if not isinstance(market_status, dict):
        return None
    markets = market_status.get("markets") or []
    row = next(
        (m for m in markets if isinstance(m, dict) and m.get("market_id") == LIVE_MARKET_ID),
        None,
    )
    if not isinstance(row, dict):
        return None
    health = row.get("filing_health") if isinstance(row.get("filing_health"), dict) else {}
    with_body = _int(health.get("filings_with_body"))
    indexed = _int(health.get("filings_indexed") or health.get("indexed_count"))
    if indexed <= 0:
        zero_buy = _int(health.get("zero_body_buy_tier"))
        if zero_buy == 0 and with_body > 0:
            return 1.0
        return None
    return _ratio(with_body, indexed)


def compute_learning_data_completeness(
    system_gaps: dict[str, Any] | None,
    *,
    market_status: dict[str, Any] | None = None,
    assessed_at: datetime | None = None,
) -> dict[str, Any]:
    """
    Composite 0–100 score for whether the live + learning path is fed with
    usable data (overlay wiring, publish parity, memo bodies, filing bodies, gaps).
    """
    if not isinstance(system_gaps, dict):
        return {
            "schema_version": 1,
            "assessed_at": (assessed_at or datetime.now(UTC)).isoformat(),
            "score": None,
            "summary": "No system_gaps snapshot — run analysis-review system-gaps.",
            "components": {},
        }

    layers = system_gaps.get("layers") if isinstance(system_gaps.get("layers"), dict) else {}
    apply_layer = layers.get("apply") if isinstance(layers.get("apply"), dict) else {}
    publish_layer = layers.get("publish") if isinstance(layers.get("publish"), dict) else {}
    produce = layers.get("produce") if isinstance(layers.get("produce"), dict) else {}
    live = produce.get("live_committed") if isinstance(produce.get("live_committed"), dict) else {}

    buy_count = _int(apply_layer.get("buy_tier_count"))
    buy_wired = _int(apply_layer.get("buy_tier_wired_count"))
    sb_count = _int(apply_layer.get("strong_buy_count"))
    sb_wired = _int(apply_layer.get("strong_buy_wired_count"))

    committed_verdicts = _int(live.get("committed_with_verdict"))
    index_count = _int(publish_layer.get("research_index_count"))
    thin_live = _int(live.get("thin_or_zero_body"))
    committed_count = _int(live.get("committed_count"))

    overlay_wiring = _ratio(buy_wired + sb_wired, max(buy_count + sb_count, 1))
    publish_index = _ratio(index_count, max(committed_verdicts, 1))
    memo_bodies = 1.0 - _ratio(thin_live, max(committed_count, 1))

    filing_ratio = _filing_body_ratio(market_status)
    if filing_ratio is None:
        filing_component = None
        filing_weight = 0.0
    else:
        filing_component = filing_ratio
        filing_weight = 0.20

    high = _int(system_gaps.get("high_flag_count"))
    medium = max(0, _int(system_gaps.get("flag_count")) - high)
    gap_penalty = min(1.0, (high * 0.12) + (medium * 0.04))
    gap_integrity = max(0.0, 1.0 - gap_penalty)

    base_weights = {
        "overlay_wiring": 0.25,
        "publish_index": 0.20,
        "memo_body_quality": 0.25,
        "gap_integrity": 0.30,
    }
    if filing_weight:
        scale = 1.0 - filing_weight
        scaled = {k: v * scale for k, v in base_weights.items()}
        scaled["filing_bodies"] = filing_weight
        base_weights = scaled

    components: dict[str, Any] = {
        "overlay_wiring": {
            "score_pct": round(overlay_wiring * 100),
            "detail": f"buy+strong_buy wired {buy_wired + sb_wired}/{buy_count + sb_count}",
        },
        "publish_index": {
            "score_pct": round(publish_index * 100),
            "detail": f"research[] {index_count} vs {committed_verdicts} committed verdicts",
        },
        "memo_body_quality": {
            "score_pct": round(memo_bodies * 100),
            "detail": f"{thin_live} thin/zero-body of {committed_count} live memos",
        },
        "gap_integrity": {
            "score_pct": round(gap_integrity * 100),
            "detail": f"{high} high + {medium} other learning-path flags",
        },
    }
    if filing_component is not None:
        components["filing_bodies"] = {
            "score_pct": round(filing_component * 100),
            "detail": f"{LIVE_MARKET_ID} indexed filings with bodies (market_status)",
        }

    score_float = sum(
        (components[key]["score_pct"] / 100.0) * base_weights[key] for key in base_weights
    )
    score = int(round(score_float * 100))

    if score >= 80:
        band = "strong"
        summary = "Live overlay, publish parity, and memo bodies are mostly wired for learning."
    elif score >= 60:
        band = "partial"
        summary = "Material gaps remain — prioritise Lane A bodies and apply/publish wiring."
    else:
        band = "weak"
        summary = "Learning path is under-fed — treat Persistent weaknesses as themes, fix wiring/bodies first."

    return {
        "schema_version": 1,
        "assessed_at": system_gaps.get("assessed_at")
        or (assessed_at or datetime.now(UTC)).isoformat(),
        "score": score,
        "band": band,
        "summary": summary,
        "weights": base_weights,
        "components": components,
        "inputs": {
            "flag_count": _int(system_gaps.get("flag_count")),
            "high_flag_count": high,
        },
    }


__all__ = ["compute_learning_data_completeness", "LIVE_MARKET_ID"]
