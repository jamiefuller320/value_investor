"""Deterministic weeding of near-duplicate and already-captured scratch fragments.

Horizon FRAGMENT CLUSTERING can DROP/PROMOTE, but that pass is under-applied
(``apply_fragments`` defaults off) and the director cap stays at 2. This weeder
clears exact-ish duplicates and fragments that already exist as deferred ideas
*before* any cap raise.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from value_investor.deferred_ideas import (
    DEFAULT_STORE,
    list_open_fragments,
    load_store,
    save_store,
)

FRAGMENT_JACCARD = 0.62
IDEA_JACCARD = 0.50
IDEA_TITLE_JACCARD = 0.70
MIN_TOKENS = 4
CONTAINMENT = 0.80

_STOP = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "be",
        "by",
        "for",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "vs",
        "we",
        "when",
        "with",
    }
)

SAFE_DROP_REASONS = frozenset({"near_duplicate", "already_open_idea", "already_done_idea"})


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _tokens(text: str) -> frozenset[str]:
    words = re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split()
    return frozenset(word for word in words if word not in _STOP and len(word) > 1)


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    inter = len(left & right)
    union = len(left | right)
    return inter / union if union else 0.0


def _containment(smaller: frozenset[str], larger: frozenset[str]) -> float:
    if not smaller:
        return 0.0
    return len(smaller & larger) / len(smaller)


def _near_duplicate(left: frozenset[str], right: frozenset[str], *, threshold: float) -> bool:
    if len(left) < MIN_TOKENS or len(right) < MIN_TOKENS:
        return False
    if _jaccard(left, right) >= threshold:
        return True
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    return _containment(shorter, longer) >= CONTAINMENT and _jaccard(left, right) >= (
        threshold - 0.12
    )


def _idea_text(idea: dict[str, Any]) -> str:
    title = str(idea.get("title") or "")
    summary = str(idea.get("summary") or "")
    return f"{title} {summary}".strip()


def _sort_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("added_at") or ""), str(row.get("id") or ""))


def propose_fragment_weeds(
    store: dict[str, Any] | None = None,
    *,
    store_path=DEFAULT_STORE,
) -> dict[str, Any]:
    """Propose DROP/KEEP actions for open fragments. Does not write."""
    store = store or load_store(store_path)
    fragments = list_open_fragments(store)
    ideas = [row for row in (store.get("ideas") or []) if isinstance(row, dict)]
    open_ideas = [row for row in ideas if str(row.get("status") or "open") == "open"]
    done_ideas = [row for row in ideas if str(row.get("status") or "") == "done"]

    idea_tokens = [
        (row, _tokens(_idea_text(row)), _tokens(str(row.get("title") or "")))
        for row in open_ideas + done_ideas
    ]
    frag_tokens = [(row, _tokens(str(row.get("text") or ""))) for row in fragments]
    claimed: set[str] = set()
    actions: list[dict[str, Any]] = []

    for row, tokens in frag_tokens:
        frag_id = str(row.get("id") or "")
        matched_idea = None
        reason = ""
        for idea, idea_tok, title_tok in idea_tokens:
            title_hit = len(title_tok) >= 3 and _jaccard(tokens, title_tok) >= IDEA_TITLE_JACCARD
            body_hit = _near_duplicate(tokens, idea_tok, threshold=IDEA_JACCARD)
            if title_hit or body_hit:
                matched_idea = idea
                status = str(idea.get("status") or "open")
                reason = "already_done_idea" if status == "done" else "already_open_idea"
                break
        if matched_idea is not None:
            claimed.add(frag_id)
            actions.append(
                {
                    "action": "DROP",
                    "fragment_id": frag_id,
                    "reason": reason,
                    "idea_id": matched_idea.get("id"),
                    "idea_title": matched_idea.get("title"),
                    "text": row.get("text"),
                }
            )

    remaining = [(row, tokens) for row, tokens in frag_tokens if str(row.get("id")) not in claimed]
    remaining.sort(key=lambda item: _sort_key(item[0]))
    clusters: list[list[dict[str, Any]]] = []
    used: set[str] = set()
    for row, tokens in remaining:
        frag_id = str(row.get("id") or "")
        if frag_id in used:
            continue
        cluster = [row]
        used.add(frag_id)
        for other, other_tokens in remaining:
            other_id = str(other.get("id") or "")
            if other_id in used:
                continue
            if _near_duplicate(tokens, other_tokens, threshold=FRAGMENT_JACCARD):
                cluster.append(other)
                used.add(other_id)
        clusters.append(cluster)

    for cluster in clusters:
        cluster.sort(key=_sort_key)
        canonical = cluster[0]
        if len(cluster) == 1:
            actions.append(
                {
                    "action": "KEEP",
                    "fragment_id": canonical.get("id"),
                    "reason": "unique",
                    "text": canonical.get("text"),
                }
            )
            continue
        actions.append(
            {
                "action": "KEEP",
                "fragment_id": canonical.get("id"),
                "reason": "cluster_canonical",
                "cluster_size": len(cluster),
                "text": canonical.get("text"),
            }
        )
        for dup in cluster[1:]:
            actions.append(
                {
                    "action": "DROP",
                    "fragment_id": dup.get("id"),
                    "reason": "near_duplicate",
                    "canonical_id": canonical.get("id"),
                    "text": dup.get("text"),
                }
            )

    drops = [row for row in actions if row["action"] == "DROP"]
    keeps = [row for row in actions if row["action"] == "KEEP"]
    return {
        "proposed_at": _utcnow(),
        "open_count": len(fragments),
        "drop_count": len(drops),
        "keep_count": len(keeps),
        "actions": sorted(
            actions,
            key=lambda row: (
                0 if row["action"] == "DROP" else 1,
                str(row.get("reason") or ""),
                str(row.get("fragment_id") or ""),
            ),
        ),
    }


def apply_fragment_weeds(
    proposal: dict[str, Any] | None = None,
    *,
    store_path=DEFAULT_STORE,
    reasons: frozenset[str] = SAFE_DROP_REASONS,
) -> dict[str, Any]:
    """Apply deterministic DROP actions. Leaves KEEP rows untouched."""
    store = load_store(store_path)
    proposal = proposal or propose_fragment_weeds(store)
    dropped: list[str] = []
    skipped: list[dict[str, str]] = []
    by_id = {
        str(row.get("id") or ""): row
        for row in (store.get("fragments") or [])
        if isinstance(row, dict)
    }
    for action in proposal.get("actions") or []:
        if action.get("action") != "DROP":
            continue
        reason = str(action.get("reason") or "")
        frag_id = str(action.get("fragment_id") or "")
        if reason not in reasons:
            skipped.append({"id": frag_id, "reason": f"reason not applied: {reason}"})
            continue
        row = by_id.get(frag_id)
        if row is None:
            skipped.append({"id": frag_id, "reason": "unknown fragment"})
            continue
        if str(row.get("status") or "open") != "open":
            skipped.append({"id": frag_id, "reason": "not open"})
            continue
        row["status"] = "drop"
        row["updated_at"] = _utcnow()
        row["weeded_reason"] = reason
        if action.get("canonical_id"):
            row["weeded_of"] = action.get("canonical_id")
        elif action.get("idea_id"):
            row["weeded_of"] = action.get("idea_id")
        dropped.append(frag_id)
    if dropped:
        save_store(store, store_path)
    remaining = list_open_fragments(store)
    return {
        "dropped": dropped,
        "skipped": skipped,
        "open_remaining": len(remaining),
        "store_path": str(store_path),
    }


def weed_fragments(
    *,
    store_path=DEFAULT_STORE,
    apply: bool = False,
) -> dict[str, Any]:
    """Propose weeds; optionally apply safe DROPs."""
    proposal = propose_fragment_weeds(store_path=store_path)
    result: dict[str, Any] = {"proposal": proposal, "applied": False}
    if apply:
        result["apply"] = apply_fragment_weeds(proposal, store_path=store_path)
        result["applied"] = True
    return result


__all__ = [
    "FRAGMENT_JACCARD",
    "SAFE_DROP_REASONS",
    "apply_fragment_weeds",
    "propose_fragment_weeds",
    "weed_fragments",
]
