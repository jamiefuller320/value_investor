"""Tests for ingest trial recording and horizon review hooks."""

from __future__ import annotations

from pathlib import Path

from value_investor.ingest_trials import (
    finalize_pending_ingest_trial,
    list_trials_pending_review,
    load_ingest_trials,
    record_ingest_trial,
)


def test_record_and_finalize_ingest_trial(tmp_path: Path):
    path = tmp_path / "ingest_trials.json"
    trial = record_ingest_trial(
        title="Single-ticker depth trial",
        summary="Top priority_score name",
        ticker="MEGP.L",
        params={"max_targets": 1},
        path=path,
    )
    assert trial["id"].startswith("trial-")
    assert trial["status"] == "pending_review"

    finalized = finalize_pending_ingest_trial(
        health_before={
            "filings_with_body": 100,
            "indexed_without_body": 20,
            "zero_body_buy_tier": 0,
        },
        health_after={
            "filings_with_body": 105,
            "indexed_without_body": 15,
            "zero_body_buy_tier": 0,
        },
        ingest_summary=None,
        path=path,
    )
    assert finalized is not None
    assert finalized["outcome"]["delta_filings_with_body"] == 5
    pending = list_trials_pending_review(path=path)
    assert len(pending) == 1
    assert pending[0]["id"] == trial["id"]

    store = load_ingest_trials(path)
    assert store["trials"][0]["completed_at"] is not None


def test_list_trials_pending_review_filters_by_trigger(tmp_path: Path):
    path = tmp_path / "ingest_trials.json"
    for trigger in ("horizon_scan", "analysis_review", "both"):
        record_ingest_trial(
            title=f"Trial {trigger}",
            summary="",
            ticker="ABC.L",
            params={},
            review_trigger=trigger,
            path=path,
        )
        finalize_pending_ingest_trial(
            health_before={"filings_with_body": 1, "indexed_without_body": 1, "zero_body_buy_tier": 0},
            health_after={"filings_with_body": 1, "indexed_without_body": 1, "zero_body_buy_tier": 0},
            ingest_summary=None,
            path=path,
        )

    horizon = list_trials_pending_review(trigger="horizon_scan", path=path)
    analysis = list_trials_pending_review(trigger="analysis_review", path=path)
    assert len(horizon) == 2
    assert len(analysis) == 2
    assert {r["review_trigger"] for r in horizon} == {"horizon_scan", "both"}
    assert {r["review_trigger"] for r in analysis} == {"analysis_review", "both"}
