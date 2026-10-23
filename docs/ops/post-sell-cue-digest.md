# Post-sell cue digest (observe) — package M

Observe-only rollup of **timing + selection** experiment cues from inventory
already collected. Does **not** seal N205, apply knobs, or invent a new paper
track.

**Product claim:** cue readiness + selection skeleton feed — **not** full
episode assessment and **not** cross-epoch truth.

| Layer | Behavior |
|-------|----------|
| Learning question | What timing + selection cues follow from closed episodes + N200/exit-timing/shadow/archive priors? |
| Trigger | Daily `collect_ops_findings` → `check_post_sell_cue_digest` |
| Store | `docs/data/post_sell_cue_digest.json` (ops-monitor `GHA_COMMIT_OPTIONAL`) |
| Finding | **Post-sell cue digest (observe)** (`auto_fixable=False`, category `research`) |
| Selection skeleton | Nested `selection_postmortem_skeleton` — ended control (`buy_tier_level`) closed sells; feeds **N205** design only (`sealed=false`) |
| Hub feed | `hub_feed.explore_candidates` (default) / `push_candidates` (empty unless cue maps to a live human gate). Daily hub Status/Push/Explore consume this feed (**L620**) — fail closed if `hub_feed` missing; see Project store `docs/daily-hub-attention-redesign.md` |
| Sunday nest | Human checklist `sunday-post-sell-cues` next to `sunday-ai-path-scoreboard`; analysis-review slim key `post_sell_cue_digest` |

## Epoch key (required) + widen gate

Owner fork **F** (locked): **require an epoch key on every cue/row before
widening beyond FTSE control `buy_tier_level` closed sells.** This PR does
**not** widen the universe.

Each skeleton row joins its exit fill to `rebalance_log` (trade `id`, else
ticker+`acted_at` within 2d) and stamps:

| Field | Source |
|-------|--------|
| `track_id` / `track_label` | exit-pass log entry |
| `capital_epoch` | surrogate `track_label\|fund.config.created_at` |
| `knob_epoch_started_at` | exit-pass (**field required**; value may be `null`) |
| `rebalance_schema_version` | exit-pass `schema_version` |
| `screen_source_generated_at` / `run_at` | exit-pass `screen_source` |
| `selection_fingerprint` | stable hash of selection knobs + `trade_cost_pct` |

**Fail closed:** if the join fails or `knob_epoch_started_at` is absent as a
key, the row is `epoch_unknown` and is **excluded** from selection experiment
cue claims (no invented epoch).

**Stratify:** `epoch_lesson_status` is `current_epoch` | `older_epoch` |
`epoch_unknown`. Default Sunday / selection cue population =
**current capital/knob epoch only** (screen epoch still differs per pass and is
carried on the row). Pre-fix trades must not pool unlabeled with current.

**Widen gate:** `widen_gate.widened=false` until every cue/row carries the key.
Do not add other markets / twins / Suite A books to this digest until then.
Code comment + `non_goals` + this runbook enforce the lock.

N200 timing cues carry `registration_id` and an explicit
**population ≠ FTSE control** label.

## Buy-set stamps (no anachronism)

- `in_buy_set_at_exit` — exit-pass `screen_buy_tier` **raw signal** in
  `{buy, strong_buy}` (not holdings membership).
- `in_buy_set_now` — today's `latest.json` buy set (labeled).
- Legacy `still_in_buy_set` is an alias of **now** with
  `still_in_buy_set_as_of=latest_json_now` — do not read it as exit-time thesis.

Skeleton also carries `entry_at`, `hold_days`, `exit_kind` (from exit-shadow when
present), and optional `post_exit_7d` when a 7d shadow checkpoint exists.

## Inputs (reuse only)

- `docs/data/n200_tech_timing_observe.json` — entry/exit lever verdicts
- `docs/data/paper_automation/learning_tracks_exit_timing.json` — readiness gaps
- `docs/data/paper_automation/learning_tracks_exit_shadow.json` — closed/open
- Control fund closed sells — `paper_automation/buy_tier_level/automated_fund.json`
- Control `rebalance_log.json` — epoch join (required for cue claims)
- Control `exit_shadow.json` — `exit_kind` / optional 7d marks
- Optional: `exit_timing_near_miss_review.json` (L121 caveat: priors only)
- Latest buy-set + `loser_snapshot_cards.json` for selection skeleton pointers

## Explicit non-goals

No `--apply`, no new paper track, no N205 seal, no LLM episode debriefs, no
archive→live probability blend, no hard veto, **no widen beyond FTSE control
until epoch keys on every cue/row**. Thicken via L368 / N25 / L117 / sealed N205
only after M cues are used.

## Related

- [exit-timing-cohorts.md](exit-timing-cohorts.md)
- [n200-tech-timing-observe.md](n200-tech-timing-observe.md)
- [ops-monitor.md](ops-monitor.md)
- [pit-decision-autopsy.md](pit-decision-autopsy.md) (freeze field list)
- [llm-agree-veto-shadow.md](llm-agree-veto-shadow.md#sunday-ai-path-scoreboard) (Sunday neighbor)
