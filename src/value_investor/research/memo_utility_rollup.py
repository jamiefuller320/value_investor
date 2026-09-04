"""Deterministic buy-tier memo-utility aggregate for horizon stage signals (L140).

Observe-only. Does not own weekly gap-fill or post_run_review (N28).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from value_investor.research.document import ResearchDocument, unresolved_questions
from value_investor.storage import read_json
from value_investor.system_gap_analysis import BUY_TIER_SIGNALS

DEFAULT_DATA_DIR = Path("docs/data")
DEFAULT_TOP_N = 8


def _normalize_question(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def summarize_buy_tier_memo_utility(
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    latest_path: Path | None = None,
    research_root: Path | None = None,
    top_n: int = DEFAULT_TOP_N,
) -> dict[str, Any]:
    """Aggregate grade / risk_tags / open questions across live buy-tier memos."""
    data_dir = Path(data_dir)
    latest_file = Path(latest_path) if latest_path is not None else data_dir / "latest.json"
    research_dir = Path(research_root) if research_root is not None else data_dir / "research"

    buy_tier: list[str] = []
    try:
        latest = read_json(latest_file)
    except (OSError, ValueError, TypeError, FileNotFoundError):
        latest = {}
    reports = latest.get("reports") if isinstance(latest, dict) else None
    if isinstance(reports, list):
        for row in reports:
            if not isinstance(row, dict):
                continue
            signal = str(row.get("signal") or "").strip()
            ticker = str(row.get("ticker") or "").strip()
            if ticker and signal in BUY_TIER_SIGNALS:
                buy_tier.append(ticker)

    grade_counts: Counter[str] = Counter()
    tag_counts: Counter[str] = Counter()
    question_tickers: dict[str, list[str]] = {}
    question_display: dict[str, str] = {}
    with_memo = 0
    with_quality = 0
    with_tags = 0
    with_questions = 0

    for ticker in buy_tier:
        path = research_dir / ticker / "research.json"
        if not path.exists():
            continue
        try:
            raw = read_json(path)
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(raw, dict):
            continue
        try:
            doc = ResearchDocument.from_dict(raw)
        except (KeyError, TypeError, ValueError):
            continue
        with_memo += 1
        quality = doc.memo_quality if isinstance(doc.memo_quality, dict) else {}
        grade = str(quality.get("grade") or "").strip()
        if quality:
            with_quality += 1
        if grade:
            grade_counts[grade] += 1
        tags = [str(tag).strip() for tag in (doc.risk_tags or []) if str(tag).strip()]
        if tags:
            with_tags += 1
            tag_counts.update(tags)
        open_qs = unresolved_questions(doc.question_outcomes)
        if open_qs:
            with_questions += 1
        for question in open_qs:
            key = _normalize_question(question)
            if not key:
                continue
            question_display.setdefault(key, question)
            bucket = question_tickers.setdefault(key, [])
            if ticker not in bucket:
                bucket.append(ticker)

    recurring = [
        {
            "question": question_display[key],
            "count": len(tickers),
            "tickers": tickers,
        }
        for key, tickers in question_tickers.items()
        if len(tickers) >= 2
    ]
    recurring.sort(key=lambda row: (-int(row["count"]), str(row["question"])))
    if not recurring:
        singles = [
            {
                "question": question_display[key],
                "count": len(tickers),
                "tickers": tickers,
            }
            for key, tickers in question_tickers.items()
        ]
        singles.sort(key=lambda row: (-int(row["count"]), str(row["question"])))
        recurring = singles[:top_n]
    else:
        recurring = recurring[:top_n]

    top_tags = [
        {"tag": tag, "count": count}
        for tag, count in tag_counts.most_common(top_n)
    ]

    return {
        "buy_tier_count": len(buy_tier),
        "memo_count": with_memo,
        "coverage": {
            "with_memo_quality": with_quality,
            "with_risk_tags": with_tags,
            "with_question_outcomes": with_questions,
        },
        "grade_histogram": dict(sorted(grade_counts.items())),
        "top_risk_tags": top_tags,
        "recurring_open_questions": recurring,
    }
