"""Review-history trimming keeps the knob timeline (inception row + every apply)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from value_investor.decision_review import (
    HISTORY_KEEP,
    REVIEW_HISTORY_FILENAME,
    _append_history,
    retain_review_history,
)
from value_investor.rebalance_log import load_decision_knob_timeline, load_initial_knobs

START = datetime(2026, 7, 1, 8, 30, tzinfo=UTC)


def _row(day: int, *, applied: bool = False, max_positions: int = 5) -> dict:
    changes = {"max_positions": max_positions} if applied else {}
    return {
        "reviewed_at": (START + timedelta(days=day)).isoformat(),
        "applied": applied,
        "proposed_changes": changes,
        "knobs_before": {"max_positions": 5 if day == 0 else max_positions},
        "knobs_after": {"max_positions": max_positions},
    }


def test_short_history_is_untouched():
    rows = [_row(i) for i in range(HISTORY_KEEP)]
    assert retain_review_history(rows) == rows


def test_rolling_window_keeps_inception_and_applies():
    rows = [_row(0)] + [_row(i) for i in range(1, 10)]
    rows.append(_row(10, applied=True, max_positions=4))
    rows += [_row(i, max_positions=4) for i in range(11, 200)]

    kept = retain_review_history(rows)

    assert kept[0] is rows[0]
    assert rows[10] in kept
    assert kept[-HISTORY_KEEP:] == rows[-HISTORY_KEEP:]
    assert len(kept) == HISTORY_KEEP + 2
    assert [r["reviewed_at"] for r in kept] == sorted(r["reviewed_at"] for r in kept)


def test_proposal_without_apply_is_trimmed():
    rows = [_row(0), {**_row(1), "proposed_changes": {"max_positions": 4}}]
    rows += [_row(i) for i in range(2, 100)]
    kept = retain_review_history(rows)
    assert rows[1] not in kept


def test_append_history_keeps_knob_timeline_for_replay(tmp_path: Path):
    path = tmp_path / REVIEW_HISTORY_FILENAME
    _append_history(path, _row(0))
    _append_history(path, _row(1, applied=True, max_positions=4))
    for day in range(2, 2 + HISTORY_KEEP * 3):
        _append_history(path, _row(day, max_positions=4))

    stored = json.loads(path.read_text(encoding="utf-8"))
    assert len(stored) == HISTORY_KEEP + 2
    assert load_initial_knobs(tmp_path) == {"max_positions": 5}
    timeline = load_decision_knob_timeline(tmp_path)
    assert [knobs for _, knobs in timeline] == [{"max_positions": 4}]
