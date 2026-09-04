"""Tests for the deterministic buy-tier memo-utility rollup (L140)."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.research.document import ResearchDocument
from value_investor.research.memo_utility_rollup import summarize_buy_tier_memo_utility


def _write_latest(path: Path, reports: list[dict]) -> None:
    path.write_text(json.dumps({"reports": reports}), encoding="utf-8")


def _write_memo(
    research_root: Path,
    *,
    ticker: str,
    grade: str,
    tags: list[str],
    questions: list[tuple[str, str]],
) -> None:
    ticker_dir = research_root / ticker
    ticker_dir.mkdir(parents=True)
    doc = ResearchDocument(
        ticker=ticker,
        name=ticker,
        signal="buy",
        version=1,
        created_at="2026-07-01T00:00:00+00:00",
        updated_at="2026-08-01T00:00:00+00:00",
        mode="initial",
        research_verdict="accumulate",
        risk_tags=tags,
        question_outcomes=[
            {"question": question, "status": status} for question, status in questions
        ],
        memo_quality={"grade": grade},
    )
    (ticker_dir / "research.json").write_text(
        json.dumps(doc.to_dict()),
        encoding="utf-8",
    )


def test_summarize_buy_tier_memo_utility_aggregates_grades_tags_questions(tmp_path: Path):
    latest = tmp_path / "latest.json"
    research = tmp_path / "research"
    _write_latest(
        latest,
        [
            {"ticker": "AAA.L", "signal": "strong_buy"},
            {"ticker": "BBB.L", "signal": "buy"},
            {"ticker": "CCC.L", "signal": "buy"},
            {"ticker": "DDD.L", "signal": "hold"},
        ],
    )
    _write_memo(
        research,
        ticker="AAA.L",
        grade="B",
        tags=["cyclical", "leverage"],
        questions=[("Pension deficit still open?", "unresolved")],
    )
    _write_memo(
        research,
        ticker="BBB.L",
        grade="C",
        tags=["cyclical"],
        questions=[("Pension deficit still open?", "partially_resolved")],
    )
    _write_memo(
        research,
        ticker="DDD.L",
        grade="A",
        tags=["governance"],
        questions=[("Should not appear — hold name", "unresolved")],
    )

    rollup = summarize_buy_tier_memo_utility(
        data_dir=tmp_path,
        latest_path=latest,
        research_root=research,
    )
    assert rollup["buy_tier_count"] == 3
    assert rollup["memo_count"] == 2
    assert rollup["grade_histogram"] == {"B": 1, "C": 1}
    assert rollup["coverage"]["with_memo_quality"] == 2
    assert rollup["coverage"]["with_risk_tags"] == 2
    assert rollup["top_risk_tags"][0] == {"tag": "cyclical", "count": 2}
    recurring = rollup["recurring_open_questions"]
    assert recurring
    assert recurring[0]["count"] == 2
    assert set(recurring[0]["tickers"]) == {"AAA.L", "BBB.L"}
    assert "DDD.L" not in {t for row in recurring for t in row["tickers"]}


def test_summarize_buy_tier_memo_utility_missing_latest(tmp_path: Path):
    rollup = summarize_buy_tier_memo_utility(data_dir=tmp_path)
    assert rollup["buy_tier_count"] == 0
    assert rollup["memo_count"] == 0
    assert rollup["grade_histogram"] == {}
