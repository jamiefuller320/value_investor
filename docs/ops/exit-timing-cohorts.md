# Exit-timing cohorts (observe-only)

## Purpose

Collect data to answer later:

- **P(hold → breakeven)** — when a position is stressed but still held, does it recover?
- **P(swap → better prospect)** — when we rotate (sell + buy same pass), does the replacement beat the exit?

This strand is **observe-only**. It does not change live paper books, knobs, or decision-review apply paths. Probability estimates and knob promotion wait until closed cohorts mature (see deferred N25 / L85 / L117).

## What runs

On every paper-auto pass, each track runs `run_exit_timing_cohort_pass()` alongside `run_exit_shadow_pass()`:

| Cohort | Trigger | Outcomes |
|--------|---------|----------|
| **Hold-recovery** | Underwater, exit_streak ≥ 1, momentum_grace, or signal downgrade while still held | `recovered_to_breakeven`, `sold_while_underwater`, max-window close |
| **Swap-rotation** | Same rebalance pass has both sells and buys | `replacement_outperformed`, `exit_outperformed`, `inconclusive` |

Checkpoints are scored at **7 / 28 / 56 / 84 days** (same windows as exit-shadow).

## Artifacts

Per track (`docs/data/paper_automation/<track_id>/`):

- `exit_timing_cohorts.json` — open + closed hold episodes and swap rotations
- `exit_timing_cohorts_review.json` — per-track summary + `readiness` block

Rollup:

- `learning_tracks_exit_timing.json` — all tracks + framework metadata

## Fields captured for later analysis

**Hold-recovery episodes:** `data_quality_score`, `conviction_score`, `screen_signal`, `effective_signal`, `exit_streak_at_start`, `stress_triggers`, checkpoint marks.

**Swap rotations:** sell/buy legs, realized % on exit, post-rotation returns, trade costs, replacement delta at each checkpoint.

## Readiness gates

`assess_framework_readiness()` reports when probability work can begin:

| Target | Minimum |
|--------|---------|
| Closed hold-recovery episodes | 15 |
| Closed swap rotations | 10 |
| Hold episodes with `data_quality_score` | ≥ 1 (needs screen marks on pass) |

Until targets are met, `ready_for_probability_analysis` stays `false` and review notes say cohorts are still collecting.

## Related artifacts

Pair with:

- `exit_shadow.json` — post-exit path **after** a sell (early vs good exit)
- `rebalance_log.json` — counterfactual replay of decision-time candidates
- `learning_tracks_churn_health.json` — cost drag and hold-buffer state

Exit-shadow answers “was the sell too early?” Hold-recovery and swap-rotation answer “should we have held or swapped differently?”

## Commands

```bash
# Runs cohort pass on every track (with paper-auto)
ftse-paper-auto --output-dir docs/data/paper_automation --reports docs/data/latest.json --tracks all
```

Weekly analysis review payload includes `exit_timing_cohorts` when the rollup exists.
