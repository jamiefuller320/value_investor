"""N153 native-currency capital-epoch twin for non-UK shard books."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.fair_cost_lab import is_cohort_lab_track_id
from value_investor.market_paper_shard import (
    apply_epoch0_native_config,
    market_needs_native_currency_twin,
)
from value_investor.market_trading_costs import (
    cost_fields_for_config,
    cost_fields_for_native_book,
)
from value_investor.paper_automation import (
    BUY_TIER_LEVEL_NATIVE_TRACK_ID,
    BUY_TIER_LEVEL_TRACK_ID,
    default_buy_tier_level_native_config,
    ensure_automated_fund,
)
from value_investor.paper_fund import PaperFund, PaperFundConfig
from value_investor.shard_nav_fx_warp import (
    FINDING_TITLE,
    inspect_market_nav_fx,
    ops_finding_from_shard_nav_fx_warp,
    update_shard_nav_fx_warp,
)


def test_native_config_is_usd_for_sp500_with_no_fx_friction():
    cfg = default_buy_tier_level_native_config("sp500")
    assert cfg.track_id == BUY_TIER_LEVEL_NATIVE_TRACK_ID
    assert cfg.reporting_currency == "USD"
    assert cfg.is_cohort_lab is True
    assert is_cohort_lab_track_id(BUY_TIER_LEVEL_NATIVE_TRACK_ID)
    gbp_funded = cost_fields_for_config("sp500")
    native = cost_fields_for_native_book("sp500")
    assert native["buy_cost_pct"] < gbp_funded["buy_cost_pct"]
    assert cfg.buy_cost_pct == native["buy_cost_pct"]
    assert market_needs_native_currency_twin("sp500") is True
    assert market_needs_native_currency_twin("ftse_smallcap") is False


def test_apply_epoch0_native_writes_cold_start_config(tmp_path: Path):
    shard = tmp_path / "markets" / "sp500"
    session = {
        "market_id": "sp500",
        "timezone": "America/New_York",
        "market_open": "09:30",
        "settle_minutes_after_open": 30,
        "weekdays_only": False,
    }
    track_dir = apply_epoch0_native_config(shard, session)
    assert track_dir is not None
    cfg = json.loads((track_dir / "config.json").read_text(encoding="utf-8"))
    assert cfg["track_id"] == BUY_TIER_LEVEL_NATIVE_TRACK_ID
    assert cfg["reporting_currency"] == "USD"
    assert not (track_dir / "automated_fund.json").exists()
    provenance = json.loads(
        (track_dir / "native_currency_provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["parent_track_id"] == BUY_TIER_LEVEL_TRACK_ID
    assert provenance["warm_start"] is False
    assert provenance["capital_epoch"] == "n153_native_currency"
    # UK markets skip the twin.
    assert (
        apply_epoch0_native_config(tmp_path / "ftse_smallcap", {"market_id": "ftse_smallcap"})
        is None
    )


def test_ensure_automated_fund_stamps_reporting_currency_on_create(tmp_path: Path):
    cfg = default_buy_tier_level_native_config("sp500")
    path = tmp_path / "automated_fund.json"
    fund = ensure_automated_fund(path, cfg)
    assert fund.config.reporting_currency == "USD"
    # Mid-flight sync must not rewrite reporting currency on an existing fund.
    cfg.reporting_currency = "GBP"
    fund2 = ensure_automated_fund(path, cfg)
    assert fund2.config.reporting_currency == "USD"


def test_native_usd_book_nav_does_not_day0_warp():
    fund = PaperFund.create(
        PaperFundConfig(
            name="native",
            initial_cash=1000.0,
            reporting_currency="USD",
            buy_cost_pct=0.0,
            sell_cost_pct=0.0,
            trade_cost_pct=0.0,
            max_positions=10,
        )
    )
    fund.buy(
        ticker="AAPL",
        price=100.0,
        sizing_mode="shares",
        amount=2.0,
        name="Apple",
    )
    assert fund.holdings["AAPL"].currency == "USD"
    # Even if a GBP rate is supplied for USD, reporting=USD leaves marks unconverted.
    value, _meta = fund.nav_reporting({"AAPL": 100.0}, rates={"USD": 0.75, "GBP": 1.0})
    assert abs(value - 1000.0) < 1e-6


def test_shard_nav_fx_warp_detects_gbp_collapse(tmp_path: Path):
    paper = tmp_path / "paper"
    sp = paper / "markets" / "sp500" / "buy_tier_level"
    sp.mkdir(parents=True)
    (sp / "automated_fund.json").write_text(
        json.dumps(
            {
                "config": {"reporting_currency": "GBP", "initial_cash": 1000},
                "equity_curve": [
                    {"at": "2026-09-01T14:00:00+00:00", "portfolio_value": 1000.0, "positions": 0},
                    {"at": "2026-09-02T14:00:00+00:00", "portfolio_value": 737.0, "positions": 120},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    row = inspect_market_nav_fx("sp500", paper_root=paper)
    assert row["gbp_book"]["fx_warp_detected"] is True
    assert row["warn"] is True
    assert row["native_twin"]["status"] == "missing"

    # Active native twin clears the warn.
    native = paper / "markets" / "sp500" / "buy_tier_level_native"
    native.mkdir(parents=True)
    (native / "config.json").write_text(
        '{"reporting_currency": "USD", "track_id": "buy_tier_level_native"}\n',
        encoding="utf-8",
    )
    (native / "automated_fund.json").write_text(
        json.dumps(
            {
                "config": {"reporting_currency": "USD"},
                "equity_curve": [
                    {"at": "2026-09-10T14:00:00+00:00", "portfolio_value": 1000.0, "positions": 0},
                    {"at": "2026-09-11T14:00:00+00:00", "portfolio_value": 998.0, "positions": 50},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    policy = tmp_path / "policy.json"
    policy.write_text(
        json.dumps({"ladder": {"admitted_learning_markets": ["sp500"]}}) + "\n",
        encoding="utf-8",
    )
    store = tmp_path / "shard_nav_fx_warp.json"
    payload = update_shard_nav_fx_warp(
        store_path=store,
        policy_path=policy,
        paper_root=paper,
        persist=True,
    )
    assert payload["summary"]["gbp_warp_count"] == 1
    assert payload["summary"]["native_twin_active"] == 1
    assert payload["summary"]["warn_count"] == 0
    assert ops_finding_from_shard_nav_fx_warp(payload) is None

    # Without native fills, finding fires.
    (native / "automated_fund.json").unlink()
    payload2 = update_shard_nav_fx_warp(
        store_path=store,
        policy_path=policy,
        paper_root=paper,
        persist=True,
    )
    finding = ops_finding_from_shard_nav_fx_warp(payload2)
    assert finding is not None
    assert finding["title"] == FINDING_TITLE
    assert finding["auto_fixable"] is False
