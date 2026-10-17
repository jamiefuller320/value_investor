"""SEK and HKD use the existing FX close fetch and no invented rate."""

from __future__ import annotations

import json

from value_investor.ftse_fx_pairs import fetch_sek_hkd


def test_positive_closes_are_stored_and_a_missing_close_is_not(tmp_path):
    pinned = tmp_path / "docs/data/library/macro/2026-10-16.json"
    pinned.parent.mkdir(parents=True)
    pinned.write_text('{"domains":{}}', encoding="utf-8")

    def fetcher(symbol: str) -> dict:
        if symbol == "SEKUSD=X":
            return {"symbol": symbol, "value": 0.105, "as_of": "2026-10-17"}
        return {"symbol": symbol, "value": None, "error": "no history"}

    path, missing = fetch_sek_hkd(tmp_path, fetcher=fetcher)
    assert missing == ["HKDUSD=X"]
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["domains"]["fx"]["markers"]["sek_usd"]["value"] == 0.105
    assert "hkd_usd" not in written["domains"]["fx"]["markers"]
    assert pinned.read_text(encoding="utf-8") == '{"domains":{}}'


def test_nothing_priced_writes_no_file(tmp_path):
    path, missing = fetch_sek_hkd(tmp_path, fetcher=lambda _symbol: None)
    assert path is None
    assert missing == ["SEKUSD=X", "HKDUSD=X"]
    assert list(tmp_path.rglob("*.json")) == []
