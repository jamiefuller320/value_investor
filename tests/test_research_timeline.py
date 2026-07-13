"""Tests for point-in-time research revision archive."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from value_investor.research.document import ResearchDocument
from value_investor.research.overlay import enrich_signals_with_research
from value_investor.research.store import ResearchStore
from value_investor.research.timeline import (
    archive_revision,
    get_research_as_of,
    list_revision_metas,
)


def _doc(
    *,
    updated_at: str,
    verdict: str,
    version: int = 1,
    mode: str = "initial",
) -> ResearchDocument:
    return ResearchDocument(
        ticker="AAA.L",
        name="Alpha PLC",
        signal="strong_buy",
        version=version,
        created_at="2026-06-01T07:00:00+00:00",
        updated_at=updated_at,
        mode=mode,
        executive_summary="Summary",
        research_verdict=verdict,
        research_risk_level="low",
        research_confidence=0.8,
        research_rationale=f"Verdict {verdict}",
    )


def test_archive_revision_writes_timeline_and_snapshot(tmp_path: Path):
    store = ResearchStore(tmp_path)
    doc = _doc(updated_at="2026-06-01T07:00:00+00:00", verdict="accumulate")
    revision_id = store.save(
        doc,
        run_at=datetime(2026, 6, 1, 7, 0, tzinfo=UTC),
        sources_as_of={"news_through": "2026-05-30T00:00:00+00:00"},
    )

    assert revision_id == "20260601T070000Z"
    assert store.timeline_path("AAA.L").exists()
    assert (store.ticker_dir("AAA.L") / "revisions" / f"{revision_id}.json.gz").exists()
    metas = list_revision_metas(store.ticker_dir("AAA.L"))
    assert len(metas) == 1
    assert metas[0].mode == "initial"


def test_get_research_as_of_returns_latest_revision_on_or_before_query(tmp_path: Path):
    ticker_dir = tmp_path / "research" / "AAA.L"
    ticker_dir.mkdir(parents=True)

    first = _doc(updated_at="2026-06-01T07:00:00+00:00", verdict="accumulate", version=1)
    second = _doc(
        updated_at="2026-06-08T07:00:00+00:00",
        verdict="caution",
        version=2,
        mode="weekly_update",
    )

    archive_revision(
        ticker_dir,
        doc=first,
        run_at=datetime(2026, 6, 1, 7, 0, tzinfo=UTC),
        sources_as_of={"financials_through": "2024"},
    )
    archive_revision(
        ticker_dir,
        doc=second,
        run_at=datetime(2026, 6, 8, 7, 0, tzinfo=UTC),
        sources_as_of={"financials_through": "2024"},
        delta={"weekly_update": "Risk rising", "verdict_changed": True},
    )

    early = get_research_as_of(tmp_path, "AAA.L", "2026-06-05T12:00:00+00:00")
    late = get_research_as_of(tmp_path, "AAA.L", "2026-06-10T12:00:00+00:00")
    too_early = get_research_as_of(tmp_path, "AAA.L", "2026-05-01T12:00:00+00:00")

    assert early is not None
    assert early.research_verdict == "accumulate"
    assert late is not None
    assert late.research_verdict == "caution"
    assert too_early is None


def test_enrich_signals_with_research_uses_point_in_time_verdict(tmp_path: Path):
    store = ResearchStore(tmp_path)
    store.save(
        _doc(updated_at="2026-06-01T07:00:00+00:00", verdict="accumulate"),
        run_at=datetime(2026, 6, 1, 7, 0, tzinfo=UTC),
    )
    store.save(
        _doc(
            updated_at="2026-06-08T07:00:00+00:00",
            verdict="pass",
            version=2,
            mode="weekly_update",
        ),
        run_at=datetime(2026, 6, 8, 7, 0, tzinfo=UTC),
        delta={"weekly_update": "Thesis broken", "verdict_changed": True, "prior_verdict": "accumulate"},
    )

    signals = pd.DataFrame([
        {"ticker": "AAA.L", "signal": "strong_buy"},
    ])

    early = enrich_signals_with_research(
        signals,
        tmp_path,
        run_at="2026-06-05T07:00:00+00:00",
    )
    late = enrich_signals_with_research(
        signals,
        tmp_path,
        run_at="2026-06-09T07:00:00+00:00",
    )

    assert early.iloc[0]["research_verdict"] == "accumulate"
    assert early.iloc[0]["adjusted_signal"] == "strong_buy"
    assert late.iloc[0]["research_verdict"] == "pass"
    assert late.iloc[0]["adjusted_signal"] == "hold"
    assert late.iloc[0]["research_as_of"] == "2026-06-08T07:00:00+00:00"

    from value_investor.storage import read_json

    revision = read_json(store.ticker_dir("AAA.L") / "revisions" / "20260608T070000Z.json")
    assert revision["delta"]["verdict_changed"] is True
