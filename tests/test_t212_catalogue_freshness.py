"""Tests for Trading 212 catalogue freshness (L665 ops-monitor)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from value_investor.storage import write_json
from value_investor.t212_coverage import (
    META_NAME,
    T212_CATALOGUE_FRESH_TITLE,
    T212_CATALOGUE_STALE_DAYS,
    T212_CATALOGUE_STALE_TITLE,
    assess_t212_catalogue_freshness,
    catalogue_dir,
    ops_findings_from_t212_catalogue_freshness,
)


def _write_meta(root: Path, fetched_at: str) -> None:
    cat = catalogue_dir(root)
    cat.mkdir(parents=True, exist_ok=True)
    write_json(
        cat / META_NAME,
        {
            "schema_version": 1,
            "fetched_at": fetched_at,
            "env": "live",
            "instrument_count": 100,
        },
        compact=False,
    )


def test_assess_fresh_catalogue(tmp_path: Path) -> None:
    now = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    fetched = (now - timedelta(days=3)).isoformat()
    _write_meta(tmp_path, fetched)
    assessment = assess_t212_catalogue_freshness(tmp_path, now=now)
    assert assessment["status"] == "fresh"
    assert assessment["age_days"] == 3.0


def test_assess_stale_catalogue(tmp_path: Path) -> None:
    now = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    fetched = (now - timedelta(days=T212_CATALOGUE_STALE_DAYS + 1)).isoformat()
    _write_meta(tmp_path, fetched)
    assessment = assess_t212_catalogue_freshness(tmp_path, now=now)
    assert assessment["status"] == "stale"
    assert assessment["age_days"] > T212_CATALOGUE_STALE_DAYS


def test_assess_missing_meta(tmp_path: Path) -> None:
    assessment = assess_t212_catalogue_freshness(tmp_path, now=datetime.now(UTC))
    assert assessment["status"] == "missing"
    assert assessment["fetched_at"] is None


def test_ops_findings_fresh_info() -> None:
    findings = ops_findings_from_t212_catalogue_freshness(
        {"status": "fresh", "age_days": 2.0, "fetched_at": "2026-11-01T00:00:00+00:00"}
    )
    assert len(findings) == 1
    assert findings[0]["severity"] == "info"
    assert findings[0]["title"] == T212_CATALOGUE_FRESH_TITLE


def test_ops_findings_stale_warn() -> None:
    findings = ops_findings_from_t212_catalogue_freshness(
        {
            "status": "stale",
            "age_days": 20.0,
            "fetched_at": "2026-10-01T00:00:00+00:00",
            "stale_after_days": 14,
        }
    )
    assert len(findings) == 1
    assert findings[0]["severity"] == "warn"
    assert findings[0]["title"] == T212_CATALOGUE_STALE_TITLE
    assert "t212-catalogue-refresh.yml" in findings[0]["summary"]


def test_ops_findings_missing_secrets_hint() -> None:
    findings = ops_findings_from_t212_catalogue_freshness({"status": "missing"})
    assert findings[0]["title"] == T212_CATALOGUE_STALE_TITLE
    assert "TRADING212_API_KEY" in findings[0]["summary"]
    assert "TRADING212_API_SECRET" in findings[0]["summary"]


def test_t212_catalogue_refresh_workflow_parses() -> None:
    path = Path(".github/workflows/t212-catalogue-refresh.yml")
    text = path.read_text(encoding="utf-8")
    yaml.safe_load(text)  # GitHub Actions YAML (`on:` is a YAML 1.1 boolean alias)
    assert 'cron: "0 5 * * 1"' in text
    assert "workflow_dispatch:" in text
    assert "Soft-skip: TRADING212_API_KEY" in text


def test_check_t212_catalogue_freshness_on_committed_meta() -> None:
    from value_investor.ops_monitor import check_t212_catalogue_freshness

    findings = check_t212_catalogue_freshness()
    assert len(findings) == 1
    assert findings[0].title in {T212_CATALOGUE_FRESH_TITLE, T212_CATALOGUE_STALE_TITLE}
    assert findings[0].auto_fixable is False
