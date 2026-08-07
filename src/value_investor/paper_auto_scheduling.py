"""Scheduling helpers for weekday paper-auto orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LAST_RUN_FILENAME = "last_run.json"

# London 08:00 + 75m settle = 09:15 local. Use 08:25 UTC primary dispatch so BST
# (09:25 local) and GMT (08:25 local, pre-market) both stay clear of mis-timed crons.
WEEKDAY_PAPER_UTC_HOUR = 8
WEEKDAY_PAPER_UTC_MINUTE = 25

_TRACK_LAST_RUN_RELATIVE = (
    LAST_RUN_FILENAME,
    f"ai_judgment/{LAST_RUN_FILENAME}",
    f"momentum_grace/{LAST_RUN_FILENAME}",
)


def last_run_after_settle(payload: dict[str, Any]) -> bool:
    """True when a last_run snapshot recorded a post-settle gate."""
    gate = payload.get("gate") or {}
    return bool(gate.get("after_settle"))


def load_last_run(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return raw if isinstance(raw, dict) else None


def paper_auto_artifacts_satisfied(base_dir: Path) -> bool:
    """
    True when committed paper-auto artifacts include a post-settle pass.

    ``ftse-paper-auto`` writes the same gate to every track in a run, so any
    track's ``last_run.json`` with ``after_settle`` is sufficient.
    """
    base = Path(base_dir)
    for relative in _TRACK_LAST_RUN_RELATIVE:
        payload = load_last_run(base / relative)
        if payload is None:
            continue
        if last_run_after_settle(payload):
            return True
    return False
