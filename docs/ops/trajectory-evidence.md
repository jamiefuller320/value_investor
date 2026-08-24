# Trajectory evidence (full-range opinion tracking)

Four complementary pieces for **trajectory-change marker** development. Built together
from weekly archives + latest screen — not whole-index memos.

| Piece | Artifact | Scope |
|-------|----------|-------|
| **1. Transition ledger** | `trajectory_transitions.json` | Sparse events when signal/conviction/timing flips (all tiers) |
| **2. Boundary watch** | `trajectory_boundary_watch.json` | ~30–80 names near tier boundaries (not 143 static holds) |
| **3. Loser snapshot cards** | `loser_snapshot_cards.json` | avoid + failed-buy alumni (~50 names) |
| **4. Outcome labels** | `trajectory_evidence_review.json` | Stratified forward returns and prediction hit rates at 1/4/8/12 archive-week horizons; weeks-to-realization |

## Command

```bash
ftse-trajectory-evidence --data-dir docs/data
ftse-loser-snapshot-cards --data-dir docs/data   # piece 3 only
```

## Boundary tags (examples)

- `pre_buy` — hold with conviction ≥ 0.28
- `pre_avoid` — hold with conviction ≤ 0.12
- `buy_weakening` — buy-tier with deteriorating trend
- `strong_buy_candidate` — buy with conviction ≥ 0.50
- `timing_wait_on_buy_tier` — buy/strong_buy with timing wait
- `avoid_recovery_candidate` — avoid with conviction ≥ 0.20

## Why this exists

The ledger is **not** a standalone dataset. Sunday `ftse-trajectory-evidence` ranks
**model focus candidates** (weak transition keys, sub-chance directional hit rates,
early-vs-price lag). Those candidates are the input to **analysis-review**, whose
output is proposed `[scoring]` / `[offline_sim]` experiments to refine assessment
models (conviction, timing overlay, family weights). Learning Director checks that
analysis-review actually proposed those experiments — it does not run a second scoring loop.

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

Sunday `analysis-review.yml` after exclusion archive (needs `history/run_*.json.gz` + `latest.json`).

## Thin history note

With &lt;3 archive snapshots, forward outcome labels on transitions will be empty — the
ledger still accumulates events week-on-week. Longer horizons need more history (≥13
snapshots for full 12-week labels). Value compounds as archive weeks extend.

See also: [loser-snapshot-cards.md](loser-snapshot-cards.md).
