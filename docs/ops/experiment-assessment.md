# Experiment assessment (unified loop)

Evidence-gated assessment for shadow tracks, experimental paper tracks, and open
experiment task queues. Replaces ad-hoc status reads with one ledger:

**proposed → observing → continue | fail | recommend**

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
# Rebuild ledger (Sunday + weekday paper-auto)
ftse-experiment-assess refresh \
  --data-dir docs/data \
  --paper-root docs/data/paper_automation \
  --sync-task-status

# Inspect committed ledger (slim JSON for agents)
ftse-experiment-assess status --data-dir docs/data --json
```

`--sync-task-status` writes assessment evidence back into task JSON stores:
`fail` → `cancelled`; `recommend` → `evidence.assessment_recommend` flag only (never auto-promote).

## Sources

| Kind | Source | Gate |
|------|--------|------|
| `calibration_shadow` | `calibration_shadow_endurance.json` | Post-seed excess/marks vs market + primary/rules |
| `exclusion_shadow` | Exclusion shadow tracks | Post-seed excess vs parent track |
| `experimental_paper_track` | momentum_grace / graduated allocation | Forward marks vs primary |
| `analysis_task` | `analysis_tasks.json` + trajectory/archive/churn evidence | Area-specific forward_evidence |
| `paper_learning_task` | `paper_learning_tasks.json` | Same |
| `learning_director_task` | `learning_director_tasks.json` | Same |

### Task evidence hooks (phase 2)

| Area | Evidence attached | Status progression |
|------|-------------------|-------------------|
| `scoring` | trajectory `model_focus_candidates`, loser card families | `continue` when candidates exist; `recommend` when candidate count ≥ 20 |
| `offline_sim` | archive run_count, simulation readiness | `continue` when history/backtest ≥ 2 runs |
| `paper_knobs` | linked experimental track metrics (e.g. momentum_grace) | observing/continue from gate marks |
| `paper_churn` / `monitoring` | exit_shadow closed counts, exit_timing readiness | `recommend` when probability analysis ready |

## Artifacts

| File | Purpose |
|------|---------|
| `docs/data/experiment_assessment.json` | Unified ledger + recommendations list |

Consumed by:

- `ftse-analysis-review` payload (`experiment_assessment` slim view)
- `ftse-learning-director` payload (complexity / human-ack inventory)
- `ftse-publish` dashboard bundle (`experiment_assessment` slim)

Refreshed:

- Sunday `analysis-review.yml` (after knob endurance)
- Weekday `paper-auto.yml` (after publish copy to `docs/data/paper_automation`)

## Human gate

When `recommendations` is non-empty:

1. Read the row in `experiment_assessment.json` (track, marks, excess, forward_evidence)
2. For calibration shadows — follow [knob-calibration.md](knob-calibration.md#promoting-a-prior-human-gate)
3. For exclusion shadows — follow [exclusion-ladder-replay.md](exclusion-ladder-replay.md#promotion-workflow-human-gate)
4. For scoring tasks with `assessment_recommend` — triage via `ftse-analysis-review promote` (human only)
5. Do **not** auto-apply — survivors are priors for refinement only

See also: [analysis-review.md](analysis-review.md), [learning-director-vision.md](learning-director-vision.md).
