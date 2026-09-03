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

### Queue triage (2026-09-03)

Sunday compile and this ledger now treat `done` like `promoted` / `cancelled` (do not reopen).

Canonical open rows after the batch triage:

| Keep | Theme | Do not reopen |
|------|-------|----------------|
| `ana-20260728-04` | Exit-shadow dashboard — **watch** until `closed_total` ≥ 10 | `ldr-20260901-04` |
| `ldr-20260823-02` | Exclusion u4 vs primary — **watch** (no promote) | `ldr-20260901-01` |
| `ldr-20260823-03` | Archive-lab full-period replay (L111) — continue | — |

Queued to engineering (human promote 2026-09-03): `eng-20260903-01` ← `ana-20260903-01` (hold→buy / `signal_unchanged`); `eng-20260903-02` ← `ana-20260903-02` (quality-family avoid gate). Observe-only scoring design — do not mutate `assign_signal()` (N3) or start chart-mix entry-timing (N59).

`plr-20260901-02` is **done**. Replay: `ftse-rebalance-log buffered-hold --paper-root docs/data/paper_automation --tracks rules,ai_judgment --lookback-days 28 --exit-confirm-variants 1,2`. The 7d window was tied (delta 0). The 28d window is not:

| Track | screens=1 trades | screens=2 trades | trade delta (1−2) | screens=1 cost drag | screens=2 cost drag |
|---|---|---|---|---|---|
| rules | 23 | 12 | **+11** | 29.72% | 9.97% |
| ai_judgment | 29 | 26 | **+3** | 32.95% | 23.65% |

Keep live `exit_confirm_screens=2`. Do not change knobs from this name (N58). Evidence: [`docs/data/buffered_hold_extended.json`](../data/buffered_hold_extended.json).

`ldr-20260823-04` (IMB.L adjacent flip) is **done**. Verdict: **screen-rotation** in a 3-slot book (replaced by SN.L on 2026-08-21), not a signal/thesis exit. Evidence: [`docs/data/imb_adjacent_flip_audit.json`](../data/imb_adjacent_flip_audit.json). Do not retune hold-buffer or conviction floors from this name.

Cancelled and parked (N58/N59 — do not retune knobs or start entry-timing from the first mixed chart pass): `ana-20260728-02`, `plr-20260901-01`, `plr-20260901-03`.

See also: [analysis-review.md](analysis-review.md), [learning-director-vision.md](learning-director-vision.md).
