# Dashboard v2: audit and realignment plan

Written 2026-11-06 after a content audit of the dashboard against the owner's
[investment strategy](../PROJECT_OBJECTIVE.md#investment-strategy-owner-2026-11-03)
and the [single track to live](strategy-reorientation-plan.md#single-track-to-live-owner-2026-11-04).
Status: **approved by the owner 2026-11-06** (human task
`adhoc-dashboard-v2-plan`). Build progress is in [section 8](#8-status).

Strategy part served: all of them. The dashboard is the owner's window onto
the strategy book. Plan step 2.3 already asks for a "dashboard strip"; this plan
is the larger version of that strip.

Row-level inventories (every section, render function, data source, freshness,
tag) are in [`dashboard-audit-2026-11-06/`](dashboard-audit-2026-11-06/). They
are the checklist for "nothing useful is lost".

## 1. What the audit found

The dashboard is a static GitHub Pages site under `docs/`: 9 tabs, about 200
visible sections, about 24,000 lines of front-end code (`app.js` alone is
14,400 lines). It was built instrument by instrument as the project grew, so
it is organised around instruments (Strand A, N200, N201, N206, N210, suites,
lenses) rather than around the strategy.

Each section was tagged by what it serves:

| Tag | Sections | Meaning |
|-----|----------|---------|
| Strategy book (parts 1–7, scoring) | **0** | — |
| Engineering and ops plumbing | ~45 | Queue lanes, monitors, settings, reconcile, PR fix log |
| Old paper books (controls) | ~41 | Strand A, learning tracks, Suite A/B, browser sandbox, £1k simulation |
| Feeders | ~35 | Screen buy tier, memos, chart outcomes, decision packs |
| Observe instruments with no strategy part | ~34 | N201/N206/N210 pages, cue-consumer lab, timing lenses, lifecycle experiments |
| Owner actions (acks, reviews, gates) | ~28 | Daily hub, human tasks, post-sale and entry-blind reviews |
| Input quality (P1) and ingest cascade (P2) | ~22 | Decision-input inventory, flip lag, market status, ingest health |

### Main findings

1. **The strategy book is invisible.** Nothing shows `owner-strategy-book-v0`,
   its seal, the thickness gate, episodes or proof bars. The operating-decline
   gate and sector headwind gate refresh daily (`operating_decline_gate.json`,
   `sector_headwind_gate.json`, both 2026-11-06) but appear nowhere; the
   Screener and Strong buys tabs show buy tier only.
2. **Some copy misstates the strategy.**
   - The Strand A companion strip labelled the paper book "live capital"
     (fixed in this PR: now "paper control").
   - The Overview system map describes the Investment pillar as Strand A and
     N200 observe.
   - Strong-buy cards show the old trade plan (tactical stop and target), not
     the strategy's exits (+10% launch, ratcheting floor, 63-session wait,
     thesis break).
   - Portfolio → Local sandbox rebalances on a top-conviction set, and its
     surveillance flags signal drift. Leaving a top-N set is not the
     strategy's exit.
   - Performance leads with the £1,000 screen-replay simulation and backtest
     buckets, which read as "how the strategy is doing".
3. **Paper performance appears in four places with four meanings:** Sunday
   review paper tracks (price-only), Automation → Tracks (total return),
   Performance → Simulation (archive replay), and the browser sandbox (local).
   The assessment scoreboard and the total-return panel are each rendered
   twice.
4. **Stale or empty content on the landing tab.** The Overview progress
   report is from 2026-09-30. The week-over-week screen diff (`run_diff`) is
   never published, so that block is always empty. Knob priors date from
   2026-08-23.
5. **The most important freshness fact is not shown.** Every market's charts
   stop at 2026-10-30, so the signal-day memo job records zero signals and a
   forward book could not run on fresh closes. The only place this shows is an
   ops finding.
6. **Codenames throughout:** Strand A/B, N200–N210, Suite A/B, F8/F9-B, L652,
   Q8B, B3, Cap B, epoch-0, IWB, matched-30. The owner has to know the
   [glossary](../glossary.md) to read most tabs.
7. **Write-back features that must survive any rebuild** go through the
   [dashboard bridge](dashboard-bridge.md): `human-task-ack`,
   `daily-focus-ack`, `daily-discuss`, the three `post-sale-review-*`
   actions, the three `entry-blind-review-*` actions, the three
   `entry-revisit-review-*` actions, and `lifecycle-experiment-ack` and
   `lifecycle-experiment-start`.

### Data the strategy page can use today

Detail: [`strategy-data-map.md`](dashboard-audit-2026-11-06/strategy-data-map.md).

| Need | Source | State on 2026-11-06 |
|------|--------|---------------------|
| Part 1 cheap | `latest.json` `reports[].signal`; `library_decision_input_inventory.json` | FTSE 65 buy tier; library 378 |
| Part 2 not declining | `operating_decline_gate.json` | FTSE buy tier: clear 53, declining 9, insufficient 3 |
| Part 3 sector sound | `sector_headwind_gate.json` | 211 sectors: sound 71, headwind 25, insufficient 115 |
| Input quality (F9-B) | `decision_input_inventory.json`, `library_decision_input_inventory.json` | FTSE 64 of 65 pass all four; library 33 of 378 (345 fail memo recency) |
| Seal | `strategy_book_registration.json` | Signed 2026-11-05; spend off |
| Memo job | `strategy_book_memo_job.json` | Idle: charts stale at 2026-10-30 |
| Parts 4–7, scoring | `strategy_book_replay.json` (+ gzipped episodes) | Only on open [PR #1311](https://github.com/jamiefuller320/value_investor/pull/1311): archive replay, three results that must not be averaged |
| Forward book | `strategy_book_forward_status.json`, `strategy_book_observe.json` | Writer on PR #1311; the observe store is written only once `forward_live` is true |
| Phase 3 proof bars | Seal text | Bars sealed; nothing measures them yet |

None of these stores are in `latest.json`. They are already valid Pages URLs
(`data/<file>.json`), so a new page can fetch them directly without changing
`ftse-publish`.

## 2. Recommendation: build v2 beside the old dashboard

Build a new page at `docs/v2/` and leave the current dashboard at the root
until the owner approves a cutover.

Why a new build rather than editing the current tabs:

- The current structure is the problem. Realigning in place would touch
  every tab of a 14,400-line file that other packages edit at the same time
  (PR #1311 adds a strategy-book section to it now).
- A separate page can be small and readable, organised by the strategy's
  questions, with plain-English labels from the start.
- Keeping the old page untouched keeps every engineering view, archive and
  write-back flow working while v2 grows. Nothing is lost by default; a
  section leaves the old page only by a recorded retirement decision.
- `pages.yml` already deploys all of `docs/`, so `docs/v2/index.html` is served
  at `/v2/` with no workflow change. It is a separate page, not a tenth tab
  (N167 stands).

v2 reuses the shared pieces rather than copying them: `charts.js` (price
charts), `dashboard_bridge.js` (write-back), the memo dialog, and the
`docs/data/*.json` stores. It does not load `app.js`.

## 3. v2 layout: one tab per owner question

| Tab | Owner question | Strategy part | Content | Data |
|-----|----------------|---------------|---------|------|
| **Today** | What needs me, and is the book healthy? | All | Book status strip (seal, forward live or not, closes age, thickness progress toward 48 counted mature episodes); owner decisions due (human tasks with Acknowledge/Approve); the day's push items from the Daily hub; one freshness line per input (charts, gates, memos, T212 catalogue) | Seal, forward status, `human_tasks_board.json`, `daily_focus.json`, store `generated_at` fields |
| **Candidates** | Which names could the book buy now, and why are the others out? | 1–4 | Per-market funnel: buy tier → not declining → sector sound → input quality → at a short-term low. A table with each check's verdict; expanding a row shows the cited reasons (decline checks, sector metrics, missing binds); price chart on demand | Gate stores and both inventories now; entry-low flag after G1 below |
| **Book** | What does the book hold and what happened to each trade? | 4–7 | Open episodes: waiting to launch (sessions left of 63), launched (checkpoint reached, current floor), review dates, recovery-hold share against the 40% line. Closed episodes split by how they ended: floor exit, sold at the 63-session wait, thesis break | `strategy_book_observe.json` once forward is live. Until then, the archive replay, labelled by result |
| **Proof** | Is it working, and how far from the bars? | Scoring | Thickness gate; median fair-cost episode %; median matched excess; the Phase 3 proof bars as a checklist ("not yet measured" until a writer exists); comparison exits; challenger bench; gate-rejected shadows; selection board; the buy-on-signal and leave-tier controls; one compact row each for the old paper books as outside controls | Replay boards, forward store, seal, `total_return_view.json`, `assessment_scoreboard.json` |
| **Reviews** | Which closed and new trades should I look at? | Step 2.4 | Post-sale reviews, entry-blind reviews and entry +28d reviews on strategy-book episodes, with the existing charts, pattern marks, drawing tools and bridge actions | Review queues once step 2.4 points them at the book |
| **Inputs** | Is the data behind the book good enough? | P1, P2 | F9-B binds (FTSE and library) with the names failing each; gate coverage gaps; memo job log; T212 catalogue age; chart freshness per market; compact market status for the ingest cascade | Inventories, gate summaries, memo job, `market_status.json`, `ops_status.json` findings |

A footer link, "Engineering and archive views", opens the old dashboard.

### Display rules for v2

1. **Plain English first.** No codename without a tooltip from the glossary.
   Labels say what a number is ("trades that reached +10%"), not its store key.
2. **Every number carries its date.** Each panel shows its source's
   `generated_at` or `as_of`, and turns amber or red past a stated age.
3. **Missing is shown as missing.** Absent data reads "not yet measured" or
   "insufficient data", never zero or a pass (the book's fail-closed rule).
4. **Replay results are never blended.** The three archive results (buy tier
   only, full strategy, today's gates painted back) are shown separately, each
   named, and the painted-back one says it uses gates dated after the trades.
5. **The book leads; controls sit beside it.** Old paper books appear only
   as comparison rows on the Proof tab, labelled as controls.
6. **Observe-only banner** on Book and Proof while `forward_live` is false.
7. **Read-only except the bridge actions** that already exist. v2 adds no
   new write paths in its first versions.

## 4. Nothing-lost ledger

What happens to each part of the old dashboard. "Legacy" means it stays on
the old page, reachable from the v2 footer, and is not ported.

| Old dashboard section | v2 destination | Note |
|------------------------|----------------|------|
| Header run meta, screen counts | Today | Plus strategy-book label |
| Overview → Daily hub pulse | Today | Push items and decisions only |
| Overview → Market status grid and dialog | Inputs (compact); full grid stays legacy | P2 view |
| Overview → Learning data completeness, ingest health | Inputs | P1 view |
| Overview → Learning-path gaps, system map | Legacy | System map needs rewriting before any port |
| Overview → Progress report, project progress | Legacy | Progress report stale since 2026-09-30 |
| Screener table, filters, chart | Candidates (buy-tier rows); full screen stays legacy | Full 248-row screen is a feeder view |
| Strong buys cards, decision pack, Log action, Unavailable watch | Candidates (row detail); legacy keeps cards | Old trade-plan levels shown only as "screen plan", not as exits |
| Trusts tab | Legacy | Not part of the strategy; owner decides its fate at cutover |
| Portfolio → Action log | Legacy until execution (step 5.1) | Manual log stays useful for real trades |
| Portfolio → Local sandbox | Legacy; retirement candidate | Top-N rebalance sandbox |
| Performance → Signal backtest, historical analysis, model attribution | Legacy | Screen-quality research, not book results |
| Performance → £1,000 simulation | Legacy; retirement candidate as a headline | Archive screen replay |
| Analysis → Observe (Strand A scoreboard, TR view) | Proof (one control row) | Full panels stay legacy |
| Analysis → Observe (N200–N210) | Legacy | N200 stays a running sealed unit; others await the freeze decision |
| Analysis → Sunday review, post-run review | Legacy | Ops narrative |
| Analysis → Chart outcomes | Candidates (entry-timing context) | Feeder for part 4 |
| Analysis → Research memos | Candidates (memo per row) and Inputs (memo age) | P1 |
| Automation → Daily hub, Human tasks | Today | Same bridge actions |
| Automation → Tracks | Legacy | Controls |
| Automation → Queue (P1 cards: flip lag, decision-input inventory) | Inputs | P1 |
| Automation → Queue (engineering lanes, merges, completion) | Legacy | Engineering |
| Automation → Queue (lab instruments, N201/N206/N210) | Legacy | Await the freeze decision |
| Automation → Ops, Settings | Legacy | Engineering |
| Lifecycle → Positions board, experiment chips | Legacy | Control board; experiment Start is not a strategy path |
| Lifecycle → Maturity mix, Sealed models | Legacy | Observe instruments |
| Lifecycle → Post-sale, Entry blind, Entry +28d reviews | Reviews | Re-keyed to strategy-book episodes at step 2.4; the old queues stay on legacy until then |

## 5. Data gaps (backend work v2 depends on)

| Gap | Needed for | Proposed owner |
|-----|------------|----------------|
| G1. Per-name "at a short-term low today" flag and a combined eligibility roster | Candidates | Forward job (PR #1311 line): add a `candidates` list to `strategy_book_forward_status.json` with each part's verdict |
| G2. Charts stale at 2026-10-30 in every market | Every tab | Close refresh on PR #1311 (`strategy_book_prices.py`); v2 shows the age loudly until fixed |
| G3. Forward episode store | Book, Proof | Exists in code; written once `forward_live` is set at the Phase 1 gate |
| G4. Phase 3 proof measurements | Proof checklist | Step 3.2 (N248); v2 shows the sealed bars as "not measured" until then |
| G5. T212 listing per name | Candidates, Proof (tradable subset) | FTSE rows carry `tradable_on_t212`; library names need a small per-name board from the catalogue |
| G6. Recovery-hold share over time | Book | Forward store should keep daily samples; the replay summary drops them |
| G7. Strategy-book review queues | Reviews | Step 2.4 (N222) |

v2 does not wait for these: each panel shows what exists and states what is
missing.

## 6. Work packages and models

Owner preference: plan-included models (Composer, Grok) wherever they can do
the job, as in the
[model allocation](strategy-reorientation-plan.md#model-allocation) of the
reorientation plan. The supervising agent writes each brief, reviews and
merges. At most two implementation agents at once. In the audit session
Composer accepted one run at a time; Grok and Composer can run side by side.

| Package | Deliverable | Depends on | Model |
|---------|-------------|------------|-------|
| WP0 | This audit and plan; old "live capital" badge fixed | — | Supervisor, with Composer 2.5 and Grok 4.7 for the inventories (done) |
| WP1 | v2 shell: `docs/v2/index.html`, `v2.css`, a small loader with a freshness helper; **Today** and **Inputs** tabs on existing stores; human-task Acknowledge through the shared bridge; footer link to legacy; a "Try the new strategy dashboard" link on the old header; cache-busting test like `tests/test_dashboard_cache_bust.py` | Owner approval | Composer 2.5 |
| WP2 | **Candidates** tab: client-side join of buy tier, decline gate, sector gate and both inventories per market; expandable reasons; chart on demand via `charts.js`. Entry-low column reads G1 when present, otherwise "pending forward job" | WP1 | Grok 4.7 (high) |
| WP3 | **Book** and **Proof** tabs on the replay summary and forward status: three replay results kept apart, thickness gate, exit-kind boards, bench, shadows, controls, Phase 3 checklist; gzipped episode table loaded on demand | WP1, PR #1311 merged | Grok 4.7 (high) |
| WP4 | G1 on the forward job (candidates list in the status store) | PR #1311 merged | Grok 4.7 (high) |
| WP5 | Ops wiring: add v2's stores and page to the UI reconciliation check in ops-monitor so a stale or broken v2 raises a finding; runbook line in `ops-monitor.md` | WP1 | Composer 2.5 |
| WP6 | **Reviews** tab: shared review-card module pointed at strategy-book episodes, reusing the existing bridge actions | Step 2.4 (N222) | Grok 4.7 (high) |
| WP7 | Cutover: if the owner approves, v2 becomes `docs/index.html` and the old page moves to `docs/legacy/`; per-section retirements recorded in the deferred store | Owner cutover decision | Composer 2.5 |

Each brief carries the hard constraints of the reorientation plan that apply
to UI work: observe-only (no new write paths), fail-closed display, no new
codenames without a glossary line, tests for each panel's empty and stale
states, `pytest` on touched tests and `ruff check` green.

## 7. Owner decisions

1. **Approve this plan** (scope, tab layout, the ledger), or change it.
   Approved 2026-11-06.
2. **Cutover** (`adhoc-dashboard-v2-cutover`), later: when v2's Today, Candidates, Book and Proof tabs run on
   the forward book for four weeks and every ledger row marked for v2 is
   ported, decide whether v2 becomes the root page. Decide the Trusts tab and
   the browser sandbox at the same time.

Both are in the [human tasks checklist](human-tasks-checklist.md#ad-hoc-when-triggered).

## 8. Status

| Package | Status | Branch / PR | Model |
|---------|--------|-------------|-------|
| WP0 | Merged 2026-11-06 | #1313 | Supervisor; Composer 2.5 and Grok 4.7 inventories |
| Plan approval | Owner approved 2026-11-06 | — | Owner |
| WP1 | Merged 2026-11-06 | #1318 | Composer 2.5 |
| WP4 | Merged 2026-11-06: forward status carries a per-name `candidates` roster (443 rows; sealed screen unchanged). Queued N257 (excluded names, version review) and L684 (snapshot signals gap) | #1318 | Grok 4.7 (high) |
| WP2 | Building in `docs/v2/candidates.js` (tab-module registry in `v2.js`) | `cursor/dashboard-v2-candidates-book-4306` | Grok 4.7 (high) |
| WP3 | Building in `docs/v2/book.js` and `proof.js` | `cursor/dashboard-v2-candidates-book-4306` | Grok 4.7 (high) |
| WP5 | Next, after WP2 and WP3 (two-agent limit) | — | Composer 2.5 |
| WP6 | Waiting on step 2.4 | — | — |
| WP7 | Waiting on the cutover decision | — | — |
