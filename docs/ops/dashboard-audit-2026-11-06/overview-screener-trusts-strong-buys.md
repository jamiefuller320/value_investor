# Dashboard tab audit — Overview, Screener, Trusts, Strong buys

Read-only audit of `/agent/repos/value_investor/docs/` static dashboard (`app.js` render paths).  
**Effective load path:** `reloadDashboard()` → `data/latest.json` then `applyDashboardSidecars()` merges `docs/data/*.json` sidecars (newer `generated_at` wins; `project_progress` sidecar is skipped when older than embed).

**Published screen snapshot:** `latest.json` `run_at` **2026-11-01** · bundle `generated_at` **2026-11-06**. Sidecars used at runtime may be newer than embeds (noted per row).

---

## Page header & data loading

| Tab > section | Render fn (line) | Data source | What it shows | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---|---|---|---|---|---|---|
| Header > run meta (`#run-meta`) | `renderDashboard` (14336) | `latest.json` → `meta.*`, `run_at`, `trust_reports` length | One-line universe label, company/trust/strong-buy counts, last screen run time | Run **2026-11-01**; published **2026-11-06** | No (auto-refresh on focus/visibility ~45s) | **FEEDER** | **Keep** — primary orientation; add strategy-book label when live route exists |
| (load) Dashboard bundle | `reloadDashboard` (1166) | `data/latest.json` | Full merged dashboard object | See above | Bridge/local `/api/refresh` on local serve | **FEEDER** | **Keep** |
| (load) Sidecar overlay | `applyDashboardSidecars` (1114) | `DASHBOARD_SIDECARS` list (593–628): `automation.json`, `project_progress.json`, `market_status.json`, `system_gaps.json`, `progress_report.json`, `chart_outcome_review.json`, `daily_focus.json`, `daily_hub_history.json`, `ui_state_reconciliation.json`, … | Overlays keys onto `data` after latest fetch | Per sidecar (below) | Same refresh | **OPS-META** | **Keep** — document which keys win over embed |

---

## Overview tab

| Tab > section | Render fn (line) | Data source | What it shows | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---|---|---|---|---|---|---|
| Overview > Daily hub | `renderDailyHubPulseStrip` (2490) | `daily_focus.json`, `ui_state_reconciliation.json`, `daily_hub_history.json` | Top focus lines, reconcile badge, link to Automation daily hub, 7d history counts | Focus **2026-11-06** (`local_date` 2026-11-06); reconcile **2026-11-06** ok | Link `#automation/daily` only | **OPS-META** / **HUMAN-TASK** | **Move** pulse to Automation tab; keep one-line link on Overview |
| Overview > Market status (grid) | `renderMarketStatusGrid` (2391) | `market_status.json` (overrides embed; embed dated **2026-11-01**) | Per-market tiles: ingest/learning chips, gate track, signal bar, sprint line, coverage/watch counts | Sidecar **2026-11-05** · **24** markets | Click tile → dialog; legend static | **DATA-P2** (+ **FEEDER** for live FTSE tile) | **Keep** on Overview for P2 head; demote jargon in legend |
| Overview > Market status > legend | `marketStatusBadgeLegend` (1743) | (static copy) | Explains ingest vs learning role vs gate pipeline | n/a | No | **DATA-P2** | **Keep** but rewrite for owner vocabulary (drop N94/L322 refs in tooltips elsewhere) |
| Overview > Market status > tile gate track | `renderLearningGateIndicator` (1768) | `market_status.json` → `markets[].learning_gate` | Start→Live gate stepper per market | **2026-11-05** sidecar | No | **DATA-P2** | **Keep** |
| Overview > Market status > tile sprint line | `sprintProgressLine` (1808) | `market_status.json` → `markets[].sprint_progress` | Recent ingest runs, gaps-to-admit, admission flags | **2026-11-05** | No | **DATA-P1** / **DATA-P2** | **Keep** |
| Overview > Market status (dialog) | `openMarketStatusCard` / `renderMarketStatusCard` (2226 / 2243) | Same row’s `markets[]` entry | Full market card: roles, epoch-0, near-miss, filing health, sprint card, blockers | **2026-11-05** | Dialog; **Open lifecycle board** button | **DATA-P2** | **Keep** detail in dialog; avoid implying epoch-0 paper = owner strategy book |
| Overview > Learning data completeness | `renderLearningCompletenessCard` (1989) | `latest.json` → `learning_data_completeness` (not a separate file) | Composite score + component bars (overlay, publish, memo bodies, gap penalty) | Assessed **2026-10-25** · score **98** | Runbook link | **DATA-P1** | **Keep** — aligns with F9-B input quality |
| Overview > Learning-path gaps | `renderSystemGapsCard` (2173) | `system_gaps.json` (sidecar **2026-11-01** overrides embed **2026-10-25**) | Flag tiles with severity; click for detail | **0** flags · assessed **2026-11-01** | Click → `#system-gaps-dialog` | **OPS-META** | **Keep** — integrity monitor, not backlog |
| Overview > System map | `renderSystemMapCard` (2100) | Derived: `project_progress.ingest_bottleneck`, `system_gaps`, `queue_health.json` | Pipeline diagram + Data/Investment/Platform pillars with stress badges | Stress inputs: queue **2026-11-06**; gaps **2026-11-01** | Doc links only | **OPS-META** | **Retire or rewrite** Investment pillar — still centers **Strand A / N200 observe**, not **owner-strategy-book-v0** |
| Overview > Operating companies (stat) | `renderOverview` (2581) | `latest.json` → `meta.company_count` | Count of screened operating names | **248** (run **2026-11-01**) | No | **FEEDER** | **Keep** |
| Overview > Strong buys (stat) | `renderOverview` (2585) | `latest.json` → `meta.strong_buy_count` | Strong-buy count only (not buy tier) | **17** | No | **FEEDER** | **Keep**; label “Buy tier” or link to Strong buys tab |
| Overview > Trust track (stat) | `renderOverview` (2589) | `latest.json` → `meta.trust_count` | Separate trust-universe count | **102** | No | **LEGACY-OBSERVE** / **FEEDER** | **Move** to Trusts tab only unless trusts stay in strategy |
| Overview > Last run (stat) | `renderOverview` (2594) | `latest.json` → `run_at`, `generated_at` | Screen run vs publish time | Run **2026-11-01** · pub **2026-11-06** | No | **FEEDER** | **Keep** |
| Overview > Progress report | `renderProgressReport` (205) | `progress_report.json` (not embedded in latest) | Headline, so-what human gates, lifecycle acks, defer/integration counts, generate/reload | **2026-09-30** (overall **warn**) — **stale** | Generate/reload/view report; Supabase bridge; optional PAT in **localStorage**; lifecycle **Acknowledge** | **OPS-META** / **HUMAN-TASK** | **Move** to Automation or collapse to link until regen cadence fixed |
| Overview > Progress report > So what? | `renderProgressReport` (369–392) | `progress_report.json` → `so_what.*` | Grouped human gates, auto-queue/observe counts, learning-path gap previews | **2026-09-30** | Runbook links | **HUMAN-TASK** | **Keep** content, **move** with progress report |
| Overview > Progress report > Lifecycle observe-acks | `renderProgressReport` (446–465) | `progress_report.json` → `lifecycle_acks` | Pending experiment acknowledgements (observe-only) | **2026-09-30** | **Acknowledge** → bridge API | **HUMAN-TASK** / **LEGACY-OBSERVE** | **Move** to Lifecycle tab |
| Overview > Progress report > Deferred & join-up (details) | `renderProgressReport` (494–507) | `progress_report.json` → `actionable`, `integration`, `role_coherence` | Deferred-now list, integration/role check previews | **2026-09-30** | `<details>` expand | **OPS-META** | **Keep** inside moved progress report |
| Overview > Project progress | `renderProjectProgress` (1514) | `latest.json` embed `project_progress` (sidecar older → embed wins) | Headline, appraisal lists, north-star stages | **2026-11-01** · focus **stage_2b** | `<details>` stages | **OPS-META** | **Keep** but shorten on Overview |
| Overview > Ingest bottleneck (alert) | `renderProjectProgress` (1541–1552) | `project_progress.ingest_bottleneck` when `stalled` | Stalled ingest alert with fixes/commands | Not stalled (`stalled: false`) — **hidden** | No | **DATA-P1** | **Keep** when stalled |
| Overview > Screen context (details) | `renderOverview` (2602–2620) | `latest.json` → `meta.signal_counts`, `meta.trust_signal_counts`, `run_diff` | Signal/trust distributions, week-over-week lists | `run_diff` **missing** → “No prior run” | `<details>` | **FEEDER** | **Keep**; fix publish of `run_diff` or remove WoW copy |
| Overview > Ingest health | `renderIngestHealth` (1581) | `latest.json` → `ingest_improvement` + `project_progress.ingest_bottleneck.health` | Buy-tier filing coverage, zero-body tickers, last ingest pass | `ingest_improvement` **missing**; health snapshot in embed (**buy_tier 67**) | No | **DATA-P1** | **Keep** — core P1 surfacing |

---

## Screener tab

| Tab > section | Render fn (line) | Data source | What it shows | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---|---|---|---|---|---|---|
| Screener > signal filters (subnav) | `renderScreenerSubnav` (2707) | `latest.json` → `reports[]` (counts by `signal`) | All / Strong buy / Buy / Hold / Avoid / Insufficient counts | **248** rows · run **2026-11-01** | Filter buttons; updates `#screener/{filter}` hash | **FEEDER** | **Keep** — primary cheapness screen |
| Screener > search | `renderScreener` (2743) | Same `reports[]` | Client filter by name/ticker/sector | **2026-11-01** | Search input | **FEEDER** | **Keep** |
| Screener > companies table | `renderScreener` / `renderRows` (2736 / 2768) | `latest.json` → `reports[]` fields: `signal`, `timing_signal`, `rsi_14`, models/families, `conviction_score`, `summary`, research overlay | Full FTSE operating-company screen with timing and conviction | **2026-11-01** | **Chart** button (buy/strong_buy); filters | **FEEDER** | **Keep**; add badges for operating-decline / sector gates when published |
| Screener > Chart (modal) | `bindChartButtons` + `charts.js` | `reports[]` + chart paths under `docs/data/charts/` (not opened in audit) | Price chart for ticker | Chart store not audited | Button | **FEEDER** | **Keep** |

---

## Trusts tab

| Tab > section | Render fn (line) | Data source | What it shows | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---|---|---|---|---|---|---|
| Trusts > intro | `renderTrusts` (2662) | (static) | Explains closed-end / IT screen separate from Graham operating models | n/a | No | **LEGACY-OBSERVE** | **Keep** disclaimer |
| Trusts > results table | `renderTrusts` (2627) | `latest.json` → `trust_reports[]` | Trust name, signal, models passed, key metrics, summary | **102** rows · run **2026-11-01** | No | **LEGACY-OBSERVE** | **Retire or defer** unless owner strategy includes ITs; not in 2026-11-03 equity book |

---

## Strong buys tab

| Tab > section | Render fn (line) | Data source | What it shows | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---|---|---|---|---|---|---|
| Strong buys > Chart outcomes since recommendation | `renderChartOutcomeReview` (2843) | `chart_outcome_review.json` | Observe-only path labels (well timed, underwater, terrible, etc.) on frozen buy-tier entries | **2026-11-01** · verdict **has_terrible** | Ticker buttons → chart (full tab) | **LEGACY-OBSERVE** | **Move** to Analysis/Performance; disclaimer is good — keep off “action” tab or collapse |
| Strong buys > helper (T212 unavailable) | `renderStrongBuys` (2991) | (static) | Explains Unavailable watch behaviour | n/a | No | **HUMAN-TASK** | **Keep** |
| Strong buys > Strong buys (cards) | `renderStrongBuys` (2927 / 2951) | `latest.json` → `reports[]` where `signal===strong_buy` minus `IIUnavailable` local watch | Pick cards: signal, timing, T212 badge, conviction, action note, **trade plan**, **decision pack**, summary | **17** strong · run **2026-11-01** | Chart, **Log action**, **Unavailable** | **FEEDER** | **Keep** as feeder shortlist; relabel as “Buy-tier candidates” not “the book” |
| Strong buys > Buys (cards) | same | `reports[]` `signal===buy` | Same card shape for buy tier | **48** buys | Same buttons | **FEEDER** | **Keep** |
| Strong buys > Watched — unavailable to trade | `renderStrongBuys` (2966) | **localStorage** `ftse_ii_unavailable_watch_v1` seeded from `latest.json` → `unavailable_watch` | Bypassed names still monitored | Server seed present; browser-local | Restore / chart | **HUMAN-TASK** | **Keep** |
| Strong buys > Log action | `renderStrongBuys` (3002) | Routes to Portfolio dialog / tab | Manual trade logging | n/a | Button → `portfolio.js` | **CONTROL** / **HUMAN-TASK** | **Keep** until strategy-book actions replace generic portfolio log |

---

## Observations

### Duplication
- **Strong-buy signal** appears on Overview stat, Screen context, Screener filters/table, and Strong buys cards — four surfaces for the same `reports[]` slice.
- **Market filing / ingest health** overlaps Overview **Ingest health**, **Market status** tiles/dialog, and **Learning data completeness** components.
- **Progress report** vs **Project progress** both carry headlines, focus stage, and engineering/defer narrative.

### Jargon / codenames (owner-unfriendly)
- **Strand A**, **N200/N201**, **epoch-0**, **L322**, **F8/F9-B**, **sprint_ingest_complete**, **IWB**, **ftse-screen** pipeline codenames in **System map** and market tooltips.
- **II / T212** tradability badges (`iiTradabilityBadge`, 71) — venue-specific; strategy book is capital-route agnostic.
- **Screen:strong_buy / overlay:** strategy strings in charts elsewhere; screener shows **families_passed** without plain-English “fundamental cheapness gate”.
- Tab title **FTSE Value Investor** vs header **FTSE 350** universe.

### Stale or empty
- **`progress_report.json` ~2026-09-30** while daily ops data is **2026-11-06** — Overview “Progress report” misleads if taken as current.
- **`run_diff` absent** — “Week-over-week changes” always empty/muted despite fresh publish.
- **Screen `run_at` 2026-11-01** vs **`generated_at` 2026-11-06** — five-day lag on company signals; header does not show publish age prominently.
- **`learning_data_completeness` assessed 2026-10-25** while **`system_gaps` sidecar 2026-11-01** — composite may not reflect latest gap pass (score still 98 / 0 flags).

### Strategy misalignment (2026-11-03/04 owner book)
- **No `strategy_book_registration` / owner-strategy-book-v0** surfacing in these tabs; **System map** still describes **Strand A + N200 observe** as the Investment pillar — reads as the live capital story.
- **Strong buys + trade plan** show legacy **tactical stop/target** lines (`tradePlanHtml`, 90) — not the **+10% checkpoint ladder**, **63-session recovery hold**, or **thesis-break** exits; can imply old trade-plan semantics are the strategy.
- **Operating-decline** and **sector headwind** gates (`operating_decline_gate.json`, `sector_headwind_gate.json`) are **not** shown on Screener or Strong buys — buy tier alone is visible.
- **Chart outcome review** on Strong buys tab is explicitly observe / not paper excess — good disclaimer — but placement next to action cards still feels like a **performance grade**.
- **Trusts tab** is a parallel asset class screen — not part of the stated operating-company strategy book.
- Nothing in scope mentions **top-N ranking exit** as exit (good); watch that **Portfolio** “Log action” and paper paths (out of scope) are not implied here as the main book.

### Data-loading notes
- Sidecar **`market_status.json` (2026-11-05)** replaces older embed in **`latest.json` (2026-11-01)** — Overview market grid is fresher than screener rows until the next **`ftse-publish`** screen run.
- **`project_progress.json` sidecar (2026-09-30)** is intentionally **not** applied over newer embed (**2026-11-01**).

---

*Audit generated 2026-11-06 (UTC). Read-only; no repo files modified.*
