import json
from pathlib import Path

from value_investor.backtest import BENCHMARK_TICKER, RunSnapshot
from value_investor.screen_premise_backtest import (
    FINDING_TITLE,
    STORE_FAILED_TITLE,
    build_screen_premise_backtest,
    ops_finding_from_screen_premise_backtest,
    score_cohort,
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

    _write_history(tmp_path, weeks=7, buy_growth=-0.02, other_growth=0.01)
    store = tmp_path / "screen_premise_backtest.json"
    findings = check_screen_premise_backtest(data_dir=tmp_path, store_path=store)
    assert [f.title for f in findings] == [FINDING_TITLE]
    assert json.loads(store.read_text())["weekly_cohorts"] == 7

    def boom(*a, **k):
        raise ValueError("bad snapshot")

    monkeypatch.setattr(module, "build_screen_premise_backtest", boom)
    failed = check_screen_premise_backtest(data_dir=tmp_path, store_path=store)
    assert [f.title for f in failed] == [STORE_FAILED_TITLE]
