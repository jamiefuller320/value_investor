"""Tests for offline library screen-lite and ladder gating."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from value_investor.agent_model_policy import load_policy, save_policy
from value_investor.data_library import market_dir
from value_investor.library_ladder import run_library_ladder
from value_investor.library_screen import research_cap_from_budget, run_library_screen
from value_investor.storage import write_json


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
    base["ladder"] = {"min_metrics_for_screen": 25, "research_hard_cap": 5}
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
