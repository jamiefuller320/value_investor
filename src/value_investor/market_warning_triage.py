"""Morning market-warning triage for the Daily hub.

Turns open market-status admission flags (and open ingest deviations) into
structured deepen / dismiss / park recommendations so operators triage in the
Daily hub instead of relying on Project chat.

Policy highlights (encoded, not optional):

* ``zero_body_stuck`` / ``unmeasured_stuck`` are **not** dismissable or
  parkable — they block ``sprint_ingest_complete``.
* Do **not** ritual-clear bare ``health=warn`` badges on sprint books; those
  are expected while filing gaps remain.
* Do **not** divert the euro fat-slot head to a spare (DAX/AEX) stall.
* Fat-slot / rate-limit sensitive deepen calls prefer **Discuss**; park /
  observe-ack paths prefer **Accept** (focus-ack). Auto-dismiss of ingest
  deviations is Phase B (deferred).
"""

from __future__ import annotations

import hashlib
from typing import Any

# Admission flags that policy forbids parking or dismissing.
NON_DISMISSABLE_FLAG_IDS = frozenset({"zero_body_stuck", "unmeasured_stuck"})
NON_PARKABLE_FLAG_IDS = frozenset({"zero_body_stuck", "unmeasured_stuck"})

# High-signal admission flags that get per-flag triage rows.
TRIAGE_FLAG_IDS = frozenset(
    {
        "zero_body_stuck",
        "unmeasured_stuck",
        "zero_improve_stall",
        "runtime_cutoff",
        "ingest_errors",
        "no_ingest_in_window",
        "awaiting_first_ingest",
    }
)

# Soft / expected flags — park (do not eng-spray or divert fat slot).
PARK_FLAG_IDS = frozenset(
    {
        "stale_buy_tier_screen",
        "no_observe_benchmark",
    }
)

SOURCE = "market_warning_triage"
TASK_FAMILY = "market-warning-triage"


def _stable_id(*parts: str) -> str:
    raw = "|".join(str(p or "").strip() for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _spare_sprint_markets(market_status: dict[str, Any]) -> set[str]:
    summary = _as_dict(market_status.get("summary"))
    spare = summary.get("spare_sprint") or {}
    out: set[str] = set()
    if isinstance(spare, dict):
        for mid in spare.values():
            text = str(mid or "").strip()
            if text:
                out.add(text)
    elif isinstance(spare, list):
        for mid in spare:
            text = str(mid or "").strip()
            if text:
                out.add(text)
    return out


def _ticker_hint(market: dict[str, Any], flag_id: str) -> str:
    health = _as_dict(market.get("filing_health"))
    if flag_id == "zero_body_stuck":
        tickers = [str(t) for t in _as_list(health.get("zero_body_tickers")) if str(t).strip()]
    elif flag_id == "unmeasured_stuck":
        tickers = [str(t) for t in _as_list(health.get("unmeasured_tickers")) if str(t).strip()]
    else:
        tickers = []
    if not tickers:
        return ""
    shown = ", ".join(tickers[:3])
    extra = f" (+{len(tickers) - 3})" if len(tickers) > 3 else ""
    return f"{shown}{extra}"


def collect_open_market_flags(
    market_status: dict[str, Any] | None,
    *,
    ingest_deviations: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Collect open market warning flags eligible for morning triage."""
    market_status = market_status if isinstance(market_status, dict) else {}
    spare = _spare_sprint_markets(market_status)
    focus_market = str(market_status.get("focus_market") or "").strip()
    flags: list[dict[str, Any]] = []
    ritual_ambers: list[str] = []

    for market in _as_list(market_status.get("markets")):
        if not isinstance(market, dict):
            continue
        market_id = str(market.get("market_id") or "").strip()
        if not market_id:
            continue
        role = str(market.get("role") or "").strip() or "other"
        is_focus = bool(market.get("is_focus")) or market_id == focus_market
        is_spare = market_id in spare
        health = str(market.get("health") or "").strip() or "ok"
        progress = _as_dict(market.get("sprint_progress"))
        admission = [
            w for w in _as_list(progress.get("admission_warnings")) if isinstance(w, dict)
        ]
        high_or_triage = [
            w
            for w in admission
            if str(w.get("id") or "") in TRIAGE_FLAG_IDS
            or str(w.get("severity") or "") == "high"
        ]

        for warning in admission:
            flag_id = str(warning.get("id") or "").strip()
            if not flag_id:
                continue
            if flag_id not in TRIAGE_FLAG_IDS and flag_id not in PARK_FLAG_IDS:
                # Unknown soft flag — park only when on a live sprint/focus book.
                if not (is_focus or is_spare or role in {"focus", "sprint", "live"}):
                    continue
            severity = str(warning.get("severity") or "warn").strip() or "warn"
            summary = str(warning.get("summary") or warning.get("message") or flag_id).strip()
            tickers = _ticker_hint(market, flag_id)
            flags.append(
                {
                    "kind": "admission_warning",
                    "flag_id": flag_id,
                    "market_id": market_id,
                    "market_label": str(market.get("label") or market_id),
                    "role": role,
                    "is_focus": is_focus,
                    "is_spare": is_spare,
                    "health": health,
                    "severity": severity,
                    "summary": summary,
                    "tickers": tickers,
                    "filing_gaps": market.get("filing_gaps"),
                }
            )

        # Bare health=warn with no triage/high admission flags → ritual amber rollup.
        if health == "warn" and not high_or_triage:
            if is_focus or is_spare or role in {"focus", "sprint"}:
                # Still surface as a park row so operators do not ritual-clear the badge.
                flags.append(
                    {
                        "kind": "health_amber",
                        "flag_id": "health_warn",
                        "market_id": market_id,
                        "market_label": str(market.get("label") or market_id),
                        "role": role,
                        "is_focus": is_focus,
                        "is_spare": is_spare,
                        "health": health,
                        "severity": "warn",
                        "summary": (
                            "health=warn with no high admission flag — expected sprint tone "
                            "while filing gaps remain; do not ritual-clear"
                        ),
                        "tickers": "",
                        "filing_gaps": market.get("filing_gaps"),
                    }
                )
            else:
                ritual_ambers.append(market_id)

    if ritual_ambers:
        shown = ", ".join(ritual_ambers[:6])
        extra = f" (+{len(ritual_ambers) - 6})" if len(ritual_ambers) > 6 else ""
        flags.append(
            {
                "kind": "health_amber_rollup",
                "flag_id": "health_warn_rollup",
                "market_id": "multi",
                "market_label": "Admitted / maintenance ambers",
                "role": "admitted",
                "is_focus": False,
                "is_spare": False,
                "health": "warn",
                "severity": "warn",
                "summary": (
                    f"health=warn on {shown}{extra} without high admission flags — "
                    "expected maintenance tone; do not ritual-clear or eng-spray"
                ),
                "tickers": "",
                "filing_gaps": None,
                "markets": ritual_ambers,
            }
        )

    for row in _as_list(_as_dict(ingest_deviations).get("items")):
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "open").strip() != "open":
            continue
        dev_id = str(row.get("id") or "").strip()
        if not dev_id:
            continue
        market_id = str(row.get("market") or row.get("market_id") or "").strip() or "unknown"
        ticker = str(row.get("ticker") or "").strip()
        triage = _as_dict(row.get("signal_triage"))
        flags.append(
            {
                "kind": "ingest_deviation",
                "flag_id": "ingest_deviation",
                "market_id": market_id,
                "market_label": market_id,
                "role": "focus" if market_id == focus_market else "other",
                "is_focus": market_id == focus_market,
                "is_spare": market_id in spare,
                "health": "warn",
                "severity": "warn",
                "summary": str(
                    row.get("summary")
                    or row.get("kind")
                    or f"Open ingest deviation {dev_id}"
                ).strip(),
                "tickers": ticker,
                "filing_gaps": None,
                "deviation_id": dev_id,
                "signal_triage": triage,
                "recommended_action": str(row.get("recommended_action") or "").strip(),
            }
        )

    return flags


def propose_triage(flag: dict[str, Any]) -> dict[str, Any]:
    """Map one open flag to deepen / dismiss / park + Accept vs Discuss preference."""
    flag_id = str(flag.get("flag_id") or "")
    kind = str(flag.get("kind") or "")
    is_focus = bool(flag.get("is_focus"))
    is_spare = bool(flag.get("is_spare"))
    market_id = str(flag.get("market_id") or "")
    tickers = str(flag.get("tickers") or "").strip()
    ticker_bit = f" ({tickers})" if tickers else ""

    dismissable = flag_id not in NON_DISMISSABLE_FLAG_IDS and kind != "ingest_deviation"
    parkable = flag_id not in NON_PARKABLE_FLAG_IDS

    # --- Ingest deviations -------------------------------------------------
    if kind == "ingest_deviation":
        triage = _as_dict(flag.get("signal_triage"))
        human = str(triage.get("human_action") or "").strip().lower()
        proposed = str(triage.get("proposed_action") or "").strip().lower()
        reason = str(triage.get("reason") or "").strip()
        dev_id = str(flag.get("deviation_id") or "")
        cli = f"ftse-library ingest-deviations dismiss {dev_id}" if dev_id else ""
        if human == "dismiss" or proposed in {"dismiss", "park_hunter", "park"}:
            return {
                "action": "dismiss",
                "dismissable": True,
                "parkable": True,
                "prefer_discuss": False,
                "accept_kind": "focus-ack",
                "rationale": (
                    f"Signal triage says dismiss{(' — ' + reason) if reason else ''}. "
                    "Do not intensive-pin or divert the euro fat slot. "
                    f"Observe-safe Accept records the triage; run `{cli}` manually "
                    "(Phase B may automate dismiss later)."
                    if cli
                    else "Signal triage says dismiss — do not intensive-pin."
                ),
                "cli_hint": cli or None,
                "href": "#automation",
            }
        # Pin / deepen path — judgment + fat-slot sensitive.
        return {
            "action": "deepen",
            "dismissable": False,
            "parkable": False,
            "prefer_discuss": True,
            "accept_kind": "focus-ack",
            "rationale": (
                f"Open deviation on {market_id}{ticker_bit} may need deepen/pin — "
                "Discuss before touching the fat slot or rate-limited sources. "
                "Do not rubber-stamp Accept as an intensive pin."
            ),
            "cli_hint": (
                f"ftse-library ingest-deviations approve {dev_id}" if dev_id else None
            ),
            "href": "#automation",
        }

    # --- Ritual / soft health ambers ---------------------------------------
    if flag_id in {"health_warn", "health_warn_rollup"} or flag_id in PARK_FLAG_IDS:
        return {
            "action": "park",
            "dismissable": True,
            "parkable": True,
            "prefer_discuss": False,
            "accept_kind": "focus-ack",
            "rationale": (
                f"{market_id}: {flag.get('summary')}. "
                "Park — do not ritual-clear the badge, eng-spray, or divert euro capacity."
            ),
            "cli_hint": None,
            "href": "#overview",
        }

    # --- Zero-body / unmeasured (cannot park or dismiss) -------------------
    if flag_id in NON_PARKABLE_FLAG_IDS:
        slot_note = (
            "This is the P2 fat-slot head — deepen on the existing euro sprint path; "
            "do not divert capacity to a spare stall."
            if is_focus
            else (
                "Spare-stream factory path — leave on spare deepen; "
                "do not steal the euro fat slot."
                if is_spare
                else "Deepen via the market's normal ingest path."
            )
        )
        # Focus deepen is a judgment / rate-limit call → Discuss.
        # Spare deepen is observe-ackable ("leave factory path; don't divert euro").
        prefer_discuss = bool(is_focus) or not is_spare
        return {
            "action": "deepen",
            "dismissable": False,
            "parkable": False,
            "prefer_discuss": prefer_discuss,
            "accept_kind": "focus-ack",
            "rationale": (
                f"{flag_id} on {market_id}{ticker_bit} blocks sprint_ingest_complete "
                f"and cannot be dismissed or parked. {slot_note} "
                + (
                    "Discuss for source/IR judgment; Accept only observes the deepen intent."
                    if prefer_discuss
                    else "Accept observes spare-factory deepen — do not divert euro capacity."
                )
            ),
            "cli_hint": None,
            "href": "#overview",
        }

    # --- Zero-improve stall ------------------------------------------------
    if flag_id == "zero_improve_stall":
        if is_spare or not is_focus:
            return {
                "action": "park",
                "dismissable": True,
                "parkable": True,
                "prefer_discuss": False,
                "accept_kind": "focus-ack",
                "rationale": (
                    f"Spare/non-focus stall on {market_id}{ticker_bit}: park the worry — "
                    "leave spare-stream factory / exhaustion; do not divert euro fat slot "
                    "or mint intensive pins from this flag alone."
                ),
                "cli_hint": None,
                "href": "#overview",
            }
        return {
            "action": "deepen",
            "dismissable": False,
            "parkable": False,
            "prefer_discuss": True,
            "accept_kind": "focus-ack",
            "rationale": (
                f"Focus-market zero_improve_stall on {market_id}{ticker_bit} — "
                "Discuss before changing fat-slot targeting or rate-limited sources."
            ),
            "cli_hint": None,
            "href": "#overview",
        }

    # --- Other high triage flags (runtime cutoff, ingest errors, …) --------
    if flag_id in TRIAGE_FLAG_IDS:
        if is_focus:
            return {
                "action": "deepen",
                "dismissable": False,
                "parkable": parkable,
                "prefer_discuss": True,
                "accept_kind": "focus-ack",
                "rationale": (
                    f"{flag_id} on focus market {market_id}{ticker_bit}: "
                    "Discuss — fat-slot / rate-limit sensitive. Do not ritual-clear."
                ),
                "cli_hint": None,
                "href": "#overview",
            }
        return {
            "action": "park",
            "dismissable": True,
            "parkable": True,
            "prefer_discuss": False,
            "accept_kind": "focus-ack",
            "rationale": (
                f"{flag_id} on {market_id}{ticker_bit} (non-focus): park / watch spare "
                "factory — do not starve the euro fat slot."
            ),
            "cli_hint": None,
            "href": "#overview",
        }

    # Fallback
    return {
        "action": "park",
        "dismissable": True,
        "parkable": True,
        "prefer_discuss": False,
        "accept_kind": "focus-ack",
        "rationale": (
            f"Unrecognized amber on {market_id}: park observe-only — "
            "do not ritual-clear or eng-spray."
        ),
        "cli_hint": None,
        "href": "#overview",
    }


def _recommendation_for_flag(
    flag: dict[str, Any],
    triage: dict[str, Any],
    *,
    priority: int,
) -> dict[str, Any]:
    market_id = str(flag.get("market_id") or "")
    flag_id = str(flag.get("flag_id") or "")
    action = str(triage.get("action") or "park")
    task_ref = f"mwarn:{market_id}:{flag_id}"
    if flag.get("kind") == "ingest_deviation":
        task_ref = f"mwarn:dev:{flag.get('deviation_id') or flag_id}"
    rid = f"rec-{_stable_id('mwarn', task_ref, action)}"
    tickers = str(flag.get("tickers") or "").strip()
    ticker_bit = f" · {tickers}" if tickers else ""
    label = str(flag.get("market_label") or market_id)
    summary = (
        f"Market warning triage → **{action}**: {label} / {flag_id}{ticker_bit}."
    )
    # Keep summary free of markdown bold for JSON consumers that echo raw text.
    summary = f"Market warning triage → {action}: {label} / {flag_id}{ticker_bit}."
    rationale = str(triage.get("rationale") or "")
    prefer_discuss = bool(triage.get("prefer_discuss"))
    dismissable = bool(triage.get("dismissable"))
    parkable = bool(triage.get("parkable"))

    options: list[str]
    if prefer_discuss:
        options = [
            "Discuss — judgment / fat-slot / rate-limit call",
            "Accept — observe-only record of deepen intent (does not dismiss or park)",
            "Do not ritual-clear the badge or divert euro capacity",
        ]
    elif action == "dismiss":
        options = [
            "Accept — observe-ack dismiss triage (run CLI if shown; Phase B may automate)",
            "Discuss — if signal triage looks wrong",
            "Do not intensive-pin from this row alone",
        ]
    else:
        options = [
            "Accept — park / observe-ack for today",
            "Discuss — only if this should become deepen",
            "Do not ritual-clear badges or starve euro fat slot",
        ]

    discuss_lines = [
        f"Discuss daily recommendation `{rid}` (market warning `{task_ref}`):",
        f"Proposed action: {action}",
        f"Market: {market_id} (focus={flag.get('is_focus')} spare={flag.get('is_spare')})",
        f"Flag: {flag_id} — {flag.get('summary')}",
        f"Rationale: {rationale}",
        f"Policy: dismissable={dismissable} parkable={parkable}",
        "Suggested options:",
    ]
    for i, opt in enumerate(options, start=1):
        discuss_lines.append(f"{i}) {opt}")
    if triage.get("cli_hint"):
        discuss_lines.append(f"CLI hint: {triage['cli_hint']}")
    discuss_lines.append(
        "Context: docs/data/market_status.json + Daily hub market warning triage"
    )
    discuss_prompt = "\n".join(discuss_lines)

    accept_kind = str(triage.get("accept_kind") or "focus-ack")
    if accept_kind == "link_only":
        accept_action: dict[str, Any] = {
            "kind": "link_only",
            "payload": {"href": triage.get("href") or "#overview"},
        }
    else:
        accept_action = {
            "kind": "focus-ack",
            "payload": {
                "focus_id": task_ref,
                "decision": "accept",
                "triage_action": action,
            },
        }

    return {
        "id": rid,
        "task_id": task_ref,
        "summary": summary,
        "rationale": rationale,
        "accept_action": accept_action,
        "discuss_prompt": discuss_prompt,
        "priority": priority,
        "options": options,
        "triage_action": action,
        "prefer_discuss": prefer_discuss,
        "dismissable": dismissable,
        "parkable": parkable,
        "market_id": market_id,
        "flag_id": flag_id,
        "cli_hint": triage.get("cli_hint"),
        "work_class": "surface",
        "task_family": TASK_FAMILY,
    }


def build_market_warning_triage_items(
    *,
    market_status: dict[str, Any] | None,
    ingest_deviations: dict[str, Any] | None = None,
    closed_ids: set[str] | None = None,
    priority_start: int = 5,
    generated_at: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return ``(tasks, recommendations)`` for open market warning flags.

    Closed refs (acked today) are skipped. Prefer Discuss when
    ``prefer_discuss`` is set; Accept remains an observe-safe focus-ack.
    """
    closed_ids = closed_ids or set()
    flags = collect_open_market_flags(market_status, ingest_deviations=ingest_deviations)
    tasks: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []
    priority = priority_start

    # Stable order: focus deepen first, then spare stalls, then ritual parks,
    # then deviations.
    def _sort_key(flag: dict[str, Any]) -> tuple[int, str, str]:
        action = propose_triage(flag).get("action")
        kind_rank = {
            "deepen": 0,
            "dismiss": 1,
            "park": 2,
        }.get(str(action), 9)
        focus_rank = 0 if flag.get("is_focus") else (1 if flag.get("is_spare") else 2)
        return (focus_rank, kind_rank, f"{flag.get('market_id')}:{flag.get('flag_id')}")

    for flag in sorted(flags, key=_sort_key):
        triage = propose_triage(flag)
        market_id = str(flag.get("market_id") or "")
        flag_id = str(flag.get("flag_id") or "")
        if flag.get("kind") == "ingest_deviation":
            task_ref = f"mwarn:dev:{flag.get('deviation_id') or flag_id}"
        else:
            task_ref = f"mwarn:{market_id}:{flag_id}"
        if task_ref in closed_ids:
            continue
        rec = _recommendation_for_flag(flag, triage, priority=priority)
        recommendations.append(rec)
        action = str(triage.get("action") or "park")
        prefer_discuss = bool(triage.get("prefer_discuss"))
        title = f"{action.title()} · {flag.get('market_label') or market_id} · {flag_id}"
        tickers = str(flag.get("tickers") or "").strip()
        summary = str(flag.get("summary") or "")
        if tickers:
            summary = f"{summary} · {tickers}" if summary else tickers
        next_steps = (
            ["Discuss in Project chat — fat-slot / rate-limit judgment"]
            if prefer_discuss
            else (
                ["Accept park/dismiss triage for today"]
                if action in {"park", "dismiss"}
                else ["Review deepen path"]
            )
        )
        waiting_on: list[dict[str, Any]] = []
        if prefer_discuss:
            waiting_on.append(
                {
                    "kind": "human",
                    "ref": "discuss",
                    "detail": "judgment call — Discuss before deepening fat slot",
                }
            )
        if not triage.get("dismissable") and action == "deepen":
            waiting_on.append(
                {
                    "kind": "artifact",
                    "ref": flag_id,
                    "detail": "cannot dismiss/park — blocks sprint_ingest_complete",
                }
            )
        status = {
            "state": "waiting" if prefer_discuss else "ready",
            "label": (
                "Discuss deepen (not dismissable)"
                if prefer_discuss and not triage.get("dismissable")
                else (f"Ready to {action}" if not prefer_discuss else "Discuss preferred")
            ),
            "next_steps": next_steps,
            "waiting_on": waiting_on,
            "ready": not prefer_discuss,
            "ready_reason": None
            if prefer_discuss
            else f"observe-safe Accept → {action}",
            "blocked_reason": (
                waiting_on[0]["detail"] if prefer_discuss and waiting_on else None
            ),
            "updated_at": generated_at,
            "updated_by": "morning_builder",
        }
        tasks.append(
            {
                "task_ref": task_ref,
                "source": SOURCE,
                "work_class": "surface",
                "task_family": TASK_FAMILY,
                "priority": priority,
                "title": title,
                "summary": summary,
                "sort_bucket": "market_warn",
                "closeable": True,
                "close_action": "daily-focus-ack",
                "close_payload": {
                    "focus_id": task_ref,
                    "decision": "accept",
                    "triage_action": action,
                },
                "href": triage.get("href") or "#overview",
                "recommendation_id": rec["id"],
                "status": status,
                "closed": False,
                "triage_action": action,
                "prefer_discuss": prefer_discuss,
                "dismissable": bool(triage.get("dismissable")),
                "parkable": bool(triage.get("parkable")),
                "market_warning": {
                    "kind": flag.get("kind"),
                    "flag_id": flag_id,
                    "market_id": market_id,
                    "is_focus": bool(flag.get("is_focus")),
                    "is_spare": bool(flag.get("is_spare")),
                    "severity": flag.get("severity"),
                    "tickers": tickers or None,
                    "cli_hint": triage.get("cli_hint"),
                    "deviation_id": flag.get("deviation_id"),
                },
            }
        )
        priority += 1

    return tasks, recommendations


__all__ = [
    "NON_DISMISSABLE_FLAG_IDS",
    "NON_PARKABLE_FLAG_IDS",
    "SOURCE",
    "TASK_FAMILY",
    "build_market_warning_triage_items",
    "collect_open_market_flags",
    "propose_triage",
]
