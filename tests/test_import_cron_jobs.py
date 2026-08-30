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


def test_import_cron_jobs_dry_run_ingest_loop_morning():
    script = Path("scripts/import_cron_jobs.py")
    proc = subprocess.run(
        [sys.executable, str(script), "--job", "ingest-loop-morning", "--dry-run", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    rows = json.loads(proc.stdout)
    assert len(rows) == 1
    payload = rows[0]["payload"]["job"]
    assert payload["title"] == "FTSE ingest loop (weekday morning)"
    assert payload["schedule"]["hours"] == [7]
    assert payload["schedule"]["minutes"] == [5]
    assert payload["schedule"]["wdays"] == [1, 2, 3, 4, 5]
    body = json.loads(payload["extendedData"]["body"])
    assert body["inputs"]["max_targets"] == "62"
    assert body["inputs"]["max_bodies"] == "40"
    assert body["inputs"]["max_runtime_seconds"] == "3600"
    assert "ingest-loop.yml" in payload["url"]


def test_import_cron_jobs_dry_run_ingest_loop_afternoon():
    script = Path("scripts/import_cron_jobs.py")
    proc = subprocess.run(
        [sys.executable, str(script), "--job", "ingest-loop-afternoon", "--dry-run", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    rows = json.loads(proc.stdout)
    assert len(rows) == 1
    payload = rows[0]["payload"]["job"]
    assert payload["title"] == "FTSE ingest loop (weekday afternoon)"
    assert payload["schedule"]["hours"] == [10]
    assert payload["schedule"]["minutes"] == [5]
    body = json.loads(payload["extendedData"]["body"])
    assert body["inputs"]["max_targets"] == "62"
    assert body["inputs"]["max_bodies"] == "40"


def test_import_cron_jobs_dry_run_disable_legacy_ingest():
    import os

    script = Path("scripts/import_cron_jobs.py")
    env = os.environ.copy()
    env.pop("CRONJOB_API_KEY", None)
    proc = subprocess.run(
        [sys.executable, str(script), "--disable-legacy-ingest", "--dry-run", "--json"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    rows = json.loads(proc.stdout)
    titles = {row["title"] for row in rows}
    assert "FTSE ingest loop (Mon/Wed/Fri morning)" in titles
    assert "Euro ingest loop (weekday morning)" in titles
    assert "Library ingest sprint (parallel morning)" in titles
    assert all(row["action"] == "would_disable" for row in rows)


def test_import_cron_jobs_library_ingest_7day_peak_and_offpeak():
    script = Path("scripts/import_cron_jobs.py")
    peak_keys = (
        "euro-ingest-loop-morning",
        "euro-ingest-loop-afternoon",
        "library-ingest-sprint-morning",
        "library-ingest-maintenance",
    )
    offpeak_keys = (
        "euro-ingest-loop-midafternoon",
        "euro-ingest-loop-evening",
        "library-ingest-sprint-evening",
        "library-ingest-maintenance-evening",
    )
    peak_wdays = [1, 2, 3, 4, 5, 6]
    offpeak_wdays = [-1]

    for key in peak_keys:
        proc = subprocess.run(
            [sys.executable, str(script), "--job", key, "--dry-run", "--json"],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(proc.stdout)[0]["payload"]["job"]
        assert payload["schedule"]["wdays"] == peak_wdays, key
        assert "weekday" not in payload["title"].lower()

    for key in offpeak_keys:
        proc = subprocess.run(
            [sys.executable, str(script), "--job", key, "--dry-run", "--json"],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(proc.stdout)[0]["payload"]["job"]
        assert payload["schedule"]["wdays"] == offpeak_wdays, key
        assert "daily" in payload["title"].lower()

    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--job",
            "library-ingest-maintenance-midafternoon",
            "--dry-run",
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    maint = json.loads(proc.stdout)[0]["payload"]["job"]
    assert maint["schedule"]["hours"] == [13]
    assert maint["schedule"]["minutes"] == [30]
    assert maint["schedule"]["wdays"] == offpeak_wdays
    assert "library-ingest-maintenance.yml" in maint["url"]


def test_import_cron_jobs_dry_run_ops_monitor():
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
