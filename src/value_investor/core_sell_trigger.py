"""When a core lot may be sold.

The core is bought because the name is in the value set. Leaving that set is
not a sell: a name that works often leaves because the price has recovered.
A price drop is not a sell either.

The core sells only when the reason for owning it has failed, and that failure
has stayed on the logged row for the book's exit-confirm screens:

- the screen signal is a hard ``avoid``
- or the research verdict says the business case is gone (``pass``, or a raw
  ``sell`` / ``avoid`` / ``exit``)

``pass`` is the research verdict this project uses for do-not-own. Caution,
neutral, a hold rank, and a lost cheapness family do not qualify. A missing
row does not qualify and does not clear a streak already under way: there is
no new fact.
"""

from __future__ import annotations

from typing import Any

HARD_AVOID_SIGNAL = "avoid"
FAILED_RESEARCH = frozenset({"pass", "sell", "avoid", "exit"})

SCREEN_AVOID = "screen_avoid"
RESEARCH_FAILED = "research_failed"


def _verdict_slug(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    line = text.splitlines()[0].strip()
    if line.startswith("verdict:"):
        line = line.split(":", 1)[1].strip()
    token = line.split()[0].strip(".,;:")
    if token.endswith("..."):
        token = token[:-3]
    return token


def core_sell_reason(row: dict[str, Any] | None) -> str | None:
    """Why this logged row fails the reason for owning the name, or None."""
    if not row:
        return None
    signal = str(row.get("signal") or "").strip().lower()
    if signal == HARD_AVOID_SIGNAL:
        return SCREEN_AVOID
    if _verdict_slug(row.get("research_verdict")) in FAILED_RESEARCH:
        return RESEARCH_FAILED
    return None


def note_thesis_streak(
    streaks: dict[str, int],
    ticker: str,
    row: dict[str, Any] | None,
) -> int:
    """Advance the failure streak. A missing row leaves the prior streak."""
    if row is None:
        return int(streaks.get(ticker, 0))
    if core_sell_reason(row):
        streaks[ticker] = int(streaks.get(ticker, 0)) + 1
    else:
        streaks[ticker] = 0
    return int(streaks[ticker])


def thesis_break_confirmed(streak: int, confirm_screens: int) -> bool:
    """True once the failure has lasted the book's exit-confirm screens."""
    return int(streak) >= max(int(confirm_screens), 1)
