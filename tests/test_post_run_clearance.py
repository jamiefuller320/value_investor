"""Post-run improvement clearance automation."""

from __future__ import annotations

from pathlib import Path

from value_investor.post_run_clearance import (
    TRIGGER_POST_RUN_EMAIL,
    post_run_review_fingerprint,
    run_post_run_clearance_cycle,
)
from value_investor.post_run_review import PostRunReview
from value_investor.storage import write_json


def test_fingerprint_stable_for_same_plan():
    review = PostRunReview(
        executive_summary="",
        persistent_weaknesses="ingest theme",
        this_week_findings="",
        improvement_plan="1. [ingest] Fix IR fetch — expected impact: bodies",
        defer="",
    )
    a = post_run_review_fingerprint(review)
    b = post_run_review_fingerprint(review)
    assert a == b
    assert len(a) == 20


def test_clearance_skips_duplicate_trigger(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "docs/data"
    data_dir.mkdir(parents=True)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    latest = data_dir / "latest.json"
    tasks = data_dir / "engineering_tasks.json"
    write_json(tasks, {"tasks": []})
    write_json(
        latest,
        {
            "run_at": "2026-09-21T08:00:00+00:00",
            "post_run_review": {
                "improvement_plan": "1. [scoring] Wire FCF selector",
                "persistent_weaknesses": "FCF gaps",
            },
        },
    )
    (output_dir / "post_run_review.md").write_text(
        "PRIORITISED IMPROVEMENT PLAN\n1. [scoring] Wire FCF selector\n",
        encoding="utf-8",
    )
    log_path = data_dir / "post_run_clearance.json"

    monkeypatch.setattr(
        "value_investor.so_what_closure.apply_so_what_auto_queue",
        lambda **kwargs: {"created_tasks": []},
    )
    monkeypatch.setattr(
        "value_investor.compile_cap_drain.compile_next_compile_cap_drain_task",
        lambda **kwargs: {"compiled_count": 0, "reason": "none"},
    )

    first = run_post_run_clearance_cycle(
        apply=True,
        trigger=TRIGGER_POST_RUN_EMAIL,
        output_dir=output_dir,
        latest_path=latest,
        tasks_path=tasks,
        log_path=log_path,
    )
    assert first.get("skipped") is False
    assert first.get("applied") is True

    second = run_post_run_clearance_cycle(
        apply=True,
        trigger=TRIGGER_POST_RUN_EMAIL,
        output_dir=output_dir,
        latest_path=latest,
        tasks_path=tasks,
        log_path=log_path,
    )
    assert second.get("skipped") is True
    assert "already ran" in str(second.get("skip_reason") or "")


def test_clearance_dry_run_records_lane_c_when_plan_unlinked(tmp_path: Path):
    data_dir = tmp_path / "docs/data"
    data_dir.mkdir(parents=True)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    latest = data_dir / "latest.json"
    tasks = data_dir / "engineering_tasks.json"
    write_json(
        tasks,
        {
            "tasks": [
                {
                    "id": "eng-1",
                    "status": "merged",
                    "title": "Unrelated merged task",
                }
            ]
        },
    )
    write_json(
        latest,
        {
            "post_run_review": {
                "improvement_plan": "1. [scoring] Brand new plan line with no queue match",
                "persistent_weaknesses": "themes",
            },
        },
    )
    (output_dir / "post_run_review.md").write_text(
        "PRIORITISED IMPROVEMENT PLAN\n1. [scoring] Brand new plan line with no queue match\n",
        encoding="utf-8",
    )
    log_path = data_dir / "post_run_clearance.json"

    result = run_post_run_clearance_cycle(
        apply=False,
        trigger=TRIGGER_POST_RUN_EMAIL,
        output_dir=output_dir,
        latest_path=latest,
        tasks_path=tasks,
        log_path=log_path,
    )
    assert result.get("lane_c_recommended") is True
    assert result.get("plan_alignment", {}).get("unlinked_plan_titles")
