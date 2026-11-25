"""Observe-only post-sale notes for closed primary strategy-book episodes.

One note per closed primary episode. The learning point is assembled only
from the exit rule that fired and from dates, fair-cost return, matched
excess, sessions held and the maturity flag on that episode. A missing
input leaves ``learning_point`` null. Nothing here walks, sells, or sets
``influences_live``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from value_investor.strategy_book_rules import (
    COLUMN_PRIMARY,
    EXIT_FAIL_TO_LAUNCH,
    EXIT_FLOOR,
    EXIT_REVIEW_CAP,
    EXIT_REVIEW_INSUFFICIENT,
    EXIT_THESIS,
    EXIT_TIME_CAP,
    FAIL_TO_LAUNCH_INDEX,
    MATURITY_SESSIONS,
    REASON_DECLINING,
    REASON_HEADWIND,
    REASON_RESEARCH_FAILED,
    REASON_SCREEN_AVOID,
    REVIEW_INDEXES,
    TIME_CAP_INDEX,
)

SCHEMA_VERSION = 1
NOTES_FILENAME = "strategy_book_post_sale_notes.json"
SOURCE = "strategy_book"
OPS_DOC = "docs/ops/strategy-book-reviews.md"
EXIT_DELISTED = "delisted"

# Same set as ``registered_exit_family("primary")``. A test locks the match.
PRIMARY_EXIT_FAMILY = frozenset(
    {
        EXIT_FLOOR,
        EXIT_FAIL_TO_LAUNCH,
        EXIT_TIME_CAP,
        EXIT_THESIS,
        EXIT_REVIEW_INSUFFICIENT,
        EXIT_REVIEW_CAP,
        EXIT_DELISTED,
    }
)
_THESIS_REASONS = frozenset(
    {
        REASON_DECLINING,
        REASON_HEADWIND,
        REASON_SCREEN_AVOID,
        REASON_RESEARCH_FAILED,
    }
)
_REASON_PHRASE = {
    REASON_DECLINING: "operating verdict declining",
    REASON_HEADWIND: "sector verdict headwind",
    REASON_SCREEN_AVOID: "screen signal avoid",
    REASON_RESEARCH_FAILED: "research verdict failed",
}

LEARNING_QUESTION = (
    "After each closed primary strategy-book episode, what did the registered "
    "exit rule that fired show, using only that episode's dates, exit reason, "
    "fair-cost return, matched excess, sessions held and maturity flag?"
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _day(value: Any) -> date | None:
    text = str(value or "").strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _pct3(fraction: float) -> float:
    quantized = (Decimal(str(fraction)) * Decimal(100)).quantize(
        Decimal("0.001"),
        rounding=ROUND_HALF_UP,
    )
    return float(quantized)


def _signed_fixed(fraction: float) -> str:
    return f"{_pct3(fraction):+.3f}"


def _price(value: float) -> str:
    quantized = Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return format(quantized, "f").rstrip("0").rstrip(".")


def _floor_text(fraction: float) -> str:
    body = f"{_pct3(fraction):+.3f}".rstrip("0").rstrip(".")
    if body in {"+", "-", ""}:
        body = f"{_pct3(fraction):+.3f}"
    return body + "%"


def _held_text(held: int) -> str:
    unit = "session" if held == 1 else "sessions"
    return f"Held {held} {unit}."


def _mature_text(mature: bool) -> str:
    flag = "The episode is mature." if mature else "The episode is not mature."
    return (
        f"{flag} Maturity is {MATURITY_SESSIONS} sessions from the fill "
        "to the scoring date."
    )


def _is_closed(episode: dict[str, Any]) -> bool:
    status = str(episode.get("status") or "").strip().lower()
    return status == "closed" or bool(str(episode.get("exit_session") or "").strip())


def _sale_clause(
    fill: date,
    exit_day: date,
    entry_px: float | None,
    exit_px: float | None,
) -> str:
    entry = fill.isoformat()
    sale = exit_day.isoformat()
    if entry_px is not None and exit_px is not None:
        return (
            f"The sale filled on {sale} at {_price(exit_px)} "
            f"after the {entry} fill at {_price(entry_px)}."
        )
    if exit_px is not None:
        return f"The sale filled on {sale} at {_price(exit_px)} after the {entry} fill."
    if entry_px is not None:
        return f"The sale filled on {sale} after the {entry} fill at {_price(entry_px)}."
    return f"The sale filled on {sale} after the {entry} fill."


def _outcome_clause(
    fair: float,
    excess: float,
    held: int,
    mature: bool,
) -> str:
    return (
        f"Fair-cost return {_signed_fixed(fair)}%. "
        f"Matched excess {_signed_fixed(excess)} percentage points. "
        f"{_held_text(held)} {_mature_text(mature)}"
    )


def _firing_line(
    episode: dict[str, Any],
    exit_reason: str,
    exit_day: date,
) -> dict[str, Any] | None:
    log = episode.get("decision_log")
    if not isinstance(log, list):
        return None
    chosen: dict[str, Any] | None = None
    chosen_key: tuple[str, int] | None = None
    for row in log:
        if not isinstance(row, dict):
            continue
        if str(row.get("action") or "").strip() != exit_reason:
            continue
        day = _day(row.get("session"))
        if day is None or day > exit_day:
            continue
        index = row.get("index")
        index_n = index if isinstance(index, int) and not isinstance(index, bool) else -1
        key = (day.isoformat(), index_n)
        if chosen_key is None or key >= chosen_key:
            chosen = row
            chosen_key = key
    return chosen


def _rule_evidence(
    episode: dict[str, Any],
    exit_reason: str,
    exit_day: date,
) -> tuple[list[str], dict[str, Any]]:
    """Return missing input codes and the facts the rule line actually holds."""
    missing: list[str] = []
    evidence: dict[str, Any] = {
        "rule_session": None,
        "reasons": None,
        "floor": None,
        "index": None,
        "launched": None,
    }
    if exit_reason == EXIT_DELISTED:
        signal = _day(episode.get("exit_signal_session"))
        if signal is not None and signal != exit_day:
            missing.append("exit_signal_session_mismatch")
        evidence["rule_session"] = (signal or exit_day).isoformat()
        return missing, evidence

    line = _firing_line(episode, exit_reason, exit_day)
    if line is None:
        missing.append("decision_log")
        return missing, evidence
    rule_day = _day(line.get("session"))
    if rule_day is None:
        missing.append("decision_log")
        return missing, evidence
    signal = _day(episode.get("exit_signal_session"))
    if signal is not None and signal != rule_day:
        missing.append("exit_signal_session_mismatch")
    evidence["rule_session"] = rule_day.isoformat()
    if "launched" in line and isinstance(line.get("launched"), bool):
        evidence["launched"] = line.get("launched")

    if exit_reason == EXIT_THESIS:
        raw = line.get("reasons")
        if not isinstance(raw, list) or not raw:
            missing.append("decision_log.reasons")
            return missing, evidence
        codes = [str(item).strip() for item in raw if str(item).strip()]
        if not codes or any(code not in _THESIS_REASONS for code in codes):
            missing.append("decision_log.reason_unknown")
            return missing, evidence
        evidence["reasons"] = codes
        return missing, evidence

    if exit_reason == EXIT_FLOOR:
        floor = _finite(line.get("floor"))
        if floor is None:
            missing.append("decision_log.floor")
        else:
            evidence["floor"] = floor
        if evidence["launched"] is not True:
            missing.append("decision_log.launched")
        return missing, evidence

    index = line.get("index")
    if isinstance(index, bool) or not isinstance(index, int):
        missing.append("decision_log.index")
        return missing, evidence
    evidence["index"] = index
    if exit_reason == EXIT_FAIL_TO_LAUNCH:
        if evidence["launched"] is not False:
            missing.append("decision_log.launched")
        if index < FAIL_TO_LAUNCH_INDEX:
            missing.append("decision_log.index")
    elif exit_reason == EXIT_TIME_CAP:
        if index < TIME_CAP_INDEX:
            missing.append("decision_log.index")
    elif exit_reason in {EXIT_REVIEW_INSUFFICIENT, EXIT_REVIEW_CAP}:
        if index not in REVIEW_INDEXES:
            missing.append("decision_log.index")
    return missing, evidence


def _learning_point(
    *,
    ticker: str,
    exit_reason: str,
    fill: date,
    exit_day: date,
    entry_px: float | None,
    exit_px: float | None,
    fair: float,
    excess: float,
    held: int,
    mature: bool,
    evidence: dict[str, Any],
) -> str:
    sale = _sale_clause(fill, exit_day, entry_px, exit_px)
    outcome = _outcome_clause(fair, excess, held, mature)
    rule_session = str(evidence.get("rule_session") or "")
    if exit_reason == EXIT_THESIS:
        phrases = [_REASON_PHRASE[code] for code in evidence["reasons"]]
        head = (
            f"{ticker}: the registered thesis break fired on {rule_session} "
            f"({'; '.join(phrases)})."
        )
    elif exit_reason == EXIT_FLOOR:
        head = (
            f"{ticker}: the registered floor exit fired on {rule_session} "
            f"(profit floor {_floor_text(float(evidence['floor']))})."
        )
    elif exit_reason == EXIT_FAIL_TO_LAUNCH:
        head = (
            f"{ticker}: the registered fail-to-launch exit fired on {rule_session} "
            f"(session index {evidence['index']}, not launched, at or after the "
            f"{FAIL_TO_LAUNCH_INDEX}-session wait)."
        )
    elif exit_reason == EXIT_TIME_CAP:
        head = (
            f"{ticker}: the registered time cap fired on {rule_session} "
            f"(session index {evidence['index']}, at or after {TIME_CAP_INDEX})."
        )
    elif exit_reason == EXIT_REVIEW_INSUFFICIENT:
        head = (
            f"{ticker}: the registered review exit for insufficient data fired on "
            f"{rule_session} (session index {evidence['index']})."
        )
    elif exit_reason == EXIT_REVIEW_CAP:
        head = (
            f"{ticker}: the registered review cap fired on {rule_session} "
            f"(session index {evidence['index']})."
        )
    else:
        head = f"{ticker}: the registered delisted exit fired on {exit_day.isoformat()}."
    return f"{head} {sale} {outcome}"


def _entry_px(episode: dict[str, Any], line_entry: float | None) -> float | None:
    if line_entry is not None:
        return line_entry
    for key in ("return_entry_fill", "entry_fill_first_seen"):
        value = _finite(episode.get(key))
        if value is not None:
            return value
    return None


def build_post_sale_note(episode: dict[str, Any]) -> dict[str, Any]:
    """One note. ``learning_point`` is null when an input is missing."""
    episode_id = str(episode.get("episode_id") or "").strip()
    ticker = str(episode.get("ticker") or "").strip()
    missing: list[str] = []
    if not ticker:
        missing.append("ticker")
    fill = _day(episode.get("fill_session"))
    if fill is None:
        missing.append("fill_session")
    exit_day = _day(episode.get("exit_session"))
    if exit_day is None:
        missing.append("exit_session")
    exit_reason = str(episode.get("exit_reason") or "").strip()
    if not exit_reason:
        missing.append("exit_reason")
    elif exit_reason not in PRIMARY_EXIT_FAMILY:
        missing.append("exit_reason_not_in_registered_family")
    fair = _finite(episode.get("fair_cost_return"))
    if fair is None:
        missing.append("fair_cost_return")
    excess = _finite(episode.get("matched_excess"))
    if excess is None:
        missing.append("matched_excess")
    held_raw = episode.get("held_sessions")
    held: int | None
    if isinstance(held_raw, bool) or not isinstance(held_raw, int) or held_raw < 0:
        missing.append("held_sessions")
        held = None
    else:
        held = held_raw
    mature_raw = episode.get("mature")
    mature: bool | None
    if not isinstance(mature_raw, bool):
        missing.append("mature")
        mature = None
    else:
        mature = mature_raw
    if episode.get("provenance_missing") is True:
        missing.append("provenance")

    evidence: dict[str, Any] = {
        "rule_session": None,
        "reasons": None,
        "floor": None,
        "index": None,
        "launched": None,
    }
    if exit_reason in PRIMARY_EXIT_FAMILY and exit_day is not None:
        rule_missing, evidence = _rule_evidence(episode, exit_reason, exit_day)
        missing.extend(rule_missing)
    elif exit_reason in PRIMARY_EXIT_FAMILY:
        missing.append("decision_log")

    entry_px = _entry_px(episode, None)
    line = (
        _firing_line(episode, exit_reason, exit_day)
        if exit_reason and exit_day is not None
        else None
    )
    if line is not None:
        entry_px = _entry_px(episode, _finite(line.get("entry_fill")))
    exit_px = _finite(episode.get("exit_fill"))

    point: str | None = None
    if (
        not missing
        and ticker
        and fill is not None
        and exit_day is not None
        and fair is not None
        and excess is not None
        and held is not None
        and mature is not None
    ):
        point = _learning_point(
            ticker=ticker,
            exit_reason=exit_reason,
            fill=fill,
            exit_day=exit_day,
            entry_px=entry_px,
            exit_px=exit_px,
            fair=fair,
            excess=excess,
            held=held,
            mature=mature,
            evidence=evidence,
        )

    cites: list[str] = []
    if ticker:
        cites.append(f"ticker={ticker}")
    if fill is not None:
        cites.append(f"fill_session={fill.isoformat()}")
    if exit_day is not None:
        cites.append(f"exit_session={exit_day.isoformat()}")
    if evidence.get("rule_session"):
        cites.append(f"rule_session={evidence['rule_session']}")
    if exit_reason and "exit_reason_not_in_registered_family" not in missing:
        cites.append(f"exit_reason={exit_reason}")
    if isinstance(evidence.get("reasons"), list):
        cites.append("rule_reasons=" + ",".join(evidence["reasons"]))
    if fair is not None:
        cites.append(f"fair_cost_return={fair}")
    if excess is not None:
        cites.append(f"matched_excess={excess}")
    if held is not None:
        cites.append(f"held_sessions={held}")
    if mature is not None:
        cites.append(f"mature={str(mature).lower()}")

    return {
        "note_id": episode_id,
        "episode_id": episode_id,
        "ticker": ticker or None,
        "market": episode.get("market"),
        "column": COLUMN_PRIMARY,
        "fill_session": fill.isoformat() if fill is not None else None,
        "exit_signal_session": evidence.get("rule_session"),
        "exit_session": exit_day.isoformat() if exit_day is not None else None,
        "entry_fill": entry_px,
        "exit_fill": exit_px,
        "exit_reason": exit_reason or None,
        "rule_reasons": evidence.get("reasons"),
        "fair_cost_return": fair,
        "fair_cost_return_pct": _pct3(fair) if fair is not None else None,
        "matched_excess": excess,
        "matched_excess_pp": _pct3(excess) if excess is not None else None,
        "held_sessions": held,
        "mature": mature,
        "learning_point": point,
        "learning_point_status": "grounded" if point else "insufficient_data",
        "missing_inputs": missing,
        "cites": cites,
        "influences_live": False,
        "observe_only": True,
        "counts_as_evidence": point is not None,
    }


def build_strategy_book_post_sale_notes(
    observe: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    observe_status: str = "ok",
) -> dict[str, Any]:
    """Collate primary closes. Does not write."""
    moment = now or _utcnow()
    store = observe if isinstance(observe, dict) else {}
    episodes = [row for row in (store.get("episodes") or []) if isinstance(row, dict)]
    seen: set[str] = set()
    notes: list[dict[str, Any]] = []
    skipped_blank = 0
    for episode in episodes:
        if str(episode.get("column") or "").strip() != COLUMN_PRIMARY:
            continue
        if not _is_closed(episode):
            continue
        episode_id = str(episode.get("episode_id") or "").strip()
        if not episode_id:
            skipped_blank += 1
            continue
        if episode_id in seen:
            continue
        seen.add(episode_id)
        notes.append(build_post_sale_note(episode))
    notes.sort(
        key=lambda row: (
            str(row.get("exit_session") or ""),
            str(row.get("ticker") or ""),
            str(row.get("episode_id") or ""),
        ),
        reverse=True,
    )
    grounded = sum(1 for row in notes if row.get("learning_point_status") == "grounded")
    fail_closed = len(notes) - grounded
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": moment.isoformat(),
        "source": SOURCE,
        "registration_id": store.get("registration_id"),
        "scoring_date": store.get("scoring_date"),
        "observe_status": observe_status if observe is not None else "missing",
        "influences_live": False,
        "observe_only": True,
        "opinion_llm": False,
        "auto_fixable": False,
        "mid_run_tunes": False,
        "version_review_only": True,
        "learning_question": LEARNING_QUESTION,
        "ops_doc": OPS_DOC,
        "maturity_sessions": MATURITY_SESSIONS,
        "fail_closed": (
            "A missing date, exit reason, fair-cost return, matched excess, "
            "sessions held, maturity flag, provenance, or the decision-log "
            "line for the rule that fired leaves learning_point null. "
            "No point is invented."
        ),
        "counts": {
            "primary_closed": len(notes),
            "notes": len(notes),
            "grounded": grounded,
            "fail_closed": fail_closed,
            "skipped_blank_id": skipped_blank,
        },
        "notes": notes,
    }
