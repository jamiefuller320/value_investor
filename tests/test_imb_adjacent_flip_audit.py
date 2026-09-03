"""Frozen IMB.L adjacent-flip audit (ldr-20260823-04)."""

from __future__ import annotations

from pathlib import Path

from value_investor.storage import read_json

AUDIT_PATH = Path("docs/data/imb_adjacent_flip_audit.json")


def test_imb_audit_verdict_is_screen_rotation():
    payload = read_json(AUDIT_PATH)
    assert payload["ticker"] == "IMB.L"
    assert payload["task_id"] == "ldr-20260823-04"
    assert payload["verdict"] == "screen_rotation"
    flags = payload["classification"]
    assert flags["signal_downgrade"] is False
    assert flags["stop_or_take_profit"] is False
    assert flags["three_slot_rank_rotation"] is True
    assert flags["hold_buffer_delayed_exit"] is True
    assert flags["same_replacement_both_books"] == "SN.L"
    assert flags["conviction_floor_contributed"]["rules"] is True
    assert flags["conviction_floor_contributed"]["ai_judgment"] is False


def test_imb_audit_shared_sell_date_and_notes():
    payload = read_json(AUDIT_PATH)
    for track_id in ("rules", "ai_judgment"):
        sell = payload["tracks"][track_id]["sell"]
        assert sell["acted_at"].startswith("2026-08-21")
        assert sell["trade_note"] == "Automated exit — left target set"
        assert sell["replacement"] == "SN.L"
        assert sell["in_target_set"] is False
        first = payload["tracks"][track_id]["first_outside_target"]
        assert first["acted_at"].startswith("2026-08-20")
        assert first["plan_reason"] == "No longer in the top conviction target set"
        assert first["trades"] == []


def test_imb_audit_fair_costs_are_much_smaller_than_stress():
    payload = read_json(AUDIT_PATH)
    costs = payload["fair_vs_stress_costs"]
    assert costs["fair_round_trip_pct"] == 0.0055
    assert costs["stress_trade_cost_pct"] == 0.03
    for track_id in ("rules", "ai_judgment"):
        row = costs["episode_buy_through_first_sell"][track_id]
        assert row["fair_costs"] < 2
        assert row["stress_costs"] > 15
        assert row["cost_share_of_stress_loss"] > 0.7
        assert row["fair_cash_pnl"] > row["stress_cash_pnl"]
