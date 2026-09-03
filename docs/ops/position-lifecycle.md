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

Every stage has ≥1 observing experiment. Planned factors activate when their
`revisit_when` trigger fires — **do not spawn a new paper book per factor**.

Diagnostic labels from `classify_lifecycle_phase()` (`prospect_ready`,
`starter`, `build`, `full`, `harvest`, `grace`, `exit_pending`, …) collapse
onto these seven stages via `stage_for_phase()`.

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

## What already runs vs what this adds

| Piece | Status |
|-------|--------|
| Graduated allocation paper track | **Live** — starter sizing + harvest on one rules book |
| Lifecycle *labels* on rebalance logs | **Live** — now includes `starter` when sleeve &lt; 40% of target |
| Full per-holding state machine | **Deferred (L177)** — catalog is the experiment inventory, not the executor |
| DCA executed on paper books | **Not now** — overlay evidence first |
| Intra-day tranche cadence | **Later** — weekday marks only |

## Human gate

Sunday: when `learning_tracks_entry_dca` shows
`ready_for_cadence_analysis=true`, read the rollup (leading cadence, mean
de-risk, `model_independent_hint`) before changing starter fraction or
proposing a DCA-executing track. Human ack only.

See also [`capital-allocation.md`](capital-allocation.md),
[`hypothesis-integrity.md`](hypothesis-integrity.md),
[`exit-timing-cohorts.md`](exit-timing-cohorts.md),
[`experiment-assessment.md`](experiment-assessment.md).
