# Knob calibration (walk-forward + full-period bootstrap)

Observe-only **grid search** over decision-review knobs using `rebalance_log`
replay (and optional archive replay). Produces ranked knob priors and optional
**competing calibrated shadow sims** — does **not** auto-apply live knobs.

Complements:

- **L1 decision-review** — reactive small steps on forward paper marks
- **Full-period retrospective bootstrap** — quicker starting priors that “worked
  up to now”; forward endurance decides what survives into learning-loop refinement
- **L86 / L111** — archive counterfactual labs for parameter priors
- **buffered_hold_counterfactual** — churn-guard (`exit_confirm_screens`) sensitivity

## When to run

| Trigger | Command |
|---------|---------|
| **Sunday analysis-review** | `analysis-review.yml` runs full-period retrospective + shadow spawn |
| **Weekday paper-auto** | Idempotent `spawn-shadow --top-n 3` + endurance ledger refresh |
| **Manual** | `ftse-knob-calibrate run --paper-root docs/data/paper_automation --write` |

Requires **≥2 acted** `rebalance_log` entries per track. Confidence stays **low**
until ≥4 entries. Shadow bootstrap prefers **≥8 acted** (ideal ≥12).

## Ranking modes

| Mode | Flag | Use |
|------|------|-----|
| Walk-forward (default) | `--ranking-mode walk_forward` | Stability-aware priors for L1-style seeding |
| Full-period retrospective | `--ranking-mode full_period_retrospective` | Bootstrap competing shadows from the monitoring window |
| Blended | `--ranking-mode blended` | 50/50 walk-forward + full-period |

Full-period score combines:

1. Full-log portfolio replay fitness (return − λ×cost drag)
2. Cohort-selection fitness (selected vs rejected name outcomes)
3. Winner/loser catch/exclude rates among buy-tier names

Screen thresholds stay frozen (**N3**) — only portfolio knobs are searched.

**Exclusion-universe archive** (`ftse-exclusion-universe-archive`) complements
calibration with high-N universe EW deltas (all vs all−exclusions) gross of costs.
See [exclusion-universe-archive-sim.md](exclusion-universe-archive-sim.md).

## Fitness function (walk-forward)

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

For `ai_judgment` (and calibrated shadows), ranking blends **portfolio replay**
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
# Sunday-style full-period bootstrap + competing shadows
ftse-knob-calibrate run \
  --paper-root docs/data/paper_automation \
  --tracks rules,ai_judgment \
  --ranking-mode full_period_retrospective \
  --bootstrap-top-n 3 \
  --write --spawn-shadow --json

# Walk-forward only (legacy default)
ftse-knob-calibrate run \
  --paper-root docs/data/paper_automation \
  --tracks rules,ai_judgment \
  --write --json

# Spawn / refresh competing shadows from last priors
ftse-knob-calibrate spawn-shadow \
  --paper-root docs/data/paper_automation \
  --top-n 3

# Forward endurance ledger
ftse-knob-calibrate endurance --paper-root docs/data/paper_automation --json

# PIT warm-start shadows (after spawn; Sunday / manual)
ftse-knob-calibrate warm-start-shadow \
  --paper-root docs/data/paper_automation \
  --parent-track ai_judgment

# Inspect last artifact
ftse-knob-calibrate status --paper-root docs/data/paper_automation --json
```

## Artifacts

| File | Purpose |
|------|---------|
| `knob_calibration_priors.json` | Ranked candidates, `bootstrap_priors`, `recommended_prior`, readiness |
| `calibration_shadow_endurance.json` | Forward marks / status for competing shadows |
| `ai_judgment_calibrated/` | Rank-1 frozen shadow |
| `ai_judgment_calibrated_r2/` … | Competing shadows for ranks 2+ |
| Sunday `analysis_review` payload | Agent reads calibration priors for synthesis |

**Dashboard:** Automation tab → **Knob bootstrap lab** (priors + endurance) and
**Learning tracks** (competing calibrated shadows). Published via `ftse-publish`
from the paper-automation artifacts above.

## Competing calibrated shadows

Bootstrap priors that “worked up to now” are seeded as **observe-only** books.
The real question is whether they **endure forward** vs `^FTSE` and the rules
control. Survivors become starting priors for learning-loop refinement — never
auto-applied.

| Step | Command / trigger |
|------|-------------------|
| **Retrospective + spawn** | Sunday `analysis-review.yml` (`full_period_retrospective`, `--spawn-shadow`) |
| **PIT warm-start** | Sunday `warm-start-shadow` — replay parent `rebalance_log` into the shadow fund, freeze `endurance_zero_datum` at seed end |
| **Persist** | Sunday commits priors, endurance, and `ai_judgment_calibrated*` even if the modelling agent is skipped |
| **Weekday** | Idempotent `spawn-shadow --top-n 3` (GC drops stale ranks) + `endurance` — does **not** re-warm-start |
| **Manual** | `ftse-knob-calibrate spawn-shadow --top-n 3` then `warm-start-shadow` |

Each shadow: `is_calibration_shadow: true`, parent AI gates, frozen knobs,
`calibration_provenance.json`. Decision-review `--apply` is disabled.

### Warm-start zero datum (forward-only endurance)

```bash
# After spawn — replay parent ai_judgment log into all calibrated shadows
ftse-knob-calibrate warm-start-shadow \
  --paper-root docs/data/paper_automation \
  --parent-track ai_judgment

# Optional: start replay on/after a sim date; force re-seed
ftse-knob-calibrate warm-start-shadow \
  --paper-root docs/data/paper_automation \
  --sim-start 2026-08-01T00:00:00+00:00 \
  --force
```

Warm-start:

1. Replays **only** each pass’s logged candidates / screen buy-tier (PIT at entry)
2. Writes `automated_fund.json` holdings, trades, equity marks, cost basis
3. Freezes `endurance_zero_datum` (+ `knob_epoch.json`) at seed end
4. Endurance survivor gates use **post-seed** excess/marks only — seed P&L is diagnostic

Do **not** run warm-start on every weekday pass (would re-inject historical P&L).

## Promoting a prior (human gate)

1. Review `ready_for_shadow_bootstrap` / `ready_for_priors`, confidence, score gap
2. Compare competing shadows in `calibration_shadow_endurance.json` (`surviving`)
3. Only then seed `ai_judgment/config.json` (or a `paper_knobs` experiment) from a survivor
4. Optionally reset the knob epoch after a live config edit

Do **not** auto-apply from calibration or endurance — survivors are priors for
refinement, not live writes.

## Guardrails

- Observe-only — no `decision-review --apply` on shadows
- Screen signals frozen (N3) — portfolio knobs only
- Bootstrapped logs flagged (L113 AI-gate caveat)
- Thin history → low confidence / bootstrap not ready
- Evolution (L2/N2) remains deferred

See also: [decision-review.md](decision-review.md), [analysis-review.md](analysis-review.md),
[human-tasks-checklist.md](human-tasks-checklist.md).
