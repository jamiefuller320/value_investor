# FTSE progress report

Generated `2026-09-02T12:32:11+00:00` · overall **WARN**

Infrastructure and offline library are ahead of schedule; the primary AI learning track is running but not yet beating the market.

**Current focus:** stage_2b · **Screen companies:** 248

## Overall progress

| Stage | Status | Focus |
|-------|--------|-------|
| 0 UK quant core | complete | FTSE 350 screen, paper funds, post-open automation |
| 1 Decision-review learning | in_progress | Book learns from outcomes after costs |
| 2b Primary learning track | in_progress | AI-judgment paper book vs ^FTSE and rules control |
| 3 Library-ready global data | complete | Offline multi-market fundamentals without live screen impact |
| 4 Controlled universe expansion | not_started | First non-UK live screen at FTSE quality bar |
| 5 Self-improving automation | not_started | Walk-forward rule evolution with frozen signals |

### Strengths

- FTSE 350 live screen and published dashboard are operational.
- Offline library: 21 graduated markets (focus: euro_depth).
- Ops automation in place: daily monitor, tier-1 backup, external cron scheduling.
- Engineering queue: 3 open, 63 merged supervised tasks.
- AI-judgment track beating rules control (-19.2% vs -28.2% excess).

### Gaps

- Primary AI track still below ^FTSE after costs (-19.2% excess; history still thin).

### Suggested next actions

- Let the learning loop accumulate before adding tracks or knobs.
- Sunday chain: orchestrator → analysis-review → data-backup (cron now wired).
- Prioritise buy-tier filing depth (Companies House + RNS body fetch).
- Keep library growing offline; defer live universe expansion until stage 2b shows edge.

## Actionable now

- Deferred `now`: **0**
- Open fragments: **23**
- Proposed review tasks: **10**
- Open engineering tasks: **3**

### Deferred — act now (`ftse-defer status … now`)

_None._

### Deferred — not now (review triggers)

- **N1** Widen universe first (AIM / Europe / worldwide) — Learning bottleneck is weekly periods, not name count; worse data/liquidity; no code path _(revisit: FTSE 350 decision-review loop is stable and there is a clear data story)_
- **N10** Node 20 Actions deprecation nit — Harmless noise _(revisit: Forced by action upgrades)_
- **N11** Sync private live holdings into git/CI — Privacy; dashboard localStorage must stay private _(revisit: Private bridge (not git) is designed)_
- **N12** Browser-only fully independent automation — Only runs when dashboard is open _(revisit: Server Action/ftse-paper-auto insufficient)_
- **N13** Capital at risk / live broker automation (stage 6) — Do not connect live capital or broker APIs until stages 2–5 are proven in paper with cost-aware review. _(revisit: Manual packs trusted, decision-review learning working, and multi-market paper track proven)_
- **N14** Live Trading 212 API integration — Do not wire live order placement yet. T212 API is beta (non-idempotent orders); project is still at stage 2 manual packs. Prefer demo/paper path first when broker work starts. _(revisit: Stages 2–5 exit criteria met and human override workflow defined (see N13))_
- **N15** Expand ladder before T212 catalogue verification — Do not grow new offline markets from allowlist assumptions alone; hang_seng/sti/asx200 look 100% on suffix heuristics but need catalogue hit rates before further APAC breadth. _(revisit: Catalogue fetched and alignment_report.json shows per-market catalogue_hit_pct)_
- **N16** Do not chase live Cursor usage API before envelope calibration — Live usage API (L32) is blocked on Cursor exposing credits to CURSOR_API_KEY. Prefer running the £30/week estimated gate for a few cycles and recalibrating estimated_memo_usd (L52) before investing in billing integration. _(revisit: Cursor documents a usage/credits API for CURSOR_API_KEY, or estimated vs billed spend diverges badly after 2–4 constrained weeks)_
- **N17** Do not expand live screen beyond FTSE 350 yet — Library breadth is far ahead (16 graduated markets). Stage 4 live expansion should wait until stage-2 decision packs are routinely trusted and decision-review has enough marks to adjust knobs. _(revisit: Stage 2 exit criteria met and decision-review has actionable excess-return history)_
- **N18** Do not let AI judgment own live capital path yet — Primary learning track is paper-only. Keep live broker automation and any promotion of AI gates to real capital off until the AI-judgment book shows persistent excess vs ^FTSE and vs the rules control in walk-forward review. _(revisit: AI judgment paper track shows persistent excess vs screen-only and FTSE in walk-forward review)_
- **N19** Do not backdate research revisions for past paper decisions — Extending source lookbacks and re-running memos is fine going forward, but inventing historical revisions as-of past run dates would leak post-period knowledge into AI-judgment / historical_analysis PIT overlays. _(revisit: Never as a learning shortcut; only reconsider if building a separate counterfactual research lab outside the live paper track)_
- **N2** Evolutionary / survival-of-the-fittest parallel sims — Sparse weekly history leads to overfitting; high-churn genomes look fit until costs dominate _(revisit: Many tens of weekly snapshots + cost-penalised walk-forward fitness)_
- **N20** Companies House Streaming API for realtime filings — Streaming API pushes company/filing changes over long-lived connections; our research path only needs on-demand REST GET for search, filing-history, and document download. Keys are not interchangeable with REST. _(revisit: Need near-realtime UK filing alerts outside weekly research cycles)_
- **N23** Do not add momentum overlay to base value screen — Momentum should remain an exit/hold overlay or offline sim track, not a new factor family in assign_signal(). Mixing value entry with momentum hold rules in the primary quant signal would blur attribution and conflict with N3 (research overlays, frozen base screen). _(revisit: Explicit product decision after walk-forward evidence that a momentum grace rule beats trailing stops and screen-only exits on cost-adjusted excess return)_
- **N24** Do not route automated paper-auto or decision-review through LLMs — Learning loop knobs (decision-review, future L85 grace auto-tune) must stay rule-based on structured JSON marks. Pro+ model access is for human/agent synthesis and selective research only — not live paper trading decisions. _(revisit: Never for live automation; only reconsider if building a separate experimental LLM paper track with its own control datum)_
- **N25** Keep exit-shadow cohort observe-only until maturity — Post-exit shadow (exit_shadow.json / exit_shadow_review.json) is wired for all three paper tracks but must stay read-only for knob changes until per-track closed cohorts mature. Do not wire verdicts into decision-review or L85 grace auto-tune prematurely. _(revisit: learning_tracks_exit_shadow.json shows ≥15 closed exits per track with stable 1/4/8/12-week scoring; L85 grace threshold (≥30 grace exits) met separately before any auto-tune)_
- **N26** Do not nudge decision-review portfolio knobs below history floor — Automated decision-review knob steps (max positions, timing strictness, conviction floor, sector cap) should not fire until the target track has ≥4 weekly marks and ≥2 closed trades. Below that floor, accumulate data hands-off. _(revisit: Each paper track (ai_judgment, rules, momentum_grace) crosses the floor independently; then enable per-track knob review in decision-review)_
- **N27** Gate AI judgment on confidence or memo_quality thresholds — Tempting to filter accumulate names by research_confidence or memo_quality, but that is a live paper knob before observe-only counterfactuals exist; keep verdict/adjusted_signal gating until evidence. _(revisit: After observe-only counterfactuals show confidence/memo_quality predict adverse outcomes)_
- **N28** Do not fold full memo-utility synthesis into horizon scan — Do not move weekly memo usefulness synthesis (gap-fill rollups, per-ticker open-question triage, research_model_suggestions eng compile) into the monthly horizon agent. Horizon may still strategically ask whether memo schema should better aid AI judgment (see L141); implementation stays in the research/post_run loop. _(revisit: If someone proposes putting gap-fill/post_run_review ownership inside horizon_scan.py)_
- **N29** Wire macro_context into automated exit veto — macro_context is research-only by design (policy use_in_scoring=false). Auto-blocking sells on macro markers would blur attribution and fight the stage-2b learning loop before panic circuit rules are calibrated offline. _(revisit: Portfolio panic circuit breaker is designed and backtested offline)_
- **N3** Rewrite assign_signal() from LLM research — Research should overlay, not own the primary quant signal _(revisit: Explicit product decision to make LLM output part of base signal)_
- **N4** More cheapness / P/E-variant screens — Saturated; adds noise _(revisit: Per-model attribution shows a cheapness gap)_
- **N5** DCF as a screen model — yfinance too thin across FTSE _(revisit: Better fundamentals (RNS/paid API))_
- **N6** ESG / sentiment as quant models — Belongs in research unless a dedicated feed exists _(revisit: Paid ESG/sentiment source available)_
- **N7** Level 2 / ADVFN order book — Weak fit for weekly batch without licensed depth _(revisit: Licensed L2 + trade-plan overlay needed)_
- **N8** Resource/reserve miner metrics — Sector-specific, hard data _(revisit: Dedicated resources feed)_
- **N9** Extra storage compression / same-day cron micro-tests — Explicitly skipped after earlier storage/cron work _(revisit: Local output/history/ pain returns)_
- **N31** Backfill all buy-tier other-RNS filing bodies — Most remaining indexed_without_body rows are category=other (PDMR, own shares, etc.). Technically fetchable via existing URLs but intentionally capped by max_bodies; full backfill is low value vs period/CH gaps. _(revisit: Priority period gaps (annual/interim/trading_update/CH accounts) are closed on buy-tier and research quality still cites missing other-RNS text)_
- **N32** Full filing ingest on non-UK library strong-buys ahead of tier — Cloning FTSE RNS/CH full ingest onto library strong_buy shortlists would poorly probe EU/US fetch issues (wrong source stack) and dilute stage-2b/metrics focus. Prefer metrics grow stalls + market-aware filing smoke after Layer B is stable; L30 memos already exist for selective research. _(revisit: Phase 2 shard shows beat_control with stable metrics, and a market-aware filing provider exists for that market (SEC/SEDAR/etc.))_
- **N33** Do not search assign_signal thresholds for historical edge — Retrospective tuning of frozen screen filters (composites, pass rates, quality floors) to catch winners over the monitoring period would look like edge today but conflicts with N3 and stage-5 counterfactual safety; keep such work research-only offline_sim if ever run, never auto-write into assign_signal. _(revisit: Explicit product decision to override N3 / frozen-signal regime for a controlled research experiment)_
- **N34** Stage-4 live universe expansion before 2b edge — Keep live screen on FTSE 350; offline library (iseq20 screen-lite) is enough until primary AI track beats ^FTSE after costs. _(revisit: Stage 2b AI judgment excess vs ^FTSE is positive with thick history)_
- **N35** Do not use weekly historical shadow rewind as promotion proof — Rewinding competing shadows through known history to pick a winner overfits the same window used for bootstrap; keep weekly consistency as a diagnostic, and reserve promotion for forward endurance vs market/rules. _(revisit: Only if a held-out weekly archive path (true walk-forward / purged CV) is implemented under L111)_
- **N36** Do not auto-promote surviving shadows into ai_judgment — Keep human gate between endurance survivors and primary config; auto-promotion would couple lab noise to live epochs before history is thick enough. _(revisit: Multiple shadows have multi-month surviving status and primary still beats rules+market with human-seeded priors)_
- **N38** Live capital dynamic rotation before paper evidence thickens — Broad-portfolio capital recycling (skim end-of-cycle, fund new growth-cycle entries) should stay paper/observe-only until primary track beats ^FTSE and rules control with graduated sizing shadow, not just equal-weight top-N rotation. _(revisit: Stage 2b exit criteria met; graduated-sizing shadow beats equal-weight in walk-forward replay; human tasks checklist promotion gate signed off)_
- **N39** Full-universe deep memo PIT replay — Re-running full research memos for every name on each archived weekly turn is out of scope; use logged screen/overlay fields at t instead (see ftse-trajectory-evidence). _(revisit: Filtered cohort track active AND loser_pattern_lab shows gaps only addressable via memo-depth (not quant features))_
- **N40** Auto-spawn exclusion ladder shadows from Sunday readiness — exclusion_ladder_replay writes ready_for_shadow_spawn but spawn remains a manual CLI. Do not auto-spawn yet — keep human gate like knob prior promotion; only revisit when checklist and endurance gates mirror calibration shadows. _(revisit: exclusion ladder ready_for_shadow_spawn true for >=4 weeks and filtered_cohort_track vision phase approaches activate)_
- **N41** Auto-spawn exclusion ladder shadow when ready — ready_for_shadow_spawn is computed Sunday but spawn-shadow stays manual; auto-spawn would couple lab noise to weekday tracks before human ack. Keep CLI spawn + register checklist gate instead. _(revisit: Exclusion u4 shadow has been manually spawned and observed for >=4 weeks with clear ops load)_
- **N42** Whole-index research memos for trajectory learning — Do not memo the full FTSE hold tier to learn trajectory shifts. Screen archives + transition ledger + boundary watch already cover full-range opinion migration; blanket memos add noise and dilute buy-tier learning. _(revisit: Trajectory prediction hit rates stay below chance after ≥13 archive weeks AND boundary-watch model_focus_candidates are exhausted)_
- **N43** Replace technical-mode hard stops with hypothesis gate — Technical paper track still auto-sells on tactical stop hits. Do not replace until hypothesis_integrity + exit-timing hold-recovery show that thesis-broken exits beat crude stops after costs. _(revisit: hypothesis_first_exit has >=8 weekly marks and exit_timing hold-recovery ready_for_probability_analysis)_
- **N44** Auto-tune selection knobs from in-portfolio loser family feedback — selection_feedback_flags attribute loser family failures vs non-losers. Do not auto-apply model weights or exclusion knobs from this until shadow evidence links flags to forward excess. _(revisit: hypothesis_integrity selection_feedback_flags stable for >=8 weeks and a scoring shadow beats control)_
- **N45** More FTSE ingest runs for enrichment — FTSE buy-tier hard gaps are closed (0 unmeasured/zero-body/indexed-without-body). Extra daily FTSE ingest slots would mostly re-walk strong_buy names with sufficient bodies; ROI is low vs euro_depth sprint. _(revisit: Buy-tier unmeasured or zero-body rises after a Sunday screen, or residual indexed-without-body returns on live path)_
- **N46** More frequent engineering task generation to accelerate enrichment — Engineering tasks fix stalled ingest/parsers; they do not create filing bodies. Queue is empty and FTSE/euro ingest are progressing without open ingest tasks — drafting more eng work would not speed enrichment. _(revisit: Ingest health shows multi-run stall with flat unmeasured/zero-body and micro-compile is not firing)_
- **N47** Do not add sp500 to ingest_parity_markets until learning-depth is green — Canonical S&P filing + 12-week trajectory must be green (learning_ready) before recording ingest parity. Adding it earlier would drop the market to 4-target maintenance while thin bodies and indexed_without_body remain. _(revisit: ftse-library learning-depth --market sp500 reports learning_ready true)_
- **N48** Flip live FTSE paper books off 3% stress costs — Keep primary FTSE learning on the 3% per-side stress case for churn discipline. Fair T212-shaped costs exist via ftse-trading-costs assess and shard/observe defaults — do not silently rewrite live configs. _(revisit: Human decides stress vs fair is the primary learning metric, or live/demo broker path starts)_
- **N49** Do not invent new paper tracks or knob churn to 'fix' stage 2b excess — End-of-week read: AI still -20% vs FTSE after costs. Adding tracks/knobs or live breadth will not create edge; hold knobs (hor-20260811-02) and let weekday marks accumulate. _(revisit: AI-judgment excess after costs is non-negative for several weeks with enough marks, or weekly review explicitly re-opens knob policy)_
- **N50** Treat Yahoo quarterly cashflow as optional for UK memo excellence — yahoo_quarterly_cashflow is thin on nearly every FTSE memo; do not block excellent/strong narrative quality on it. Prefer filing OCF bridges and gate/suppress empty Yahoo TTM rather than waiting for Yahoo series. _(revisit: If Yahoo UK quarterly cashflow coverage improves or a primary filing OCF bridge is standardized in every memo)_
- **N51** Consider making value_investor private — Public visibility widens fork-PR workflow_run attack surface. Private repo would reduce outsider triggerability of privileged responders; weigh against Pages/dashboard sharing needs. _(revisit: If further secret exposure incidents occur or Pages no longer needs a public repo)_
- **N52** Fit a new screen ruleset from Suite A stress P&L for Suite B — Do not reverse-engineer a full new screen/model from Suite A after-cost returns — those P&Ls are stress-distorted and history is thin. Suite B should warm-start from current AI+rules books and transplant stress-surviving knobs (conviction, exit confirms, cooldowns) as priors only. _(revisit: Suite B has a thick forward window and a separate offline rules lab is justified)_
- **N53** Mirror every Suite A shadow into Suite B (full 2x fork) — Do not duplicate all calibrated/exclusion/exploratory shadows onto fair costs. Suite B should validate promotion candidates (start AI+rules); full fork doubles books, burns the ~5 experiment / ~4 shadow budget, and thins attention without much extra signal. _(revisit: Suite B AI+rules endurance is trusted and human triage load is light)_
- **N54** Do not treat Suite A conviction floors as Suite B policy — High min_conviction discovered under 3% stress is a churn-survival filter for relative AI-vs-rules assessment. With fair costs, the same floor can starve deployable edge. Keep A floors on A; let B run suite-local conviction (including easing) and only promote floors that still help after fair costs. _(revisit: Someone proposes copying ai_judgment min_conviction onto ai_judgment_fair as a permanent lock, or using A epoch success alone to claim deployable conviction policy)_
- **N55** Live sentiment scoring from mined news phrases — Do not wire bag-of-words or lexicon sentiment into screen weights or paper knobs. Open-source news + phrase mining may later inform research memos or event tags; treating it as a quant model remains premature (extends N6). _(revisit: Phrase-trajectory panel shows out-of-sample lift on trajectory flips, and analysis-review proposes a gated experiment)_
- **N56** Auto-write FCF bridges without human review — Do not auto-author policy_fcf bridge numbers; choosing company-adjusted vs filing-aligned remains a judgment call. Keep human_gate for bridges. _(revisit: If an explicit deterministic source policy covers every buy-tier mismatch without filing judgment)_

### Open fragments (monthly horizon triage)

- **frag-20260811-02** Archive near-miss sim gives offline priors for below-buy-tier names; reconcile with live cohort counts before trusting exit-timing knobs.
- **frag-20260811-03** Counterfactual evidence still thin: near-miss archive does not yet answer what would have happened on names we actually held or swapped.
- **frag-20260811-04** CI ruff autofix on cursor/* PRs works but ~5min lag can look like unresolved failure — PR comment on push should reduce confusion.
- **frag-20260811-05** Autofix covers ruff only; pytest failures and check_committed_data_json still need manual fix or main-branch ci-fix-responder.
- **frag-20260811-10** Value downgrade vs rising price: rotate on screen downgrade vs ride recognition-phase momentum while the name is no longer cheap — core tension for exit overlays, not stock picking.
- **frag-20260811-11** Bounded momentum grace may cut winner churn but risks style drift — holding non-cheap names when the trend breaks.
- **frag-20260811-12** Post-close regret is ambiguous: price rising after exit does not prove a wrong sell — exit-shadow learning needs risk-adjusted and opportunity-cost framing.
- **frag-20260811-14** Daily weekday paper-auto surveillance vs weekly decision-review knob learning — UI 'self-improving' narrative overshoots actual adaptation cadence.
- **frag-20260811-15** Archive ftse-simulate, browser paper_sims, and server learning tracks coexist without one anchor for which automated model is under evaluation.
- **frag-20260811-16** Stage 2b primary track still negative excess after costs while ops/library infra ran ahead — when does doctrine pause breadth until AI excess turns positive?
- **frag-20260811-17** Ingest canonical bootstrap increases counted zero-body buy-tier stalls before depth pays off — stall metrics may need a third state beyond pass/fail.
- **frag-20260811-19** Ops micro-compile can false-green ingest stalls when the engineering queue is empty and zero-body count unchanged — targeted escalation policy still open.
- … and 11 more

### Proposed review tasks

**analysis**
- ana-20260728-01: Seed second+ archived weekly run and replay rules vs ai_judgment vs momentum_grace sim tracks — unlock excess_return, trade_count, and total_costs comparisons once run_count ≥ 2.
- ana-20260728-02: Counterfactual paper run: rules track with pre-review knobs (min_conviction 0.0, max_positions 5) vs post-review knobs (0.05, 4) on identical mark windows — quantify whether cost-drag reduction offset
- ana-20260728-04: Exit-shadow cohort thickness dashboard: alert when any track reaches ≥10 closed exits with grace vs screen_rotation split — prerequisite before any momentum_grace knob experiment.
- ana-20260728-05: Historical-analysis window bootstrap: archive two consecutive weekly runs with overlay_comparison populated — test whether research_overlay / adjusted_signal ranks predict forward 4w/12w excess once t

**horizon**
- hor-20260811-02: Hold ai_judgment and rules knobs fixed for one epoch — accumulate ≥2 epoch marks and ≥1 epoch trade before any human decision-review apply; isolates cost/concentration effects of 2026-08-11 knob chang

**learning_director**
- ldr-20260901-01: Human-ack forward pass on ai_judgment_exclusion_u4 vs live primary (`ldr-20260823-02`; aligns `convergence_summary.look_now[0]`) — expected learning value: first cost-aware week-pair read on whether u
- ldr-20260901-02: Ensure scoring experiment queued for hold->buy and signal_unchanged transition keys — expected learning value: convert `analysis_review.sections.proposed_experiments` item 1 (offline conviction-timing
- ldr-20260901-03: Ensure scoring experiment queued for quality-family composite gate on avoid cohort — expected learning value: convert `analysis_review.sections.proposed_experiments` item 2 into tracked task; tests fa
- ldr-20260901-04: Human-ack exit-shadow cohort thickness dashboard (`ana-20260728-04`; `experiment_assessment.recommendations[0]`) — expected learning value: alert when any track reaches ≥10 closed exits with grace vs 
- ldr-20260901-05: Human-ack extended buffered-hold counterfactual (`plr-20260901-02`) — expected learning value: 7d replay tied at delta 0 on rules/ai_judgment; extended lookback to epoch start 2026-08-12/26 may surfac


### Open engineering queue

- **eng-20260902-02** [open] Enable and gate Yahoo `quarterly_cashflow` for UK names; suppress TTM FCF and flag when series empty (HIK.L $14.4m TTM vs $119m filing; ITV.L empty)
- **eng-20260902-03** [open] Emit labelled dual FCF/dividend coverage (statutory OCF−capex vs management cash-generated−capex) plus universe-level FCF divergence flags in `screening_snapsho
- **eng-20260902-04** [open] Compute Lynch PEG and earnings-growth overlays from filing EPS (core where disclosed) with statutory fallback and >300 bps divergence warning; attach auto-gener

## Integration health

Overall: **OK**


## Role coherence (join-up)

Overall: **INFO**

- **[INFO]** Stage 2b focus aligned with primary learning gap: North-star focus is stage 2b while AI-judgment excess after costs is still negative (-19.2%). Breadth expansion and new tracks should stay deferred.
- **[INFO]** Offline library ahead of live learning edge: 21 graduated library markets vs stage 2b still in progress — library growth is correctly offline; live universe expansion remains gated.

## So what? (gap closure)

- Findings: **56** (auto_queue=14, human_gate=22, observe=20); engineering tasks created this pass: **0**.
- Auto-queue covers no-judgment enforcement gaps (e.g. FCF mismatch with uncapped buy/strong_buy). Human gate covers policy FCF bridge reviews.

### High-severity so-whats

- `BKG.L` (auto_queue): Buy-tier signal remains uncapped while screen vs filing FCF diverge by ~46%. Enforcement must fail closed (overlay) without waiting for a human prompt.
- `BME.L` (auto_queue): Buy-tier signal remains uncapped while screen vs filing FCF diverge by ~39%. Enforcement must fail closed (overlay) without waiting for a human prompt.
- `BT-A.L` (auto_queue): Buy-tier signal remains uncapped while screen vs filing FCF diverge by ~35%. Enforcement must fail closed (overlay) without waiting for a human prompt.
- `BTRW.L` (auto_queue): Buy-tier signal remains uncapped while screen vs filing FCF diverge by ~111%. Enforcement must fail closed (overlay) without waiting for a human prompt.
- `BYIT.L` (auto_queue): Buy-tier signal remains uncapped while screen vs filing FCF diverge by ~29%. Enforcement must fail closed (overlay) without waiting for a human prompt.
- `DOM.L` (auto_queue): Buy-tier signal remains uncapped while screen vs filing FCF diverge by ~38%. Enforcement must fail closed (overlay) without waiting for a human prompt.
- `FOUR.L` (auto_queue): Buy-tier signal remains uncapped while screen vs filing FCF diverge by ~30%. Enforcement must fail closed (overlay) without waiting for a human prompt.
- `GSK.L` (auto_queue): Buy-tier signal remains uncapped while screen vs filing FCF diverge by ~27%. Enforcement must fail closed (overlay) without waiting for a human prompt.
- `INCH.L` (auto_queue): Buy-tier signal remains uncapped while screen vs filing FCF diverge by ~28%. Enforcement must fail closed (overlay) without waiting for a human prompt.
- `ITV.L` (auto_queue): Buy-tier signal remains uncapped while screen vs filing FCF diverge by ~30%. Enforcement must fail closed (overlay) without waiting for a human prompt.
- `MEGP.L` (auto_queue): Buy-tier signal remains uncapped while screen vs filing FCF diverge by ~38%. Enforcement must fail closed (overlay) without waiting for a human prompt.
- `MGAM.L` (auto_queue): Buy-tier signal remains uncapped while screen vs filing FCF diverge by ~29%. Enforcement must fail closed (overlay) without waiting for a human prompt.

### Human gates

- `ABDN.L`: Review filings for ABDN.L and write docs/data/research/ABDN.L/sources/fcf_bridge.json (policy_fcf + policy_basis + source_refs; set resolved=true).
- `BKG.L`: Review filings for BKG.L and write docs/data/research/BKG.L/sources/fcf_bridge.json (policy_fcf + policy_basis + source_refs; set resolved=true).
- `BME.L`: Review filings for BME.L and write docs/data/research/BME.L/sources/fcf_bridge.json (policy_fcf + policy_basis + source_refs; set resolved=true).
- `BT-A.L`: Review filings for BT-A.L and write docs/data/research/BT-A.L/sources/fcf_bridge.json (policy_fcf + policy_basis + source_refs; set resolved=true).
- `BTRW.L`: Review filings for BTRW.L and write docs/data/research/BTRW.L/sources/fcf_bridge.json (policy_fcf + policy_basis + source_refs; set resolved=true).
- `BYIT.L`: Review filings for BYIT.L and write docs/data/research/BYIT.L/sources/fcf_bridge.json (policy_fcf + policy_basis + source_refs; set resolved=true).
- `CNA.L`: Review filings for CNA.L and write docs/data/research/CNA.L/sources/fcf_bridge.json (policy_fcf + policy_basis + source_refs; set resolved=true).
- `DOM.L`: Review filings for DOM.L and write docs/data/research/DOM.L/sources/fcf_bridge.json (policy_fcf + policy_basis + source_refs; set resolved=true).


## References

- Deferred review: `docs/deferred-review.md`
- Ops cadence: `docs/ops/ops-review-cadence.md`
- Human tasks: `docs/ops/human-tasks-checklist.md`
- So-what gap closure: `docs/ops/so-what-gap-closure.md`

Regenerate: `ftse-progress-report build --write`
Queue enforcement gaps: `ftse-progress-report so-what --apply`
