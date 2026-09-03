"""Frozen 28-day buffered-hold extension (plr-20260901-02)."""

from __future__ import annotations

from pathlib import Path

from value_investor.storage import read_json

EVIDENCE_PATH = Path("docs/data/buffered_hold_extended.json")


def test_buffered_hold_extended_keeps_exit_confirm_screens_2():
    payload = read_json(EVIDENCE_PATH)
    assert payload["task_id"] == "plr-20260901-02"
    assert payload["lookback_days"] == 28
    assert payload["observe_only"] is True
    assert payload["verdict"] == "keep_exit_confirm_screens_2"
    rules = payload["tracks"]["rules"]["comparison"]
    ai_judgment = payload["tracks"]["ai_judgment"]["comparison"]
    assert rules["trade_count_delta_lower_minus_higher"] > 0
    assert ai_judgment["trade_count_delta_lower_minus_higher"] > 0
    assert rules["cost_drag_delta_lower_minus_higher"] > 0
    assert ai_judgment["cost_drag_delta_lower_minus_higher"] > 0
    assert payload["tracks"]["rules"]["screens_1"]["trade_count"] == 23
    assert payload["tracks"]["rules"]["screens_2"]["trade_count"] == 12
