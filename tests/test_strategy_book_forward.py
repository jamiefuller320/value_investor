"""Close refresh, forward job, and observe findings. No network."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pandas as pd

from value_investor.ops_monitor import check_strategy_book_observe
from value_investor.strategy_book_forward import (
    TITLE_CLOSES_STALE,
    TITLE_FAILED,
    TITLE_INTERIM,
    TITLE_LATE,
    TITLE_PENDING,
    TITLE_REFRESHED,
    TITLE_T212,
    TITLE_THICKNESS,
    run_forward_job,
)
from value_investor.strategy_book_forward_cli import main as forward_main
from value_investor.strategy_book_memo_job import TITLE_BEHIND
from value_investor.strategy_book_observe import (
    F9Fact,
    GateFact,
    MemoFact,
    NameSpec,
    ScreenFact,
    options_for,
    walk_book,
)
from value_investor.strategy_book_prices import run_close_refresh
from value_investor.strategy_book_replay_cli import main as replay_main
from value_investor.strategy_book_rules import (
    COLUMN_PRIMARY,
    forward_live,
    forward_start_date,
)

NOW = datetime(2026, 11, 5, 22, 0, tzinfo=UTC)
AS_OF = "2026-11-05T22:00:00+00:00"


def test_close_refresh_rebuilds_a_stale_chart_and_leaves_a_current_one(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _repo(tmp_path)
    data = repo / "docs" / "data"
    _screen(data, date(2026, 11, 4), ["BEHIND", "CURRENT"])
    behind = data / "charts" / "BEHIND.json"
    current = data / "charts" / "CURRENT.json"
    _chart(behind, ["2026-11-03"], [10.0])
    _chart(current, ["2026-11-04", "2026-11-05"], [10.0, 11.0])
    before = current.read_bytes()
    called: list[str] = []

    def fake_fetch(tickers, period="2y", market=None):
        called.extend(tickers)
        index = pd.to_datetime(["2026-11-04", "2026-11-05"])
        frame = pd.DataFrame(
            {"Close": [10.0, 11.0], "High": [11.0, 12.0], "Low": [9.0, 10.0], "Volume": [1, 1]},
            index=index,
        )
        return {ticker: frame for ticker in tickers}

    monkeypatch.setattr("value_investor.technical_analysis.fetch_price_history", fake_fetch)
    dry = run_close_refresh(repo_root=repo, now=NOW, apply=False, pause_seconds=0)
    assert dry["would_refresh"] == 1
    assert dry["left_alone"] == 1
    assert called == []
    assert current.read_bytes() == before

    result = run_close_refresh(repo_root=repo, now=NOW, apply=True, pause_seconds=0)
    assert called == ["BEHIND"]
    assert current.read_bytes() == before
    assert behind.read_bytes() != b""
    stored = json.loads((data / "strategy_book_closes.json").read_text(encoding="utf-8"))
    assert stored["markets"]["ftse350"]["closes_through"] == "2026-11-05"
    assert "refresh_tickers" not in stored["markets"]["ftse350"]
    assert result["markets"]["ftse350"]["refresh_tickers"] == ["BEHIND"]
    assert stored["markets"]["ftse350"]["stale"] is False


def test_close_refresh_keeps_a_name_inside_the_budget(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    data = repo / "docs" / "data"
    _screen(data, date(2026, 11, 4), ["AAA", "BBB"])
    aaa = data / "charts" / "AAA.json"
    bbb = data / "charts" / "BBB.json"
    _chart(aaa, ["2026-11-03"], [1.0])
    _chart(bbb, ["2026-11-03"], [1.0])
    bbb_bytes = bbb.read_bytes()
    called: list[str] = []

    def fake_fetch(tickers, period="2y", market=None):
        called.extend(tickers)
        index = pd.to_datetime(["2026-11-05"])
        frame = pd.DataFrame({"Close": [2.0]}, index=index)
        return {ticker: frame for ticker in tickers}

    monkeypatch.setattr("value_investor.technical_analysis.fetch_price_history", fake_fetch)
    run_close_refresh(repo_root=repo, now=NOW, apply=True, budget=1, pause_seconds=0)
    assert called == ["AAA"]
    assert bbb.read_bytes() == bbb_bytes


def test_weekend_apply_does_not_fetch(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    data = repo / "docs" / "data"
    _screen(data, date(2026, 11, 4), ["AAA"])
    chart = data / "charts" / "AAA.json"
    _chart(chart, ["2026-11-03"], [1.0])
    before = chart.read_bytes()

    def fail_fetch(*_args, **_kwargs):
        raise AssertionError("weekend fetch")

    monkeypatch.setattr("value_investor.technical_analysis.fetch_price_history", fail_fetch)
    result = run_close_refresh(
        repo_root=repo,
        now=datetime(2026, 11, 7, 22, 0, tzinfo=UTC),
        apply=True,
        pause_seconds=0,
    )
    assert result["skipped"] == "weekend"
    assert result["fetched"] == 0
    assert chart.read_bytes() == before
    assert not (data / "strategy_book_closes.json").exists()


def test_entry_not_before_does_not_open_an_earlier_episode() -> None:
    closes = [80.0 - index for index in range(15)] + [100.0, 101.0]
    days = _weekdays(len(closes), date(2026, 8, 3))
    run_day = days[13]
    fill = days[15]
    spec = NameSpec(
        market="ftse350",
        ticker="AAA",
        sessions=days,
        closes=closes,
        screens=[
            ScreenFact(
                run_date=run_day,
                signal="buy",
                adjusted_signal="buy",
                research_verdict="hold",
            )
        ],
        gates=[GateFact(as_of=run_day, decline="clear", sector="sound")],
        memos=[
            MemoFact(
                finished_at=datetime.combine(fill, time(8), tzinfo=UTC),
                verdict="hold",
            )
        ],
        f9=[
            F9Fact(
                as_of=days[14],
                key_filing_bodies=True,
                fcf_basis_bound=True,
                overlay_bound=True,
                memo_recent=True,
            )
        ],
    )
    opened = walk_book([spec], options=options_for("forward"))
    assert any(row["column"] == COLUMN_PRIMARY for row in opened["episodes"])
    cut = options_for("forward")
    cut.entry_not_before = days[15]
    held = walk_book([spec], options=cut)
    assert not any(row["column"] == COLUMN_PRIMARY for row in held["episodes"])


def test_forward_start_ignores_august_when_the_seal_is_absent(tmp_path: Path) -> None:
    path = tmp_path / "strategy_book_registration.json"
    assert forward_start_date(path, decision=date(2026, 11, 5)) == date(2026, 11, 5)
    path.write_text(
        json.dumps({"signed": True, "signed_at": "2026-11-05T21:00:00Z", "forward_live": "true"}),
        encoding="utf-8",
    )
    assert forward_live(path) is False
    assert forward_start_date(path, decision=date(2026, 11, 6)) == date(2026, 11, 5)


def test_dry_run_writes_counts_only(tmp_path: Path) -> None:
    repo = _live_tree(tmp_path, live=False)
    summary = run_forward_job(repo_root=repo, now=NOW, apply=True)
    data = repo / "docs" / "data"
    assert (data / "strategy_book_forward_status.json").is_file()
    assert not (data / "strategy_book_observe.json").exists()
    assert not (data / "strategy_book_gate_log.jsonl").exists()
    text = (data / "strategy_book_forward_status.json").read_text(encoding="utf-8")
    for token in ("fair_cost", "median", "episodes", "gross_return", "capital_return"):
        assert token not in text
    assert summary["forward_live"] is False
    assert summary["dry_run"] is True
    assert summary["signals"] == 0


def test_live_gate_log_hashes_the_chart(tmp_path: Path) -> None:
    repo = _live_tree(tmp_path, live=True)
    data = repo / "docs" / "data"
    chart = data / "charts" / "AAA.json"
    summary = run_forward_job(repo_root=repo, now=NOW, apply=True, data_commit="abc")
    assert summary["wrote_observe"] is True
    assert (data / "strategy_book_observe.json").is_file()
    log = (data / "strategy_book_gate_log.jsonl").read_text(encoding="utf-8")
    row = json.loads(log.splitlines()[0])
    digest = hashlib.sha256(chart.read_bytes()).hexdigest()
    assert any(item["sha256"] == digest for item in row["inputs"])
    assert row["data_commit"] == "abc"
    status = json.loads((data / "strategy_book_forward_status.json").read_text(encoding="utf-8"))
    assert "fair_cost" not in json.dumps(status)


def test_provenance_mismatch_does_not_rewrite_the_log(tmp_path: Path) -> None:
    repo = _live_tree(tmp_path, live=True)
    data = repo / "docs" / "data"
    digest = hashlib.sha256(b"chart").hexdigest()
    log = data / "strategy_book_gate_log.jsonl"
    log.write_text(
        json.dumps(
            {
                "kind": "session",
                "market": "ftse350",
                "ticker": "AAA",
                "as_of": "2026-11-05",
                "inputs": [{"path": "docs/data/charts/AAA.json", "sha256": digest}],
                "data_commit": "abc",
                "observed_at": "2026-11-05T21:40:00+00:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before = log.read_bytes()

    def reader(_commit: str, _path: str) -> bytes:
        return b"other"

    summary = run_forward_job(
        repo_root=repo,
        now=NOW,
        apply=True,
        data_commit="abc",
        blob_reader=reader,
    )
    assert summary["provenance_mismatches"] == 1
    assert log.read_bytes() == before


def test_forward_cli_prints_counts_only(tmp_path: Path, capsys) -> None:
    repo = _live_tree(tmp_path, live=False)
    assert forward_main(["--repo-root", str(repo), "--as-of", AS_OF]) == 0
    text = capsys.readouterr().out
    assert "fair_cost" not in text
    assert "episodes" not in text
    assert "signals" in text


def test_replay_persist_outside_a_fixture_stays_there(tmp_path: Path, capsys) -> None:
    repo = _repo(tmp_path)
    _write(
        repo / "docs" / "data" / "strategy_book_registration.json",
        {"signed": True, "signed_at": "2026-11-05", "signature": "owner", "forward_live": False},
    )
    outside = tmp_path / "fixture"
    outside.mkdir()
    assert replay_main(["--repo-root", str(repo), "--fixture-dir", str(outside), "--persist"]) == 0
    assert (outside / "strategy_book_replay.json").is_file()
    assert not (repo / "docs" / "data" / "strategy_book_replay.json").exists()
    capsys.readouterr()


def test_observe_findings_are_not_auto_fixable(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    data = repo / "docs" / "data"
    _write(
        data / "strategy_book_registration.json",
        {"signed": True, "signed_at": "2026-11-05T21:00:00Z", "forward_live": False},
    )
    _write(
        data / "strategy_book_forward_status.json",
        {
            "generated_at": "2026-11-05T22:00:00+00:00",
            "signals": 10,
            "entries_that_would_open": 2,
            "filled": 1,
            "pending_fill": 1,
            "late_signal": 2,
            "memo_not_ready": 3,
            "memo_blocked": 0,
            "blocked_reasons": {"gate": 4},
            "sample_tickers": ["AAA"],
            "interim_announce": True,
            "thickness_ready": True,
            "disposition": False,
            "errors": [],
            "provenance_mismatches": 0,
        },
    )
    _write(
        data / "strategy_book_closes.json",
        {
            "markets": {
                "ftse350": {
                    "stale": True,
                    "buy_tier": 20,
                    "more_than_one_session_behind": 5,
                    "sample_tickers": ["ZZ"],
                }
            }
        },
    )
    findings = check_strategy_book_observe(repo_root=repo, now=NOW)
    titles = {row.title for row in findings}
    assert TITLE_PENDING in titles
    assert TITLE_REFRESHED in titles
    assert TITLE_INTERIM in titles
    assert TITLE_LATE in titles
    assert TITLE_BEHIND in titles
    assert TITLE_CLOSES_STALE in titles
    assert TITLE_T212 in titles
    assert TITLE_THICKNESS not in titles
    assert all(row.auto_fixable is False for row in findings)
    assert all("fair_cost" not in row.summary for row in findings)

    _write(
        data / "strategy_book_registration.json",
        {
            "signed": True,
            "signed_at": "2026-11-05T21:00:00Z",
            "signature": {"by": "owner"},
            "forward_live": True,
        },
    )
    _write(data / "strategy_book_observe.json", {"registration_id": "owner-strategy-book-v0"})
    live = check_strategy_book_observe(repo_root=repo, now=NOW)
    live_titles = {row.title for row in live}
    assert TITLE_PENDING not in live_titles
    assert TITLE_THICKNESS in live_titles
    assert all(row.auto_fixable is False for row in live)

    _write(
        data / "strategy_book_forward_status.json",
        {"generated_at": "2026-11-02T22:00:00+00:00", "signals": 0, "errors": []},
    )
    missed = check_strategy_book_observe(
        repo_root=repo, now=datetime(2026, 11, 5, 7, 45, tzinfo=UTC)
    )
    assert any(row.title == TITLE_FAILED for row in missed)


def test_dashboard_strip_is_read_only() -> None:
    text = Path("docs/app.js").read_text(encoding="utf-8")
    assert 'id: "strategy-book"' in text
    assert '["strategy_book_forward_status", "data/strategy_book_forward_status.json"]' in text
    branch = text.split('if (id === "strategy-book")', 1)[1].split("// Strand A", 1)[0]
    assert "renderStrategyBookObserveSection" in branch
    assert "renderModelLifecycleMonitor" not in branch
    fn = text.split("function renderStrategyBookObserveSection(", 1)[1].split("\nfunction ", 1)[0]
    assert "renderModelLifecycleMonitor" not in fn
    assert "renderObservePathScoreboardPanel" not in fn
    assert "fair_cost" not in fn
    assert "No promote button" in fn
    queue = text.split("function renderQueueHealthMonitor(", 1)[1].split("\nfunction ", 1)[0]
    assert "renderStrategyBookObserveSection(" in queue
    html = Path("docs/index.html").read_text(encoding="utf-8")
    assert "app.js?v=strategy-book-forward-20261105" in html
    runbook = Path("docs/ops/strategy-book-observe.md").read_text(encoding="utf-8")
    assert "## Go-live" in runbook
    registration = Path("docs/ops/strategy-book-registration.md").read_text(encoding="utf-8")
    assert "strategy-book-observe.md" in registration


def test_human_task_covers_forward_live_and_spend() -> None:
    payload = json.loads(Path("docs/human_tasks_checklist.json").read_text(encoding="utf-8"))
    tasks = [task for section in payload["sections"] for task in section["tasks"]]
    row = next(task for task in tasks if task["id"] == "adhoc-strategy-book-memo-spend")
    assert row["doc_path"] == "docs/ops/strategy-book-observe.md"
    assert row["doc_anchor"] == "go-live"
    assert "forward_live" in row["summary"]
    assert "spend_enabled" in row["summary"]
    assert row["automated"] is False


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "docs" / "data").mkdir(parents=True)
    return repo


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _chart(path: Path, days: list[str], closes: list[float]) -> None:
    _write(path, {"dates": days, "closes": closes})


def _screen(data: Path, when: date, tickers: list[str]) -> None:
    _write(
        data / "history" / f"run_{when.strftime('%Y%m%d')}_120000.json",
        {
            "run_at": datetime.combine(when, time(12), tzinfo=UTC).isoformat(),
            "reports": [{"ticker": ticker, "signal": "buy", "name": ticker} for ticker in tickers],
        },
    )


def _live_tree(tmp_path: Path, *, live: bool) -> Path:
    repo = _repo(tmp_path)
    data = repo / "docs" / "data"
    _write(
        data / "strategy_book_registration.json",
        {
            "signed": True,
            "signed_at": "2026-11-05T21:00:00Z",
            "signature": {"by": "owner"},
            "forward_live": live,
            "spend_enabled": False,
        },
    )
    _screen(data, date(2026, 11, 4), ["AAA"])
    _chart(data / "charts" / "AAA.json", ["2026-11-05"], [10.0])
    return repo


def _weekdays(count: int, start: date) -> list[date]:
    days: list[date] = []
    cursor = start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days
