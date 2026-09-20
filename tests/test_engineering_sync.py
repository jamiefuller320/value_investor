"""Tests for engineering queue / agent synchronisation."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.engineering_sync import (
    audit_compile_drop_risk,
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


def test_is_ch_administrative_filing_detects_confirmation_statement():
    from value_investor.engineering_queue import is_ch_administrative_filing

    assert is_ch_administrative_filing(
        {
            "source": "companies_house",
            "headline": "Confirmation statement made on 12 June 2026",
            "category": "confirmation-statement",
        }
    )


def test_ch_refetch_hooks_deprioritize_parent_only_for_period_coverage():
    from value_investor.engineering_queue import install_ch_refetch_scoring_hooks
    from value_investor.research.filings import period_body_coverage, summarize_filings

    install_ch_refetch_scoring_hooks(force=True)
    filings = [
        {
            "source": "companies_house",
            "period": "interim",
            "entity_type": "other",
            "headline": "Companies House accounts — accounts-with-accounts-type-small",
            "summary": "accounts-with-accounts-type-small",
            "has_body": True,
        },
        {
            "source": "companies_house",
            "period": "interim",
            "entity_type": "consolidated",
            "headline": "Companies House accounts — accounts-with-accounts-type-group",
            "summary": "accounts-with-accounts-type-group",
            "has_body": False,
        },
    ]
    coverage = period_body_coverage(filings)
    assert coverage["interim"]["with_body"] == 0
    summary = summarize_filings(filings)
    assert summary["period_coverage"]["interim"]["with_body"] == 0


def test_ch_refetch_hooks_prefers_group_over_parent_sme(tmp_path: Path, monkeypatch):
    from value_investor.engineering_queue import install_ch_refetch_scoring_hooks

    install_ch_refetch_scoring_hooks(force=True)
    from value_investor.research.filings import refetch_companies_house_filing_bodies

    filings_dir = tmp_path / "filings"
    filings_dir.mkdir()
    ch_url = "https://document-api.company-information.service.gov.uk/document/ch"
    rows = [
        {
            "id": "ch_small",
            "source": "companies_house",
            "headline": "Companies House accounts — accounts-with-accounts-type-small",
            "summary": "accounts-with-accounts-type-small",
            "url": f"{ch_url}-small",
            "document_metadata_url": f"{ch_url}-small",
            "published_at": "2025-06-01T00:00:00+00:00",
            "has_body": False,
            "priority": 140,
        },
        {
            "id": "ch_group",
            "source": "companies_house",
            "headline": "Companies House accounts — accounts-with-accounts-type-group",
            "summary": "accounts-with-accounts-type-group",
            "url": f"{ch_url}-group",
            "document_metadata_url": f"{ch_url}-group",
            "published_at": "2025-06-15T00:00:00+00:00",
            "has_body": False,
            "priority": 140,
        },
    ]
    filings_dir.joinpath("filings_index.json").write_text(
        json.dumps({"ticker": "MEGP.L", "filings": rows, "summary": {"total": 2, "with_body": 0}}),
        encoding="utf-8",
    )
    fetched_ids: list[str] = []

    def _fake_fetch(row: dict) -> str:
        fetched_ids.append(str(row.get("id") or ""))
        return "A" * 220 + " consolidated income pension covenant going concern"

    monkeypatch.setattr(
        "value_investor.research.filings._fetch_companies_house_body",
        _fake_fetch,
    )
    result = refetch_companies_house_filing_bodies(filings_dir, max_bodies=1)
    assert result["fetched"] == 1
    assert fetched_ids == ["ch_group"]


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
