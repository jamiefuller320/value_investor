"""Tests for ingest backlog resume after runtime cutoff."""

from __future__ import annotations

from pathlib import Path

from value_investor.ingest_backlog import (
    backlog_tickers,
    load_ingest_backlog,
    prioritize_backlog_targets,
    record_ingest_backlog_after_pass,
)
from value_investor.research.ingest_improvement import IngestImprovementTarget


def _target(ticker: str, score: float) -> IngestImprovementTarget:
    return IngestImprovementTarget(
        ticker=ticker,
        name=ticker,
        signal="buy",
        priority_score=score,
    )


def test_prioritize_backlog_targets_prepends_pending_tickers():
    candidates = [_target("AAA.L", 10), _target("BBB.L", 20), _target("CCC.L", 5)]
    ordered = prioritize_backlog_targets(candidates, ["CCC.L", "AAA.L"])
    assert [row.ticker for row in ordered] == ["CCC.L", "AAA.L", "BBB.L"]


def test_record_backlog_on_cutoff_and_clear_on_complete(tmp_path: Path):
    backlog_path = tmp_path / "ingest_backlog.json"
    targets = [_target("AAA.L", 1), _target("BBB.L", 2)]
    payload = record_ingest_backlog_after_pass(
        targets=targets,
        completed_tickers=["AAA.L"],
        runtime_cutoff=True,
        path=backlog_path,
    )
    assert payload["remaining_tickers"] == ["BBB.L"]
    assert backlog_tickers(load_ingest_backlog(backlog_path)) == ["BBB.L"]

    record_ingest_backlog_after_pass(
        targets=targets,
        completed_tickers=["AAA.L", "BBB.L"],
        runtime_cutoff=False,
        path=backlog_path,
    )
    assert not backlog_path.exists()


def test_load_ingest_backlog_tolerates_corrupt_file(tmp_path: Path):
    path = tmp_path / "ingest_backlog.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_ingest_backlog(path) == {}
