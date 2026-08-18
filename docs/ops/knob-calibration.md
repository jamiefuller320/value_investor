# Knob calibration (walk-forward priors)

Observe-only **walk-forward grid search** over decision-review knobs using
`rebalance_log` replay (and optional archive replay). Produces ranked knob priors
for manual seeding — does **not** auto-apply live knobs.

Complements:

- **L1 decision-review** — reactive small steps on forward paper marks
- **L86 / L111** — archive counterfactual labs for parameter priors
- **buffered_hold_counterfactual** — churn-guard (`exit_confirm_screens`) sensitivity

## When to run

| Trigger | Command |
|---------|---------|
| **Sunday analysis-review** | `analysis-review.yml` runs calibration before the modelling agent |
| **Manual** | `ftse-knob-calibrate run --paper-root docs/data/paper_automation --write` |

Requires **≥2 acted** `rebalance_log` entries per track. Confidence stays **low**
until ≥4 entries (and higher with thicker walk-forward folds).

## Fitness function

Per fold:

```
fitness = return_delta_vs_actual (or simulated_return)
        - λ × simulated_cost_drag
```

Walk-forward composite:

```
composite = mean(fold fitness) - stability_penalty × std(fold fitness)
```

Defaults: `λ = 0.5`, `stability_penalty = 0.25`.

## Cohort-selection fitness (AI judgment tracks)

For `ai_judgment` (and calibrated shadow), ranking blends **portfolio replay**
with **name-level cohort outcomes** from consecutive rebalance passes:

| Cohort metric | Meaning |
|---------------|---------|
| `cohort_hit_rate` | Share of held/selected names with positive forward return to next pass |
| `cohort_mean_forward_return` | Mean forward return of selected cohort |
| `selection_spread` | Selected mean minus rejected eligible mean |
| `new_buy_hit_rate` | Hit rate on fresh entries only |

Blended score (default):

```
blended = 0.4 × portfolio_walk_forward + 0.6 × cohort_walk_forward
```

`knob_axis_discriminability` flags axes with negligible separation (e.g. `sector_cap`
tying across values). Priors require `score_gap_vs_runner_up ≥ 0.005` for
`ready_for_priors=true`.

Disable with `ftse-knob-calibrate run ... --no-cohort-fitness`.

## Default search space

| Knob | Values |
|------|--------|
| `max_positions` | 3, 4, 5 |
| `min_conviction` | 0.0, 0.15, 0.25, 0.35 |
| `sector_cap` | 0.2, 0.25, 0.3 |
| `skip_timing_wait` | true |

Add `--include-churn-knobs` to sweep `exit_confirm_screens` (1, 2).

AI overlay gates (`use_adjusted_signal`, `require_research_accumulate`) stay fixed
to track config until L113 PIT bootstrap.

## Commands

```bash
# Rules + ai_judgment, write artifact
ftse-knob-calibrate run \
  --paper-root docs/data/paper_automation \
  --tracks rules,ai_judgment \
  --write --json

# Single track, custom grid
ftse-knob-calibrate run \
  --track-dir docs/data/paper_automation/ai_judgment \
  --max-positions-grid 3,4 \
  --min-conviction-grid 0.15,0.25,0.35 \
  --write

# Inspect last artifact
ftse-knob-calibrate status --paper-root docs/data/paper_automation --json
```

## Artifacts

| File | Purpose |
|------|---------|
| `docs/data/paper_automation/knob_calibration_priors.json` | Ranked candidates + `recommended_prior` per track |
| Sunday `analysis_review` payload | Agent reads `knob_calibration_priors` for synthesis |

## Promoting a prior (human gate)

1. Review `recommended_prior.confidence` and `changed_vs_current`
2. If acceptable, edit track `config.json` (and optionally reset knob epoch)
3. Or file a `paper_knobs` experiment via analysis / paper-learning review

Do **not** wire auto-apply from calibration until forward epochs confirm uplift.

## Calibrated shadow track (phase 1 — ai_judgment only)

Forward-validation book with **frozen** calibration priors, running alongside the
primary `ai_judgment` track. Decision-review `--apply` is disabled on the shadow.

| Step | Command / trigger |
|------|-------------------|
| **Spawn (manual)** | `ftse-knob-calibrate spawn-shadow --paper-root docs/data/paper_automation` |
| **After calibration** | `ftse-knob-calibrate run ... --write --spawn-shadow` |
| **Weekday paper-auto** | `spawn-shadow` before learning tracks (idempotent) |

Artifacts under `docs/data/paper_automation/ai_judgment_calibrated/`:

| File | Purpose |
|------|---------|
| `config.json` | Parent AI gates + calibrated knobs; `is_calibration_shadow: true` |
| `automated_fund.json` | Fresh book at same `initial_cash` as parent |
| `calibration_provenance.json` | Prior source, confidence, `changed_vs_parent` |

Dashboard: Automation tab shows knob parameters and a **calibrated shadow** badge.
Compare forward marks vs primary before promoting knobs to `ai_judgment/config.json`.

## Guardrails

- Observe-only — no `decision-review --apply`
- Bootstrapped logs flagged (L113 AI-gate caveat)
- Thin history → low confidence priors
- Evolution (L2/N2) remains deferred

See also: [decision-review.md](decision-review.md), [analysis-review.md](analysis-review.md).
