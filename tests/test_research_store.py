"""Tests for research store persistence."""

import json
from pathlib import Path

from value_investor.research.document import ResearchDocument
from value_investor.research.store import ResearchStore
from value_investor.research.timeline import list_revision_metas


def test_research_store_round_trip(tmp_path: Path):
    store = ResearchStore(tmp_path)
    doc = ResearchDocument(
        ticker="AAA.L",
        name="Alpha PLC",
        signal="strong_buy",
        version=1,
        created_at="2026-07-01T00:00:00+00:00",
        updated_at="2026-07-01T00:00:00+00:00",
        mode="initial",
        executive_summary="Summary",
        agent_id="agent-123",
    )
    store.save(doc)

    loaded = store.load("AAA.L")
    assert loaded is not None
    assert loaded.executive_summary == "Summary"
    assert loaded.agent_id == "agent-123"
    assert store.markdown_path("AAA.L").exists()
    assert json.loads(store.metadata_path("AAA.L").read_text(encoding="utf-8"))["version"] == 1
    assert store.timeline_path("AAA.L").exists()
    assert list_revision_metas(store.ticker_dir("AAA.L"))
