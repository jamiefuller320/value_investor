"""Tags on requested strategy-book memos, and the weekly used/unused counts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from value_investor.ops_monitor import check_strategy_book_memo_job
from value_investor.strategy_book_memo_cli import main as memo_cli
from value_investor.strategy_book_memo_spend import TITLE_SPEND
from value_investor.strategy_book_memo_use import (
    FED_BLOCKED,
    FED_FILL,
    FED_NOT_READY,
    FED_NOTHING,
    apply_strategy_book_memo_use,
    fed_for_row,
)

_FILL = {
    "kind": "filled",
    "market": "ftse350",
    "ticker": "DATA.L",
    "session": "2026-11-20",
    "fill_session": "2026-11-21",
    "column": "primary",
}
_EPISODE = {
    "column": "primary",
    "market": "ftse350",
    "ticker": "DATA.L",
    "signal_session": "2026-11-20",
    "memo_by_signal_job": True,
    "memo_verdict": "accumulate",
}


def _requested(**extra: object) -> dict:
    row = {
        "ticker": "DATA.L",
        "market": "ftse350",
        "kind": "signal_day",
        "session": "2026-11-20",
        "action": "requested",
        "memo_finished_at": "2026-11-21T10:00:00+00:00",
        "verdict": "accumulate",
    }
    row.update(extra)
    return row


def test_fill_when_the_memo_was_in_time_for_the_primary_episode() -> None:
    assert fed_for_row(_requested(), decision=_FILL, episode=_EPISODE) == FED_FILL


def test_late_memo_is_not_ready_even_when_another_memo_filled() -> None:
    row = _requested(memo_finished_at="2026-11-21T18:00:00+00:00")
    episode = {**_EPISODE, "memo_by_signal_job": False, "memo_verdict": "neutral"}
    assert fed_for_row(row, decision=_FILL, episode=episode) == FED_NOT_READY


def test_blocking_verdict_in_time_is_memo_blocked() -> None:
    decision = {
        "kind": "memo_blocked",
        "market": "ftse350",
        "ticker": "DATA.L",
        "session": "2026-11-20",
        "fill_session": "2026-11-21",
        "column": "primary",
        "verdict": "pass",
    }
    row = _requested(verdict="pass")
    assert fed_for_row(row, decision=decision, episode=None) == FED_BLOCKED


def test_stale_memo_at_the_close_is_memo_not_ready() -> None:
    decision = {
        "kind": "memo_not_ready",
        "market": "ftse350",
        "ticker": "DATA.L",
        "session": "2026-11-20",
        "fill_session": "2026-11-21",
        "column": "primary",
    }
    row = _requested(memo_finished_at="2026-10-01T10:00:00+00:00")
    assert fed_for_row(row, decision=decision, episode=None) == FED_NOT_READY


def test_fresh_memo_is_not_blamed_for_a_not_ready_event() -> None:
    decision = {
        "kind": "memo_not_ready",
        "market": "ftse350",
        "ticker": "DATA.L",
        "session": "2026-11-20",
        "fill_session": "2026-11-21",
        "column": "primary",
    }
    assert fed_for_row(_requested(), decision=decision, episode=None) == FED_NOTHING


def test_already_open_and_other_columns_feed_nothing() -> None:
    already = {
        "kind": "already_open_skip",
        "market": "ftse350",
        "ticker": "DATA.L",
        "session": "2026-11-20",
    }
    assert fed_for_row(_requested(), decision=already, episode=None) == FED_NOTHING
    shadow = {**_FILL, "column": "decline_rejected_shadow"}
    assert fed_for_row(_requested(), decision=shadow, episode=_EPISODE) == FED_NOTHING
    control = {
        "kind": "memo_not_ready",
        "market": "ftse350",
        "ticker": "DATA.L",
        "session": "2026-11-20",
        "fill_session": "2026-11-21",
        "column": "buy_on_signal",
    }
    assert fed_for_row(_requested(), decision=control, episode=None) == FED_NOTHING
    assert fed_for_row(_requested(), decision=None, episode=None) == FED_NOTHING


def test_review_date_and_skipped_rows_are_not_entry_use() -> None:
    review = _requested(kind="review_date")
    assert fed_for_row(review, decision=_FILL, episode=_EPISODE) == FED_NOTHING
    skipped = _requested(action="skipped", skip_reason="memo_not_ready_budget")
    assert fed_for_row(skipped, decision=_FILL, episode=_EPISODE) is None


def _repo(tmp_path: Path, *, observe: object, requested: dict, skipped: dict) -> Path:
    data = tmp_path / "docs" / "data"
    data.mkdir(parents=True)
    log = data / "strategy_book_memo_log.jsonl"
    skipped_line = json.dumps(skipped, ensure_ascii=False, separators=(",", ":"))
    requested_line = json.dumps(requested, ensure_ascii=False, separators=(",", ":"))
    log.write_text(skipped_line + "\n" + requested_line + "\n", encoding="utf-8")
    (data / "strategy_book_observe.json").write_text(json.dumps(observe), encoding="utf-8")
    return log


def test_persist_tags_requested_rows_and_leaves_skips_unchanged(tmp_path: Path) -> None:
    skipped = {
        "ticker": "DATA.L",
        "market": "ftse350",
        "kind": "signal_day",
        "session": "2026-11-20",
        "action": "skipped",
        "skip_reason": "memo_not_ready_budget",
    }
    observe = {"events": [_FILL], "episodes": [_EPISODE]}
    log = _repo(tmp_path, observe=observe, requested=_requested(), skipped=skipped)
    before_observe = (tmp_path / "docs" / "data" / "strategy_book_observe.json").read_bytes()
    first = apply_strategy_book_memo_use(repo_root=tmp_path, persist=True)
    assert first["wrote"] is True
    assert first["rows"][1]["fed"] == FED_FILL
    text = log.read_text(encoding="utf-8").splitlines()
    assert json.loads(text[0]) == skipped
    assert json.loads(text[1])["fed"] == FED_FILL
    assert "action" not in text[0] or json.loads(text[0])["action"] == "skipped"
    second = apply_strategy_book_memo_use(repo_root=tmp_path, persist=True)
    assert second["wrote"] is False
    assert log.read_text(encoding="utf-8").splitlines() == text
    assert (
        tmp_path / "docs" / "data" / "strategy_book_observe.json"
    ).read_bytes() == before_observe


def test_unreadable_forward_book_tags_nothing_and_says_so(tmp_path: Path) -> None:
    data = tmp_path / "docs" / "data"
    data.mkdir(parents=True)
    log = data / "strategy_book_memo_log.jsonl"
    log.write_text(
        json.dumps(_requested(), separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    (data / "strategy_book_observe.json").write_text("{", encoding="utf-8")
    result = apply_strategy_book_memo_use(repo_root=tmp_path, persist=True)
    assert result["rows"][0]["fed"] == FED_NOTHING
    assert result["note"]
    assert "unreadable" in result["note"]


def test_show_use_does_not_write(tmp_path: Path, capsys) -> None:
    skipped = {
        "action": "skipped",
        "market": "ftse350",
        "ticker": "DATA.L",
        "session": "2026-11-20",
    }
    observe = {"events": [_FILL], "episodes": [_EPISODE]}
    log = _repo(tmp_path, observe=observe, requested=_requested(), skipped=skipped)
    before = log.read_bytes()
    assert memo_cli(["--repo-root", str(tmp_path), "--show-use"]) == 0
    assert log.read_bytes() == before
    payload = json.loads(capsys.readouterr().out)
    assert payload["influences_live"] is False
    assert payload["fill"] == 1
    assert payload["used"] == 1
    assert payload["unused"] == 0


def test_check_wires_use_into_the_spend_finding(monkeypatch, tmp_path: Path) -> None:
    def fake_job(**kwargs):
        assert kwargs["persist"] is False
        return {
            "spend_enabled": True,
            "weeks": {"2026-W47": {"requested": 1, "skipped_budget": 0, "memo_needed": 1}},
            "last_run_at": "2026-11-20T12:00:00+00:00",
            "markets": {},
            "errors": [],
        }

    def fake_use(**kwargs):
        assert kwargs["persist"] is False
        return {
            "rows": [{"action": "requested", "session": "2026-11-20", "fed": "fill"}],
            "note": None,
            "wrote": False,
        }

    monkeypatch.setattr(
        "value_investor.strategy_book_memo_job.run_strategy_book_memo_job", fake_job
    )
    monkeypatch.setattr(
        "value_investor.strategy_book_memo_use.apply_strategy_book_memo_use", fake_use
    )
    findings = check_strategy_book_memo_job(
        repo_root=tmp_path,
        now=datetime(2026, 11, 20, tzinfo=UTC),
        persist=False,
    )
    spend = next(row for row in findings if row.title == TITLE_SPEND)
    assert spend.auto_fixable is False
    assert "2026-W47 use: 1 used (1 fill, 0 memo_blocked), 0 unused" in spend.summary


def test_runbook_names_the_tags_and_the_persisted_finding() -> None:
    text = Path("docs/ops/ops-monitor.md").read_text(encoding="utf-8")
    assert "used/unused counts" in text
    assert "`fill`, `memo_blocked`, `memo_not_ready`" in text
    assert "docs/data/ops_status.json" in text
    assert "auto_fixable=false" in text
    job = Path("docs/ops/strategy-book-memo-job.md").read_text(encoding="utf-8")
    assert "does not rememo, ingest, or change a fill" in job
