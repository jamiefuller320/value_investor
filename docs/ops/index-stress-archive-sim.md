# Index stress archive sim (observe-only)

Offline lab for **rule-based index stress triggers** and stop-out counterfactuals.
Calibrates future portfolio panic circuit breakers without touching live paper books.

## Frequency: daily vs hourly

**Daily ROC is necessary but not sufficient.** **Hourly adds meaningful sensitivity** for flash moves that a single daily close can mask (e.g. −8% Monday, −0.5% Friday close).

| Frequency | Captures | Limit |
|-----------|----------|-------|
| **Daily 1d/5d + vol-z + drawdown** | Panic weeks, regime stress | Misses intraday gap structure |
| **Hourly `abs_1h`** | Worst hour-over-hour move in session | Yahoo ~730d depth |
| **Hourly session return** | Open→close stress day | Same |
| **Sub-hourly (1m/5m)** | Microstructure noise | Not worth it for weekly rebalance cadence |

Recommended stack: **OR** across hourly + daily triggers, then cooldown before re-enabling exits.

Hourly bars persist under `docs/data/library/macro/index_intraday/` on each run (more-data-now).

## Commands

```bash
# Default: daily + hourly, exit_confirm_screens=2, momentum grace on
ftse-index-stress-archive --output-dir docs/data

# Daily-only triggers
ftse-index-stress-archive --no-hourly

# Custom thresholds
ftse-index-stress-archive \
  --abs-1d -0.025 \
  --abs-5d -0.06 \
  --abs-1h -0.02 \
  --abs-session -0.04 \
  --drawdown -0.08 \
  --json

# Exit-policy replay knobs
ftse-index-stress-archive --exit-confirm-screens 2
ftse-index-stress-archive --no-momentum-grace
```

Backfill weekly snapshots first if history is thin:

```bash
ftse-archive-history --data-dir docs/data
```

## Artifacts

Written to `--output-dir`:

- `index_stress_archive.json` — daily/hourly bars, stressed days, episodes
- `index_stress_archive_review.json` — replay + sweep + `exit_policy_replay`

Persisted hourly store: `docs/data/library/macro/index_intraday/ftse_1h.json`

## Replay metrics

### Tactical stops (`primary_replay`)

- Stress windows between weekly snapshots
- Buy-tier `tactical_stop_loss` hits
- `counterfactual_sells_avoided` on stress windows

### Exit policy (`exit_policy_replay`)

- **`exit_confirm_screens`** — rotation buffer before screen-based exit
- **Momentum grace** — hold after downgrade when trend intact
- `mechanical_exits_total` = stops + rotation + grace exits
- `counterfactual_exits_avoided` on stress windows

## Threshold sweep

Three preset bundles (tight / default / loose): stressed days, stress windows, stop hits.

## Limitations

- Position marks still use **weekly snapshot prices** between rebalance dates.
- Hypothetical book seeded from top buy-tier names — not actual paper holdings.
- Archive chain is still short — treat readiness flag as guidance.

## Pairing evidence

| Source | Role |
|--------|------|
| `index_stress_archive_review.json` | Stress trigger calibration |
| `learning_tracks_exit_shadow.json` | Post-exit regret on real sells |
| `exit_timing_near_miss_review.json` | Hold-recovery on near-miss names |
| `ftse-simulate --grace-sweep` | Grace-week parameter priors |

See deferred **L145** (portfolio panic circuit breaker) for live promotion criteria.
