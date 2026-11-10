"""Dated gate store versions: the verdict in force at a session, never a later one."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from value_investor.gate_store_history import (
    DECLINE_KIND,
    HISTORY_STALE_TITLE,
    SECTOR_KIND,
    GateHistory,
    archive_gate_version,
    backfill_from_git,
    history_dir,
    history_findings,
    load_versions,
    version_date,
)
from value_investor.strategy_book_forward import _gate_log_fields
from value_investor.strategy_book_memo_job import run_strategy_book_memo_job
from value_investor.strategy_book_observe import _gate_in_force
from value_investor.strategy_book_signals import evaluate_market

TICKER = "AAA.L"
SESSION = date(2026, 11, 9)


def _decline(as_of: date, verdict: str, *, generated: str | None = None) -> dict:
    return {
        "as_of": as_of.isoformat(),
        "generated_at": generated or f"{as_of.isoformat()}T02:33:00+00:00",
        "names": {TICKER: {"verdict": verdict, "market": "ftse350", "checks": {}}},
    }


def _sector(as_of: date, verdict: str, *, generated: str | None = None) -> dict:
    return {
        "as_of": as_of.isoformat(),
        "generated_at": generated or f"{as_of.isoformat()}T02:33:00+00:00",
        "names": {TICKER: {"market": "ftse350", "sector_verdict": verdict}},
        "names_by_market": {
            "ftse350": {TICKER: {"sector_verdict": verdict, "sector_basis": "own_market"}}
        },
    }


def _data(root: Path) -> Path:
    data = root / "docs" / "data"
    data.mkdir(parents=True, exist_ok=True)
    return data


def _refresh(data: Path, decline: dict, sector: dict) -> None:
    """What the two gate refreshes do: overwrite the live store, archive the dated copy."""
    for name, kind, payload in (
        ("operating_decline_gate.json", DECLINE_KIND, decline),
        ("sector_headwind_gate.json", SECTOR_KIND, sector),
    ):
        store = data / name
        store.write_text(json.dumps(payload), encoding="utf-8")
        archive_gate_version(store, kind, payload)


def _history(data: Path) -> GateHistory:
    return GateHistory.load(
        data / "operating_decline_gate.json", data / "sector_headwind_gate.json"
    )


def test_store_rewritten_after_the_session_keeps_the_verdict_in_force(tmp_path: Path) -> None:
    data = _data(tmp_path)
    _refresh(data, _decline(date(2026, 11, 6), "clear"), _sector(date(2026, 11, 6), "sound"))
    # The morning run after the close rewrites both stores with that day's date.
    _refresh(
        data, _decline(date(2026, 11, 10), "declining"), _sector(date(2026, 11, 10), "headwind")
    )
    live = json.loads((data / "operating_decline_gate.json").read_text(encoding="utf-8"))
    assert live["as_of"] == "2026-11-10"

    decline, sector = _history(data).in_force(SESSION)
    assert decline["as_of"] == "2026-11-06"
    assert decline["names"][TICKER]["verdict"] == "clear"
    assert sector["names_by_market"]["ftse350"][TICKER]["sector_verdict"] == "sound"

    # The run-date version applies from the next session only.
    decline, _ = _history(data).in_force(date(2026, 11, 10))
    assert decline["names"][TICKER]["verdict"] == "clear"
    decline, sector = _history(data).in_force(date(2026, 11, 11))
    assert decline["names"][TICKER]["verdict"] == "declining"
    assert sector["names_by_market"]["ftse350"][TICKER]["sector_verdict"] == "headwind"


def test_no_verdict_dated_on_or_after_the_session_is_ever_read(tmp_path: Path) -> None:
    data = _data(tmp_path)
    days = [date(2026, 11, 3) + timedelta(days=offset) for offset in range(8)]
    for index, day in enumerate(days):
        verdict = "clear" if index % 2 else "declining"
        _refresh(data, _decline(day, verdict), _sector(day, "sound"))
    history = _history(data)
    for session in [days[0] - timedelta(days=1), *days, days[-1] + timedelta(days=1)]:
        decline, sector = history.in_force(session)
        for payload in (decline, sector):
            assert date.fromisoformat(payload["as_of"]) < session or not (
                payload.get("names") or payload.get("names_by_market")
            )
    decline, sector = history.in_force(days[0])
    # Only a later version exists: a stub with no verdicts, dated on the session.
    assert decline == {"as_of": "2026-11-03", "names": {}, "names_by_market": {}}
    assert sector["names_by_market"] == {}


def test_version_is_dated_no_earlier_than_it_was_generated(tmp_path: Path) -> None:
    data = _data(tmp_path)
    backdated = _sector(date(2026, 11, 1), "sound", generated="2026-11-04T20:26:28+00:00")
    assert version_date(backdated) == date(2026, 11, 4)
    _refresh(data, _decline(date(2026, 11, 4), "clear"), backdated)
    history = _history(data)
    _, sector = history.in_force(date(2026, 11, 4))
    assert sector["names_by_market"] == {}
    _, sector = history.in_force(date(2026, 11, 5))
    assert sector["as_of"] == "2026-11-04"
    assert sector["names_by_market"]["ftse350"][TICKER]["sector_verdict"] == "sound"


def test_same_day_rerun_replaces_and_older_copy_does_not(tmp_path: Path) -> None:
    data = _data(tmp_path)
    store = data / "operating_decline_gate.json"
    day = date(2026, 11, 9)
    early = _decline(day, "clear", generated="2026-11-09T02:33:00+00:00")
    late = _decline(day, "declining", generated="2026-11-09T07:48:00+00:00")
    archive_gate_version(store, DECLINE_KIND, late)
    assert archive_gate_version(store, DECLINE_KIND, early) is None
    path = history_dir(store, DECLINE_KIND) / "2026-11-09.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        assert json.load(handle)["names"][TICKER]["verdict"] == "declining"
    first = path.read_bytes()
    archive_gate_version(store, DECLINE_KIND, late)
    assert path.read_bytes() == first


def test_prune_keeps_the_newest_versions(tmp_path: Path) -> None:
    store = _data(tmp_path) / "operating_decline_gate.json"
    for offset in range(5):
        day = date(2026, 11, 1) + timedelta(days=offset)
        archive_gate_version(store, DECLINE_KIND, _decline(day, "clear"), max_versions=3)
    names = sorted(p.name for p in history_dir(store, DECLINE_KIND).iterdir())
    assert names == ["2026-11-03.json.gz", "2026-11-04.json.gz", "2026-11-05.json.gz"]


def test_live_store_counts_as_a_version_without_an_archive(tmp_path: Path) -> None:
    data = _data(tmp_path)
    (data / "operating_decline_gate.json").write_text(
        json.dumps(_decline(date(2026, 11, 6), "clear")), encoding="utf-8"
    )
    versions = load_versions(data / "operating_decline_gate.json", DECLINE_KIND)
    assert [v.day for v in versions] == [date(2026, 11, 6)]


def test_flat_sector_schema_is_read_by_market(tmp_path: Path) -> None:
    data = _data(tmp_path)
    old = _sector(date(2026, 11, 3), "sound")
    old.pop("names_by_market")
    _refresh(data, _decline(date(2026, 11, 3), "clear"), old)
    _, sector = _history(data).in_force(date(2026, 11, 4))
    assert sector["names_by_market"]["ftse350"][TICKER]["sector_verdict"] == "sound"


def test_walker_and_gate_log_read_the_fact_in_force(tmp_path: Path) -> None:
    data = _data(tmp_path)
    _refresh(data, _decline(date(2026, 11, 6), "clear"), _sector(date(2026, 11, 6), "sound"))
    _refresh(data, _decline(date(2026, 11, 10), "declining"), _sector(date(2026, 11, 10), "sound"))
    facts = _history(data).facts_for("ftse350", TICKER)
    assert [(f.as_of, f.decline) for f in facts] == [
        (date(2026, 11, 6), "clear"),
        (date(2026, 11, 10), "declining"),
    ]
    assert _gate_log_fields(facts, SESSION) == ("clear", "sound", "2026-11-06")
    assert _gate_log_fields(facts, date(2026, 11, 11)) == ("declining", "sound", "2026-11-10")
    assert _gate_log_fields(facts, date(2026, 11, 6)) == (None, None, "2026-11-06")

    class _Name:
        def __init__(self, gates):
            from value_investor.strategy_book_observe import _GateList

            self.gates = _GateList(gates)
            self._gate_fact = None

    gate = _gate_in_force(_Name(facts), SESSION)
    assert gate is not None and gate.decline == "clear" and gate.as_of < SESSION


def _weekdays_ending(end: date, count: int) -> list[date]:
    days: list[date] = []
    cursor = end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(days))


def _signal_tree(root: Path) -> None:
    """One FTSE name that fires the entry rule on ``SESSION`` with every F9 bind but the memo."""
    data = _data(root)
    days = _weekdays_ending(SESSION, 30)
    (data / "charts").mkdir()
    (data / "charts" / f"{TICKER}.json").write_text(
        json.dumps(
            {
                "ticker": TICKER,
                "dates": [d.isoformat() for d in days],
                "closes": [100.0 - i for i in range(len(days))],
            }
        ),
        encoding="utf-8",
    )
    (data / "history").mkdir()
    (data / "history" / "run_20261101_120000.json").write_text(
        json.dumps(
            {
                "run_at": "2026-11-01T12:00:00+00:00",
                "reports": [
                    {
                        "ticker": TICKER,
                        "signal": "buy",
                        "fcf_basis_overlay": True,
                        "adjusted_signal": "buy",
                        "research_verdict": "hold",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    filings = data / "research" / TICKER / "sources" / "filings"
    filings.mkdir(parents=True)
    (filings / "filings_index.json").write_text(
        json.dumps(
            {
                "fetched_at": "2026-10-20T00:00:00+00:00",
                "summary": {
                    "total": 2,
                    "with_body": 2,
                    "period_coverage": {
                        "annual": {"total": 1, "with_body": 1},
                        "interim": {"total": 1, "with_body": 1},
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def test_memo_job_reads_the_version_in_force_not_the_rewritten_store(tmp_path: Path) -> None:
    _signal_tree(tmp_path)
    data = tmp_path / "docs" / "data"
    _refresh(data, _decline(date(2026, 11, 8), "clear"), _sector(date(2026, 11, 8), "sound"))
    _refresh(data, _decline(date(2026, 11, 10), "clear"), _sector(date(2026, 11, 10), "sound"))

    name = evaluate_market("ftse350", SESSION, repo_root=tmp_path).names[0]
    assert name.price_entry
    assert name.checks["part2_decline"].passed
    assert name.checks["part2_decline"].detail["as_of"] == "2026-11-08"
    assert name.checks["part3_sector"].passed
    assert name.eligible_except_memo and name.memo_needed
    assert any("gate_history" in path for path in name.input_paths)

    summary = run_strategy_book_memo_job(
        repo_root=tmp_path,
        now=datetime(2026, 11, 10, 9, tzinfo=UTC),
        markets=["ftse350"],
        sessions_by_market={"ftse350": [SESSION.isoformat()]},
        persist=False,
    )
    report = summary["markets"]["ftse350"]
    assert (report["signals"], report["all_but_memo"], report["memo_needed"]) == (1, 1, 1)


def test_memo_job_without_an_earlier_version_fails_closed(tmp_path: Path) -> None:
    _signal_tree(tmp_path)
    data = tmp_path / "docs" / "data"
    _refresh(data, _decline(date(2026, 11, 10), "clear"), _sector(date(2026, 11, 10), "sound"))
    name = evaluate_market("ftse350", SESSION, repo_root=tmp_path).names[0]
    assert name.checks["part2_decline"].reason == "store_after_session"
    assert name.checks["part3_sector"].reason == "store_after_session"
    assert not name.eligible_except_memo


def test_history_finding_warns_when_stale_or_missing(tmp_path: Path) -> None:
    store = _data(tmp_path) / "operating_decline_gate.json"
    assert history_findings(store, DECLINE_KIND)[0]["title"] == HISTORY_STALE_TITLE
    archive_gate_version(store, DECLINE_KIND, _decline(date(2026, 11, 9), "clear"))
    assert history_findings(store, DECLINE_KIND, today=date(2026, 11, 10)) == []
    stale = history_findings(store, DECLINE_KIND, today=date(2026, 11, 20))
    assert stale and stale[0]["auto_fixable"] is False


def test_backfill_from_git_archives_each_committed_day(tmp_path: Path) -> None:
    import subprocess

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    data = _data(tmp_path)
    store = data / "operating_decline_gate.json"
    for payload in (
        _decline(date(2026, 11, 8), "clear", generated="2026-11-08T02:33:00+00:00"),
        _decline(date(2026, 11, 8), "declining", generated="2026-11-08T07:48:00+00:00"),
        _decline(date(2026, 11, 9), "clear"),
    ):
        store.write_text(json.dumps(payload), encoding="utf-8")
        git("add", ".")
        git("commit", "-q", "-m", "store")
    rel = Path("docs/data/operating_decline_gate.json")
    assert backfill_from_git(tmp_path, rel, DECLINE_KIND) == [
        "2026-11-08.json.gz",
        "2026-11-09.json.gz",
    ]
    decline, _ = GateHistory.load(store, data / "missing.json").in_force(SESSION)
    assert decline["names"][TICKER]["verdict"] == "declining"
