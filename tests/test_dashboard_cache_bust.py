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
    assert '["queue_health", "data/queue_health.json"]' in text
    assert '["observe_utilization", "data/observe_utilization.json"]' in text
    assert '["lifecycle_maturity_trajectory", "data/lifecycle_maturity_trajectory.json"]' in text
    assert '["market_status", "data/market_status.json"]' in text
    assert '["system_gaps", "data/system_gaps.json"]' in text
    assert '["ingest_deviations", "data/ingest_deviations.json"]' in text
    assert '["human_tasks_checklist", "human_tasks_checklist.json"]' in text
    assert '["lifecycle_board", "data/lifecycle_board.json"]' in text
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


def test_sunday_review_paper_tracks_sorted_by_track_then_week() -> None:
    """Analysis → Sunday review paper table groups by track, weeks ascending within track."""
    text = APP_JS.read_text(encoding="utf-8")
    fn = text.split("function renderSundayReview(", 1)[1].split("\nfunction renderAnalysis(", 1)[0]
    assert "trackA.localeCompare(trackB)" in fn
    assert 'String(a.week_ending || "").localeCompare(String(b.week_ending || ""))' in fn
    # Collapsed-by-track disclosure: summary line + expand for week detail.
    assert "groupPaperTracksById(trackWeekRows)" in fn
    assert "paperTrackStory(group.weeks)" in fn
    assert 'class="paper-track-details overview-secondary"' in fn
    assert "<th>Week</th>" in fn
    assert fn.index("<th>Week</th>") < fn.index("<th>Excess vs ^FTSE</th>")
    # Must not revert to week-only newest-first sort of the flattened rows.
    assert "String(b.week_ending).localeCompare(String(a.week_ending))" not in fn
    # Flat all-tracks mega-table with Track column must not return.
    assert "<th>Track</th>" not in fn


def test_paper_track_story_helper_deterministic() -> None:
    """paperTrackStory is a pure helper from excess / cost / marks (no LLM)."""
    text = APP_JS.read_text(encoding="utf-8")
    assert "function paperTrackStory(weeks)" in text
    assert "function groupPaperTracksById(trackWeekRows)" in text
    assert "function fmtSignedPct(value" in text
    # Extract and eval the helper (plus fmtSignedPct it depends on).
    start = text.index("function fmtSignedPct(value")
    end = text.index("function renderSundayReview(")
    chunk = text[start:end]
    from subprocess import check_output

    script = (
        chunk
        + """
const improving = paperTrackStory([
  { excess_after_costs: -0.02, cost_drag: 0.001, equity_marks: 10, trade_count: 2 },
  { excess_after_costs: 0.01, cost_drag: 0.002, equity_marks: 12, trade_count: 3 },
]);
const lagging = paperTrackStory([
  { excess_after_costs: 0.03, cost_drag: 0.01, equity_marks: 8, trade_count: 1 },
  { excess_after_costs: -0.02, cost_drag: 0.012, equity_marks: 9, trade_count: 10 },
]);
const thin = paperTrackStory([
  { excess_after_costs: 0.02, cost_drag: 0.001, equity_marks: 2, trade_count: 0 },
]);
const empty = paperTrackStory([]);
console.log(JSON.stringify({ improving, lagging, thin, empty }));
"""
    )
    out = check_output(["node", "-e", script], text=True)
    import json

    payload = json.loads(out)
    assert "Beating ^FTSE" in payload["improving"]
    assert "improving" in payload["improving"]
    assert "Lagging ^FTSE" in payload["lagging"]
    assert "softening" in payload["lagging"]
    assert "Cost drag" in payload["lagging"]
    assert "Trade count rising" in payload["lagging"]
    assert "thin" in payload["thin"].lower()
    assert payload["empty"] == "No weekly marks yet."
