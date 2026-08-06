"""Tests for paper-auto orchestration scheduling helpers."""

from pathlib import Path

from value_investor.paper_auto_scheduling import (
    last_run_after_settle,
    paper_auto_artifacts_satisfied,
)


def test_last_run_after_settle():
    assert last_run_after_settle({"gate": {"after_settle": True}}) is True
    assert last_run_after_settle({"gate": {"after_settle": False}}) is False
    assert last_run_after_settle({}) is False


def test_paper_auto_artifacts_satisfied_when_any_track_post_settle(tmp_path: Path):
    base = tmp_path / "paper_automation"
    (base / "momentum_grace").mkdir(parents=True)
    (base / "momentum_grace" / "last_run.json").write_text(
        '{"gate": {"after_settle": false}}',
        encoding="utf-8",
    )
    (base / "last_run.json").write_text(
        '{"gate": {"after_settle": true}}',
        encoding="utf-8",
    )
    assert paper_auto_artifacts_satisfied(base) is True


def test_paper_auto_artifacts_not_satisfied_pre_settle_only(tmp_path: Path):
    base = tmp_path / "paper_automation"
    base.mkdir()
    (base / "last_run.json").write_text(
        '{"gate": {"after_settle": false, "reason": "waiting for open settle"}}',
        encoding="utf-8",
    )
    (base / "ai_judgment").mkdir()
    (base / "ai_judgment" / "last_run.json").write_text(
        '{"gate": {"after_settle": false}}',
        encoding="utf-8",
    )
    assert paper_auto_artifacts_satisfied(base) is False


def test_paper_auto_artifacts_missing_files(tmp_path: Path):
    assert paper_auto_artifacts_satisfied(tmp_path / "missing") is False
