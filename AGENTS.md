# Agent instructions — FTSE Value Investor

## Project objective

Ultimate goal: a **self-improving automated global value portfolio**.  
Interim goal: **high-quality prompts / decision packs** for manual verification and trade actions.

North-star stages and the “richness before breadth on the live path” rule are in [`docs/PROJECT_OBJECTIVE.md`](docs/PROJECT_OBJECTIVE.md). Pipeline and data-model reference: [`docs/architecture.md`](docs/architecture.md). Keep the live screener on FTSE 350 until stage 4; grow other markets via `ftse-library` offline.

## Spend priorities (now)

Prefer work that serves these two, in order. Anything else should be parked with `ftse-defer`, not started.

1. **P1 — Live-path utilization.** Change what a weekday paper-auto / AI-judgment pass can see: filings, FCF basis, overlay bind, memo recency on FTSE holdings and buy-tier. Extra FTSE ingest on a green buy-tier, new paper tracks, and live universe expansion are factory, not foundation.
2. **P2 — Offline ingest cascade.** Serialize one market at a time to the **maintenance ingest threshold** (`sprint_ingest_complete`: raw parity or leftover thin/IWB parked). Fat slot on that head; spare streams front-start the next queue names and **auto-advance** when a spare graduates (today: `tsx60` / `ftse_smallcap`). When the head graduates, shift the fat slot and give the graduated market **equivalent resource** (FTSE-volume maintenance + epoch-0 `buy_tier_level` + equal-support near-miss / counterfactual archives). Admitted now: `sp500`, `asx200`. Do **not** pause spare auto-advance; watch shared runner capacity (job timeouts, source rate limits, L323) as more markets join maintenance. Do **not** fork shard AI-judgment or `decision-review --apply` until those books have marks. Do **not** add a fourth equal sprint stream that can starve the current head. See [`docs/ops/market-sharded-learning.md`](docs/ops/market-sharded-learning.md#what-enter-learning-means).

See [`docs/ops/market-sharded-learning.md`](docs/ops/market-sharded-learning.md) and [`docs/ops/euro-depth-sprint.md`](docs/ops/euro-depth-sprint.md).

## Dialogue → instrument (working style)

Open question / dialogue is the preferred way to turn loose ideas into system
changes. Keep this loop:

1. **Pin the learning question** before building (what must this prove or
   disprove?).
2. **Prefer one instrument** — often observe-only — over a stack of live tracks.
3. **Freeze markers / capital epoch** explicitly (widest window, documented twin,
   readiness gate). Mid-flight silent rewrites of live books are not OK.
4. **Park the rest** with `ftse-defer` so chat does not become the backlog.

Also keep:

- **Separate ID, timing, and capital-path questions** — do not collapse them into
  one NAV line or one track.
- **Twins over edits** for capital-policy experiments (e.g. deposits): new cold
  start / epoch, not toggling the recycling book mid-flight.
- **Do not back-label** prior NAV or marks as evidence for a new dual-path /
  deposit / sleeve design.
- **Readiness before promotion** — thick closed cohorts / stated gates before
  treating an experiment as adoption truth.
- **Not every good idea is a live track** — shadows, archives, and deferred
  entries are first-class outcomes of a good dialogue turn.

Spend priorities (P1/P2), clash-aware eng capacity, and “new agent session after
a long multi-topic chat” still apply; this section is about *how* ideas enter
the system, not *what* to work on first.

## Full automation wiring (required)

**Any new component must be fully wired into automation so findings are usable** —
not shipped as CLI / manual-only. Minimal bar (detail:
[`docs/ops/ops-monitor.md`](docs/ops/ops-monitor.md#full-automation-wiring)):

1. **Scheduled trigger** — usually daily ops-monitor `collect_ops_findings` (or a
   named workflow with cron); not “run when someone remembers.”
2. **Persisted finding** — lands in committed `docs/data/ops_status.json` with a
   stable title, severity, and category.
3. **Runbook mention** — named in `docs/ops/ops-monitor.md` (or a sibling
   instrument doc linked from there).
4. **CLI optional** — for ad-hoc drill-down only; never the sole path.

**Lanes:** observe / warn-only → `auto_fixable=False` (email/PM handoff; no
rememo / ingest / eng spray from the finding alone). Auto-fixable →
`auto_fixable=True` plus a safe heal path (or documented supervised draft).
Optional beyond the bar (defer unless needed): ops-monitor commit of raw
instrument store JSON (**L460**). Instrument-specific observe-utilization
dashboard with freshness + trajectory is shipped (**L461**).

## Post-run persistent weaknesses & intensive clearance (required)

The Analysis tab **Post-run improvement review** (`docs/data/latest.json` →
`post_run_review`) includes a **Persistent weaknesses** section that rolls up
hundreds of accumulated gap-fill / model suggestions into **themes**. It is **not**
an engineering backlog and must **not** be executed as “fix every bullet.”

**Canonical policy:** [`docs/ops/post-run-improvement-clearance.md`](docs/ops/post-run-improvement-clearance.md)

When a user or task asks to “clear persistent weaknesses,” “intensively fix post-run
findings,” or similar:

1. Read that policy and follow the **three-lane model** (ingest factory → engineering
   queue → narrative refresh).
2. Align work to **P1** (FTSE buy-tier bodies, FCF basis, overlay bind, memo recency)
   then **P2** (focus ingest sprint). Defer the rest with `ftse-defer`.
3. Use **existing batching** — ingest-loop + gap-closure pins, `so-what --apply`,
   compile-cap drain, narrow eng splits, clash-aware max **2** agents — never a
   parallel “clearance queue” or one PR per ticker for shared scoring gaps.
4. After merges with **idle queue**, refresh narrative via
   [`docs/ops/accelerated-review-cycle.md`](docs/ops/accelerated-review-cycle.md)
   (`email_only`) when plan lines still match merged tasks.

Automation runs **`ftse-engineering run-post-run-clearance --apply`** after each new
post-run review (Sunday email bundle and analysis-review follow-up). See
`docs/data/post_run_clearance.json` → `last_run`.

**Do not** widen rememo for thin memos without new filing bodies (system_gaps remedy:
ingest then body-lag rememo). Off-buy-tier zero-filing memos stay parked (**N138**)
until the revisit trigger there.

## Parked / later ideas (required)

When you give advice that is **not relevant now** or **potentially useful later** (deferred features, premature ideas, “revisit when…”, out-of-scope enhancements), **append it to the deferred-ideas store before ending the turn**:

```bash
ftse-defer add \
  --category later|not_now|security|both \
  --title "Short title" \
  --summary "One or two sentences" \
  --revisit-when "Concrete trigger for revisiting" \
  --section learning|universe|research|ops|not_now|security \
  --tags "comma,separated" \
  --source "https://cursor.com/agents/<bcId> or conversation topic"
```

Rules:

1. Call `ftse-defer add` for each distinct parked idea (the CLI dedupes by title).
2. Prefer `--category not_now` when explicitly advising against starting now; `--category later` for future enhancements.
3. Always regenerate is automatic on `add`; use `ftse-defer render` only if you edited `docs/deferred-ideas.json` by hand.
4. Do **not** hand-edit `docs/deferred-review.md` — it is generated from `docs/deferred-ideas.json`.
5. If several ideas appear in one answer, add each separately.

For thoughts **not ready** for a full defer entry (no clear revisit trigger yet), use a scratch fragment:

```bash
ftse-defer fragment --text "Half-formed observation" --tags "comma,separated" --source "…"
```

Monthly `ftse-horizon-scan` clusters open fragments and may suggest PROMOTE/DROP — see [`docs/ops/horizon-scan.md`](docs/ops/horizon-scan.md).

Human-readable review page: [`docs/deferred-review.md`](docs/deferred-review.md).

Prefer `ftse-defer list` (and `add` / `fragment`) over reading `docs/deferred-ideas.json` or `docs/deferred-review.md` during unrelated work. Open those files only when the task is about the deferred store itself.

## Codebase inspection (token efficiency)

Bulk artifacts under `docs/data/` dominate token spend when agents Grep the whole tree. Defaults:

1. **Do not** run repo-wide Grep / Glob / explore over:
   - `docs/data/library/`
   - `docs/data/research/`
   - `docs/data/charts/`
   - `docs/data/archive/`
   - `docs/data/history/`
   - `docs/data/research_director_worker/`
   - `docs/data/paper_automation/`
   - `docs/data/latest.json`
2. Scope searches to `src/`, `tests/`, `.github/`, `docs/ops/`, or other code/docs paths.
3. When an ops task needs state, **Read a named file** (e.g. `docs/data/engineering_tasks.json`, `docs/data/automation.json`, `docs/data/ops_status.json`) — do not discover it via unbounded Grep under `docs/data/`.
4. Search bulk dirs only when the user or task explicitly requires that artifact.

Indexing: those bulk paths are listed in [`.cursorindexingignore`](.cursorindexingignore) so they stay out of default codebase search while remaining readable via Read / Shell when named. Do **not** put them in `.cursorignore` (that would block Agent Read / `@`).

Prefer a **new agent session** for a new major workstream after a long multi-topic chat (roughly 20–30 user turns), so context tax does not compound across unrelated PRs.

## PR fix occasion log (required)

When a human asks you to **fix failing PR checks** or a **blocked merge**, record the
occasion (with failure reason) before or while fixing:

```bash
ftse-project-traffic record-fix --pr <N> --kind ci_check|merge_conflict \
  --reason "<short failure reason>" [--failed-checks "CI / test,…"] [--notes "…"]
```

Traffic controller comments also append automatically. Review aggregates with
`ftse-project-traffic common-issues`. See [`docs/ops/project-traffic.md`](docs/ops/project-traffic.md#pr-fix-occasion-log).

## Human tasks checklist (required)

When you add or change a **manual** ops step (review gate, promotion checklist,
cadence item), update **both**:

- [`docs/human_tasks_checklist.json`](docs/human_tasks_checklist.json) — dashboard UI source
- [`docs/ops/human-tasks-checklist.md`](docs/ops/human-tasks-checklist.md) — human runbook

Run `pytest tests/test_human_tasks_checklist.py` after edits. See
[`.cursor/rules/human-tasks-checklist.mdc`](.cursor/rules/human-tasks-checklist.mdc).
