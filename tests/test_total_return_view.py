"""Tests for the observe-only total-return view (L528 / L532 / L533)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from value_investor.ops_monitor import check_total_return_view
from value_investor.total_return_view import (
    FINDING_TITLE,
    PRICE_BENCHMARK,
    TR_BENCHMARK,
    TickerHistory,
    build_total_return_view,
    dividend_credits,
    ops_finding_from_total_return_view,
    score_window,
    stress_cost_contamination,
)

START = date(2026, 6, 1)


def _at(day: date, hour: int = 8) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 30, tzinfo=UTC)


def _days(n: int) -> list[date]:
    return [START + timedelta(days=i) for i in range(n)]


def _flat(level: float, *, dividends: dict[date, float] | None = None) -> TickerHistory:
    closes = {START - timedelta(days=10) + timedelta(days=i): level for i in range(60)}
    return TickerHistory(closes=closes, dividends=dict(dividends or {}))


def _trend(start_level: float, daily: float) -> TickerHistory:
    closes = {}
    level = start_level
    for i in range(60):
        closes[START - timedelta(days=10) + timedelta(days=i)] = level
        level *= 1 + daily
    return TickerHistory(closes=closes)


def _trade(day: date, side: str, shares: float, price: float, cost_rate: float = 0.0) -> dict:
    gross = shares * price
    return {
        "ticker": "DIV.L",
        "side": side,
        "shares": shares,
        "price": price,
        "gross": gross,
        "cost": gross * cost_rate,
        "acted_at": _at(day).isoformat(),
        "_at": _at(day),
    }


def test_dividend_credits_only_for_shares_held_over_ex_date():
    ex_day = START + timedelta(days=5)
    # Yahoo in pence (500p close, 25p dividend); paper price in pounds (5.0).
    histories = {"DIV.L": _flat(500.0, dividends={ex_day: 25.0})}
    trades = [
        _trade(START, "buy", 10, 5.0),
        _trade(START + timedelta(days=2), "sell", 4, 5.0),
        _trade(ex_day, "buy", 100, 5.0),
    ]
    total, credited, skipped = dividend_credits(trades, histories)
    assert skipped == []
    assert len(credited) == 1
    assert credited[0]["shares"] == 6
    assert abs(total - 6 * 5.0 * 0.05) < 1e-9


def test_dividend_credits_skip_implausible_yield():
    ex_day = START + timedelta(days=5)
    histories = {"DIV.L": _flat(500.0, dividends={ex_day: 250.0})}
    total, credited, skipped = dividend_credits([_trade(START, "buy", 10, 5.0)], histories)
    assert total == 0
    assert credited == []
    assert "implausible" in skipped[0]["why"]


def test_score_window_adds_dividends_and_uses_tr_benchmark():
    days = _days(10)
    marks = [(_at(d), 1000.0, 1000.0) for d in days]
    histories = {"DIV.L": _flat(500.0, dividends={days[5]: 25.0})}
    benchmarks = {PRICE_BENCHMARK: _flat(100.0), TR_BENCHMARK: _trend(100.0, 0.001)}
    trades = [_trade(days[0], "buy", 100, 5.0)]
    scored = score_window(marks, trades, histories, benchmarks)
    assert scored is not None
    assert scored["price_return"] == 0
    assert scored["dividends_gbp"] == 25.0
    assert scored["total_return"] == 0.025
    assert scored["benchmark_price_return"] == 0
    assert scored["benchmark_total_return"] > 0
    assert scored["excess_total_return"] < scored["total_return"]


def test_score_window_strips_deposits():
    days = _days(3)
    marks = [
        (_at(days[0]), 1000.0, 1000.0),
        (_at(days[1]), 1500.0, 1500.0),
        (_at(days[2]), 1530.0, 1500.0),
    ]
    benchmarks = {PRICE_BENCHMARK: _flat(100.0), TR_BENCHMARK: _flat(100.0)}
    scored = score_window(marks, [], {}, benchmarks)
    assert scored is not None
    assert scored["price_return"] == 0.02


def test_stress_cost_contamination_only_for_fair_books():
    trades = [
        _trade(START, "buy", 10, 5.0, cost_rate=0.03),
        _trade(START + timedelta(days=3), "buy", 10, 5.0, cost_rate=0.005),
    ]
    assert stress_cost_contamination({"buy_cost_pct": 0.03}, trades) is None
    assert stress_cost_contamination({"buy_cost_pct": 0.005}, trades) == _at(START)
    assert stress_cost_contamination({"buy_cost_pct": 0.005}, trades[1:]) is None


def _write_book(
    root: Path,
    subdir: str,
    *,
    navs: list[float],
    trades: list[dict],
    published: float | None,
    config: dict | None = None,
) -> None:
    path = root / subdir if subdir else root
    path.mkdir(parents=True, exist_ok=True)
    curve = [
        {"at": _at(d).isoformat(), "portfolio_value": nav, "contributed_capital": 1000.0}
        for d, nav in zip(_days(len(navs)), navs, strict=True)
    ]
    serial = [{k: v for k, v in t.items() if k != "_at"} for t in trades]
    (path / "automated_fund.json").write_text(
        json.dumps({"equity_curve": curve, "trades": serial}), encoding="utf-8"
    )
    if config is not None:
        (path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    if published is not None:
        (path / "decision_review.json").write_text(
            json.dumps({"metrics": {"excess_after_costs": published}}), encoding="utf-8"
        )


def _fetcher(dividend_day: date):
    def fetch(ticker: str, _start: date, _end: date) -> TickerHistory:
        if ticker == TR_BENCHMARK:
            return _trend(100.0, 0.002)
        if ticker == PRICE_BENCHMARK:
            return _flat(100.0)
        return _flat(500.0, dividends={dividend_day: 25.0})

    return fetch


def _seed_paper_root(root: Path) -> None:
    days = _days(10)
    flat = [1000.0] * 10
    _write_book(root, "", navs=flat, trades=[], published=0.0)
    _write_book(
        root,
        "ai_judgment_fair",
        navs=flat,
        trades=[
            _trade(days[0], "buy", 10, 5.0, cost_rate=0.03),
            _trade(days[2], "buy", 100, 5.0, cost_rate=0.005),
        ],
        published=0.08,
        config={"buy_cost_pct": 0.005, "sell_cost_pct": 0.005},
    )
    _write_book(
        root,
        "buy_tier_level",
        navs=flat,
        trades=[_trade(days[0], "buy", 50, 5.0)],
        published=None,
    )


def test_build_total_return_view_tracks_clean_epoch_and_value_control(tmp_path: Path):
    _seed_paper_root(tmp_path)
    payload = build_total_return_view(tmp_path, history_fetcher=_fetcher(START + timedelta(days=5)))
    assert payload["observe_only"] is True
    fair = payload["tracks"]["ai_judgment_fair"]
    assert fair["stress_cost_trades_until"] == _at(START).isoformat()
    assert fair["clean_epoch"]["start"] == _at(START + timedelta(days=1)).isoformat()
    assert fair["lifetime"]["dividends_gbp"] == 110 * 5.0 * 0.05
    pair = payload["pairs"]["ai_fair_vs_buy_tier_level"]
    assert pair["left"] == "ai_judgment_fair"
    assert pair["difference"] > 0


def test_finding_fires_on_large_gap_and_names_track(tmp_path: Path):
    _seed_paper_root(tmp_path)
    payload = build_total_return_view(tmp_path, history_fetcher=_fetcher(START + timedelta(days=5)))
    finding = ops_finding_from_total_return_view(payload)
    assert finding is not None
    assert finding["title"] == FINDING_TITLE
    assert finding["auto_fixable"] is False
    assert "ai_judgment_fair: published +8.0%" in finding["summary"]
    assert "clean epoch" in finding["summary"]
    assert "rules:" not in finding["summary"]


def test_no_finding_when_published_close_to_total_return():
    payload = {
        "tracks": {
            "rules": {
                "published_excess_after_costs": 0.03,
                "lifetime": {"excess_total_return": 0.01, "dividends_gbp": 4.0},
            }
        }
    }
    assert ops_finding_from_total_return_view(payload) is None


def test_check_total_return_view_persists_store(tmp_path: Path):
    paper = tmp_path / "paper"
    _seed_paper_root(paper)
    store = tmp_path / "total_return_view.json"
    findings = check_total_return_view(
        paper_root=paper,
        store_path=store,
        history_fetcher=_fetcher(START + timedelta(days=5)),
    )
    assert [f.title for f in findings] == [FINDING_TITLE]
    assert findings[0].auto_fixable is False
    stored = json.loads(store.read_text(encoding="utf-8"))
    assert "ai_judgment_fair" in stored["tracks"]


def test_check_total_return_view_skips_missing_root(tmp_path: Path):
    assert check_total_return_view(paper_root=tmp_path / "missing", persist=False) == []
