"""Tests for offline library screen-lite and ladder gating."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from value_investor.agent_model_policy import load_policy, save_policy
from value_investor.data_library import market_dir
from value_investor.library_ladder import run_library_ladder
from value_investor.library_screen import (
    assess_library_metrics_health,
    load_library_metrics,
    research_cap_from_budget,
    run_library_screen,
)
from value_investor.storage import read_json, write_json


def _seed_metrics(root: Path, market: str = "sp500", n: int = 30) -> None:
    rows = []
    for i in range(n):
        rows.append(
            {
                "ticker": f"T{i:03d}",
                "name": f"Test Co {i}",
                "sector": "Technology" if i % 2 == 0 else "Energy",
                "market_cap": 1e10 + i * 1e8,
                "trailing_pe": 8.0 + (i % 5),
                "forward_pe": 7.0 + (i % 4),
                "price_to_book": 0.8 + (i % 3) * 0.2,
                "dividend_yield": 0.02 + (i % 4) * 0.01,
                "current_ratio": 1.5,
                "debt_to_equity": 40.0 + i,
                "return_on_equity": 0.12,
                "return_on_assets": 0.06,
                "profit_margins": 0.1,
                "revenue_growth": 0.05,
                "earnings_growth": 0.04,
                "free_cashflow": 1e9,
                "enterprise_value": 1.2e10,
                "ebitda": 2e9,
                "ebit": 1.5e9,
                "total_revenue": 5e9,
                "total_assets": 8e9,
                "total_current_liabilities": 2e9,
                "total_debt": 1e9,
                "total_cash": 5e8,
                "ncav": 1e9,
                "last_price": 50.0 + i,
                "errors": [],
            }
        )
    path = market_dir(root, market) / "metrics" / "latest.json.gz"
    write_json(path, rows, compact=True, compress=True)
    write_json(
        market_dir(root, market) / "manifest.json",
        {
            "ticker_count": n,
            "coverage_count": n,
            "coverage_pct": 1.0,
            "tickers": [r["ticker"] for r in rows],
            "ticker_state": {
                r["ticker"]: {"last_refresh": "2026-07-16T00:00:00+00:00"} for r in rows
            },
        },
        compact=False,
    )


def test_run_library_screen_writes_artifacts(tmp_path: Path):
    root = tmp_path / "library"
    _seed_metrics(root, "sp500", n=30)
    result = run_library_screen(root, "sp500")
    assert result.summary["ticker_count"] == 30
    assert (result.screen_dir / "latest_signals.csv").exists()
    assert (result.screen_dir / "latest_shortlist.csv").exists()
    assert (result.screen_dir / "latest_summary.json").exists()
    signals = pd.read_csv(result.screen_dir / "latest_signals.csv")
    assert "signal" in signals.columns
    assert len(signals) == 30


def test_run_library_screen_iseq20_tail_market(tmp_path: Path):
    root = tmp_path / "library"
    _seed_metrics(root, "iseq20", n=20)
    result = run_library_screen(root, "iseq20")
    assert result.summary["ticker_count"] == 20


def test_assess_library_metrics_health_counts_usable(tmp_path: Path):
    root = tmp_path / "library"
    metrics_dir = market_dir(root, "sp500") / "metrics"
    metrics_dir.mkdir(parents=True)
    write_json(
        metrics_dir / "latest.json",
        [
            {"ticker": "A", "trailing_pe": 10.0},
            {"ticker": "B", "trailing_pe": None, "errors": "yahoo 401"},
        ],
        compact=False,
    )
    health = assess_library_metrics_health(root, "sp500")
    assert health["total_rows"] == 2
    assert health["usable_rows"] == 1
    assert health["honest_usable_rows"] == 1
    assert health["sample_tickers"] == ["B"]


def test_assess_iseq20_dedupes_mangled_rows_and_meets_screen_floor(tmp_path: Path):
    root = tmp_path / "library"
    market = "iseq20"
    tickers = [f"T{i}.IR" for i in range(20)]

    def _row(ticker: str, **extra: object) -> dict:
        base = {
            "ticker": ticker,
            "market_cap": 1e9,
            "trailing_pe": 12.0,
            "price_to_book": 1.5,
        }
        base.update(extra)
        return base

    metrics_dir = market_dir(root, market) / "metrics"
    metrics_dir.mkdir(parents=True)
    rows = [_row(t) for t in tickers]
    rows.extend(
        _row(t.replace(".IR", "-IR.L"), market_cap=None, trailing_pe=None, errors=["stooq fail"])
        for t in tickers
    )
    write_json(metrics_dir / "latest.json.gz", rows, compact=True, compress=True)
    write_json(
        market_dir(root, market) / "manifest.json",
        {"tickers": tickers, "ticker_count": 20},
        compact=False,
    )
    health = assess_library_metrics_health(root, market)
    assert health["total_rows"] == 20
    assert health["honest_usable_rows"] == 20
    assert health["usable_rows"] == 25
    assert health["effective_min_metrics_for_screen"] == 20

    universe = load_library_metrics(root, market)
    assert len(universe) == 20
    assert set(universe["ticker"]) == set(tickers)


def test_ladder_screens_iseq_sized_market_with_policy_min_25(tmp_path: Path):
    """Tail markets with ticker_count < policy min must still screen when fully covered."""
    root = tmp_path / "library"
    policy = tmp_path / "policy.json"
    market = "iseq20"
    _seed_metrics(root, market, n=20)
    # Rewrite tickers to look Irish while keeping full metric columns.
    metrics_path = market_dir(root, market) / "metrics" / "latest.json.gz"
    rows = read_json(metrics_path)
    for i, row in enumerate(rows):
        row["ticker"] = f"T{i:02d}.IR"
    write_json(metrics_path, rows, compact=True, compress=True)
    tickers = [r["ticker"] for r in rows]
    write_json(
        market_dir(root, market) / "manifest.json",
        {
            "market": market,
            "ticker_count": 20,
            "coverage_count": 20,
            "coverage_pct": 1.0,
            "tickers": tickers,
            "ticker_state": {t: {"last_refresh": "2026-08-16T00:00:00+00:00"} for t in tickers},
        },
        compact=False,
    )
    base = load_policy(policy)
    base["focus_market"] = market
    base["market_queue"] = [market]
    base["graduated_markets"] = []
    base["ladder"] = {
        "min_metrics_for_screen": 25,
        "research_hard_cap": 0,
        "observe_sim_after_screen": False,
        "research_all_graduated": False,
    }
    save_policy(base, policy)

    payload = run_library_ladder(
        root=root,
        policy_path=policy,
        skip_grow=True,
        skip_research=True,
    )
    screen = payload["layers"]["screen_lite"]
    assert not screen.get("skipped"), screen
    assert screen.get("ticker_count") == 20


def test_research_cap_from_budget():
    assert research_cap_from_budget(remaining_usd=2.0, estimated_memo_usd=0.4) == 5  # hard_cap
    assert research_cap_from_budget(remaining_usd=1.6, estimated_memo_usd=0.4) == 4
    assert research_cap_from_budget(remaining_usd=0.3, estimated_memo_usd=0.4) == 0
    assert research_cap_from_budget(remaining_usd=0.0, estimated_memo_usd=0.4, surplus=True) == 1


def test_ladder_screen_without_research(tmp_path: Path, monkeypatch):
    root = tmp_path / "library"
    policy = tmp_path / "policy.json"
    _seed_metrics(root, "sp500", n=30)
    base = load_policy(policy)
    base["focus_market"] = "sp500"
    base["budget"]["plan_refresh_day_of_month"] = 8
    base["budget"]["plan_monthly_usd"] = 20
    base["ladder"] = {
        "min_metrics_for_screen": 25,
        "research_hard_cap": 5,
        "observe_sim_after_screen": False,
    }
    save_policy(base, policy)

    # Avoid Yahoo grow; use seeded metrics
    payload = run_library_ladder(
        root=root,
        policy_path=policy,
        skip_grow=True,
        skip_research=True,
    )
    assert payload["focus_market"] == "sp500"
    assert payload["layers"]["screen_lite"].get("ticker_count") == 30
    assert payload["layers"]["selective_research"].get("skipped") is True
