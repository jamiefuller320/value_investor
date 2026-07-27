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


@patch("value_investor.research.gap_fill_sources.fetch_alternate_gap_fill_news", return_value=[])
@patch("value_investor.research.gap_fill_sources.refetch_ir_allowlist_filing_bodies")
@patch("value_investor.research.gap_fill_sources.fetch_filings_ir_allowlist", return_value=[])
@patch("value_investor.research.gap_fill_sources.refetch_investegate_filing_bodies")
@patch("value_investor.research.gap_fill_sources.refetch_companies_house_filing_bodies")
@patch("value_investor.research.gap_fill_sources.refetch_missing_filing_bodies")
def test_prepare_gap_fill_calls_ch_refetch_for_uk(
    mock_refetch,
    mock_ch_refetch,
    mock_investegate_refetch,
    mock_ir_rows,
    mock_ir_refetch,
    mock_news,
    tmp_path: Path,
):
    from value_investor.research.gap_fill_sources import prepare_gap_fill_source_pack

    filings_dir = tmp_path / "filings"
    filings_dir.mkdir(parents=True)
    (filings_dir / "filings_index.json").write_text(
        json.dumps({"summary": {"with_body": 0}, "filings": []}),
        encoding="utf-8",
    )
    mock_refetch.return_value = {"fetched": 0, "with_body_after": 0}
    mock_ch_refetch.return_value = {"fetched": 2, "with_body_after": 2}
    mock_investegate_refetch.return_value = {"fetched": 0, "with_body_after": 2}

    pack = prepare_gap_fill_source_pack(
        ticker="BT-A.L",
        company_name="BT Group",
        sources_dir=tmp_path,
        open_questions=["pension deficit"],
        market="ftse350",
    )
    mock_ch_refetch.assert_called_once()
    mock_investegate_refetch.assert_called_once()
    assert pack["ch_refetch"]["fetched"] == 2
    assert pack["body_refetch"]["fetched"] == 2


@patch("value_investor.research.gap_fill_sources.fetch_alternate_gap_fill_news", return_value=[])
@patch("value_investor.research.gap_fill_sources.refetch_ir_allowlist_filing_bodies")
@patch("value_investor.research.gap_fill_sources.fetch_filings_ir_allowlist", return_value=[])
@patch("value_investor.research.gap_fill_sources.refetch_investegate_filing_bodies")
@patch("value_investor.research.gap_fill_sources.refetch_companies_house_filing_bodies")
@patch("value_investor.research.gap_fill_sources.refetch_missing_filing_bodies")
def test_prepare_gap_fill_calls_investegate_refetch_for_uk(
    mock_refetch,
    mock_ch_refetch,
    mock_investegate_refetch,
    mock_ir_rows,
    mock_ir_refetch,
    mock_news,
    tmp_path: Path,
):
    from value_investor.research.gap_fill_sources import prepare_gap_fill_source_pack

    filings_dir = tmp_path / "filings"
    filings_dir.mkdir(parents=True)
    (filings_dir / "filings_index.json").write_text(
        json.dumps({"summary": {"with_body": 0}, "filings": []}),
        encoding="utf-8",
    )
    mock_refetch.return_value = {"fetched": 0, "with_body_after": 0}
    mock_ch_refetch.return_value = {"fetched": 0, "with_body_after": 0}
    mock_investegate_refetch.return_value = {"fetched": 3, "with_body_after": 3}

    pack = prepare_gap_fill_source_pack(
        ticker="ITV.L",
        company_name="ITV plc",
        sources_dir=tmp_path,
        open_questions=["annual results"],
        market="ftse350",
    )
    mock_investegate_refetch.assert_called_once()
    assert pack["investegate_refetch"]["fetched"] == 3
    assert pack["body_refetch"]["fetched"] == 3


@patch("value_investor.research.gap_fill_sources.refetch_ir_allowlist_filing_bodies")
@patch("value_investor.research.gap_fill_sources.fetch_filings_ir_allowlist", return_value=[])
@patch("value_investor.research.gap_fill_sources.refetch_companies_house_filing_bodies")
@patch("value_investor.research.gap_fill_sources.refetch_missing_filing_bodies")
@patch("value_investor.research.gap_fill_sources.execute_planned_alternate_sources")
@patch("value_investor.research.gap_fill_sources.prepare_gap_fill_source_pack")
def test_deepen_thin_filings_runs_when_thin(
    mock_prepare,
    mock_execute,
    mock_refetch,
    mock_ch_refetch,
    mock_ir_rows,
    mock_ir_refetch,
    tmp_path: Path,
):
    filings_dir = tmp_path / "filings"
    filings_dir.mkdir(parents=True)
    (filings_dir / "filings_index.json").write_text(
        json.dumps({"summary": {"with_body": 0}, "sources_used": []}),
        encoding="utf-8",
    )
    mock_prepare.return_value = {"planned_alternate_sources": [{"id": "exchange_filings_full"}]}
    mock_execute.return_value = {"sources_tried": ["exchange_filings_full"], "fetched": 2}
    mock_refetch.return_value = {"fetched": 0, "with_body_after": 0}
    mock_ch_refetch.return_value = {"fetched": 0, "with_body_after": 0}

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


@patch("value_investor.research.filings.prune_orphaned_filing_bodies")
@patch("value_investor.research.gap_fill_sources.refetch_ir_allowlist_filing_bodies")
@patch("value_investor.research.gap_fill_sources.merge_ir_allowlist_filings")
def test_execute_planned_company_ir_presentation_uses_ir_pipeline(
    mock_merge,
    mock_ir_refetch,
    mock_prune,
    tmp_path: Path,
):
    from value_investor.research.gap_fill_sources import execute_planned_alternate_sources

    mock_merge.return_value = {"added": 1}
    mock_ir_refetch.return_value = {
        "attempted": 2,
        "fetched": 1,
        "with_body_before": 0,
        "with_body_after": 1,
    }

    result = execute_planned_alternate_sources(
        ticker="HIK.L",
        company_name="Hikma Pharmaceuticals PLC",
        sources_dir=tmp_path,
        planned=[{"id": "company_ir_presentation", "score": "2"}],
        market="ftse350",
    )

    mock_merge.assert_called_once()
    mock_ir_refetch.assert_called_once()
    mock_prune.assert_called_once()
    assert result["sources_tried"] == ["company_ir_presentation"]
    assert result["fetched"] == 1
    assert result["body_refetch"]["fetched"] == 1


@patch("value_investor.research.gap_fill_sources.fetch_alternate_gap_fill_news", return_value=[])
@patch("value_investor.research.gap_fill_sources.refetch_ir_allowlist_filing_bodies")
@patch("value_investor.research.gap_fill_sources.fetch_filings_ir_allowlist")
@patch("value_investor.research.gap_fill_sources.refetch_investegate_filing_bodies")
@patch("value_investor.research.gap_fill_sources.refetch_companies_house_filing_bodies")
@patch("value_investor.research.gap_fill_sources.refetch_missing_filing_bodies")
def test_prepare_gap_fill_calls_ir_refetch_for_allowlisted_ticker(
    mock_refetch,
    mock_ch_refetch,
    mock_investegate_refetch,
    mock_ir_rows,
    mock_ir_refetch,
    mock_news,
    tmp_path: Path,
):
    from value_investor.research.gap_fill_sources import prepare_gap_fill_source_pack

    filings_dir = tmp_path / "filings"
    filings_dir.mkdir(parents=True)
    (filings_dir / "filings_index.json").write_text(
        json.dumps({"summary": {"with_body": 0}, "filings": []}),
        encoding="utf-8",
    )
    mock_refetch.return_value = {"fetched": 0, "with_body_after": 0}
    mock_ch_refetch.return_value = {"fetched": 0, "with_body_after": 0}
    mock_investegate_refetch.return_value = {"fetched": 0, "with_body_after": 0}
    mock_ir_rows.return_value = [{"id": "ir_test", "source": "ir_allowlist", "url": "https://x/y.pdf"}]
    mock_ir_refetch.return_value = {"fetched": 1, "with_body_after": 1}

    pack = prepare_gap_fill_source_pack(
        ticker="HIK.L",
        company_name="Hikma Pharmaceuticals PLC",
        sources_dir=tmp_path,
        open_questions=["fcf bridge"],
        market="ftse350",
    )

    mock_ir_refetch.assert_called_once()
    assert pack["ir_refetch"]["fetched"] == 1
    assert pack["body_refetch"]["fetched"] == 1
