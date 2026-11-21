"""Trading 212 catalogue walk: stream 1 screens, stream 2 ingests buys."""

from __future__ import annotations

import json
import time
from pathlib import Path

from value_investor.catalogue_explorer import (
    VENUE_ORDER,
    complete_one,
    count_skipped_held,
    default_walk,
    explore_one,
    finding_summary,
    merge_states,
    next_unheld,
    run_one_handoff,
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


def test_buy_screen_hit_is_handed_off_before_the_next_name(tmp_path: Path):
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
        )

    first = explore_one(tmp_path, fetch=walk, instruments=_rows(), held=set())
    assert first["t212_ticker"] == "AAA_US_EQ"
    assert first["screen"]["signal"] == "buy"
    assert first["screen"]["seconds"] >= 0
    assert first["signal"] == "buy"
    assert first["screen_seconds"] == first["screen"]["seconds"]
    assert first["venue"] == "US"
    assert first["outcome"] == "saved"
    assert first["handoff"]["status"] == "pending"
    assert first["handoff_saved"] is True
    assert "full_ingest" not in first
    assert ingested == []
    saved = (tmp_path / "catalogue_explorer.json").read_text(encoding="utf-8")
    assert "pending" in saved

    second = explore_one(tmp_path, fetch=walk, instruments=_rows(), held=set())
    assert second["t212_ticker"] == "BBB_US_EQ"
    assert second["screen"]["signal"] == "hold"
    assert "handoff" not in second
    assert ingested == []

    done = run_one_handoff(tmp_path, ingest=ingest)
    assert done["action"] == "ran"
    assert done["t212_ticker"] == "AAA_US_EQ"
    assert done["status"] == "done"
    assert done["ingest"]["financial_years"] == 4
    assert ingested == ["AAA_US_EQ"]
    idle = run_one_handoff(tmp_path, ingest=ingest)
    assert idle["action"] == "idle"
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
    assert found[0].category == "ingest"
    assert "Screened 1" in found[0].summary
    assert "Buys handed off 0" in found[0].summary
    assert "Skips not recorded yet" in found[0].summary


def test_new_row_keeps_screen_seconds_and_signal(tmp_path: Path):
    state: dict = {"completed": [], "runs": []}

    def fetch(_instrument: dict) -> dict:
        return {
            "filings": [{"title": "10-K"}],
            "screen": {"signal": "strong_buy", "fits": True, "seconds": 3.25},
        }

    record = complete_one(
        state,
        {"ticker": "AAA_US_EQ", "type": "STOCK", "isin": "US1", "shortName": "Aaa"},
        fetch=fetch,
    )
    assert record["t212_ticker"] == "AAA_US_EQ"
    assert record["venue"] == "US"
    assert record["seconds"] >= 0
    assert record["screen_seconds"] == 3.25
    assert record["signal"] == "strong_buy"
    assert record["outcome"] == "saved"
    assert state["totals"]["signals"]["strong_buy"] == 1
    assert state["totals"]["screened"] == 1
    assert state["handoffs"][0]["status"] == "pending"


def test_screen_reload_keeps_a_finished_handoff(tmp_path: Path):
    (tmp_path / "catalogue_explorer.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "completed": ["OLD_US_EQ"],
                "runs": [],
                "handoffs": [
                    {
                        "t212_ticker": "OLD_US_EQ",
                        "signal": "buy",
                        "status": "pending",
                        "name": "Old",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def fetch(instrument: dict) -> dict:
        del instrument
        run_one_handoff(
            tmp_path,
            ingest=lambda *_args: {"financial_years": 1, "filings_summary": {}},
        )
        return {"filings": [], "screen": {"signal": "hold", "fits": False, "seconds": 1.5}}

    payload = explore_one(tmp_path, fetch=fetch, instruments=_rows(), held={"DE1"})
    saved = json.loads((tmp_path / "catalogue_explorer.json").read_text(encoding="utf-8"))
    assert payload["t212_ticker"] == "AAA_US_EQ"
    assert payload["signal"] == "hold"
    assert payload["screen_seconds"] == 1.5
    assert "AAA_US_EQ" in saved["completed"]
    old = next(row for row in saved["handoffs"] if row["t212_ticker"] == "OLD_US_EQ")
    assert old["status"] == "done"
    assert saved["skipped_held"] == count_skipped_held(_rows(), {"DE1"}) == 1


def test_handoff_reload_keeps_a_screen_saved_during_the_ingest(tmp_path: Path):
    (tmp_path / "catalogue_explorer.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "completed": ["AAA_US_EQ"],
                "runs": [],
                "handoffs": [
                    {
                        "t212_ticker": "AAA_US_EQ",
                        "yahoo": "AAA",
                        "signal": "buy",
                        "status": "pending",
                        "name": "Aaa",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def ingest(instrument: dict, _screen: dict, root: Path) -> dict:
        del instrument, root

        def filings(_row: dict) -> list:
            return [{"title": "10-K"}]

        explore_one(
            tmp_path,
            fetch=lambda row: default_walk(
                row,
                filings_fetch=filings,
                screen=lambda _row: {
                    "signal": "hold",
                    "fits": False,
                },
            ),
            instruments=_rows(),
            held=set(),
        )
        return {"financial_years": 2, "filings_summary": {"with_body": 1}}

    done = run_one_handoff(tmp_path, ingest=ingest)
    saved = json.loads((tmp_path / "catalogue_explorer.json").read_text(encoding="utf-8"))
    assert done["status"] == "done"
    assert done["t212_ticker"] == "AAA_US_EQ"
    assert "BBB_US_EQ" in saved["completed"]
    assert saved["handoffs"][0]["status"] == "done"


def test_merge_keeps_the_cursor_and_a_finished_ingest():
    base = {
        "completed": ["AAA_US_EQ"],
        "runs": [{"t212_ticker": "AAA_US_EQ", "at": "2026-11-21T00:00:00+00:00"}],
        "handoffs": [
            {
                "t212_ticker": "AAA_US_EQ",
                "status": "done",
                "signal": "buy",
                "ingest": {"seconds": 9},
            }
        ],
        "last": {"t212_ticker": "AAA_US_EQ", "at": "2026-11-21T00:00:00+00:00", "seconds": 1},
        "updated_at": "2026-11-21T00:01:00+00:00",
        "skipped_held": 4,
        "totals": {
            "screened": 1,
            "signals": {"buy": 1},
            "signals_n": 1,
            "screen_seconds_sum": 1.0,
            "screen_seconds_n": 1,
            "outcomes": {"saved": 1},
        },
    }
    incoming = {
        "completed": ["AAA_US_EQ", "BBB_US_EQ"],
        "runs": [
            {"t212_ticker": "AAA_US_EQ", "at": "2026-11-21T00:00:00+00:00"},
            {
                "t212_ticker": "BBB_US_EQ",
                "at": "2026-11-21T00:02:00+00:00",
                "signal": "hold",
                "screen_seconds": 2.0,
                "outcome": "miss",
                "seconds": 2.5,
                "venue": "US",
            },
        ],
        "handoffs": [
            {"t212_ticker": "AAA_US_EQ", "status": "pending", "signal": "buy"},
            {"t212_ticker": "BBB_US_EQ", "status": "pending", "signal": "hold"},
        ],
        "last": {
            "t212_ticker": "BBB_US_EQ",
            "at": "2026-11-21T00:02:00+00:00",
            "seconds": 2.5,
            "signal": "hold",
        },
        "updated_at": "2026-11-21T00:02:00+00:00",
        "skipped_held": 5,
    }
    merged = merge_states(base, incoming)
    assert merged["completed"] == ["AAA_US_EQ", "BBB_US_EQ"]
    statuses = {row["t212_ticker"]: row["status"] for row in merged["handoffs"]}
    assert statuses == {"AAA_US_EQ": "done", "BBB_US_EQ": "pending"}
    assert merged["handoffs"][0]["ingest"]["seconds"] == 9
    assert merged["last"]["t212_ticker"] == "BBB_US_EQ"
    assert merged["skipped_held"] == 5
    assert merged["totals"]["signals"]["buy"] == 1
    assert merged["totals"]["signals"]["hold"] == 1
    assert merged["totals"]["screened"] == 2
    assert merged["totals"]["screen_seconds_n"] == 2
    assert merged["totals"]["screen_seconds_sum"] == 3.0


def test_monitor_quotes_screened_names_signals_and_skips():
    summary = finding_summary(
        {
            "completed": ["AAA_US_EQ", "BBB_US_EQ"],
            "last": {
                "t212_ticker": "BBB_US_EQ",
                "venue": "US",
                "seconds": 10.0,
                "screen_seconds": 9.5,
                "signal": "buy",
                "outcome": "saved",
            },
            "runs": [
                {
                    "t212_ticker": "AAA_US_EQ",
                    "at": "t1",
                    "signal": "hold",
                    "screen_seconds": 4.0,
                    "outcome": "miss",
                },
                {
                    "t212_ticker": "BBB_US_EQ",
                    "at": "t2",
                    "signal": "buy",
                    "screen_seconds": 9.5,
                    "outcome": "saved",
                },
            ],
            "handoffs": [
                {"t212_ticker": "BBB_US_EQ", "status": "done", "signal": "buy"},
            ],
            "skipped_held": 12,
            "totals": {
                "screened": 2,
                "signals": {"hold": 1, "buy": 1},
                "signals_n": 2,
                "screen_seconds_sum": 13.5,
                "screen_seconds_n": 2,
                "outcomes": {"miss": 1, "saved": 1},
            },
        }
    )
    assert "Screened 2 catalogue names" in summary
    assert "BBB_US_EQ" in summary
    assert "10.0" in summary
    assert "screen 9.5s" in summary
    assert "signal buy" in summary
    assert "Seconds per screen 6.75 over 2" in summary
    assert "Signals: buy 1, hold 1" in summary
    assert "Buys handed off 1, ingested 1" in summary
    assert "Skips 12" in summary
