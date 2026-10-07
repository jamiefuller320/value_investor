import json
from datetime import date
from pathlib import Path

from value_investor.backtest import BENCHMARK_TICKER, RunSnapshot
from value_investor.screen_premise_backtest import (
    AI_GATE_FINDING_TITLE,
    FINDING_TITLE,
    STORE_FAILED_TITLE,
    ai_gate_finding_from_screen_premise_backtest,
    build_screen_premise_backtest,
    financials_move_the_buy_tier,
    ops_finding_from_screen_premise_backtest,
    score_cohort,
    snapshot_verdicts,
    spearman,
    summarise,
    weekly_cohorts,
    weeks_to_detect,
)
from value_investor.storage import write_json


def _snapshot(run_at: str, buy_growth: float, other_growth: float, *, week: int) -> dict:
    signals = []
    prices = {BENCHMARK_TICKER: 8000.0}
    for i in range(20):
        signal = "buy" if i < 6 else ("avoid" if i >= 16 else "hold")
        ticker = f"T{i:02d}.L"
        growth = buy_growth if signal == "buy" else other_growth
        signals.append({"ticker": ticker, "signal": signal, "conviction_score": 1.0 - i / 20.0})
        prices[ticker] = round(100.0 * (1.0 + growth) ** week, 6)
    return {"run_at": run_at, "prices": prices, "signals": signals}


def _write_history(data_dir: Path, weeks: int, buy_growth: float, other_growth: float) -> None:
    history = data_dir / "history"
    history.mkdir(parents=True)
    for week in range(weeks):
        day = 2 + 7 * week
        month, dom = (8, day) if day <= 31 else (9, day - 31)
        run_at = f"2026-{month:02d}-{dom:02d}T07:00:00+00:00"
        stamp = f"2026{month:02d}{dom:02d}_070000"
        write_json(
            history / f"run_{stamp}.json.gz",
            _snapshot(run_at, buy_growth, other_growth, week=week),
            compress=True,
        )


def test_weekly_cohorts_skip_runs_within_six_days():
    runs = [
        RunSnapshot(run_at=at, prices={}, signals=[])
        for at in (
            "2026-08-02T07:00:00+00:00",
            "2026-08-03T07:00:00+00:00",
            "2026-08-09T07:00:00+00:00",
            "2026-08-10T07:00:00+00:00",
        )
    ]
    assert [s.run_at[:10] for s in weekly_cohorts(runs)] == ["2026-08-02", "2026-08-09"]


def test_spearman_perfect_and_inverse():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == -1.0
    assert spearman([1, 2], [1, 2]) is None


def test_score_cohort_spreads_and_unit_flip_drop():
    entry = RunSnapshot(**_snapshot("2026-08-02T07:00:00+00:00", 0.02, 0.0, week=0))
    exit_payload = _snapshot("2026-08-09T07:00:00+00:00", 0.02, 0.0, week=1)
    exit_payload["prices"]["T19.L"] = 1.0
    scored = score_cohort(entry, RunSnapshot(**exit_payload))
    assert scored is not None
    assert scored["dropped_unit_flips"] == 1
    assert scored["names"] == 19
    assert scored["buy_tier_spread"] > 0
    assert scored["avoid_spread"] < 0
    assert scored["rank_ic"] > 0.5
    assert scored["ai_gate_pass_share"] is None
    assert scored["ai_gate_spread"] is None


def test_summarise_withholds_interval_until_effective_n():
    thin = summarise([0.01, 0.02, 0.03], horizon_days=28)
    assert thin["effective_n"] == 1.0
    assert thin["ci90_low"] is None
    wide = summarise([0.01, 0.02, 0.03, 0.02], horizon_days=7)
    assert wide["ci90_low"] is not None and wide["ci90_low"] < wide["mean"] < wide["ci90_high"]


def test_weeks_to_detect_scales_with_noise():
    quiet = weeks_to_detect(0.002, 7)
    noisy = weeks_to_detect(0.004, 7)
    assert quiet is not None and noisy is not None
    assert noisy == quiet * 4 or abs(noisy - quiet * 4) <= 2
    assert weeks_to_detect(None, 7) is None


def test_build_and_finding_flags_losing_buy_tier(tmp_path: Path):
    _write_history(tmp_path, weeks=7, buy_growth=-0.02, other_growth=0.01)
    payload = build_screen_premise_backtest(tmp_path)
    weekly = payload["horizons"]["7"]
    assert weekly["buy_tier_spread"]["cohorts"] == 6
    assert weekly["buy_tier_spread"]["mean"] < 0
    finding = ops_finding_from_screen_premise_backtest(payload)
    assert finding is not None
    assert finding["title"] == FINDING_TITLE
    assert finding["auto_fixable"] is False


def test_finding_silent_when_buy_tier_wins(tmp_path: Path):
    _write_history(tmp_path, weeks=7, buy_growth=0.02, other_growth=0.0)
    payload = build_screen_premise_backtest(tmp_path)
    assert payload["horizons"]["7"]["buy_tier_spread"]["mean"] > 0
    assert ops_finding_from_screen_premise_backtest(payload) is None


def test_check_screen_premise_backtest_persists_and_fails_closed(tmp_path: Path, monkeypatch):
    from value_investor import screen_premise_backtest as module
    from value_investor.ops_monitor import check_screen_premise_backtest
    from value_investor.total_return_view import TickerHistory

    _write_history(tmp_path, weeks=7, buy_growth=-0.02, other_growth=0.01)
    store = tmp_path / "screen_premise_backtest.json"
    findings = check_screen_premise_backtest(
        data_dir=tmp_path,
        store_path=store,
        dividend_fetcher=lambda ticker, start, end: TickerHistory(),
    )
    assert [f.title for f in findings] == [FINDING_TITLE]
    assert json.loads(store.read_text())["weekly_cohorts"] == 7

    def boom(*a, **k):
        raise ValueError("bad snapshot")

    monkeypatch.setattr(module, "build_screen_premise_backtest", boom)
    failed = check_screen_premise_backtest(data_dir=tmp_path, store_path=store)
    assert [f.title for f in failed] == [STORE_FAILED_TITLE]


def _gate_snapshot(run_at: str, week: int, *, gate_growth: float, reject_growth: float) -> dict:
    """Buy tier T00–T07: T00–T03 accumulate (higher conviction), T04–T07 neutral."""
    payload = _snapshot(run_at, 0.0, 0.0, week=week)
    for i, row in enumerate(payload["signals"]):
        if i < 8:
            row["signal"] = "buy"
            row["research_verdict"] = "accumulate" if i < 4 else "neutral"
            growth = gate_growth if i < 4 else reject_growth
            payload["prices"][row["ticker"]] = round(100.0 * (1.0 + growth) ** week, 6)
    return payload


def test_sector_split_separates_financials_real_estate_and_the_rest():
    entry = _snapshot("2026-08-02T07:00:00+00:00", 0.0, 0.0, week=0)
    exit_snap = _snapshot("2026-08-09T07:00:00+00:00", 0.0, 0.0, week=1)
    for i, row in enumerate(entry["signals"]):
        if i < 3:
            row["sector"] = "Financial Services"
            exit_snap["prices"][row["ticker"]] = 100.0
        elif i == 3:
            row["sector"] = "Real Estate"
        else:
            row["sector"] = "Industrials"
            if row["signal"] == "buy":
                exit_snap["prices"][row["ticker"]] = 110.0
    scored = score_cohort(RunSnapshot(**entry), RunSnapshot(**exit_snap))
    splits = scored["sector_splits"]
    assert splits["financial_services"]["buy_tier_names"] == 3
    assert splits["real_estate"]["buy_tier_names"] == 1
    assert splits["rest"]["buy_tier_names"] == 2
    assert splits["financials_and_real_estate_share"] == round(4 / 6, 4)
    assert splits["financial_services"]["spread_vs_universe"] is not None
    assert splits["rest"]["spread_vs_universe"] is None


def test_financials_exclusion_needs_both_share_and_spread_move():
    quiet = financials_move_the_buy_tier(
        {
            "buy_tier_spread": {"mean": 0.01},
            "sector_splits": {"rest": {"mean": 0.012}},
            "financials_and_real_estate_share": 0.4,
        }
    )
    assert quiet["exclude_from_industrial_models"] is False
    moved = financials_move_the_buy_tier(
        {
            "buy_tier_spread": {"mean": 0.0},
            "sector_splits": {"rest": {"mean": 0.02}},
            "financials_and_real_estate_share": 0.4,
        }
    )
    assert moved["exclude_from_industrial_models"] is True
    assert moved["spread_gap_rest_minus_full"] == 0.02
    thin = financials_move_the_buy_tier(
        {
            "buy_tier_spread": {"mean": 0.0},
            "sector_splits": {"rest": {"mean": 0.02}},
            "financials_and_real_estate_share": 0.05,
        }
    )
    assert thin["exclude_from_industrial_models"] is False
    assert financials_move_the_buy_tier({})["exclude_from_industrial_models"] is False


def test_score_cohort_ai_gate_and_conviction_half_spreads():
    entry = _gate_snapshot("2026-08-02T07:00:00+00:00", 0, gate_growth=-0.02, reject_growth=0.02)
    exit_snap = _gate_snapshot(
        "2026-08-09T07:00:00+00:00", 1, gate_growth=-0.02, reject_growth=0.02
    )
    verdicts = {r["ticker"]: r.get("research_verdict") for r in entry["signals"][:8]}
    verdicts["T07.L"] = None
    scored = score_cohort(RunSnapshot(**entry), RunSnapshot(**exit_snap), verdicts)
    assert scored["ai_gate_pass_names"] == 4
    assert scored["ai_gate_reject_names"] == 4
    assert scored["ai_gate_no_memo_names"] == 1
    assert scored["ai_gate_pass_share"] == 0.5
    assert scored["ai_gate_spread"] == -0.04
    assert scored["conviction_half_spread"] == -0.04


def test_ai_gate_spread_needs_names_on_both_sides():
    entry = _gate_snapshot("2026-08-02T07:00:00+00:00", 0, gate_growth=0.01, reject_growth=0.0)
    exit_snap = _gate_snapshot("2026-08-09T07:00:00+00:00", 1, gate_growth=0.01, reject_growth=0.0)
    all_pass = {f"T{i:02d}.L": "accumulate" for i in range(8)}
    scored = score_cohort(RunSnapshot(**entry), RunSnapshot(**exit_snap), all_pass)
    assert scored["ai_gate_pass_share"] == 1.0
    assert scored["ai_gate_spread"] is None


def test_snapshot_verdicts_prefers_row_then_point_in_time_archive(tmp_path: Path, monkeypatch):
    from value_investor import screen_premise_backtest as module

    calls: list[tuple[str, str]] = []

    class _Doc:
        research_verdict = "neutral"

    def fake_as_of(research_dir, ticker, as_of):
        calls.append((ticker, as_of))
        return _Doc() if ticker == "B.L" else None

    monkeypatch.setattr(module, "get_research_as_of", fake_as_of)
    snap = RunSnapshot(
        run_at="2026-08-16T07:00:00+00:00",
        prices={},
        signals=[
            {"ticker": "A.L", "signal": "buy", "research_verdict": "accumulate"},
            {"ticker": "B.L", "signal": "strong_buy", "research_verdict": None},
            {"ticker": "C.L", "signal": "buy"},
            {"ticker": "D.L", "signal": "hold"},
        ],
    )
    verdicts = snapshot_verdicts(snap, tmp_path)
    assert verdicts == {"A.L": "accumulate", "B.L": "neutral", "C.L": None}
    assert calls == [
        ("B.L", "2026-08-16T07:00:00+00:00"),
        ("C.L", "2026-08-16T07:00:00+00:00"),
    ]
    assert snapshot_verdicts(snap, None) == {"A.L": "accumulate", "B.L": None, "C.L": None}


def test_build_and_ai_gate_finding_when_gate_picks_lose(tmp_path: Path):
    history = tmp_path / "history"
    history.mkdir()
    for week in range(7):
        day = 2 + 7 * week
        month, dom = (8, day) if day <= 31 else (9, day - 31)
        write_json(
            history / f"run_2026{month:02d}{dom:02d}_070000.json.gz",
            _gate_snapshot(
                f"2026-{month:02d}-{dom:02d}T07:00:00+00:00",
                week,
                gate_growth=-0.01 - 0.001 * week,
                reject_growth=0.01,
            ),
            compress=True,
        )
    payload = build_screen_premise_backtest(tmp_path)
    weekly = payload["horizons"]["7"]
    assert weekly["ai_gate_spread"]["mean"] < 0
    assert weekly["ai_gate_pass_share"] == 0.5
    assert weekly["conviction_half_spread"]["cohorts"] == 6
    finding = ai_gate_finding_from_screen_premise_backtest(payload)
    assert finding is not None
    assert finding["title"] == AI_GATE_FINDING_TITLE
    assert "50% of the buy tier" in finding["summary"]
    assert finding["auto_fixable"] is False


def test_backfill_snapshot_research_fills_only_empty_research_fields(tmp_path: Path):
    import pandas as pd

    from value_investor.scoring.snapshot import backfill_snapshot_research
    from value_investor.storage import read_json

    path = tmp_path / "run_20261004_072146.json"
    write_json(
        path,
        {
            "run_at": "2026-10-04T07:21:46+00:00",
            "prices": {},
            "signals": [
                {
                    "ticker": "A.L",
                    "signal": "buy",
                    "adjusted_signal": "hold",
                    "research_verdict": None,
                },
                {"ticker": "B.L", "signal": "buy", "research_verdict": "neutral"},
                {"ticker": "C.L", "signal": "hold", "research_verdict": None},
            ],
        },
        compress=True,
    )
    signals = pd.DataFrame(
        [
            {
                "ticker": "A.L",
                "research_verdict": "accumulate",
                "research_confidence": 0.7,
                "research_as_of": "2026-10-01",
                "adjusted_signal": "buy",
            },
            {"ticker": "B.L", "research_verdict": "accumulate"},
            {"ticker": "C.L", "research_verdict": None},
        ]
    )
    assert backfill_snapshot_research(path, signals) == 1
    rows = {r["ticker"]: r for r in read_json(path)["signals"]}
    assert rows["A.L"]["research_verdict"] == "accumulate"
    assert rows["A.L"]["research_confidence"] == 0.7
    assert rows["A.L"]["adjusted_signal"] == "hold"
    assert rows["B.L"]["research_verdict"] == "neutral"
    assert rows["C.L"]["research_verdict"] is None
    assert backfill_snapshot_research(tmp_path / "missing.json", signals) == 0


def _flat_history(ticker: str, start: date, end: date, *, dividend: float = 0.0) -> object:
    from datetime import timedelta

    from value_investor.total_return_view import TickerHistory

    history = TickerHistory()
    day = start
    while day <= end:
        history.closes[day] = 100.0
        day += timedelta(days=1)
    if dividend > 0 and ticker == "T00.L":
        history.dividends[date(2026, 8, 5)] = dividend
    return history


def test_ex_date_dividend_lifts_the_judging_spread_and_keeps_the_price_spread(tmp_path: Path):
    _write_history(tmp_path, weeks=3, buy_growth=0.0, other_growth=0.0)
    price = build_screen_premise_backtest(tmp_path)
    credited = build_screen_premise_backtest(
        tmp_path,
        dividend_fetcher=lambda ticker, start, end: _flat_history(ticker, start, end, dividend=5.0),
    )
    price_mean = price["horizons"]["7"]["buy_tier_spread"]["mean"]
    weekly = credited["horizons"]["7"]
    assert credited["return_basis"] == "price_plus_dividends"
    assert weekly["price_buy_tier_spread"]["mean"] == price_mean
    assert weekly["buy_tier_spread"]["mean"] > price_mean
    cohort = weekly["cohorts"][0]
    assert cohort["price_buy_tier_spread"] == 0
    assert cohort["buy_tier_spread"] > 0


def test_implausible_yield_and_entry_day_dividend_are_not_credited(tmp_path: Path):
    _write_history(tmp_path, weeks=3, buy_growth=0.0, other_growth=0.0)

    def fetcher(ticker, start, end):
        history = _flat_history(ticker, start, end)
        if ticker == "T00.L":
            history.dividends[date(2026, 8, 2)] = 5.0
            history.dividends[date(2026, 8, 6)] = 50.0
        return history

    payload = build_screen_premise_backtest(tmp_path, dividend_fetcher=fetcher)
    cohort = payload["horizons"]["7"]["cohorts"][0]
    assert cohort["buy_tier_spread"] == cohort["price_buy_tier_spread"]


def test_a_missing_dividend_history_adds_nothing_and_is_counted(tmp_path: Path):
    from value_investor.total_return_view import TickerHistory

    _write_history(tmp_path, weeks=3, buy_growth=0.0, other_growth=0.0)

    def fetcher(ticker, start, end):
        if ticker == "T01.L":
            return TickerHistory()
        return _flat_history(ticker, start, end, dividend=5.0)

    payload = build_screen_premise_backtest(tmp_path, dividend_fetcher=fetcher)
    assert "T01.L" in payload["dividends_skipped_tickers"]
    cohort = payload["horizons"]["7"]["cohorts"][0]
    assert cohort["dividends_skipped"] >= 1
    assert cohort["buy_tier_spread"] > cohort["price_buy_tier_spread"]


def test_dividend_cache_skips_a_second_fetch(tmp_path: Path):
    _write_history(tmp_path, weeks=3, buy_growth=0.0, other_growth=0.0)
    calls = {"n": 0}

    def fetcher(ticker, start, end):
        calls["n"] += 1
        return _flat_history(ticker, start, end, dividend=1.0)

    cache = tmp_path / "screen_premise_dividend_cache.json"
    build_screen_premise_backtest(tmp_path, dividend_fetcher=fetcher, dividend_cache_path=cache)
    first = calls["n"]
    assert first > 0
    assert cache.exists()
    build_screen_premise_backtest(tmp_path, dividend_fetcher=fetcher, dividend_cache_path=cache)
    assert calls["n"] == first
