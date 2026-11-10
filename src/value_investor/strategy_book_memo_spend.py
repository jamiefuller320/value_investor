"""Weekly memo spend for the strategy book, against the owner's review cadence.

Observe-only. Reads the memo job summary and the registration's
``operational_switches`` log. It does not change the flag, the budget, or
a memo. Whether a memo fed an entry decision is not tracked yet, so the
finding reports spend and skips only.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from value_investor.strategy_book_memo_job import ESTIMATED_MEMO_USD

TITLE_SPEND = "Strategy book memo spend this week"


def _spend_switch(registration: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(registration, dict):
        return None
    rows = registration.get("operational_switches")
    if not isinstance(rows, list):
        return None
    latest = None
    for row in rows:
        if isinstance(row, dict) and row.get("switch") == "spend_enabled":
            latest = row
    return latest


def _day(raw: Any) -> date | None:
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _week_key(day: date) -> str:
    iso = day.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def memo_spend_finding(
    summary: dict[str, Any],
    registration: dict[str, Any] | None,
    *,
    weekly_ops: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Info finding with the latest week's requested memos and spend. None while spend is off."""
    if not summary.get("spend_enabled"):
        return None
    moment = now or datetime.now(UTC)
    weeks = summary.get("weeks") if isinstance(summary.get("weeks"), dict) else {}
    week_key = sorted(weeks)[-1] if weeks else _week_key(moment.date())
    week = weeks.get(week_key) if isinstance(weeks.get(week_key), dict) else {}
    requested = int(week.get("requested") or 0)
    skipped = int(week.get("skipped_budget") or 0)
    needed = int(week.get("memo_needed") or 0)

    switch = _spend_switch(registration) or {}
    switched_on = _day(switch.get("at"))
    since_key = _week_key(switched_on) if switched_on else None
    total = sum(
        int((row or {}).get("requested") or 0)
        for key, row in weeks.items()
        if isinstance(row, dict) and (since_key is None or key >= since_key)
    )
    parts = [
        f"{week_key}: {requested} memos requested (${requested * ESTIMATED_MEMO_USD:.2f} "
        f"at ${ESTIMATED_MEMO_USD:.2f}), {skipped} budget skips, {needed} memo needed.",
        f"Since switch-on {switched_on.isoformat() if switched_on else 'unknown'}: "
        f"{total} memos (${total * ESTIMATED_MEMO_USD:.2f}).",
    ]
    if isinstance(weekly_ops, dict) and weekly_ops.get("weekly_ops_cap_usd") is not None:
        parts.append(
            f"weekly_ops cap ${float(weekly_ops['weekly_ops_cap_usd']):.2f}, "
            f"remaining ${float(weekly_ops.get('remaining_weekly_ops_usd') or 0.0):.2f}."
        )
    review = switch.get("review") if isinstance(switch.get("review"), dict) else {}
    due = _day(review.get("next_review_on"))
    if due is not None:
        state = "due" if moment.date() >= due else "next"
        parts.append(f"Spend-vs-use review {state} {due.isoformat()}.")
    parts.append(
        "Whether a memo fed an entry decision is not tracked yet. "
        "Observe-only; no rememo or ingest from this finding."
    )
    return {
        "severity": "info",
        "category": "research",
        "title": TITLE_SPEND,
        "summary": " ".join(parts),
        "auto_fixable": False,
    }


__all__ = ["TITLE_SPEND", "memo_spend_finding"]
