# Dashboard audit: Portfolio, Performance, Analysis (+ scoped Automation panels)

Audit date: 2026-11-06 (repo `docs/data/latest.json` `generated_at` **2026-11-06T06:01:17Z**). Sidecars merge at load (`applyDashboardSidecars`, `docs/app.js` ~1095–1145).

**Mount points:** `renderDashboard` → `renderPortfolio` (`docs/app.js` ~14367), `renderPerformance` (~14369), `renderAnalysis` (~14370). Portfolio body in `docs/portfolio.js`; paper sandbox in `docs/paper_sims.js`.

**Strategy book gap:** `owner-strategy-book-v0` (`docs/data/strategy_book_registration.json`) has **no dedicated tab/section** in this scope. UI still centres Strand A / learning tracks / observe seals.

Legend — **Tag:** STRATEGY-CORE | FEEDER | CONTROL | DATA-P1 | DATA-P2 | OPS-META | HUMAN-TASK | LEGACY-OBSERVE | UNCLEAR

---

## Tab: Portfolio

| Section (as shown) | Render fn (file:line) | Data source | Shows (one line) | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---|---|---|---|---|---|---|
| Sub-nav: **Action log** / **Local sandbox** | `renderPortfolio` (`portfolio.js:858–862`) | `latest.json` → `reports` (+ localStorage section key) | Switches between intent log and browser paper funds. | Section state: localStorage only | Tab buttons; hash not used | UNCLEAR | **Keep** split; rename sandbox “Legacy browser lab” |
| **Action log** → toolbar (Log / Seed / Export / Import / Book filter) | `renderPortfolio` (`portfolio.js:762–778`) | `reports`; actions in `localStorage` `ftseValueInvestor.portfolioActions.v1` | Manual trade-intent logging separate from server books. | Run: **2026-11-06** screen (`latest.generated_at`) | Buttons, file import, book filter select | HUMAN-TASK | **Keep** as manual execution log; wire strategy-book episodes later |
| **Diversification steer** | `renderPortfolio` (`portfolio.js:782–813`) | `latest.json` → `reports` (buy/strong_buy) | Sector weights, warnings, ranked next buys by conviction+diversity. | **2026-11-06** run | Chart/Log on candidates | FEEDER | **Move** under Screen/Decision pack or strategy-book “candidates”; demote as primary portfolio view |
| **Next diversified candidates** (table) | same | `reports` | Buy-tier names not already in open actions. | **2026-11-06** | Chart, Log | FEEDER | **Keep** as feeder shortlist helper |
| **Open actions** (table) | `renderPortfolio` (`portfolio.js:815–836`) | localStorage actions + `reports` for marks via `buildPriceMap` | Open intents with mark/P&L vs entry. | Marks: live fetch; screen **2026-11-06** | Status select, live/sim toggle, delete, enrich marks | HUMAN-TASK | **Keep** for live execution tracking |
| **Closed / cancelled** (table) | `renderPortfolio` (`portfolio.js:838–855`) | localStorage | Historical intent rows. | User-dependent | Status, delete | HUMAN-TASK | **Keep** archive |
| **Log action** (modal) | `renderActionDialog` (`portfolio.js:431+`) | `reports`, trade plans on report rows | Form to log limit/stop/target/qty. | **2026-11-06** | Modal form | HUMAN-TASK | **Keep** |
| **Local sandbox** → legacy banner | `renderPaperFundsSection` (`paper_sims.js:1547–1551`) | static copy | Warns browser sim ≠ server learning tracks. | n/a | none | LEGACY-OBSERVE | **Keep** disclaimer |
| **Paper fund simulations** (bootstrap) | `renderBootstrapCard` (`paper_sims.js:1358`) | localStorage empty | Create three parallel £ pots. | empty until user creates | Form submit | CONTROL | **Retire** or collapse behind “advanced”; conflicts with single-track-to-live |
| Sub-nav: **Overview** / **Immediate** / **Technical** / **Automated** | `paperSubnavHtml` (`paper_sims.js:1504`) | localStorage subpage | Nav between sandbox modes. | localStorage | Subtab buttons | CONTROL | **Retire** top-level tab placement; optional dev tool |
| **Simulation overview** (NAV table) | `renderOverviewPage` (`paper_sims.js:1382`) | `localStorage` `ftseValueInvestor.paperFunds.v1`; prices from `reports`/charts | Compare three browser funds’ NAV/return. | User-dependent | Deposits, refresh, export, reset, Open | CONTROL | **Retire** from main Portfolio; keep docs link only |
| Mode cards (Immediate / Technical / Automated) | `renderOverviewPage` (`paper_sims.js:1448–1458`) | static | Short intros + Go to controls. | n/a | Buttons | CONTROL | **Retire** with overview |
| **Immediate buy/sell** (mode page) | `renderModePage` (`paper_sims.js:1463`, manual) | localStorage fund + `reports` | Manual buy/sell, holdings, trades. | User + **2026-11-06** prices | Trade/deposit/refresh buttons | CONTROL | **Retire** public surface |
| **Follow technical cues** (mode page) | `renderModePage` (technical) | localStorage + `reports` + `buildTechnicalPlan` | Technical pass narrative, holdings, trades. | User + screen | Run technical pass | CONTROL | **Retire**; server technical track is Automation |
| **How the technical model decides** | `technicalNarrativeHtml` (`paper_sims.js:~989`) | plan object from candidates | Explains planned trades. | ephemeral | none | CONTROL | **Retire** with mode page |
| **Automated stock picking** (mode page) | `renderModePage` (automated) | localStorage + `reports` + `buildAutomatedPlan` | Auto rebalance sandbox. | User + screen | Run automated rebalance | CONTROL | **Retire** |
| **Independent daily automation** | `independentAutoControlsHtml` (`paper_sims.js:1224`) | localStorage settings + `latest.json` → `paper_automation` | Browser auto gate + server paper-auto last run note. | Server note **2026-11-05** (`paper_automation.generated_at`) | Form toggles (independent mode) | OPS-META | **Move** to Automation settings only |
| **How the automated model decides** | `automatedNarrativeHtml` (`paper_sims.js:~1281`) | plan | Planned rebalance explanation. | ephemeral | none | CONTROL | **Retire** |
| **Owned-stock surveillance** | `ownedSurveillanceHtml` (`paper_sims.js:1135`) | fund holdings + live actions localStorage + `reports` | Stop/target/timing alerts (includes **top-N style signal drift**). | **2026-11-06** screen | none (display) | FEEDER | **Move** to strategy-book risk panel; drop top-N exit framing |
| **Holdings** / **Recent trades** | `holdingsTableHtml` / `tradesTableHtml` (called from `renderModePage`) | localStorage | Position and trade history. | User | mode-specific actions | CONTROL | **Retire** with sandbox |

---

## Tab: Performance

Sub-nav: **Signals** | **Simulation** | **Historical** — `renderPerformanceSubnav` (`app.js:3599`), pane switch `renderPerformance` (`app.js:3625`).

| Section | Render fn (file:line) | Data source | Shows | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---|---|---|---|---|---|---|
| **Signal backtest** (card) | `renderPerformance` (`app.js:3758–3760`) | `latest.json` → `backtest` | Archived weekly signal buckets vs FTSE excess by horizon. | **30** archived runs (no `generated_at`; tied to archive thru **2026-11-01** window) | Subnav only | FEEDER | **Move** to Research/Archive; not strategy P&L |
| → Primary / secondary horizon tables | `renderPerformance` (`app.js:3634–3696`) | `backtest.horizons` | avg/benchmark/excess by signal. | same | none | FEEDER | **Keep** as screen quality diagnostic |
| → Noise check (7d) | `renderPerformance` (`app.js:3670–3690`) | `backtest.horizons` | Demoted short horizons. | same | `<details>` | FEEDER | **Keep** collapsed |
| **Portfolio simulation (£1,000)** | `renderPerformance` (`app.js:3766–3768`) | `latest.json` → `simulation` (+ track variants) | Historical rebalance sim (£528.67 final in current data). | **30** periods; archive window ends **2026-11-01** | Sim track subtabs; `localStorage` `perfSimTrack` | CONTROL | **Retire** as headline performance; label “archive screen replay” |
| → Track subtabs (Screen / Overlay / Static / Trailing / Momentum grace) | `renderPerformance` (`app.js:3727–3737`) | `simulation`, `simulation.research_overlay`, etc. | Per-track P&L table + holdings. | same | Track buttons | CONTROL | **Keep** collapsed archive only |
| → Compare all tracks | `renderPerformance` (`app.js:3741–3749`) | `simulation` | Side-by-side track metrics. | same | `<details>` | CONTROL | **Keep** archive |
| **Historical analysis** (card intro) | `renderPerformance` (`app.js:3774–3777`) | `latest.json` → `historical_analysis` | Explainer for replay analytics. | Window **2026-08-02 → 2026-11-01**, 30 runs | Subnav | FEEDER | **Move** out of owner-facing Performance |
| → Weekly excess charts (28d / 84d) | `renderWeeklySeriesChart` (`app.js:3046`) | `historical_analysis.weekly_series` | Smoothed weekly excess by screen/overlay strategies. | same | none | FEEDER | **Keep** research |
| → Strategy horizons tables (primary/secondary/noise) | `renderHistoricalAnalysis` (`app.js:3168–3258`) | `historical_analysis.strategy_horizons` | Smoothed excess for signal cohorts. | same | `<details>` for noise | FEEDER | **Keep** research |
| → Screen vs research overlay tables | `renderHistoricalAnalysis` (`app.js:3260–3312`) | `historical_analysis.overlay_comparison` | Overlay uplift on buy-tier. | same | details | FEEDER | **Keep** memo/overlay feeder |
| → **Model attribution** (primary/secondary/noise) | `renderModelAttributionPanel` (`app.js:3380`) | `historical_analysis.model_attribution` | Score→return correlation by model_id. | same | details | FEEDER | **Keep** for weight-learning; not strategy book |

---

## Tab: Analysis

Sub-nav: **Observe** | **Sunday** | **Charts** | **Deep** | **Post-run** | **Memos** — `renderAnalysisSubnav` (`app.js:4439`); shell `renderAnalysis` (`app.js:4647`).

### Observe (all models)

| Section | Render fn | Data source | Shows | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---|---|---|---|---|---|---|
| **Investment model** switcher | `renderInvestmentModelSwitcher` (`app.js:4544`) | static `INVESTMENT_MODELS` + sidecar scoreboards | Strand A vs N200/N201/N206/N210 tabs. | n/a | Model buttons; hash `#analysis/observe/{model}` | OPS-META | **Keep** but add **Strategy book** slot; demote “Strand A · live” badge |
| IA contract blurb | `renderAnalysisSubnav` (`app.js:4457–4461`) | static | Explains observe vs single live path. | n/a | none | OPS-META | **Keep**; update when strategy book UI lands |

### Observe → Strand A (control)

| Section | Render fn | Data source | Shows | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---|---|---|---|---|---|---|
| Companion strip (primary track, TR excess) | `renderInvestmentModelCompanionStrip` (`app.js:6697`) | `data/assessment_scoreboard.json` (sidecar) | Quick primary track TR excess vs FTAL.L. | **2026-11-06T02:34Z** | none | CONTROL | **Move** to “Control books”; strip “live capital” label |
| **Lifecycle monitor · Strand A** | `renderStrandALifecycleMonitor` (`app.js:6233`) | `lifecycle_maturity_trajectory.json` / `queue_health` | Links to Lifecycle tab; FTSE maturity snapshot. | **2026-11-06T02:37Z** | Jump Lifecycle tab/subpage | CONTROL | **Keep** as control diagnostics |
| **Assessment scoreboard** | `renderAssessmentScoreboardPanel` (`app.js:8014`) | `assessment_scoreboard.json` | Total return vs FTAL.L, roles, AI gate, twins/frozen. | **2026-11-06T02:34Z** (4 tracks) | `<details>` frozen/twins | CONTROL | **Keep** for control comparison; **not** strategy-core |
| **Total return vs price-only excess** | `renderTotalReturnVsPricePanel` (`app.js:8126`) | `total_return_view.json` | TR vs published price-only excess by track. | **2026-11-06T02:32Z** | none | CONTROL | **Reuse** for strategy book TR column |
| **Legacy Suite A/B buckets** | `renderPaperTrackBucketsPanel` (`app.js:8171`) | `latest.json` → `learning_tracks_dual_suite` (+ optional `paper_track_buckets`) | Collapsed dual-suite stress/adoption bullets. | dual suite **2026-11-01** | `<details>` | LEGACY-OBSERVE | **Retire** when strategy book scoreboard live |
| **Observe utilization** (compact) | `renderObserveUtilizationSection` compact (`app.js:7319`) | `observe_utilization.json` | Flip-lag / input-quality headline strip. | **2026-11-06T02:37Z** | Link → Automation Queue | DATA-P1 | **Keep** compact; full cards on Automation |

### Observe → N200 / N201 / N206 / N210 (same layout; stores differ)

| Section | Render fn | Data source | Shows | Freshness (stores) | Interactive? | Tag | Keep / move / retire |
|---|---|---|---|---|---|---|---|
| Companion strip | `renderInvestmentModelCompanionStrip` (`app.js:6738+`) | `n200_tech_timing_observe.json` / `n201_value_mom_observe.json` / `n206_plain_ey_observe.json` / `n210_ai_judgment_observe.json` | Volume gate, cohort median, running time. | All **2026-11-06** (~02:33–02:34Z) | none | LEGACY-OBSERVE | **Keep** as observe feeders; queue behind strategy proof |
| **Lifecycle monitor · N*** | `renderObserveLifecycleMonitor` (`app.js:6400`) | same observe JSON | Phase/volume/path cards; episodes sample; change markers. | same | none | LEGACY-OBSERVE | **Reuse** episode table pattern for strategy book |
| **N200 pipeline health** (or N201/N206/N210 titled sections) | `renderN200PipelineHealthSection` etc. (`app.js:5559`, `5745`, `5912`, `6090`) | `queue_health.json` projections + observe stores | Factory throughput, levers, freshness badges. | queue **2026-11-06T02:37Z** | Link Automation (compact elsewhere) | DATA-P1 / LEGACY-OBSERVE | **Keep** on observe models; not owner strategy |
| **Path scoreboard (N*** · alone)** | `renderObservePathScoreboardPanel` (`app.js:6838`) | observe store → `path_scoreboard` | Fair-cost cohort medians / control cells. | store dates above | none | LEGACY-OBSERVE | **Reuse** metrics layout for matched-excess episodes |
| Link to Automation Queue | `renderAnalysisObserveForModel` (`app.js:4591–4635`) | static | Cross-tab navigation hint. | n/a | `data-tab-jump` | OPS-META | **Keep** |

### Sunday / Charts / Deep / Post-run / Memos

| Section | Render fn | Data source | Shows | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---|---|---|---|---|---|---|
| **Sunday review** | `renderSundayReview` (`app.js:3955`) | `latest.json` → `sunday_review` | Exclusion ladder, regime history, paper tracks by week, experiments. | **2026-11-01** (`generated_at`, week ending) | `<details>` blocks | LEGACY-OBSERVE | **Move** to Automation/Archive; regime/exclusion not owner strategy |
| → Exclusion ladder | `renderSundayReview` (`app.js:4250–4257`) | `sunday_review.current.exclusion.weekly` | Forward EW exclusion alpha pairs. | **2026-11-01** | details | LEGACY-OBSERVE | **Retire** from owner Analysis default |
| → Regime snapshots | `renderSundayReview` (`app.js:4259–4269`) | `sunday_review.history` | Filter step, shadow-ready flags, beat market. | weekly thru **2026-11-01** | details | OPS-META | **Move** ops-only |
| → **Paper tracks by week** | `renderSundayReview` (`app.js:4272–4274`) | `sunday_review.history[].paper_tracks` | Price-only excess per learning track. | thru **2026-11-01** | per-track `<details>` | CONTROL | **Keep** as control telemetry; label not strategy |
| → Experiments ledger | `renderSundayReview` (`app.js:4276–4283`) | `sunday_review.current.experiments` | Shadow/experiment gate excess. | **2026-11-01** | details | OPS-META | **Keep** ops |
| **Buy-tier chart outcomes** | `renderChartOutcomeReview` (`app.js:2843`) via Analysis (`app.js:4763`) | `chart_outcome_review.json` (sidecar) | Timing labels on chart entries (well-timed / underwater). | **2026-11-01T09:15Z**; verdict `has_terrible` | Chart ticker buttons | FEEDER | **Keep** for entry-at-low feeder (strategy rule 4) |
| **Portfolio deep analysis** | `renderAnalysis` deep block (`app.js:4767–4769`) | `latest.json` → `deep_analysis` | LLM executive intro / picks / red flags. | **empty** in current publish | none | FEEDER | **Keep** when CI key present; optional |
| **Post-run improvement review** | `renderAnalysis` (`app.js:4695–4720`) | `latest.json` → `post_run_review` | Executive summary, persistent weaknesses themes, plan. | Text present; **no** `generated_at` field (treat as **2026-11-01** bundle age) | `<details>` | OPS-META | **Keep** human narrative; not a backlog |
| → Executive / weaknesses / findings / plan / defer / full text | `renderAnalysis` | `post_run_review.*` | Structured post-run sections. | same | details | OPS-META | **Keep** |
| **Strong buy research memos** | `renderAnalysis` (`app.js:4772–4775`) | `latest.json` → `research` (101 memos) | Memo list with quality badges. | Memo `updated_at` per row (not rolled up) | Read memo → fetch `memo_path` | FEEDER / DATA-P1 | **Keep** as P1 memo freshness surface |

---

## Automation tab (scoped panels — not a primary tab in title, but mounted here)

| Section | Render fn | Data source | Shows | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---|---|---|---|---|---|---|
| **Automation → Tracks** (pane) | `renderAutomation` (`app.js:10190–10197`) | merges sidecars + `latest.json` | Hosts scoreboard, learning tracks, knobs, churn. | varies | Automation subnav | OPS-META | **Keep** ops home |
| **Assessment scoreboard** (duplicate) | `renderAssessmentScoreboardPanel` (`app.js:8014`) | `assessment_scoreboard.json` | Same as Analysis Strand A. | **2026-11-06** | details | CONTROL | **Dedupe** — single instance linked from Analysis |
| **Total return vs price-only** (duplicate) | `renderTotalReturnVsPricePanel` (`app.js:8126`) | `total_return_view.json` | Same TR table. | **2026-11-06** | none | CONTROL | **Dedupe** |
| **Learning tracks (server)** | `renderLearningTracksPanel` (`app.js:8371`) | `latest.json` → `learning_tracks_review`, `learning_track_funds`, `learning_tracks_dual_suite`, `paper_automation` | Collapsed legacy Suite A/B NAV tables. | dual suite **2026-11-01**; review verdict `underperforming`; funds embedded | `<details>` archive | CONTROL | **Retire** from default view; keep frozen archive link |
| **Knob bootstrap lab** | `renderKnobBootstrapPanel` (`app.js:7859`) | `latest.json` → `knob_calibration_priors`, `calibration_shadow_endurance` | Retrospective knob priors + shadow endurance. | calibrated **2026-08-23**; endurance **2026-10-30** | none | OPS-META | **Keep** ops-only |
| **Churn & counterfactual** | `renderChurnCounterfactualPanel` (`app.js:4908`) | `latest.json` → `churn_health`, `buffered_hold_counterfactual` | Cost drag, exit_confirm counterfactual on learning tracks. | **2026-10-30** | none | CONTROL | **Keep** ops; not strategy exits |
| **Automation → Human → Ingest deviations** | `renderIngestDeviationsSection` (`app.js:5084`) | `ingest_deviations.json` (sidecar) | Open ingest/IR deviation rows + triage hints. | **2026-11-05T22:48Z** | display-only (CLI reprocess codes) | DATA-P2 | **Keep** on Human pane |

---

## Observations

### Duplication across tabs
- **Assessment scoreboard** + **Total return vs price** appear on **Analysis → Observe (Strand A)** and **Automation → Tracks** (identical render fns).
- **Paper track / learning performance** appears in **Sunday review → Paper tracks by week**, **Automation → Learning tracks**, **Performance → Simulation**, and **Portfolio local sandbox** — four different semantics (price-only vs TR vs browser vs archive sim).
- **Observe pipeline health** full cards vs compact strips: Analysis Observe vs Automation Queue (by design, still easy to confuse).
- **Chart outcomes** also surface on Strong Buys tab via same `renderChartOutcomeReview` (out of scope but duplicated).

### Jargon / codenames an owner may not parse
- Strand A/B, N200/N201/N206/N210, Suite A/B, FTAL.L, F5/F8/F9-B, O3/O6, “launch-queue waiter”, “exit_confirm”, “dual-suite”, “shadow spawn”, “exclusion ladder step u4”, “primary learning track”, “matched-30”, “cue-consumer”, “flip-lag”, “IWB”, “knob bootstrap”, “buffered hold”, “top-N / conviction rebalance” (browser automated fund sells names dropping out of top set — **not** owner strategy exit).

### Stale / empty / misleading
- **`sunday_review` / dual-suite / chart outcomes** lag latest screen (**2026-11-06**) by ~5 days (**2026-11-01**).
- **`deep_analysis`** empty in publish; Post-run has content but no timestamp field.
- **`knob_calibration_priors`** last calibrated **2026-08-23** (very stale UI if opened).
- **Strand A “live capital” badge** contradicts stated policy (strategy book only route to live capital).
- **No UI** for `operating_decline_gate.json` / `sector_headwind_gate.json` (**2026-11-06**) or **strategy book registration** — strategy gates exist in data but not in these tabs.
- **`progress_report.json`** sidecar **2026-09-30** if user opens progress dialog from elsewhere.

### Old funds / top-N framing vs strategy book
- **Portfolio → Automated sandbox** explicitly rebalance/top-conviction behaviour; surveillance warns on signal downgrade — looks like a book rule but is local-only.
- **Performance → Simulation** and **Sunday paper tracks** present **screen/AI learning books** as performance heros.
- **Assessment scoreboard primary** still reads as adoption truth; UI text partially disclaimers Suite B/A.

### Panels to reuse for `owner-strategy-book-v0`
| Existing panel | Reuse for |
|---|---|
| `renderObservePathScoreboardPanel` / episode tables in `renderObserveLifecycleMonitor` | Fixed-stake **episode table**, matched buy-tier excess, recovery-hold status |
| `renderTotalReturnVsPricePanel` + `renderAssessmentScoreboardPanel` | **Book-level TR vs benchmark** beside matched excess (strategy phase-3 bar) |
| `renderChartOutcomeReview` | **Short-term entry low** monitoring (rule 4) on buy-tier |
| `renderInvestmentModelSwitcher` | Add **Strategy book** as sole “live path”; relegate Strand A to **Control** |
| `renderPortfolio` open-actions table | Live **holdings / episodes** once wired to strategy book (today localStorage only) |
| Gates (not yet UI) | Surface `operating_decline_gate.json` + `sector_headwind_gate.json` next to buy-tier candidates |

### Recommended tab architecture (short)
1. **Strategy book** (new): episodes, gates, TR scoreboard, checkpoint/recovery policy state.  
2. **Feeders**: Screen quality, memos, chart outcomes, ingest/P1 strips.  
3. **Controls**: Strand A scoreboard, learning tracks archive, Performance historical replay.  
4. **Retire / hide by default**: Portfolio local sandbox, Performance £1k sim as main metric, Sunday exclusion ladder for owner default.
