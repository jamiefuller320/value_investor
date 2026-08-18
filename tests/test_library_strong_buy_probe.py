"""Tests for strong-buy-first metrics probe (ladder L153)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from value_investor.library_strong_buy_probe import (
    engineering_queue_is_idle,
    load_buy_tier_tickers_from_screen,
    prioritize_probe_tickers,
    probe_markets_for_policy,
    run_strong_buy_metrics_probe,
)
from value_investor.storage import write_json


def _write_screen(root: Path, market_id: str, rows: list[dict]) -> Path:
    screen = root / "markets" / market_id / "screen"
    screen.mkdir(parents=True, exist_ok=True)
    path = screen / "signals_20260818_120000.csv"
    headers = ["ticker", "signal", "name"]
    lines = [",".join(headers)]
    for row in rows:
        lines.append(",".join(str(row.get(h) or "") for h in headers))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_manifest(
    root: Path, market_id: str, tickers: list[str], *, failed: list[str] | None = None
) -> None:
    market = root / "markets" / market_id
    market.mkdir(parents=True, exist_ok=True)
    state = {}
    for t in tickers:
        state[t] = {
            "last_refresh": "2026-08-01T00:00:00+00:00",
            "fetch_status": "failed" if failed and t in failed else "ok",
        }
    write_json(
        market / "manifest.json",
        {
            "market": market_id,
            "tickers": tickers,
            "ticker_count": len(tickers),
            "ticker_state": state,
            "coverage_count": len(tickers),
        },
        compact=False,
    )
    write_json(
        market / "constituents" / "latest.json",
        [{"ticker": t, "name": t, "sector": "Test"} for t in tickers],
        compact=False,
    )


def test_engineering_queue_is_idle(tmp_path: Path):
    tasks = tmp_path / "engineering_tasks.json"
    write_json(tasks, {"tasks": [{"id": "eng-1", "status": "merged", "area": "coverage"}]})
    assert engineering_queue_is_idle(tasks) is True
    write_json(tasks, {"tasks": [{"id": "eng-2", "status": "open", "area": "coverage"}]})
    assert engineering_queue_is_idle(tasks) is False


def test_load_buy_tier_and_prioritize(tmp_path: Path):
    root = tmp_path / "library"
    tickers = ["AAA", "BBB", "CCC", "DDD"]
    _write_manifest(root, "sp500", tickers, failed=["BBB"])
    _write_screen(
        root,
        "sp500",
        [
            {"ticker": "AAA", "signal": "strong_buy"},
            {"ticker": "BBB", "signal": "strong_buy"},
            {"ticker": "CCC", "signal": "buy"},
            {"ticker": "DDD", "signal": "hold"},
        ],
    )
    write_json(
        root / "markets" / "sp500" / "metrics" / "latest.json.gz",
        [
            {"ticker": "AAA", "market_cap": 1, "trailing_pe": 10, "errors": []},
            {"ticker": "BBB", "errors": ["yahoo 401"]},
            {"ticker": "CCC", "market_cap": 1, "trailing_pe": 12},
        ],
        compact=True,
        compress=True,
    )
    bands = load_buy_tier_tickers_from_screen(root, "sp500")
    assert bands["strong_buy"] == ["AAA", "BBB"]
    assert bands["buy"] == ["CCC"]
    ordered = prioritize_probe_tickers(
        root,
        "sp500",
        strong_buy=bands["strong_buy"],
        buy=bands["buy"],
        max_tickers=10,
    )
    assert ordered[0] == "BBB"
    assert "AAA" in ordered
    assert "DDD" not in ordered


def test_probe_markets_phase2_first(tmp_path: Path):
    root = tmp_path / "library"
    for mid in ("sp500", "euro_stoxx50", "nasdaq100"):
        _write_screen(root, mid, [{"ticker": "X", "signal": "strong_buy"}])
    policy = {
        "ladder": {
            "weekly_paper_shard_after_screen": True,
            "weekly_paper_shard_capacity": 2,
            "weekly_paper_shard_markets": ["euro_stoxx50", "sp500"],
            "observe_sim_markets_mode": "explicit",
            "observe_sim_markets": ["nasdaq100", "euro_stoxx50"],
        }
    }
    markets = probe_markets_for_policy(policy, root=root, max_markets=3)
    assert markets[0] == "euro_stoxx50"
    assert "sp500" in markets
    assert "nasdaq100" in markets


def test_run_strong_buy_metrics_probe_skips_when_eng_busy(tmp_path: Path):
    root = tmp_path / "library"
    tasks = tmp_path / "engineering_tasks.json"
    write_json(tasks, {"tasks": [{"id": "eng-1", "status": "open", "area": "ops"}]})
    policy = {
        "ladder": {
            "strong_buy_metrics_probe_after_maintenance": True,
            "strong_buy_metrics_probe_when_eng_idle": True,
            "weekly_paper_shard_markets": ["sp500"],
            "weekly_paper_shard_after_screen": True,
            "weekly_paper_shard_capacity": 2,
            "observe_sim_markets_mode": "explicit",
            "observe_sim_markets": [],
        }
    }
    out = run_strong_buy_metrics_probe(
        root, policy, tasks_path=tasks, policy_path=tmp_path / "policy.json"
    )
    assert out["skipped"] is True
    assert "not idle" in str(out.get("reason") or "")


def test_run_strong_buy_metrics_probe_refetches(tmp_path: Path, monkeypatch):
    root = tmp_path / "library"
    tasks = tmp_path / "engineering_tasks.json"
    write_json(tasks, {"tasks": []})
    policy_path = tmp_path / "policy.json"
    write_json(
        policy_path,
        {
            "focus_market": "sp500",
            "ladder": {
                "min_metrics_for_screen": 25,
                "strong_buy_metrics_probe_after_maintenance": True,
                "strong_buy_metrics_probe_when_eng_idle": True,
                "strong_buy_metrics_probe_max_tickers": 10,
                "strong_buy_metrics_probe_max_markets": 2,
                "weekly_paper_shard_after_screen": True,
                "weekly_paper_shard_capacity": 2,
                "weekly_paper_shard_markets": ["sp500"],
                "observe_sim_markets_mode": "explicit",
                "observe_sim_markets": [],
            },
        },
    )
    tickers = ["AAA", "BBB", "CCC"]
    _write_manifest(root, "sp500", tickers)
    _write_screen(
        root,
        "sp500",
        [
            {"ticker": "AAA", "signal": "strong_buy"},
            {"ticker": "BBB", "signal": "buy"},
            {"ticker": "CCC", "signal": "hold"},
        ],
    )
    fetched: list[str] = []

    def fake_fetch(ticker: str, name: str | None, sector: str | None):
        fetched.append(ticker)
        return SimpleNamespace(
            to_dict=lambda: {
                "ticker": ticker,
                "name": name,
                "sector": sector,
                "market_cap": 100,
                "trailing_pe": 12.0,
                "errors": [],
            }
        )

    out = run_strong_buy_metrics_probe(
        root,
        json.loads(policy_path.read_text(encoding="utf-8")),
        policy_path=policy_path,
        tasks_path=tasks,
        fetch_fn=fake_fetch,
    )
    assert out["skipped"] is False
    assert out["total_selected"] == 2
    assert set(fetched) == {"AAA", "BBB"}
    assert "sp500" in out["markets"]
    assert out["markets"]["sp500"]["errors"] == 0
