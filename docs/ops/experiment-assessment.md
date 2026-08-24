# Experiment assessment (unified loop)

Evidence-gated assessment for shadow tracks and open experiment task queues.
Replaces ad-hoc status reads with one Sunday ledger: **proposed → observing →
continue | fail | recommend**.

Never auto-applies knobs, configs, or engineering tasks — `recommend` is human ack only.

## States

| State | Meaning |
|-------|---------|
| `proposed` | Task-queue experiment not yet running forward |
| `observing` | Shadow running; insufficient marks/evidence |
| `continue` | Enough marks to keep observing; not ready to promote |
| `fail` | Evidence gate failed — retire or stop watching |
| `recommend` | Ready for human review / promotion ack |

## Commands

```bash
# Rebuild ledger (Sunday workflow runs this after knob endurance)
ftse-experiment-assess refresh \
  --data-dir docs/data \
  --paper-root docs/data/paper_automation

# Inspect committed ledger (slim JSON for agents)
ftse-experiment-assess status --data-dir docs/data --json
```

## Sources (phase 1)

| Kind | Source | Gate |
|------|--------|------|
| `calibration_shadow` | `calibration_shadow_endurance.json` | Post-seed excess/marks vs market + primary/rules |
| `exclusion_shadow` | Exclusion shadow tracks | Post-seed excess vs parent track |
| `analysis_task` | `analysis_tasks.json` | Stays `proposed` until forward evidence hooks land |
| `paper_learning_task` | `paper_learning_tasks.json` | Same |
| `learning_director_task` | `learning_director_tasks.json` | Same |

Future phases: attach `paper_knobs` / `paper_churn` forward probes and
`[scoring]` / `[offline_sim]` tasks once evidence hooks exist.

## Artifacts

| File | Purpose |
|------|---------|
| `docs/data/experiment_assessment.json` | Unified ledger + recommendations list |

Consumed by:

- `ftse-analysis-review` payload (`experiment_assessment` slim view)
- `ftse-learning-director` payload (complexity / human-ack inventory)

## Human gate

When `recommendations` is non-empty:

1. Read the row in `experiment_assessment.json` (track, marks, excess)
2. For calibration shadows — follow [knob-calibration.md](knob-calibration.md#promoting-a-prior-human-gate)
3. For exclusion shadows — follow [exclusion-ladder-replay.md](exclusion-ladder-replay.md#promotion-workflow-human-gate)
4. Do **not** auto-apply — survivors are priors for refinement only

See also: [analysis-review.md](analysis-review.md), [learning-director-vision.md](learning-director-vision.md).
