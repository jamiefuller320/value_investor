"""One-name Trading 212 catalogue explorer."""

from __future__ import annotations

import time
from pathlib import Path

from value_investor.catalogue_explorer import (
    VENUE_ORDER,
    complete_one,
    default_walk,
    explore_one,
    finding_summary,
    next_unheld,
    yahoo_ticker,
)
from value_investor.ops_monitor import check_catalogue_explorer


def _rows() -> list[dict]:
    return [
        {"ticker": "BBB_US_EQ", "type": "STOCK", "isin": "US2", "shortName": "Bee"},
        {"ticker": "AAA_US_EQ", "type": "STOCK", "isin": "US1", "shortName": "Aaa"},
        {"ticker": "ETF_US_EQ", "type": "ETF", "isin": "US9", "shortName": "Etf"},
        {"ticker": "ZZZd_EQ", "type": "STOCK", "isin": "DE1", "shortName": "Zed"},
        {"ticker": "VODl_EQ", "type": "STOCK", "isin": "GB1", "shortName": "Vodafone"},
    ]


def test_venue_order_is_us_then_xetra_then_lse_and_one_name_at_a_time():
    assert VENUE_ORDER == ("US", "DE", "LSE")
    first = next_unheld(_rows(), held=set(), completed=set())
    assert first is not None
    assert first["ticker"] == "AAA_US_EQ"
    second = next_unheld(_rows(), held={"US1"}, completed={"AAA_US_EQ"})
    assert second is not None
    assert second["ticker"] == "BBB_US_EQ"
    after_us = next_unheld(_rows(), held={"US1", "US2"}, completed=set())
    assert after_us is not None
    assert after_us["ticker"] == "ZZZd_EQ"
    lse = next_unheld(_rows(), held={"US1", "US2", "DE1"}, completed=set())
    assert lse is not None
    assert lse["ticker"] == "VODl_EQ"
    assert yahoo_ticker("VODl_EQ") == "VOD.L"
    assert yahoo_ticker("AAA_US_EQ") == "AAA"
    assert yahoo_ticker("ZZZd_EQ") == "ZZZ.DE"


def test_held_yahoo_symbol_is_skipped_and_a_miss_still_advances():
    skipped = next_unheld(_rows(), held={"VOD.L", "US1", "US2", "DE1"}, completed=set())
    assert skipped is None
    state: dict = {"completed": [], "runs": []}

    def slow(instrument: dict) -> list:
        del instrument
        time.sleep(0.02)
        return []

    record = complete_one(
        state, {"ticker": "AAA_US_EQ", "type": "STOCK", "isin": "US1"}, fetch=slow
    )
    assert record["outcome"] == "miss"
    assert record["venue"] == "US"
    assert record["seconds"] >= 0.01
    assert "AAA_US_EQ" in state["completed"]
    nxt = next_unheld(_rows(), held=set(), completed=set(state["completed"]))
    assert nxt is not None
    assert nxt["ticker"] == "BBB_US_EQ"


def test_explore_one_writes_the_timing_record(tmp_path: Path):
    def fetch(_instrument: dict) -> list:
        return [{"title": "10-K", "url": "https://example.test/10k"}]

    payload = explore_one(
        tmp_path,
        fetch=fetch,
        instruments=_rows(),
        held=set(),
    )
    assert payload["action"] == "ran"
    assert payload["t212_ticker"] == "AAA_US_EQ"
    assert "seconds" in payload
    state_path = tmp_path / "catalogue_explorer.json"
    assert state_path.exists()
    again = explore_one(tmp_path, fetch=fetch, instruments=_rows(), held=set())
    assert again["t212_ticker"] == "BBB_US_EQ"


def test_buy_screen_hit_is_ingested_before_the_next_name(tmp_path: Path):
    ingested: list[str] = []

    def filings(_instrument: dict) -> list:
        return [{"title": "10-K", "url": "https://example.test/10k"}]

    def screen(instrument: dict) -> dict:
        fits = instrument["ticker"] == "AAA_US_EQ"
        return {"signal": "buy" if fits else "hold", "fits": fits}

    def ingest(instrument: dict, _screen: dict, root: Path) -> dict:
        ingested.append(instrument["ticker"])
        target = root / "catalogue_explorer" / "research" / "AAA" / "sources"
        target.mkdir(parents=True, exist_ok=True)
        (target / "screening_snapshot.json").write_text("{}", encoding="utf-8")
        return {
            "financial_years": 4,
            "filings_summary": {"with_body": 2},
            "snapshot_path": str(target / "screening_snapshot.json"),
        }

    def walk(instrument: dict) -> dict:
        return default_walk(
            instrument,
            library_root=tmp_path,
            filings_fetch=filings,
            screen=screen,
            ingest=ingest,
        )

    first = explore_one(tmp_path, fetch=walk, instruments=_rows(), held=set())
    assert first["t212_ticker"] == "AAA_US_EQ"
    assert first["screen"]["signal"] == "buy"
    assert first["screen"]["fits"] is True
    assert first["screen"]["seconds"] >= 0
    assert first["full_ingest"]["financial_years"] == 4
    assert first["full_ingest"]["seconds"] >= 0
    assert ingested == ["AAA_US_EQ"]
    saved = tmp_path / "catalogue_explorer" / "names" / "AAA_US_EQ.json"
    assert saved.exists()
    assert "buy" in saved.read_text(encoding="utf-8")

    second = explore_one(tmp_path, fetch=walk, instruments=_rows(), held=set())
    assert second["t212_ticker"] == "BBB_US_EQ"
    assert second["screen"]["signal"] == "hold"
    assert second["full_ingest"] is None
    assert ingested == ["AAA_US_EQ"]


def test_ops_finding_is_info_and_not_auto_fixable(tmp_path: Path):
    missing = check_catalogue_explorer(state_path=tmp_path / "missing.json")
    assert len(missing) == 1
    assert missing[0].title == "Catalogue explorer"
    assert missing[0].severity == "info"
    assert missing[0].auto_fixable is False
    assert "has not started" in missing[0].summary

    path = tmp_path / "catalogue_explorer.json"
    path.write_text(
        '{"completed": ["AAA_US_EQ"], "last": {"t212_ticker": "AAA_US_EQ", '
        '"venue": "US", "seconds": 12.5, "outcome": "saved"}}',
        encoding="utf-8",
    )
    found = check_catalogue_explorer(state_path=path)
    assert found[0].auto_fixable is False
    assert "12.5" in found[0].summary
    assert "AAA_US_EQ" in found[0].summary
    assert "one at a time" in finding_summary(
        {
            "completed": ["AAA_US_EQ"],
            "last": {"t212_ticker": "AAA_US_EQ", "venue": "US", "seconds": 1, "outcome": "saved"},
        }
    )
