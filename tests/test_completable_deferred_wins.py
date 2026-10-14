"""Static checks for completable deferred dashboard wins (L271/L376/L406/L453/L469/L486/L548)."""

from __future__ import annotations

from pathlib import Path

APP_JS = Path("docs/app.js")
STYLES = Path("docs/styles.css")
ARCHITECTURE = Path("docs/architecture.md")


def test_l271_fragment_glossary_in_architecture() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    assert "Glossary: “fragment”" in text or 'Glossary: "fragment"' in text
    assert "Deferred scratch" in text
    assert "Keyword substring" in text
    assert "Action-note prose" in text
    assert "Ingest utilization unit" in text


def test_l376_lifecycle_ticker_opens_memo() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    assert "function findResearchMemo(" in text
    assert 'data-lifecycle-open-memo="' in text
    assert "Read memo" in text
    assert "openMemo(memo)" in text


def test_l406_pr_fix_common_issues_on_ops() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    assert '["pr_fix_occasions", "data/pr_fix_occasions.json"]' in text
    assert "function renderPrFixCommonIssuesPanel(" in text
    assert "renderPrFixCommonIssuesPanel(data)" in text
    assert "pr-fix-common-issues" in text
    css = STYLES.read_text(encoding="utf-8")
    assert ".pr-fix-common-issues" in css


def test_l453_regime_wow_delta_highlighting() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    sunday = text.split("function renderSundayReview(", 1)[1].split(
        "\nfunction renderAnalysis(", 1
    )[0]
    assert "regimeDeltaSpan" in sunday
    assert "regime-unchanged" in sunday
    assert "regime-changed" in sunday
    assert "week-over-week" in sunday
    css = STYLES.read_text(encoding="utf-8")
    assert ".regime-unchanged" in css
    assert ".regime-delta" in css


def test_l469_collapse_shared_experiment_start_chips() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    assert "function lifecycleExperimentGroupKey(" in text
    assert "function lifecycleCollapsedExperimentChip(" in text
    assert "lifecycle-exp-collapsed" in text
    assert "lifecycle-exp-siblings" in text
    assert "Collapse shared-experiment Start chips" in text


def test_l486_performance_and_screener_subnav() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    assert 'PERFORMANCE_SECTION_IDS = ["signals", "sim", "historical"]' in text
    assert "function renderPerformanceSubnav(" in text
    assert "function syncPerformanceHash(" in text
    assert 'data-performance-section="' in text
    assert 'aria-label="Performance sections"' in text
    assert "function renderScreenerSubnav(" in text
    assert "function syncScreenerHash(" in text
    assert 'data-screener-filter="' in text
    assert 'aria-label="Screener signal filters"' in text
    parse_fn = text.split("function parseDashboardHash()", 1)[1].split(
        "\nfunction syncLifecycleHash", 1
    )[0]
    assert 'tab === "performance"' in parse_fn
    assert 'tab === "screener"' in parse_fn
    css = STYLES.read_text(encoding="utf-8")
    assert ".performance-subnav" in css
    assert ".screener-subnav" in css


def test_l548_scoreboard_primary_dual_suite_retired() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    assert "function renderAssessmentScoreboardPanel(" in text
    assert "learning-tracks-dual-suite-archive" in text
    tracks_fn = text.split("function renderLearningTracksPanel(", 1)[1].split(
        "\nconst AUTOMATION_SECTION_IDS", 1
    )[0]
    assert "Legacy Suite A/B track tables" in tracks_fn
    assert "learning-tracks-dual-suite-archive" in tracks_fn
    # Suite tables should live inside the collapsed archive details.
    assert tracks_fn.index("learning-tracks-dual-suite-archive") < tracks_fn.index(
        "renderLearningTracksSuiteTable"
    )
