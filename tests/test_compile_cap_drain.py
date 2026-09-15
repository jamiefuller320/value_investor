"""Tests for idle compile-cap / role-coherence backlog drain."""

from __future__ import annotations

from pathlib import Path

from value_investor.compile_cap_drain import (
    COMPILE_CAP_DRAIN_PRIORITY_FLOOR,
    COMPILE_CAP_DRAIN_SOURCE,
    compile_next_compile_cap_drain_task,
    evaluate_compile_cap_drain,
    should_defer_parked_hunter_for_compile_cap_drain,
)
from value_investor.engineering_tasks import PARKED_SOURCE_HUNTER_SOURCE
from value_investor.storage import read_json, write_json


def _write_suggestions(path: Path, rows: list[dict]) -> None:
    write_json(path, {"suggestions": rows}, compact=False)


def _suggestion(
    *,
    area: str,
    text: str,
    priority: str = "medium",
    recorded_at: str = "2026-09-14T12:00:00+00:00",
) -> dict:
    return {
        "area": area,
        "suggestion": text,
        "priority": priority,
        "recorded_at": recorded_at,
        "ticker": "",
    }


def test_compile_cap_drain_skips_when_priority_queue_busy(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    write_json(
        tasks_path,
        {
            "tasks": [
                {
                    "id": "eng-20260914-01",
                    "area": "ingest",
                    "title": "Priority ingest work",
                    "summary": "Priority ingest work",
                    "priority": "high",
                    "priority_score": 99.0,
                    "source": "post_run_review",
                    "status": "open",
                    "evidence": {},
                    "acceptance_criteria": [],
                    "allowed_paths": ["src/value_investor/research/filings.py"],
                    "blocked_paths": [],
                }
            ]
        },
        compact=False,
    )
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    latest_path = tmp_path / "latest.json"
    write_json(latest_path, {"run_at": "2026-09-14T12:00:00+00:00"}, compact=False)
    suggestions = tmp_path / "suggestions.json"
    _write_suggestions(
        suggestions,
        [_suggestion(area="prompt", text=f"Suggestion backlog item {i}") for i in range(12)],
    )
    decision = evaluate_compile_cap_drain(
        tasks_path=tasks_path,
        output_dir=output_dir,
        latest_path=latest_path,
        suggestions_path=suggestions,
        max_tasks=2,
    )
    assert decision.should_compile is False
    assert "priority" in decision.reason


def test_compile_cap_drain_queues_one_and_chains(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    write_json(tasks_path, {"tasks": []}, compact=False)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    latest_path = tmp_path / "latest.json"
    write_json(latest_path, {"run_at": "2026-09-14T12:00:00+00:00"}, compact=False)
    (output_dir / "post_run_review.md").write_text(
        "PRIORITISED IMPROVEMENT PLAN\n"
        "1. [ingest] First plan line for sunday compile cap\n"
        "2. [ingest] Second plan line for sunday compile cap\n",
        encoding="utf-8",
    )
    suggestions = tmp_path / "suggestions.json"
    _write_suggestions(
        suggestions,
        [
            _suggestion(area="prompt", text="Backlog prompt suggestion alpha unique"),
            _suggestion(area="scoring", text="Backlog scoring suggestion beta unique"),
            _suggestion(area="ops", text="Backlog ops suggestion gamma unique"),
        ],
    )

    first = compile_next_compile_cap_drain_task(
        apply=True,
        tasks_path=tasks_path,
        committed_path=tasks_path,
        output_dir=output_dir,
        latest_path=latest_path,
        suggestions_path=suggestions,
        max_tasks=2,
    )
    assert first["compiled_count"] == 1
    assert first["priority_score"] >= COMPILE_CAP_DRAIN_PRIORITY_FLOOR
    payload = read_json(tasks_path)
    drain = next(row for row in payload["tasks"] if row["status"] == "open")
    assert drain["source"] == COMPILE_CAP_DRAIN_SOURCE
    assert (
        "alpha" in drain["title"].lower()
        or "beta" in drain["title"].lower()
        or "gamma" in drain["title"].lower()
    )

    second = compile_next_compile_cap_drain_task(
        apply=True,
        tasks_path=tasks_path,
        committed_path=tasks_path,
        output_dir=output_dir,
        latest_path=latest_path,
        suggestions_path=suggestions,
        max_tasks=2,
    )
    assert second["compiled_count"] == 0
    assert "already queued" in second["reason"]

    drain["status"] = "merged"
    write_json(tasks_path, payload, compact=False)
    third = compile_next_compile_cap_drain_task(
        apply=True,
        tasks_path=tasks_path,
        committed_path=tasks_path,
        output_dir=output_dir,
        latest_path=latest_path,
        suggestions_path=suggestions,
        max_tasks=2,
    )
    assert third["compiled_count"] == 1
    assert third["task_ids"][0] != drain["id"]


def test_hunter_defers_while_compile_cap_drain_backlog(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    write_json(tasks_path, {"tasks": []}, compact=False)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    latest_path = tmp_path / "latest.json"
    write_json(latest_path, {"run_at": "2026-09-14T12:00:00+00:00"}, compact=False)
    suggestions = tmp_path / "suggestions.json"
    _write_suggestions(
        suggestions,
        [_suggestion(area="prompt", text=f"Drain defer hunter item {i} unique") for i in range(10)],
    )
    defer, reason = should_defer_parked_hunter_for_compile_cap_drain(
        tasks_path=tasks_path,
        output_dir=output_dir,
        latest_path=latest_path,
        suggestions_path=suggestions,
        max_tasks=2,
    )
    assert defer is True
    assert "outranks hunter" in reason

    write_json(
        tasks_path,
        {
            "tasks": [
                {
                    "id": "eng-20260914-99",
                    "area": "ingest",
                    "title": "Priority blocks hunter defer check",
                    "summary": "Priority",
                    "priority": "high",
                    "priority_score": 90.0,
                    "source": "post_run_review",
                    "status": "open",
                    "evidence": {},
                    "acceptance_criteria": [],
                    "allowed_paths": [],
                    "blocked_paths": [],
                }
            ]
        },
        compact=False,
    )
    defer2, reason2 = should_defer_parked_hunter_for_compile_cap_drain(
        tasks_path=tasks_path,
        output_dir=output_dir,
        latest_path=latest_path,
        suggestions_path=suggestions,
        max_tasks=2,
    )
    assert defer2 is False
    assert "priority queue busy" in reason2


def test_compile_cap_drain_allows_open_hunter_background(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    write_json(
        tasks_path,
        {
            "tasks": [
                {
                    "id": "eng-20260914-12",
                    "area": "ingest",
                    "title": "Hunt fetchable IR source for parked sp500 leftover ZZZZ",
                    "summary": "hunter",
                    "priority": "low",
                    "priority_score": 12.0,
                    "source": PARKED_SOURCE_HUNTER_SOURCE,
                    "status": "open",
                    "evidence": {"hunter_ticker": "ZZZZ", "market_id": "sp500"},
                    "acceptance_criteria": [],
                    "allowed_paths": ["src/value_investor/research/filings.py"],
                    "blocked_paths": [],
                }
            ]
        },
        compact=False,
    )
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    latest_path = tmp_path / "latest.json"
    write_json(latest_path, {"run_at": "2026-09-14T12:00:00+00:00"}, compact=False)
    suggestions = tmp_path / "suggestions.json"
    _write_suggestions(
        suggestions,
        [_suggestion(area="prompt", text=f"With hunter open still drain {i}") for i in range(10)],
    )
    result = compile_next_compile_cap_drain_task(
        apply=True,
        tasks_path=tasks_path,
        committed_path=tasks_path,
        output_dir=output_dir,
        latest_path=latest_path,
        suggestions_path=suggestions,
        max_tasks=2,
    )
    assert result["compiled_count"] == 1
    payload = read_json(tasks_path)
    open_rows = [row for row in payload["tasks"] if row["status"] == "open"]
    sources = {row["source"] for row in open_rows}
    assert COMPILE_CAP_DRAIN_SOURCE in sources
    assert PARKED_SOURCE_HUNTER_SOURCE in sources
    drain = next(row for row in open_rows if row["source"] == COMPILE_CAP_DRAIN_SOURCE)
    hunter = next(row for row in open_rows if row["source"] == PARKED_SOURCE_HUNTER_SOURCE)
    assert float(drain["priority_score"]) > float(hunter["priority_score"])
