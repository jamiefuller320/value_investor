"""Tests for preflight checks."""

from pathlib import Path

from value_investor.preflight import run_preflight


def test_preflight_warns_without_history(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    report = run_preflight(tmp_path)
    assert report.ok
    names = {check.name for check in report.checks}
    assert "history" in names
    history = next(check for check in report.checks if check.name == "history")
    assert history.status == "warn"


def test_preflight_fails_when_email_required(tmp_path: Path, monkeypatch):
    for name in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO"):
        monkeypatch.delenv(name, raising=False)
    report = run_preflight(tmp_path, require_email=True)
    assert not report.ok
    smtp = next(check for check in report.checks if check.name == "smtp")
    assert smtp.status == "fail"
