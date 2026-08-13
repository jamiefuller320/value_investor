"""Tests for director baseline promotion onto live memos."""

from __future__ import annotations

from pathlib import Path

import pytest

from value_investor.research.director_promotion import promote_director_baseline_to_store
from value_investor.research.document import ResearchDocument
from value_investor.research.store import ResearchStore


def test_promote_director_baseline_merges_onto_live_doc(tmp_path: Path):
    store = ResearchStore(tmp_path)
    live = ResearchDocument(
        ticker="VTY.L",
        name="Vistry Group PLC",
        signal="strong_buy",
        version=1,
        created_at="2026-08-13T00:00:00+00:00",
        updated_at="2026-08-13T00:00:00+00:00",
        mode="initial",
        executive_summary="Composer memo.",
        research_verdict="accumulate",
        research_confidence=0.65,
    )
    store.save(live)

    director_doc = ResearchDocument(
        ticker="VTY.L",
        name="Vistry Group PLC",
        signal="strong_buy",
        version=1,
        created_at="2026-08-13T12:00:00+00:00",
        updated_at="2026-08-13T12:00:00+00:00",
        mode="director_worker",
        executive_summary="Director memo.",
        research_verdict="caution",
        research_confidence=0.42,
        director_baseline={
            "schema_version": 1,
            "run_id": "20260813T120000Z",
            "open_questions": ["Is dividend cover sustainable?"],
            "research_verdict": "caution",
        },
    )

    promoted = promote_director_baseline_to_store(
        store=store,
        director_doc=director_doc,
        run_id="20260813T120000Z",
        trial_output_dir="docs/data/research_director_worker/VTY.L/run",
    )

    assert promoted.executive_summary == "Composer memo."
    assert promoted.research_verdict == "accumulate"
    assert promoted.director_baseline["trial_run_id"] == "20260813T120000Z"
    assert promoted.director_baseline["open_questions"] == ["Is dividend cover sustainable?"]
    assert promoted.director_baseline["promoted_at"]

    reloaded = store.load("VTY.L")
    assert reloaded is not None
    assert reloaded.director_baseline["trial_run_id"] == "20260813T120000Z"


def test_promote_requires_live_memo(tmp_path: Path):
    store = ResearchStore(tmp_path)
    director_doc = ResearchDocument(
        ticker="VTY.L",
        name="Vistry Group PLC",
        signal="strong_buy",
        version=1,
        created_at="2026-08-13T12:00:00+00:00",
        updated_at="2026-08-13T12:00:00+00:00",
        mode="director_worker",
        director_baseline={"open_questions": ["Q1"]},
    )
    with pytest.raises(ValueError, match="No live research memo"):
        promote_director_baseline_to_store(
            store=store,
            director_doc=director_doc,
            run_id="run-1",
            trial_output_dir="out",
        )
