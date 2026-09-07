"""Admission to the equal-resource learning set after maintenance ingest threshold."""

from __future__ import annotations

from typing import Any


def admitted_learning_markets_for_policy(policy: dict[str, Any] | None) -> list[str]:
    """Markets that should start equivalent learning resource now.

    Explicit ``ladder.admitted_learning_markets`` plus
    ``ingest_exhausted_markets`` (maintenance-threshold graduates). Does **not**
    auto-include ``ingest_parity_markets`` — the focus can be listed there while
    still holding the fat sprint.
    """
    policy = policy or {}
    ladder = policy.get("ladder") or {}
    explicit = [
        str(mid).strip()
        for mid in (ladder.get("admitted_learning_markets") or [])
        if str(mid).strip()
    ]
    exhausted = [
        str(mid).strip()
        for mid in (policy.get("ingest_exhausted_markets") or [])
        if str(mid).strip()
    ]
    out: list[str] = []
    for mid in [*explicit, *exhausted]:
        if mid and mid not in out:
            out.append(mid)
    return out


__all__ = ["admitted_learning_markets_for_policy"]
