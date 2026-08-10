# Exit-timing archive near-miss sim (observe-only)

Offline priors for the exit-timing research strand on names **below the primary buy tier**.
Complements live paper cohorts (`exit_timing_cohorts.json`) which only see names that
entered or stressed-held the book.

## Purpose

Accelerate data gathering for:

- **P(hold → breakeven)** on near-miss `hold` names (high conviction but not buy-tier)
- **P(swap → better prospect)** vs top buy-tier name from the same weekly screen

This is **observe-only** — priors for hold-buffer and grace knob design until live paper
cohorts mature (deferred L118). Does not auto-apply knobs.

## How it works

1. Loads `history/run_*.json.gz` snapshots from `docs/data` (same chain as `ftse-simulate`).
2. Each week (except the last snapshot), opens episodes for near-miss rows matching:
   - Signal not in `strong_buy` / `buy` (default: `hold`)
   - `conviction_score >= min_conviction` (default 0.35)
   - Optional `data_quality_score` floor
3. Scores forward paths using **subsequent snapshot prices** at 7 / 28 / 56 / 84 days.
4. Pairs each near-miss with the **top buy-tier** name from the same week for swap comparison.

If history is thin, backfill first:

```bash
ftse-archive-history --data-dir docs/data
```

## Commands

```bash
# Default gate: hold names with conviction >= 0.35, max 10 per week
ftse-exit-timing-archive --output-dir docs/data

# Tighter gate + JSON output
ftse-exit-timing-archive \
  --output-dir docs/data \
  --min-conviction 0.45 \
  --min-data-quality 0.7 \
  --max-episodes-per-week 5 \
  --json
```

## Artifacts

Written to `--output-dir`:

- `exit_timing_near_miss.json` — cohort store (hold episodes + swap rotations)
- `exit_timing_near_miss_review.json` — summary + readiness gates

Weekly `ftse-analysis-review` payload includes `exit_timing_near_miss` when the review file exists.

## Pairing evidence

| Source | Role |
|--------|------|
| `learning_tracks_exit_timing.json` | Live paper stress / rotation (primary) |
| `exit_timing_near_miss_review.json` | Archive priors on names never bought |
| `learning_tracks_exit_shadow.json` | Post-exit path after real sells |
| `rebalance_log.json` replay | Knob sensitivity on logged passes |

## Limitations

- Forward marks use **weekly snapshot prices**, not daily — checkpoints align to first snapshot on/after each window.
- Hypothetical entry at week mark — no trade costs, timing waits, or AI gates unless you widen live paper tracks.
- Near-miss selection is a **research gate**, not a live screen tier — tune `--min-conviction` deliberately.

See also [`exit-timing-cohorts.md`](exit-timing-cohorts.md) for live paper cohorts.
