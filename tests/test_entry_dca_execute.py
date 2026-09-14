"""Tests for graduated-only entry DCA execute helpers."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from value_investor.entry_dca_execute import (
    PENDING_FILENAME,
    enable_graduated_entry_dca_execute,
    first_tranche_notional,
    resolve_cadence,
    schedule_remaining_tranches,
)
from value_investor.storage import write_json


def test_resolve_and_schedule_4x_weekly():
    cadence = resolve_cadence("dca_4x_weekly")
    assert cadence is not None
    assert cadence.tranches == 4
    assert first_tranche_notional(1000.0, cadence) == 250.0
    pending = schedule_remaining_tranches(
        ticker="AAA.L",
        sleeve_notional=1000.0,
        cadence=cadence,
        started_on=date(2026, 9, 14),
    )
    assert len(pending) == 3
    assert pending[0]["due_on"] == "2026-09-21"
    assert pending[0]["notional_gbp"] == 250.0


def test_enable_writes_graduated_config_only(tmp_path: Path):
    track = tmp_path / "graduated_allocation"
    track.mkdir()
    write_json(
        track / "config.json",
        {"track_id": "graduated_allocation", "use_graduated_allocation": True},
    )
    result = enable_graduated_entry_dca_execute(tmp_path, cadence="dca_4x_weekly")
    assert result["cadence"] == "dca_4x_weekly"
    cfg = (track / "config.json").read_text()
    assert "entry_dca_execute_cadence" in cfg
    assert (track / PENDING_FILENAME).exists()
