"""Automation tab Daily hub sub-pages + illumination + Accept/Discuss contracts."""

from __future__ import annotations

from pathlib import Path

APP_JS = Path("docs/app.js")
STYLES = Path("docs/styles.css")
OPS_MONITOR = Path("docs/ops/ops-monitor.md")
BRIDGE = Path("docs/ops/dashboard-bridge.md")


def test_automation_subnav_and_hash_routes() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    assert "function renderAutomationSubnav(" in text
    assert "function normalizeAutomationSection(" in text
    assert "function syncAutomationHash(" in text
    assert "function jumpToAutomationSection(" in text
    assert 'data-automation-section="' in text
    assert 'aria-label="Automation sections"' in text
    assert "automation-subnav" in text
    assert (
        'AUTOMATION_SECTION_IDS = ["daily", "tracks", "human", "queue", "ops", "settings"]' in text
    )
    assert 'history.replaceState(null, "", "#automation")' in text
    assert "`#automation/${section}`" in text or "#automation/" in text
    # Hash parser branch for automation
    parse_fn = text.split("function parseDashboardHash()", 1)[1].split(
        "\nfunction syncLifecycleHash", 1
    )[0]
    assert 'tab === "automation"' in parse_fn
    assert "normalizeAutomationSection" in parse_fn


def test_render_automation_uses_section_panes() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    fn = text.split("function renderAutomation(data)", 1)[1].split("\nlet lifecycleMarketId", 1)[0]
    assert "renderAutomationSubnav(" in fn
    assert "renderDailyHubPanel(" in fn
    assert 'data-automation-pane="daily"' in fn
    assert 'data-automation-pane="tracks"' in fn
    assert 'data-automation-pane="human"' in fn
    assert 'data-automation-pane="queue"' in fn
    assert 'data-automation-pane="ops"' in fn
    assert 'data-automation-pane="settings"' in fn
    assert "renderUiReconcileTable(" in fn


def test_daily_hub_accept_discuss_ux() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    assert "function renderDailyRecommendationBlock(" in text
    assert "function acceptDailyRecommendation(" in text
    assert "function discussDailyRecommendation(" in text
    assert "function dailyDiscussPastePhrase(" in text
    assert "function showDailyDiscussPastePhrase(" in text
    assert "function copyTextToClipboard(" in text
    assert 'data-daily-accept="' in text
    assert 'data-daily-discuss="' in text
    assert "discuss daily recommendation" in text
    assert "daily-discuss-paste-phrase" in text
    assert "Copy paste phrase" in text
    assert "Paste into Project chat" in text
    # Canonical short phrase (backticks around rec id).
    assert "discuss daily recommendation \\`" in text or "discuss daily recommendation `" in text
    assert "daily_discuss_inbox.json" in text or "daily-discuss" in text
    assert 'queueDailyBridgeAction("daily-discuss"' in text or '"daily-discuss"' in text
    assert "daily-focus-ack" in text
    assert "human-task-ack" in text
    css = STYLES.read_text(encoding="utf-8")
    assert ".daily-discuss-paste" in css
    assert ".daily-discuss-paste-phrase" in css


def test_daily_hub_accept_discuss_optimistic_disable() -> None:
    """Accept/Discuss must lock buttons before any bridge await; Accept persists via overlay."""
    text = APP_JS.read_text(encoding="utf-8")
    assert "const pendingDailyAccepts" in text
    assert "const pendingDailyDiscuss" in text
    assert "const inflightDailyRecActions" in text
    assert "function applyOptimisticDailyAccept(" in text
    assert "function syncDailyFocusOverlay(" in text
    assert "function disableDailyRecRowButtons(" in text
    assert "function dailyRecRowState(" in text
    assert "let dailyFocusBase" in text

    accept_fn = text.split("async function acceptDailyRecommendation(", 1)[1].split(
        "\nasync function discussDailyRecommendation(", 1
    )[0]
    # Disable + overlay before any network / bridge await.
    assert "disableDailyRecRowButtons(button" in accept_fn
    assert "applyOptimisticDailyAccept(payload)" in accept_fn
    assert accept_fn.index("disableDailyRecRowButtons(button") < accept_fn.index(
        "queueDailyBridgeAction"
    )
    assert accept_fn.index("applyOptimisticDailyAccept(payload)") < accept_fn.index(
        "queueDailyBridgeAction"
    )
    # Human-task Accept path: optimistic board ack before bridge await (same as card ack).
    assert "applyOptimisticHumanTaskAck(htPayload)" in accept_fn
    assert accept_fn.index("applyOptimisticHumanTaskAck(htPayload)") < accept_fn.index(
        "DashboardBridge.init()"
    )
    assert "inflightDailyRecActions" in accept_fn

    discuss_fn = text.split("async function discussDailyRecommendation(", 1)[1].split(
        "\nfunction renderAutomationSettingsSection(", 1
    )[0]
    assert "disableDailyRecRowButtons(button" in discuss_fn
    assert 'rememberPendingDailyDiscuss(payload, "inflight")' in discuss_fn
    assert discuss_fn.index("disableDailyRecRowButtons(button") < discuss_fn.index(
        "copyTextToClipboard"
    )
    assert discuss_fn.index('rememberPendingDailyDiscuss(payload, "inflight")') < discuss_fn.index(
        "queueDailyBridgeAction"
    )
    # After success Discuss stays locked; Accept re-enabled (copy buttons still work).
    assert 'rememberPendingDailyDiscuss(payload, "queued")' in discuss_fn
    assert "enableDailyRecRowButtons(button, { accept: true, discuss: false })" in discuss_fn
    # Must not re-enable Discuss after queue (old bug).
    assert "button.disabled = false" not in discuss_fn.split("catch", 1)[0]

    render_fn = text.split("function renderDashboard(data)", 1)[1].split(
        "\nasync function loadOptionalDashboardJson", 1
    )[0]
    assert "syncDailyFocusOverlay(data)" in render_fn

    sidecar_fn = text.split("async function applyDashboardSidecars(data)", 1)[1].split(
        "\nfunction isLocalDashboardServe(", 1
    )[0]
    assert "dailyFocusBase = data.daily_focus" in sidecar_fn
    assert "syncDailyFocusOverlay(data)" in sidecar_fn


def test_daily_hub_accept_overlay_closes_task_until_durable() -> None:
    """Session pending Accept marks the daily hub task closed across soft reloads."""
    import json
    from subprocess import check_output

    text = APP_JS.read_text(encoding="utf-8")
    # Extract only Daily-hub overlay helpers (not human-task board merge).
    fn_start = text.index("function dailyRecOverlayKey(payload)")
    fn_end = text.index("function setHumanTaskAckStatus(taskId, text)")
    helpers = text[fn_start:fn_end]
    script = (
        "let dailyFocusBase = null;\n"
        "const pendingDailyAccepts = Object.create(null);\n"
        "const pendingDailyDiscuss = Object.create(null);\n"
        "const inflightDailyRecActions = Object.create(null);\n"
        # Stub view refresh — overlay tests only need remember/apply/prune/state.
        "function refreshDailyHubView() {}\n"
        "function renderAutomation() {}\n"
        + helpers
        + """
const base = {
  local_date: "2026-09-28",
  closed_today: [],
  tasks: [
    {
      task_ref: "focus-2",
      recommendation_id: "rec-aaa",
      closed: false,
      title: "Focus 2",
    },
    {
      task_ref: "human:task-x",
      recommendation_id: "rec-bbb",
      closed: false,
      title: "Human X",
    },
  ],
  open_task_count: 2,
};
dailyFocusBase = base;
rememberPendingDailyAccept({
  recommendation_id: "rec-aaa",
  task_ref: "focus-2",
  local_date: "2026-09-28",
});
const overlaid = applyPendingDailyOverlays(base);
const open = overlaid.tasks.filter((t) => !t.closed);
const data = {
  daily_focus: base,
  daily_focus_acks: { acks: [] },
};
syncDailyFocusOverlay(data);
// Soft-reload clobber simulation: replace hub with pristine open tasks, re-sync.
data.daily_focus = {
  ...base,
  tasks: base.tasks.map((t) => ({ ...t, closed: false })),
};
syncDailyFocusOverlay(data);
const row = dailyRecRowState("rec-aaa");
rememberPendingDailyDiscuss({ recommendation_id: "rec-bbb", local_date: "2026-09-28" }, "queued");
const discussRow = dailyRecRowState("rec-bbb");
// Durable catch-up prunes pending.
data.daily_focus_acks = {
  acks: [{
    task_ref: "focus-2",
    recommendation_id: "rec-aaa",
    decision: "accept",
    status: "open",
    local_date: "2026-09-28",
  }],
};
dailyFocusBase = {
  ...base,
  tasks: [
    { task_ref: "focus-2", recommendation_id: "rec-aaa", closed: true },
    { task_ref: "human:task-x", recommendation_id: "rec-bbb", closed: false },
  ],
  closed_today: ["focus-2"],
};
prunePendingDailyAcceptsAgainstDurable(data);
console.log(JSON.stringify({
  overlaidClosed: overlaid.tasks.map((t) => !!t.closed),
  openRefs: open.map((t) => t.task_ref),
  syncedClosed: data.daily_focus.tasks.map((t) => !!t.closed),
  acceptDisabled: row.acceptDisabled,
  discussDisabledAfterAccept: row.discussDisabled,
  discussQueuedAcceptDisabled: discussRow.acceptDisabled,
  discussQueuedDiscussDisabled: discussRow.discussDisabled,
  pendingAfterPrune: Object.keys(pendingDailyAccepts),
}));
"""
    )
    payload = json.loads(check_output(["node", "-e", script], text=True))
    assert payload["overlaidClosed"] == [True, False]
    assert payload["openRefs"] == ["human:task-x"]
    assert payload["syncedClosed"] == [True, False]
    assert payload["acceptDisabled"] is True
    assert payload["discussDisabledAfterAccept"] is True
    assert payload["discussQueuedAcceptDisabled"] is False
    assert payload["discussQueuedDiscussDisabled"] is True
    assert payload["pendingAfterPrune"] == []


def test_illumination_chips_prefer_amber() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    assert "function renderIllumChips(" in text
    assert "illum-attn" in text
    assert "illum-new" in text
    assert "badge-watch" in text
    assert "badge-buy" in text
    # Amber-over-green rule documented in helper
    chip_fn = text.split("function renderIllumChips(", 1)[1].split(
        "\nfunction renderAutomationSubnav", 1
    )[0]
    assert "attention" in chip_fn
    assert chip_fn.index("attention") < chip_fn.index("new_info")


def test_sidecars_include_daily_hub_artifacts() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    assert '["daily_focus", "data/daily_focus.json"]' in text
    assert '["ui_state_reconciliation", "data/ui_state_reconciliation.json"]' in text
    assert '["daily_focus_acks", "data/daily_focus_acks.json"]' in text
    assert '["daily_discuss_inbox", "data/daily_discuss_inbox.json"]' in text
    assert '["daily_hub_history", "data/daily_hub_history.json"]' in text


def test_daily_hub_history_session_and_status_chips() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    assert "function renderDailyHubHistorySession(" in text
    assert "function renderDailyHubStatusChips(" in text
    assert "function isDailyHubStale(" in text
    assert "function londonLocalDate(" in text
    assert "Accept followed" in text
    assert "Discuss resolved" in text
    assert "Accept-streak hint" in text
    assert "Ready to progress" in text or ">Ready<" in text
    assert "daily-hub-history" in text
    assert "daily-hub-today" in text
    panel = text.split("function renderDailyHubPanel(", 1)[1].split(
        "\n/** Canonical Project-chat pickup phrase", 1
    )[0]
    assert "renderDailyHubHistorySession(data)" in panel
    assert "isDailyHubStale(hub)" in panel
    assert "counts.market_warnings" in panel
    assert "Market warning triage" in panel
    css = STYLES.read_text(encoding="utf-8")
    assert ".daily-hub-history" in css
    assert ".daily-hub-accept-streak" in css


def test_daily_hub_market_warning_triage_badges() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    card = text.split("function renderDailyHubTaskCard(", 1)[1].split(
        "\nfunction renderDailyHubPanel(", 1
    )[0]
    assert "triage_action" in card
    assert "prefer_discuss" in card
    assert "no dismiss" in card
    assert "badge-sell" in card
    html = Path("docs/index.html").read_text(encoding="utf-8")
    assert "app.js?v=daily-hub-warning-triage1" in html
    assert "Market warning triage" in OPS_MONITOR.read_text(encoding="utf-8")
    assert "zero_body_stuck" in OPS_MONITOR.read_text(encoding="utf-8")


def test_overview_pulse_links_daily_hub() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    assert "function renderDailyHubPulseStrip(" in text
    assert "Open daily hub" in text
    overview = text.split("function renderOverview(data)", 1)[1].split(
        "\nfunction renderLearningCompletenessCard", 1
    )[0]
    assert "renderDailyHubPulseStrip(data)" in overview
    pulse = text.split("function renderDailyHubPulseStrip(", 1)[1].split(
        "\nfunction renderOverview(", 1
    )[0]
    assert "isDailyHubStale(hub)" in pulse
    assert "candidates" in pulse


def test_css_automation_subnav_and_daily_rec() -> None:
    css = STYLES.read_text(encoding="utf-8")
    assert ".automation-subnav" in css
    assert ".illum-chip" in css
    assert ".daily-rec-block" in css
    assert ".daily-hub-pulse" in css


def test_ops_runbook_documents_daily_hub() -> None:
    ops = OPS_MONITOR.read_text(encoding="utf-8")
    assert "## Daily hub" in ops
    assert "#automation/daily" in ops
    assert "Europe/London" in ops
    assert "04:00" in ops
    assert "02:30 UTC" in ops
    assert "daily_hub_history.json" in ops
    assert "daily_hub_local_date_matches_today" in ops
    assert "## UI state reconciliation" in ops
    assert "UI state reconciliation drift" in ops
    bridge = BRIDGE.read_text(encoding="utf-8")
    assert "daily-focus-ack" in bridge
    assert "daily-discuss" in bridge


def test_ops_monitor_early_cron_and_gate() -> None:
    wf = Path(".github/workflows/ops-monitor.yml").read_text(encoding="utf-8")
    assert 'cron: "30 2 * * *"' in wf
    assert 'cron: "45 7 * * *"' in wf
    assert "hour >= 6" in wf
    cron = Path("scripts/import_cron_jobs.py").read_text(encoding="utf-8")
    assert 'key="ops-monitor-early"' in cron
    assert "hours=[2]" in cron
    assert "minutes=[30]" in cron
    commit = Path("scripts/gha_commit_ops_monitor.sh").read_text(encoding="utf-8")
    assert "docs/data/daily_hub_history.json" in commit
