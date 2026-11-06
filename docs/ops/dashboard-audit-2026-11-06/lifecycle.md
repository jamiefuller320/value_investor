# Lifecycle tab audit (read-only)

**Repo:** `/agent/repos/value_investor` · **Scope:** `docs/app.js` lifecycle renderers + related data files  
**Audit date:** 2026-11-06 (UTC) · **Published snapshot:** lifecycle_board / sealed / review queues generated ~2026-11-06T02:32–02:34Z

## Where scoped renderers mount

| Renderer | Line | Mounted on |
|----------|------|------------|
| `renderLifecycleSubnav` | 10516 | **Lifecycle** (all sub-pages) |
| `renderLifecycle` | 13932 | **Lifecycle** tab (`#panel-lifecycle`) |
| `renderLifecycleMaturitySection` | 7446 | **Lifecycle → Maturity mix** |
| `renderSealedLifecycle` (+ heat/list/detail/collation) | 11817–11904 | **Lifecycle → Sealed models** |
| `renderPostSaleReviews` (+ cards, draw tools) | 12770–12887 | **Lifecycle → Post-sale reviews** |
| `renderEntryBlindReviews` | 13474 | **Lifecycle → Entry blind** |
| `renderEntryRevisitReviews` | 13775 | **Lifecycle → Entry +28d** |
| `renderModelLifecycleMonitor` | 6227 | **Analysis → Observe** (per model switcher), not Lifecycle tab |
| `renderSealedLifecycleCollation` | 6633 | **Lifecycle → Sealed models** (and duplicates Analysis data) |
| `renderInvestmentModelCompanionStrip` | 6697 | **Analysis → Observe** + **Sealed models** collation strip |
| `renderObservePathScoreboardPanel` | 6838 | **Analysis → Observe** only (N200/N201/N206/N210) |

Data merge map (`docs/app.js` ~614–621): sidecars `data/lifecycle_board.json`, `data/sealed_lifecycle.json`, review queue/label JSON files → `dashboardData.*` (also embedded in `latest.json` bundle when published).

---

## Shared: Lifecycle sub-navigation

| # | Tab > section | Render fn @ line | Data source | Shows | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---------------|------------------|-------------|-------|-----------|--------------|-----|----------------------|
| 1 | Lifecycle > sub-nav (Positions / Maturity mix / Sealed models / Post-sale reviews / Entry blind / Entry +28d) | `renderLifecycleSubnav` @ 10516 | None (UI state `lifecycleSubpage`, hash `#lifecycle&subpage=…`) | Six sub-tab buttons | n/a | Yes — `data-lifecycle-subpage` → `renderLifecycle`; hash via `syncLifecycleHash` | OPS-META | **Keep** on Lifecycle; add strategy-book sub-tab only when book has its own board |

---

## Lifecycle → Positions (default sub-page)

| # | Tab > section | Render fn @ line | Data source | Shows | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---------------|------------------|-------------|-------|-----------|--------------|-----|----------------------|
| 2 | Positions > header “Position lifecycle” | `renderLifecycle` @ 14069–14096 | `lifecycle_board.note`, `lifecycle_board.markets` | Title + board purpose blurb | `lifecycle_board.generated_at` **2026-11-06T02:34:29Z**; 23 markets, 8 columns | Market `<select>`, chip sort `<select>` ×2 | CONTROL | **Keep** as Strand A / FTSE paper control board until strategy-book position UI exists; then **move** primary view to strategy book and demote this to “control track” |
| 3 | Positions > market pills | `renderLifecycle` @ 14005–14011 | `lifecycle_board.markets[]` (`is_live`, `is_focus`, `is_admitted`) | Quick market switcher | Same board timestamp | `data-lifecycle-market` | CONTROL | **Keep** for multi-market screen funnel (feeder to book), not live capital |
| 4 | Positions > paper track pills | `renderLifecycle` @ 14012–14017 | `markets[].tracks[]` | Book track switch (holdings count badge) | FTSE350 default track **63** holdings | `data-lifecycle-track` | CONTROL | **Keep** for paper book tracks; strategy book should get its own track id in data model |
| 5 | Positions > tenure legend | `lifecycleTenureLegend` @ 11389 | `lifecycle_board.tenure.bands` | Color key for time-in-stage on chips | Bands in board JSON | No | OPS-META | **Keep** |
| 6 | Positions > column “Not buy tier” | `renderLifecycle` @ 14044–14061 + `lifecycleExperimentChips` @ 11152 | `lifecycle_board.columns[]` + `market.screen_columns.not_buy_tier` merged via `mergeLifecycleColumns` | Screen census cards + experiment chips | Column defs + market counts | Ticker chips; experiment chips → dialog | FEEDER | **Keep** as universe funnel (buy-tier gate input), not strategy execution |
| 7 | Positions > column “Not now” | same | `screen_columns.not_now` | Deferred screen names | per `column_counts` | same | FEEDER | **Keep** |
| 8 | Positions > column “Near buy threshold” | same | `screen_columns.near_buy` | Near-buy watch | per counts | same | FEEDER | **Keep** |
| 9 | Positions > column “Just bought” | same | `track.position_columns.just_bought` | Recent entries on selected book | FTSE350 example **1** | same | CONTROL | **Keep** on control book; mirror columns for **STRATEGY-CORE** when book ships |
| 10 | Positions > column “Growth” | same | `position_columns.growth` | Core hold stage | example **26** | same | CONTROL | **Keep** / twin for strategy book |
| 11 | Positions > column “Near sell threshold” | same | `position_columns.near_sell` | Pre-exit watch | example **36** | same | CONTROL | **Keep** / twin |
| 12 | Positions > column “Just sold” | same | `position_columns.just_sold` | Recent exits | example **7** | same | CONTROL | **Keep**; links conceptually to post-sale review queue |
| 13 | Positions > column “Post sale monitor” | same | `position_columns.post_sale` | Post-exit watch window | board `post_sale_days`: 84 | same | CONTROL | **Keep** |
| 14 | Positions > ticker chip (each name) | `lifecycleTickerCard` @ 11203 | Card rows in board JSON; detail enriches from `latest.json` → `reports[]`, `research[]`, `chart_outcome_review.rows` | Ticker, signal, tenure days, column reason, P&L snippet | Reports tied to publish cycle | Opens **`lifecycle-ticker-dialog`** | CONTROL / FEEDER | **Keep** chips; for strategy book key cards on **episode id** not just ticker |
| 15 | Positions > dialog “Lifecycle ticker” | `renderLifecycleTickerCard` @ 11285 · `openLifecycleTickerCard` @ 11365 | `lifecycle_board` card + `reports[]` + `research[]` + `chart_outcome_review` | Badges, trade plan, decision pack, memo button, chart outcome, price chart | `chart_outcome_review` in latest (1119 charts); memo/report may be missing for sold names | Memo open; `mountPriceChart` with book overlays | CONTROL | **Move** enrichment to strategy-book episode payload; keep chart pattern |
| 16 | Positions > experiment chip (per column) | `lifecycleExperimentChipButton` @ 11081 | `lifecycle_board.columns[].experiments[]` | Factor id + status badge | **27** experiments total on board | Opens **`lifecycle-experiment-dialog`** | LEGACY-OBSERVE | **Retire** auto-promote / DCA experiment chips from live path; **keep** observe-only or re-home under Engineering, not Positions |
| 17 | Positions > dialog “Lifecycle experiment” | `renderLifecycleExperimentCard` @ 10574 | Same experiments + `initiation` payloads | Aim, progress, recommend block, evidence, Acknowledge/Start | Ledger joined when present | **Bridge:** `lifecycle-experiment-ack`, `lifecycle-experiment-start` (or `/api/lifecycle-experiment-*`) | LEGACY-OBSERVE | **Retire** from Positions for strategy era; queue via `ftse-defer` unless tied to strategy-book version review |

**Positions empty state:** if `lifecycle_board` missing → message to run `ftse-publish` (@ 13974–13979).

---

## Lifecycle → Maturity mix

| # | Tab > section | Render fn @ line | Data source | Shows | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---------------|------------------|-------------|-------|-----------|--------------|-----|----------------------|
| 18 | Maturity mix > section | `renderLifecycleMaturitySection` @ 7446 | `latest.json` → `lifecycle_maturity_trajectory` **or** `queue_health.lifecycle_maturity_trajectory` via `resolveLifecycleMaturity` @ 5469 | Early-share %, held mix, UW rates, sparkline per market | Not embedded in `latest.json`, but loaded from the `data/lifecycle_maturity_trajectory.json` sidecar (`generated_at` 2026-11-06, 23 markets), so the section renders | No | OPS-META | **Keep** observe twin — useful for strategy book maturity once wired to book board timestamp |
| 19 | Maturity mix > per-market card | `renderLifecycleMaturityMarketCard` @ 7410 | `payload.markets[]`, `payload.history[]` | Primary early-share, trajectory badge, held/sold metrics | Same as above | No | OPS-META | **Keep** |

**Note:** Strand A monitor snapshot (@ 6233) duplicates FTSE early-share from same maturity payload for Analysis tab pointer only.

---

## Lifecycle → Sealed models

| # | Tab > section | Render fn @ line | Data source | Shows | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---------------|------------------|-------------|-------|-----------|--------------|-----|----------------------|
| 20 | Sealed models > page shell | `renderSealedLifecycle` @ 11817 | `sealed_lifecycle.json` | Model title, registration id, observe-only banner | `generated_at` **2026-11-06T02:34:19Z**; **4** models, **735** chips total | Model pills, heat/list toggle, sort toggle | LEGACY-OBSERVE | **Keep** as sealed N200/N201/N206/N210 scan; not strategy book |
| 21 | Sealed models > companion strip | `renderInvestmentModelCompanionStrip` @ 6697 (via collation) | `n*_observe.json` + `*_pipeline_health` / client projection | Time running, volume gate, cohort median, sample stats | e.g. N200 store **2026-11-06T02:33:01Z**, 112 ep | Jump to Analysis → Observe | LEGACY-OBSERVE | **Keep** on sealed page; duplicate of Analysis |
| 22 | Sealed models > phase/volume/path stages | `renderObserveLifecycleMonitor` stagesOnly @ 6400 (via `renderSealedLifecycleCollation` @ 6633) | Same observe stores | Phase floor, volume gate, fair path primary | Store `generated_at` per model | Link buttons only | LEGACY-OBSERVE | **Keep** for feeder sealed units |
| 23 | Sealed models > pipeline extras line | `renderSealedLifecycleExtras` @ 6585 | `resolveN*PipelineHealth` | Freshness badge, functioning, N200 entry/exit lever badges | Store + ops projection | No | LEGACY-OBSERVE | **Keep**; lever scores are **cue-consumer / timing lab** output — map to strategy episode levers in plan 2.4 |
| 24 | Sealed models > episode board (heatmap) | `renderSealedLifecycleHeatBoard` @ 11779 | `sealed_lifecycle.models[].columns` phases just_bought/holding/just_sold/post_sale | Dense heat cells (return + days in phase) | Per-model `as_of` (e.g. N200 **2026-11-06**) | Cell click → detail | LEGACY-OBSERVE | **Keep** for observe books; optional **move** pattern to strategy-book episode scan |
| 25 | Sealed models > episode board (chip list) | `renderSealedLifecycleListBoard` @ 11798 | same | List chips per phase | same | Chip click → detail | LEGACY-OBSERVE | **Keep** |
| 26 | Sealed models > episode detail card | `renderSealedLifecycleDetail` @ 11636 | Selected chip in sealed model | Entry/exit dates, return, hold days, assessment-window chart | Chip-level | Close button; chart fetch `data/charts/` | LEGACY-OBSERVE | **Keep** UX; retarget data to strategy `episode_key` + `close_in` |
| 27 | Sealed models > empty | `renderSealedLifecycle` @ 11839 | missing `sealed_lifecycle` | Publish hint | missing | No | OPS-META | n/a |

---

## Lifecycle → Post-sale reviews

| # | Tab > section | Render fn @ line | Data source | Shows | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---------------|------------------|-------------|-------|-----------|--------------|-----|----------------------|
| 28 | Post-sale > header + sort | `renderPostSaleReviews` @ 12770 | `post_sale_review_queue.json` | Product claim, active counts, by-book breakdown | Queue `generated_at` **2026-11-06T02:32:51Z**; **141** active; 471 candidates | Sort tabs `data-psr-sort` | HUMAN-TASK | **Move** (plan 2.4) to **strategy-book episodes**; keep machinery |
| 29 | Post-sale > review card (collapsed) | `renderPostSaleReviewCard` @ 12649 | `queue.active[]` + overlay filter | Book tag, ticker, exit date, return %, buy/sell reason summary | Labels `updated_at` **2026-10-30** (218 events) | Expand `data-psr-expand` | HUMAN-TASK | **Move** — re-key `book_id` → `owner-strategy-book-v0`, keep `episode_key` |
| 30 | Post-sale > review card (expanded) | same @ 12690 | Item fields + `chart_annotations` | Framing, factory dialogue, dual charts (episode + wider TF), pattern mark chips | Charts from published series | Accept / Duplicate / Comment | HUMAN-TASK | **Move** — core **review machinery** |
| 31 | Post-sale > factory pattern marks | `renderPatternMarkChips` @ 12310 | `item.chart_annotations.marks[]` | Explainable factory overlays on charts | Per card | Tap to expand explain | FEEDER | **Keep** with post-sale cards on strategy episodes |
| 32 | Post-sale > owner chart draw toolbar | `renderHumanDrawToolbar` @ 12255 · `renderChartWithDrawTools` @ 12274 | In-memory `humanChartDrafts[reviewId][chartKey]` | Highlight, H-line, trend, parallel, undo, clear | Session only until Comment | Draw tools; geometry seals on Comment | HUMAN-TASK | **Move** with reviews; keys **`review_id` + chart (`episode`/`wider_tf`)** |
| 33 | Post-sale > durable history list | `renderPostSaleReviews` @ 12831 | `post_sale_review_labels.json` → `events[]` | Last 40 accept/comment/duplicate events | 218 events | Read-only | OPS-META | **Keep**; extend labels file for strategy book |
| 34 | Post-sale > bridge write-back | `submitPostSaleReviewAction` @ 13033 | Payload: `review_id`, `decision`, `episode_key`, `book_id`/`book_tag`, `model_id`, `ticker`, `entry_at`, `exit_at`, `buy_decision`, `sell_decision`, optional `post_hoc_human_geometry` | n/a | n/a | **Bridge:** `post-sale-review-ack`, `post-sale-review-comment`, `post-sale-review-duplicate`; localStorage `ftse.pendingPostSaleActions.v1` | HUMAN-TASK | **Repoint** population filter to strategy-book exits; keep actions |

---

## Lifecycle → Entry blind

| # | Tab > section | Render fn @ line | Data source | Shows | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---------------|------------------|-------------|-------|-----------|--------------|-----|----------------------|
| 35 | Entry blind > header + sort | `renderEntryBlindReviews` @ 13474 | `entry_blind_review_queue.json` | Blind entry critique claim, counts | `generated_at` **2026-11-06T02:32:52Z**; **12** active; 57 candidates | Sort `data-ebr-sort` | HUMAN-TASK | **Move** to strategy-book **entry episodes** (PIT stage) |
| 36 | Entry blind > card collapsed | `renderEntryBlindReviewCard` @ 13387 | `queue.active[]` | Buy reason, news polarity, timing lenses teasers | Labels **2026-10-30** (36 events) | Expand | HUMAN-TASK | **Move** — keys `episode_key` / `family_id`, `stage: entry_blind` |
| 37 | Entry blind > card expanded | same @ 13408 | + `parallel_timing_lenses`, `entry_news_polarity` | PIT chart to buy day, pattern marks, draw tools on `pit` chart | Outcome fields stripped by design | Accept / Duplicate / Comment | HUMAN-TASK | **Move** — entry gate review for strategy (short-term low, sector/ops gates in framing) |
| 38 | Entry blind > bridge | `submitEntryBlindReviewAction` @ 13579 | Slim snapshot keys @ 13108–13127 | n/a | n/a | **Bridge:** `entry-blind-review-ack`, `-comment`, `-duplicate`; localStorage `ftse.pendingEntryBlindActions.v1`; Comment attaches `post_hoc_human_geometry` | HUMAN-TASK | **Repoint** book filter from lab/sealed to strategy book |

---

## Lifecycle → Entry +28d (entry revisit)

| # | Tab > section | Render fn @ line | Data source | Shows | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---------------|------------------|-------------|-------|-----------|--------------|-----|----------------------|
| 39 | Entry +28d > section | `renderEntryRevisitReviews` @ 13775 | `entry_revisit_review_queue.json` | buy+28d follow-up cards | `generated_at` **2026-11-06T02:32:52Z**; **0** active; labels file **missing** | Expand; Accept/Dup/Comment | HUMAN-TASK | **Move** to strategy book after blind stage; aligns with **63-session** recovery horizon concept |
| 40 | Entry +28d > card detail | `renderEntryRevisitReviewCard` @ 13720 | `path_status`, `blind_review_id` | Textual path % to +28d; **no charts / no draw tools** | Per card | **Bridge:** `entry-revisit-review-ack`, `-comment`, `-duplicate` via `queueDashboardCommand` or `/api/entry-revisit-review-action` | HUMAN-TASK | **Keep** stage; add charts later or merge into single episode timeline |

---

## Analysis → Observe (in scope 6227–7020; not Lifecycle tab)

| # | Tab > section | Render fn @ line | Data source | Shows | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---------------|------------------|-------------|-------|-----------|--------------|-----|----------------------|
| 41 | Analysis > Strand A lifecycle monitor | `renderStrandALifecycleMonitor` @ 6233 | `lifecycle_maturity_trajectory` + links | Pointer to Lifecycle Positions/Maturity; FTSE maturity snapshot | Maturity sidecar 2026-11-06 | Tab jump buttons | CONTROL | **Keep** as control pointer until strategy tab replaces copy |
| 42 | Analysis > N200/N201/N206/N210 lifecycle monitor | `renderObserveLifecycleMonitor` @ 6400 | `n200_tech_timing_observe.json`, etc. | Phase, volume, path, episode sample table, change markers | N200 **2026-11-06**, 112 ep, 25 sample rows | No write | LEGACY-OBSERVE | **Keep** on Analysis; episode table shows **entry_lever/exit_lever** (N200) = five-lever/lab scoring at episode level |
| 43 | Analysis > path scoreboard panel | `renderObservePathScoreboardPanel` @ 6838 | `store.path_scoreboard` | Fair-cost cohort metrics per model | Store timestamps above | No | LEGACY-OBSERVE | **Keep** feeder metrics; not strategy NAV |
| 44 | Analysis > companion strip | `renderInvestmentModelCompanionStrip` @ 6697 | observe stores / assessment_scoreboard for strand-a | Running time, volume, cohort median | per store | No | CONTROL / LEGACY-OBSERVE | **Keep** split by model |

---

## Observations

1. **Lifecycle tab is still Strand A + sealed observe + Package M review queues** — none of the sub-pages yet bind to `owner-strategy-book-v0` as STRATEGY-CORE; Positions board is explicitly multi-market paper + screen funnel (`lifecycle_board.note`).

2. **Review machinery cluster (plan step 2.4):** Post-sale cards (judgment-in-the-round: framing, factory dialogue, dual charts, pattern marks, human draw → geometry on Comment), entry blind (PIT + lenses + draw), entry revisit (textual +28d). Five-lever / timing scoring appears in **N200 episode sample** and **N200 pipeline entry/exit lever badges**, not inside post-sale cards (those use structured `buy_decision` / `sell_decision` trails).

3. **Identity keys for reuse on strategy-book episodes:**
   - `review_id` (stable card id)
   - `episode_key` (post-sale dedupe; entry blind uses `episode_key` / `family_id`)
   - `book_id` / `book_tag` / `model_id` / `registration_id`
   - `ticker`, `entry_at`, `exit_at`, `opened_at`, `sold_at`
   - Chart scope: `chartKey` ∈ `episode` | `wider_tf` | `pit`

4. **Freshness gaps:** Post-sale/entry-blind **labels** lag queues by ~1 week (labels Oct 30 vs queues Nov 6). (`lifecycle_maturity_trajectory` is not in `latest.json` but arrives through its sidecar, so Maturity mix is populated.)

5. **Interactive persistence:** Post-sale and entry-blind use **localStorage** optimistic clears (2h TTL). Lifecycle Positions chip sort uses **localStorage** keys `ftseValueInvestor.lifecycleChipSort.v1`. Sealed view mode/sort is session-only (`sealedLifecycleViewMode`, `sealedLifecycleSortMode`).

6. **Experiment Acknowledge/Start** on Positions column chips targets graduated entry DCA observe factors — conflicts with “strategy book only route to live capital”; treat as LEGACY-OBSERVE.

---

## Reusable for strategy book (plan 2.4)

| Component | Repoint data | Keep UX / bridge |
|-----------|--------------|------------------|
| Post-sale queue + cards + draw tools + pattern marks | Build queue from **strategy-book closed episodes** (`book_id=owner-strategy-book-v0`, same `episode_key` scheme); map sell reasons to owner gates (thesis break, 63d hold, checkpoint ladder) | Same three bridge actions + `post_hoc_human_geometry`; same dual-horizon charts keyed by `review_id` |
| Entry blind | Candidate **strategy-book entries** at buy (PIT only); strip forbidden outcome fields already enforced in queue JSON | Same `entry-blind-review-*` actions; `stage: entry_blind` |
| Entry revisit | Trigger at buy+28d (or align to strategy recovery checkpoint); link `blind_review_id` | Same `entry-revisit-review-*`; add charts when ready |
| Human chart drafts | `humanChartDrafts[reviewId][chartKey]` — no change | Attach to Comment payload on strategy reviews |
| Episode scan (sealed heat/detail) | Optional **strategy-book episode board** replacing sealed-only phases | Reuse `close_in` chart mount + episode_key |
| Positions column board | New publish path for **strategy holdings** by lifecycle phase (cheap / not declining / sector sound / entry low) | Reuse `lifecycleTickerCard` dialog with strategy decision pack |
| Lever scores | Wire episode rows to strategy timing/lever fields (successor to N200 `entry_lever`/`exit_lever`) | Show in episode detail, not as auto-promote |
| Maturity mix | Point `board_generated_at` at strategy board refresh | Keep trajectory observe-only |

**Retire or hide from default Lifecycle nav:** Positions experiment Acknowledge/Start dialog for DCA overlay factors; sealed model pills as primary workflow once strategy book live (keep under Analysis/Sealed as CONTROL/LEGACY-OBSERVE).

---

## Bridge action reference (Lifecycle scope)

| Action | Trigger UI |
|--------|------------|
| `lifecycle-experiment-ack` | Experiment dialog Acknowledge |
| `lifecycle-experiment-start` | Experiment dialog Start (entry DCA execute) |
| `post-sale-review-ack` / `-comment` / `-duplicate` | Post-sale expanded card |
| `entry-blind-review-ack` / `-comment` / `-duplicate` | Entry blind expanded card |
| `entry-revisit-review-ack` / `-comment` / `-duplicate` | Entry +28d expanded card |
| `progress-report` | After experiment ack from progress report path (related) |

All review actions declare `influences_live=false` in UI copy; strategy-book promotion still requires separate human gates per AGENTS.md F8 / single-track-to-live policy.
