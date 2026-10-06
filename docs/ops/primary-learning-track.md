# Primary learning track (hands-off)

## Idea

Stock-picking decisions are made by an **AI quasi-human** policy using whatever
research/overlay is available at decision time. Confirmation is **not** a human
trade checklist — it is a performance comparison to market datums. Success =
**outperformance after costs** in that market.

## Assessment model and frozen tracks

Since **2026-10-06** the live FTSE paper root is judged by **one assessment
model** on a single fair (T212-shaped) cost basis instead of two suites. The
committed file `docs/data/paper_automation/assessment_model.json` records:

- `primary_track` = **`ai_judgment_fair`** — the book judged against the market;
- `control_track` = **`buy_tier_level`** — the unfiltered buy-tier book the
  primary must beat (does the AI/conviction filter add value over the screen?);
- `switches` — every primary/control change with its date and reason;
- `frozen_tracks` — books that stopped trading, each with `frozen_at`, `reason`,
  `superseded_by` and its final NAV, contributed capital, holdings and trade count.

Frozen on 2026-10-06 (history kept, nothing rewritten):

| Frozen track | Why | Superseded by |
|--------------|-----|---------------|
| `rules`, `ai_judgment`, `momentum_grace`, `technical`, `still_in_buy_set` | Suite A 3% stress-cost books. `rules` and `ai_judgment` held identical names 31/31 days; the research gate never binds at `min_conviction` 0.6 | `ai_judgment_fair` / `buy_tier_level` |
| `rules_fair` | Identical holdings to `ai_judgment_fair` 19/19 days | `ai_judgment_fair` |
| `ai_judgment_calibrated`, `_r2`, `_r3` | Shadows of a frozen parent; near-identical to each other and ranked on pre-L540 replays | `ai_judgment_fair` |
| `ai_judgment_exclusion_u4` | Shadow of a frozen parent; same holdings as `ai_judgment` | `ai_judgment_fair` |

Still trading: `ai_judgment_fair` (primary), `buy_tier_level` (control),
`buy_tier_level_dca` (deposit realism) and `graduated_allocation` (still on the
3% stress cost; fair twin parked with **N188**).

What freezing does:

- `ftse-paper-auto --tracks all` and `ftse-decision-review --tracks all` skip
  frozen books (no marks, no fills, no knob applies). Single-track CLI runs of a
  frozen book exit with an error.
- Calibrated and exclusion shadows do not spawn from a frozen parent.
- When `rules` (the root book) is frozen, paper-auto mirrors the primary's
  `last_run.json` to the root (`mirrored_from_track`) so schedulers, ops-monitor
  and publish keep their "ran post-settle" marker. The rules fund itself stays
  at the root untouched.
- `is_primary_learning_track` follows `primary_track` on every config pass.
- Market shards have no `assessment_model.json` and keep the legacy
  `ai_judgment` primary / `rules` control.

**Do not** unfreeze or edit a frozen book to test an idea — start a twin with
its own cold start and add it to the model. Switching primary/control again
needs a new `switches` entry via `apply_assessment_model()` in
`src/value_investor/assessment_model.py`, with the reason recorded.

Known limit: `ai_judgment_fair` copies `min_conviction` 0.6 and the accumulate
gate from `ai_judgment`, so its AI gate does not bind either; the binding-gate
twin is parked as **N189**.

## Tracks

| Track | Directory | Decision policy | Role |
|-------|-----------|-----------------|------|
| **AI judgment fair** *(primary)* | `docs/data/paper_automation/ai_judgment_fair/` | `adjusted_signal` + `research_verdict=accumulate`, fair costs | Learning book |
| **Buy-tier level** *(control)* | `docs/data/paper_automation/buy_tier_level/` | Raw screen buy-tier, no conviction/sector cap, fair T212 costs, frozen knobs | Unfiltered buy-tier baseline |
| **Buy-tier level DCA** *(realism)* | `docs/data/paper_automation/buy_tier_level_dca/` | Same level-book policy + £500/mo deposits (cold-start capital epoch) | Household DCA realism; overlays FTSE held-vs-market |
| **Graduated allocation** *(experimental)* | `docs/data/paper_automation/graduated_allocation/` | Screen rules + trade-plan starter sizing + harvest skims (`max_positions=4`) | Capital recycling experiment (3% stress cost) |
| AI judgment *(frozen)* | `docs/data/paper_automation/ai_judgment/` | `adjusted_signal` + `research_verdict=accumulate`, 3% stress | Former primary |
| Screen rules *(frozen)* | `docs/data/paper_automation/` | Raw buy-tier screen signal, 3% stress | Former control |
| Technical *(frozen)* | `docs/data/paper_automation/technical/` | Stops/targets from `trade_plan`, tactical entries | Former timing/levels floor |
| Momentum grace *(frozen)* | `docs/data/paper_automation/momentum_grace/` | Screen rules + bounded hold on value downgrade when price trend stays strong | Former exit-overlay experiment |
| Exclusion ladder *(frozen)* | `docs/data/paper_automation/ai_judgment_exclusion_u4/` | AI judgment + frozen archive ladder `u4` knobs | Former loser-filter experiment |
| Still-in-buy-set *(frozen)* | `docs/data/paper_automation/still_in_buy_set/` | Screen rules + rank-gated still-in-buy-set hold | Former Suite A churn twin |

The sections below describe the pre-2026-10-06 dual-suite setup where they
mention Suite A; they still apply to market shards.

Both primary books use the same costs, position caps, and weekday paper-auto schedule.
Live FTSE configs keep the **3% per-side stress** cost by default (Suite A —
defensive / low-churn lab). Fair T212-shaped performance truth is Suite B /
`ftse-trading-costs assess` — see
[`market-trading-costs.md`](market-trading-costs.md#test-and-adoption-strategy-dual-suite).
Do **not** promote knobs on stress excess vs ^FTSE alone.

The **still_in_buy_set** track is a Suite A **cold-start churn twin** (rank-gated
hold + never-left-candidates + CD2). Frozen (`is_churn_policy_twin`); do **not**
mid-flight flip live rules / ai_judgment cooldown or still-in-buy-set knobs.
Compare marks to rules; adoption stays on Suite B.

## Algo → LLM agree/veto shadow (observe-only)

Parallel **review layer** (not a capital-path twin): on every paper-auto pass the
algo proposals (sell / hold / rebuy) get evidence-citing agree/veto/abstain cards
written into `llm_agree_veto_shadow.json` and the rebalance log. Cards never
block fills (`influences_live=false`). See
[`llm-agree-veto-shadow.md`](llm-agree-veto-shadow.md) and the live-path evidence
principle [`llm-live-path-evidence.md`](llm-live-path-evidence.md). Hard veto
stays parked until the promotion gate in that doc (N173).

The dashboard **Automation → Learning tracks** panel publishes a dual-suite
scoreboard (`learning_tracks_dual_suite` in the dashboard bundle): Suite B fair
excess is the adoption headline; Suite A remains the primary-flag churn lab.
Presentation only — does not flip `is_primary_learning_track` (**N145**).

Sunday **analysis-review** cites the same split as three payload buckets
(`paper_track_buckets`: Suite A stress, Suite B fair adoption, Suite B identity
floor). Identity greens (`buy_tier_level` / DCA) are not the adoption series.
See [`analysis-review.md`](analysis-review.md#dual-suite-paper-track-buckets-observe-only).

## Post-exit shadow learning (observe-only)

On every paper-auto run, each track records **full position sells** into a shadow cohort and
scores post-exit price paths at 1/4/8/12 weeks. Artifacts per track:

- `exit_shadow.json` — open + closed cohort records
- `exit_shadow_review.json` — aggregate verdicts by exit kind (`grace`, `screen_rotation`, …)
- `learning_tracks_exit_shadow.json` — rollup across tracks (compare grace vs rules)

Verdicts (`good_exit`, `early_exit`, `neutral`) are **not** wired to auto-tune grace knobs yet —
wait for a thicker closed cohort before promoting parameter changes.

Cross-market **tagged join** (observe-only): each record carries `market_id` (live book =
`ftse350`) plus first-episode identity so FTSE / euro_depth / sp500 `buy_tier_level`
rows do not collide. Combined vs per-market rollup:
[`combined-tagged-learning.md`](combined-tagged-learning.md) /
`docs/data/combined_tagged_learning.json`. No shared NAV and no live exit-policy
change (**N23**).

## Exit-timing cohorts (observe-only)

On the same paper-auto pass, each track also records **hold-recovery** and **swap-rotation**
cohorts for the exit-timing research strand (P(hold→breakeven) vs P(swap→better prospect)):

- `exit_timing_cohorts.json` — open + closed episodes per track
- `exit_timing_cohorts_review.json` — readiness + summaries
- `learning_tracks_exit_timing.json` — rollup across tracks

See also [`exit-timing-cohorts.md`](exit-timing-cohorts.md) for live paper cohorts and
[`exit-timing-archive-sim.md`](exit-timing-archive-sim.md) for offline near-miss priors.

## Success datums

1. **Market (adoption truth):** excess return after **fair** costs vs FTSE 100 (`^FTSE`)
   on the fair-cost lab / assess view — not the 3% stress book alone.
2. **Control:** primary (or fair AI book) excess should also beat the rules book on the
   same cost basis before promoting further knobs/gates.
3. **Stress lab (defensive):** on the live 3% books, prefer improving cost drag /
   churn / epoch stability; treat deep negative excess vs ^FTSE as expected under
   stress, not as automatic policy failure.

Human verify-before-trade packs remain useful for live capital, but they are
**not** the primary learning loop.

**Dual-path sleeve lab (observe-only):** widest buy-tier lifecycle episodes with
`on_book` / `off_book` / `never_funded` tags run on weekday paper-auto — see
[`dual-path-sleeve-lab.md`](dual-path-sleeve-lab.md). Sleeve timing is stratified
by tag; NAV vs ^FTSE stays on the capital books.

## Decision learning loop (target)

Track excess vs ^FTSE / rules is necessary but not sufficient. The intended
continuous-improvement strand is:

1. **At decision time t** — freeze what the AI-judgment pass used (screen +
   overlay + structured verdict / key filing features), not an essay.
2. **Later** — score whether wait / buy / hold / sell was optimal vs
   alternatives on forward marks.
3. **Attribute** — separate **data gaps** (missing bodies, unbound FCF/EPS,
   stale overlay) from **logic gaps** (gate/knob/policy), and let those
   conclusions prioritize engineering work.

**Design locked:** see [`pit-decision-autopsy.md`](pit-decision-autopsy.md)
(pack schema, Suite B optimality, data-vs-logic rules, eng-queue contract,
KPIs). Implementation remains deferred **L368**, funded by memo retarget
**L367** Phase C; feeder features **L365**.

**Recording discipline (now):** before opening a new analysis / counterfactual /
model-dev strand, answer the four freeze questions and validate with
[`decision-recording-checklist.md`](decision-recording-checklist.md) /
`ftse-decision-recording` (**L386**). Observe-only `preview-freeze` is allowed
before Phase C readiness; the freeze **writer** is not.

**Phase B (producer for the freeze):** scheduled research stays always-on while
the accumulate gate lives, but slim to structured verdict fields — design locked
in [`structured-verdict-slim.md`](structured-verdict-slim.md) (L367 Phase B /
N119+N120).

Today: `rebalance_log.json` + PIT research (`get_research_as_of`) + knob
counterfactuals cover (1)–(2) only partially; automated (3) is not built.
Learning conclusions from this loop should drive other development (ingest,
overlays, gates) ahead of prose polish or offline breadth.

## Human tasks checklist

Weekly manual gates (Sunday priors review, shadow vs primary, promotion rules)
live in [`human-tasks-checklist.md`](human-tasks-checklist.md) and on the
dashboard **Automation → Human tasks** panel. The weekday Automation-tab
glance after paper-auto is automated by ops-monitor — see
[`ops-monitor.md`](ops-monitor.md#paper-learning-tracks). Excess vs ^FTSE
interpretation stays Sunday.

## Commands

```bash
# Run both tracks after open settle
ftse-paper-auto --output-dir docs/data/paper_automation --reports docs/data/latest.json --tracks all

# Review both vs market; apply knobs only when history is thick
ftse-decision-review --output-dir docs/data/paper_automation --tracks all --apply

# Refresh overlay + force bootstrap (weekends / testing):
python3 scripts/bootstrap_learning_loop.py
```

Weekday CI (`paper-auto.yml`) refreshes the research overlay on `docs/data/latest.json`
automatically before trading — no manual bootstrap needed.

The **buy-tier level** cohort is Suite B (fair T212 costs), cold-starts with no
fund on the first weekday pass, and is frozen vs decision-review `--apply`.
The matching **buy-cross** policy is archive-only — see
[`buy-tier-cohort-labs.md`](buy-tier-cohort-labs.md).

Artifacts: `learning_tracks_summary.json`, `learning_tracks_review.json`, plus
per-track `automated_fund.json` / `decision_review.json` / `rebalance_log.json`
(append-only decision snapshots for knob counterfactual replay).

## Safety

- Does **not** rewrite base screen `assign_signal()` (N3).
- Knob updates stay small and clamped (L1).
- Evolutionary genomes (L2) wait until this loop has thick walk-forward history.
- Live broker automation stays off until the primary track shows persistent excess.
