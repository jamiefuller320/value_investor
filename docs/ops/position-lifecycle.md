# Position lifecycle experiments

Formal **entry–exit stages** plus a **perpetual factor inventory**. The first
cross-model experiment is an observe-only **dollar-cost averaging / graduated
entry overlay**: can spreading a decided notional de-risk entries, and which
cadence is effective?

This strand does **not** change live paper books. The graduated-allocation
track already sizes first fills; the overlay asks the counterfactual on
**every** track’s new buys.

## Why (loss tolerance)

Hypothesis-first review already asks whether an underwater holding’s *thesis*
still holds. Graduated entry asks a prior question: **did we need that much
capital at risk on day one?** If a cheaper average fill or a smaller peak £
drawdown shows up across models, the finding is about *how we enter*, not
*which model picked the name*.

## Stages

Canonical catalog: `value_investor.position_lifecycle.lifecycle_catalog()`.

| Stage | Question | Observing experiments |
|-------|----------|------------------------|
| **prospect** | Receive any capital this cycle? | entry appetite, timing gate, conviction floor, research gate |
| **starter** | Partial first fill vs lump-sum? | starter fraction (graduated track) + **entry DCA overlay** |
| **build** | How fast to complete the sleeve? | same DCA overlay; cheaper-only / thesis-intact adds planned |
| **full** | Loss tolerance and rebalance band? | hypothesis integrity, churn notional band |
| **harvest** | Recycle gains without abandoning the thesis? | graduated skim urgency / gain floor |
| **grace** | How long after leaving the target set? | exit-confirm screens, momentum grace, intact-thesis dampen |
| **exit** | Rotate, recover, or cut a broken thesis? | thesis-broken priority, reentry cooldown; swap-score planned |
| **recommit** | New buy *decision* on a name we already cycled? | Overlay tags `first_entry` vs `recommit` (cadence ranking uses first-entry only) |

Every stage has ≥1 observing experiment. Planned factors activate when their
`revisit_when` trigger fires — **do not spawn a new paper book per factor**.

Experiment **collection** is enough today (one overlay + existing tracks).
Winner-evolve / loser-park-but-keep-feeding is planned in
[`experiment-assessment.md`](experiment-assessment.md) and vision phase
`experiment_lineage_and_park`. Park bound = one max value hold (84d min /
400d default), not the 28d DCA window.

Complexity: coverage experiments do **not** count against the discretionary
cap (12 tasks / 8 expensive shadows, agent-managed). See
[`learning-director-vision.md`](learning-director-vision.md#complexity-budget-default).

Diagnostic labels from `classify_lifecycle_phase()` (`prospect_ready`,
`starter`, `build`, `full`, `harvest`, `grace`, `exit_pending`, …) collapse
onto these stages via `stage_for_phase()`.

**Recommit is not a second DCA tranche.** Completing the original decided
notional stays `build`. A second *trigger* — cooldown elapsed after an exit,
or (later) an independent add after the first cycle is done — is a new
decision. First-entry cadence stats exclude those episodes so they do not
contaminate the model-independent overlay. Adding beyond the original sleeve
while still held (pyramid) stays deferred.

## Model-independent DCA overlay

```bash
# Runs on every weekday paper-auto pass
ftse-paper-auto --output-dir docs/data/paper_automation --tracks all

# Manual refresh (marks open episodes; does not invent new buys)
ftse-entry-dca --output-dir docs/data/paper_automation --tracks all
```

For each **new sleeve** (buy of a ticker not held at the start of the pass):

1. Record the actual lump-sum fill (control).
2. Score counterfactual cadences on subsequent weekday marks:
   - `lump_sum` — 100% at decision
   - `dca_2x_weekly` — 50/50 over 1 week
   - `dca_4x_weekly` — 25% weekly × 4
   - `dca_2x_biweekly` — 50/50 over 2 weeks
   - `dca_5x_weekday` — 20% over 5 weekday marks
3. Compare **peak adverse £** (de-risk), **average fill**, and **end value
   after extra buy costs**.

Promotion gate for any cadence (or later skim-linked variant) is **net end
value after costs**. Peak £ de-risk is a diagnostic for loss tolerance, not a
second objective. Do **not** lot-link entry blocks to tactical sells: a skim
does not lower remaining `avg_cost` (weighted average is unchanged), and a
sell+rebuy clip must clear round-trip friction (3% stress per side on Suite A;
~0.55% fair UK including stamp on the rebuy). The material interaction, if
any, is already parked as planned factor `skim_linked_remaining_adds`: pause
or cheaper-only remaining adds after a harvest during build.

Cadences are watched on rules, AI judgment, graduated allocation, and other
tracks alike. If the same cadence leads on ≥2 tracks, the rollup sets
`model_independent_hint`.

### Artifacts

Per track (`docs/data/paper_automation/<track_id>/`):

| File | Role |
|------|------|
| `entry_dca_overlay.json` | Open + closed episodes + cadence scores |
| `entry_dca_overlay_review.json` | Per-track summary + readiness |

Rollup: `docs/data/paper_automation/learning_tracks_entry_dca.json`

Weekday `paper-auto.yml` must **publish** these files (and the per-track
stores) back into `docs/data/paper_automation`. If they stay only under
CI `output/`, the next run starts with an empty overlay and episodes never
accumulate.

Also folded into:

- `experiment_assessment.json` as kind `lifecycle_overlay` (`entry_dca_overlay`)
- Sunday analysis-review / Learning Director payloads (`entry_dca_overlay` slim)
- Director inventory (`lifecycle_overlays.factor_coverage`)

### Readiness

`ready_for_cadence_analysis` when:

| Gate | Minimum |
|------|---------|
| Closed scored episodes (all tracks) | 12 |
| Tracks with ≥1 scored episode | 2 |

Until then, collect only. Do **not** execute DCA on paper books or apply
starter-size knobs from this overlay.

## Dashboard board

The dashboard **Lifecycle** tab is a per-market funnel of individual names plus
the catalog experiments that watch each column. It is **observe-only** — the
same diagnostic labels as `classify_lifecycle_phase()`, not the deferred L177
state machine.

| Column | Typical members | Catalog stages |
|--------|-----------------|----------------|
| Not buy tier | Below buy / strong_buy | prospect (ineligible) |
| Not now | Buy-tier + `timing_signal=wait` | prospect (waitlist) |
| Near buy threshold | Ready buy-tier; hold at the pre-buy conviction floor | prospect (ready) |
| Just bought | Starter sleeve or first fill within 14 days | starter |
| Growth | Build / full holdings | build + full |
| Near sell threshold | Harvest, grace, or exit-pending still held | harvest + grace |
| Just sold | Closed sell within 14 days | exit |
| Post sale monitor | Cooldown or sold within 84 days | recommit |

Switch market (and paper track) rather than stacking every universe on one
page. Payload: `docs/data/lifecycle_board.json` (also rebuilt by local
`POST /api/refresh`).

Each column’s experiment chips open a detail card (aim, catalog/ledger
progress, artifact). A `recommend` row shows structured **evidence**, a
**recommendation**, and a Supabase-linked **Start** button that records an
observe-only ack when the human-ack gate is clear. Start never auto-applies
DCA or starter fraction — `recommend` stays observe-only.

Held, sold, and screen name cards use a green→red **time-in-stage** heatmap:
≤7d fresh, ≤3w, ≤6w, ≤8w, then red beyond 8 weeks. Held columns clock
`opened_at`; sold columns clock the closing mark; screen columns clock
`signal_since` (fallback `weeks_at_signal × 7`).

## What already runs vs what this adds

| Piece | Status |
|-------|--------|
| Graduated allocation paper track | **Live** — starter sizing + harvest on one rules book |
| Lifecycle *labels* on rebalance logs | **Live** — now includes `starter` when sleeve &lt; 40% of target |
| Full per-holding state machine | **Deferred (L177)** — catalog is the experiment inventory, not the executor |
| DCA executed on paper books | **Not now** — overlay evidence first; see [adoption plan](#entry-dca-adoption-plan) |
| Intra-day tranche cadence | **Later** — weekday marks only |

## Human gate

Sunday: when `learning_tracks_entry_dca` shows
`ready_for_cadence_analysis=true`, read the rollup (leading cadence, mean
de-risk, `model_independent_hint`) and the adoption plan. Record ack with
`ftse-experiment-assess ack --experiment-id entry_dca_overlay` (observe-only)
or the Lifecycle card **Start** button (Supabase dashboard bridge).
Do **not** execute DCA or change starter fraction from the overlay.

See also [`capital-allocation.md`](capital-allocation.md),
[`hypothesis-integrity.md`](hypothesis-integrity.md),
[`exit-timing-cohorts.md`](exit-timing-cohorts.md),
[`experiment-assessment.md`](experiment-assessment.md).

## Entry DCA adoption plan

Ack is not adopt. The durable plan is
[`docs/data/entry_dca_adoption_plan.json`](../data/entry_dca_adoption_plan.json),
refreshed with the assessment ledger. Acks live in
[`docs/data/experiment_acks.json`](../data/experiment_acks.json) so Sunday
refresh cannot wipe them.

```bash
ftse-experiment-assess ack --experiment-id entry_dca_overlay --decision ack_observe
ftse-experiment-assess plan
```

| Stage | Meaning | Open when |
|-------|---------|-----------|
| `acked` | Human read the overlay finding | `ftse-experiment-assess ack` recorded for current `leading_cadence` |
| `out_of_sample_first_entry` | Confirm `dca_4x_weekly` on **new** first-entry closes | Live books: `ai_judgment` first-entry ≥ 3 and `rules` ≥ 1; fair tracks still agree |
| `paper_execute_graduated` | Optional execute 4× weekly on `graduated_allocation` only | Previous stage ready **and** graduated `equity_marks` ≥ 8 |
| `primary_or_live` | Primary / live size | Fair-cost primary `beat_market` true **and** graduated execute ready |

A new leading cadence re-opens ack. Do not spawn a per-model DCA paper book.
Promotion metric remains net end value after extra buy costs; peak adverse £
is diagnostic only. Track excess vs ^FTSE after fair costs remains adoption
truth for primary/live.
