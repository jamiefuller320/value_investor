# Index stress archive sim (observe-only)

Offline lab for **rule-based index stress triggers** and stop-out counterfactuals.
Calibrates future portfolio panic circuit breakers without touching live paper books.

## Why daily rate of change?

**Daily ROC is necessary but not sufficient on its own.**

| Horizon | Captures | Misses |
|---------|----------|--------|
| **Daily 1d** | Intraweek gaps, crash days | Noisy in volatile but non-panic weeks |
| **Daily 5d** | Panic weeks | Slower to fire |
| **Vol-z (20d)** | Unusual vs recent regime | Backward-looking vol |
| **Drawdown from peak** | Sustained stress | Lags the first gap day |
| **Weekly snapshot only** | Coarse trend | **Intraweek gaps** (e.g. −8% Mon, flat Fri) |

Recommended production stack: **OR** across `abs_1d`, `abs_5d`, `vol_z`, and `drawdown`,
then apply a **cooldown** before re-enabling exits (not implemented live yet).

## Commands

```bash
# Default thresholds: 1d −3%, 5d −5%, drawdown −6%, vol-z 2.5
ftse-index-stress-archive --output-dir docs/data

# Custom primary thresholds + JSON output
ftse-index-stress-archive \
  --output-dir docs/data \
  --abs-1d -0.025 \
  --abs-5d -0.06 \
  --drawdown -0.08 \
  --json
```

Backfill weekly snapshots first if history is thin:

```bash
ftse-archive-history --data-dir docs/data
```

## Artifacts

Written to `--output-dir`:

- `index_stress_archive.json` — recent daily bars, stressed days, per-window episodes
- `index_stress_archive_review.json` — primary replay + threshold sweep summary

## Primary replay metrics

For each consecutive weekly snapshot window:

- Whether **any daily stress trigger** fired between snapshot dates
- Buy-tier names whose forward price would have **hit `tactical_stop_loss`**
- `counterfactual_sells_avoided` — stop hits on stress windows (if suspension had been active)

## Threshold sweep

Runs three preset threshold bundles (tight / default / loose) and reports:

- `stressed_days` on daily bars
- `stress_windows` across the snapshot chain
- `stop_hits_stress_windows` per bundle

Use sweep output to pick thresholds before any paper-auto wiring.

## Limitations

- Stop counterfactual uses **weekly snapshot prices**, not daily marks — conservative for gap risk.
- Hypothetical book = buy-tier names on each snapshot, not actual paper holdings.
- Does not model `exit_confirm_screens` hold buffer or momentum grace yet.
- Archive chain is still short — treat readiness flag as guidance, not sign-off.

## Pairing evidence

| Source | Role |
|--------|------|
| `index_stress_archive_review.json` | Stress trigger calibration |
| `learning_tracks_exit_shadow.json` | Post-exit regret on real sells |
| `exit_timing_near_miss_review.json` | Hold-recovery on near-miss names |
| `ftse-simulate --grace-sweep` | Grace-week parameter priors |

See deferred **L145** (portfolio panic circuit breaker) for live promotion criteria.
