# Exit-timing reconciliation (L121)

## Purpose

Before comparing **hold→breakeven** or **swap-success** rates between live paper
cohorts and archive near-miss priors, use a single reconciliation artifact that:

- Documents **episode populations** (book stress vs synthetic near-miss observe).
- Maps **close_reason** labels to shared outcome buckets.
- Exposes **comparability gates** so analysis review does not average incompatible denominators.

Observe-only — no knob apply paths.

## Artifact

| File | Writer |
|------|--------|
| `docs/data/exit_timing_reconciliation.json` | Regenerated when any writer below runs |

## When it runs

| Process | Trigger |
|---------|---------|
| **Weekday paper-auto** | After `learning_tracks_exit_timing.json` rollup |
| **Sunday archive sim** | After `ftse-exit-timing-archive` (with live `paper_automation` present) |
| **Analysis review payload** | `ftse-analysis-review payload` / Sunday workflow input check |

## Downstream consumers

| Consumer | Key |
|----------|-----|
| `ftse-analysis-review` modelling agent | `exit_timing_reconciliation` (slim) in JSON payload |
| Learning Director weekly payload | Same slim block when committed artifact exists |
| Human / agents | Read JSON `comparability.analysis_contract` |

## Related

- Live cohorts: [`exit-timing-cohorts.md`](exit-timing-cohorts.md)
- Archive priors: [`exit-timing-archive-sim.md`](exit-timing-archive-sim.md)
- Sunday contracts: [`analysis-review.md`](analysis-review.md)
