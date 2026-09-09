"""Admission to the equal-resource learning set after maintenance ingest threshold."""

from __future__ import annotations

from typing import Any


def _clean_market_ids(values: Any) -> list[str]:
    out: list[str] = []
    for mid in values or []:
        text = str(mid).strip()
        if text and text not in out:
            out.append(text)
    return out


def admit_market_to_learning(policy: dict[str, Any], market_id: str) -> bool:
    """Persist ``market_id`` onto ``ladder.admitted_learning_markets``.

    Returns True when the explicit admitted list changed.
    """
    mid = str(market_id or "").strip()
    if not mid:
        return False
    ladder = dict(policy.get("ladder") or {})
    admitted = _clean_market_ids(ladder.get("admitted_learning_markets"))
    if mid in admitted:
        policy["ladder"] = ladder
        ladder["admitted_learning_markets"] = admitted
        return False
    admitted.append(mid)
    ladder["admitted_learning_markets"] = admitted
    policy["ladder"] = ladder
    return True


def sync_admitted_learning_markets(policy: dict[str, Any]) -> list[str]:
    """Rewrite explicit admitted list from L322 threshold signals already on policy.

    Union of current explicit + ``ingest_exhausted_markets`` + ``ingest_parity_markets``
    (the stored forms of ``sprint_ingest_complete``).
    """
    merged = admitted_learning_markets_for_policy(policy)
    ladder = dict(policy.get("ladder") or {})
    ladder["admitted_learning_markets"] = list(merged)
    policy["ladder"] = ladder
    return list(merged)


def admitted_learning_markets_for_policy(policy: dict[str, Any] | None) -> list[str]:
    """Markets that should receive equivalent learning resource now (L322).

    ``sprint_ingest_complete`` is raw parity **or** leftover exhaustion. Policy
    stores those as ``ingest_parity_markets`` and ``ingest_exhausted_markets``.
    Explicit ``ladder.admitted_learning_markets`` remains the durable roster and
    is unioned with both threshold lists so a graduate is not missed when only
    one signal was written.
    """
    policy = policy or {}
    ladder = policy.get("ladder") or {}
    explicit = _clean_market_ids(ladder.get("admitted_learning_markets"))
    exhausted = _clean_market_ids(policy.get("ingest_exhausted_markets"))
    parity = _clean_market_ids(policy.get("ingest_parity_markets"))
    out: list[str] = []
    for mid in [*explicit, *exhausted, *parity]:
        if mid and mid not in out:
            out.append(mid)
    return out


__all__ = [
    "admit_market_to_learning",
    "admitted_learning_markets_for_policy",
    "sync_admitted_learning_markets",
]
