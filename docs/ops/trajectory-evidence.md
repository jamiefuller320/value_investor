# Trajectory evidence (full-range opinion tracking)

Four complementary pieces for **trajectory-change marker** development. Built together
from weekly archives + latest screen — not whole-index memos.

| Piece | Artifact | Scope |
|-------|----------|-------|
| **1. Transition ledger** | `trajectory_transitions.json` | Sparse events when signal/conviction/timing flips (all tiers) |
| **2. Boundary watch** | `trajectory_boundary_watch.json` | ~30–80 names near tier boundaries (not 143 static holds) |
| **3. Loser snapshot cards** | `loser_snapshot_cards.json` | avoid + failed-buy alumni (~50 names) |
| **4. Outcome labels** | `trajectory_evidence_review.json` | Stratified 1-week forward returns by transition type |

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

## When to run

Sunday `analysis-review.yml` after exclusion archive (needs `history/run_*.json.gz` + `latest.json`).

## Thin history note

With &lt;3 archive snapshots, forward outcome labels on transitions will be empty — the
ledger still accumulates events week-on-week. Value compounds as history extends.

See also: [loser-snapshot-cards.md](loser-snapshot-cards.md).
