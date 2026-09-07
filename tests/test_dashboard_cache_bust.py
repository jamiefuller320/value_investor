"""Dashboard fetch paths must bust GitHub Pages JSON caching."""

from __future__ import annotations

from pathlib import Path

APP_JS = Path("docs/app.js")


def test_load_dashboard_cache_busts_progress_report() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    assert "async function fetchDashboardJson(path)" in text
    assert 'cache: "no-store"' in text
    assert 'fetchDashboardJson("data/latest.json")' in text
    assert '["progress_report", "data/progress_report.json"]' in text
    assert '["market_status", "data/market_status.json"]' in text
    assert '["system_gaps", "data/system_gaps.json"]' in text
    assert '["ingest_deviations", "data/ingest_deviations.json"]' in text
    assert '["human_tasks_checklist", "human_tasks_checklist.json"]' in text
    assert "async function applyDashboardSidecars(data)" in text
    assert "DASHBOARD_SIDECARS" in text
    assert "function bindDashboardAutoRefresh()" in text
    assert "visibilitychange" in text
    assert "await reloadDashboard({ silent: true, rebuild: true })" in text
    assert 'fetch("/api/refresh"' in text
    # Sidecars overlay latest.json every load, not only when the embed is missing.
    assert "if (!data.market_status)" not in text
    assert "if (!data.automation)" not in text
    reload_fn = text.split("async function reloadDashboard(", 1)[1].split(
        "\nfunction bindDashboardAutoRefresh", 1
    )[0]
    assert "applyDashboardSidecars(data)" in reload_fn
    assert 'fetch("data/progress_report.json")' not in reload_fn
    load_fn = text.split("async function loadDashboard()", 1)[1].split("\ninitTabs()", 1)[0]
    assert "reloadDashboard()" in load_fn
    assert 'fetch("data/progress_report.json")' not in load_fn
