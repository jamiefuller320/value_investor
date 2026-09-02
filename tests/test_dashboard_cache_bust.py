"""Dashboard fetch paths must bust GitHub Pages JSON caching."""

from __future__ import annotations

from pathlib import Path

APP_JS = Path("docs/app.js")


def test_load_dashboard_cache_busts_progress_report() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    assert "async function fetchDashboardJson(path)" in text
    assert 'cache: "no-store"' in text
    assert "fetchDashboardJson(\"data/latest.json\")" in text
    assert "fetchDashboardJson(\"data/progress_report.json\")" in text or (
        'loadOptionalDashboardJson("data/progress_report.json")' in text
    )
    # Must not leave a bare uncached progress_report fetch in loadDashboard.
    load_fn = text.split("async function loadDashboard()", 1)[1].split(
        "\nasync function ", 1
    )[0]
    assert "fetch(\"data/progress_report.json\")" not in load_fn
    assert "progress_report.json" in load_fn
