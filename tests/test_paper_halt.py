"""Observe-only paper halt. The fund is not frozen."""

from value_investor.paper_fund import PaperFund, PaperFundConfig
from value_investor.paper_halt import (
    FINDING_TITLE,
    build_paper_halt,
    evaluate_fund,
    finding_for_halt,
)


def _marked(fund: PaperFund, values: list[float]) -> None:
    fund.equity_curve = [
        {"at": f"2026-01-0{i + 1}T00:00:00+00:00", "portfolio_value": value}
        for i, value in enumerate(values)
    ]


def test_thresholds_flag_drawdown_name_and_sector_without_changing_the_book():
    fund = PaperFund.create(
        PaperFundConfig(name="Auto", mode="automated", initial_cash=100, trade_cost_pct=0)
    )
    fund.buy(
        ticker="AAA.L",
        price=10,
        sizing_mode="shares",
        amount=6,
        sector="Banks",
        acted_at="2026-01-01T00:00:00+00:00",
    )
    cash_before = fund.cash
    shares_before = fund.holdings["AAA.L"].shares
    _marked(fund, [100, 70])
    row = evaluate_fund(fund, track_id="rules")
    assert row["would_halt"] is True
    assert any(item.startswith("drawdown") for item in row["breaches"])
    assert any("AAA.L" in item for item in row["breaches"])
    assert any("Banks" in item for item in row["breaches"])
    assert fund.cash == cash_before
    assert fund.holdings["AAA.L"].shares == shares_before
    assert not any("GBP" in item or "currency" in item for item in row["breaches"])


def test_single_currency_book_does_not_warn_on_fx_and_a_gbp_book_does():
    home = PaperFund.create(
        PaperFundConfig(
            name="Auto",
            mode="automated",
            initial_cash=200,
            trade_cost_pct=0,
            reporting_currency="USD",
        )
    )
    for ticker in ("AAA", "BBB", "CCC", "DDD"):
        home.buy(ticker=ticker, price=10, sizing_mode="shares", amount=4, sector="Tech")
        home.holdings[ticker].currency = "USD"
        home.holdings[ticker].sector = ticker
    _marked(home, [200, 200])
    home_row = evaluate_fund(home, track_id="sp")
    assert not any("weight" in item and "USD" in item for item in home_row["breaches"])
    assert home_row["multi_currency"] is False

    mixed = PaperFund.create(
        PaperFundConfig(name="Auto", mode="automated", initial_cash=200, trade_cost_pct=0)
    )
    for i, ticker in enumerate(("AAA.L", "BBB.L", "CCC.L", "DDD.L")):
        mixed.buy(
            ticker=ticker,
            price=10,
            sizing_mode="shares",
            amount=4,
            sector=["Banks", "Energy", "Industrials", "Utilities"][i],
        )
    mixed.holdings["AAA.L"].currency = "USD"
    mixed.holdings["BBB.L"].currency = "USD"
    mixed.holdings["CCC.L"].currency = "USD"
    _marked(mixed, [200, 200])
    row = evaluate_fund(mixed, track_id="rules")
    assert any("non-GBP" in item for item in row["breaches"])
    payload = build_paper_halt([("rules", mixed)])
    finding = finding_for_halt(payload)
    assert finding is not None
    assert finding["title"] == FINDING_TITLE
    assert finding["auto_fixable"] is False
    assert "not frozen" in finding["summary"]


def test_quiet_book_has_no_finding():
    fund = PaperFund.create(
        PaperFundConfig(name="Auto", mode="automated", initial_cash=1000, trade_cost_pct=0)
    )
    for i, ticker in enumerate(["AAA.L", "BBB.L", "CCC.L", "DDD.L"]):
        fund.buy(
            ticker=ticker,
            price=10,
            sizing_mode="cash",
            amount=200,
            sector=["Banks", "Energy", "Industrials", "Utilities"][i],
        )
    _marked(fund, [1000, 1010])
    payload = build_paper_halt([("rules", fund)])
    assert payload["tracks"][0]["would_halt"] is False
    assert finding_for_halt(payload) is None
