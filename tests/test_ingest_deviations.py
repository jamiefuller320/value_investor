"""Post-ingest deviation store, review, and CLI."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from value_investor.data_library_cli import main as library_main
from value_investor.ingest_deviations import (
    SHADOW_ACTION_DISMISS,
    SHADOW_ACTION_PARK,
    SHADOW_ACTION_PIN,
    annotate_deviation_with_signal_triage,
    collect_library_ingest_deviations,
    propose_signal_triage,
    record_library_ingest_deviations,
    review_ingest_deviation,
)
from value_investor.storage import read_json


def _row(
    ticker: str,
    *,
    improved: bool = False,
    ticker_budget_hit: bool = False,
    ir_exhausted: bool = False,
    iwb: int = 0,
    with_body: int = 0,
) -> dict:
    return {
        "ticker": ticker,
        "improved": improved,
        "ticker_budget_hit": ticker_budget_hit,
        "ir_exhausted": ir_exhausted,
        "after": {
            "indexed_without_body": iwb,
            "filings_with_body": with_body,
            "filings_total": with_body + iwb,
        },
    }


def test_collect_skips_productive_and_clean_rows():
    rows = collect_library_ingest_deviations(
        market_id="euro_depth",
        results=[
            _row("RAND.AS", improved=True, iwb=2),
            _row("DG.PA", ticker_budget_hit=True, improved=False, iwb=0),
        ],
    )
    assert rows == []


def test_collect_ir_exhausted_and_blocker(tmp_path: Path):
    rows = collect_library_ingest_deviations(
        market_id="euro_depth",
        results=[
            _row("ABI.BR", ir_exhausted=True, ticker_budget_hit=True, iwb=11, with_body=20),
            _row("WKL.AS", ticker_budget_hit=True, improved=False, iwb=3),
        ],
    )
    kinds = {row["ticker"]: row["kind"] for row in rows}
    assert kinds["ABI.BR"] == "ir_exhausted"
    assert kinds["WKL.AS"] == "blocker_no_improve"
    assert all(row["human_required"] is True for row in rows)
    assert "ir_rows_marked_unfetchable" in rows[0]["auto_actions"]


def test_record_dedupes_open_and_resolves_on_improve(tmp_path: Path):
    path = tmp_path / "deviations.json"
    first = record_library_ingest_deviations(
        market_id="euro_depth",
        results=[_row("ABI.BR", ir_exhausted=True, iwb=11, with_body=20)],
        path=path,
        now=datetime(2026, 9, 4, 13, 15, tzinfo=UTC),
    )
    assert first["opened"] == ["dev-euro_depth-ABI.BR-ir_exhausted"]
    second = record_library_ingest_deviations(
        market_id="euro_depth",
        results=[_row("ABI.BR", ir_exhausted=True, iwb=10, with_body=21)],
        path=path,
        now=datetime(2026, 9, 4, 16, 15, tzinfo=UTC),
    )
    assert second["opened"] == []
    assert second["refreshed"] == ["dev-euro_depth-ABI.BR-ir_exhausted"]
    assert second["open_count"] == 1
    closed = record_library_ingest_deviations(
        market_id="euro_depth",
        results=[_row("ABI.BR", improved=True, iwb=0, with_body=31)],
        improved=["ABI.BR"],
        path=path,
        now=datetime(2026, 9, 5, 7, 15, tzinfo=UTC),
    )
    assert closed["resolved"] == ["dev-euro_depth-ABI.BR-ir_exhausted"]
    assert closed["open_count"] == 0
    saved = read_json(path)
    assert saved["items"][0]["status"] == "resolved"


def test_approve_writes_pin_and_dismiss_cools_down(tmp_path: Path):
    store = tmp_path / "deviations.json"
    pins = tmp_path / "pins.json"
    record_library_ingest_deviations(
        market_id="euro_depth",
        results=[_row("WKL.AS", ticker_budget_hit=True, iwb=3)],
        path=store,
        now=datetime(2026, 9, 4, 13, 15, tzinfo=UTC),
    )
    approved = review_ingest_deviation(
        "dev-euro_depth-WKL.AS-blocker_no_improve",
        action="approve",
        path=store,
        pins_path=pins,
        now=datetime(2026, 9, 4, 15, 0, tzinfo=UTC),
    )
    assert approved["item"]["status"] == "approved"
    pin_store = read_json(pins)
    assert pin_store["pins"][0]["ticker"] == "WKL.AS"
    assert pin_store["pins"][0]["until"].startswith("2026-09-11")

    record_library_ingest_deviations(
        market_id="euro_depth",
        results=[_row("WKL.AS", ticker_budget_hit=True, iwb=3)],
        path=store,
        now=datetime(2026, 9, 4, 16, 15, tzinfo=UTC),
    )
    assert read_json(store)["open_count"] == 0

    record_library_ingest_deviations(
        market_id="euro_depth",
        results=[_row("DG.PA", ir_exhausted=True, iwb=2)],
        path=store,
        now=datetime(2026, 9, 4, 16, 15, tzinfo=UTC),
    )
    review_ingest_deviation(
        "dev-euro_depth-DG.PA-ir_exhausted",
        action="dismiss",
        path=store,
        pins_path=pins,
        now=datetime(2026, 9, 4, 16, 20, tzinfo=UTC),
    )
    again = record_library_ingest_deviations(
        market_id="euro_depth",
        results=[_row("DG.PA", ir_exhausted=True, iwb=2)],
        path=store,
        now=datetime(2026, 9, 5, 16, 15, tzinfo=UTC),
    )
    assert "dev-euro_depth-DG.PA-ir_exhausted" in again["skipped_cooldown"]
    later = record_library_ingest_deviations(
        market_id="euro_depth",
        results=[_row("DG.PA", ir_exhausted=True, iwb=2)],
        path=store,
        now=datetime(2026, 9, 4, 16, 20, tzinfo=UTC) + timedelta(hours=169),
    )
    assert "dev-euro_depth-DG.PA-ir_exhausted" in later["opened"]


def test_cli_list_and_approve(tmp_path: Path, capsys):
    store = tmp_path / "deviations.json"
    pins = tmp_path / "pins.json"
    record_library_ingest_deviations(
        market_id="euro_depth",
        results=[_row("ABI.BR", ir_exhausted=True, iwb=11)],
        path=store,
    )
    assert library_main(["ingest-deviations", "list", "--store", str(store)]) == 0
    listed = capsys.readouterr().out
    assert "dev-euro_depth-ABI.BR-ir_exhausted" in listed
    assert (
        library_main(
            [
                "ingest-deviations",
                "approve",
                "dev-euro_depth-ABI.BR-ir_exhausted",
                "--store",
                str(store),
                "--pins-path",
                str(pins),
            ]
        )
        == 0
    )
    assert read_json(pins)["pins"][0]["ticker"] == "ABI.BR"


def test_propose_signal_triage_ladder():
    strong = propose_signal_triage(signal="strong_buy", indexed_without_body=17)
    assert strong["proposed_action"] == SHADOW_ACTION_PIN
    assert strong["human_action"] == "approve"
    assert strong["observe_only"] is True

    buy = propose_signal_triage(signal="buy", indexed_without_body=17, filings_with_body=10)
    assert buy["proposed_action"] == SHADOW_ACTION_PARK
    assert buy["human_action"] == "dismiss"

    patchy = propose_signal_triage(
        signal="buy",
        indexed_without_body=2,
        filings_with_body=111,
        filings_total=116,
    )
    assert patchy["proposed_action"] == SHADOW_ACTION_PARK
    assert patchy["reason"] == "buy_patchy_leftover"

    leftover = propose_signal_triage(signal="hold")
    assert leftover["proposed_action"] == SHADOW_ACTION_DISMISS

    parked = propose_signal_triage(signal="buy", parked=True)
    assert parked["proposed_action"] == SHADOW_ACTION_DISMISS
    assert parked["reason"] == "parked_leftover"

    # strong_buy still pins even when the name is already parked.
    strong_parked = propose_signal_triage(signal="strong_buy", parked=True)
    assert strong_parked["proposed_action"] == SHADOW_ACTION_PIN
    assert strong_parked["reason"] == "strong_buy"


def test_annotate_reads_screen_csv(tmp_path: Path):
    market = tmp_path / "markets" / "tsx60" / "screen"
    market.mkdir(parents=True)
    (market / "latest_signals.csv").write_text(
        "ticker,signal,conviction_score\nSU.TO,strong_buy,0.77\nXIU.TO,hold,0.1\n",
        encoding="utf-8",
    )
    row = {
        "id": "dev-tsx60-SU.TO-ir_exhausted",
        "market_id": "tsx60",
        "ticker": "SU.TO",
        "status": "open",
        "evidence": {
            "indexed_without_body": 17,
            "filings_with_body": 31,
            "filings_total": 48,
        },
    }
    annotated = annotate_deviation_with_signal_triage(row, library_root=tmp_path)
    triage = annotated["signal_triage"]
    assert triage["proposed_action"] == SHADOW_ACTION_PIN
    assert triage["signal"] == "strong_buy"
    assert triage["screen_found"] is True
    assert triage["conviction_score"] == 0.77
