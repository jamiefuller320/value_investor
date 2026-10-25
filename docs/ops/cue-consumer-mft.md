# Cue-consumer MFT observe lab (super book)

**Status:** observe-only **lab skeleton** (2026-10-25).  
**lab_id:** `cue_consumer_mft`  
**registration_id:** `cue-consumer-mft-v0`  
**deferred_id:** `N222` (skeleton shipped; spawn/cull/rule-aware remain deferred)

Declared-incomparable fixed-stake mid-flight-tune sleeve. Rolls Package **M**
autopsy critique into knob epochs on **this lab only**. Emits thin
`hardened_ruleset_proposal` candidates under novelty / per-root cap / cull
stubs — never Package **L** on sealed cue books, never silent strand-A promote,
never credit cue-book historical NAV as lab wins.

Design pins: Project store `super-book-midflight-tune-2026-10-25.md`,
`post-sale-autopsy-llm-voice-2026-10-25.md`.

## Learning question

Given frozen cue-sources, can a declared-incomparable fixed-stake cue-consumer
sleeve that rolls critique into mid-flight tunes on itself prove/falsify lesson
incorporation on five fair-cost levers, emit thin but novel hardened proposals
into a lineage-tracked, cap-bounded sealed-twin population with declared
periodic cull, without credit-claim, Package L, silent strand-A promote, or
active-model noise spray?

## Spec (v0 skeleton)

| Knob | Value |
|------|-------|
| Stake | Fixed **100** local (cash/NAV parked) |
| Scoreboard | `incomparable_midflight_tune` — MoM on 5 fair-cost levers |
| Cue selection | Short whitelist, PIT only (`cue_ts ≤ decision_ts`) |
| Mid-flight markers | `knob_epoch_started_at`, `tune_spec_id` (lab only) |
| Thin emit (Q6B) | Closes-primary ≥**3** citing levers; MoM diagnostic only |
| Same-day exits | Soft bias / scoreboard penalty; exception `major_error_reverse` with durable cites — **not** a hard ban |
| Live influence | `influences_live=false` |
| Findings | `auto_fixable=false` |

### Five MoM levers

1. Stock choice  
2. Buy timing  
3. Buy strategy  
4. Sell timing (default bias against same-calendar-day exit)  
5. Sell strategy (`major_error_reverse` only for same-day)

## Start gate (Q8B)

First **evolutionary shadows** / thin sealed children become eligible after a
**named open-autopsy cohort checkpoint** completes — **not** forever-wait on
`post_sale_review_queue.active_count == 0` while daily `just_sold` refills.

### How measured

1. Freeze a cohort of open-autopsy `review_id`s into
   `docs/data/cue_consumer_mft_start_gate.json` → `cohort_review_ids` under
   `checkpoint_id` (default `open_autopsy_cohort_2026_q4`).
2. Checkpoint **completes** when every frozen id is Accept/Comment-actioned in
   `post_sale_review_labels.json` — even if new sells refill the active queue.
3. Alternate calendar: `on_or_after` **2026-12-01**.

Human task: `adhoc-cue-consumer-mft-start-gate`.

## Thin emit + anti-noise stubs

| Interface | Behaviour now | Remainder |
|-----------|---------------|-----------|
| Soft readiness | ≥3 closes + proposal hygiene | — (L629 scaffolding shipped) |
| Novelty gate | fingerprint reject/merge/spawn stub | **N226** full distance |
| Per-root cap | ≤3 active; cull/replace policy stub | **N227** |
| Cull / archive | declared criteria stub; cull≠live promote | **N227** / **L631** |
| Spawn sealed child | scaffold proposal only | **N223** / **L630** |
| Rule-aware LLM decide | not in skeleton | **N228** |
| Chart draw tools | not shipped | **N229** |

## Automation

- **Trigger:** daily ops-monitor `check_cue_consumer_mft`
- **Stores:**
  - `docs/data/cue_consumer_mft_observe.json`
  - `docs/data/cue_consumer_mft_registration.json`
  - `docs/data/cue_consumer_mft_start_gate.json`
- **Findings** (`auto_fixable=False`):
  - **Cue-consumer MFT lab refreshed**
  - **Cue-consumer MFT start gate eligible (evolutionary shadows)** (when Q8B/calendar clears)
  - **Cue-consumer MFT lab failed**
- **CLI:** `ftse-cue-consumer-mft` (ad-hoc drill-down)

## Related

- [post-sale-review-queue.md](post-sale-review-queue.md) — Package M autopsy intake
- [fair-cost-primacy.md](fair-cost-primacy.md) — fixed-stake v0
- [ops-monitor.md](ops-monitor.md#full-automation-wiring) — wiring bar
- [llm-live-path-evidence.md](llm-live-path-evidence.md) — no silent LLM live influence
