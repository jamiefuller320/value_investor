EXECUTIVE SUMMARY
The single assessment model is **ai_judgment_matched30_fair** (primary) vs **buy_tier_matched30_fair** (unfiltered buy-tier control). Headline: primary total return **-2.4%** vs FTAL.L **+0.6%** since 2026-10-15 — **too few marks to judge**; on the common window the filter shows **+0.7%** vs control (**primary_vs_control.difference +0.68%**, not significance-tested). Active scoreboard rows: primary **-2.38%** vs benchmark **+0.57%**, statistics **insufficient_data** (16 marks); control **-2.55%** vs **+0.57%**, **insufficient_data** (16 marks); legacy Suite B floors **buy_tier_level** **+1.44%** vs **-0.09%**, verdict **indistinguishable_from_noise** (43 marks); **buy_tier_level_dca** **+1.55%** vs **+0.97%**, **indistinguishable_from_noise** (32 marks). Running twins on common marked days: matched-30 AI twin **-1.58%** vs parent **ai_judgment_fair** (10 days); control construction twin **-3.81%** vs **buy_tier_level** (15 days). **learning_tracks_review** verdict **underperforming** (**beat_market** / **beat_control** false). Paper P&L is still seeding; the biggest modelling gap is **weak directional calibration** (**trajectory_evidence** 1w **prediction_hit_rate 0.3675**, focus **strong_buy->buy**) plus **loser forensics** (**highest_failed_family dividend 12, garp 12**). The largest **system** gap is **produce**: **research_skipped_already_done** with **executed=0** and **547** already-researched skips while **weekly_ops** still shows **$66.10** unused.

PERFORMANCE DIAGNOSIS
- **Primary vs control vs market:** Since 2026-10-15, primary excess **-2.95%** vs FTAL.L; control **-3.12%**; filter-only edge **+0.68%** on total return in the common window — headline says not yet testable.
- **learning_tracks_review (after costs):** Primary excess **-1.45%**, control **-0.57%**; portfolio verdict **underperforming**, not beating market or control on the stated criterion.
- **Cost drag:** Fair configured buy cost **0.525%** per side; at **3%** stress cost, primary stress excess **-11.16%** vs fair **-2.95%** — turnover would hurt if stress costs applied.
- **Mark thickness / trust:** Primary and control each **16 marks**, statistics **status: insufficient_data** (15 periods) — no **positive** verdict; do not treat NAV as filter-skill evidence. Suite B **buy_tier_level** / **buy_tier_level_dca** have more marks but only **indistinguishable_from_noise** — observe only, not adoption.
- **Hypothesis mix (primary):** **loser_share 5.9%**, **within_tolerance true**, **broken_loser_count 0** — underwater names look like intact value losers, not a broken-book signal.

SIGNAL & BACKTEST FINDINGS
- **Archived backtest** (**run_count 32**): 84d **buy** excess **+5.68%** (n=381); **strong_buy** **+2.52%** (n=144); **hold** **+2.70%** (n=1093); **avoid** **-1.59%** (n=304); **insufficient_data** 84d **-9.46%** (n=4).
- **historical_analysis** (**run_count 32**): 7d **overlay:buy** smoothed excess **+0.68%** (888 obs, 14 weeks); **research:accumulate** **+0.86%** (493 obs, 4 weeks); 84d overlay smoothed excess **+5.85%** vs screen **+5.43%**.
- **Offline sim** (**simulation**, 32 periods): **static_levels** / **trailing_levels** excess **-1.15%**; **research_overlay** / **momentum_grace** **~-44.9%** excess (heavy trade/cost paths) — lab churn, not live primary.
- **trajectory_evidence:** **labeled_event_count 1618**; hit rates **1w 0.3675**, **4w 0.4329**, **8w 0.4518**, **12w 0.4592**; **weeks_to_realization** median **1.0**, **within_4w_rate 0.8201**. Model-focus hypotheses (not live-screen edits): **strong_buy->buy** 1w **positive_rate 0.325** (n=40); **hold->buy** **0.329** (n=79); **1w horizon_hit_rate 0.3675** (n=1208).
- **loser_snapshot_cards:** **card_count 91**; cohorts **avoid 61**, **failed_buy_alumni 33**; **top_failed_families:** dividend 12, garp 12, cheapness 7, quality 5, risk 4 (e.g. **ADM.L** cheapness/dividend/garp/risk failures on avoid).
- **chart_outcome_review (observe-only):** Verdict **has_terrible**; **stop_hit 8**, **terrible 97** / 1289 charts; well-timed **RWS.L** (+66.8%); weakest terrible **LNZ.VI** (-48.5%).
- **exclusion_universe:** **ready_for_priors true**; recommended **u2** (“Exclude avoid + timing wait”) **cumulative_exclusion_alpha -0.00195** over 31 week-pairs (best among pool-size gates, not positive alpha).
- **exclusion_ladder_replay:** **ready_for_shadow_spawn false** despite **primary_return_delta_vs_actual +0.0052** on **u2** (**shadow_spawn_supported false**).

PAPER TRACK COMPARISON
- **assessment_scoreboard:** Primary **ai_judgment_matched30_fair** **-2.38%** vs **+0.57%** benchmark; control **buy_tier_matched30_fair** **-2.55%**; filter gap **+0.68%** on common window since 2026-10-15.
- **learning_tracks_review:** Same primary/control IDs; **beat_market false**, **beat_control false**; review metrics excess after costs primary **-1.45%**, control **-0.57%**; **applied false**, no knob proposals (“No knob change warranted”).
- **knob_calibration_priors:** No matched-30-specific prior in payload; legacy **ai_judgment** / **rules** priors **confidence low**, **changed_vs_current** on **max_positions** / **min_conviction** — seed shadows only, not primary epoch knobs.
- **exit_timing_cohorts (live primary):** **ready_for_probability_analysis false** — hold closed **9** (target ≥15), swap closed **0** (target ≥10).
- **exit_timing_near_miss (archive):** **ready_for_probability_analysis true** — hold closed **729**, recovery **87.65%**; swap closed **748**, replacement outperformed **42.11%**.
- **exit_timing_reconciliation:** **hold_recovery_rates_directly_comparable false**; **archive_may_inform_priors_while_live_collects true** — live primary hold recovery **66.67%** (n=9) vs archive **87.65%**; do not blend rates.
- **exit_shadow:** **0 closed** episodes on all active tracks (including primary **open_count 9**) — post-exit learning still empty.
- **hypothesis_integrity:** Primary **within_tolerance true**, **balancing_hint tolerate_intact_losers**; control matched-30 **loser_share 26.7%** still **within_tolerance**; no **selection_feedback_flags** on active assessment books.
- **entry_dca_overlay:** **ready_for_cadence_analysis true**; **leading_cadence dca_4x_weekly** (117 wins); **tracks_with_closed 17**; **model_independent_hint true**.
- **entry_dca_adoption:** **acked true**; **current_stage out_of_sample_first_entry** (open, not ready) — follow plan gates; do not execute DCA on primary.

SYSTEM GAPS
**Probe answers (JSON only):**

1. **Is the learning consumer seeing paid research?** Partially wired: **apply** buy-tier **70/70**, strong-buy **16/16**, but **wired_missing_committed_verdicts 1**; meanwhile **ladder_research executed 0** with **547** already-researched skips — produce did not refresh bodies this pass.
2. **Would a new market inherit the miss?** Yes pattern risk: **euro_depth** runs screens (**last_screen 2026-11-08**, 59 observe snapshots) with **learning_ready null** / **trajectory_ready null** while ladder **dedupe_skipped_count 404** and **fresh_memo** skips dominate — same dedupe-without-rememo shape as today.
3. **Green counters if quality were zero?** **healthy_counter_distrust** explicitly warns: **remaining_weekly_ops_usd 66.1** + **executed 0**, **already_researched_count 547**, and **live_committed thin_or_zero_body 0** (FTSE committed shell) can stay green without feeding overlay consumers.
4. **Freshness vs rememo dedupe?** **rememo_eligible_count 0**, **rememo_action none**, **dedupe_skipped_count 404**; skips cite **fresh_memo** — existence/fresh-bit blocks rememo even when **focus_library_research mode_initial 1** on euro_depth.
5. **Observe clocks on ingest-healthy markets?** Yes accumulating: multi-market **observe_snapshots** 52–77 with **filing_ready/learning_ready null** on most; **sp500** alone shows **filing_ready/learning_ready/trajectory_ready true** — clocks run ahead of learning_ready parity.
6. **Sunday rememo on admitted buy-tier vs focus only?** **rememo_action none**; **admitted_rememo** lists 22 markets but last ladder **focus_market euro_depth**, **executed 0** — no cross-market rememo execution this cycle.

**Flags:**

- **research_skipped_already_done** — layer **produce**; masked by **already_researched_count 547**, **dedupe_skipped_count 404**, and **weekly_ops budget_flag enforced** while **executed=0**.
- **unused_budget_zero_research** — layer **produce**; **remaining_weekly_ops_usd 66.1** looks healthy while **executed=0**.

**Distinctions:** Written memos (**live_committed 104/104 with verdict**) ≠ wired gap (**1 missing verdict on apply path**); filing-grade euro_depth samples ≠ **learning_ready** on the clock; **persist_hole false** ≠ produce hunger on rememo.

PROPOSED EXPERIMENTS
1. **[scoring]** Offline family-weight stress on avoid cohort dividend/garp failures (loser cards + **hold->buy** / **strong_buy->buy** trajectory keys) — human ack **ana-20260921-02** — expected learning value: test whether quality+dividend gate tightening reduces opinion-flip losers without live N3 mutation.
2. **[paper_churn]** Archive hold-vs-swap probability strand (**exit_timing_near_miss** hold **729**, swap **748**, **ready_for_probability_analysis true**; pair with **exit_timing_reconciliation** archive priors only) — ack **ana-20260921-04** — expected learning value: quantify swap vs hold before live primary closes **9** hold episodes.
3. **[offline_sim]** Exclusion-ladder prior replay for **u2** (“Exclude avoid + timing wait”, **cumulative_exclusion_alpha -0.00195**, **ready_for_priors true**) on matched-30 construction — expected learning value: cost-aware counterfactual before any shadow book (human gate; not auto-apply).
4. **[ops]** Break **research_skipped_already_done** produce stall — rememo/body-lag queue ahead of **fresh_memo** dedupe when **rememo_eligible_count 0** but learning_ready null on euro_depth-style markets — expected learning value: research spend reaches overlay/trajectory consumers, not just skip tallies.
5. **[monitoring]** Clear experiment ledger acks: **ana-20260921-02**, **ana-20260921-04** (**status recommend**, **human_ack_required true**; gate marks/excess unset) — expected learning value: promotes scoring/churn work without auto-apply.

DEFER
- **Exclusion shadow spawn** — **ready_for_shadow_spawn false**, **shadow_spawn_supported false**; revisit when replay gate binds with ≥2 acted log entries and human runs `ftse-exclusion-ladder-replay spawn-shadow`.
- **Live decision-review knob apply** — primary/control **insufficient_data** and significance gate; revisit only if **statistics.verdict** becomes **positive** or **negative** with thick marks.
- **DCA execution on primary** — **entry_dca_adoption.acked true** but stage **out_of_sample_first_entry** blocked; revisit when matched-30 first-entry gates clear and **paper_execute_graduated** unblocks.
- **Auto-merge paper-auto / assign_signal / evolution** — no JSON trigger for promotion; revisit only after human experiment queue and explicit engineering charter.
