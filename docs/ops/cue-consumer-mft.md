# Cue-consumer MFT observe lab (super book)

**Status:** observe-only **lab armed** (2026-10-26) — awaiting Q8B cohort freeze confirm for evolutionary shadows.  
**lab_id:** `cue_consumer_mft`  
**registration_id:** `cue-consumer-mft-v0`  
**lab_arm_marker_id:** `mft-lab-arm-epoch0-v0`  
**deferred_id:** `N222` (skeleton shipped; spawn/cull/rule-aware remain deferred)

Declared-incomparable fixed-stake mid-flight-tune sleeve. Rolls Package **M**
autopsy critique into knob epochs on **this lab only**. Emits thin
`hardened_ruleset_proposal` candidates under novelty / per-root cap / cull
stubs — never Package **L** on sealed cue books, never silent strand-A promote,
never credit cue-book historical NAV as lab wins.

Design pins: Project store `super-book-midflight-tune-2026-10-25.md`,
`post-sale-autopsy-llm-voice-2026-10-25.md`,
`super-book-judgment-in-the-round-2026-10-26.md`,
`super-book-start-progress-2026-10-26.md`.

## Learning question

Given frozen cue-sources, can a declared-incomparable fixed-stake cue-consumer
sleeve that rolls critique into mid-flight tunes on itself prove/falsify lesson
incorporation on five fair-cost levers, emit thin but novel hardened proposals
into a lineage-tracked, cap-bounded sealed-twin population with declared
periodic cull, without credit-claim, Package L, silent strand-A promote, or
active-model noise spray?

## Spec (v0 armed observe)

| Knob | Value |
|------|-------|
| Stake | Fixed **100** local (cash/NAV parked) |
| Scoreboard | `incomparable_midflight_tune` — MoM on 5 fair-cost levers |
| Cue selection | Short whitelist, PIT only (`cue_ts ≤ decision_ts`) |
| Mid-flight markers | `knob_epoch_started_at`, `tune_spec_id`, `lab_arm_marker_id` (lab only) |
| Thin emit (Q6B) | Closes-primary ≥**3** citing levers; MoM diagnostic only |
| Same-day exits | Soft bias / scoreboard penalty; exception `major_error_reverse` with durable cites — **not** a hard ban |
| Judgment rubric | `judgment_in_the_round_v0` schema stub (B1–B6 / S1–S6); fill = **N228** |
| Live influence | `influences_live=false` |
| Findings | `auto_fixable=false` |
| Spend | Investment observe — **does not** steal Data P1 fat slot |

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

Lab **arming** (observe refresh, autopsy alignment feed, judgment schema, epoch
markers) runs **before** this gate. Evolutionary spawn does not.

### Named cohort definition (`open_autopsy_cohort_2026_q4`)

Selection id: **`non_mechanical_open_autopsy_v0`**

| Include | Exclude |
|---------|---------|
| Active queue rows whose `exit_reason` starts with `identity_break` or `quality_break` | `reply:` dialogue thread ids |
| Snapshot at propose/freeze time | Mechanical piles (`hold_trading_days`, `leave_buy_tier`, blank reason) |

Prefs: prefer identity-break / non-mechanical over blanket max-days / leave-buy-cohort review.

### How measured

1. Daily refresh (or `ftse-cue-consumer-mft propose-cohort --persist`) writes
   sticky `proposed_cohort_review_ids` into
   `docs/data/cue_consumer_mft_start_gate.json` under `checkpoint_id`
   `open_autopsy_cohort_2026_q4` — **does not freeze**.
2. **Owner decision:** confirm freeze via
   `ftse-cue-consumer-mft freeze-cohort --apply` (copies proposed →
   `cohort_review_ids`). Rebuild first with `propose-cohort` if the set should
   shrink/change.
3. Checkpoint **completes** when every frozen id is Accept/Comment-actioned in
   `post_sale_review_labels.json` — even if new sells refill the active queue.
4. Alternate calendar: `on_or_after` **2026-12-01**.

Human task: `adhoc-cue-consumer-mft-start-gate`.

## Thin emit + anti-noise stubs

| Interface | Behaviour now | Remainder |
|-----------|---------------|-----------|
| Soft readiness | ≥3 closes + proposal hygiene | — (L629 scaffolding shipped) |
| Novelty gate | fingerprint reject/merge/spawn stub | **N226** full distance |
| Per-root cap | ≤3 active; cull/replace policy stub | **N227** |
| Cull / archive | declared criteria stub; cull≠live promote | **N227** / **L631** |
| Spawn sealed child | scaffold proposal only | **N223** / **L630** |
| Rule-aware LLM decide | schema stub only | **N228** |
| Chart draw tools | not shipped | **N229** |
| Episode walker / paper fills | not shipped | deferred |

## Automation

- **Trigger:** daily ops-monitor `check_cue_consumer_mft`
- **Stores:**
  - `docs/data/cue_consumer_mft_observe.json`
  - `docs/data/cue_consumer_mft_registration.json`
  - `docs/data/cue_consumer_mft_start_gate.json`
- **Findings** (`auto_fixable=False`):
  - **Cue-consumer MFT lab refreshed**
  - **Cue-consumer MFT lab armed (observe)**
  - **Cue-consumer MFT Q8B cohort freeze proposed — owner confirm**
  - **Cue-consumer MFT start gate eligible (evolutionary shadows)** (when Q8B/calendar clears)
  - **Cue-consumer MFT lab failed**
- **CLI:** `ftse-cue-consumer-mft` (`refresh` | `propose-cohort` | `freeze-cohort`)

## Related

- [post-sale-review-queue.md](post-sale-review-queue.md) — Package M autopsy intake
- [fair-cost-primacy.md](fair-cost-primacy.md) — fixed-stake v0
- [ops-monitor.md](ops-monitor.md#full-automation-wiring) — wiring bar
- [llm-live-path-evidence.md](llm-live-path-evidence.md) — no silent LLM live influence
- [llm-agree-veto-shadow.md](llm-agree-veto-shadow.md) — propose → agree/veto pattern
