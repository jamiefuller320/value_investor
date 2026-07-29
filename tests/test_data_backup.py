"""Tests for tier-1 data backup snapshots."""

from __future__ import annotations

import json
from pathlib import Path

from value_investor.data_backup import (
    create_backup_snapshot,
    merge_email_chunks,
    restore_backup_snapshot,
    run_restore_drill,
    send_backup_snapshot_email,
    split_archive_for_email,
    verify_backup_snapshot,
)


def test_snapshot_verify_and_restore_roundtrip(tmp_path: Path):
    repo = tmp_path / "repo"
    library = repo / "docs/data/library/markets/test"
    library.mkdir(parents=True)
    (library / "manifest.json").write_text('{"market":"test"}', encoding="utf-8")
    history = repo / "docs/data/history"
    history.mkdir(parents=True)
    (history / "run_20260729.json.gz").write_bytes(b"{}")
    paper = repo / "docs/data/paper_automation"
    paper.mkdir(parents=True)
    (paper / "config.json").write_text("{}", encoding="utf-8")
    research = repo / "docs/data/research/ABC.L/sources"
    research.mkdir(parents=True)
    (research / "news_manifest.json").write_text("{}", encoding="utf-8")

    backup_dir = tmp_path / "backups"
    snapshot = create_backup_snapshot(repo_root=repo, backup_dir=backup_dir)
    assert snapshot.archive_path.exists()
    assert snapshot.manifest_path.exists()

    verify = verify_backup_snapshot(snapshot.archive_path)
    assert verify["ok"] is True

    target = tmp_path / "restore"
    target.mkdir()
    restore_backup_snapshot(snapshot.archive_path, repo_root=target)
    assert (target / "docs/data/library/markets/test/manifest.json").exists()
    assert (target / "docs/data/history/run_20260729.json.gz").exists()

    drill = run_restore_drill(repo_root=target, output_dir=target / "output")
    assert drill["ok"] is True
    assert drill["history_files_restored_to_output"] == 1


def test_snapshot_manifest_records_paths(tmp_path: Path):
    repo = tmp_path / "repo"
    path = repo / "docs/data/paper_automation"
    path.mkdir(parents=True)
    (path / "last_run.json").write_text("{}", encoding="utf-8")

    snapshot = create_backup_snapshot(repo_root=repo, backup_dir=tmp_path / "backups")
    manifest = json.loads(snapshot.manifest_path.read_text(encoding="utf-8"))
    assert "docs/data/paper_automation" in manifest["paths"]
    assert manifest["file_count"] >= 1


def test_split_and_merge_email_chunks(tmp_path: Path):
    archive = tmp_path / "sample.tar.gz"
    payload = b"x" * 25
    archive.write_bytes(payload)
    parts = split_archive_for_email(archive, chunk_bytes=10, output_dir=tmp_path / "parts")
    assert len(parts) == 3
    restored = tmp_path / "restored.tar.gz"
    merge_email_chunks(parts, restored)
    assert restored.read_bytes() == payload


def test_send_backup_email_uses_backup_to(monkeypatch, tmp_path: Path):
    repo = tmp_path / "repo"
    paper = repo / "docs/data/paper_automation"
    paper.mkdir(parents=True)
    (paper / "state.json").write_text("{}", encoding="utf-8")
    snapshot = create_backup_snapshot(repo_root=repo, backup_dir=tmp_path / "backups")

    sent: list[dict] = []

    def _fake_send_email(**kwargs):
        sent.append(kwargs)
        return None

    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("EMAIL_TO", "screen@example.com")
    monkeypatch.setattr("value_investor.emailer.send_email", _fake_send_email)

    result = send_backup_snapshot_email(snapshot)
    assert result["emailed"] is True
    assert result["email_to"] == "intellaigence101@gmail.com"
    assert result["parts"] >= 1
    assert sent
    assert all(msg["config"].email_to == "intellaigence101@gmail.com" for msg in sent)
