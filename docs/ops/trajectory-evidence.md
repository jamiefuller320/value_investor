# Trajectory evidence (full-range opinion tracking)

Four complementary pieces for **trajectory-change marker** development. Built together
from weekly archives + latest screen — not whole-index memos.

| Piece | Artifact | Scope |
|-------|----------|-------|
| **1. Transition ledger** | `trajectory_transitions.json` | Sparse events when signal/conviction/timing flips (all tiers) |
| **2. Boundary watch** | `trajectory_boundary_watch.json` | ~30–80 names with **core** tier-boundary tags (not static mid-pack) |
| **3. Loser snapshot cards** | `loser_snapshot_cards.json` | avoid + failed-buy alumni (~50 names) |
| **4. Outcome labels** | `trajectory_evidence_review.json` | Stratified forward returns and prediction hit rates at 1/4/8/12 archive-week horizons; weeks-to-realization |

## Command

```bash
ftse-trajectory-evidence --data-dir docs/data
ftse-loser-snapshot-cards --data-dir docs/data   # piece 3 only
```

## Boundary tags

**Core** (required for panel membership):

- `pre_buy` — hold with conviction ≥ 0.28
- `pre_avoid` — hold with conviction ≤ 0.12
- `hold_improving` / `hold_deteriorating` — hold with directional `signal_trend`
- `buy_weakening` — buy-tier with deteriorating trend
- `strong_buy_candidate` — buy with conviction ≥ 0.50
- `timing_wait_on_buy_tier` — buy/strong_buy with timing wait
- `avoid_recovery_candidate` — avoid with conviction ≥ 0.20

**Secondary** (never qualifies alone):

- `fresh_opinion` — trend `new` on hold/buy/strong_buy

Panel rows also carry cheap features: conviction gaps to buy/avoid floors,
`data_quality_score`, sector, overlay fields, `weeks_on_boundary`, and
`conviction_delta_1w` / `conviction_delta_4w` from archive history.

## Why this exists

The ledger is **not** a standalone dataset. Sunday `ftse-trajectory-evidence` ranks
**model focus candidates** (weak transition keys, sub-chance directional hit rates,
early-vs-price lag). Those candidates — together with slim **loser snapshot cards**,
**exclusion** ladder priors, and **exit-timing** readiness — feed **analysis-review**,
whose output is proposed experiments to refine assessment models and filters.
Learning Director checks that specialist reviews actually proposed those experiments —
it does not run a second scoring or churn loop.

See [analysis-review.md](analysis-review.md) and [learning-director.md](learning-director.md).

## Outcome horizons

Each transition event records what the screen asserted at `week_to` (signal, conviction,
timing, overlay) and scores forward price paths at **1 / 4 / 8 / 12 archive-week**
horizons — no memo re-runs.

Per event (`trajectory_transitions.json` → `outcomes`):

| Field | Meaning |
|-------|---------|
| `forward_return_{1,4,8,12}w` | Price return from transition week to +N archives |
| `prediction_success_{1,4,8,12}w` | Did return align with implied direction? |
| `weeks_to_realization` | First week (1–12) where cumulative return matched prediction |
| `realization_within_12w` | Whether prediction materialized within 12 archive weeks |

Review rollup adds `prediction_hit_rate_by_horizon`, `weeks_to_realization` summary
(median lag, within-4w rate), and **`model_focus_candidates`** — ranked weak spots
for analysis-review scoring experiments.

## When to run

Sunday `analysis-review.yml` after `ftse-archive-history` densifies
`docs/data/history/` from dashboard archives (needs `history/run_*.json.gz` +
`latest.json`).

## Thin history note

With &lt;3 archive snapshots, forward outcome labels on transitions will be empty — the
ledger still accumulates events week-on-week. Longer horizons need more history (≥13
snapshots for full 12-week labels). Value compounds as archive weeks extend.

Live screen snapshots and archive backfills now retain trajectory fields
(`signal_trend`, `weeks_at_signal`, `passed_families`, `name`, `sector`,
`price_vs_sma200_pct`) so boundary enrichment improves as history thickens.

See also: [loser-snapshot-cards.md](loser-snapshot-cards.md).
