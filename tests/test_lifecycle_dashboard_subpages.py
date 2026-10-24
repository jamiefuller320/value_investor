"""Lifecycle tab splits Positions board vs Maturity mix (L463) onto sub-pages."""

from __future__ import annotations

from pathlib import Path

APP_JS = Path("docs/app.js")
STYLES = Path("docs/styles.css")
OPS_MONITOR = Path("docs/ops/ops-monitor.md")
POSITION_LIFECYCLE = Path("docs/ops/position-lifecycle.md")


def _lifecycle_render_fn(text: str) -> str:
    return text.split("function renderLifecycle(", 1)[1].split("\nfunction bindLifecyclePanel", 1)[
        0
    ]


def test_lifecycle_subnav_and_hash_routes() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    assert "function renderLifecycleSubnav()" in text
    assert 'data-lifecycle-subpage="positions"' in text
    assert 'data-lifecycle-subpage="maturity"' in text
    assert 'aria-label="Lifecycle sections"' in text
    assert 'class="paper-subnav lifecycle-subnav"' in text
    assert 'history.replaceState(null, "", "#lifecycle/maturity")' in text
    assert 'lifecycleSubpage = "positions"' in text
    assert "function normalizeLifecycleSubpage(" in text
    assert "function parseDashboardHash()" in text
    # Backward-compatible market hashes still supported (no forced /positions/).
    sync_fn = text.split("function syncLifecycleHash()", 1)[1].split(
        "\nfunction applyDashboardHash", 1
    )[0]
    assert '"#lifecycle/maturity"' in sync_fn
    assert 'parts = ["lifecycle", lifecycleMarketId]' in sync_fn


def test_render_lifecycle_does_not_stack_maturity_on_positions() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    fn = _lifecycle_render_fn(text)
    assert "renderLifecycleSubnav()" in fn
    assert 'lifecycleSubpage === "maturity"' in fn
    assert "renderLifecycleMaturitySection(data)" in fn
    assert "lifecycle-board-section" in fn
    # Maturity and board are mutually exclusive branches — maturity call must
    # not sit in the same HTML template as the positions board card.
    maturity_if, _, after = fn.partition('lifecycleSubpage === "maturity"')
    assert maturity_if  # renderLifecycle starts before the maturity branch
    maturity_body, _, positions_body = after.partition("return;")
    assert "renderLifecycleMaturitySection" in maturity_body
    assert "lifecycle-board-section" not in maturity_body
    assert "renderLifecycleMaturitySection" not in positions_body
    assert "lifecycle-board-section" in positions_body


def test_maturity_subpage_keeps_trajectory_over_raw_counts() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    maturity_fn = text.split("function renderLifecycleMaturitySection(", 1)[1].split(
        "\nfunction queueLaneBadge", 1
    )[0]
    assert "observeFreshnessBadge(payload.surface_freshness)" in maturity_fn
    assert "observeTrajectoryBadge(traj)" in maturity_fn or "observe-primary-traj" in text
    assert "observe-stale-banner" in maturity_fn
    assert "Prefer trajectory" in maturity_fn or "prefer trajectory" in maturity_fn
    assert "beat_market" in maturity_fn
    assert "exit_shadow" in maturity_fn
    assert "observe utilization" in maturity_fn.lower() or "observe_utilization" in maturity_fn
    # Separation from analysis measures stays in the maturity payload path.
    assert "resolveLifecycleMaturity" in text
    assert "resolveObserveUtilization" in text
    assert text.index("function resolveLifecycleMaturity") != text.index(
        "function resolveObserveUtilization"
    )


def test_open_lifecycle_board_lands_on_positions() -> None:
    text = APP_JS.read_text(encoding="utf-8")
    open_fn = text.split("function openLifecycleBoard(", 1)[1].split(
        "\nfunction lifecycleStatusChip", 1
    )[0]
    assert 'lifecycleSubpage = "positions"' in open_fn


def test_lifecycle_subnav_reuses_paper_subnav_styles() -> None:
    css = STYLES.read_text(encoding="utf-8")
    assert ".lifecycle-subnav" in css
    assert ".paper-subnav" in css
    assert ".paper-subtab" in css


def test_ops_runbook_points_at_maturity_subpage() -> None:
    ops = OPS_MONITOR.read_text(encoding="utf-8")
    assert "Lifecycle → **Maturity mix**" in ops or "Lifecycle → Maturity mix" in ops
    assert "#lifecycle/maturity" in ops
    board = POSITION_LIFECYCLE.read_text(encoding="utf-8")
    assert "**Positions**" in board
    assert "**Maturity mix**" in board
    assert "#lifecycle/maturity" in board


def test_sealed_lifecycle_subpage_collates_observe_diagnostics() -> None:
    """Lifecycle → Sealed models collates companion + stages from observe SSoT."""
    text = APP_JS.read_text(encoding="utf-8")
    assert "function renderSealedLifecycle(" in text
    assert "function renderSealedLifecycleCollation(" in text
    assert "function renderSealedLifecycleExtras(" in text
    sealed_fn = text.split("function renderSealedLifecycle(", 1)[1].split(
        "\nfunction renderLifecycle(", 1
    )[0]
    assert "renderSealedLifecycleCollation(" in sealed_fn
    assert (
        "renderSealedLifecycleHeatBoard" in sealed_fn
        or "renderSealedLifecycleListBoard" in sealed_fn
    )
    collate_fn = text.split("function renderSealedLifecycleCollation(", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "renderInvestmentModelCompanionStrip(" in collate_fn
    assert "stagesOnly: true" in collate_fn or "stagesOnly:true" in collate_fn
    assert "data-sealed-observe-jump" in collate_fn
    assert "renderSealedLifecycleExtras(" in collate_fn
    # stagesOnly reuses the same monitor helpers (no divergent numbers).
    monitor_sig = text.split("function renderObserveLifecycleMonitor(", 1)[1].split("\n", 1)[0]
    assert "stagesOnly" in monitor_sig
    assert 'data-lifecycle-subpage="sealed"' in text
    assert "#lifecycle/sealed" in text or 'lifecycleSubpage = "sealed"' in text
    css = STYLES.read_text(encoding="utf-8")
    assert ".sealed-life-collation" in css
    assert ".sealed-life-stages" in css
    ops = OPS_MONITOR.read_text(encoding="utf-8")
    assert "collates companion" in ops.lower() or "collate" in ops.lower()
    board = POSITION_LIFECYCLE.read_text(encoding="utf-8")
    assert "Collated header" in board or "companion" in board.lower()


def test_post_sale_review_layout_scrolls_on_tablet() -> None:
    """Post-sale data card must not clip on iPad; dual charts stack ≤1180px."""
    css = STYLES.read_text(encoding="utf-8")
    app = APP_JS.read_text(encoding="utf-8")
    html = Path("docs/index.html").read_text(encoding="utf-8")
    ops = Path("docs/ops/post-sale-review-queue.md").read_text(encoding="utf-8")

    assert "function renderPostSaleReviews(" in app
    assert "function renderPostSaleDialogue(" in app
    assert "post-sale-review-section" in app
    assert "psr-dual-charts" in app
    assert "psr-card-detail" in app
    assert "psr-dialogue" in app
    assert "psr-learning-points" in app
    assert "chart_annotations" in app
    assert "mountDualHorizonCharts" in app
    assert "Durable history" in app

    # Do not inherit lifecycle-board overflow:hidden clip on this surface.
    assert ".post-sale-review-section.lifecycle-board-section" in css
    section_rule = css.split(".post-sale-review-section.lifecycle-board-section", 1)[1].split(
        "}", 1
    )[0]
    assert "overflow: visible" in section_rule
    assert "safe-area-inset" in section_rule

    detail_rule = css.split(".psr-card-detail", 1)[1].split("}", 1)[0]
    assert "overflow-x: auto" in detail_rule
    assert "overflow-y: auto" in detail_rule
    assert "-webkit-overflow-scrolling: touch" in detail_rule
    assert "overscroll-behavior: contain" in detail_rule

    chart_rule = css.split(".psr-chart", 1)[1].split("}", 1)[0]
    assert "overflow-x: auto" in chart_rule
    assert "-webkit-overflow-scrolling: touch" in chart_rule

    dual = css.split(".psr-dual-charts {", 1)[1].split("}", 1)[0]
    assert "minmax(0, 1fr)" in dual

    assert "@media (max-width: 1180px)" in css
    tablet = css.split("@media (max-width: 1180px)", 1)[1].split("}", 2)[0]
    assert ".psr-dual-charts" in tablet
    assert "minmax(0, 1fr)" in tablet

    assert "viewport-fit=cover" in html
    assert "styles.css?v=" in html
    assert "Tablet / iPad layout" in ops or "iPad" in ops
