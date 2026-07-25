"""Tests for thin-filing deepen hook shared by memo ingest paths."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from value_investor.research.gap_fill_sources import deepen_thin_filings_if_needed


def test_deepen_thin_filings_skips_when_sufficient(tmp_path: Path):
    result = deepen_thin_filings_if_needed(
        ticker="TEST",
        company_name="Test Co",
        sources_dir=tmp_path,
        market="sp500",
        filings_summary={"with_body": 5},
    )
    assert result["skipped"] is True
    assert result["reason"] == "sufficient_bodies"


@patch("value_investor.research.gap_fill_sources.execute_planned_alternate_sources")
@patch("value_investor.research.gap_fill_sources.prepare_gap_fill_source_pack")
def test_deepen_thin_filings_runs_when_thin(mock_prepare, mock_execute, tmp_path: Path):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir(parents=True)
    (filings_dir / "filings_index.json").write_text(
        json.dumps({"summary": {"with_body": 0}, "sources_used": []}),
        encoding="utf-8",
    )
    mock_prepare.return_value = {"planned_alternate_sources": [{"id": "exchange_filings_full"}]}
    mock_execute.return_value = {"sources_tried": ["exchange_filings_full"], "fetched": 2}

    # Simulate bodies added after execute
    (filings_dir / "filings_index.json").write_text(
        json.dumps({"summary": {"with_body": 2}, "sources_used": ["asx_direct"]}),
        encoding="utf-8",
    )

    result = deepen_thin_filings_if_needed(
        ticker="WOR.AX",
        company_name="Worley Limited",
        sources_dir=tmp_path,
        market="asx200",
        filings_summary={"with_body": 0},
    )
    assert result["skipped"] is False
    assert result["improved"] is True
    mock_prepare.assert_called_once()
    mock_execute.assert_called_once()
