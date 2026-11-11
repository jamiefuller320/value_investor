from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from value_investor.strategy_book_memo_job import spend_enabled
from value_investor.strategy_book_memo_spend import TITLE_SPEND, memo_spend_finding
from value_investor.strategy_book_rules import forward_live

_REGISTRATION = {
    "operational_switches": [
        {
            "at": "2026-11-10T09:00:00Z",
            "switch": "spend_enabled",
            "from": False,
            "to": True,
            "review": {"every_weeks": 4, "next_review_on": "2026-12-08"},
        }
    ]
}


def _summary(spend: bool = True) -> dict:
    return {
        "spend_enabled": spend,
        "weeks": {
            "2026-W45": {"requested": 0, "dry_run_requests": 9},
            "2026-W46": {"requested": 3, "skipped_budget": 1, "memo_needed": 4},
            "2026-W47": {"requested": 5, "skipped_budget": 0, "memo_needed": 5},
        },
    }


def test_silent_while_spend_is_off() -> None:
    assert memo_spend_finding(_summary(spend=False), _REGISTRATION) is None


def test_reports_latest_week_and_total_since_switch() -> None:
    finding = memo_spend_finding(
        _summary(),
        _REGISTRATION,
        weekly_ops={"weekly_ops_cap_usd": 124.5, "remaining_weekly_ops_usd": 80.0},
        now=datetime(2026, 11, 20, tzinfo=UTC),
    )
    assert finding is not None
    assert finding["title"] == TITLE_SPEND
    assert finding["severity"] == "info"
    assert finding["auto_fixable"] is False
    text = finding["summary"]
    assert "2026-W47: 5 memos requested ($2.00 at $0.40), 0 budget skips" in text
    assert "Since switch-on 2026-11-10: 8 memos ($3.20)" in text
    assert "weekly_ops cap $124.50, remaining $80.00" in text
    assert "review next 2026-12-08" in text
    assert "not tracked yet" in text


def test_review_marked_due_on_the_date() -> None:
    finding = memo_spend_finding(
        _summary(), _REGISTRATION, now=datetime(2026, 12, 8, 6, tzinfo=UTC)
    )
    assert finding is not None
    assert "review due 2026-12-08" in finding["summary"]


def test_committed_seal_has_spend_on_and_forward_live_on() -> None:
    path = Path("docs/data/strategy_book_registration.json")
    assert spend_enabled(path) is True
    assert forward_live(path) is True
    payload = json.loads(path.read_text(encoding="utf-8"))
    switches = {row["switch"]: row for row in payload["operational_switches"]}
    assert switches["spend_enabled"]["to"] is True
    assert switches["forward_live"]["to"] is True
    assert switches["forward_live"]["approved_by"] == "owner"
    assert payload["forward_start"] == switches["forward_live"]["forward_start"]


def test_committed_budget_covers_the_memo_raise() -> None:
    budget = json.loads(Path("docs/data/library/policy.json").read_text(encoding="utf-8"))["budget"]
    raise_ = budget["strategy_book_memo_raise"]
    assert raise_["weekly_usd"] == raise_["memos_covered"] * raise_["estimated_memo_usd"]
    base = budget["cycle_surplus_provisional"]["previous_weekly_ops_cap_usd"]
    assert budget["weekly_ops_cap_usd"] >= base >= raise_["weekly_usd"]
