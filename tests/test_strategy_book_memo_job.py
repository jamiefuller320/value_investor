"""Signal-day entry rule and memo job. Fixtures only; no network and no model."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from value_investor.strategy_book_memo_job import (
    TITLE_BEHIND,
    TITLE_NOT_RUN,
    TITLE_REFRESHED,
    findings_from_memo_job,
    memo_routine_falling_behind,
    plan_sessions,
    run_strategy_book_memo_job,
)
from value_investor.strategy_book_signals import (
    ALT_RSI_LEVEL,
    ALT_SMA_DISTANCE,
    LOW_WINDOW_SESSIONS,
    RSI_LEVEL,
    RSI_PERIOD,
    evaluate_market,
    repo_paths,
    rsi_below,
    rsi_last,
    universe_markets,
)

SESSION = date(2026, 10, 30)
TICKER = "AAA.L"


def _weekdays_ending(end: date, count: int) -> list[date]:
    days: list[date] = []
    cursor = end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(days))


def _decline_closes(count: int, *, start: float = 100.0, step: float = 1.0) -> list[float]:
    return [start - (step * index) for index in range(count)]


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _chart(root: Path, ticker: str, days: list[date], closes: list[float]) -> None:
    _write_json(
        root / "docs" / "data" / "charts" / f"{ticker}.json",
        {"ticker": ticker, "dates": [day.isoformat() for day in days], "closes": closes},
    )


def _screen(root: Path, run_day: date, rows: list[dict], *, name: str | None = None) -> None:
    stamp = run_day.strftime("%Y%m%d")
    filename = name or f"run_{stamp}_120000.json"
    _write_json(
        root / "docs" / "data" / "history" / filename,
        {"run_at": f"{run_day.isoformat()}T12:00:00+00:00", "reports": rows},
    )


def _screen_row(**overrides: object) -> dict:
    row = {
        "ticker": TICKER,
        "signal": "buy",
        "name": "Aaa",
        "fcf_basis_overlay": True,
        "adjusted_signal": "buy",
        "research_verdict": "hold",
    }
    row.update(overrides)
    return row


def _gates(root: Path, *, as_of: date, decline: str = "clear", sector: str = "sound") -> None:
    _write_json(
        root / "docs" / "data" / "operating_decline_gate.json",
        {"as_of": as_of.isoformat(), "names": {TICKER: {"verdict": decline, "market": "ftse350"}}},
    )
    _write_json(
        root / "docs" / "data" / "sector_headwind_gate.json",
        {
            "as_of": as_of.isoformat(),
            "names_by_market": {
                "ftse350": {TICKER: {"sector_verdict": sector, "sector_basis": "own_market"}}
            },
        },
    )


def _filings(root: Path, ticker: str, fetched: str) -> None:
    _write_json(
        root / "docs" / "data" / "research" / ticker / "sources" / "filings" / "filings_index.json",
        {
            "fetched_at": fetched,
            "summary": {
                "total": 2,
                "with_body": 2,
                "period_coverage": {
                    "annual": {"total": 1, "with_body": 1},
                    "interim": {"total": 1, "with_body": 1},
                },
            },
        },
    )


def _memo(root: Path, ticker: str, updated: str) -> None:
    _write_json(
        root / "docs" / "data" / "research" / ticker / "research.json",
        {
            "ticker": ticker,
            "created_at": updated,
            "updated_at": updated,
            "research_verdict": "hold",
        },
    )


def _green(root: Path, *, closes: list[float] | None = None, days: int = 30) -> list[date]:
    days_list = _weekdays_ending(SESSION, days)
    _chart(root, TICKER, days_list, closes or _decline_closes(len(days_list)))
    _screen(root, date(2026, 10, 23), [_screen_row()])
    _gates(root, as_of=date(2026, 10, 29))
    _filings(root, TICKER, "2026-10-20T00:00:00+00:00")
    return days_list


def _one(root: Path):
    result = evaluate_market("ftse350", SESSION, repo_root=root)
    assert result.names, result.error
    return result.names[0]


def test_registered_thresholds_are_strict() -> None:
    assert RSI_PERIOD == 14
    assert RSI_LEVEL == 35
    assert LOW_WINDOW_SESSIONS == 10
    assert ALT_RSI_LEVEL == 40
    assert ALT_SMA_DISTANCE == 0.03
    assert rsi_below(35.0, RSI_LEVEL) is False
    assert rsi_below(34.999, RSI_LEVEL) is True
    assert rsi_below(40.0, ALT_RSI_LEVEL) is False
    assert rsi_below(None, RSI_LEVEL) is False


def test_primary_fires_on_decline_and_ten_session_low(tmp_path: Path) -> None:
    _green(tmp_path)
    name = _one(tmp_path)
    assert name.checks["rsi_below_35"].passed
    assert name.checks["rsi_below_35"].detail["rsi_14"] < RSI_LEVEL
    assert name.checks["ten_session_low"].passed
    assert name.price_entry
    assert name.checks["part1_signal"].passed


def test_rsi_at_or_above_35_does_not_fire_even_on_a_low(tmp_path: Path) -> None:
    days = _weekdays_ending(SESSION, 30)
    rising = [80 + index for index in range(20)]
    tail = [120.0] * 8 + [119.5, 119.0]
    closes = rising + tail
    assert len(closes) == len(days)
    _green(tmp_path, closes=closes)
    name = _one(tmp_path)
    assert name.checks["ten_session_low"].passed
    assert name.checks["rsi_below_35"].passed is False
    assert name.checks["rsi_below_35"].reason == "not_below_35"
    assert name.price_entry is False
    # The same series sits on each side of 35 if the last close is pushed down.
    probed = list(closes)
    below = None
    above = None
    for step in range(0, 80):
        probed[-1] = 119.0 - step
        value = rsi_last(probed)
        if value is None:
            continue
        if value < RSI_LEVEL and below is None:
            below = (list(probed), value)
        if value >= RSI_LEVEL:
            above = (list(probed), value)
    assert above is not None and below is not None
    assert above[1] >= RSI_LEVEL
    assert below[1] < RSI_LEVEL


def test_ten_session_edges_and_ties(tmp_path: Path) -> None:
    short = _weekdays_ending(SESSION, 9)
    _chart(tmp_path, TICKER, short, _decline_closes(9))
    _screen(tmp_path, date(2026, 10, 23), [_screen_row()])
    _gates(tmp_path, as_of=date(2026, 10, 29))
    _filings(tmp_path, TICKER, "2026-10-20T00:00:00+00:00")
    short_name = _one(tmp_path)
    assert short_name.checks["ten_session_low"].reason == "shorter_than_10"
    assert short_name.price_entry is False

    days = _weekdays_ending(SESSION, 10)
    ten = _decline_closes(10)
    _chart(tmp_path, TICKER, days, ten)
    exactly_ten = _one(tmp_path)
    assert exactly_ten.checks["ten_session_low"].passed
    assert exactly_ten.checks["rsi_below_35"].reason == "not_finite"

    days = _weekdays_ending(SESSION, 20)
    closes = _decline_closes(20)
    closes[-1] = min(closes[-10:-1])
    assert closes[-1] == min(closes[-10:])
    _chart(tmp_path, TICKER, days, closes)
    tied = _one(tmp_path)
    assert tied.checks["ten_session_low"].passed
    assert tied.checks["ten_session_low"].reason == "is_low"

    closes[-1] = min(closes[-10:-1]) + 0.5
    _chart(tmp_path, TICKER, days, closes)
    higher = _one(tmp_path)
    assert higher.checks["ten_session_low"].reason == "not_low"
    assert higher.checks["rsi_below_35"].passed


def test_each_gate_failing_alone_excludes_the_name(tmp_path: Path) -> None:
    _green(tmp_path)
    base = _one(tmp_path)
    assert base.eligible_except_memo
    assert base.memo_needed

    _gates(tmp_path, as_of=date(2026, 10, 29), decline="declining")
    declined = _one(tmp_path)
    assert declined.checks["part2_decline"].reason == "declining"
    assert declined.checks["part3_sector"].passed
    assert declined.eligible_except_memo is False

    _gates(tmp_path, as_of=date(2026, 10, 29), sector="headwind")
    headwind = _one(tmp_path)
    assert headwind.checks["part3_sector"].reason == "headwind"
    assert headwind.checks["part2_decline"].passed
    assert headwind.eligible_except_memo is False

    _gates(
        tmp_path, as_of=date(2026, 10, 29), decline="insufficient_data", sector="insufficient_data"
    )
    thin = _one(tmp_path)
    assert thin.checks["part2_decline"].passed is False
    assert thin.checks["part3_sector"].passed is False

    _gates(tmp_path, as_of=date(2026, 10, 29))
    index = (
        tmp_path
        / "docs"
        / "data"
        / "research"
        / TICKER
        / "sources"
        / "filings"
        / "filings_index.json"
    )
    index.unlink()
    no_bodies = _one(tmp_path)
    assert no_bodies.checks["key_filing_bodies"].passed is False
    assert no_bodies.checks["fcf_basis_bound"].passed
    assert no_bodies.checks["overlay_bound"].passed
    assert no_bodies.eligible_except_memo is False

    _filings(tmp_path, TICKER, "2026-10-20T00:00:00+00:00")
    _screen(tmp_path, date(2026, 10, 23), [_screen_row(fcf_basis_overlay=None)])
    no_fcf = _one(tmp_path)
    assert no_fcf.checks["fcf_basis_bound"].reason == "overlay_not_boolean"
    assert no_fcf.checks["key_filing_bodies"].passed
    assert no_fcf.eligible_except_memo is False

    _screen(
        tmp_path,
        date(2026, 10, 23),
        [_screen_row(adjusted_signal=None, research_verdict=None)],
    )
    no_overlay = _one(tmp_path)
    assert no_overlay.checks["overlay_bound"].passed is False
    assert no_overlay.checks["fcf_basis_bound"].passed
    assert no_overlay.eligible_except_memo is False

    _screen(tmp_path, date(2026, 10, 23), [_screen_row(signal="hold")])
    held = evaluate_market("ftse350", SESSION, repo_root=tmp_path)
    assert held.names == []


def test_files_dated_after_session_are_ignored(tmp_path: Path) -> None:
    days = _green(tmp_path)
    later = days[-1] + timedelta(days=3)
    closes = _decline_closes(len(days))
    _chart(tmp_path, TICKER, [*days, later], [*closes, closes[-1] - 50])
    name = _one(tmp_path)
    assert name.checks["ten_session_low"].detail["window_min"] == closes[-1]
    assert name.checks["ten_session_low"].passed

    _screen(
        tmp_path,
        SESSION,
        [_screen_row(signal="strong_buy")],
        name="run_20261030_180000.json",
    )
    same_day = evaluate_market("ftse350", SESSION, repo_root=tmp_path)
    # The same-calendar-day strong_buy file is ignored. The 2026-10-23 buy row remains.
    assert same_day.screen_run_at is not None and same_day.screen_run_at.startswith("2026-10-23")
    assert [row.ticker for row in same_day.names] == [TICKER]
    assert same_day.names[0].checks["part1_signal"].detail["signal"] == "buy"

    _gates(tmp_path, as_of=SESSION)
    not_yet = _one(tmp_path)
    assert not_yet.checks["part2_decline"].reason == "verdict_not_in_force"
    assert not_yet.checks["part3_sector"].reason == "verdict_not_in_force"

    _gates(tmp_path, as_of=date(2026, 11, 5))
    future = _one(tmp_path)
    assert future.checks["part2_decline"].reason == "store_after_session"
    assert future.eligible_except_memo is False

    _gates(tmp_path, as_of=date(2026, 10, 29))
    _filings(tmp_path, TICKER, "2026-11-01T00:00:00+00:00")
    late_index = _one(tmp_path)
    assert late_index.checks["key_filing_bodies"].passed is False


def test_fresh_memo_needs_no_request_and_missing_memo_does(tmp_path: Path) -> None:
    _green(tmp_path)
    missing = _one(tmp_path)
    assert missing.checks["memo_recent"].reason == "missing"
    assert missing.memo_needed

    _memo(tmp_path, TICKER, "2026-10-20T12:00:00+00:00")
    fresh = _one(tmp_path)
    assert fresh.checks["memo_recent"].passed
    assert fresh.memo_needed is False

    _memo(tmp_path, TICKER, "2026-09-01T12:00:00+00:00")
    stale = _one(tmp_path)
    assert stale.checks["memo_recent"].reason == "older_than_21_days"
    assert stale.memo_needed


def test_alternative_sma_rule_does_not_gate_the_memo(tmp_path: Path) -> None:
    drop = [100 - (index * 3) for index in range(20)]
    flat = [drop[-1]] * 9
    closes = drop + flat + [drop[-1] - 0.05]
    _green(tmp_path, closes=closes)
    name = _one(tmp_path)
    assert name.price_entry
    assert name.checks["alternative_entry"].passed is False
    assert name.memo_needed


def test_dry_run_logs_and_does_not_call_the_runner(tmp_path: Path) -> None:
    _green(tmp_path)
    calls: list[dict] = []

    def runner(**kwargs):
        calls.append(kwargs)
        return {"verdict": "hold", "finished_at": "2026-11-05T12:00:00+00:00"}

    summary = run_strategy_book_memo_job(
        repo_root=tmp_path,
        now=datetime(2026, 11, 2, 12, tzinfo=UTC),
        markets=["ftse350"],
        sessions_by_market={"ftse350": [SESSION.isoformat()]},
        persist=True,
        runner=runner,
    )
    assert calls == []
    assert summary["spend_enabled"] is False
    logged = summary["logged"]
    assert len(logged) == 1
    assert logged[0]["action"] == "dry_run"
    assert logged[0]["kind"] == "signal_day"
    line = (tmp_path / "docs" / "data" / "strategy_book_memo_log.jsonl").read_text(encoding="utf-8")
    row = json.loads(line)
    assert row["estimated_spend_usd"] == 0.40
    assert row["action"] == "dry_run"
    assert row["inputs"]
    assert all(item["path"] and item["sha256"] for item in row["inputs"])
    assert row["data_commit"]


def test_spend_on_calls_the_mocked_runner_and_logs_the_verdict(tmp_path: Path) -> None:
    _green(tmp_path)
    _write_json(
        tmp_path / "docs" / "data" / "strategy_book_registration.json",
        {"signed_at": "2026-11-05T00:00:00+00:00", "signature": "owner", "spend_enabled": True},
    )
    calls: list[str] = []

    def runner(**kwargs):
        calls.append(kwargs["ticker"])
        return {"verdict": "hold", "finished_at": "2026-11-05T15:00:00+00:00"}

    recorded: list[float] = []
    summary = run_strategy_book_memo_job(
        repo_root=tmp_path,
        now=datetime(2026, 11, 2, 12, tzinfo=UTC),
        markets=["ftse350"],
        sessions_by_market={"ftse350": [SESSION.isoformat()]},
        persist=True,
        runner=runner,
        budget_status=lambda: {"constraining": False, "remaining_weekly_ops_usd": 100.0},
        record_spend=recorded.append,
    )
    assert calls == [TICKER]
    assert recorded == [0.40]
    row = json.loads(
        (tmp_path / "docs" / "data" / "strategy_book_memo_log.jsonl").read_text(encoding="utf-8")
    )
    assert row["action"] == "requested"
    assert row["verdict"] == "hold"
    assert row["memo_finished_at"] == "2026-11-05T15:00:00+00:00"
    assert summary["spend_enabled"] is True


def test_budget_headroom_skip_does_not_call_the_runner(tmp_path: Path) -> None:
    _green(tmp_path)
    _write_json(
        tmp_path / "docs" / "data" / "strategy_book_registration.json",
        {"signed": True, "spend_enabled": True},
    )
    calls: list[str] = []
    summary = run_strategy_book_memo_job(
        repo_root=tmp_path,
        now=datetime(2026, 11, 2, 12, tzinfo=UTC),
        markets=["ftse350"],
        sessions_by_market={"ftse350": [SESSION.isoformat()]},
        persist=True,
        runner=lambda **_kwargs: calls.append("x"),
        budget_status=lambda: {"constraining": True, "remaining_weekly_ops_usd": 0.0},
        record_spend=lambda _amount: None,
    )
    assert calls == []
    assert summary["logged"][0]["action"] == "skipped"
    assert summary["logged"][0]["skip_reason"] == "memo_not_ready_budget"


def test_rerun_for_the_same_close_does_not_duplicate_rows(tmp_path: Path) -> None:
    _green(tmp_path)
    kwargs = {
        "repo_root": tmp_path,
        "now": datetime(2026, 11, 2, 12, tzinfo=UTC),
        "markets": ["ftse350"],
        "sessions_by_market": {"ftse350": [SESSION.isoformat()]},
        "persist": True,
        "runner": lambda **_kwargs: (_ for _ in ()).throw(AssertionError("runner")),
    }
    first = run_strategy_book_memo_job(**kwargs)
    second = run_strategy_book_memo_job(**kwargs)
    log = tmp_path / "docs" / "data" / "strategy_book_memo_log.jsonl"
    assert len(first["logged"]) == 1
    assert second["logged"] == []
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1
    stored = json.loads((tmp_path / "docs" / "data" / "strategy_book_memo_job.json").read_text())
    week = stored["weeks"]["2026-W44"]
    assert week["dry_run_requests"] == 1
    assert week["memo_needed"] == 1


def test_review_date_from_an_observe_fixture(tmp_path: Path) -> None:
    _screen(tmp_path, date(2026, 10, 23), [_screen_row(signal="hold")])
    _write_json(
        tmp_path / "docs" / "data" / "strategy_book_observe.json",
        {
            "episodes": [
                {
                    "episode_id": "ep1",
                    "ticker": "REV.L",
                    "market": "ftse350",
                    "status": "open",
                    "launched": True,
                    "reviews": [{"index": 63, "session": SESSION.isoformat()}],
                },
                {
                    "episode_id": "ep2",
                    "ticker": "SKIP.L",
                    "market": "ftse350",
                    "status": "open",
                    "launched": True,
                    "reviews": [{"index": 62, "session": SESSION.isoformat()}],
                },
            ]
        },
    )
    summary = run_strategy_book_memo_job(
        repo_root=tmp_path,
        now=datetime(2026, 11, 2, 12, tzinfo=UTC),
        markets=["ftse350"],
        sessions_by_market={"ftse350": [SESSION.isoformat()]},
        persist=True,
        runner=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("runner")),
    )
    assert summary["logged"] == [
        {
            "ticker": "REV.L",
            "market": "ftse350",
            "kind": "review_date",
            "session": SESSION.isoformat(),
            "action": "dry_run",
            "skip_reason": None,
        }
    ]
    _memo(tmp_path, "REV.L", "2026-10-20T12:00:00+00:00")
    again = run_strategy_book_memo_job(
        repo_root=tmp_path,
        now=datetime(2026, 11, 2, 13, tzinfo=UTC),
        markets=["ftse350"],
        sessions_by_market={"ftse350": ["2026-11-02"]},
        persist=True,
        runner=lambda **_kwargs: None,
    )
    assert all(
        row["ticker"] != "REV.L" or row["session"] != "2026-11-02" for row in again["logged"]
    )


def test_falling_behind_hook_is_inert_while_spend_is_off() -> None:
    summary = {
        "spend_enabled": False,
        "weeks": {"2026-W44": {"all_but_memo": 10, "skipped_budget": 9}},
    }
    assert memo_routine_falling_behind(summary) is None
    findings = findings_from_memo_job(
        {**summary, "last_run_at": "2026-11-05T12:00:00+00:00", "markets": {}, "logged": []},
        now=datetime(2026, 11, 5, 12, tzinfo=UTC),
    )
    assert [row["title"] for row in findings] == [TITLE_REFRESHED]

    live = {
        "spend_enabled": True,
        "weeks": {"2026-W44": {"all_but_memo": 5, "skipped_budget": 2}},
        "last_run_at": "2026-11-05T12:00:00+00:00",
        "markets": {},
        "logged": [],
    }
    behind = memo_routine_falling_behind(live)
    assert behind is not None
    assert behind["title"] == TITLE_BEHIND
    assert behind["auto_fixable"] is False
    exact = {
        "spend_enabled": True,
        "weeks": {"2026-W44": {"all_but_memo": 5, "skipped_budget": 1}},
    }
    assert memo_routine_falling_behind(exact) is None


def test_weekday_miss_and_refresh_findings(tmp_path: Path) -> None:
    _green(tmp_path)
    summary = run_strategy_book_memo_job(
        repo_root=tmp_path,
        now=datetime(2026, 11, 5, 8, tzinfo=UTC),
        markets=["ftse350"],
        sessions_by_market={"ftse350": [SESSION.isoformat()]},
        persist=True,
        runner=lambda **_kwargs: None,
    )
    findings = findings_from_memo_job(summary, now=datetime(2026, 11, 5, 8, tzinfo=UTC))
    titles = [row["title"] for row in findings]
    assert TITLE_REFRESHED in titles
    assert TITLE_NOT_RUN not in titles
    assert all(row["auto_fixable"] is False for row in findings)
    refreshed = next(row for row in findings if row["title"] == TITLE_REFRESHED)
    assert "AAA.L" in refreshed["summary"]
    assert "no rememo" in refreshed["summary"].lower() or "No rememo" in refreshed["summary"]

    stale = dict(summary)
    stale["last_run_at"] = "2026-11-04T08:00:00+00:00"
    missed = findings_from_memo_job(stale, now=datetime(2026, 11, 5, 8, tzinfo=UTC))
    assert any(row["title"] == TITLE_NOT_RUN and row["severity"] == "warn" for row in missed)


def test_graduated_markets_only_and_missing_observe_is_empty(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "docs" / "data" / "market_status.json",
        {
            "markets": [
                {"market_id": "sp500", "is_graduated": True},
                {"market_id": "dax", "is_graduated": False},
            ]
        },
    )
    assert universe_markets(repo_paths(tmp_path).market_status) == ["ftse350", "sp500"]
    assert (tmp_path / "docs" / "data" / "strategy_book_observe.json").exists() is False


def test_spend_flag_requires_signature_and_the_boolean(tmp_path: Path) -> None:
    from value_investor.strategy_book_memo_job import spend_enabled

    path = tmp_path / "strategy_book_registration.json"
    assert spend_enabled(path) is False
    _write_json(path, {"spend_enabled": True})
    assert spend_enabled(path) is False
    _write_json(path, {"signed_at": "2026-11-05", "spend_enabled": False})
    assert spend_enabled(path) is False
    _write_json(path, {"signed_at": "2026-11-05", "spend_enabled": True})
    assert spend_enabled(path) is True


def test_stale_chart_is_suppressed_and_replay_takes_the_latest_closes(tmp_path: Path) -> None:
    _green(tmp_path)
    paths = repo_paths(tmp_path)
    now = datetime(2026, 11, 5, 12, tzinfo=UTC)
    scheduled = plan_sessions(
        "ftse350",
        paths=paths,
        now=now,
        last_session=None,
        allow_stale=False,
    )
    assert scheduled["latest_bar"] == "2026-10-30"
    assert scheduled["sessions"] == []
    assert scheduled["suppressed_stale"] == ["2026-10-30"]

    replay = plan_sessions(
        "ftse350",
        paths=paths,
        now=now,
        last_session=None,
        allow_stale=True,
        replay_limit=2,
    )
    assert replay["sessions"] == ["2026-10-29", "2026-10-30"]
    assert replay["suppressed_stale"] == []
