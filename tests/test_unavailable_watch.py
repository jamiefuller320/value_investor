"""Tests for unavailable / bypass watchlist and FIRDS MIC helpers."""

from __future__ import annotations

from pathlib import Path

from value_investor.firds_mics import filter_firds_file, ii_allowed_mics
from value_investor.unavailable_watch import (
    is_unavailable,
    load_unavailable_watch,
    mark_unavailable,
    restore_unavailable,
    unavailable_tickers,
)


def test_mark_and_restore_unavailable(tmp_path: Path):
    path = tmp_path / "unavailable_watch.json"
    payload = mark_unavailable("SAP.DE", name="SAP", reason="unavailable_on_ii", path=path)
    assert len(payload["items"]) == 1
    assert "SAP.DE" in unavailable_tickers(path)
    assert is_unavailable("sap.de", path=path)

    # Idempotent update
    mark_unavailable("SAP.DE", name="SAP SE", path=path)
    assert len(load_unavailable_watch(path)["items"]) == 1
    assert load_unavailable_watch(path)["items"][0]["name"] == "SAP SE"

    restore_unavailable("SAP.DE", path=path)
    assert unavailable_tickers(path) == set()


def test_ii_allowed_mics_skips_phone_only():
    policy = {
        "schema_version": 1,
        "exchanges": [
            {
                "ii_label": "United Kingdom",
                "yahoo_suffixes": [".L"],
                "online_dealable": True,
                "phone_only": False,
                "mics": ["XLON", "AIMX"],
            },
            {
                "ii_label": "Sweden",
                "yahoo_suffixes": [".ST"],
                "online_dealable": False,
                "phone_only": True,
                "mics": ["XSTO"],
            },
        ],
    }
    assert ii_allowed_mics(policy) == {"XLON", "AIMX"}


def test_filter_firds_csv(tmp_path: Path):
    csv_path = tmp_path / "firds.csv"
    csv_path.write_text(
        "ISIN,TradingVenue,FullName\n"
        "DE0007164600,XETR,SAP SE\n"
        "SE0000115446,XSTO,Volvo\n"
        "DE0007164600,XETR,SAP SE\n",
        encoding="utf-8",
    )
    rows = filter_firds_file(csv_path, mics={"XETR"})
    assert len(rows) == 1
    assert rows[0]["isin"] == "DE0007164600"
    assert rows[0]["mic"] == "XETR"
