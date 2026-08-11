STAGE READINESS
- **Current focus is stage 2b (primary learning track):** `project_objective_excerpt` names AI-judgment paper book vs market datums as the active north star; `learning_tracks_review.primary_learning_track` = `ai_judgment`; `stage_signals.stage_0_core` = true.
- **Stage 0 exit criteria largely met:** `history_run_count` = 7, `backtest.run_count` = 7, `has_learning_tracks_review` = true, four paper tracks in `learning_tracks_summary` (rules, ai_judgment, momentum_grace, technical) all `acted` = true; live screen stays FTSE 350 (`screen_meta.universe` = `ftse350`, `company_count` = 249).
- **Stage 1 decision-review loop is running but epoch evidence is thin:** rules, ai_judgment, and momentum_grace all show `applied` = true with fresh knob epochs; each new epoch notes "Insufficient epoch marks for benchmark span." Technical track: `enough_history` = false, `applied` = false (lifetime marks = 2, lifetime trades = 3).
- **Stage 2b success criterion not met:** `learning_tracks_review.beat_market` = false, `primary_excess_after_costs` = −2.33%, `verdict` = `underperforming`; `beat_control` = true vs rules control (−11.73% excess). Primary track still loses to ^FTSE after costs.
- **Exit-shadow and live exit-timing cohorts immature:** all `exit_shadow.tracks.*.closed_count` = 0; `exit_timing_cohorts` = null; `exit_timing_near_miss.readiness.ready_for_probability_analysis` = false (hold closed = 7 vs target ≥15; swap closed = 7 vs target ≥10).
- **Richness-before-breadth compliant:** `stage_signals.richness_before_breadth` = true; `library_policy.ladder.research_all_graduated` = true with offline breadth across 20 library research markets while live path remains FTSE 350; deferred N1/N17/N15 block live universe and ladder expansion ahead of evidence.

EVIDENCE STRANDS
- **Paper learning tracks (instrumented):** four server tracks under `learning_tracks_summary` with `churn_health` guards (`exit_confirm_screens` = 2, `reentry_cooldown_screens` = 1); `trades_last_7d` totals: rules 6, ai_judgment 6, momentum_grace 5, technical 3; `churn_health.alerts` flag elevated cost drag on rules (14.2%) and ai_judgment (6.7%).
- **Decision-review + counterfactual preview (partial):** rules track has `counterfactual_preview.scope` = `rebalance_log_replay` (5/5 log entries, return_delta_vs_actual = +5.98%); ai_judgment and momentum_grace use `lifetime_trade_replay` with explicit limitation that min_conviction, skip_timing_wait, and AI gates need archived weekly screens for full P&L.
- **Exit-shadow post-exit paths (observe-only, open only):** rules and ai_judgment each `open_count` = 3, `closed_count` = 0; momentum_grace and technical both 0 open / 0 closed; `ingested_this_pass` = 0 all tracks.
- **Archive near-miss exit-timing sim (offline priors, below target):** `exit_timing_near_miss.snapshot_count` = 7; hold_recovery closed = 7 (4 recovered_to_breakeven, 3 underwater_archive_end); swap_rotation closed = 7 (all `inconclusive`); 3 open hold + 3 open swap episodes; `hold_with_data_quality_count` = 10.
- **Backtest / historical analysis (accumulating but short window):** `historical_analysis.window_start`–`window_end` spans ~8 days; top strategies show `observation_weeks` = 1; overlay vs screen excess identical (`downgrade_count` = 0).
- **Offline simulation tracks present:** research_overlay (−8.12% excess, 30 trades), momentum_grace (−2.11% excess, 19 trades); static/trailing_levels flat (0 trades).
- **Missing / null:** `exit_timing_cohorts` = null (no live paper hold-recovery/swap cohort artifact); `model_weights` = null; full knob counterfactual P&L for AI gates (per replay limitations); probability-grade exit-timing estimates (`ready_for_probability_analysis` = false).

AUTOMATION RISKS
- **Knob auto-apply on thin epochs:** three tracks just started new knob epochs with zero epoch marks/trades; further automated steps would optimize on pre-change P&L (`learning_tracks_review.reviews.*.metrics.epoch.note` = insufficient marks) and confound attribution.
- **Technical track premature apply:** decision review already proposes sector_cap/min_conviction changes but correctly blocks apply (`enough_history` = false); auto-apply would tune on 2 lifetime marks and 70.7% cash fraction.
- **Grace / exit-shadow auto-tune:** 0 closed exits across all tracks; `exit_shadow.note` and deferred N25/L85 explicitly defer knob wiring until ≥15–30 closed cohorts — early auto-tune would fit noise.
- **Counterfactual overconfidence:** rules replay covers only 5 rebalance passes and notes pre-logging history needs archive lab (L111); ai_judgment replay blocked 4 buys / 2 orphan sells on max_positions+sector_cap only — scaling knob changes from these previews risks wrong churn/cost tradeoffs (rules simulated cost_drag 6.88% vs actual 14.17%).
- **Breadth expansion while stage 2b underperforms:** library already graduated 20 markets (`research_markets` length) with `observe_sim_after_screen` = true on sp500; live screen expansion (N1/N17) would multiply research spend (scales with researched-name count R per fragments) before primary track beats ^FTSE.
- **Agent/engineering scale without gates:** `open_engineering_tasks` shows ingest work parked; auto-merge scoped narrowly (frag-24); cloud agents cannot reliably `workflow_dispatch` (frag-20) — scaling agent-driven ingest/scoring PRs without human merge increases desync risk (`latest_analysis_review` cites insufficient archived evidence depth).
- **UX overshoot on adaptation cadence:** weekday paper-auto runs daily but decision-review knob learning is epoch-gated; presenting "self-improving" narrative (frag-14) ahead of ≥2 epoch marks invites manual knob chasing.

COUNTERFACTUAL GAPS
- **Would proposed knobs have improved full-track P&L from inception?** Cannot answer with current trade/lifetime replays alone — needs **archive weekly-screen rebalance replay** (L111 scope; rules preview already flags this gap).
- **Do AI-judgment gates (adjusted_signal, research accumulate) help or hurt vs rules on identical history?** Cannot answer — ai_judgment replay lacks PIT memo joins; needs **PIT rebalance_log bootstrap for ai_judgment** (L113).
- **Hold buffer vs rotate on downgraded-but-rising names?** Cannot answer for names actually held — archive near-miss uses below-buy-tier gate (`near_miss_gate.default_signals` = hold); needs **live paper exit_timing cohorts** (`exit_timing_cohorts` currently null) plus reconciliation with archive near-miss denominators.
- **Does momentum grace reduce winner churn without style drift?** 0 closed grace exits; momentum_grace track −2.83% excess, 5 lifetime trades — needs **exit_shadow closed cohorts with grace_vs_rotation splits** and longer paper marks.
- **Did swap rotations beat holding the exit?** All 7 closed swap episodes = `inconclusive`; needs **more closed swap_rotation episodes on live paper tracks** (target ≥10) with paired sell/buy forward returns.
- **Which sim is the canonical evaluation book?** Browser localStorage, archive ftse-simulate, and server learning tracks coexist without declared anchor — needs **explicit track canonicalization artifact / dashboard panel** (L106/L107) before cross-source counterfactuals.
- **Do overlay research downgrades predict forward underperformance vs screen-only?** `simulation.comparison_note` = identical returns to screen-only over 7 periods — needs **thicker archived overlay comparison** (`historical_analysis.overlay_comparison` sample_count = 63, observation_weeks = 1).

FRAGMENT CLUSTERING
**Exit timing & counterfactual evidence (frag-01, 02, 03, 10, 11, 12)** — Live paper exit-timing cohorts are absent (`exit_timing_cohorts` null) while archive near-miss supplies below-buy-tier priors (7 closed hold, 7 closed swap, all swap inconclusive); the core unresolved tension is rotate-on-downgrade vs ride recognition-phase momentum, and exit-shadow cannot yet score post-close regret without closed cohorts or risk-adjusted framing.

- PROMOTE frag-20260811-01 → **Reconcile live vs archive exit-timing denominators** — Shared episode definitions before comparing hold→breakeven vs swap-success rates. Revisit when: `exit_timing_cohorts` artifact exists and `exit_timing_near_miss.readiness.hold_closed_count` ≥ 15.

**Paper-track canonicalization & cadence (frag-13, 14, 15)** — Browser localStorage books and server `paper_automation` tracks share strategy names but differ on churn guards and decision-review inputs; multiple parallel sims (browser, archive, server) lack a declared evaluation anchor while UI narrative overstates adaptation frequency vs weekly/epoch-gated review.

- PROMOTE frag-20260811-13 → **Align browser vs server paper books** — Label or align hold-buffer/reentry rules before tuning conviction/sector caps from learning data (L106). Revisit when: `learning_tracks_churn_health` reaches ≥8 weeks of marks per L106 revisit trigger.

**Stage doctrine & universe gating (frag-09, 16)** — Richness-before-breadth holds (FTSE 350 live, 20 library markets offline), but primary track still underperforms ^FTSE after costs while infra runs ahead; no explicit doctrine trigger to pause offline breadth when stage 2b excess stays negative.

**Ingest depth, scheduling & stall metrics (frag-17, 18, 19)** — Canonical ingest bootstrap may inflate zero-body buy-tier stall counts before depth pays off; Sunday full screen refresh vs capped weekday ingest may leave buy-tier memos shallow; ops micro-compile can false-green unchanged zero-body stalls.

- PROMOTE frag-20260811-18 → **Post-Sunday full-cap ingest pass for buy-tier** — Guarantee memo depth after weekly screen refresh. Revisit when: next Sunday email run shows buy-tier names with `has_body: false` on primary filing gaps.

**CI, horizon ops & cloud triggers (frag-04, 05, 07, 08, 20)** — Ruff autofix on cursor PRs works but ~5 min lag looks like failure; pytest and committed-data checks remain manual; horizon scan payload exists but committed review cadence and unified runbook anchor are unset; cloud agents depend on external cron/PATs for production triggers.

**Offline parallel sims & promotion criteria (frag-21, 22)** — Recurring observe sims after library screen-lite are infrastructure (`history_run_count` = 7, single observation week) not yet signal; no defined gate for promoting a second live learning track vs keeping frozen-signal observe mode.

**Engineering throughput & artifact freshness (frag-23, 24)** — Compile/dispatch races and pre-merge analysis_review can desync dashboard conclusions from merged code; auto-merge limited to narrow CI-fix tasks caps ingest/scoring self-improvement throughput.

**Research cost scaling (frag-25)** — Spend scales with researched-name count R (library `executed` = 26 memos this run, £10.4 weekly_ops spend) not universe N; widening buy-tier caps or markets without hard weekly cap risks cost dominance.

- DROP frag-20260811-06 — Duplicates deferred L120 (fragment + horizon scan is the capture path; transcript mining explicitly deferred).

- DROP frag-20260811-09 — Duplicates deferred N1/N17 richness-before-breadth gating already captured in `open_deferred_ideas`.

PARK
- **Unified ops review runbook anchor** — Register weekly `analysis_review`, monthly horizon scan, and quarterly deferred-review as one calendar/runbook sequence with owners and artifact paths. Revisit when: first committed `horizon_scan.md` review completes and frag-08 operational-rhythm gap persists.

- **CI autofix lag visibility** — Post a PR comment when cursor-branch ruff autofix push completes (~5 min lag) so authors do not treat transient red checks as unresolved failures. Revisit when: next cursor/* PR shows red CI despite autofix commit pending.

- **Ingest stall third state (bootstrap vs true stall)** — Distinguish counted zero-body buy-tier names during canonical bootstrap from persistent post-depth stalls in monitoring metrics. Revisit when: `eng-20260729-01` CH PDF fetch unparked and zero-body count unchanged after successful body extraction.

- **Analysis-review artifact freshness gate** — Block or flag dashboard/analysis conclusions when compile/dispatch or pre-merge screens desync merged code from reviewed artifacts. Revisit when: next Sunday `analysis_review` runs on screens generated before an ingest/scoring merge lands.

- **Offline observe-sim promotion criteria** — Define minimum archive depth and local-benchmark excess bar before any non-UK market graduates from frozen-signal observe sim to a second live paper learning track. Revisit when: `library_policy.observe_sim_markets` expands beyond sp500 and `history_run_count` ≥ 12.

- **Stage 2b negative-excess doctrine pause** — Explicit policy for pausing new offline library breadth or infra expansion while `primary_excess_after_costs` < 0 and `beat_market` = false. Revisit when: primary track accumulates ≥4 post-knob epoch marks without beating ^FTSE.

ACCELERATE
1. [offline_sim] Archive rebalance replay for rules knob set (min_conviction 0.55, sector_cap 0.2) from first logged pass — full P&L path vs 5-entry preview; validates whether +5.98% return delta vs actual holds on longer window.

2. [paper_knobs] Hold ai_judgment and rules knobs fixed for one epoch — accumulate ≥2 epoch marks and ≥1 epoch trade before any human decision-review apply; isolates cost/concentration effects of 2026-08-11 knob changes (human gate: manual review only).

3. [paper_churn] Buffered-hold counterfactual on rules/ai_judgment — replay last 7d exits (3 full_exits each track, exit_streak=1 on HIK.L/ITV.L/FGP.L) with exit_confirm_screens 1 vs 2; quantifies churn-guard sensitivity given 14.2% vs 6.7% cost drag.

4. [offline_sim] Extend archive near-miss to held-ticker episodes — rerun hold_recovery/swap_rotation on names that appeared in rebalance_log with buy-tier history (not only below-buy-tier gate); closes gap that 7/7 swap verdicts are inconclusive for actual book decisions.

5. [monitoring] Epoch-zero datum dashboard slice — surface per-track epoch NAV, post-apply trade count, and benchmark span availability (all tracks currently "Insufficient epoch marks"); makes stage 2b underperformance legible before further knob experiments (human gate: observe-only panel, no auto-apply).
