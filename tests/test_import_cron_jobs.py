"""Tests for cron-job.org import helper."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_import_cron_jobs_dry_run_data_backup():
    script = Path("scripts/import_cron_jobs.py")
    proc = subprocess.run(
        [sys.executable, str(script), "--job", "data-backup", "--dry-run", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    rows = json.loads(proc.stdout)
    assert len(rows) == 1
    payload = rows[0]["payload"]["job"]
    assert payload["title"] == "FTSE data backup (Sunday)"
    assert payload["requestMethod"] == 1
    assert payload["schedule"]["hours"] == [12]
    assert payload["schedule"]["minutes"] == [30]
    assert "data-backup.yml" in payload["url"]


def test_import_cron_jobs_dry_run_ci_main_nightly():
    script = Path("scripts/import_cron_jobs.py")
    proc = subprocess.run(
        [sys.executable, str(script), "--job", "ci-main-nightly", "--dry-run", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    rows = json.loads(proc.stdout)
    assert len(rows) == 1
    payload = rows[0]["payload"]["job"]
    assert payload["title"] == "FTSE CI main nightly (daily)"
    assert payload["schedule"]["hours"] == [7]
    assert payload["schedule"]["minutes"] == [30]
    assert "ci-main-nightly.yml" in payload["url"]


def test_import_cron_jobs_dry_run_engineering_queue():
    script = Path("scripts/import_cron_jobs.py")
    proc = subprocess.run(
        [sys.executable, str(script), "--job", "engineering-queue", "--dry-run", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    rows = json.loads(proc.stdout)
    assert len(rows) == 1
    payload = rows[0]["payload"]["job"]
    assert payload["title"] == "FTSE engineering queue (hourly weekdays)"
    assert payload["schedule"]["hours"] == list(range(24))
    assert payload["schedule"]["minutes"] == [15]
    assert payload["schedule"]["wdays"] == [1, 2, 3, 4, 5]
    assert "engineering-queue.yml" in payload["url"]
    script = Path("scripts/import_cron_jobs.py")
    proc = subprocess.run(
        [sys.executable, str(script), "--job", "ops-monitor", "--dry-run", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    rows = json.loads(proc.stdout)
    assert len(rows) == 1
    payload = rows[0]["payload"]["job"]
    assert payload["title"] == "FTSE ops monitor (daily)"
    assert payload["requestMethod"] == 1
    assert payload["schedule"]["hours"] == [7]
    assert payload["schedule"]["minutes"] == [45]
    assert payload["schedule"]["wdays"] == [-1]
    assert "ops-monitor.yml" in payload["url"]
