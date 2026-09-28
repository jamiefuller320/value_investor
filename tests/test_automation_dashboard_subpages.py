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


def test_overview_pulse_links_daily_hub() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    assert "function renderDailyHubPulseStrip(" in text
    assert "Open daily hub" in text
    overview = text.split("function renderOverview(data)", 1)[1].split(
        "\nfunction renderLearningCompletenessCard", 1
    )[0]
    assert "renderDailyHubPulseStrip(data)" in overview


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
    assert "## UI state reconciliation" in ops
    assert "UI state reconciliation drift" in ops
    bridge = BRIDGE.read_text(encoding="utf-8")
    assert "daily-focus-ack" in bridge
    assert "daily-discuss" in bridge
