"""What each requested strategy-book memo fed.

Observe-only. Reads the memo log and the forward book's already-written
events. It tags ``action: requested`` rows and does not request a memo,
ingest, or edit a fill, a bench slot, or an exit challenger.

``fed`` is one of:

- ``fill`` — this memo was in time for the primary fill and the episode
  records it (or no episode is stored to contradict that).
- ``memo_blocked`` — this memo was in time and its verdict blocked the entry.
- ``memo_not_ready`` — this memo finished after the fill close, or was older
  than the memo age limit at that close.
- ``nothing`` — the signal never reached one of those decisions (already
  open, still pending, a shadow or control column), or a different memo was
  the one the book used.

Used is ``fill`` or ``memo_blocked``. Unused is the other two.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from value_investor.core_sell_trigger import core_sell_reason
from value_investor.decision_input_inventory import _memo_age_days
from value_investor.strategy_book_rules import (
    MEMO_MAX_AGE_DAYS,
    OBSERVE_STORE_NAME,
    UnknownMarketClose,
    session_close,
)

FED_FILL = "fill"
FED_BLOCKED = "memo_blocked"
FED_NOT_READY = "memo_not_ready"
FED_NOTHING = "nothing"
FED_VALUES = frozenset({FED_FILL, FED_BLOCKED, FED_NOT_READY, FED_NOTHING})
_USED = frozenset({FED_FILL, FED_BLOCKED})
_DECISION_RANK = {FED_FILL: 0, FED_BLOCKED: 1, FED_NOT_READY: 2}
_PRIMARY = frozenset({None, "primary"})
_KIND_TO_FED = {"filled": FED_FILL, "memo_blocked": FED_BLOCKED, "memo_not_ready": FED_NOT_READY}

MEMO_LOG_NAME = "strategy_book_memo_log.jsonl"
_UNREADABLE = "Forward book events were unreadable, so requested memos are tagged nothing."
_UNWRITTEN = "Memo log could not be tagged on this run."


def _day(raw: Any) -> date | None:
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _week_key(day: date) -> str:
    iso = day.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _parse_dt(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        parsed = raw
    else:
        text = str(raw or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _signal_key(market: Any, ticker: Any, session: Any) -> tuple[str, str, str] | None:
    market_s = str(market or "")
    ticker_s = str(ticker or "")
    day = str(session or "")[:10]
    if not market_s or not ticker_s or len(day) != 10:
        return None
    return market_s, ticker_s, day


def _blocks(verdict: Any) -> bool:
    return core_sell_reason({"research_verdict": verdict}) is not None


def index_decisions(events: list[Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Primary fill, memo_blocked, or memo_not_ready for each signal session.

    A shadow, bench, or buy-on-signal column is not an entry decision.
    """
    found: dict[tuple[str, str, str], dict[str, Any]] = {}
    for event in events:
        if not isinstance(event, dict) or event.get("column") not in _PRIMARY:
            continue
        kind = str(event.get("kind") or "")
        fed = _KIND_TO_FED.get(kind)
        if fed is None:
            continue
        key = _signal_key(event.get("market"), event.get("ticker"), event.get("session"))
        if key is None:
            continue
        current = found.get(key)
        current_fed = None if current is None else _KIND_TO_FED.get(str(current.get("kind")))
        if current_fed is None or _DECISION_RANK[fed] < _DECISION_RANK[current_fed]:
            found[key] = event
    return found


def index_episodes(episodes: list[Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    found: dict[tuple[str, str, str], dict[str, Any]] = {}
    for episode in episodes:
        if not isinstance(episode, dict) or episode.get("column") not in _PRIMARY:
            continue
        key = _signal_key(
            episode.get("market"), episode.get("ticker"), episode.get("signal_session")
        )
        if key is not None:
            found[key] = episode
    return found


def _close_of(market: Any, event: dict[str, Any]) -> datetime | None:
    day = _day(event.get("fill_session"))
    if day is None:
        return None
    try:
        return session_close(str(market), day)
    except UnknownMarketClose:
        return None


def _this_memo(row: dict[str, Any], episode: dict[str, Any] | None) -> bool | None:
    """Whether the primary episode says this signal-job memo was the one used."""
    if not isinstance(episode, dict):
        return None
    if not episode.get("memo_by_signal_job"):
        return False
    recorded = episode.get("memo_verdict")
    verdict = row.get("verdict")
    if recorded not in (None, "") and verdict not in (None, "") and str(recorded) != str(verdict):
        return False
    return True


def fed_for_row(
    row: dict[str, Any],
    *,
    decision: dict[str, Any] | None,
    episode: dict[str, Any] | None,
) -> str | None:
    """Tag for one log row. None when the row is not a requested memo."""
    if row.get("action") != "requested":
        return None
    if row.get("kind") != "signal_day":
        return FED_NOTHING
    if not isinstance(decision, dict) or decision.get("column") not in _PRIMARY:
        return FED_NOTHING
    kind = str(decision.get("kind") or "")
    close = _close_of(row.get("market"), decision)
    finished = _parse_dt(row.get("memo_finished_at"))
    late = finished is not None and close is not None and finished > close
    in_time = finished is not None and close is not None and finished <= close
    blocks = _blocks(row.get("verdict"))
    if kind == "filled":
        if late:
            return FED_NOT_READY
        used = _this_memo(row, episode)
        if in_time and not blocks and used is not False:
            return FED_FILL
        if used is True and not blocks:
            return FED_FILL
        return FED_NOTHING
    if kind == "memo_blocked":
        recorded = decision.get("verdict")
        verdict_ok = recorded in (None, "") or str(recorded) == str(row.get("verdict"))
        if blocks and verdict_ok and (in_time or close is None):
            return FED_BLOCKED
        if late:
            return FED_NOT_READY
        return FED_NOTHING
    if kind == "memo_not_ready":
        if in_time:
            age = _memo_age_days(finished, now=close)
            if age is None or age > float(MEMO_MAX_AGE_DAYS):
                return FED_NOT_READY
            return FED_NOTHING
        return FED_NOT_READY
    return FED_NOTHING


def use_totals(
    rows: list[Any],
    *,
    week_key: str,
    since_key: str | None,
) -> dict[str, dict[str, int]]:
    """Used and unused counts for one ISO week and for every week since switch-on."""

    def empty() -> dict[str, int]:
        return {
            "used": 0,
            "unused": 0,
            "fill": 0,
            "memo_blocked": 0,
            "memo_not_ready": 0,
            "nothing": 0,
        }

    week = empty()
    since = empty()
    for row in rows:
        if not isinstance(row, dict) or row.get("action") != "requested":
            continue
        day = _day(row.get("session"))
        if day is None:
            continue
        key = _week_key(day)
        fed = str(row.get("fed") or FED_NOTHING)
        if fed not in FED_VALUES:
            fed = FED_NOTHING
        boards = []
        if key == week_key:
            boards.append(week)
        if since_key is None or key >= since_key:
            boards.append(since)
        for board in boards:
            board[fed] += 1
            board["used" if fed in _USED else "unused"] += 1
    return {"week": week, "since": since}


def _read_lines(path: Path) -> list[tuple[str, dict[str, Any] | None]]:
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    lines: list[tuple[str, dict[str, Any] | None]] = []
    for raw in text.splitlines():
        if not raw.strip():
            lines.append((raw, None))
            continue
        try:
            payload = json.loads(raw)
        except ValueError:
            lines.append((raw, None))
            continue
        lines.append((raw, payload if isinstance(payload, dict) else None))
    return lines


def load_forward_book(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    """Events and episodes from the observe store. A missing file is no decisions."""
    if not path.is_file():
        return [], [], None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], [], "unreadable"
    if not isinstance(payload, dict):
        return [], [], "unreadable"
    events = payload.get("events")
    episodes = payload.get("episodes")
    event_rows = (
        [row for row in events if isinstance(row, dict)] if isinstance(events, list) else []
    )
    episode_rows = (
        [row for row in episodes if isinstance(row, dict)] if isinstance(episodes, list) else []
    )
    return event_rows, episode_rows, None


def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    temporary.replace(path)


def apply_strategy_book_memo_use(
    *,
    repo_root: Path | None = None,
    persist: bool = False,
) -> dict[str, Any]:
    """Tag requested rows. Writes the log only when a tag changes and ``persist`` is set."""
    root = Path(repo_root) if repo_root is not None else Path()
    data = root / "docs" / "data"
    log_path = data / MEMO_LOG_NAME
    events, episodes, error = load_forward_book(data / OBSERVE_STORE_NAME)
    note = _UNREADABLE if error else None
    if error:
        events, episodes = [], []
    decisions = index_decisions(events)
    episodes_by_signal = index_episodes(episodes)
    new_lines: list[str] = []
    rows: list[dict[str, Any]] = []
    changed = False
    for raw, row in _read_lines(log_path):
        if row is None:
            new_lines.append(raw)
            continue
        key = _signal_key(row.get("market"), row.get("ticker"), row.get("session"))
        fed = fed_for_row(
            row,
            decision=None if key is None else decisions.get(key),
            episode=None if key is None else episodes_by_signal.get(key),
        )
        if fed is None or row.get("fed") == fed:
            new_lines.append(raw)
            rows.append(row)
            continue
        tagged = dict(row)
        tagged["fed"] = fed
        new_lines.append(json.dumps(tagged, ensure_ascii=False, separators=(",", ":")))
        rows.append(tagged)
        changed = True
    wrote = False
    if persist and changed:
        try:
            _write_lines(log_path, new_lines)
        except OSError:
            note = _UNWRITTEN if note is None else f"{note} {_UNWRITTEN}"
        else:
            wrote = True
    return {"rows": rows, "note": note, "wrote": wrote}


def show_memo_use(*, repo_root: Path | None = None) -> dict[str, Any]:
    """Read-only totals across every requested memo. Does not write the log."""
    applied = apply_strategy_book_memo_use(repo_root=repo_root, persist=False)
    totals = use_totals(applied["rows"], week_key="", since_key=None)["since"]
    return {
        "requested": totals["used"] + totals["unused"],
        "used": totals["used"],
        "unused": totals["unused"],
        "fill": totals["fill"],
        "memo_blocked": totals["memo_blocked"],
        "memo_not_ready": totals["memo_not_ready"],
        "nothing": totals["nothing"],
        "note": applied["note"],
        "influences_live": False,
    }


__all__ = [
    "FED_BLOCKED",
    "FED_FILL",
    "FED_NOT_READY",
    "FED_NOTHING",
    "FED_VALUES",
    "MEMO_LOG_NAME",
    "apply_strategy_book_memo_use",
    "fed_for_row",
    "index_decisions",
    "index_episodes",
    "load_forward_book",
    "show_memo_use",
    "use_totals",
]
