"""Tests for thin-filing deepen hook shared by memo ingest paths."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from value_investor.research.gap_fill_sources import (
    deepen_thin_filings_if_needed,
    inspect_local_sources,
)


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
@patch("value_investor.research.gap_fill_sources.refetch_uk_primary_filing_bodies")
@patch("value_investor.research.gap_fill_sources.refetch_missing_filing_bodies")
def test_prepare_gap_fill_calls_ch_refetch_for_uk(
    mock_refetch,
    mock_primary_refetch,
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
    mock_primary_refetch.return_value = {
        "fetched": 2,
        "with_body_after": 2,
        "companies_house": {"fetched": 2, "with_body_after": 2},
        "rns": {
            "fetched": 0,
            "investegate": {"fetched": 0, "with_body_after": 2},
            "ticker_rns": {"fetched": 0, "with_body_after": 2},
        },
    }

    pack = prepare_gap_fill_source_pack(
        ticker="BT-A.L",
        company_name="BT Group",
        sources_dir=tmp_path,
        open_questions=["pension deficit"],
        market="ftse350",
    )
    mock_primary_refetch.assert_called_once()
    assert pack["ch_refetch"]["fetched"] == 2
    assert pack["body_refetch"]["fetched"] == 2


def test_companies_house_catalog_mentions_consolidated_notes():
    from value_investor.research.gap_fill_sources import ALTERNATE_SOURCE_CATALOG

    ch = next(
        item for item in ALTERNATE_SOURCE_CATALOG["uk"] if item["id"] == "companies_house_accounts"
    )
    why = ch["why"].lower()
    assert "borrowings" in why
    assert "cash-flow" in why or "cash flow" in why
    assert "segment" in why


@patch("value_investor.research.gap_fill_sources.fetch_alternate_gap_fill_news", return_value=[])
@patch("value_investor.research.gap_fill_sources.refetch_ir_allowlist_filing_bodies")
@patch("value_investor.research.gap_fill_sources.fetch_filings_ir_allowlist", return_value=[])
@patch("value_investor.research.gap_fill_sources.refetch_uk_primary_filing_bodies")
@patch("value_investor.research.gap_fill_sources.refetch_missing_filing_bodies")
def test_prepare_gap_fill_calls_investegate_refetch_for_uk(
    mock_refetch,
    mock_primary_refetch,
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
    mock_primary_refetch.return_value = {
        "fetched": 3,
        "with_body_after": 3,
        "companies_house": {"fetched": 0, "with_body_after": 0},
        "rns": {
            "fetched": 3,
            "investegate": {"fetched": 3, "with_body_after": 3},
            "ticker_rns": {"fetched": 0, "with_body_after": 3},
        },
    }

    pack = prepare_gap_fill_source_pack(
        ticker="ITV.L",
        company_name="ITV plc",
        sources_dir=tmp_path,
        open_questions=["annual results"],
        market="ftse350",
    )
    mock_primary_refetch.assert_called_once()
    assert pack["investegate_refetch"]["fetched"] == 3
    assert pack["body_refetch"]["fetched"] == 3


@patch("value_investor.research.gap_fill_sources.execute_planned_alternate_sources")
@patch("value_investor.research.gap_fill_sources.prepare_gap_fill_source_pack")
def test_deepen_thin_filings_runs_when_thin(
    mock_prepare,
    mock_execute,
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


@patch("value_investor.research.gap_fill_sources.extract_ir_presentation_metrics")
@patch("value_investor.research.filings.prune_orphaned_filing_bodies")
@patch("value_investor.research.gap_fill_sources.refetch_ir_allowlist_filing_bodies")
@patch("value_investor.research.gap_fill_sources.merge_ir_allowlist_filings")
def test_execute_planned_company_ir_presentation_uses_ir_pipeline(
    mock_merge,
    mock_ir_refetch,
    mock_prune,
    mock_extract,
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
    mock_extract.return_value = {
        "bridge_count": 1,
        "segment_split_count": 1,
        "lease_maturity_count": 0,
        "mandatory": True,
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
    mock_extract.assert_called_once()
    assert result["sources_tried"] == ["company_ir_presentation"]
    assert result["fetched"] == 1
    assert result["body_refetch"]["fetched"] == 1


@patch("value_investor.research.filings.prune_orphaned_filing_bodies")
@patch("value_investor.research.filings.ingest_filings")
@patch("value_investor.research.filings.refetch_companies_house_filing_bodies")
def test_execute_planned_companies_house_uses_ch_refetch(
    mock_ch_refetch,
    mock_ingest,
    mock_prune,
    tmp_path: Path,
):
    from value_investor.research.gap_fill_sources import execute_planned_alternate_sources

    filings_dir = tmp_path / "filings"
    filings_dir.mkdir(parents=True)
    mock_ingest.return_value = {"filings_summary": {"with_body": 0}}
    mock_ch_refetch.return_value = {
        "attempted": 3,
        "fetched": 2,
        "with_body_before": 0,
        "with_body_after": 2,
    }

    result = execute_planned_alternate_sources(
        ticker="MER.L",
        company_name="Merchants Trust PLC",
        sources_dir=tmp_path,
        planned=[{"id": "companies_house_accounts", "score": "3"}],
        market="ftse350",
    )

    mock_ch_refetch.assert_called_once()
    assert result["sources_tried"] == ["companies_house_accounts"]
    assert result["fetched"] == 2
    assert result["body_refetch"]["fetched"] == 2


@patch("value_investor.research.gap_fill_sources.fetch_alternate_gap_fill_news", return_value=[])
@patch("value_investor.research.gap_fill_sources.refetch_ir_allowlist_filing_bodies")
@patch("value_investor.research.gap_fill_sources.fetch_filings_ir_allowlist")
@patch("value_investor.research.gap_fill_sources.refetch_uk_primary_filing_bodies")
@patch("value_investor.research.gap_fill_sources.refetch_missing_filing_bodies")
def test_prepare_gap_fill_calls_ir_refetch_for_allowlisted_ticker(
    mock_refetch,
    mock_primary_refetch,
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
    mock_primary_refetch.return_value = {
        "fetched": 0,
        "companies_house": {"fetched": 0},
        "rns": {"fetched": 0, "investegate": {"fetched": 0}, "ticker_rns": {"fetched": 0}},
    }
    mock_ir_rows.return_value = [
        {"id": "ir_test", "source": "ir_allowlist", "url": "https://x/y.pdf"}
    ]
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
    assert pack["ir_refetch"]["mandatory"] is True
    assert pack["body_refetch"]["fetched"] == 1


@patch("value_investor.research.gap_fill_sources.fetch_alternate_gap_fill_news", return_value=[])
@patch("value_investor.research.gap_fill_sources.refetch_ir_allowlist_filing_bodies")
@patch("value_investor.research.gap_fill_sources.fetch_filings_ir_allowlist")
@patch("value_investor.research.gap_fill_sources.refetch_uk_primary_filing_bodies")
@patch("value_investor.research.gap_fill_sources.refetch_missing_filing_bodies")
def test_prepare_gap_fill_source_map_includes_ir_retry_log(
    mock_refetch,
    mock_primary_refetch,
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
    mock_primary_refetch.return_value = {
        "fetched": 0,
        "companies_house": {"fetched": 0},
        "rns": {"fetched": 0, "investegate": {"fetched": 0}, "ticker_rns": {"fetched": 0}},
    }
    mock_ir_rows.return_value = [
        {"id": "ir_test", "source": "ir_allowlist", "url": "https://x/y.pdf"}
    ]
    mock_ir_refetch.return_value = {
        "fetched": 0,
        "attempted": 1,
        "retries_used": 2,
        "mandatory": True,
        "retry_log": [
            {"filing_id": "ir_test", "outcome": "retry", "attempt": 1},
            {"filing_id": "ir_test", "outcome": "failed", "attempt": 3},
        ],
    }

    pack = prepare_gap_fill_source_pack(
        ticker="MEGP.L",
        company_name="ME Group International plc",
        sources_dir=tmp_path,
        open_questions=["fcf bridge"],
        market="ftse350",
    )

    mock_ir_refetch.assert_called_once()
    assert pack["ir_refetch"]["mandatory"] is True
    assert pack["ir_refetch"]["retries_used"] == 2
    assert len(pack["ir_refetch"]["retry_log"]) == 2
    map_path = tmp_path / "gap_fill_source_map.json"
    assert map_path.exists()
    saved = json.loads(map_path.read_text(encoding="utf-8"))
    assert saved["ir_refetch"]["retry_log"][0]["outcome"] == "retry"


@patch("value_investor.research.gap_fill_sources.fetch_alternate_gap_fill_news", return_value=[])
@patch("value_investor.research.gap_fill_sources.refetch_ir_allowlist_filing_bodies")
@patch("value_investor.research.gap_fill_sources.fetch_filings_ir_allowlist")
@patch("value_investor.research.gap_fill_sources.refetch_uk_primary_filing_bodies")
@patch("value_investor.research.gap_fill_sources.refetch_missing_filing_bodies")
def test_prepare_gap_fill_calls_ir_refetch_for_itv_l(
    mock_refetch,
    mock_primary_refetch,
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
    mock_primary_refetch.return_value = {
        "fetched": 0,
        "companies_house": {"fetched": 0},
        "rns": {"fetched": 0, "investegate": {"fetched": 0}, "ticker_rns": {"fetched": 0}},
    }
    mock_ir_rows.return_value = [
        {
            "id": "ir_itv_fy25",
            "source": "ir_allowlist",
            "url": "https://www.itvplc.com/~/media/Files/I/ITV-PLC-V2/ITV%20Plc%202025%20FY%20Results%20Presentation.pdf",
        }
    ]
    mock_ir_refetch.return_value = {"fetched": 1, "with_body_after": 1}

    pack = prepare_gap_fill_source_pack(
        ticker="ITV.L",
        company_name="ITV plc",
        sources_dir=tmp_path,
        open_questions=["segment revenue and dividend cover"],
        market="ftse350",
    )

    mock_ir_refetch.assert_called_once()
    assert pack["ir_refetch"]["fetched"] == 1
    assert pack["body_refetch"]["fetched"] == 1


@patch("value_investor.research.gap_fill_sources.fetch_alternate_gap_fill_news", return_value=[])
@patch("value_investor.research.gap_fill_sources.refetch_ir_allowlist_filing_bodies")
@patch("value_investor.research.gap_fill_sources.fetch_filings_ir_allowlist", return_value=[])
@patch("value_investor.research.gap_fill_sources.refetch_uk_primary_filing_bodies")
@patch("value_investor.research.gap_fill_sources.refetch_missing_filing_bodies")
def test_prepare_gap_fill_attaches_screen_run_manifest(
    mock_refetch,
    mock_primary_refetch,
    mock_ir_rows,
    mock_ir_refetch,
    mock_news,
    tmp_path: Path,
    monkeypatch,
):
    from value_investor.research.gap_fill_sources import prepare_gap_fill_source_pack
    from value_investor.storage import write_json

    history_dir = tmp_path / "history"
    history_dir.mkdir()
    monkeypatch.setattr(
        "value_investor.research.gap_fill_sources.COMMITTED_HISTORY_DIR",
        history_dir,
    )
    run_at = "2026-08-16T06:19:37.808906+00:00"
    write_json(
        history_dir / "run_20260816_061937.json.gz",
        {
            "run_at": run_at,
            "prices": {"MEGP.L": 100.0},
            "signals": [
                {
                    "ticker": "MEGP.L",
                    "signal": "strong_buy",
                    "adjusted_signal": "buy",
                    "models_passed": 15.0,
                }
            ],
        },
        compress=True,
    )
    write_json(
        history_dir / "models_20260816_061937.json.gz",
        {
            "run_at": run_at,
            "models": [
                {"ticker": "MEGP.L", "model_id": "graham", "passed": True, "score": 0.8},
            ],
        },
        compress=True,
    )

    filings_dir = tmp_path / "sources" / "filings"
    filings_dir.mkdir(parents=True)
    (filings_dir / "filings_index.json").write_text(
        json.dumps({"summary": {"with_body": 0}, "filings": []}),
        encoding="utf-8",
    )
    mock_refetch.return_value = {"fetched": 0, "with_body_after": 0}
    mock_primary_refetch.return_value = {
        "fetched": 0,
        "companies_house": {},
        "rns": {"investegate": {}, "ticker_rns": {}},
    }
    mock_ir_refetch.return_value = {"fetched": 0, "with_body_after": 0}

    pack = prepare_gap_fill_source_pack(
        ticker="MEGP.L",
        company_name="ME Group International plc",
        sources_dir=tmp_path / "sources",
        open_questions=["fcf bridge"],
        market="ftse350",
    )

    manifest_path = tmp_path / "sources" / "screen_run_manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["ticker_signal"]["signal"] == "strong_buy"
    assert manifest["models_passed"] == 1
    assert pack["screen_run_manifest"]["attached"] is True


def test_inspect_local_sources_flags_empty_quarterly_cashflow(tmp_path: Path):
    sources = tmp_path / "sources"
    sources.mkdir(parents=True)
    (sources / "financials_annual.json").write_text(
        json.dumps(
            {
                "ticker": "HIK.L",
                "cash_flow": {"2025": {"Operating Cash Flow": 436_000_000.0}},
                "quarterly_cashflow": {},
                "cashflow_metrics": {
                    "operating_cashflow": 436_000_000.0,
                    "ttm_cashflow_suppressed": True,
                    "ttm_cashflow_suppressed_reason": "quarterly_cashflow_empty",
                },
            }
        ),
        encoding="utf-8",
    )

    inventory = inspect_local_sources(sources)
    assert inventory["available"]["yahoo_financials"] is True
    assert inventory["available"]["yahoo_quarterly_cashflow"] is False
    assert "yahoo_quarterly_cashflow" in inventory["thin"]


def test_inspect_local_sources_flags_empty_quarterly_income(tmp_path: Path):
    sources = tmp_path / "sources"
    sources.mkdir(parents=True)
    (sources / "financials_annual.json").write_text(
        json.dumps(
            {
                "ticker": "MEGP.L",
                "income_statement": {"2025": {"Total Revenue": 315_400_000.0}},
                "quarterly_income": {},
            }
        ),
        encoding="utf-8",
    )

    inventory = inspect_local_sources(sources)
    assert inventory["available"]["yahoo_quarterly_income"] is False
    assert "yahoo_quarterly_income" in inventory["thin"]


@patch("value_investor.research.gap_fill_sources.fetch_alternate_gap_fill_news", return_value=[])
@patch("value_investor.research.gap_fill_sources.refetch_ir_allowlist_filing_bodies")
@patch("value_investor.research.gap_fill_sources.fetch_filings_ir_allowlist")
@patch("value_investor.research.gap_fill_sources.refetch_uk_primary_filing_bodies")
@patch("value_investor.research.gap_fill_sources.refetch_missing_filing_bodies")
def test_prepare_gap_fill_calls_ir_refetch_for_euro_depth_shell_as(
    mock_refetch,
    mock_primary_refetch,
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
    mock_primary_refetch.return_value = {
        "fetched": 0,
        "companies_house": {"fetched": 0},
        "rns": {"fetched": 0, "investegate": {"fetched": 0}, "ticker_rns": {"fetched": 0}},
    }
    mock_ir_rows.return_value = [
        {
            "id": "ir_shell",
            "source": "ir_allowlist",
            "url": "https://www.sec.gov/Archives/edgar/data/1306965/000162828026017024/shel-20251231.htm",
        }
    ]
    mock_ir_refetch.return_value = {"fetched": 1, "with_body_after": 1}

    pack = prepare_gap_fill_source_pack(
        ticker="SHELL.AS",
        company_name="Shell plc",
        sources_dir=tmp_path,
        open_questions=["annual report bodies"],
        market="euro_depth",
    )

    mock_ir_refetch.assert_called_once()
    assert pack["ir_refetch"]["fetched"] == 1
    assert pack["body_refetch"]["fetched"] == 1
