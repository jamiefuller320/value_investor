"""Daily-hub GHA failure bundle: one open task per local_date."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from value_investor.daily_focus import build_daily_focus
from value_investor.gha_failure_triage import (
    TASK_REF,
    build_gha_failure_hub_items,
    load_gha_failure_triage,
    ops_findings_from_gha_failure_triage,
    record_gha_failure_triage,
)
from value_investor.storage import write_json
from value_investor.workflow_failure_tasks import (
    classify_workflow_failure,
    respond_to_workflow_failure,
)


def test_two_failure_types_append_one_open_bundle(tmp_path: Path) -> None:
    now = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
    record_gha_failure_triage(
        workflow_file="pages.yml",
        kind="unmatched:pages.yml",
        proposed_solution="Inspect Pages token / deploy logs; do not guess PATs.",
        run_url="https://example.test/pages",
        data_dir=tmp_path,
        now=now,
    )
    record_gha_failure_triage(
        workflow_file="gha-secret-hygiene.yml",
        kind="unmatched:gha-secret-hygiene.yml",
        proposed_solution="Fix hygiene scan finding; do not ticket every flake.",
        run_url="https://example.test/hygiene",
        data_dir=tmp_path,
        now=now,
    )
    # Same kind again must not duplicate.
    record_gha_failure_triage(
        workflow_file="pages.yml",
        kind="unmatched:pages.yml",
        proposed_solution="Inspect Pages token / deploy logs; do not guess PATs.",
        data_dir=tmp_path,
        now=now,
    )
    store = load_gha_failure_triage(tmp_path)
    failures = store["open"]["failures"]
    assert store["open"]["task_ref"] == TASK_REF
    assert store["open"]["local_date"] == "2026-10-04"
    assert [row["kind"] for row in failures] == [
        "unmatched:pages.yml",
        "unmatched:gha-secret-hygiene.yml",
    ]


def test_hub_emits_one_task_and_one_recommendation(tmp_path: Path) -> None:
    now = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
    record_gha_failure_triage(
        workflow_file="pages.yml",
        kind="unmatched:pages.yml",
        proposed_solution="Pages proposed fix A",
        data_dir=tmp_path,
        now=now,
    )
    record_gha_failure_triage(
        workflow_file="ci.yml",
        kind="unmatched:ci.yml",
        proposed_solution="CI proposed fix B",
        data_dir=tmp_path,
        now=now,
    )
    tasks, recs = build_gha_failure_hub_items(
        data_dir=tmp_path,
        closed_ids=set(),
        local_date="2026-10-04",
        generated_at="2026-10-04T12:00:00Z",
    )
    assert len(tasks) == 1
    assert len(recs) == 1
    assert tasks[0]["task_ref"] == TASK_REF
    assert recs[0]["task_id"] == TASK_REF
    assert "Pages proposed fix A" in recs[0]["rationale"]
    assert "CI proposed fix B" in recs[0]["rationale"]
    assert recs[0]["id"] == recs[0]["id"]


def test_ack_hides_bundle_for_local_date(tmp_path: Path) -> None:
    now = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
    record_gha_failure_triage(
        workflow_file="pages.yml",
        kind="unmatched:pages.yml",
        proposed_solution="fix",
        data_dir=tmp_path,
        now=now,
    )
    tasks, recs = build_gha_failure_hub_items(
        data_dir=tmp_path,
        closed_ids={TASK_REF},
        local_date="2026-10-04",
    )
    assert tasks == []
    assert recs == []


def test_next_local_date_starts_fresh_bundle(tmp_path: Path) -> None:
    record_gha_failure_triage(
        workflow_file="pages.yml",
        kind="unmatched:pages.yml",
        proposed_solution="day1",
        data_dir=tmp_path,
        now=datetime(2026, 10, 4, 12, 0, tzinfo=UTC),
    )
    record_gha_failure_triage(
        workflow_file="ci.yml",
        kind="unmatched:ci.yml",
        proposed_solution="day2",
        data_dir=tmp_path,
        now=datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
    )
    store = load_gha_failure_triage(tmp_path)
    assert store["open"]["local_date"] == "2026-10-05"
    assert [row["kind"] for row in store["open"]["failures"]] == ["unmatched:ci.yml"]


def test_ops_finding_warn_only(tmp_path: Path) -> None:
    record_gha_failure_triage(
        workflow_file="pages.yml",
        kind="unmatched:pages.yml",
        proposed_solution="fix",
        data_dir=tmp_path,
        now=datetime(2026, 10, 4, 12, 0, tzinfo=UTC),
    )
    rows = ops_findings_from_gha_failure_triage(
        data_dir=tmp_path,
        now=datetime(2026, 10, 4, 12, 0, tzinfo=UTC),
    )
    assert len(rows) == 1
    assert rows[0]["auto_fixable"] is False
    assert rows[0]["title"] == "GHA failure needs Daily-hub triage"


def test_daily_focus_collates_single_gha_card(tmp_path: Path) -> None:
    write_json(tmp_path / "human_tasks_board.json", {"tasks": []}, compact=False)
    write_json(tmp_path / "progress_report.json", {"actionable": {}}, compact=False)
    write_json(
        tmp_path / "ui_state_reconciliation.json",
        {"overall": "ok", "checks": []},
        compact=False,
    )
    now = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
    record_gha_failure_triage(
        workflow_file="pages.yml",
        kind="unmatched:pages.yml",
        proposed_solution="Pages fix",
        data_dir=tmp_path,
        now=now,
    )
    record_gha_failure_triage(
        workflow_file="ci.yml",
        kind="unmatched:ci.yml",
        proposed_solution="CI fix",
        data_dir=tmp_path,
        now=now,
    )
    payload = build_daily_focus(data_dir=tmp_path, now=now)
    gha = [t for t in payload["tasks"] if t.get("source") == "gha_failure_triage"]
    recs = [r for r in payload["recommendations"] if r.get("task_id") == TASK_REF]
    assert len(gha) == 1
    assert len(recs) == 1
    assert payload["counts"]["gha_failures"] == 1
    assert "Pages fix" in gha[0]["summary"]
    assert "CI fix" in gha[0]["summary"]


def test_dispatch_403_drafts_not_hub(tmp_path: Path) -> None:
    log = (
        "could not create workflow dispatch event: HTTP 403: "
        "Resource not accessible by integration\n"
        "##[error]Process completed with exit code 1."
    )
    classified = classify_workflow_failure("analysis-review.yml", log)
    assert classified["action"] == "draft"
    assert classified["kind"] == "dispatch_403"
    tasks_path = tmp_path / "engineering_tasks.json"
    write_json(tasks_path, {"tasks": []}, compact=False)
    result = respond_to_workflow_failure(
        workflow_file="analysis-review.yml",
        log_text=log,
        run_id=1,
        tasks_path=tasks_path,
        data_dir=tmp_path,
    )
    assert result["drafted"]
    assert result["hub_recorded"] is False
    assert not (tmp_path / "gha_failure_triage.json").exists()


def test_unmatched_failure_appends_hub_not_eng_task(tmp_path: Path) -> None:
    log = "##[error]Process completed with exit code 1.\nTraceback (most recent call last):"
    tasks_path = tmp_path / "engineering_tasks.json"
    write_json(tasks_path, {"tasks": []}, compact=False)
    respond_to_workflow_failure(
        workflow_file="pages.yml",
        log_text=log,
        run_id=2,
        tasks_path=tasks_path,
        data_dir=tmp_path,
    )
    respond_to_workflow_failure(
        workflow_file="gha-secret-hygiene.yml",
        log_text=log,
        run_id=3,
        tasks_path=tasks_path,
        data_dir=tmp_path,
    )
    payload = load_gha_failure_triage(tmp_path)
    kinds = [row["kind"] for row in payload["open"]["failures"]]
    assert kinds == ["unmatched:pages.yml", "unmatched:gha-secret-hygiene.yml"]
    eng = __import__("json").loads(tasks_path.read_text(encoding="utf-8"))
    assert eng.get("tasks") == []


def test_flake_ignored(tmp_path: Path) -> None:
    log = "The job was not acquired by Runner\n##[error]Process completed with exit code 1."
    result = respond_to_workflow_failure(
        workflow_file="automation-orchestrator.yml",
        log_text=log,
        tasks_path=tmp_path / "engineering_tasks.json",
        data_dir=tmp_path,
    )
    assert result["drafted"] == []
    assert result["hub_recorded"] is False
