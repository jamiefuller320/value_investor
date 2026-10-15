"""Tests for sealed N210 B3 fixed-stake AI/filter judgment observe stub."""

from __future__ import annotations

from pathlib import Path

from value_investor.n210_ai_judgment_observe import (
    DEFERRED_ID,
    FINDING_TITLE,
    PIPELINE_STATUS,
    REGISTRATION_ID,
    STUB_TITLE,
    VOLUME_MIN_EPISODES,
    VOLUME_MIN_WEEKS,
    build_registration_payload,
    ops_findings_from_n210_observe,
    refresh_n210_ai_judgment_observe,
)


def test_registration_payload_fixed_stake_and_gates():
    reg = build_registration_payload()
    assert reg["registration_id"] == REGISTRATION_ID
    assert reg["deferred_id"] == DEFERRED_ID
    assert reg["observe_only"] is True
    assert reg["influences_live"] is False
    assert reg["sizing"]["mode"] == "fixed_stake"
    assert reg["sizing"]["stake_units"] == 100.0
    assert reg["sizing"]["scoreboard_unit"] == "fair_cost_episode_pct"
    assert reg["o3_volume_gate"]["completed_entry_episodes_min"] == VOLUME_MIN_EPISODES
    assert reg["o3_volume_gate"]["calendar_weeks_spanned_min"] == VOLUME_MIN_WEEKS
    assert "f8_fail_closed" in reg["constraints"]
    assert "o3_alone_first" in reg["constraints"]


def test_refresh_persists_stub_store(tmp_path: Path):
    store = tmp_path / "n210_ai_judgment_observe.json"
    reg_path = tmp_path / "n210_ai_judgment_registration.json"
    payload = refresh_n210_ai_judgment_observe(
        store_path=store,
        registration_path=reg_path,
        persist=True,
    )
    assert store.exists()
    assert reg_path.exists()
    assert payload["pipeline_status"] == PIPELINE_STATUS
    assert payload["completed_entry_episodes"] == 0
    assert payload["volume_gate"]["met"] is False
    assert payload["path_scoreboard"]["scoreboard_unit"] == "fair_cost_episode_pct"


def test_ops_findings_stub_and_refresh_titles():
    payload = refresh_n210_ai_judgment_observe(persist=False)
    titles = {f["title"] for f in ops_findings_from_n210_observe(payload)}
    assert FINDING_TITLE in titles
    assert STUB_TITLE in titles
    assert all(f["auto_fixable"] is False for f in ops_findings_from_n210_observe(payload))
