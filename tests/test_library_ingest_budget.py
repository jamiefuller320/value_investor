"""Library ingest discovery vs deepen wall-clock split."""

from __future__ import annotations

from value_investor.library_ingest_budget import (
    deadline_reached,
    discovery_prefer_tickers,
    discovery_runtime_budget,
    select_blocker_ticker,
    should_start_next_ticker,
    ticker_deadline,
    weekday_per_ticker_max_seconds,
)


def test_discovery_budget_is_quarter_of_euro_sprint_slot():
    assert discovery_runtime_budget(2700) == 675.0
    assert discovery_runtime_budget(2100) == 525.0


def test_discovery_budget_zero_when_no_runtime():
    assert discovery_runtime_budget(0) == 0.0
    assert discovery_runtime_budget(-1) == 0.0


def test_discovery_prefer_tickers_orders_thin_then_gaps():
    critical = type(
        "CP",
        (),
        {
            "thin_need_discovery": ["STR.VI"],
            "unmeasured": [],
            "zero_body": ["RAND.AS"],
            "indexed_without_body": [{"ticker": "ABI.BR"}, {"ticker": "RAND.AS"}],
        },
    )()
    assert discovery_prefer_tickers(critical) == ["STR.VI", "RAND.AS", "ABI.BR"]


def test_weekday_per_ticker_cap_disabled_for_intensive_pin():
    assert (
        weekday_per_ticker_max_seconds(
            pin_tickers=None,
            record_gap_closure=False,
        )
        == 320.0
    )
    assert (
        weekday_per_ticker_max_seconds(
            pin_tickers=["DG.PA"],
            record_gap_closure=False,
        )
        is None
    )
    assert (
        weekday_per_ticker_max_seconds(
            pin_tickers=None,
            record_gap_closure=True,
        )
        is None
    )
    assert (
        weekday_per_ticker_max_seconds(
            pin_tickers=None,
            record_gap_closure=False,
            per_ticker_max_seconds=0,
        )
        is None
    )


def test_ticker_deadline_is_min_of_slot_and_per_ticker_cap():
    started = 1000.0
    assert (
        ticker_deadline(
            slot_started=started,
            max_runtime_seconds=2700,
            per_ticker_max_seconds=320,
            now=1100.0,
        )
        == 1420.0
    )
    assert (
        ticker_deadline(
            slot_started=started,
            max_runtime_seconds=2700,
            per_ticker_max_seconds=None,
            now=1100.0,
        )
        == 3700.0
    )
    assert deadline_reached(1420.0, now=1420.0) is True
    assert deadline_reached(None, now=9999.0) is False
    assert (
        should_start_next_ticker(
            slot_started=started,
            max_runtime_seconds=2700,
            now=3656.0,
        )
        is False
    )


def test_select_blocker_ticker_prefers_first_failed_budget_or_ir():
    assert (
        select_blocker_ticker(
            [
                {"ticker": "BOL.ST", "improved": False},
                {"ticker": "DG.PA", "improved": False, "ticker_budget_hit": True},
                {"ticker": "RAND.AS", "improved": False, "ir_exhausted": True},
            ]
        )
        == "DG.PA"
    )
    assert (
        select_blocker_ticker([{"ticker": "DG.PA", "improved": True, "ticker_budget_hit": True}])
        is None
    )
