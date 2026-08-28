"""Tests for per-market fair trading-cost assumptions."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.market_paper_shard import apply_shard_session_to_configs, ensure_shard_meta
from value_investor.market_trading_costs import (
    FX_CONVERSION,
    HALF_SPREAD_LIQUID,
    UK_STAMP_DUTY_BUY,
    assess_paper_tracks_under_fair_costs,
    assess_trades_under_fair_costs,
    cost_fields_for_config,
    costs_for_market,
    trade_cost_pct_for_market,
)
from value_investor.paper_automation import CONFIG_FILENAME, learning_track_dirs
from value_investor.paper_fund import PaperFund, PaperFundConfig
from value_investor.trading_costs_cli import main as trading_costs_main


def test_ftse350_buy_includes_stamp_no_fx():
    model = costs_for_market("ftse350")
    assert model.stamp_duty_on_buy is True
    assert model.fx_applies is False
    assert abs(model.buy_pct - (HALF_SPREAD_LIQUID + UK_STAMP_DUTY_BUY)) < 1e-12
    assert abs(model.sell_pct - HALF_SPREAD_LIQUID) < 1e-12
    assert model.round_trip_pct == model.buy_pct + model.sell_pct


def test_sp500_fx_both_sides_no_stamp():
    model = costs_for_market("sp500")
    assert model.stamp_duty_on_buy is False
    assert model.fx_applies is True
    expected = HALF_SPREAD_LIQUID + FX_CONVERSION
    assert abs(model.buy_pct - expected) < 1e-12
    assert abs(model.sell_pct - expected) < 1e-12


def test_live_aliases_map_to_ftse350():
    assert costs_for_market(None).market_id == "ftse350"
    assert costs_for_market("live").market_id == "ftse350"
    assert costs_for_market("FTSE").market_id == "ftse350"


def test_cost_fields_for_config_asymmetric():
    fields = cost_fields_for_config("ftse350")
    assert fields["buy_cost_pct"] > fields["sell_cost_pct"]
    assert abs(fields["trade_cost_pct"] - trade_cost_pct_for_market("ftse350")) < 1e-12


def test_paper_fund_uses_asymmetric_buy_sell_costs():
    fund = PaperFund.create(
        PaperFundConfig(
            name="Asym",
            mode="manual",
            initial_cash=10_000,
            trade_cost_pct=0.03,
            buy_cost_pct=0.00525,
            sell_cost_pct=0.00025,
            max_positions=5,
        )
    )
    buy = fund.buy(
        ticker="AAA.L",
        price=10.0,
        sizing_mode="shares",
        amount=100,
    )
    assert abs(buy.cost - (1000.0 * 0.00525)) < 1e-6
    sell = fund.sell(
        ticker="AAA.L",
        price=10.0,
        sizing_mode="shares",
        amount=100,
    )
    assert abs(sell.cost - (1000.0 * 0.00025)) < 1e-6


def test_assess_trades_under_fair_costs_relief():
    trades = [
        {"id": "1", "ticker": "AAA.L", "side": "buy", "gross": 1000.0, "cost": 30.0},
        {"id": "2", "ticker": "AAA.L", "side": "sell", "gross": 1000.0, "cost": 30.0},
    ]
    result = assess_trades_under_fair_costs(trades, market_id="ftse350", contributed_capital=10_000)
    assert result["trade_count"] == 2
    assert result["recorded_costs"] == 60.0
    model = costs_for_market("ftse350")
    expected_fair = model.cost_on_gross(1000, side="buy") + model.cost_on_gross(1000, side="sell")
    assert abs(result["fair_costs"] - expected_fair) < 1e-6
    assert result["cost_drag_relief"] is not None
    assert result["cost_drag_relief"] > 0


def test_apply_shard_session_stamps_fair_costs(tmp_path: Path):
    shard_root = tmp_path / "shard"
    meta = ensure_shard_meta("euro_depth", shard_root)
    assert "trading_costs" in meta
    apply_shard_session_to_configs(shard_root, meta)
    expected = cost_fields_for_config("euro_depth")
    dirs = learning_track_dirs(shard_root)
    for track_dir in dirs.values():
        cfg = json.loads((track_dir / CONFIG_FILENAME).read_text(encoding="utf-8"))
        assert abs(float(cfg["trade_cost_pct"]) - expected["trade_cost_pct"]) < 1e-12
        assert abs(float(cfg["buy_cost_pct"]) - expected["buy_cost_pct"]) < 1e-12
        assert abs(float(cfg["sell_cost_pct"]) - expected["sell_cost_pct"]) < 1e-12
        # Must not leave the live FTSE stress default on shards.
        assert float(cfg["trade_cost_pct"]) < 0.01


def test_assess_paper_tracks_read_only(tmp_path: Path):
    root = tmp_path / "paper"
    track = root / "ai_judgment"
    track.mkdir(parents=True)
    fund = PaperFund.create(
        PaperFundConfig(
            name="AI",
            mode="automated",
            initial_cash=1000,
            trade_cost_pct=0.03,
            max_positions=3,
        )
    )
    fund.buy(ticker="AAA.L", price=10.0, sizing_mode="shares", amount=10)
    (track / "automated_fund.json").write_text(
        json.dumps(fund.to_dict(), indent=2), encoding="utf-8"
    )
    payload = assess_paper_tracks_under_fair_costs(
        root, market_id="ftse350", track_ids=["ai_judgment"]
    )
    row = payload["tracks"]["ai_judgment"]
    assert row["ok"] is True
    assert row["trade_count"] == 1
    assert row["recorded_costs"] > row["fair_costs"]
    # Config on disk unchanged.
    stored = json.loads((track / "automated_fund.json").read_text(encoding="utf-8"))
    assert stored["config"]["trade_cost_pct"] == 0.03


def test_cli_list_and_assess(tmp_path: Path, capsys):
    assert trading_costs_main(["list", "--market", "ftse350"]) == 0
    out = capsys.readouterr().out
    assert "ftse350" in out
    assert "0.525" in out or "0.5" in out

    root = tmp_path / "paper"
    root.mkdir(parents=True)
    fund = PaperFund.create(
        PaperFundConfig(name="Rules", mode="automated", initial_cash=1000, trade_cost_pct=0.03)
    )
    # rules track lives at paper root (not a rules/ subdir)
    (root / "automated_fund.json").write_text(json.dumps(fund.to_dict()), encoding="utf-8")
    assert (
        trading_costs_main(["assess", "--paper-root", str(root), "--tracks", "rules", "--json"])
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["tracks"]["rules"]["ok"] is True
