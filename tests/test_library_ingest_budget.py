"""Library ingest discovery vs deepen wall-clock split."""

from __future__ import annotations

from value_investor.library_ingest_budget import (
    discovery_prefer_tickers,
    discovery_runtime_budget,
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
