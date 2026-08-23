# Exclusion-universe archive sim (observe-only)

Offline lab for **graduated loser-filter tightening**: compare equal-weight forward
returns of the full screened (or buy-tier) universe vs the same universe minus
point-in-time exclusions. Gross of costs — isolates whether exclusion rules add
alpha before portfolio construction and churn.

Complements:

- **Knob calibration** — portfolio replay on `rebalance_log` (winner/loser catch rates)
- **Exit-timing archive** — near-miss hold/swap paths below buy tier
- **Decision-review** — reactive knob tightening on live paper marks

## Purpose

Answer: *“Does stepping selectivity tighter (conviction floors, timing wait, AI
overlay gates) improve universe returns?”* before promoting rules to paper knobs.

Primary metric per ladder rung:

```
exclusion_alpha = EW(filtered universe) − EW(baseline universe)
```

Secondary:

- **Top-N book overlay** — top `max_positions` by conviction from filtered pool
- **Hindsight quartiles** (evaluation only) — bottom/top quartile exclude/retain rates

## When to run

| Trigger | Command |
|---------|---------|
| **After archive backfill** | `ftse-archive-history --data-dir docs/data` then exclusion archive |
| **Sunday analysis prep** | Manual or CI hook before `ftse-analysis-review` |
| **Manual** | `ftse-exclusion-universe-archive --output-dir docs/data` |

Requires **≥2** archived weekly snapshots (`history/run_*.json.gz`). Readiness for
priors defaults to **≥4** consecutive week pairs and avg filtered pool **≥15** names.

## Universe modes

| Mode | Flag | Baseline pool |
|------|------|---------------|
| Buy-tier (default) | `--universe buy_tier` | `strong_buy` / `buy` screen signals only |
| Full screened | `--universe full_screened` | All ~249 FTSE 350 screened names |

Exclusions are always **point-in-time** (screen fields at week *t*). Hindsight
quartiles use forward returns for scoring only — never to define exclusions.

## Default tightening ladder

| Step | Cumulative filter |
|------|-------------------|
| `u0` | Baseline universe |
| `u1` | Exclude `avoid` |
| `u2` | + exclude `timing_signal=wait` |
| `u3` | + `conviction >= 0.25` |
| `u4` | + `conviction >= 0.35` |
| `u5` | + `conviction >= 0.45` |
| `u6` | + effective buy-tier (overlay) |
| `u7` | + `research_verdict=accumulate` |

Skip AI overlay rungs with `--no-ai-overlay-steps`. Custom conviction rungs:

```bash
ftse-exclusion-universe-archive \
  --output-dir docs/data \
  --conviction-ladder 0.2,0.3,0.4,0.5 \
  --no-ai-overlay-steps
```

## Commands

```bash
# Buy-tier universe (matches live decision path)
ftse-exclusion-universe-archive --output-dir docs/data

# Full screened universe + PIT research overlay
ftse-exclusion-universe-archive \
  --output-dir docs/data \
  --universe full_screened \
  --use-adjusted-signal \
  --json

# Tighter recommendation gate (small buy-tier weeks)
ftse-exclusion-universe-archive \
  --output-dir docs/data \
  --min-filtered-pool 8 \
  --min-week-pairs 2
```

## Artifacts

Written to `--output-dir`:

| File | Purpose |
|------|---------|
| `exclusion_universe_archive.json` | Ladder summaries + config |
| `exclusion_universe_review.json` | Readiness, recommended step, analysis-review payload |

Sunday `ftse-analysis-review` payload includes `exclusion_universe` when the review
file exists.

## Interpreting results

| Field | Meaning |
|-------|---------|
| `cumulative_exclusion_alpha` | Sum of weekly `filtered_ew − baseline_ew` |
| `positive_alpha_rate` | Share of weeks filtered beat baseline |
| `mean_bottom_quartile_exclude_rate` | Hindsight: share of worst names removed |
| `book_summary` | Top-N conviction book vs baseline EW |
| `recommended_step` | Best rung with enough pool depth and week pairs |

**Promote workflow (human gate):**

1. Confirm positive `cumulative_exclusion_alpha` on buy-tier mode
2. Check hindsight bottom-quartile exclude rate rises without collapsing pool size
3. Replay winning rung on `rebalance_log` (`offline_sim`) with costs
4. Only then seed `paper_knobs` or a paper track ladder experiment

Do **not** auto-apply from archive priors — N3 screen thresholds stay frozen.

## Limitations

- Weekly snapshot marks only (same as backtest / exit-timing archive)
- No trade costs, position-cap churn, or AI gate timing in universe EW path
- Thin buy-tier weeks → lower confidence; use `--min-filtered-pool` accordingly
- `u6`/`u7` overlay steps need `adjusted_signal` / memo store for PIT resolution

See also: [knob-calibration.md](knob-calibration.md), [exit-timing-archive-sim.md](exit-timing-archive-sim.md).
