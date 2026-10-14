# Post-sell cue digest (observe) — package M

Observe-only rollup of **timing + selection** experiment cues from inventory
already collected. Does **not** seal N205, apply knobs, or invent a new paper
track.

| Layer | Behavior |
|-------|----------|
| Learning question | What timing + selection cues follow from closed episodes + N200/exit-timing/shadow/archive priors? |
| Trigger | Daily `collect_ops_findings` → `check_post_sell_cue_digest` |
| Store | `docs/data/post_sell_cue_digest.json` (ops-monitor `GHA_COMMIT_OPTIONAL`) |
| Finding | **Post-sell cue digest (observe)** (`auto_fixable=False`, category `research`) |
| Selection skeleton | Nested `selection_postmortem_skeleton` — ended control (`buy_tier_level`) closed sells; feeds **N205** design only (`sealed=false`) |
| Hub feed | `hub_feed.explore_candidates` (default) / `push_candidates` (empty unless cue maps to a live human gate). Sibling daily-hub ship consumes this — see Project store `docs/daily-hub-attention-redesign.md` |
| Sunday nest | Human checklist `sunday-post-sell-cues` next to `sunday-ai-path-scoreboard`; analysis-review slim key `post_sell_cue_digest` |

## Inputs (reuse only)

- `docs/data/n200_tech_timing_observe.json` — entry/exit lever verdicts
- `docs/data/paper_automation/learning_tracks_exit_timing.json` — readiness gaps
- `docs/data/paper_automation/learning_tracks_exit_shadow.json` — closed/open
- Control fund closed sells — `paper_automation/buy_tier_level/automated_fund.json`
- Optional: `exit_timing_near_miss_review.json` (L121 caveat: priors only)
- Latest buy-set + `loser_snapshot_cards.json` for selection skeleton pointers

## Explicit non-goals

No `--apply`, no new paper track, no N205 seal, no LLM episode debriefs, no
archive→live probability blend, no hard veto. Thicken via L368 / N25 / L117 /
sealed N205 only after M cues are used.

## Related

- [exit-timing-cohorts.md](exit-timing-cohorts.md)
- [n200-tech-timing-observe.md](n200-tech-timing-observe.md)
- [ops-monitor.md](ops-monitor.md)
- [llm-agree-veto-shadow.md](llm-agree-veto-shadow.md#sunday-ai-path-scoreboard) (Sunday neighbor)
