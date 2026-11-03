"""Observe-only paper halt. The fund is not frozen."""

import json
from pathlib import Path

from value_investor.assessment_model import apply_assessment_model
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


def _trade_prices(fund: PaperFund, price: float = 10.0) -> dict[str, float]:
    return {ticker: price for ticker in fund.holdings}


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
    curve_before = list(fund.equity_curve)
    row = evaluate_fund(fund, track_id="rules", prices=_trade_prices(fund))
    assert row["weight_basis"] == "marked_prices"
    assert fund.equity_curve == curve_before
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
    home_row = evaluate_fund(home, track_id="sp", prices=_trade_prices(home))
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
    mixed_prices = _trade_prices(mixed)
    row = evaluate_fund(mixed, track_id="rules", prices=mixed_prices)
    assert any("non-GBP" in item for item in row["breaches"])
    payload = build_paper_halt([("rules", mixed)], prices_by_track={"rules": mixed_prices})
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
    payload = build_paper_halt(
        [("rules", fund)],
        prices_by_track={"rules": _trade_prices(fund)},
    )
    assert payload["tracks"][0]["would_halt"] is False
    assert payload["tracks"][0]["weight_basis"] == "marked_prices"
    assert finding_for_halt(payload) is None


def test_missing_marks_do_not_fall_back_to_average_cost():
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
    _marked(fund, [100, 70])
    row = evaluate_fund(fund, track_id="rules")
    assert row["weight_basis"] == "marks_unavailable"
    assert row["max_name_weight"] is None
    assert any(item.startswith("drawdown") for item in row["breaches"])
    assert not any("AAA.L" in item for item in row["breaches"])


def test_partial_marks_do_not_mix_with_average_cost():
    fund = PaperFund.create(
        PaperFundConfig(name="Auto", mode="automated", initial_cash=100, trade_cost_pct=0)
    )
    fund.buy(ticker="AAA.L", price=10, sizing_mode="shares", amount=6, sector="Banks")
    fund.buy(ticker="BBB.L", price=10, sizing_mode="shares", amount=1, sector="Energy")
    _marked(fund, [100, 100])
    row = evaluate_fund(fund, track_id="rules", prices={"AAA.L": 100})
    assert row["weight_basis"] == "marks_unavailable"
    assert row["max_name_weight"] is None
    assert not any("AAA.L" in item or "BBB.L" in item for item in row["breaches"])


def test_a_rally_breaches_on_marks_when_cost_weight_does_not():
    fund = PaperFund.create(
        PaperFundConfig(name="Auto", mode="automated", initial_cash=1000, trade_cost_pct=0)
    )
    for i, ticker in enumerate(["AAA.L", "BBB.L", "CCC.L", "DDD.L"]):
        fund.buy(
            ticker=ticker,
            price=10,
            sizing_mode="shares",
            amount=10,
            sector=["Banks", "Energy", "Industrials", "Utilities"][i],
        )
    _marked(fund, [1000, 1000])
    cost_prices = _trade_prices(fund)
    quiet = evaluate_fund(fund, track_id="rules", prices=cost_prices)
    assert quiet["max_name_weight"] < 0.40
    assert not any("AAA.L" in item for item in quiet["breaches"])
    rally = evaluate_fund(
        fund,
        track_id="rules",
        prices={"AAA.L": 80, "BBB.L": 10, "CCC.L": 10, "DDD.L": 10},
    )
    assert rally["weight_basis"] == "marked_prices"
    assert rally["max_name_weight"] >= 0.40
    assert any("AAA.L" in item for item in rally["breaches"])
    assert fund.equity_curve[-1]["portfolio_value"] == 1000


def test_a_fall_does_not_keep_a_cost_weight_breach():
    fund = PaperFund.create(
        PaperFundConfig(name="Auto", mode="automated", initial_cash=100, trade_cost_pct=0)
    )
    fund.buy(ticker="AAA.L", price=10, sizing_mode="shares", amount=6, sector="Banks")
    _marked(fund, [100, 100])
    at_cost = evaluate_fund(fund, track_id="rules", prices={"AAA.L": 10})
    assert any("AAA.L" in item for item in at_cost["breaches"])
    halved = evaluate_fund(fund, track_id="rules", prices={"AAA.L": 3})
    assert halved["max_name_weight"] < 0.40
    assert not any("AAA.L" in item for item in halved["breaches"])


def _drawdown_fund() -> PaperFund:
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
    _marked(fund, [100, 70])
    return fund


def test_finding_excludes_frozen_tracks_but_keeps_active_heat():
    frozen_fund = _drawdown_fund()
    active_fund = _drawdown_fund()
    payload = build_paper_halt(
        [("rules", frozen_fund), ("buy_tier_level", active_fund)],
        prices_by_track={},
    )
    assert finding_for_halt(payload) is not None
    assert finding_for_halt(payload, exclude_track_ids={"rules"}) is not None
    finding = finding_for_halt(payload, exclude_track_ids={"rules"})
    assert finding is not None
    assert "buy_tier_level" in finding["summary"]
    assert "rules:" not in finding["summary"]
    assert finding_for_halt(payload, exclude_track_ids={"rules", "buy_tier_level"}) is None


def test_check_paper_halt_skips_assessment_frozen_books(tmp_path: Path):
    from value_investor.ops_monitor import check_paper_halt
    from value_investor.paper_automation import FUND_FILENAME

    paper = tmp_path / "paper_automation"
    (paper / "buy_tier_level").mkdir(parents=True)
    (paper / "buy_tier_level_dca").mkdir(parents=True)
    apply_assessment_model(
        paper,
        primary="buy_tier_level",
        control="buy_tier_level_dca",
        freeze={"rules": {"reason": "suite A retired", "superseded_by": "buy_tier_level"}},
        reason="test freeze",
    )
    (paper / FUND_FILENAME).write_text(json.dumps(_drawdown_fund().to_dict()), encoding="utf-8")
    (paper / "buy_tier_level" / FUND_FILENAME).write_text(
        json.dumps(_drawdown_fund().to_dict()), encoding="utf-8"
    )
    store = tmp_path / "paper_halt.json"
    findings = check_paper_halt(paper_root=paper, store_path=store, persist=True)
    stored = json.loads(store.read_text(encoding="utf-8"))
    halted_ids = {row["track_id"] for row in stored["tracks"] if row.get("would_halt")}
    assert "rules" in halted_ids
    assert "buy_tier_level" in halted_ids
    assert len(findings) == 1
    assert findings[0].title == FINDING_TITLE
    assert "buy_tier_level" in findings[0].summary
    assert "rules:" not in findings[0].summary


def test_check_paper_halt_silent_when_only_frozen_books_breach(tmp_path: Path):
    from value_investor.ops_monitor import check_paper_halt
    from value_investor.paper_automation import FUND_FILENAME

    paper = tmp_path / "paper_automation"
    (paper / "buy_tier_level").mkdir(parents=True)
    (paper / "buy_tier_level_dca").mkdir(parents=True)
    apply_assessment_model(
        paper,
        primary="buy_tier_level",
        control="buy_tier_level_dca",
        freeze={"rules": {"reason": "suite A retired", "superseded_by": "buy_tier_level"}},
        reason="test freeze",
    )
    (paper / FUND_FILENAME).write_text(json.dumps(_drawdown_fund().to_dict()), encoding="utf-8")
    quiet = PaperFund.create(
        PaperFundConfig(name="Auto", mode="automated", initial_cash=1000, trade_cost_pct=0)
    )
    _marked(quiet, [1000, 1010])
    (paper / "buy_tier_level" / FUND_FILENAME).write_text(
        json.dumps(quiet.to_dict()), encoding="utf-8"
    )
    findings = check_paper_halt(
        paper_root=paper, store_path=tmp_path / "paper_halt.json", persist=True
    )
    assert findings == []
