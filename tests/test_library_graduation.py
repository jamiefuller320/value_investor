"""Tests for focus graduation and maintenance grow."""

from __future__ import annotations

from pathlib import Path

from value_investor.agent_model_policy import load_policy, save_policy
from value_investor.data_library import market_dir
from value_investor.library_graduation import (
    apply_graduation,
    evaluate_graduation,
    market_meets_graduation,
    maybe_graduate_focus,
    next_focus_market,
    run_maintenance_grow,
    stale_pct_from_status,
)
from value_investor.library_ladder import run_library_ladder
from value_investor.storage import write_json


def _seed_market(
    root: Path,
    market: str,
    *,
    n: int,
    covered: int,
    stale: int = 0,
) -> None:
    tickers = [f"{market.upper()}{i:03d}" for i in range(n)]
    state = {}
    for i, ticker in enumerate(tickers):
        if i >= covered:
            continue
        # Fresh unless in the stale tail of the covered set
        if i >= covered - stale:
            last = "2020-01-01T00:00:00+00:00"
        else:
            last = "2026-07-16T00:00:00+00:00"
        state[ticker] = {"last_refresh": last, "fields_present": ["trailing_pe"], "errors": []}
    write_json(
        market_dir(root, market) / "manifest.json",
        {
            "tickers": tickers,
            "ticker_count": n,
            "covered_tickers": tickers[:covered],
            "coverage_count": covered,
            "coverage_pct": round(covered / n, 4) if n else 0.0,
            "ticker_state": state,
        },
        compact=False,
    )


def test_market_meets_graduation_floors():
    row = {
        "ticker_count": 100,
        "coverage_count": 96,
        "coverage_pct": 0.96,
        "stale": 10,  # 10/96 ≈ 0.104
        "never_fetched": 4,
        "fresh": 86,
    }
    assert stale_pct_from_status(row) == round(10 / 96, 4)
    assert market_meets_graduation(row, min_coverage_pct=0.95, max_stale_pct=0.15)
    row["stale"] = 30  # 30/96 ≈ 0.31
    assert not market_meets_graduation(row, min_coverage_pct=0.95, max_stale_pct=0.15)
    row["stale"] = 5
    row["coverage_pct"] = 0.90
    assert not market_meets_graduation(row, min_coverage_pct=0.95, max_stale_pct=0.15)


def test_apply_graduation_advances_queue(tmp_path: Path):
    policy = load_policy(tmp_path / "policy.json")
    policy["focus_market"] = "sp500"
    policy["market_queue"] = ["sp500", "euro_stoxx50", "asx200"]
    evaluation = {
        "focus_market": "sp500",
        "meets_floors": True,
        "auto_advance": True,
        "coverage_pct": 0.96,
        "stale_pct": 0.1,
        "next_focus": "euro_stoxx50",
        "can_advance": True,
        "queue_complete": False,
    }
    policy, event = apply_graduation(policy, evaluation)
    assert event["graduated"] is True
    assert event["to_market"] == "euro_stoxx50"
    assert policy["focus_market"] == "euro_stoxx50"
    assert policy["graduated_markets"][0]["market"] == "sp500"
    assert next_focus_market(policy) == "asx200"


def test_maybe_graduate_persists(tmp_path: Path):
    root = tmp_path / "library"
    policy_path = tmp_path / "policy.json"
    _seed_market(root, "sp500", n=100, covered=96, stale=5)
    policy = load_policy(policy_path)
    policy["focus_market"] = "sp500"
    policy["market_queue"] = ["sp500", "euro_stoxx50", "asx200"]
    save_policy(policy, policy_path)

    result = maybe_graduate_focus(root, policy_path, stale_days=14)
    assert result["event"]["graduated"] is True
    assert result["policy_focus"] == "euro_stoxx50"
    reloaded = load_policy(policy_path)
    assert reloaded["focus_market"] == "euro_stoxx50"


def test_maintenance_grow_only_graduated(tmp_path: Path, monkeypatch):
    root = tmp_path / "library"
    policy = load_policy(tmp_path / "policy.json")
    policy["focus_market"] = "euro_stoxx50"
    policy["market_queue"] = ["sp500", "euro_stoxx50", "asx200"]
    policy["graduated_markets"] = [{"market": "sp500", "graduated_at": "2026-07-01T00:00:00+00:00"}]
    calls: list[list[str]] = []
    grow_kwargs: list[dict] = []

    def fake_grow(root_path, markets=None, **kwargs):
        calls.append(list(markets or []))
        grow_kwargs.append(kwargs)
        return [{"market": m, "updated": 1} for m in (markets or [])]

    monkeypatch.setattr(
        "value_investor.library_graduation.grow_library",
        fake_grow,
    )
    monkeypatch.setattr(
        "value_investor.library_graduation.library_status",
        lambda root_path, markets=None, **kwargs: [
            {"market": m, "coverage_pct": 0.96, "ticker_count": 503} for m in (markets or [])
        ],
    )
    out = run_maintenance_grow(root, policy)
    assert out["skipped"] is False
    assert out["markets"] == ["sp500"]
    assert out["maintenance_full_refresh"] is True
    assert out["max_tickers"] == 503
    assert out["queue_complete"] is False
    assert out["include_focus"] is False
    assert calls == [["sp500"]]
    assert grow_kwargs[0].get("refresh_constituents_first") is True
    assert grow_kwargs[0].get("max_tickers_per_run") == 503


def test_maintenance_includes_focus_when_queue_complete(tmp_path: Path, monkeypatch):
    root = tmp_path / "library"
    policy = load_policy(tmp_path / "policy.json")
    policy["focus_market"] = "asx200"
    policy["market_queue"] = ["sp500", "euro_stoxx50", "asx200"]
    policy["graduated_markets"] = [
        {"market": "sp500", "graduated_at": "2026-07-01T00:00:00+00:00"},
        {"market": "euro_stoxx50", "graduated_at": "2026-07-02T00:00:00+00:00"},
        {"market": "asx200", "graduated_at": "2026-07-03T00:00:00+00:00"},
    ]
    calls: list[list[str]] = []

    def fake_grow(root_path, markets=None, **kwargs):
        calls.append(list(markets or []))
        return [{"market": m, "updated": 1} for m in (markets or [])]

    monkeypatch.setattr("value_investor.library_graduation.grow_library", fake_grow)
    monkeypatch.setattr(
        "value_investor.library_graduation.library_status",
        lambda root_path, markets=None, **kwargs: [
            {"market": m, "coverage_pct": 1.0, "ticker_count": {"sp500": 503, "euro_stoxx50": 50, "asx200": 200}[m]}
            for m in (markets or [])
        ],
    )
    out = run_maintenance_grow(root, policy)
    assert out["skipped"] is False
    assert out["queue_complete"] is True
    assert out["include_focus"] is True
    assert out["markets"] == ["sp500", "euro_stoxx50", "asx200"]
    assert out["maintenance_full_refresh"] is True
    assert out["max_tickers"] == 503
    assert calls == [["sp500", "euro_stoxx50", "asx200"]]


def test_maintenance_int_cap_still_throttles(tmp_path: Path, monkeypatch):
    root = tmp_path / "library"
    policy = load_policy(tmp_path / "policy.json")
    policy["focus_market"] = "euro_stoxx50"
    policy["market_queue"] = ["sp500", "euro_stoxx50", "asx200"]
    policy["graduated_markets"] = [{"market": "sp500", "graduated_at": "2026-07-01T00:00:00+00:00"}]
    policy["focus_graduation"] = dict(policy.get("focus_graduation") or {})
    policy["focus_graduation"]["maintenance_max_tickers"] = 75
    grow_kwargs: list[dict] = []

    def fake_grow(root_path, markets=None, **kwargs):
        grow_kwargs.append(kwargs)
        return [{"market": m, "updated": 1} for m in (markets or [])]

    monkeypatch.setattr("value_investor.library_graduation.grow_library", fake_grow)
    monkeypatch.setattr(
        "value_investor.library_graduation.library_status",
        lambda root_path, markets=None, **kwargs: [
            {"market": m, "coverage_pct": 0.96, "ticker_count": 503} for m in (markets or [])
        ],
    )
    out = run_maintenance_grow(root, policy)
    assert out["maintenance_full_refresh"] is False
    assert out["max_tickers"] == 75
    assert grow_kwargs[0]["max_tickers_per_run"] == 75


def test_ladder_runs_graduation(tmp_path: Path, monkeypatch):
    root = tmp_path / "library"
    policy_path = tmp_path / "policy.json"
    _seed_market(root, "sp500", n=40, covered=39, stale=2)
    policy = load_policy(policy_path)
    policy["focus_market"] = "sp500"
    policy["market_queue"] = ["sp500", "euro_stoxx50"]
    policy["ladder"] = {"min_metrics_for_screen": 1000}  # skip screen
    save_policy(policy, policy_path)

    payload = run_library_ladder(
        root=root,
        policy_path=policy_path,
        skip_grow=True,
        skip_screen=True,
        skip_research=True,
        skip_maintenance=True,
    )
    assert payload["layers"]["graduation"]["event"]["graduated"] is True
    assert payload["focus_market_after"] == "euro_stoxx50"
    assert load_policy(policy_path)["focus_market"] == "euro_stoxx50"


def test_evaluate_does_not_graduate_when_below_floor(tmp_path: Path):
    root = tmp_path / "library"
    _seed_market(root, "sp500", n=100, covered=50, stale=0)
    policy = load_policy(tmp_path / "p.json")
    policy["focus_market"] = "sp500"
    evaluation = evaluate_graduation(root, policy)
    assert evaluation["meets_floors"] is False
    assert evaluation["can_advance"] is False
