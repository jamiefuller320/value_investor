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

## Guardrails

- Observe-only — no `decision-review --apply`
- Bootstrapped logs flagged (L113 AI-gate caveat)
- Thin history → low confidence priors
- Evolution (L2/N2) remains deferred

See also: [decision-review.md](decision-review.md), [analysis-review.md](analysis-review.md).
