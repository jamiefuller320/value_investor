"""Tests for engineering queue / agent synchronisation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from value_investor.engineering_sync import (
    audit_compile_drop_risk,
    classify_ch_body_parse_quality,
    collect_ch_filing_body_parse_quality,
    enrich_gap_fill_ch_refetch_parse_quality,
    resolve_dispatch_task_id,
    run_engineering_sync,
)
from value_investor.engineering_tasks import (
    EngineeringTask,
    _merge_task_rows,
)


def _task(task_id: str, *, title: str = "Build CH PDF fetch") -> EngineeringTask:
    return EngineeringTask(
        id=task_id,
        area="ingest",
        title=title,
        summary=title,
        priority="high",
        priority_score=99.0,
        source="post_run_review",
    )


def test_open_task_ids_not_dropped_after_merge_guard():
    existing = [_task("eng-20260802-02", title="Old open task").to_dict()]
    compiled = [_task("eng-20260803-01", title="Brand new compiled task")]
    merged = _merge_task_rows(existing, compiled)
    ids = {row["id"] for row in merged if row.get("status") == "open"}
    assert "eng-20260802-02" in ids
    assert "eng-20260803-01" in ids


def test_resolve_dispatch_task_id_falls_back_when_stale(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    payload = {
        "tasks": [
            _task("eng-20260802-02", title="Stale task").to_dict(),
            _task("eng-20260803-29", title="Current top task").to_dict(),
        ]
    }
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")
    assert resolve_dispatch_task_id("eng-20260802-02", tasks_path=tasks_path) == "eng-20260802-02"
    payload["tasks"][0]["status"] = "merged"
    tasks_path.write_text(json.dumps(payload), encoding="utf-8")
    assert resolve_dispatch_task_id("eng-20260802-02", tasks_path=tasks_path) == "eng-20260803-29"


def test_audit_compile_drop_risk_empty_without_artifacts(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(
        json.dumps({"tasks": [_task("eng-20260802-02").to_dict()]}), encoding="utf-8"
    )
    assert audit_compile_drop_risk(tasks_path=tasks_path, output_dir=tmp_path / "output") == []


def test_run_engineering_sync_flags_recent_failures(tmp_path: Path):
    tasks_path = tmp_path / "engineering_tasks.json"
    tasks_path.write_text(
        json.dumps({"tasks": [_task("eng-20260803-29").to_dict()]}), encoding="utf-8"
    )
    report = run_engineering_sync(
        tasks_path=tasks_path,
        recent_agent_failures=[{"id": 1, "created_at": "2026-08-03T08:00:00Z"}],
        apply=False,
    )
    assert report.recent_agent_failures == 1
    assert report.should_redispatch is True


def test_classify_ch_body_parse_quality_ocr_vs_ixbrl():
    ocr_noise = (
        "Strategic report chairman statement revenue overview "
        + ("fontsymbol | OCR noise " * 60)
        + " free cash flow conversion 65%"
    )
    assert classify_ch_body_parse_quality(ocr_noise) == "ocr"

    ixbrl_like = (
        "Principal risks and uncertainties\n"
        "3.8 Pensions - Defined benefit pension surplus of GBP 198 million after "
        "GBP 65 million of employer contributions and remeasurement gains.\n"
        "Consolidated cash flow statement\n"
        "Borrowings and covenant compliance under the revolving credit facility."
    )
    assert classify_ch_body_parse_quality(ixbrl_like) == "ixbrl"


def test_enrich_gap_fill_ch_refetch_parse_quality_writes_source_map(tmp_path: Path):
    sources_dir = tmp_path / "sources"
    filings_dir = sources_dir / "filings"
    bodies_dir = filings_dir / "bodies"
    bodies_dir.mkdir(parents=True)
    row_id = "ch_test_parse_quality"
    ocr_body = "Strategic highlights " + ("fontsymbol garbled " * 40)
    (bodies_dir / f"{row_id}.txt").write_text(ocr_body, encoding="utf-8")
    index = {
        "summary": {"with_body": 1},
        "filings": [
            {
                "id": row_id,
                "source": "companies_house",
                "has_body": True,
                "body_path": str(bodies_dir / f"{row_id}.txt"),
            }
        ],
    }
    (filings_dir / "filings_index.json").write_text(json.dumps(index), encoding="utf-8")

    payload = {
        "ticker": "ITV.L",
        "ch_refetch": {"attempted": 1, "fetched": 1},
        "instructions": "Walk evidence_ladder in order.",
    }
    (sources_dir / "gap_fill_source_map.json").write_text(json.dumps(payload), encoding="utf-8")

    enriched = enrich_gap_fill_ch_refetch_parse_quality(sources_dir, payload)
    assert enriched["ch_refetch"]["body_parse_quality"][0]["parse_quality"] == "ocr"
    assert "body_parse_quality" in enriched["instructions"]

    saved = json.loads((sources_dir / "gap_fill_source_map.json").read_text(encoding="utf-8"))
    assert saved["ch_refetch"]["fetched"] == 1
    assert saved["ch_refetch"]["body_parse_quality"][0]["filing_id"] == row_id


@patch("value_investor.research.gap_fill_sources.fetch_alternate_gap_fill_news", return_value=[])
@patch("value_investor.research.gap_fill_sources.refetch_ir_allowlist_filing_bodies")
@patch("value_investor.research.gap_fill_sources.fetch_filings_ir_allowlist", return_value=[])
@patch("value_investor.research.gap_fill_sources.refetch_uk_primary_filing_bodies")
@patch("value_investor.research.gap_fill_sources.refetch_missing_filing_bodies")
def test_prepare_gap_fill_source_map_tags_ch_parse_quality_on_refetch(
    mock_refetch,
    mock_primary_refetch,
    mock_ir_rows,
    mock_ir_refetch,
    mock_news,
    tmp_path: Path,
):
    from value_investor.research.gap_fill_sources import prepare_gap_fill_source_pack

    filings_dir = tmp_path / "filings"
    bodies_dir = filings_dir / "bodies"
    bodies_dir.mkdir(parents=True)
    row_id = "ch_hook_tag"
    (bodies_dir / f"{row_id}.txt").write_text(
        "Principal risks and uncertainties\n3.8 Pensions defined benefit pension surplus.",
        encoding="utf-8",
    )
    (filings_dir / "filings_index.json").write_text(
        json.dumps(
            {
                "summary": {"with_body": 1},
                "filings": [
                    {
                        "id": row_id,
                        "source": "companies_house",
                        "has_body": True,
                        "body_path": str(bodies_dir / f"{row_id}.txt"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    mock_refetch.return_value = {"fetched": 0, "with_body_after": 0}
    mock_primary_refetch.return_value = {
        "fetched": 1,
        "companies_house": {"attempted": 1, "fetched": 1},
        "rns": {"fetched": 0, "investegate": {"fetched": 0}, "ticker_rns": {"fetched": 0}},
    }
    mock_ir_refetch.return_value = {"fetched": 0}

    pack = prepare_gap_fill_source_pack(
        ticker="ITV.L",
        company_name="ITV plc",
        sources_dir=tmp_path,
        open_questions=["pension risk"],
        market="ftse350",
    )

    assert pack["ch_refetch"]["body_parse_quality"][0]["parse_quality"] == "ixbrl"
    saved = json.loads((tmp_path / "gap_fill_source_map.json").read_text(encoding="utf-8"))
    assert saved["ch_refetch"]["body_parse_quality"][0]["filing_id"] == row_id


def test_collect_ch_filing_body_parse_quality_empty_without_index(tmp_path: Path):
    assert collect_ch_filing_body_parse_quality(tmp_path / "filings") == []
