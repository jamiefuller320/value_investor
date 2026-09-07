"""Tests for held-book vs whole-market equivalent series."""

from __future__ import annotations

from pathlib import Path

from value_investor.held_vs_market import (
    assemble_held_vs_market,
    bench_closes_for_market,
    build_held_vs_market_payload,
    densify_held_from_charts,
    empty_held_vs_market,
    load_macro_index_closes,
    merge_branch_series,
)
from value_investor.storage import write_json


def test_empty_payload_is_branch_ready():
    payload = empty_held_vs_market(market_id="ftse350", currency="GBP")
    assert payload["status"] == "empty"
    assert payload["branch_ready"] is True
    assert payload["branches"] == []
    assert payload["benchmark_ticker"] == "^FTSE"
    assert any(row["kind"] == "market" for row in payload["series"])


def test_build_payload_scales_market_by_index():
    marks = [
        {
            "date": "2026-09-01",
            "held": 1000.0,
            "nav": 1000.0,
            "held_stock": 1000.0,
            "cash": 0.0,
            "positions": 3,
            "branches": {},
        },
        {
            "date": "2026-09-02",
            "held": 1010.0,
            "nav": 1010.0,
            "held_stock": 1010.0,
            "cash": 0.0,
            "positions": 3,
            "branches": {},
        },
        {
            "date": "2026-09-03",
            "held": 990.0,
            "nav": 990.0,
            "held_stock": 990.0,
            "cash": 0.0,
            "positions": 3,
            "branches": {},
        },
    ]
    payload = build_held_vs_market_payload(
        market_id="ftse350",
        marks=marks,
        bench_closes={"2026-09-01": 100.0, "2026-09-02": 102.0, "2026-09-03": 101.0},
        currency="GBP",
    )
    assert payload["status"] == "ok"
    assert payload["market_path"] == "index_levels"
    by_date = {row["date"]: row for row in payload["points"]}
    assert by_date["2026-09-01"]["market"] == 1000.0
    assert by_date["2026-09-02"]["market"] == 1020.0
    assert by_date["2026-09-03"]["market"] == 1010.0
    assert payload["last"]["excess_pct"] == round((990.0 / 1010.0) - 1.0, 6)


def test_endpoint_fallback_when_index_missing():
    marks = [
        {
            "date": "2026-07-01",
            "held": 1000.0,
            "nav": 1000.0,
            "cash": 0.0,
            "positions": 5,
            "branches": {},
        },
        {
            "date": "2026-08-01",
            "held": 1100.0,
            "nav": 1100.0,
            "cash": 0.0,
            "positions": 5,
            "branches": {},
        },
    ]
    payload = build_held_vs_market_payload(
        market_id="sp500",
        marks=marks,
        benchmark_return=0.05,
    )
    assert payload["market_path"] == "period_return_endpoints"
    assert payload["points"][0]["market"] == 1000.0
    assert payload["points"][-1]["market"] == 1050.0
    assert payload["points"][0]["held"] == 1000.0
    assert payload["benchmark_ticker"] == "^GSPC"


def test_merge_branch_series_overlays_same_dates():
    marks = [
        {
            "date": "2026-09-01",
            "held": 1000.0,
            "nav": 1000.0,
            "cash": 0.0,
            "positions": 2,
            "branches": {},
        },
        {
            "date": "2026-09-08",
            "held": 1030.0,
            "nav": 1030.0,
            "cash": 0.0,
            "positions": 2,
            "branches": {},
        },
    ]
    payload = build_held_vs_market_payload(
        market_id="ftse350",
        marks=marks,
        bench_closes={"2026-09-01": 50.0, "2026-09-08": 51.0},
    )
    overlay = merge_branch_series(
        payload,
        branch_id="min_conviction_0.4",
        label="min_conviction 0.4",
        values={"2026-09-01": 1000.0, "2026-09-08": 1015.0},
        knobs={"min_conviction": 0.4},
    )
    assert overlay["branches"][0]["status"] == "active"
    assert overlay["points"][-1]["branches"]["min_conviction_0.4"] == 1015.0
    assert any(row["id"] == "branch:min_conviction_0.4" for row in overlay["series"])

    pending = merge_branch_series(payload, branch_id="skip_timing_wait_false", status="pending")
    assert pending["branches"][0]["status"] == "pending"
    assert pending["points"][-1]["branches"] == {}


def test_densify_current_book_from_charts_clips_to_start():
    holdings = {"AAA.L": 2.0, "BBB.L": 1.0}
    closes = {
        "AAA.L": {"2026-08-01": 10.0, "2026-09-01": 11.0, "2026-09-02": 12.0},
        "BBB.L": {"2026-08-01": 20.0, "2026-09-01": 21.0, "2026-09-02": 19.0},
    }
    rows = densify_held_from_charts(
        holdings=holdings,
        closes_by_ticker=closes,
        start_date="2026-09-01",
        cash_by_date={"2026-09-01": 0.0},
    )
    assert [row["date"] for row in rows] == ["2026-09-01", "2026-09-02"]
    assert rows[0]["held"] == 43.0  # 2*11 + 21
    assert rows[1]["held"] == 43.0  # 2*12 + 19


def test_assemble_prefers_paper_fund_over_observe(tmp_path: Path):
    fund = {
        "config": {"reporting_currency": "GBP"},
        "holdings": {"AAA.L": {"shares": 1.0}},
        "equity_curve": [
            {
                "at": "2026-09-01T08:00:00+00:00",
                "portfolio_value": 1000.0,
                "cash": 1000.0,
                "positions": 0,
            },
            {
                "at": "2026-09-01T09:30:00+00:00",
                "portfolio_value": 980.0,
                "cash": 0.0,
                "positions": 1,
            },
            {
                "at": "2026-09-02T09:30:00+00:00",
                "portfolio_value": 1005.0,
                "cash": 0.0,
                "positions": 1,
            },
        ],
    }
    observe = {
        "benchmark": "^FTSE",
        "tracks": {
            "screen_rules": {
                "benchmark_return": 0.02,
                "equity_curve": [
                    {"run_at": "2026-07-01", "portfolio_value": 998.0, "cash": 0.0, "positions": 5},
                    {
                        "run_at": "2026-08-01",
                        "portfolio_value": 1020.0,
                        "cash": 0.0,
                        "positions": 5,
                    },
                ],
            }
        },
    }
    payload = assemble_held_vs_market(
        "ftse350",
        fund=fund,
        observe=observe,
        bench_closes={"2026-09-01": 100.0, "2026-09-02": 101.0},
        currency="GBP",
    )
    assert payload["source"] == "paper_fund"
    assert payload["points"][0]["held"] == 980.0  # cash-only open collapsed same day
    assert len(payload["points"]) == 2


def test_assemble_falls_back_to_observe_sim():
    observe = {
        "tracks": {
            "screen_rules": {
                "benchmark_return": 0.1,
                "equity_curve": [
                    {"run_at": "2026-07-18", "portfolio_value": 998.0, "cash": 0.0, "positions": 5},
                    {
                        "run_at": "2026-08-02",
                        "portfolio_value": 1040.0,
                        "cash": 0.0,
                        "positions": 5,
                    },
                ],
            }
        }
    }
    payload = assemble_held_vs_market("euro_depth", observe=observe, currency="EUR")
    assert payload["source"] == "observe_sim"
    assert payload["paper_instrument"] == "observe_sim"
    assert payload["points"][-1]["market"] == round(998.0 * 1.1, 2)


def test_load_macro_index_closes(tmp_path: Path):
    write_json(
        tmp_path / "2026-09-07.json",
        {
            "domains": {
                "uk": {
                    "markers": {
                        "ftse_100": {"symbol": "^FTSE", "value": 10831.1, "as_of": "2026-09-04"}
                    }
                },
                "euro": {
                    "markers": {
                        "euro_stoxx_50": {
                            "symbol": "^STOXX50E",
                            "value": 6392.9,
                            "as_of": "2026-09-04",
                        }
                    }
                },
            }
        },
    )
    closes = load_macro_index_closes(tmp_path)
    assert closes["^FTSE"]["2026-09-04"] == 10831.1
    assert bench_closes_for_market("ftse350", macro_closes=closes)["2026-09-04"] == 10831.1
    assert bench_closes_for_market("euro_depth", macro_closes=closes)["2026-09-04"] == 6392.9
    assert bench_closes_for_market("sp500", macro_closes=closes) == {}
