"""Admitted / epoch-0 weekday rememo — equal treatment, not Sunday spray."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from value_investor.library_admitted_rememo import (
    already_ran_today,
    assess_admitted_rememo_backlog,
    assess_market_rememo,
    is_weekday,
    list_admitted_rememo_backlog,
    run_admitted_rememo_pass,
)
from value_investor.market_shard_admission import admitted_learning_markets_for_policy


def _write_memo(
    root: Path,
    market_id: str,
    ticker: str,
    *,
    grade: str,
    memo_bodies: int,
    disk_bodies: int,
    signal: str = "buy",
    verdict: str = "accumulate",
) -> None:
    screen = root / "markets" / market_id / "screen"
    research = screen / "research" / ticker
    (research / "sources" / "filings").mkdir(parents=True)
    (research / "research.json").write_text(
        json.dumps(
            {
                "ticker": ticker,
                "name": ticker,
                "signal": signal,
                "research_verdict": verdict,
                "memo_quality": {
                    "grade": grade,
                    "filings_with_body": memo_bodies,
                    "filings_total": disk_bodies,
                },
            }
        ),
        encoding="utf-8",
    )
    (research / "research.md").write_text(f"# {ticker}\n", encoding="utf-8")
    (research / "sources" / "filings" / "filings_index.json").write_text(
        json.dumps({"summary": {"with_body": disk_bodies, "total": disk_bodies}}),
        encoding="utf-8",
    )
    (research / "sources" / "screening_snapshot.json").write_text(
        json.dumps(
            {
                "ticker": ticker,
                "name": ticker,
                "signal": signal,
                "data_quality_score": 1.0,
                "models_passed": 8,
                "model_count": 22,
            }
        ),
        encoding="utf-8",
    )


def _write_signals(root: Path, market_id: str, tickers: list[str]) -> None:
    screen = root / "markets" / market_id / "screen"
    screen.mkdir(parents=True, exist_ok=True)
    rows = [
        {"ticker": ticker, "signal": "buy", "conviction_score": 0.8, "last_price": 10.0}
        for ticker in tickers
    ]
    pd.DataFrame(rows).to_csv(screen / "latest_signals.csv", index=False)


def test_admitted_set_is_not_all_graduated():
    policy = {
        "ladder": {"admitted_learning_markets": ["sp500", "asx200"]},
        "ingest_exhausted_markets": ["euro_depth", "sp500"],
        "graduated_markets": [{"market": "nasdaq100"}, {"market": "dax"}],
    }
    admitted = admitted_learning_markets_for_policy(policy)
    assert admitted == ["sp500", "asx200", "euro_depth"]
    assert "nasdaq100" not in admitted
    assert "dax" not in admitted


def test_list_backlog_uses_body_lag_rule(tmp_path: Path):
    _write_signals(tmp_path, "sp500", ["AAA", "BBB", "CCC"])
    _write_memo(tmp_path, "sp500", "AAA", grade="adequate", memo_bodies=2, disk_bodies=20)
    _write_memo(tmp_path, "sp500", "BBB", grade="strong", memo_bodies=10, disk_bodies=12)
    _write_memo(tmp_path, "sp500", "CCC", grade="strong", memo_bodies=10, disk_bodies=40)
    policy = {"ladder": {"admitted_learning_markets": ["sp500"], "rememo_body_lag_threshold": 10}}
    backlog = list_admitted_rememo_backlog(tmp_path, policy, markets=["sp500"])
    assert "AAA" in backlog["sp500"]
    assert "BBB" not in backlog["sp500"]  # strong, lag 2
    assert "CCC" in backlog["sp500"]  # strong, lag 30


def test_catch_up_when_market_exceeds_weekly_capacity():
    eligible = {f"T{i}": "stale_adequate_grade_body_lag_12" for i in range(20)}
    row = assess_market_rememo(eligible, per_day_cap=3, affordable=40)
    assert row["action"] == "catch_up"
    assert row["effective_cap"] == 6
    assert len(row["selected"]) == 6


def test_assess_does_not_include_non_admitted(tmp_path: Path, monkeypatch):
    _write_signals(tmp_path, "sp500", ["AAA"])
    _write_memo(tmp_path, "sp500", "AAA", grade="adequate", memo_bodies=0, disk_bodies=12)
    _write_signals(tmp_path, "nasdaq100", ["QQQ"])
    _write_memo(tmp_path, "nasdaq100", "QQQ", grade="adequate", memo_bodies=0, disk_bodies=12)
    policy = {"ladder": {"admitted_learning_markets": ["sp500"], "rememo_body_lag_threshold": 10}}
    monkeypatch.setattr(
        "value_investor.library_admitted_rememo.weekly_ops_budget_status",
        lambda estimated_memo_usd=0.4: {
            "remaining_weekly_ops_usd": 50.0,
            "constraining": False,
        },
    )
    status = assess_admitted_rememo_backlog(tmp_path, policy)
    assert list(status["markets"]) == ["sp500"]
    assert status["eligible_total"] == 1
    assert "nasdaq100" not in status["markets"]


def test_dry_run_selects_and_skips_weekend(tmp_path: Path, monkeypatch):
    _write_signals(tmp_path, "asx200", ["AAA.AX"])
    _write_memo(tmp_path, "asx200", "AAA.AX", grade="thin", memo_bodies=0, disk_bodies=15)
    policy = {"ladder": {"admitted_learning_markets": ["asx200"], "rememo_body_lag_threshold": 10}}
    monkeypatch.setattr(
        "value_investor.library_admitted_rememo.weekly_ops_budget_status",
        lambda estimated_memo_usd=0.4: {
            "remaining_weekly_ops_usd": 50.0,
            "constraining": False,
        },
    )
    summary_path = tmp_path / "summary.json"
    saturday = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
    weekend = run_admitted_rememo_pass(
        api_key=None,
        library_root=tmp_path,
        policy=policy,
        dry_run=True,
        force=False,
        record_spend=False,
        summary_path=summary_path,
        backlog_path=tmp_path / "backlog.json",
        now=saturday,
    )
    assert "weekend" in weekend["skipped"]
    assert weekend["selected"] == []

    tuesday = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    dry = run_admitted_rememo_pass(
        api_key=None,
        library_root=tmp_path,
        policy=policy,
        dry_run=True,
        force=False,
        record_spend=False,
        summary_path=summary_path,
        backlog_path=tmp_path / "backlog.json",
        now=tuesday,
    )
    assert dry["selected"] == ["asx200:AAA.AX"]
    assert dry["rememoed"] == []
    assert dry["dry_run"] is True


def test_already_ran_today_gate(tmp_path: Path):
    path = tmp_path / "summary.json"
    path.write_text(
        json.dumps({"run_at": "2026-09-08T07:40:00+00:00", "dry_run": False, "rememoed": ["sp500:AAA"]}),
        encoding="utf-8",
    )
    now = datetime(2026, 9, 8, 16, 30, tzinfo=UTC)
    assert already_ran_today(path, now=now) is True
    path.write_text(
        json.dumps(
            {
                "run_at": "2026-09-08T10:40:00+00:00",
                "dry_run": False,
                "skipped_reason": "already_ran_today",
            }
        ),
        encoding="utf-8",
    )
    assert already_ran_today(path, now=now) is True
    assert already_ran_today(path, now=datetime(2026, 9, 9, 7, 30, tzinfo=UTC)) is False
    assert is_weekday(now) is True
    assert is_weekday(datetime(2026, 9, 6, 12, 0, tzinfo=UTC)) is False
