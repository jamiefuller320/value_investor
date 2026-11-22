"""Budget-skip catch-up planning. No network and no model."""

from __future__ import annotations

import json

import pytest

from value_investor.strategy_book_memo_catchup import (
    appended_suffix,
    apply_saved_artifacts,
    is_publishable_artifact,
    merge_log_text,
    plan_budget_skip_catchup,
)

COMMIT_A = "a" * 40
COMMIT_B = "b" * 40


def _skip(ticker: str, *, market: str = "sp500", session: str = "2026-11-20", commit: str = COMMIT_A) -> dict:
    return {
        "ticker": ticker,
        "market": market,
        "kind": "signal_day",
        "session": session,
        "action": "skipped",
        "skip_reason": "memo_not_ready_budget",
        "data_commit": commit,
        "inputs": [
            {
                "path": f"docs/data/library/markets/{market}/screen/latest_signals.csv",
                "sha256": "abc",
            },
            {
                "path": f"docs/data/library/markets/{market}/screen/latest_summary.json",
                "sha256": "def",
            },
        ],
    }


def test_plan_keeps_budget_skips_and_pins_one_screen_commit() -> None:
    rows = [
        _skip("WDC"),
        _skip("MU"),
        {
            "ticker": "DATA.L",
            "market": "ftse350",
            "kind": "signal_day",
            "session": "2026-11-20",
            "action": "skipped",
            "skip_reason": "memo_not_ready_budget",
            "data_commit": COMMIT_B,
            "inputs": [],
        },
    ]
    plan = plan_budget_skip_catchup(rows)
    assert plan["sessions_by_market"] == {
        "ftse350": ["2026-11-20"],
        "sp500": ["2026-11-20"],
    }
    assert {item["ticker"] for item in plan["pending"]} == {"WDC", "MU", "DATA.L"}
    assert plan["screen_snapshots"] == [
        {
            "path": "docs/data/library/markets/sp500/screen/latest_signals.csv",
            "commit": COMMIT_A,
        },
        {
            "path": "docs/data/library/markets/sp500/screen/latest_summary.json",
            "commit": COMMIT_A,
        },
    ]


def test_plan_drops_a_skip_that_was_requested_later() -> None:
    rows = [
        _skip("WDC"),
        {
            "ticker": "WDC",
            "market": "sp500",
            "kind": "signal_day",
            "session": "2026-11-20",
            "action": "requested",
        },
    ]
    plan = plan_budget_skip_catchup(rows)
    assert plan["pending"] == []
    assert plan["screen_snapshots"] == []


def test_plan_rejects_two_commits_for_one_screen() -> None:
    rows = [_skip("WDC", commit=COMMIT_A), _skip("MU", commit=COMMIT_B)]
    with pytest.raises(ValueError, match="two commits"):
        plan_budget_skip_catchup(rows)


def test_publishable_paths_are_memos_and_usage_shards() -> None:
    assert is_publishable_artifact(
        "docs/data/library/markets/sp500/screen/research/WDC/research.json"
    )
    assert is_publishable_artifact("docs/data/research/DATA.L/research.md")
    assert is_publishable_artifact("docs/data/agent_usage/2026-11-22/memo-1.jsonl")
    assert not is_publishable_artifact(
        "docs/data/library/markets/sp500/screen/research/WDC/sources/sec_companyfacts.json"
    )
    assert not is_publishable_artifact(
        "docs/data/library/markets/sp500/screen/latest_signals.csv"
    )
    assert not is_publishable_artifact("docs/data/library/policy.json")
    assert not is_publishable_artifact("docs/data/charts/WDC.json")
    assert not is_publishable_artifact("docs/data/eodhd/WDC.json")


def test_merge_log_appends_only_new_rows() -> None:
    existing = json.dumps({"ticker": "WDC", "market": "sp500", "kind": "signal_day", "session": "2026-11-20", "action": "skipped"}) + "\n"
    new_rows = [
        {"ticker": "WDC", "market": "sp500", "kind": "signal_day", "session": "2026-11-20", "action": "skipped"},
        {"ticker": "WDC", "market": "sp500", "kind": "signal_day", "session": "2026-11-20", "action": "requested"},
    ]
    merged = merge_log_text(existing, new_rows)
    assert merged.count("\n") == 2
    assert '"action":"requested"' in merged
    assert merged.startswith(existing.strip())


def test_appended_suffix_rejects_a_rewrite() -> None:
    assert appended_suffix(b"a\n", b"a\nb\n") == b"b\n"
    assert appended_suffix(b"a\n", b"a\n") == b""
    assert appended_suffix(b"a\n", b"b\n") is None


def test_apply_saved_artifacts_appends_the_log_and_skips_vendor_paths(tmp_path) -> None:
    workdir = tmp_path / "work"
    files = workdir / "files"
    memo = files / "docs/data/research/DATA.L/research.json"
    memo.parent.mkdir(parents=True)
    memo.write_text('{"research_verdict":"buy"}', encoding="utf-8")
    shard = files / "docs/data/agent_usage/2026-11-22/memo.jsonl"
    shard.parent.mkdir(parents=True)
    shard.write_bytes(b'{"run":1}\n')
    (workdir / "manifest.json").write_text(
        json.dumps(
            {
                "log_rows": [
                    {
                        "ticker": "DATA.L",
                        "market": "ftse350",
                        "kind": "signal_day",
                        "session": "2026-11-20",
                        "action": "requested",
                    }
                ],
                "files": [
                    {"path": "docs/data/research/DATA.L/research.json", "mode": "replace"},
                    {"path": "docs/data/agent_usage/2026-11-22/memo.jsonl", "mode": "append"},
                ],
            }
        ),
        encoding="utf-8",
    )
    repo = tmp_path / "repo"
    log = repo / "docs/data/strategy_book_memo_log.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text('{"ticker":"OLD","market":"sp500","kind":"signal_day","session":"2026-11-18","action":"requested"}\n', encoding="utf-8")
    changed = apply_saved_artifacts(repo, workdir)
    text = log.read_text(encoding="utf-8")
    assert "OLD" in text
    assert "DATA.L" in text
    assert (repo / "docs/data/research/DATA.L/research.json").is_file()
    assert (repo / "docs/data/agent_usage/2026-11-22/memo.jsonl").read_bytes() == b'{"run":1}\n'
    assert "docs/data/strategy_book_memo_log.jsonl" in changed
