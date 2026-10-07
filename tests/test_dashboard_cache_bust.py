"""Dashboard fetch paths must bust GitHub Pages JSON caching."""

from __future__ import annotations

from pathlib import Path

APP_JS = Path("docs/app.js")


def test_index_html_cache_busts_app_js() -> None:
    html = Path("docs/index.html").read_text(encoding="utf-8")
    assert 'src="app.js?v=' in html
    assert 'src="dashboard_bridge.js?v=' in html


def test_load_dashboard_cache_busts_progress_report() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    assert "async function fetchDashboardJson(path)" in text
    assert 'cache: "no-store"' in text
    assert 'fetchDashboardJson("data/latest.json")' in text
    assert '["progress_report", "data/progress_report.json"]' in text
    assert '["queue_health", "data/queue_health.json"]' in text
    assert '["observe_utilization", "data/observe_utilization.json"]' in text
    assert '["assessment_scoreboard", "data/assessment_scoreboard.json"]' in text
    assert '["total_return_view", "data/total_return_view.json"]' in text
    assert '["lifecycle_maturity_trajectory", "data/lifecycle_maturity_trajectory.json"]' in text
    assert '["market_status", "data/market_status.json"]' in text
    assert '["system_gaps", "data/system_gaps.json"]' in text
    assert '["ingest_deviations", "data/ingest_deviations.json"]' in text
    assert '["human_tasks_checklist", "human_tasks_checklist.json"]' in text
    assert '["human_tasks_board", "data/human_tasks_board.json"]' in text
    assert '["human_task_acks", "data/human_task_acks.json"]' in text
    assert "function mergeHumanTaskAcksIntoBoard(board, acksStore)" in text
    assert "mergeHumanTaskAcksIntoBoard(" in text
    assert '["daily_focus", "data/daily_focus.json"]' in text
    assert '["ui_state_reconciliation", "data/ui_state_reconciliation.json"]' in text
    assert '["universe_filing_archive_status", "data/universe_filing_archive_status.json"]' in text
    assert '["daily_focus_acks", "data/daily_focus_acks.json"]' in text
    assert '["daily_discuss_inbox", "data/daily_discuss_inbox.json"]' in text
    assert '["daily_hub_history", "data/daily_hub_history.json"]' in text
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
    # Human-task ack: optimistic bottom-sort on click (before bridge), then wait/reload.
    assert "const pendingHumanTaskAcks" in text
    assert "function applyOptimisticHumanTaskAck(" in text
    assert "function overlayPendingHumanTaskAcks(" in text
    assert "function syncHumanTasksBoardOverlay(" in text
    assert "function refreshHumanTasksBoardView(" in text
    assert "prunePendingHumanTaskAcksAgainstDurable(" in text
    assert "const pendingDailyAccepts" in text
    assert "function applyOptimisticDailyAccept(" in text
    assert "function syncDailyFocusOverlay(" in text
    render_fn = text.split("function renderDashboard(data)", 1)[1].split(
        "\nasync function loadOptionalDashboardJson", 1
    )[0]
    assert "syncHumanTasksBoardOverlay(data)" in render_fn
    assert "syncDailyFocusOverlay(data)" in render_fn
    ack_fn = text.split("async function acknowledgeHumanTaskFromCard(", 1)[1].split(
        "\nfunction resolveObserveUtilization(", 1
    )[0]
    assert "applyOptimisticHumanTaskAck(payload)" in ack_fn
    # Must paint disabled/bottom *before* any bridge await (latency was the bug).
    assert ack_fn.index("applyOptimisticHumanTaskAck(payload)") < ack_fn.index("queueCommand")
    assert ack_fn.index("applyOptimisticHumanTaskAck(payload)") < ack_fn.index(
        "DashboardBridge.init()"
    )
    assert "queueCommand" in ack_fn
    assert "waitForCommand" in ack_fn
    assert "reloadDashboard({ silent: true, rebuild: true })" in ack_fn
    assert "Queued — waiting for bridge" not in ack_fn
    bridge_js = Path("docs/dashboard_bridge.js").read_text(encoding="utf-8")
    assert "async function queueCommand(" in bridge_js
    assert "function waitForCommand(" in bridge_js
    assert "options.wait === false" in bridge_js
    load_fn = text.split("async function loadDashboard()", 1)[1].split("\ninitTabs()", 1)[0]
    assert "reloadDashboard()" in load_fn
    assert 'fetch("data/progress_report.json")' not in load_fn
    assert "function shouldOverlayDashboardSidecar(key, existing, sidecar)" in text
    sidecar_fn = text.split("async function applyDashboardSidecars(data)", 1)[1].split(
        "\nfunction isLocalDashboardServe(", 1
    )[0]
    assert "shouldOverlayDashboardSidecar(key, data[key], payload)" in sidecar_fn


def test_project_progress_sidecar_does_not_hide_newer_embed() -> None:
    """L484-owned sidecar may lag Sunday publish; keep newer generated_at."""
    from subprocess import check_output

    text = APP_JS.read_text(encoding="utf-8")
    start = text.index("function sidecarGeneratedAtMs(payload)")
    end = text.index("async function applyDashboardSidecars(data)")
    helpers = text[start:end]
    script = (
        helpers
        + """
const embed = { generated_at: "2026-10-04T08:19:40.234221+00:00", source: "embed" };
const stale = { generated_at: "2026-09-30T20:08:50.133761+00:00", source: "sidecar" };
const fresh = { generated_at: "2026-10-04T20:00:00Z", source: "sidecar" };
const out = {
  skip_stale: shouldOverlayDashboardSidecar("project_progress", embed, stale),
  take_fresh: shouldOverlayDashboardSidecar("project_progress", embed, fresh),
  other_key: shouldOverlayDashboardSidecar("automation", embed, stale),
  missing_embed: shouldOverlayDashboardSidecar("project_progress", null, stale),
};
console.log(JSON.stringify(out));
"""
    )
    raw = check_output(["node", "-e", script], text=True)
    import json

    out = json.loads(raw)
    assert out["skip_stale"] is False
    assert out["take_fresh"] is True
    assert out["other_key"] is True
    assert out["missing_embed"] is True


def test_human_task_ack_optimistic_overlay_sorts_acked_to_bottom() -> None:
    """Session pending ack moves a card to acked/bottom via the same merge helper."""
    import json
    from subprocess import check_output

    text = APP_JS.read_text(encoding="utf-8")
    start = text.index("function mergeHumanTaskAcksIntoBoard(board, acksStore)")
    end = text.index("async function applyDashboardSidecars(data)")
    chunk = text[start:end]
    # Standalone harness: pending map + helpers extracted from app.js
    script = (
        "const pendingHumanTaskAcks = Object.create(null);\n"
        + "let humanTasksBoardBase = null;\n"
        + chunk
        + """
const board = {
  counts: { new_info: 0, unacked: 2, acked: 0, human: 2 },
  tasks: [
    {
      id: "task-a",
      sort_bucket: "unacked",
      ack: { acked: false, stale: false },
      analysis: { fingerprint: "fp-a", updated_at: "2026-09-27T12:00:00Z" },
    },
    {
      id: "task-b",
      sort_bucket: "unacked",
      ack: { acked: false, stale: false },
      analysis: { fingerprint: "fp-b", updated_at: "2026-09-27T11:00:00Z" },
    },
  ],
};
humanTasksBoardBase = board;
rememberPendingHumanTaskAck({
  task_id: "task-a",
  decision: "ack_observe",
  finding_fingerprint: "fp-a",
});
const merged = mergeHumanTaskAcksIntoBoard(board, overlayPendingHumanTaskAcks(null));
// Pending must override a durable open row with a different fingerprint.
const durableStale = {
  acks: [{
    task_id: "task-a",
    status: "open",
    finding_fingerprint: "fp-old",
    decision: "ack_observe",
    acked_at: "2026-09-01T00:00:00Z",
  }],
};
const overridden = mergeHumanTaskAcksIntoBoard(
  board,
  overlayPendingHumanTaskAcks(durableStale)
);
// Soft-reload simulation: merge without pending first, then sync with pending.
const data = {
  human_task_acks: { acks: [] },
  human_tasks_board: board,
};
const clobbered = mergeHumanTaskAcksIntoBoard(board, { acks: [] });
data.human_tasks_board = clobbered;
syncHumanTasksBoardOverlay(data);
const taskA = overridden.tasks.find((t) => t.id === "task-a");
const syncedA = data.human_tasks_board.tasks.find((t) => t.id === "task-a");
console.log(JSON.stringify({
  ids: merged.tasks.map((t) => t.id),
  buckets: merged.tasks.map((t) => t.sort_bucket),
  counts: merged.counts,
  pendingKeys: Object.keys(pendingHumanTaskAcks),
  overrideBucket: taskA && taskA.sort_bucket,
  overrideStale: taskA && taskA.ack && taskA.ack.stale,
  syncedBucket: syncedA && syncedA.sort_bucket,
  syncedAcked: syncedA && syncedA.ack && syncedA.ack.acked,
  syncedDisabled: syncedA && syncedA.ack && syncedA.ack.acked && !syncedA.ack.stale,
}));
"""
    )
    payload = json.loads(check_output(["node", "-e", script], text=True))
    assert payload["ids"] == ["task-b", "task-a"]
    assert payload["buckets"] == ["unacked", "acked"]
    assert payload["counts"]["acked"] == 1
    assert payload["counts"]["unacked"] == 1
    assert payload["pendingKeys"] == ["task-a"]
    assert payload["overrideBucket"] == "acked"
    assert payload["overrideStale"] is False
    assert payload["syncedBucket"] == "acked"
    assert payload["syncedAcked"] is True
    assert payload["syncedDisabled"] is True


def test_sunday_review_paper_tracks_sorted_by_track_then_week() -> None:
    """Analysis → Sunday review paper table groups by track, weeks ascending within track."""
    text = APP_JS.read_text(encoding="utf-8")
    fn = text.split("function renderSundayReview(", 1)[1].split("\nconst ANALYSIS_SECTION_IDS", 1)[
        0
    ]
    if "function renderAnalysis(" in fn:
        fn = fn.split("\nfunction renderAnalysis(", 1)[0]
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
    # Exclusion / regime / experiments default-collapsed (Analysis IA).
    assert 'class="analysis-block overview-secondary"' in fn
    assert "<strong>Exclusion ladder</strong>" in fn
    assert "<strong>Regime snapshots</strong>" in fn
    assert "open>" not in fn  # no always-open details for these blocks


def test_analysis_tab_ia_contract() -> None:
    """Analysis tab: subnav + compact observe strip + section anchors (L477)."""
    text = APP_JS.read_text(encoding="utf-8")
    css = Path("docs/styles.css").read_text(encoding="utf-8")
    assert "function renderAnalysisSubnav(activeId)" in text
    assert "function jumpToAnalysisSection(sectionId" in text
    assert "function bindAnalysisPanel(panel)" in text
    assert 'id="analysis-observe"' in text
    assert 'id="analysis-sunday"' in text
    assert 'id="analysis-charts"' in text
    assert 'id="analysis-postrun"' in text
    assert 'id="analysis-memos"' in text
    assert "analysis-observe-compact" in text
    assert 'data-tab-jump="automation"' in text
    assert "Compact strip" in text
    # Compact path must not render the full instrument grid.
    observe = text.split("function renderObserveUtilizationSection(", 1)[1].split(
        "\nfunction renderLifecycleMaturityHistorySparkline(", 1
    )[0]
    compact_branch = observe.split("if (compact)", 1)[1].split("const cards =", 1)[0]
    assert "observe-instrument-grid" not in compact_branch
    assert "observe-instrument-grid" in observe
    assert ".analysis-subnav" in css
    assert ".analysis-section" in css
    assert ".analysis-block" in css
    # Hash routing for Analysis sections.
    parse = text.split("function parseDashboardHash()", 1)[1].split(
        "\nfunction syncLifecycleHash()", 1
    )[0]
    assert 'tab === "analysis"' in parse
    assert "normalizeAnalysisSection" in parse


def test_market_role_badge_taxonomy_helpers() -> None:
    """Market role chips disambiguate admitted / graduated / queue / live (L478)."""
    text = APP_JS.read_text(encoding="utf-8")
    start = text.index("const MARKET_INGEST_LABELS =")
    end = text.index("function learningBookLine(")
    chunk = text[start:end]
    import json
    from subprocess import check_output

    script = (
        "function esc(t){return String(t??'');}\n"
        + chunk
        + """
const admitted = marketLearningRoleChips({
  role: 'admitted', is_admitted: true, is_graduated: true, is_queue: false
});
const graduatedOnly = marketLearningRoleChips({
  role: 'graduated', is_graduated: true, is_admitted: false, is_queue: false
});
const queue = marketLearningRoleChips({
  role: 'queue', is_queue: true, is_admitted: false, is_graduated: false
});
const live = marketLearningRoleChips({
  role: 'live', is_live: true, is_admitted: false
});
const focusAdmitted = marketLearningRoleChips({
  role: 'focus', is_focus: true, is_admitted: true, is_graduated: true
});
console.log(JSON.stringify({
  admitted, graduatedOnly, queue, live, focusAdmitted,
  ingestLive: marketIngestBadge('live'),
  ingestMaint: marketIngestBadge('maintenance'),
}));
"""
    )
    payload = json.loads(check_output(["node", "-e", script], text=True))
    assert "mrole-admitted" in payload["admitted"]
    assert "mrole-graduated" not in payload["admitted"]  # admitted ⇒ skip graduated synonym chip
    assert "mrole-graduated" in payload["graduatedOnly"]
    assert "mrole-admitted" not in payload["graduatedOnly"]
    assert "mrole-queue" in payload["queue"]
    assert "mrole-live" in payload["live"]
    assert (
        "mrole-focus" in payload["focusAdmitted"] and "mrole-admitted" in payload["focusAdmitted"]
    )
    assert "mingest-live" in payload["ingestLive"]
    assert "mingest-maintenance" in payload["ingestMaint"]
    assert "stage-complete" not in payload["ingestLive"]
    assert "stage-complete" not in payload["ingestMaint"]


def test_learning_gate_indicator_helper_renders_steps() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    start = text.index("function renderLearningGateIndicator(")
    end = text.index("const ADMISSION_FLAG_LABELS =")
    chunk = text[start:end]
    import json
    from subprocess import check_output

    script = (
        "function esc(t){return String(t??'');}\n"
        + chunk
        + """
const html = renderLearningGateIndicator({
  current_id: 'ftse_parity_learning',
  steps: [
    {id:'start', label:'Start', gate:'ingest_clock', status:'done'},
    {id:'bodies', label:'Bodies', gate:'unmeasured_zero_clear', status:'done'},
    {id:'sprint_complete', label:'Sprint', gate:'sprint_ingest_complete', status:'done'},
    {id:'admit', label:'Admit', gate:'l322_admit', status:'done'},
    {id:'epoch0', label:'Epoch-0', gate:'epoch0_marks', status:'done'},
    {id:'ftse_parity_learning', label:'Parity', gate:'learning_ready', status:'current'},
    {id:'live_ready', label:'Live', gate:'phase_4_live_screen', status:'pending'},
  ],
  next_gate: {name:'FTSE-parity learning', criteria:'learning_ready = filing_ready and 12w', timeframe:'~1.4w remaining'},
  annotation: 'full card text',
}, {compact: true});
const live = renderLearningGateIndicator({
  current_id: 'live_ready',
  annotation: 'Next: Live-path utilization (P1) — FTSE 350 is already the live screen',
  steps: [
    {id:'start', label:'Start', gate:'ingest_clock', status:'done'},
    {id:'bodies', label:'Bodies', gate:'unmeasured_zero_clear', status:'done'},
    {id:'sprint_complete', label:'Sprint', gate:'sprint_ingest_complete', status:'done'},
    {id:'admit', label:'Admit', gate:'l322_admit', status:'done'},
    {id:'epoch0', label:'Epoch-0', gate:'epoch0_marks', status:'done'},
    {id:'ftse_parity_learning', label:'Parity', gate:'learning_ready', status:'done'},
    {id:'live_ready', label:'Live', gate:'phase_4_live_screen', status:'done'},
  ],
  next_gate: {name:'Live-path utilization (P1)', criteria:'FTSE 350 is already the live screen', timeframe:'Not calendar'},
});
console.log(JSON.stringify({html, live, empty: renderLearningGateIndicator(null)}));
"""
    )
    payload = json.loads(check_output(["node", "-e", script], text=True))
    assert "learning-gate-track" in payload["html"]
    assert "is-current" in payload["html"]
    assert "is-done" in payload["html"]
    assert "Parity" in payload["html"]
    assert "~1.4w remaining" in payload["html"]
    assert "Live-path utilization" in payload["live"]
    assert payload["empty"] == ""


def test_model_attribution_panel_prefers_primary_horizon() -> None:
    """Performance historical panel: 28d buy-tier excess primary; 7d demoted."""
    text = APP_JS.read_text(encoding="utf-8")
    assert "function renderModelAttributionPanel(historical)" in text
    assert "function modelAttributionMeta(historical)" in text
    fn = text.split("function renderHistoricalAnalysis(historical)", 1)[1].split(
        "\nconst PERF_SIM_TRACK_KEY", 1
    )[0]
    assert "renderModelAttributionPanel(historical)" in fn
    assert ".slice(0, 8)" not in fn
    assert "primary_horizon_days" in text
    assert "score → FTSE excess, buy-tier" in text
    assert "Noise check" in text
    assert "model_attribution_meta.exit_join" in text
    # Must not present an unsorted top-8 that buries 28d behind 7d.
    assert "Model attribution (score→return correlation)" not in text


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


def test_learning_tracks_panel_dual_suite_contract() -> None:
    """Automation tracks: assessment scoreboard is canonical; Suite A/B is legacy."""
    text = APP_JS.read_text(encoding="utf-8")
    assert "function renderLearningTracksPanel(data)" in text
    assert "function learningTrackIsSuiteB(trackId, trackConfigs)" in text
    assert "function renderAssessmentScoreboardPanel(data)" in text
    assert "function renderTotalReturnVsPricePanel(data)" in text
    fn = text.split("function renderLearningTracksPanel(data)", 1)[1].split(
        "\nfunction renderAutomation(", 1
    )[0]
    assert "Legacy Suite B pair" in fn
    assert "Suite A stress / churn lab" in fn
    assert "do not promote on stress excess alone" in fn
    assert "total return vs FTAL.L" in fn
    assert "Primary success = AI judgment excess vs ^FTSE after costs" not in fn
    assert "Adoption truth (Suite B fair)" not in fn
    assert "learning_tracks_dual_suite" in fn
    assert "N145" in fn
    board = text.split("function renderAssessmentScoreboardPanel(data)", 1)[1].split(
        "\nfunction renderTotalReturnVsPricePanel(data)", 1
    )[0]
    assert "significance_gate_v1" in board
    assert "Price-only 90% band" in board


def test_historical_siblings_prefer_28d_primary() -> None:
    """Strategy / overlay / signal backtest: 28d primary, 7d demoted (not attribution)."""
    text = APP_JS.read_text(encoding="utf-8")
    assert "function historicalHorizonMeta(source)" in text
    assert "function partitionByHorizon(rows, meta)" in text
    hist = text.split("function renderHistoricalAnalysis(historical)", 1)[1].split(
        "\n/** Model attribution:", 1
    )[0]
    assert "Strategy horizons — primary" in hist
    assert "Noise check" in hist
    assert (
        "a.horizon_days - b.horizon_days || a.strategy.localeCompare"
        not in hist.split("strategyNoise", 1)[0]
    )
    # Attribution remains separate and untouched by sibling tables.
    assert "renderModelAttributionPanel(historical)" in hist
    perf = text.split("function renderPerformance(data)", 1)[1].split(
        "\nfunction renderAnalysis(", 1
    )[0]
    assert "Primary" in perf and "d — excess vs ^FTSE" in perf
    assert "Noise check —" in perf
    assert "Cohort: universe signal buckets" in perf


def test_post_run_and_chart_outcome_presentation_contracts() -> None:
    """Post-run uses structured sections; chart outcomes restore samples + success copy."""
    text = APP_JS.read_text(encoding="utf-8")
    analysis = text.split("function renderAnalysis(data)", 1)[1].split("\nfunction settingRow(", 1)[
        0
    ]
    assert "Persistent weaknesses" in analysis
    assert (
        "not</strong> an engineering backlog" in analysis
        or "not an engineering backlog" in analysis
    )
    assert "post-run-improvement-clearance.md" in analysis
    assert "full_text || postRun.executive_summary" not in analysis
    assert "Full text (archive)" in analysis
    chart = text.split("function renderChartOutcomeReview(data", 1)[1].split(
        "\nfunction renderStrongBuys(", 1
    )[0]
    assert "not</strong> paper-book excess" in chart or "not paper-book excess" in chart
    assert "chart-outcome-samples" in chart
    assert "N58" in chart
    assert 'samples = compact\n    ? ""' not in chart
    churn = text.split("function renderChurnCounterfactualPanel(data)", 1)[1].split(
        "\nfunction renderIngestDeviationsSection(", 1
    )[0]
    assert "Churn ops window" in churn
    assert "not an investment thesis horizon" in churn


def test_held_vs_market_caption_not_fair_excess() -> None:
    """Overview held-vs-market caption (L341): sleeve vs price index, not fair book excess."""
    charts = Path("docs/charts.js").read_text(encoding="utf-8")
    assert "Sleeve vs price index (not fair book excess)" in charts
    fn = charts.split("function heldVsMarketLastCaption(", 1)[1].split("\n/** Short epoch-0", 1)[0]
    assert "not fair book excess" in fn
    assert "beat_market" in fn
