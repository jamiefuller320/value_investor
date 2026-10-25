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

from value_investor.cue_consumer_mft import assess_same_day_round_trip
from value_investor.post_sale_decision_reasons import (
    UNKNOWN_LABEL,
    format_decision_reasons_for_prompt,
)

LlmCompleteFn = Callable[[str], str]

OPINION_SOURCE_DETERMINISTIC = "deterministic_v0"
OPINION_SOURCE_LLM = "llm"
REPLY_SOURCE_DETERMINISTIC = "deterministic_contextual"
REPLY_SOURCE_LLM = "llm"
REPLY_SOURCE_STUB = "deterministic_ack"

# Soft cap if a future refresh path batches LLM opinions (not used by default).
LLM_OPINION_BATCH_CAP = 8

HUMAN_CONSIDER_AGREE = "agree"
HUMAN_CONSIDER_PARTIAL = "partial"
HUMAN_CONSIDER_DISAGREE = "disagree"
HUMAN_CONSIDER_UNKNOWN = "unknown"


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _deterministic_strengths_weaknesses(
    *,
    buy_label: str,
    sell_label: str,
    sell_code: str,
    sell_join_ok: bool,
    buy_join_ok: bool,
    pct: Any,
    short_hold: bool,
    same_day: bool,
    same_day_assessment: str,
) -> dict[str, list[str]]:
    """Plain-language buy/sell strengths & weaknesses (L633 deterministic_v0)."""
    buy_strengths: list[str] = []
    buy_weaknesses: list[str] = []
    sell_strengths: list[str] = []
    sell_weaknesses: list[str] = []

    if buy_join_ok:
        buy_strengths.append(
            f"Buy decision is joinable: {buy_label} — comments can ground on that trail."
        )
    else:
        buy_weaknesses.append(
            "Buy reason unjoinable / unknown — do not invent a buy thesis from the chart alone."
        )

    if sell_join_ok:
        sell_strengths.append(
            f"Sell decision is joinable: {sell_label}"
            + (f" [{sell_code}]" if sell_code else "")
            + " — weigh 'premature' claims against this code."
        )
        if sell_code in {"leave_buy_tier", "left_target_set"}:
            sell_strengths.append(
                "Mechanical identity / buy-tier leave is an honest sealed exit, not a "
                "silent timing skill claim."
            )
    else:
        sell_weaknesses.append(
            "Sell reason unjoinable / unknown — never invent a sell-trigger ID."
        )

    if isinstance(pct, (int, float)) and pct <= -5:
        buy_weaknesses.append(
            "Material fair-cost loss: pick quality and/or buy timing may be weak — "
            "read wider TF before blaming only the sell."
        )
        sell_weaknesses.append(
            "Exit did not prevent a material loss — ask whether sell timing/strategy "
            "could have cut earlier without inventing knobs."
        )
    elif isinstance(pct, (int, float)) and pct >= 2:
        buy_strengths.append(
            "Positive fair-cost outcome supports the pick/entry enough for alignment "
            "review — still check cyclical location on wider TF."
        )

    if short_hold and not same_day:
        sell_weaknesses.append(
            "Short hold: check whether exit timing looks premature vs the wider range."
        )
    if same_day:
        if same_day_assessment == "major_error_reverse":
            sell_strengths.append(
                "Same-day exit flagged as major_error_reverse with durable evidence — "
                "exception to the default same-day weakness bias."
            )
        else:
            sell_weaknesses.append(
                "Same-calendar-day buy→sell is default undesirable (churn / weak sell "
                "timing) unless major decision-error reverse evidence is cited."
            )
            buy_weaknesses.append(
                "Same-day round-trip often means the buy was a mistake worth reversing "
                "— or the sell was noise; burden of proof is on the reverse case."
            )

    if not buy_strengths:
        buy_strengths.append(
            "No strong deterministic buy strength beyond the structured label — "
            "owner Comment can add pattern evidence."
        )
    if not sell_strengths:
        sell_strengths.append(
            "No strong deterministic sell strength beyond the structured label — "
            "owner Comment can add pattern evidence."
        )

    return {
        "buy_strengths": buy_strengths[:4],
        "buy_weaknesses": buy_weaknesses[:4],
        "sell_strengths": sell_strengths[:4],
        "sell_weaknesses": sell_weaknesses[:4],
    }


def _learning_point_forward(
    *,
    same_day: bool,
    same_day_assessment: str,
    short_hold: bool,
    sell_code: str,
    sell_join_ok: bool,
    pct: Any,
) -> str:
    """One durable lesson candidate for the super-book / proposal lane (L633)."""
    if same_day and same_day_assessment != "major_error_reverse":
        return (
            "Bias sell timing/strategy against same-calendar-day exits unless "
            "major_error_reverse evidence is durable — soft penalty for cue-consumer "
            "MFT levers 4–5, not a hard ban."
        )
    if same_day and same_day_assessment == "major_error_reverse":
        return (
            "When intraday path shows a mistaken entry, a same-day reverse with "
            "cited evidence can be the right sell — keep that exception narrow."
        )
    if sell_join_ok and sell_code in {"leave_buy_tier", "left_target_set"} and short_hold:
        return (
            "Short mechanical leave-buy-tier exits are identity churn, not timing "
            "skill — do not harden 'hold longer' from these without a separate twin."
        )
    if isinstance(pct, (int, float)) and pct <= -5:
        return (
            "Material-loss autopsies should separate stock choice vs buy/sell timing "
            "before any mid-flight tune proposal on the cue-consumer lab."
        )
    if short_hold:
        return (
            "Short-hold exits need wider-TF range-location critique before treating "
            "fair-cost as timing proof."
        )
    return (
        "Carry one concrete chart/decision pattern forward into the cue-consumer "
        "MFT lesson intake — never auto-apply knobs on sealed books (Package M only)."
    )


def consider_human_comment(
    *,
    owner_comment: str,
    item: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministic consider (agree/partial/disagree) — never blind-follow (L633)."""
    comment = str(owner_comment or "").strip()
    snap = item if isinstance(item, dict) else {}
    reasons = format_decision_reasons_for_prompt(snap)
    sell_label = str(reasons["sell"].get("label") or UNKNOWN_LABEL)
    sell_code = str(reasons["sell"].get("code") or "")
    sell_join = bool(reasons["sell"].get("join_ok"))
    lower = comment.lower()

    if not comment:
        return {
            "stance": HUMAN_CONSIDER_UNKNOWN,
            "why": "No owner Comment text to weigh.",
            "influences_live": False,
        }

    premature = any(
        token in lower for token in ("premature", "too early", "sold too soon", "cut short")
    )
    mechanical = sell_join and sell_code in {"leave_buy_tier", "left_target_set"}
    if premature and mechanical:
        return {
            "stance": HUMAN_CONSIDER_PARTIAL,
            "why": (
                f"Owner flags premature sell, but structured exit is mechanical "
                f"({sell_label}"
                + (f" [{sell_code}]" if sell_code else "")
                + ") — agree the chart may show more room; disagree that the sealed "
                "rule was a free timing choice. Not a knob order."
            ),
            "influences_live": False,
        }
    if premature and sell_join:
        return {
            "stance": HUMAN_CONSIDER_PARTIAL,
            "why": (
                f"Weigh premature claim against joinable sell reason ({sell_label}). "
                "Chart critique welcome; Comment is not an auto-tune order."
            ),
            "influences_live": False,
        }
    if any(token in lower for token in ("agree", "looks right", "framing matches")):
        return {
            "stance": HUMAN_CONSIDER_AGREE,
            "why": "Owner language aligns with Accept-style framing — still observe-only.",
            "influences_live": False,
        }
    if any(token in lower for token in ("disagree", "wrong", "missed", "bottom of range", "climb")):
        return {
            "stance": HUMAN_CONSIDER_PARTIAL,
            "why": (
                "Owner pattern critique noted for dual-horizon charts and "
                "learning_point_forward — considered, not blindly applied."
            ),
            "influences_live": False,
        }
    return {
        "stance": HUMAN_CONSIDER_PARTIAL,
        "why": (
            "Comment recorded and considered against structured buy/sell reasons; "
            "factory does not treat Comment as a sealed-knob order."
        ),
        "influences_live": False,
    }


def build_initial_opinion(item: dict[str, Any]) -> dict[str, Any]:
    """Structured what-happened + learning points for chart annotation.

    Deterministic so every sealed + control card has opinion on first paint.
    Optional LLM prose may replace ``opinion`` later (same schema); never
    influences live capital.

    L633 enrich: buy/sell strengths & weaknesses, ``learning_point_forward``,
    same-day soft bias flags. Chart captions retained.
    """
    book = str(item.get("book_tag") or item.get("book_id") or "?")
    ticker = str(item.get("ticker") or "?")
    hold = item.get("hold_days")
    pct = item.get("return_pct")
    exit_kind = str(item.get("exit_kind") or "").strip() or "exit"
    basis = str(item.get("basis_label") or "return")
    entry = str(item.get("entry_at") or "")[:10] or "?"
    exit_at = str(item.get("exit_at") or "")[:10] or "?"
    reasons = format_decision_reasons_for_prompt(item)
    buy_label = str(reasons["buy"].get("label") or UNKNOWN_LABEL)
    sell_label = str(reasons["sell"].get("label") or UNKNOWN_LABEL)
    sell_code = str(reasons["sell"].get("code") or "")
    sell_join_ok = bool(reasons["sell"].get("join_ok"))
    buy_join_ok = bool(reasons["buy"].get("join_ok"))

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
    same_day_row = assess_same_day_round_trip(
        entry_at=item.get("entry_at"),
        exit_at=item.get("exit_at"),
        hold_days=hold,
        major_error_reverse=bool(item.get("major_error_reverse")),
        evidence_cites=list(item.get("same_day_evidence_cites") or []),
    )
    same_day = bool(same_day_row["same_day_round_trip"])
    same_day_assessment = str(same_day_row["same_day_assessment"])

    rapid = " Rapid entry→exit" if short_hold else ""
    same_day_bit = (
        f" Same-day round-trip flagged ({same_day_assessment})."
        if same_day
        else ""
    )
    opinion = (
        f"{book} closed {ticker} after a {hold_bit} hold ({entry} → {exit_at}, "
        f"{exit_kind}): {outcome}.{rapid}{same_day_bit} "
        f"Bought because: {buy_label}. Sold because: {sell_label}. "
        "Read episode window for the trade path and wider TF for the cyclical / "
        "trend context the episode alone can hide. Observe-only — not a veto."
    )

    learning_points: list[str] = [
        "Verify episode chart and wider TF together before Accepting framing.",
        "Comment on missed patterns (range location, climb after exit, rapid churn) "
        "— factory must reply; no knobs/fills from this loop.",
        f"Ground comments in the structured sell reason ({sell_label}) — "
        "e.g. 'premature' is only meaningful vs a timing/tech trigger, not a "
        "buy-tier / identity exit.",
    ]
    if short_hold:
        if sell_join_ok and sell_code in {"leave_buy_tier", "left_target_set"}:
            learning_points.append(
                "Short hold with buy-tier / target-set exit: churn may be mechanical "
                "identity leave — weigh that before calling the sell premature."
            )
        else:
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
    if same_day:
        learning_points.append(
            "Same-day buy→sell: default likely weakness unless major_error_reverse "
            "with durable evidence — soft bias for super-book sell levers, not hard ban."
        )

    sw = _deterministic_strengths_weaknesses(
        buy_label=buy_label,
        sell_label=sell_label,
        sell_code=sell_code,
        sell_join_ok=sell_join_ok,
        buy_join_ok=buy_join_ok,
        pct=pct,
        short_hold=short_hold,
        same_day=same_day,
        same_day_assessment=same_day_assessment,
    )
    learning_point_forward = _learning_point_forward(
        same_day=same_day,
        same_day_assessment=same_day_assessment,
        short_hold=short_hold,
        sell_code=sell_code,
        sell_join_ok=sell_join_ok,
        pct=pct,
    )

    chart_annotations = {
        "episode": (
            f"Episode: {hold_bit} hold, {outcome}."
            + (" Same-day round-trip." if same_day else "")
            + " Confirm entry/exit marks match the sealed/control path."
        ),
        "wider_tf": (
            "Wider TF: judge range location and post-exit climb/fade that the "
            "episode sleeve can hide."
            + (
                " Same-day exits still need wider context before calling the reverse skillful."
                if same_day
                else ""
            )
        ),
    }

    return {
        "llm_opinion": opinion,
        "learning_points": learning_points,
        "chart_annotations": chart_annotations,
        "buy_strengths": sw["buy_strengths"],
        "buy_weaknesses": sw["buy_weaknesses"],
        "sell_strengths": sw["sell_strengths"],
        "sell_weaknesses": sw["sell_weaknesses"],
        "learning_point_forward": learning_point_forward,
        "same_day_round_trip": same_day,
        "same_day_assessment": same_day_assessment,
        "same_day_soft_penalty": bool(same_day_row.get("soft_penalty")),
        "opinion_source": OPINION_SOURCE_DETERMINISTIC,
        "influences_live": False,
        "generated_at": _utcnow(),
    }


def seed_dialogue(
    item: dict[str, Any], opinion: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Initial dialogue turn: factory opinion (+ learning points)."""
    packed = opinion if isinstance(opinion, dict) else build_initial_opinion(item)
    return [
        {
            "role": "factory",
            "kind": "initial_opinion",
            "text": str(packed.get("llm_opinion") or "").strip(),
            "learning_points": list(packed.get("learning_points") or []),
            "chart_annotations": dict(packed.get("chart_annotations") or {}),
            "buy_strengths": list(packed.get("buy_strengths") or []),
            "buy_weaknesses": list(packed.get("buy_weaknesses") or []),
            "sell_strengths": list(packed.get("sell_strengths") or []),
            "sell_weaknesses": list(packed.get("sell_weaknesses") or []),
            "learning_point_forward": str(packed.get("learning_point_forward") or ""),
            "same_day_round_trip": bool(packed.get("same_day_round_trip")),
            "same_day_assessment": str(
                packed.get("same_day_assessment") or "not_applicable"
            ),
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
    item["buy_strengths"] = opinion["buy_strengths"]
    item["buy_weaknesses"] = opinion["buy_weaknesses"]
    item["sell_strengths"] = opinion["sell_strengths"]
    item["sell_weaknesses"] = opinion["sell_weaknesses"]
    item["learning_point_forward"] = opinion["learning_point_forward"]
    item["same_day_round_trip"] = opinion["same_day_round_trip"]
    item["same_day_assessment"] = opinion["same_day_assessment"]
    item["same_day_soft_penalty"] = opinion["same_day_soft_penalty"]
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
    reasons = format_decision_reasons_for_prompt(snap)
    buy_label = str(reasons["buy"].get("label") or UNKNOWN_LABEL)
    sell_label = str(reasons["sell"].get("label") or UNKNOWN_LABEL)
    sell_code = str(reasons["sell"].get("code") or "")
    sell_join = bool(reasons["sell"].get("join_ok"))
    consideration = consider_human_comment(owner_comment=owner_comment, item=snap)
    forward = str(snap.get("learning_point_forward") or "").strip()

    lines = [
        f"Acknowledged owner Comment on [{book}] {ticker} "
        f"(hold {hold_bit}, outcome {pct_bit}" + (f", {exit_kind}" if exit_kind else "") + ").",
        f'You wrote: "{comment_bit}"',
        f"Structured decision trail — bought because: {buy_label}; "
        f"sold because: {sell_label}"
        + (f" [{sell_code}]" if sell_join and sell_code else "")
        + ".",
        f"Considered your Comment ({consideration['stance']}): {consideration['why']}",
        "Development-loop read (observe / alignment only): dual-horizon charts are "
        "the surface for range-location and post-exit path claims; cite the "
        "structured buy/sell reasons above (fail-closed when unjoinable) — this "
        "card does not force knobs or fills "
        "(influences_live=false; Package M — not Package L auto-tune).",
    ]
    if forward:
        lines.append(f"Learning point forward (super-book lane candidate): {forward}")
    lines.append(
        "Accept if this reply matches what you see; Comment again to continue the mini dialogue."
    )
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
            "Cite decision_reasons.buy / decision_reasons.sell when join_ok is true; "
            "when join_ok is false say the reason is unknown/unjoinable — never invent "
            "sell-trigger IDs, filing facts, or range percentiles you were not given.",
            "Weigh owner labels like 'premature sell' against the structured sell "
            "reason (e.g. leave_buy_tier is mechanical identity exit, not a tech trigger).",
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
            "decision_reasons": format_decision_reasons_for_prompt(snap),
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
    consideration = consider_human_comment(owner_comment=owner_comment, item=item)
    fallback = build_contextual_reply_text(owner_comment=owner_comment, item=item)
    if not allow_llm:
        return {
            "text": fallback,
            "reply_kind": REPLY_SOURCE_DETERMINISTIC,
            "llm_attempted": False,
            "human_comment_consideration": consideration,
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
                text.rstrip() + "\n\n(Observe / alignment only — influences_live=false; "
                "Package M — not Package L auto-tune.)"
            )
        return {
            "text": text,
            "reply_kind": REPLY_SOURCE_LLM,
            "llm_attempted": True,
            "llm_ok": True,
            "human_comment_consideration": consideration,
            "influences_live": False,
        }
    except Exception as exc:  # noqa: BLE001 — fail closed to deterministic
        return {
            "text": fallback,
            "reply_kind": REPLY_SOURCE_DETERMINISTIC,
            "llm_attempted": True,
            "llm_ok": False,
            "llm_error": str(exc)[:240],
            "human_comment_consideration": consideration,
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
    "HUMAN_CONSIDER_AGREE",
    "HUMAN_CONSIDER_DISAGREE",
    "HUMAN_CONSIDER_PARTIAL",
    "HUMAN_CONSIDER_UNKNOWN",
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
    "consider_human_comment",
    "extend_dialogue_for_comment_reply",
    "generate_factory_reply",
    "seed_dialogue",
]
