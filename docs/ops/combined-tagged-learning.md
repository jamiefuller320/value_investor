# Combined tagged learning (observe-only)

Tagged **analysis join** across independent paper books. Does **not** merge NAV,
apply knobs, or change live exit policy (**N23**).

Learning question: after closed 84d shadows thicken, does the combined
early-vs-good-exit / first-episode story match each per-market story?

## Identity

Live FTSE books sit at `docs/data/paper_automation/` (not `markets/<id>/`).
Canonical live market id is **`ftse350`**. euro_depth / sp500 / FTSE all use
`track_id=buy_tier_level`, so concat without `market_id` collides.

Join key: `market_id|track_id|ticker|episode_index`.

First-episode strip: the first full-position sell of a name on that book.
Later buy-sell-buy fragments stay in the all-records rollup but are excluded
from `first_episode` stats.

## Wiring

| Layer | Detail |
|-------|--------|
| Per-book stamp | Weekday `ftse-paper-auto` / shard weekday → `run_exit_shadow_pass(market_id=…)` writes `market_id` + episode fields on `exit_shadow.json` / review |
| Combined store | `docs/data/combined_tagged_learning.json` — combined vs `by_market` open/closed, `by_exit_kind`, `grace_vs_rotation`, first-episode subset |
| Trigger | Daily ops-monitor `collect_ops_findings` → `check_combined_tagged_learning` |
| Commit | L460 optional: `scripts/gha_commit_ops_monitor.sh` (`combined_tagged_learning.json`) |
| Dashboard | Observe utilization card (L461) — freshness + unstamped-row trajectory (lower missing `market_id` is better). Zero closed N is not a warn |
| Finding | **Combined tagged learning store stale** when missing/stale (`auto_fixable=False`) |
| CLI (optional) | `ftse-tagged-learning` |

Empty / zero-closed structure is expected until 84d cohorts thicken.
