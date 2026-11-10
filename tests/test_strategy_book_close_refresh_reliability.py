"""Close refresh timing: late weekend runs, partial bars, unpublished sessions, schedule."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time
from pathlib import Path

import pandas as pd
import yaml

from value_investor.ops_monitor import (
    CHECK_CRASHED_TITLE,
    OpsFinding,
    _guarded_check,
    check_strategy_book_observe,
)
from value_investor.strategy_book_forward import TITLE_CLOSES_SHORT, TITLE_FAILED
from value_investor.strategy_book_prices import run_close_refresh, short_markets


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _repo(tmp_path: Path, tickers: list[str], *, screen_day: date) -> Path:
    repo = tmp_path / "repo"
    data = repo / "docs" / "data"
    data.mkdir(parents=True)
    _write(
        data / "history" / f"run_{screen_day.strftime('%Y%m%d')}_120000.json",
        {
            "run_at": datetime.combine(screen_day, time(12), tzinfo=UTC).isoformat(),
            "reports": [{"ticker": t, "signal": "buy", "name": t} for t in tickers],
        },
    )
    return repo


def _frame(days: list[str]) -> pd.DataFrame:
    count = len(days)
    return pd.DataFrame(
        {
            "Close": [10.0 + i for i in range(count)],
            "High": [11.0 + i for i in range(count)],
            "Low": [9.0 + i for i in range(count)],
            "Volume": [1] * count,
        },
        index=pd.to_datetime(days),
    )


def _dates(path: Path) -> list[str]:
    return json.loads(path.read_text(encoding="utf-8"))["dates"]


def test_friday_slot_started_on_saturday_still_fetches_friday(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path, ["AAA"], screen_day=date(2026, 11, 5))
    data = repo / "docs" / "data"
    _write(data / "charts" / "AAA.json", {"dates": ["2026-11-04"], "closes": [1.0]})
    called: list[str] = []

    def fake_fetch(tickers, period="2y", market=None):
        called.extend(tickers)
        return {t: _frame(["2026-11-05", "2026-11-06"]) for t in tickers}

    monkeypatch.setattr("value_investor.technical_analysis.fetch_price_history", fake_fetch)
    result = run_close_refresh(
        repo_root=repo,
        now=datetime(2026, 11, 7, 1, 3, tzinfo=UTC),
        apply=True,
        pause_seconds=0,
    )
    assert result["skipped"] is None
    assert called == ["AAA"]
    assert result["markets"]["ftse350"]["closes_through"] == "2026-11-06"
    assert _dates(data / "charts" / "AAA.json")[-1] == "2026-11-06"
    stored = json.loads((data / "strategy_book_closes.json").read_text(encoding="utf-8"))
    assert stored["dry_run"] is False
    assert stored["markets"]["ftse350"]["short_of_session"] == 0


def test_refresh_drops_bars_after_the_completed_session(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path, ["AAA"], screen_day=date(2026, 11, 6))
    data = repo / "docs" / "data"
    _write(data / "charts" / "AAA.json", {"dates": ["2026-11-05"], "closes": [1.0]})

    def fake_fetch(tickers, period="2y", market=None):
        return {t: _frame(["2026-11-06", "2026-11-09", "2026-11-10"]) for t in tickers}

    monkeypatch.setattr("value_investor.technical_analysis.fetch_price_history", fake_fetch)
    # 11:00 UTC Tuesday: London is in session, Monday is the latest completed one.
    result = run_close_refresh(
        repo_root=repo,
        now=datetime(2026, 11, 10, 11, 0, tzinfo=UTC),
        apply=True,
        pause_seconds=0,
    )
    assert result["markets"]["ftse350"]["closes_through"] == "2026-11-09"
    assert _dates(data / "charts" / "AAA.json")[-1] == "2026-11-09"


def test_unpublished_session_is_recorded_and_reported(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path, ["AAA", "BBB"], screen_day=date(2026, 11, 6))
    data = repo / "docs" / "data"
    for ticker in ("AAA", "BBB"):
        _write(data / "charts" / f"{ticker}.json", {"dates": ["2026-11-05"], "closes": [1.0]})

    # Yahoo overnight: Monday's European bar is not in the daily history yet.
    def fake_fetch(tickers, period="2y", market=None):
        return {t: _frame(["2026-11-05", "2026-11-06"]) for t in tickers}

    monkeypatch.setattr("value_investor.technical_analysis.fetch_price_history", fake_fetch)
    now = datetime(2026, 11, 10, 3, 45, tzinfo=UTC)
    run_close_refresh(repo_root=repo, now=now, apply=True, pause_seconds=0)
    stored = json.loads((data / "strategy_book_closes.json").read_text(encoding="utf-8"))
    row = stored["markets"]["ftse350"]
    assert row["closes_through"] == "2026-11-09"
    assert row["more_than_one_session_behind"] == 0
    assert row["stale"] is False
    assert row["short_of_session"] == 2
    assert row["short_sample_tickers"] == ["AAA", "BBB"]
    assert [item["market"] for item in short_markets(stored)] == ["ftse350"]

    findings = check_strategy_book_observe(repo_root=repo, now=now)
    short = [row for row in findings if row.title == TITLE_CLOSES_SHORT]
    assert len(short) == 1
    assert short[0].severity == "info"
    assert short[0].auto_fixable is False
    assert "ftse350: 2 of 2" in short[0].summary

    assert short_markets({**stored, "dry_run": True}) == []


def test_observe_failed_clears_once_the_forward_job_ran_after_the_slot(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    data = repo / "docs" / "data"
    data.mkdir(parents=True)
    _write(
        data / "strategy_book_forward_status.json",
        {"generated_at": "2026-11-07T01:06:00+00:00", "signals": 0, "errors": []},
    )
    morning = datetime(2026, 11, 10, 2, 32, tzinfo=UTC)
    assert any(
        r.title == TITLE_FAILED for r in check_strategy_book_observe(repo_root=repo, now=morning)
    )
    _write(
        data / "strategy_book_forward_status.json",
        {"generated_at": "2026-11-10T03:46:30+00:00", "signals": 0, "errors": []},
    )
    later = datetime(2026, 11, 10, 7, 45, tzinfo=UTC)
    assert not any(
        r.title == TITLE_FAILED for r in check_strategy_book_observe(repo_root=repo, now=later)
    )


def test_guarded_check_turns_a_crash_into_one_warn() -> None:
    def check_boom(*, latest_path: Path) -> list[OpsFinding]:
        raise AttributeError("'float' object has no attribute 'strip'")

    rows = _guarded_check(check_boom, latest_path=Path("x"))
    assert len(rows) == 1
    assert rows[0].title == CHECK_CRASHED_TITLE
    assert rows[0].severity == "warn"
    assert rows[0].auto_fixable is False
    assert "check_boom raised AttributeError" in rows[0].summary

    ok = OpsFinding(severity="info", category="ops", title="t", summary="s")
    assert _guarded_check(lambda path: [ok], Path("x")) == [ok]


def test_collect_ops_findings_survives_one_crashing_check(monkeypatch, tmp_path: Path) -> None:
    import value_investor.ops_monitor as om

    names = [
        name
        for name in dir(om)
        if name.startswith("check_")
        and callable(getattr(om, name))
        and name != "check_buy_tier_flip_lag"
    ]
    for name in names:
        monkeypatch.setattr(om, name, lambda *a, **k: [])
    monkeypatch.setattr(om, "check_engineering_queue", lambda **k: ([], {}))
    monkeypatch.setattr(om, "check_engineering_sync", lambda **k: ([], {}))
    monkeypatch.setattr(om, "check_workflow_freshness", lambda **k: ([], []))
    monkeypatch.setattr(om, "check_automation_waste", lambda **k: [])

    def boom(**_kwargs):
        raise AttributeError("'float' object has no attribute 'strip'")

    monkeypatch.setattr(om, "check_buy_tier_flip_lag", boom)
    findings, _queue, _checks = om.collect_ops_findings(
        tasks_path=tmp_path / "tasks.json",
        health_log_path=tmp_path / "health.jsonl",
        latest_path=tmp_path / "latest.json",
        open_prs=[],
        eng_failures=[],
    )
    assert [row.title for row in findings] == [CHECK_CRASHED_TITLE]


def test_forward_workflow_has_a_europe_slot_and_external_primary() -> None:
    workflow = yaml.safe_load(
        Path(".github/workflows/strategy-book-forward.yml").read_text(encoding="utf-8")
    )
    triggers = workflow.get("on") or workflow.get(True)
    crons = [row["cron"] for row in triggers["schedule"]]
    assert crons == ["45 17 * * 1-5", "30 21 * * 1-5"]
    assert "workflow_dispatch" in triggers

    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("icj_forward", "scripts/import_cron_jobs.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["icj_forward"] = mod
    spec.loader.exec_module(mod)
    jobs = {s.key: s for s in mod._job_specs()}
    europe = jobs["strategy-book-forward-europe"]
    us = jobs["strategy-book-forward"]
    assert (europe.hours, europe.minutes, europe.wdays) == ([17], [45], [1, 2, 3, 4, 5])
    assert (us.hours, us.minutes, us.wdays) == ([21], [30], [1, 2, 3, 4, 5])
    assert europe.workflow == us.workflow == "strategy-book-forward.yml"

    importer = Path(".github/workflows/import-ingest-crons.yml").read_text(encoding="utf-8")
    assert "--job strategy-book-forward-europe" in importer
    assert "--job strategy-book-forward \\" in importer
    assert '".github/workflows/strategy-book-forward.yml"' in importer


def test_forward_loader_ignores_a_partial_bar_after_the_completed_session(
    tmp_path: Path,
) -> None:
    from value_investor.strategy_book_forward import _load_forward_specs, _through_completed
    from value_investor.strategy_book_signals import repo_paths

    days = [date(2026, 11, 6), date(2026, 11, 9), date(2026, 11, 10)]
    clipped = _through_completed((days, [1.0, 2.0, 3.0], [1.1, 2.1, 3.1], None), date(2026, 11, 9))
    assert clipped == (days[:2], [1.0, 2.0], [1.1, 2.1], None)
    whole = (days, [1.0, 2.0, 3.0], None, None)
    assert _through_completed(whole, date(2026, 11, 10)) is whole

    repo = _repo(tmp_path, ["AAA"], screen_day=date(2026, 11, 6))
    data = repo / "docs" / "data"
    _write(
        data / "charts" / "AAA.json",
        {"dates": ["2026-11-05", "2026-11-06", "2026-11-09", "2026-11-10"], "closes": [1, 2, 3, 4]},
    )
    # 03:45 UTC Tuesday: Monday is London's latest completed session.
    loaded = _load_forward_specs(
        repo_paths(repo),
        start=date(2026, 11, 5),
        now=datetime(2026, 11, 10, 3, 45, tzinfo=UTC),
        commit=None,
        log_rows=[],
    )
    specs = [spec for spec in loaded["specs"] if spec.ticker == "AAA"]
    assert specs, loaded["blocked"]
    assert specs[0].sessions[-1] == date(2026, 11, 9)
    assert specs[0].closes[-1] == 3.0
