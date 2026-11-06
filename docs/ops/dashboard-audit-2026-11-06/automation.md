# Automation tab audit (read-only)

**Repo:** `value_investor` static dashboard (`docs/app.js`, `docs/dashboard_bridge.js`)  
**Audit date:** 2026-11-06 (freshness from committed `docs/data/*.json` sidecars)  
**Scope:** Automation tab only (`#panel-automation`, `#automation/…` hash sub-tabs)

Data loading: `latest.json` embed + sidecar overlay per `DASHBOARD_SIDECARS` (`app.js` ~593–629). Sidecars win when newer unless `project_progress` embed is newer.

---

## Tab shell

| # | Tab > section | Render fn @ line | Data source | Shows (one sentence) | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---------------|------------------|-------------|------------------------|-----------|--------------|-----|---------------------|
| 0 | Automation > (empty) | `renderAutomation` @ 10168 | `latest.json` → `automation` or sidecar `docs/data/automation.json` | Placeholder when automation status was never published. | Sidecar present: `2026-11-06T06:01:17Z` | No | OPS-META | **Keep** as guard; rare on main. |
| 0b | Automation > sub-nav | `renderAutomationSubnav` @ 8588 | `daily_focus.illumination_hints` + section heuristics (`automationIlluminationFor` @ 8532) | Six sub-tabs (Daily, Tracks, Human, Queue, Ops, Settings) with green/amber “unread/attention” chips. | Hints from `daily_focus.generated_at` `2026-11-06T02:37:49Z` | Click switches pane + hash `#automation/{id}` | OPS-META | **Keep**; rename chips in rebuild (“new info” not “healthy”). |
| 0c | Automation > IA contract blurb | `renderAutomationSubnav` @ 8606 | Copy only | Explains Daily hub timezone and chip semantics. | n/a | No | OPS-META | **Keep** one line under owner cockpit. |

---

## Daily (`#automation` or `#automation/daily`)

| # | Tab > section | Render fn @ line | Data source | Shows (one sentence) | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---------------|------------------|-------------|------------------------|-----------|--------------|-----|---------------------|
| 1 | Daily > Daily hub | `renderDailyHubPanel` @ 9542 | `docs/data/daily_focus.json` (+ merge `daily_focus_acks.json`; overlay session) | Morning cockpit: local date, open-task counts, reconcile badge, aim text. | `generated_at` `2026-11-06T02:37:49Z`; wall stale if `local_date` ≠ London today | Reconcile badge → Ops pane; stale banner read-only | HUMAN-TASK | **Keep** as owner entry; align copy to strategy book not strand A. |
| 2 | Daily > Status | `renderDailyHubStatusReport` @ 9469 | `daily_focus.status_report.rows` | Grounded status bullets (ops/factory snapshot). | Same hub artifact | No | OPS-META | **Keep** under Daily; shorten for owner. |
| 3 | Daily > Focus | `renderDailyHubPanel` @ 9610 | `daily_focus.focus_lines` + matching `tasks` | P1/P2 focus chips (not Accept ritual). | Same | No | DATA-P1 / DATA-P2 | **Keep** chips; de-emphasize codenames in titles. |
| 4 | Daily > Push (today) | `renderDailyHubLaneBlock` @ 9487 | `daily_focus.push_suggestions` | ≤3 cited execution pushes for today. | Same; counts.push=1 | No | HUMAN-TASK | **Keep**; tie cites to strategy-book gates. |
| 5 | Daily > Later | `renderDailyHubLaterBlock` @ 9522 | `daily_focus.later_suggestions` | Gap-only items not in Push lane. | counts.later=0 | No | OPS-META | **Keep** when non-empty. |
| 6 | Daily > Explore (not-today) | `renderDailyHubLaneBlock` @ 9487 | `daily_focus.explore_suggestions` | Deferred ideas with falsify/promote hints. | counts.explore=2 | No | OPS-META | **Move** to deferred-review surface long-term; ok as labeled not-today. |
| 7 | Daily > Prioritized tasks | `renderDailyHubTaskCard` @ 9394 | `daily_focus.tasks` (open, non push/explore/later) | Expandable cards with assessment, review detail, recommendations. | 21 open tasks | ✓ ack, Accept, Discuss, options, copy paste phrase | HUMAN-TASK | **Keep**; bridge actions critical (see Observations). |
| 8 | Daily > Recommendation block | `renderDailyRecommendationBlock` @ 8912 | Per-task `recommendation` in `daily_focus` | Summary, rationale, in-card options, Accept/Discuss. | Per task | `daily-focus-ack`, `human-task-ack`, `daily-discuss`, `link_only` | HUMAN-TASK | **Keep** all write paths. |
| 9 | Daily > History (dev completed) | `renderDailyHubHistorySession` @ 9304 | `docs/data/daily_hub_history.json` | Table of closed dev-class daily tasks + accept-streak hints. | `generated_at` `2026-11-06T02:37:49Z` | No | OPS-META | **Keep** for operator memory; not owner-critical. |

---

## Tracks (`#automation/tracks`)

| # | Tab > section | Render fn @ line | Data source | Shows (one sentence) | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---------------|------------------|-------------|------------------------|-----------|--------------|-----|---------------------|
| 10 | Tracks > Assessment scoreboard | `renderAssessmentScoreboardPanel` @ 8014 | `docs/data/assessment_scoreboard.json` | Total return vs FTAL.L, statistics interval, primary/control/twin roles. | `2026-11-06T02:34:31Z` | No (details for frozen/twins) | CONTROL | **Move** to Performance or Strategy control panel; not strategy-book core. |
| 11 | Tracks > Total return vs price-only excess | `renderTotalReturnVsPricePanel` @ 8126 | `docs/data/total_return_view.json` | TR vs published price-only excess by track. | `2026-11-06T02:32:51Z` | No | CONTROL | **Merge** with scoreboard or retire duplicate. |
| 12 | Tracks > Learning tracks (server) | `renderLearningTracksPanel` @ 8371 | `latest.json` → `learning_tracks_review`, `learning_tracks_dual_suite`, `learning_track_funds`, configs | Legacy weekday paper-auto track review; points to scoreboard as canonical. | Dual suite `2026-11-01`; review undated embed | Collapsed **Legacy Suite A/B** details | CONTROL | **Retire** or freeze as archive; conflicts with single track to live. |
| 13 | Tracks > Legacy Suite A/B archive | `renderLearningTracksPanel` @ 8491 | `learning_tracks_dual_suite` | Suite B fair + Suite A stress tables (price vs ^FTSE). | Same | Expand/collapse only | CONTROL | **Retire** from owner view; engineer-only. |
| 14 | Tracks > Knob bootstrap lab | `renderKnobBootstrapPanel` @ 7859 | `latest.json` → `knob_calibration_priors`, `calibration_shadow_endurance` | Retrospective knob priors + forward shadow endurance (no auto-apply). | Calibrated `2026-08-23`; endurance `2026-10-30` | No | LEGACY-OBSERVE | **Move** to Ops/learning archive; not strategy v0. |
| 15 | Tracks > Churn & counterfactual | `renderChurnCounterfactualPanel` @ 4908 | `latest.json` → `churn_health`, `buffered_hold_counterfactual` | Weekday decision-review churn alerts, cost drag, exit_confirm 1 vs 2 counterfactual. | `2026-10-30` | No | CONTROL | **Keep** as control/churn lab; label as strand A / paper books. |

---

## Human (`#automation/human`)

| # | Tab > section | Render fn @ line | Data source | Shows (one sentence) | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---------------|------------------|-------------|------------------------|-----------|--------------|-----|---------------------|
| 16 | Human > Ingest deviations | `renderIngestDeviationsSection` @ 5084 | `docs/data/ingest_deviations.json` | Open post-ingest deviations with observe-only triage text (no auto reprocess). | `updated_at` `2026-11-05T22:48:48Z` | No (CLI/runbook only) | DATA-P2 | **Keep** for Data ops; optional move under Queue. |
| 17 | Human > Human tasks | `renderHumanTasksChecklistSection` @ 5153 | `docs/human_tasks_checklist.json` + `docs/data/human_tasks_board.json` (+ `human_task_acks.json` merge) | Promotion/version gates with analysis bullets and counts. | Board `2026-11-06T02:37:48Z`; checklist `2026-11-05` | **Acknowledge**, **Approve** → bridge `human-task-ack`; session overlay | HUMAN-TASK | **Keep**; must survive rebuild (owner phase gates). |
| 18 | Human > Human task card | `renderHumanTaskCard` @ 5258 | Per `human_tasks_board.tasks[]` | Single gate card (ack/approve, fingerprint). | Per-task `analysis.updated_at` | Same as §17 | HUMAN-TASK | **Keep**. |
| 19 | Human > Automated CI | `renderHumanTasksChecklistSection` @ 5171 | `human_tasks_board.automated_tasks` | CI-handled checklist rows (read-only list). | Same board | No | OPS-META | **Keep** collapsed. |

---

## Queue (`#automation/queue`)

| # | Tab > section | Render fn @ line | Data source | Shows (one sentence) | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---------------|------------------|-------------|------------------------|-----------|--------------|-----|---------------------|
| 20 | Queue > Queue & hunter monitor | `renderQueueHealthMonitor` @ 7605 | `docs/data/queue_health.json` (or `automation.queue_health`) | Headline + merge/agent/ops lanes and dispatch signals. | `2026-11-06T02:37:48Z` | No | OPS-META | **Keep** for eng; demote for owner. |
| 21 | Queue > Merge lane | `renderQueueHealthMonitor` @ 7637 | `queue_health.merge_lane` | Open PR count and merge lane state. | Same | No | OPS-META | **Keep** (eng). |
| 22 | Queue > Agent / hunter lane | `renderQueueHealthMonitor` @ 7642 | `queue_health.agent_lane`, `queue_clearing`, `traffic_control` | Whether engineering agent should dispatch, next task, pauses. | Same | No | OPS-META | **Keep** (eng). |
| 23 | Queue > Ops monitor (lane card) | `renderQueueHealthMonitor` @ 7661 | `queue_health.ops_monitor` | Last ops run and engineering dispatch hold/ready. | `ops.run_at` via health embed | No | OPS-META | **Keep**. |
| 24 | Queue > Task / PR completion | `renderTaskCompletionMonitor` @ 7578 | `queue_health.completion_monitor` | UTC merge/fix intervention buckets + 14d chart. | Today `2026-11-06` | No | OPS-META | **Keep** (eng metrics). |
| 25 | Queue > Observe utilization | `renderObserveUtilizationSection` @ 7319 (full, not compact) | `docs/data/observe_utilization.json` (also nested in `queue_health`) | Headline, trajectory summary, instrument grid (P1 factory + lab observe). | `2026-11-06T02:37:45Z`; surface **fresh** | No | DATA-P1 / LEGACY-OBSERVE | **Split**: keep P1 cards; freeze/move lab instruments. |
| 26 | Queue > Buy-tier flip → usable | `renderObserveInstrumentCard` @ 7051 | `observe_utilization.instruments[id=buy_tier_flip_lag]` | Warn cohort when buy-tier flip not yet decision-usable (memo/ingest lag). | Instrument + ops_run in payload | No | DATA-P1 | **Keep** — direct F9-B feeder. |
| 27 | Queue > FTSE decision-input inventory | `renderObserveInstrumentCard` @ 7101 | `instruments[id=decision_input_inventory]` | Dominant gap counts for filing/FCF/overlay/memo on active inventory. | Same | No | DATA-P1 | **Keep** — core P1 dashboard. |
| 28 | Queue > Universe archive body-miss | `renderObserveInstrumentCard` @ 7292 (default metrics) | `instruments[id=universe_filing_archive_miss_rate]` | Cold-store archive miss proxy (quiet lane). | Same | No | DATA-P2 | **Move** to Ops/cold-store panel (already duplicated in Ops). |
| 29 | Queue > Shard NAV FX unit mismatch | `renderObserveInstrumentCard` @ 7292 | `instruments[id=shard_nav_fx_warp]` | FX unit mismatch warn across shard NAVs. | Same | No | OPS-META | **Keep** eng monitor. |
| 30 | Queue > Combined tagged exit_shadow join | `renderObserveInstrumentCard` @ 7292 | `instruments[id=combined_tagged_learning]` | Learning join health for tagged exit shadow. | Same | No | LEGACY-OBSERVE | **Retire** if exit_shadow not strategy-book. |
| 31 | Queue > Cue-consumer MFT (super book) | `renderObserveInstrumentCard` @ 7117 | `instruments[id=cue_consumer_mft]` | Super-book lab walker, Q8B cohort, MoM levers (observe-only). | Same | No | LEGACY-OBSERVE | **Freeze/retire** candidate (not strategy book). |
| 32 | Queue > Parallel timing lenses (L652) | `renderObserveInstrumentCard` @ 7163 | `instruments[id=parallel_timing_lenses]` | Concurrence/timing lens activity (fixed-stake v0). | Same | No | LEGACY-OBSERVE | **Freeze** per owner candidate list. |
| 33 | Queue > Lab learning progress | `renderObserveInstrumentCard` @ 7184 | `instruments[id=lab_learning_progress]` | Package M weekly learning strip (MFT + L652 metrics). | Same | No | LEGACY-OBSERVE | **Retire** or Analysis-only. |
| 34 | Queue > N200 / learning-factory pipeline | `renderN200PipelineHealthSection` @ 5559 (full) | `queue_health.n200_pipeline_health` + fallback `n200_tech_timing_observe.json` | Phase floor, volume gate, entry/exit levers, pipeline ops check (strand B). | Projection `2026-11-06T02:37:45Z`; store `2026-11-06T02:33:01Z` | Link jump only | FEEDER | **Keep** as running sealed unit monitor; label feeder not live. |
| 35 | Queue > N200 cards (Phase, Volume, Entry/Exit lever, Pipeline) | same @ 5637–6687 | Same | Five inner cards for N200 mechanism health. | Same | No | FEEDER | **Keep** compact in strategy ops view. |
| 36 | Queue > N201 pipeline health (compact) | `renderN201PipelineHealthSection` @ 5912 `{compact:true}` | `queue_health.n201_pipeline_health` / `n201_value_mom_observe.json` | Short N201 phase/volume/path strip + launch-queue waiter badge. | Same | Jump to Analysis/Automation | LEGACY-OBSERVE | **Freeze/retire** candidate (owner list). |
| 37 | Queue > N206 pipeline health (compact) | `renderN206PipelineHealthSection` @ 5745 `{compact:true}` | `n206_pipeline_health` / `n206_plain_ey_observe.json` | N206 throughput + path median strip. | Store `2026-11-06T02:34:19Z` | No | LEGACY-OBSERVE | **Freeze/retire** candidate. |
| 38 | Queue > N210 pipeline health (compact) | `renderN210PipelineHealthSection` @ 6090 `{compact:true}` | `n210_pipeline_health` / `n210_ai_judgment_observe.json` | AI-judgment observe walker/volume strip (B3). | Store `2026-11-06T02:34:08Z` | No | LEGACY-OBSERVE | **Freeze/retire** candidate. |
| 39 | Queue > Engineering merges today | `renderQueueHealthMonitor` @ 7689 | `queue_health.merges_today` | List of today’s merged PRs with verification flags. | Same | External PR links | OPS-META | **Keep** (eng). |
| 40 | Queue > Engineering queue | `renderEngineeringQueueSection` @ 7712 | `automation.engineering_queue` or `docs/data/engineering_tasks.json` | Queued/parked eng tasks table + spend checkpoint when present. | Compiled `2026-11-06T02:37:31Z`; open=0 | No | OPS-META | **Keep** eng-only. |

**Note:** `renderN200/N201/N206/N210PipelineHealthSection` full (non-compact) versions also mount on **Analysis** tab (model switcher) and compact strips on Analysis; Automation Queue is the full N200 + compact N201/N206/N210 stack inside `renderQueueHealthMonitor` @ 7668–7688.

**Not on Automation tab:** `renderLifecycleMaturitySection` @ 7446 lives on Lifecycle/Analysis paths only (L463 twin).

---

## Ops (`#automation/ops`)

| # | Tab > section | Render fn @ line | Data source | Shows (one sentence) | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---------------|------------------|-------------|------------------------|-----------|--------------|-----|---------------------|
| 41 | Ops > PR fix common issues | `renderPrFixCommonIssuesPanel` @ 8713 | `docs/data/pr_fix_occasions.json` | Top recurring CI/merge fix reasons from occasion log. | `2026-11-05T20:33:14Z` | No | OPS-META | **Keep** eng; duplicate mention on Human tab docstring only. |
| 42 | Ops > Cold-store archive pack | `renderColdStoreArchiveStatusPanel` @ 8843 | `docs/data/universe_filing_archive_status.json` | L499/L594 quiet lane last run, caps, clash/isolation chips. | Panel `2026-11-06T02:37:49Z`; last_run `2026-11-06T02:10:11Z` | No | DATA-P2 | **Keep** below launch-queue head; owner rarely needs daily. |
| 43 | Ops > UI ↔ system reconciliation | `renderUiReconcileTable` @ 8754 | `docs/data/ui_state_reconciliation.json` | Cap B drift checks between dashboard JSON and git truth. | `2026-11-06T02:37:49Z`; overall typically ok | Badge in Daily links here | OPS-META | **Keep** for dashboard health. |

---

## Settings (`#automation/settings`)

| # | Tab > section | Render fn @ line | Data source | Shows (one sentence) | Freshness | Interactive? | Tag | Keep / move / retire |
|---|---------------|------------------|-------------|------------------------|-----------|--------------|-----|---------------------|
| 44 | Settings > Current settings (intro) | `renderAutomationSettingsSection` @ 10025 | `automation.json` → `settings`, `note`, `generated_at` | Explainer + timestamp for automation config snapshot. | `2026-11-06T06:01:17Z` | No | OPS-META | **Keep** reference. |
| 45 | Settings > Paper automation | same @ 10087 | `automation.settings.paper` | Paper-auto cron, rebalance, surveil flags, caps. | Same | No | CONTROL | **Relabel** control book settings; strategy book settings TBD. |
| 46 | Settings > Library ladder | same @ 10097 | `automation.settings.library` | P2 focus market, graduation, maintenance, research model. | Same | No | DATA-P2 | **Keep** for ingest cascade. |
| 47 | Settings > Budget | same @ 10109 | `automation.settings.library.budget` | Subscription plan, weekly ops cap, checkpoint spend. | Same | No | OPS-META | **Keep** eng/finance. |
| 48 | Settings > Scheduled workflows | same @ 10134 | `automation.settings.workflows` | Named workflow cadences (cron summaries). | Same | No | OPS-META | **Keep**. |
| 49 | Settings > Achievements | same @ 10138 | `automation.achievements` | Milestones, ladder snapshot, paper last run, timeline. | Same | No | OPS-META | **Move** to changelog; low owner value. |

---

## Shared code in scope (not visible Automation UI)

| Area | Lines | Role |
|------|-------|------|
| Sidecar merge, human-task ack handlers | 1085–1146, 5335–5461 | Loads sidecars; optimistic ack + `human-task-ack` bridge/local API |
| Progress report generate | 1209–1466 | Binds **Overview** panel, not Automation (`panel-overview` @ 1469) |
| Bridge reload hook | 1199–1206 | `DashboardBridge.onArtifactUpdated` → silent dashboard reload |

---

## Observations

### Engineering plumbing vs owner-relevant

Roughly **half** of Automation surface area is eng/ops (Queue lanes, engineering queue, completion monitor, UI reconcile, PR fix log, Settings, Daily history, Explore lane). **Owner-critical** paths: **Daily hub** prioritized tasks, **Human tasks** ack/approve, and **P1 observe cards** (flip-lag + decision-input inventory). **Tracks** tab is mostly **legacy paper-book assessment** (scoreboard, dual suite, knobs, churn)—misaligned with “strategy book only route to live” unless reframed as **control/feeder** panels.

### Duplication

- **Assessment scoreboard** + **Total return view** + **Learning tracks** + **Churn** overlap Performance/Analysis narratives.
- **Observe utilization** full grid on Queue duplicates Analysis compact strip (`renderObserveUtilizationSection` compact @ 7347).
- **N201/N206/N210** compact on Queue duplicates Analysis model switcher full sections.
- **Cold-store** appears both as observe instrument (#28) and **Ops > Cold-store archive pack** (#42).
- **PR fix common issues** referenced from Human tasks copy but rendered only under Ops.

### Codename jargon (owner-unfriendly)

Examples visible without glossary: **N200/N201/N206/N210**, **strand A/B/C/D/E**, **F8/F9-B**, **Suite A/B**, **L652/L640/Package M**, **buy_tier**, **raw_buy_tier**, **launch-queue waiter**, **Q8B**, **B3**, **Cap B**, **ftse-defer**, **phase floor**, **volume gate**, **observe-only**, **knob bootstrap**, **exit_confirm_screens**, **FTAL.L** vs **^FTSE**. Daily hub aim text partially translates P1/P2 but still assumes internal vocabulary.

### Stale / empty (current repo snapshot)

- No empty top-level Automation tab (automation sidecar present).
- **ingest_deviations** not embedded in `latest.json` but sidecar exists (2026-11-05).
- **Churn/counterfactual** and **knob endurance** embeds in `latest.json` lag ops cycle (**2026-10-30**).
- **learning_tracks_dual_suite** sidecar date **2026-11-01** vs scoreboard **2026-11-06**.
- Daily hub artifact date matches build; verify wall-clock stale banner at London morning boundary.

### Bridge / ack features to preserve in any rebuild

| UI action | Bridge `action` | Persists to (git) | Session overlay |
|-----------|-----------------|-------------------|-----------------|
| Human task **Acknowledge** / **Approve** | `human-task-ack` | `docs/data/human_task_acks.json` (+ board refresh) | `pendingHumanTaskAcks` / optimistic sort |
| Daily hub **Accept** (default / focus) | `daily-focus-ack` | `daily_focus_acks.json`, hub rebuild | `pendingDailyAccepts` |
| Daily **Accept** when action is human gate | `human-task-ack` | same as human tasks | merges with human overlay |
| Daily **Discuss** | `daily-discuss` | `daily_discuss_inbox.json` | `pendingDailyDiscuss`; clipboard phrase |
| Daily focus line **✓** | `daily-focus-ack` | same | reload |
| In-card **options** (defer/park/approve) | routes to above | same | same |

Local dev (`127.0.0.1`): POST `/api/human-task-ack`, `/api/daily-focus-ack`, `/api/daily-discuss` instead of Supabase (`dashboard_bridge.js` + `app.js` @ 9727–9751).

**Not on Automation tab** but same bridge: `progress-report`, `engineering-queue`, `ops-monitor`, `lifecycle-experiment-ack/start` (Lifecycle tab).

**Ingest deviations** explicitly **non-interactive** on Pages (approve/dismiss are CLI hints only @ 5143–5144).

### Rebuild alignment (strategy 2026-11-03)

Promote: **Daily hub** + **Human tasks** + **P1 observe** + **N200 feeder** (if still running sealed unit). Demote or freeze: **Tracks** dual-suite/knob/churn wall, **N201/N206/N210**, **cue_consumer/L652/lab** cards, **Settings achievements**. Add when live: **owner-strategy-book-v0** health (not present in this tab today).

---

*Generated by read-only audit; no repository files modified.*
