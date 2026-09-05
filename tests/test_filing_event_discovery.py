"""Tests for the on-disk filing unknown-unknown scan."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.filing_event_discovery import (
    UNKNOWN_FILENAME,
    is_routine_filing_headline,
    run_filing_event_discovery,
)
from value_investor.news_event_journal import classify_headline


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_routine_and_known_filing_headlines():
    assert is_routine_filing_headline("Total Voting Rights")
    assert is_routine_filing_headline("Companies House accounts — accounts-with-accounts-type-group")
    assert not is_routine_filing_headline("Proposed IPO of PT AEP Nusantara")
    assert classify_headline("Appointment of Chief Financial Officer")["primary_event_type"] == (
        "leadership"
    )
    assert classify_headline("Directorate change")["primary_event_type"] == "leadership"


def test_run_filing_event_discovery_keeps_leftovers(tmp_path: Path):
    data_dir = tmp_path / "data"
    _write_json(
        data_dir / "latest.json",
        {
            "reports": [
                {
                    "ticker": "AAA.L",
                    "name": "Alpha Plc",
                    "signal": "buy",
                    "conviction_score": 0.4,
                    "sector": "Test",
                }
            ]
        },
    )
    _write_json(data_dir / "trajectory_boundary_watch.json", {"schema_version": 1, "panel": []})
    _write_json(
        data_dir / "research" / "AAA.L" / "sources" / "filings" / "filings_index.json",
        {
            "filings": [
                {
                    "id": "tvr",
                    "headline": "Total Voting Rights",
                    "period": "other",
                    "published_at": "2026-07-01T00:00:00+00:00",
                    "has_body": True,
                },
                {
                    "id": "cfo",
                    "headline": "Appointment of Chief Financial Officer",
                    "period": "other",
                    "published_at": "2026-07-02T00:00:00+00:00",
                    "has_body": True,
                },
                {
                    "id": "ipo",
                    "headline": "Proposed IPO of subsidiary plantatio",
                    "period": "other",
                    "published_at": "2026-07-03T00:00:00+00:00",
                    "has_body": True,
                },
            ]
        },
    )
    payload = run_filing_event_discovery(data_dir)
    assert payload["extra_http"] is False
    assert payload["routine_count"] == 1
    assert payload["known_event_count"] == 1
    assert payload["unknown_count"] == 1
    assert payload["samples"][0]["headline"].startswith("Proposed IPO")
    assert (data_dir / UNKNOWN_FILENAME).is_file()
