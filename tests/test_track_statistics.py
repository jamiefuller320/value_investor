"""Tests for learning-track statistical power and significance (L529)."""

from __future__ import annotations

import json
import random
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from value_investor.ops_monitor import check_track_statistics
from value_investor.track_statistics import (
    FINDING_TITLE,
    MIN_PERIODS,
    benchmark_period_returns,
    build_track_statistics,
    daily_marks,
    ops_finding_from_track_statistics,
    period_returns,
    summarize_active_returns,
)

START = date(2026, 6, 1)


def _weekdays(count: int) -> list[date]:
    days: list[date] = []
    day = START
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _curve(navs: list[float], *, contributed: list[float] | None = None) -> list[dict]:
    days = _weekdays(len(navs))
    contrib = contributed or [1000.0] * len(navs)
    return [
        {
            "at": datetime(d.year, d.month, d.day, 8, 30, tzinfo=UTC).isoformat(),
            "portfolio_value": nav,
            "contributed_capital": c,
        }
        for d, nav, c in zip(days, navs, contrib, strict=True)
    ]


def _write_track(root: Path, subdir: str, navs: list[float]) -> None:
    path = root / subdir if subdir else root
    path.mkdir(parents=True, exist_ok=True)
    (path / "automated_fund.json").write_text(
        json.dumps({"equity_curve": _curve(navs)}), encoding="utf-8"
    )


def _flat_benchmark(_ticker: str, start: date, end: date) -> dict[date, float]:
    out: dict[date, float] = {}
    day = start - timedelta(days=7)
    while day <= end:
        out[day] = 100.0
        day += timedelta(days=1)
    return out


def test_daily_marks_keeps_last_mark_per_day():
    curve = [
        {"at": "2026-06-01T08:00:00+00:00", "portfolio_value": 1000, "contributed_capital": 1000},
        {"at": "2026-06-01T15:00:00+00:00", "portfolio_value": 1010, "contributed_capital": 1000},
        {"at": "2026-06-02T08:00:00+00:00", "portfolio_value": 1020, "contributed_capital": 1000},
        {"at": "", "portfolio_value": 5},
    ]
    marks = daily_marks(curve)
    assert [m[1] for m in marks] == [1010, 1020]


def test_period_returns_strip_deposits():
    marks = [
        (date(2026, 6, 1), 1000.0, 1000.0),
        (date(2026, 6, 2), 1500.0, 1500.0),
        (date(2026, 6, 3), 1530.0, 1500.0),
    ]
    rows = period_returns(marks)
    assert rows[0][1] == 0.0
    assert abs(rows[1][1] - 0.02) < 1e-12


def test_benchmark_uses_close_before_mark_date():
    closes = {date(2026, 6, 1): 100.0, date(2026, 6, 2): 110.0, date(2026, 6, 3): 121.0}
    out = benchmark_period_returns([date(2026, 6, 2), date(2026, 6, 3)], closes)
    assert abs(out[date(2026, 6, 3)] - 0.10) < 1e-12


def test_summarize_needs_min_periods():
    rows = [(d, 0.001) for d in _weekdays(MIN_PERIODS - 1)]
    assert summarize_active_returns(rows, z_crit=2.0)["status"] == "insufficient_data"


def test_noise_is_indistinguishable_and_reports_power():
    rng = random.Random(1)
    rows = [(d, rng.gauss(0.0, 0.02)) for d in _weekdays(60)]
    stats = summarize_active_returns(rows, z_crit=2.8)
    assert stats["status"] == "ok"
    assert stats["verdict"] == "indistinguishable_from_noise"
    low, high = stats["ci_annualized_active_return"]
    assert low < 0 < high
    assert stats["significant_after_correction"] is False
    assert stats["min_detectable_annual_edge"] > 0.5
    assert stats["years_to_detect_target_edge"] > 50


def test_steady_edge_is_positive_and_significant():
    rng = random.Random(2)
    rows = [(d, 0.004 + rng.gauss(0.0, 0.001)) for d in _weekdays(60)]
    stats = summarize_active_returns(rows, z_crit=2.8)
    assert stats["verdict"] == "positive"
    assert stats["ci_annualized_active_return"][0] > 0
    assert stats["significant_after_correction"] is True


def test_build_track_statistics_tracks_and_pair(tmp_path: Path):
    root = tmp_path / "paper"
    n = MIN_PERIODS + 10
    rules = [1000.0 * (1.001**i) for i in range(n)]
    ai = [1000.0 * (1.002**i) for i in range(n)]
    _write_track(root, "", rules)
    _write_track(root, "ai_judgment", ai)
    _write_track(root, "technical", [1000.0, 1001.0])

    payload = build_track_statistics(root, benchmark_fetcher=_flat_benchmark)
    tracks = payload["tracks"]
    assert tracks["rules"]["status"] == "ok"
    assert tracks["ai_judgment"]["verdict"] == "positive"
    assert tracks["technical"]["status"] == "insufficient_data"
    pair = payload["pairs"]["primary_vs_control"]
    assert (pair["left"], pair["right"]) == ("ai_judgment", "rules")
    assert pair["status"] == "ok"
    assert pair["annualized_active_return"] > 0
    assert payload["tests_corrected_for"] == 2 + 1
    assert payload["observe_only"] is True


def test_build_uses_model_pair_and_skips_frozen_books(tmp_path: Path):
    root = tmp_path / "paper"
    n = MIN_PERIODS + 10
    for track_id, rate, flag in (
        ("ai_judgment_fair", 1.002, "is_fair_cost_lab"),
        ("buy_tier_level", 1.001, "is_cohort_lab"),
    ):
        _write_track(root, track_id, [1000.0 * (rate**i) for i in range(n)])
        (root / track_id / "config.json").write_text(
            json.dumps({"track_id": track_id, flag: True}), encoding="utf-8"
        )
    _write_track(root, "", [1000.0 * (1.003**i) for i in range(n)])
    _write_track(root, "ai_judgment", [1000.0 * (1.004**i) for i in range(n)])
    (root / "assessment_model.json").write_text(
        json.dumps(
            {
                "primary_track": "ai_judgment_fair",
                "control_track": "buy_tier_level",
                "frozen_tracks": {"rules": {}, "ai_judgment": {}},
            }
        ),
        encoding="utf-8",
    )

    payload = build_track_statistics(root, benchmark_fetcher=_flat_benchmark)

    assert "rules" not in payload["tracks"] and "ai_judgment" not in payload["tracks"]
    assert payload["excluded_frozen_tracks"] == ["ai_judgment", "rules"]
    pair = payload["pairs"]["primary_vs_control"]
    assert (pair["left"], pair["right"]) == ("ai_judgment_fair", "buy_tier_level")
    assert payload["tests_corrected_for"] == 2 + 1

    noisy = {**payload, "pairs": {"primary_vs_control": _ok("indistinguishable_from_noise")}}
    finding = ops_finding_from_track_statistics(noisy, {"beat_control": True})
    assert "ai_judgment_fair minus buy_tier_level" in finding["summary"]


def test_build_handles_missing_benchmark(tmp_path: Path):
    root = tmp_path / "paper"
    _write_track(root, "ai_judgment", [1000.0 + i for i in range(MIN_PERIODS + 5)])
    payload = build_track_statistics(root, benchmark_fetcher=lambda *_a: {})
    stats = payload["tracks"]["ai_judgment"]
    assert stats["status"] == "insufficient_data"
    assert "Benchmark closes unavailable" in stats["note"]


def _ok(verdict: str) -> dict:
    return {
        "status": "ok",
        "verdict": verdict,
        "annualized_active_return": 0.4,
        "ci_annualized_active_return": [-0.01, 1.2],
        "min_detectable_annual_edge": 0.8,
    }


def test_finding_only_on_unsupported_claims():
    payload = {
        "tracks": {"ai_judgment": _ok("positive")},
        "pairs": {"primary_vs_control": _ok("positive")},
    }
    claims = {"beat_market": True, "beat_control": True}
    assert ops_finding_from_track_statistics(payload, claims) is None

    noisy = {
        "tracks": {"ai_judgment": _ok("indistinguishable_from_noise")},
        "pairs": {"primary_vs_control": _ok("indistinguishable_from_noise")},
    }
    assert ops_finding_from_track_statistics(noisy, {"beat_market": False}) is None
    finding = ops_finding_from_track_statistics(noisy, {"beat_control": True})
    assert finding is not None
    assert finding["title"] == FINDING_TITLE
    assert finding["severity"] == "warn"
    assert finding["auto_fixable"] is False
    assert "beat_control" in finding["summary"]
    assert "beat_market" not in finding["summary"]


def test_check_track_statistics_persists_store_and_warns(tmp_path: Path):
    root = tmp_path / "paper"
    n = MIN_PERIODS + 5
    rng = random.Random(3)
    navs = [1000.0]
    for _ in range(n - 1):
        navs.append(navs[-1] * (1 + rng.gauss(0, 0.02)))
    _write_track(root, "", navs)
    _write_track(root, "ai_judgment", [v * 1.0005 for v in navs])
    (root / "learning_tracks_review.json").write_text(
        json.dumps({"beat_market": True, "beat_control": True}), encoding="utf-8"
    )
    store = tmp_path / "track_statistics.json"
    findings = check_track_statistics(
        paper_root=root, store_path=store, benchmark_fetcher=_flat_benchmark
    )
    assert store.exists()
    assert json.loads(store.read_text())["tracks"]["ai_judgment"]["status"] == "ok"
    assert [f.title for f in findings] == [FINDING_TITLE]
    assert findings[0].auto_fixable is False


def test_check_track_statistics_skips_missing_root(tmp_path: Path):
    assert check_track_statistics(paper_root=tmp_path / "missing", persist=False) == []
