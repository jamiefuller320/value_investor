"""Tests for merged hunter allowlist URL monitor."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from value_investor.engineering_tasks import HUNTER_URL_REPAIR_SOURCE, load_engineering_tasks
from value_investor.hunter_url_monitor import (
    apply_known_canonical_allowlist_repair,
    draft_hunter_url_repair_task,
    monitor_merged_hunter_allowlist_urls,
    recent_merged_hunter_allowlist_tasks,
)


def _filings_with_url(ticker: str, url: str) -> str:
    return f'''"""filings stub."""
PARKED_SOURCE_HUNTER_SKIP: dict[str, str] = {{}}

_BUILTIN_IR_URLS: dict[str, list[str]] = {{
    "{ticker.upper()}": [
        "{url}",
    ],
}}

_IR_ALLOWLIST_URL_CANONICAL: dict[str, str] = {{
}}
'''


def _merged_hunter_task(
    task_id: str,
    *,
    ticker: str = "AZE.BR",
    url: str = "https://dead.example/report.pdf",
    merged_at: str | None = None,
) -> dict:
    return {
        "id": task_id,
        "area": "ingest",
        "title": f"Hunt fetchable IR source for parked euro_depth leftover {ticker}",
        "summary": "hunter task",
        "priority": "low",
        "priority_score": 12.0,
        "source": "parked_source_hunter",
        "status": "merged",
        "merged_at": merged_at or datetime.now(UTC).isoformat(),
        "evidence": {
            "market_id": "euro_depth",
            "hunter_market_id": "euro_depth",
            "hunter_ticker": ticker,
        },
        "allowed_paths": ["src/value_investor/research/filings.py"],
        "blocked_paths": [],
        "_url": url,
    }


def test_recent_merged_hunter_allowlist_tasks_filters_by_market_and_resolution(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    filings_path = tmp_path / "filings.py"
    filings_path.write_text(
        _filings_with_url("AZE.BR", "https://live.example/report.pdf"),
        encoding="utf-8",
    )
    now = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    tasks_path.write_text(
        json.dumps(
            {
                "tasks": [
                    _merged_hunter_task("eng-20260910-01", ticker="AZE.BR"),
                    _merged_hunter_task(
                        "eng-20260801-01",
                        ticker="OLD.BR",
                        merged_at=(now - timedelta(days=60)).isoformat(),
                    ),
                ]
            }
        ),
        encoding="utf-8",
    )
    rows = recent_merged_hunter_allowlist_tasks(
        tasks_path=tasks_path,
        lookback_days=30,
        market_ids=("euro_depth",),
        now=now,
        filings_path=filings_path,
    )
    assert [row["id"] for row in rows] == ["eng-20260910-01"]


def test_apply_known_canonical_allowlist_repair_updates_builtin_and_map(
    tmp_path: Path, monkeypatch
):
    filings_path = tmp_path / "filings.py"
    old_url = "https://dead.example/report.pdf"
    new_url = "https://live.example/report.pdf"
    filings_path.write_text(_filings_with_url("AZE.BR", old_url), encoding="utf-8")
    monkeypatch.setattr(
        "value_investor.research.filings._IR_ALLOWLIST_URL_CANONICAL",
        {old_url: new_url},
    )

    result = apply_known_canonical_allowlist_repair(
        ticker="AZE.BR",
        old_url=old_url,
        new_url=new_url,
        filings_path=filings_path,
        apply=True,
    )
    assert result["applied"] is True
    updated = filings_path.read_text(encoding="utf-8")
    assert new_url in updated
    assert f'"{old_url}":' in updated


def test_monitor_applies_canonical_repair_on_fetch_failure(tmp_path: Path, monkeypatch):
    tasks_path = tmp_path / "engineering_tasks.json"
    filings_path = tmp_path / "filings.py"
    old_url = "https://dead.example/report.pdf"
    new_url = "https://live.example/report.pdf"
    filings_path.write_text(_filings_with_url("AZE.BR", old_url), encoding="utf-8")
    tasks_path.write_text(
        json.dumps({"tasks": [_merged_hunter_task("eng-20260910-01", url=old_url)]}),
        encoding="utf-8",
    )

    def fake_fetch(urls, ticker):
        if list(urls) == [new_url]:
            return True, "ok"
        return False, "failed"

    monkeypatch.setattr(
        "value_investor.hunter_url_monitor.live_fetch_hunter_urls",
        fake_fetch,
    )
    monkeypatch.setattr(
        "value_investor.hunter_url_monitor.canonical_replacement_url",
        lambda url, ticker: new_url if url == old_url else None,
    )
    monkeypatch.setattr(
        "value_investor.hunter_url_monitor.default_filings_path",
        lambda cwd=None: filings_path,
    )

    result = monitor_merged_hunter_allowlist_urls(
        tasks_path=tasks_path,
        committed_path=tasks_path,
        filings_path=filings_path,
        apply=True,
    )
    assert any(row.action == "canonical_applied" for row in result.actions)
    assert new_url in filings_path.read_text(encoding="utf-8")


def test_monitor_drafts_repair_task_when_unfixable(tmp_path: Path, monkeypatch):
    tasks_path = tmp_path / "engineering_tasks.json"
    filings_path = tmp_path / "filings.py"
    bad_url = "https://bad.example/report.pdf"
    filings_path.write_text(_filings_with_url("AZE.BR", bad_url), encoding="utf-8")
    task = _merged_hunter_task("eng-20260910-01", url=bad_url)
    task["evidence"]["verify_status"] = "passed"
    tasks_path.write_text(json.dumps({"tasks": [task]}), encoding="utf-8")

    monkeypatch.setattr(
        "value_investor.hunter_url_monitor.live_fetch_hunter_urls",
        lambda urls, ticker: (False, "live-fetch failed"),
    )
    monkeypatch.setattr(
        "value_investor.hunter_url_monitor.canonical_replacement_url",
        lambda url, ticker: None,
    )
    monkeypatch.setattr(
        "value_investor.hunter_url_monitor.default_filings_path",
        lambda cwd=None: filings_path,
    )

    result = monitor_merged_hunter_allowlist_urls(
        tasks_path=tasks_path,
        committed_path=tasks_path,
        filings_path=filings_path,
        apply=True,
    )
    assert any(row.action == "repair_drafted" for row in result.actions)
    updated = load_engineering_tasks(tasks_path)
    repair_rows = [
        row for row in updated["tasks"] if str(row.get("source") or "") == HUNTER_URL_REPAIR_SOURCE
    ]
    assert len(repair_rows) == 1
    assert repair_rows[0]["evidence"]["failed_url"] == bad_url


def test_draft_hunter_url_repair_task_dedupes_open_repair(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    parent = _merged_hunter_task("eng-20260910-01")
    tasks_path.write_text(
        json.dumps(
            {
                "tasks": [
                    parent,
                    {
                        "id": "eng-20260910-02",
                        "status": "open",
                        "source": HUNTER_URL_REPAIR_SOURCE,
                        "evidence": {
                            "hunter_ticker": "AZE.BR",
                            "failed_url": "https://bad.example/report.pdf",
                        },
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    draft = draft_hunter_url_repair_task(
        parent_task=parent,
        failed_url="https://bad.example/report.pdf",
        failure_reason="dead",
        tasks_path=tasks_path,
        committed_path=tasks_path,
        apply=True,
    )
    assert draft["drafted"] is False
    assert draft["reason"] == "open_repair_already_queued"
