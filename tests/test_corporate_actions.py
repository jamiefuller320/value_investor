"""Paper-ledger settlement of explicit splits, cash bids, and delistings."""

from datetime import date
from pathlib import Path

from value_investor.corporate_actions import (
    FINDING_TITLE,
    apply_corporate_actions,
    events_from_split_ratios,
    finding_for_funds,
    settle_fund_corporate_actions,
)
from value_investor.paper_fund import PaperFund, PaperFundConfig


def _fund() -> PaperFund:
    fund = PaperFund.create(
        PaperFundConfig(name="Auto", mode="automated", initial_cash=1000, trade_cost_pct=0.0)
    )
    fund.buy(
        ticker="AAA.L",
        price=10,
        sizing_mode="shares",
        amount=10,
        acted_at="2026-01-01T12:00:00+00:00",
    )
    return fund


def test_split_adjusts_shares_and_does_not_rewrite_marks():
    fund = _fund()
    curve = list(fund.equity_curve)
    cash = fund.cash
    result = apply_corporate_actions(
        fund,
        [
            {
                "id": "AAA.L:split",
                "ticker": "AAA.L",
                "type": "split",
                "effective_at": "2026-02-01T08:00:00+00:00",
                "ratio": 2,
            }
        ],
        as_of="2026-02-02T08:00:00+00:00",
    )
    assert result["applied"] == ["AAA.L:split"]
    assert fund.holdings["AAA.L"].shares == 20
    assert fund.holdings["AAA.L"].avg_cost == 5
    assert fund.cash == cash
    assert fund.equity_curve == curve
    again = apply_corporate_actions(
        fund,
        [
            {
                "id": "AAA.L:split",
                "ticker": "AAA.L",
                "type": "split",
                "effective_at": "2026-02-01T08:00:00+00:00",
                "ratio": 2,
            }
        ],
        as_of="2026-02-02T08:00:00+00:00",
    )
    assert again["applied"] == []
    assert fund.holdings["AAA.L"].shares == 20


def test_cash_bid_becomes_cash_and_delisting_without_cash_stays_open():
    fund = _fund()
    curve = list(fund.equity_curve)
    pending = apply_corporate_actions(
        fund,
        [
            {
                "id": "AAA.L:delist",
                "ticker": "AAA.L",
                "type": "delisting",
                "effective_at": "2026-03-01T08:00:00+00:00",
            }
        ],
        as_of="2026-03-02T08:00:00+00:00",
    )
    assert pending["unsettled"] == ["AAA.L:delist"]
    assert "AAA.L" in fund.holdings
    assert fund.unsettled_corporate_actions[0]["reason"].startswith("No cash amount")
    finding = finding_for_funds([("rules", fund)])
    assert finding is not None
    assert finding["title"] == FINDING_TITLE
    assert finding["auto_fixable"] is False

    settled = apply_corporate_actions(
        fund,
        [
            {
                "id": "AAA.L:delist",
                "ticker": "AAA.L",
                "type": "delisting",
                "effective_at": "2026-03-01T08:00:00+00:00",
                "cash_per_share": 12,
            }
        ],
        as_of="2026-03-02T08:00:00+00:00",
    )
    assert settled["applied"] == ["AAA.L:delist"]
    assert "AAA.L" not in fund.holdings
    assert fund.cash == 1000 - 100 + 120
    assert fund.unsettled_corporate_actions == []
    assert fund.equity_curve == curve
    assert finding_for_funds([("rules", fund)]) is None


def test_future_event_and_price_ratio_are_not_applied():
    fund = _fund()
    result = apply_corporate_actions(
        fund,
        [
            {
                "id": "later",
                "ticker": "AAA.L",
                "type": "cash_bid",
                "effective_at": "2026-12-01T08:00:00+00:00",
                "cash_per_share": 50,
            }
        ],
        as_of="2026-06-01T08:00:00+00:00",
    )
    assert result["applied"] == []
    assert "AAA.L" in fund.holdings
    ratios = events_from_split_ratios("AAA.L", {date(2026, 4, 1): 1.0, date(2026, 4, 2): 3.0})
    assert len(ratios) == 1
    assert ratios[0]["ratio"] == 3.0
    assert ratios[0]["type"] == "split"


def test_settle_reads_the_committed_feed(tmp_path: Path):
    fund = _fund()
    events = tmp_path / "corporate_actions.json"
    events.write_text(
        '{"events":[{"id":"bid","ticker":"AAA.L","type":"cash_bid",'
        '"effective_at":"2026-02-01T08:00:00+00:00","cash_per_share":11}]}',
        encoding="utf-8",
    )
    result = settle_fund_corporate_actions(
        fund, tmp_path, as_of="2026-02-02T08:00:00+00:00", events_path=events
    )
    assert result["applied"] == ["bid"]
    assert fund.cash == 1000 - 100 + 110
