"""Observe-only analysis opinion + factory reply text for post-sale reviews.

Package **M** alignment — never fills, knobs, or Package L auto-tune.
``influences_live=false`` always.

Initial presentation: structured opinion + learning points (deterministic v0,
optional LLM upgrade later). Comment → factory reply (LLM when available,
contextual deterministic fallback).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

LlmCompleteFn = Callable[[str], str]

OPINION_SOURCE_DETERMINISTIC = "deterministic_v0"
OPINION_SOURCE_LLM = "llm"
REPLY_SOURCE_DETERMINISTIC = "deterministic_contextual"
REPLY_SOURCE_LLM = "llm"
REPLY_SOURCE_STUB = "deterministic_ack"

# Soft cap if a future refresh path batches LLM opinions (not used by default).
LLM_OPINION_BATCH_CAP = 8


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def build_initial_opinion(item: dict[str, Any]) -> dict[str, Any]:
    """Structured what-happened + learning points for chart annotation.

    Deterministic so every sealed + control card has opinion on first paint.
    Optional LLM prose may replace ``opinion`` later (same schema); never
    influences live capital.
    """
    book = str(item.get("book_tag") or item.get("book_id") or "?")
    ticker = str(item.get("ticker") or "?")
    hold = item.get("hold_days")
    pct = item.get("return_pct")
    exit_kind = str(item.get("exit_kind") or "").strip() or "exit"
    basis = str(item.get("basis_label") or "return")
    entry = str(item.get("entry_at") or "")[:10] or "?"
    exit_at = str(item.get("exit_at") or "")[:10] or "?"

    hold_bit = f"{hold}-day" if hold is not None else "unknown-length"
    if isinstance(pct, (int, float)):
        if pct <= -5:
            outcome = f"material loss ({pct:.2f}% {basis})"
        elif pct < 0:
            outcome = f"small loss ({pct:.2f}% {basis})"
        elif pct < 2:
            outcome = f"near-flat / small gain ({pct:.2f}% {basis})"
        else:
            outcome = f"gain ({pct:.2f}% {basis})"
    else:
        outcome = f"return n/a ({basis})"

    short_hold = isinstance(hold, int) and hold <= 10
    rapid = " Rapid entry→exit" if short_hold else ""
    opinion = (
        f"{book} closed {ticker} after a {hold_bit} hold ({entry} → {exit_at}, "
        f"{exit_kind}): {outcome}.{rapid} "
        "Read episode window for the trade path and wider TF for the cyclical / "
        "trend context the episode alone can hide. Observe-only — not a veto."
    )

    learning_points: list[str] = [
        "Verify episode chart and wider TF together before Accepting framing.",
        "Comment on missed patterns (range location, climb after exit, rapid churn) "
        "— factory must reply; no knobs/fills from this loop.",
    ]
    if short_hold:
        learning_points.append(
            "Short hold: check whether exit timing / churn looks premature vs the "
            "wider range the owner may see on longer history."
        )
    if isinstance(pct, (int, float)) and pct <= -5:
        learning_points.append(
            "Material loss: ask whether the miss was pick quality, timing, or both "
            "(read-only; no Layer reopen from this card)."
        )
    if isinstance(pct, (int, float)) and pct >= 0 and short_hold:
        learning_points.append(
            "Small/positive fair-cost on a short hold can still sit at a poor "
            "cyclical location on wider TF — flag that pattern in Comment if so."
        )

    chart_annotations = {
        "episode": (
            f"Episode: {hold_bit} hold, {outcome}. Confirm entry/exit marks match "
            "the sealed/control path."
        ),
        "wider_tf": (
            "Wider TF: judge range location and post-exit climb/fade that the "
            "episode sleeve can hide."
        ),
    }

    return {
        "llm_opinion": opinion,
        "learning_points": learning_points,
        "chart_annotations": chart_annotations,
        "opinion_source": OPINION_SOURCE_DETERMINISTIC,
        "influences_live": False,
        "generated_at": _utcnow(),
    }


def seed_dialogue(item: dict[str, Any], opinion: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Initial dialogue turn: factory opinion (+ learning points)."""
    packed = opinion if isinstance(opinion, dict) else build_initial_opinion(item)
    return [
        {
            "role": "factory",
            "kind": "initial_opinion",
            "text": str(packed.get("llm_opinion") or "").strip(),
            "learning_points": list(packed.get("learning_points") or []),
            "chart_annotations": dict(packed.get("chart_annotations") or {}),
            "source": str(packed.get("opinion_source") or OPINION_SOURCE_DETERMINISTIC),
            "at": str(packed.get("generated_at") or _utcnow()),
            "influences_live": False,
        }
    ]


def attach_opinion_fields(item: dict[str, Any]) -> dict[str, Any]:
    """Mutate/return item with opinion, learning points, chart notes, dialogue seed."""
    opinion = build_initial_opinion(item)
    item["llm_opinion"] = opinion["llm_opinion"]
    item["learning_points"] = opinion["learning_points"]
    item["chart_annotations"] = opinion["chart_annotations"]
    item["opinion_source"] = opinion["opinion_source"]
    item["dialogue"] = seed_dialogue(item, opinion)
    return item


def build_contextual_reply_text(
    *,
    owner_comment: str,
    item: dict[str, Any] | None = None,
) -> str:
    """Deterministic factory reply that addresses the owner comment (observe)."""
    snap = item if isinstance(item, dict) else {}
    book = str(snap.get("book_tag") or snap.get("book_id") or "?")
    ticker = str(snap.get("ticker") or "?")
    hold = snap.get("hold_days")
    pct = snap.get("return_pct")
    exit_kind = str(snap.get("exit_kind") or "").strip()
    hold_bit = f"{hold}d" if hold is not None else "?"
    pct_bit = f"{pct}%" if isinstance(pct, (int, float)) else "n/a"
    comment = str(owner_comment or "").strip()
    comment_bit = comment if len(comment) <= 280 else comment[:277] + "…"

    lines = [
        f"Acknowledged owner Comment on [{book}] {ticker} "
        f"(hold {hold_bit}, outcome {pct_bit}"
        + (f", {exit_kind}" if exit_kind else "")
        + ").",
        f'You wrote: "{comment_bit}"',
        "Development-loop read (observe / alignment only): dual-horizon charts are "
        "the surface for range-location and post-exit path claims; sealed exit "
        "reasons stay in the book trail — this card does not force knobs or fills "
        "(influences_live=false; Package M — not Package L auto-tune).",
        "Accept if this reply matches what you see; Comment again to continue the "
        "mini dialogue.",
    ]
    return "\n".join(lines)


def _default_llm_complete(prompt: str) -> str:
    from value_investor.cursor_api_key import resolve_cursor_api_key
    from value_investor.research.agent import _run_agent_prompt

    api_key, _ = resolve_cursor_api_key()
    if not api_key:
        raise RuntimeError("CURSOR_API_KEY missing — cannot run post-sale LLM reply")
    model = (
        os.environ.get("FTSE_POST_SALE_LLM_MODEL")
        or os.environ.get("FTSE_LLM_AGREE_VETO_MODEL")
        or "composer-2.5"
    ).strip()
    text, _agent_id = _run_agent_prompt(
        prompt=prompt,
        api_key=api_key,
        model=model,
        cwd=None,
    )
    return text


def _extract_reply_text(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("empty LLM reply")
    # Prefer fenced or bare JSON {"reply": "..."}
    try:
        from value_investor.research.director_worker import extract_json_object

        obj = extract_json_object(text)
        if isinstance(obj, dict):
            reply = obj.get("reply") or obj.get("text") or obj.get("response")
            if isinstance(reply, str) and reply.strip():
                return reply.strip()
    except (ValueError, TypeError, AttributeError):
        pass
    # Strip markdown fences if present
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        inner = fenced.group(1).strip()
        try:
            obj = json.loads(inner)
            if isinstance(obj, dict):
                reply = obj.get("reply") or obj.get("text")
                if isinstance(reply, str) and reply.strip():
                    return reply.strip()
        except json.JSONDecodeError:
            if inner:
                return inner
    return text


def build_llm_reply_prompt(*, owner_comment: str, item: dict[str, Any] | None) -> str:
    snap = item if isinstance(item, dict) else {}
    payload = {
        "role": "post_sale_review_factory_reply",
        "rules": [
            "Observe / alignment only — never change knobs, fills, or live capital.",
            "influences_live must remain false; Package M not Package L auto-tune.",
            "Address the owner's missed-pattern comment using dual-horizon framing.",
            "Do not invent filing facts, exact historical range percentiles, or "
            "sealed sell-trigger IDs you were not given.",
            "Invite Accept or further Comment on this reply.",
            'Return JSON only: {"reply": "..."}',
        ],
        "episode": {
            "book_tag": snap.get("book_tag") or snap.get("book_id"),
            "model_id": snap.get("model_id"),
            "ticker": snap.get("ticker"),
            "entry_at": snap.get("entry_at"),
            "exit_at": snap.get("exit_at"),
            "hold_days": snap.get("hold_days"),
            "exit_kind": snap.get("exit_kind"),
            "return_pct": snap.get("return_pct"),
            "basis_label": snap.get("basis_label"),
            "llm_opinion": snap.get("llm_opinion"),
            "learning_points": snap.get("learning_points"),
        },
        "owner_comment": str(owner_comment or "").strip(),
    }
    return (
        "You write the factory side of a post-sale review mini dialogue.\n"
        "Reply with a single JSON object only.\n\n"
        f"{json.dumps(payload, indent=2)}\n"
    )


def generate_factory_reply(
    *,
    owner_comment: str,
    item: dict[str, Any] | None = None,
    llm_complete: LlmCompleteFn | None = None,
    allow_llm: bool | None = None,
) -> dict[str, Any]:
    """Build factory reply text; try LLM when allowed, else contextual deterministic."""
    if allow_llm is None:
        # Opt-in: GHA / local can set FTSE_POST_SALE_LLM_REPLY=1. Default off
        # so unit tests and ops refresh never spray agent calls.
        allow_llm = str(os.environ.get("FTSE_POST_SALE_LLM_REPLY", "0")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    fallback = build_contextual_reply_text(owner_comment=owner_comment, item=item)
    if not allow_llm:
        return {
            "text": fallback,
            "reply_kind": REPLY_SOURCE_DETERMINISTIC,
            "llm_attempted": False,
            "influences_live": False,
        }

    complete = llm_complete or _default_llm_complete
    try:
        raw = complete(build_llm_reply_prompt(owner_comment=owner_comment, item=item))
        text = _extract_reply_text(raw)
        # Soft guard: refuse live-influence language by appending observe footer
        # if the model omitted it.
        if "influences_live" not in text.lower():
            text = (
                text.rstrip()
                + "\n\n(Observe / alignment only — influences_live=false; "
                "Package M — not Package L auto-tune.)"
            )
        return {
            "text": text,
            "reply_kind": REPLY_SOURCE_LLM,
            "llm_attempted": True,
            "llm_ok": True,
            "influences_live": False,
        }
    except Exception as exc:  # noqa: BLE001 — fail closed to deterministic
        return {
            "text": fallback,
            "reply_kind": REPLY_SOURCE_DETERMINISTIC,
            "llm_attempted": True,
            "llm_ok": False,
            "llm_error": str(exc)[:240],
            "influences_live": False,
        }


def extend_dialogue_for_comment_reply(
    *,
    prior_dialogue: list[dict[str, Any]] | None,
    item: dict[str, Any] | None,
    owner_comment: str,
    reply_text: str,
    reply_kind: str,
    commented_at: str | None = None,
    replied_at: str | None = None,
) -> list[dict[str, Any]]:
    """Append owner comment + factory reply turns to the dialogue thread."""
    base = list(prior_dialogue) if isinstance(prior_dialogue, list) else []
    if not base and isinstance(item, dict):
        base = seed_dialogue(item)
    now_comment = commented_at or _utcnow()
    now_reply = replied_at or _utcnow()
    base.append(
        {
            "role": "owner",
            "kind": "comment",
            "text": str(owner_comment or "").strip(),
            "at": now_comment,
            "influences_live": False,
        }
    )
    base.append(
        {
            "role": "factory",
            "kind": "reply",
            "text": str(reply_text or "").strip(),
            "source": str(reply_kind or REPLY_SOURCE_DETERMINISTIC),
            "at": now_reply,
            "influences_live": False,
        }
    )
    return base


__all__ = [
    "LLM_OPINION_BATCH_CAP",
    "OPINION_SOURCE_DETERMINISTIC",
    "OPINION_SOURCE_LLM",
    "REPLY_SOURCE_DETERMINISTIC",
    "REPLY_SOURCE_LLM",
    "REPLY_SOURCE_STUB",
    "attach_opinion_fields",
    "build_contextual_reply_text",
    "build_initial_opinion",
    "build_llm_reply_prompt",
    "extend_dialogue_for_comment_reply",
    "generate_factory_reply",
    "seed_dialogue",
]
