"""Observe-only investor net yield. Live FTSE signals stay on gross yield."""

from pathlib import Path

import pandas as pd

from value_investor.investor_yield import (
    FINDING_TITLE,
    UK_DIVIDEND_ORDINARY_RATE,
    attach_investor_yield,
    finding_for_library,
    net_yield,
)


def test_net_yield_isa_keeps_withholding_and_taxable_uses_the_larger_drag():
    assert net_yield(0.04, "US", "isa") == round(0.04 * 0.85, 6)
    assert net_yield(0.04, "US", "taxable") == round(
        0.04 * (1 - max(0.15, UK_DIVIDEND_ORDINARY_RATE)), 6
    )
    assert net_yield(0.04, "GB", "isa") == 0.04
    assert net_yield(0.04, "GB", "taxable") == round(0.04 * (1 - UK_DIVIDEND_ORDINARY_RATE), 6)
    assert net_yield(0.04, "ZZ", "isa") is None
    assert net_yield(None, "US", "isa") is None


def test_uk_listing_market_is_left_unchanged():
    frame = pd.DataFrame({"ticker": ["AAA.L"], "dividend_yield": [0.03], "signal": ["buy"]})
    out = attach_investor_yield(frame, "ftse350")
    assert "investor_net_yield_isa" not in out.columns
    assert out["signal"].tolist() == ["buy"]


def test_suffix_beats_the_market_default():
    frame = pd.DataFrame(
        {"ticker": ["SAP.DE", "LOCAL"], "dividend_yield": [0.02, 0.02], "signal": ["hold", "hold"]}
    )
    out = attach_investor_yield(frame, "sp500")
    assert out["investor_yield_country"].tolist() == ["DE", "US"]
    assert out["signal"].tolist() == ["hold", "hold"]


def test_finding_names_a_screen_that_lacks_the_column(tmp_path: Path):
    screen = tmp_path / "markets" / "sp500" / "screen"
    screen.mkdir(parents=True)
    (screen / "latest_signals.csv").write_text(
        "ticker,signal,dividend_yield\nA,buy,0.02\n", encoding="utf-8"
    )
    finding = finding_for_library(tmp_path)
    assert finding is not None
    assert finding["title"] == FINDING_TITLE
    assert finding["auto_fixable"] is False
    assert "sp500" in finding["summary"]
    (screen / "latest_signals.csv").write_text(
        "ticker,investor_net_yield_isa\nA,0.017\n", encoding="utf-8"
    )
    assert finding_for_library(tmp_path) is None
