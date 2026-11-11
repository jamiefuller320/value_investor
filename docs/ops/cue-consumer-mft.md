# Cue-consumer MFT observe lab (super book)

**Status:** observe-only **lab paper episode walker active** when Q8B/calendar
eligible (2026-10-28).  
**lab_id:** `cue_consumer_mft`  
**registration_id:** `cue-consumer-mft-v0`  
**lab_arm_marker_id:** `mft-lab-arm-epoch0-v0`  
**tune_spec_id:** `mft-tune-spec-cap50-epoch1-v0` (epoch-1 open-cap raise; prior `mft-tune-spec-epoch0-v0`)  
**walker_marker_id:** `mft-episode-walker-v0`  
**deferred_id:** `N222` (skeleton + walker shipped; spawn/cull/rule-aware remain deferred)

Declared-incomparable fixed-stake mid-flight-tune sleeve. Rolls Package **M**
autopsy critique into knob epochs on **this lab only**. Emits thin
`hardened_ruleset_proposal` candidates under novelty / per-root cap / cull
stubs — never Package **L** on sealed cue books, never silent strand-A promote,
never credit cue-book historical NAV as lab wins.

Design pins: Project store `super-book-midflight-tune-2026-10-25.md`,
`post-sale-autopsy-llm-voice-2026-10-25.md`,
`super-book-judgment-in-the-round-2026-10-26.md`,
`super-book-start-progress-2026-10-26.md`.

## Role under the single track (owner, 2026-11-04)

The strategy book is the project's single track to live capital
([plan](strategy-reorientation-plan.md#single-track-to-live-owner-2026-11-04)).
This lab's aim, training toward better timing, carries over; its own book does
not become a route to live, because it tunes itself mid-run and its scores are
declared incomparable.

| Part of this lab | What happens |
|------------------|--------------|
| Lab paper book (buy on the weekly cue, hold 63 trading days or exit on an identity break) | Keeps running unchanged on the FTSE screen as an outside reference. No new knob epochs. |
| Same policy as a control | The strategy book carries it as its **buy-on-signal control** on the strategy book's own universe ([registration section 8](strategy-book-registration.md#8-scoring)). That is where "does timing add anything?" is answered. |
| Post-sale reviews, judgment-in-the-round trail, five-lever scoring | On strategy-book closes ([strategy-book-reviews.md](strategy-book-reviews.md)). Built, awaiting the first close. The lab's own queue is unchanged. |
| Mid-flight tunes and hardened-ruleset proposals | Become inputs to the strategy book's version review. They do not spawn sealed children. |
| Sealed-child spawn, novelty distance, cull (N223, N226, N227) | Not built while the single-track section holds. |

The open-cap raise to 50 (epoch 1) is the last knob epoch on this lab under
this decision.

## Learning question

Given frozen cue-sources, can a declared-incomparable fixed-stake cue-consumer
sleeve that rolls critique into mid-flight tunes on itself prove/falsify lesson
incorporation on five fair-cost levers, emit thin but novel hardened proposals
into a lineage-tracked, cap-bounded sealed-twin population with declared
periodic cull, without credit-claim, Package L, silent strand-A promote, or
active-model noise spray?

## Spec (v0 armed observe + lab fills)

| Knob | Value |
|------|-------|
| Stake | Fixed **100** local (cash/NAV parked) |
| Scoreboard | `incomparable_midflight_tune` — MoM on 5 fair-cost levers |
| Cue selection | Short whitelist, PIT only (`cue_ts ≤ decision_ts`) |
| Mid-flight markers | `knob_epoch_started_at`, `tune_spec_id`, `lab_arm_marker_id` (lab only); closed epochs in `mid_flight_tune.epoch_history` |
| Open-position cap | **50** concurrent lab opens (`MAX_OPEN_POSITIONS`; epoch-1 raise from 30 on 2026-11-01 — same book, not a dual-cap twin) |
| Lab paper walker | Progressive PIT cue clears → open/close lab episodes (`mft-episode-walker-v0`) when `evolutionary_shadows_eligible` |
| Exit | 63 trading days **or** cue identity break; same-day soft bias on close |
| Thin emit (Q6B) | Closes-primary ≥**3** citing levers; MoM diagnostic only |
| Same-day exits | Soft bias / scoreboard penalty; exception `major_error_reverse` with durable cites — **not** a hard ban |
| Judgment rubric | `judgment_in_the_round_v0`; **N228** deterministic cite fill on decide trail (B1–B6 / S1–S6); missing cells stay `unknown`; misfit_evidence when timing wait vs cue or same-day exit without `major_error_reverse` |
| Live influence | `influences_live=false` (fail-closed; `authorize_judgment_live_influence` always false) |
| Findings | `auto_fixable=false` |
| Spend | Investment observe — **does not** steal Data P1 fat slot |

### Five MoM levers

1. Stock choice  
2. Buy timing  
3. Buy strategy  
4. Sell timing (default bias against same-calendar-day exit)  
5. Sell strategy (`major_error_reverse` only for same-day)

## Episode walker / lab paper fills

When the start gate is eligible, daily refresh walks archived weekly screen
snapshots and records **lab** fixed-stake paper positions:

1. Progressive clears on whitelist cue sources (`n210_ai_filter` preferred,
   then `n200_raw_buy_tier`, then `ftse_control_buy_tier`) — one open stake per
   ticker (no double-stake on the lab book).
2. PIT filter via `select_pit_cues` (look-ahead rejected; missing cue stamp
   fail-closed).
3. Durable open evidence: cue id/ts, pit_ok, **N228** judgment-in-the-round
   fill citing screen/cue fields (B1–B6); unknown when cites missing.
4. Close at hold horizon (63 trading days) or cue identity break; attach
   same-day soft-bias assessment **and** sell-side checklist cites (S1–S6).
5. Persist open/closed samples + path scoreboard
   (`fair_cost_episode_pct` median) on `docs/data/cue_consumer_mft_observe.json`.

**Not in v0:** sealed-child spawn (N223), full novelty distance (N226), cull
factory (N227), remote LLM voice on the same checklist (optional later),
weekday paper-auto track wiring.

Open-position cap (default **50**, raised from **30** on 2026-11-01 with a new
`tune_spec_id` / `knob_epoch_started_at`) limits lab spray; sealed anti-noise
caps still apply only when spawn is built. Cap **100** stays parked (`N244`).
Owner locked same-book epoch-raise for lens volume — do **not** spawn a dual-cap
twin for this fork (`L658` remains later for other A/B caps).

**Epoch stratification (L640 / scoreboards):** use
`mid_flight_tune.knob_epoch_started_at` (current) +
`mid_flight_tune.epoch_history[]` (closed density epochs with `ended_at` /
`end_reason`). Stratify MoM / fair-cost cells by `entry_run_at` vs that
boundary. MoM lever stubs are still null — **do not** claim post-raise cohort
median continuous with epoch-0. `influences_live=false`.

### How to verify

```bash
ftse-cue-consumer-mft refresh
# expect pipeline_status=episode_walker_active when start gate eligible
# open_lab_episodes / closed_lab_episodes > 0 once archive has progressive clears
# max_open_positions=50; tune_spec_id=mft-tune-spec-cap50-epoch1-v0
python -c "import json; d=json.load(open('docs/data/cue_consumer_mft_observe.json')); m=d['mid_flight_tune']; print(d['pipeline_status'], d['open_lab_episodes'], d['closed_lab_episodes'], d['episode_walker']['status'], m.get('max_open_positions'), m.get('tune_spec_id'), m.get('knob_epoch_started_at'))"
```

## Start gate (Q8B)

First **evolutionary shadows** / thin sealed children become eligible after a
**named open-autopsy cohort checkpoint** completes — **not** forever-wait on
`post_sale_review_queue.active_count == 0` while daily `just_sold` refills.

Lab **arming** (observe refresh, autopsy alignment feed, judgment schema, epoch
markers) runs **before** this gate. The **lab paper episode walker** also waits
on this gate (or calendar). Evolutionary sealed spawn still waits on novelty/cap
scaffolding (N223+) after eligibility.

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
   `post_sale_review_labels.json` — joined via canonical `actioned_review_ids`
   **and** top-level `events[].kind` (`accept` / `comment` / `duplicate`) — even
   if new sells refill the active queue. The UI **Interesting** sort is only an
   attention order; the gate still requires the **full frozen cohort**, not the
   Interesting-first subset alone.
4. Alternate calendar: `on_or_after` **2026-12-01**.

Human task: `adhoc-cue-consumer-mft-start-gate` (freeze/complete already cleared
as of 2026-10-28; keep as reference if a future cohort is proposed).

## Thin emit + anti-noise stubs

| Interface | Behaviour now | Remainder |
|-----------|---------------|-----------|
| Soft readiness | ≥3 closes + proposal hygiene | — (L629 scaffolding shipped) |
| Novelty gate | fingerprint reject/merge/spawn stub | **N226** full distance |
| Per-root cap | ≤3 active; cull/replace policy stub | **N227** |
| Cull / archive | declared criteria stub; cull≠live promote | **N227** / **L631** |
| Spawn sealed child | scaffold proposal only | **N223** / **L630** |
| Rule-aware decide + misfit trail | **shipped** deterministic N228 fill on trail | optional remote LLM voice later (still observe-only) |
| Chart draw tools | shipped (N229 v0) | post-sale dual-horizon + entry_blind PIT; attach with Comment; fail-closed if unread |
| Episode walker / lab paper fills | **shipped** (`mft-episode-walker-v0`) when eligible | paper-auto track wiring later |
| Dashboard strip | **shipped** (observe-utilization `cue_consumer_mft` card — open/closed + MoM) | — |
| Parallel timing lenses (L652) | **shipped** thin observe on shared lab candidates | concurrence / outcome gaps; never Package L |

## Automation

- **Trigger:** daily ops-monitor `check_cue_consumer_mft`
- **Stores:**
  - `docs/data/cue_consumer_mft_observe.json`
  - `docs/data/cue_consumer_mft_registration.json`
  - `docs/data/cue_consumer_mft_start_gate.json`
- **Sibling:** L652 `docs/data/parallel_timing_lenses.json` (see [parallel-timing-lenses.md](parallel-timing-lenses.md))
- **Lab learning progress strip:** weekly Observe utilization card joining MFT +
  L652 companions (`check_lab_learning_progress`; fair-cost primary;
  `influences_live=false`)
- **Findings** (`auto_fixable=False`):
  - **Cue-consumer MFT lab refreshed**
  - **Cue-consumer MFT lab armed (observe)**
  - **Cue-consumer MFT Q8B cohort freeze proposed — owner confirm**
  - **Cue-consumer MFT start gate eligible (evolutionary shadows)** (when Q8B/calendar clears)
  - **Cue-consumer MFT episode walker (lab paper fills)** (when walker active)
  - **Cue-consumer MFT lab failed**
- **CLI:** `ftse-cue-consumer-mft` (`refresh` | `propose-cohort` | `freeze-cohort`)

## Related

- [post-sale-review-queue.md](post-sale-review-queue.md) — Package M autopsy intake
- [fair-cost-primacy.md](fair-cost-primacy.md) — fixed-stake v0
- [ops-monitor.md](ops-monitor.md#full-automation-wiring) — wiring bar
- [llm-live-path-evidence.md](llm-live-path-evidence.md) — no silent LLM live influence
- [llm-agree-veto-shadow.md](llm-agree-veto-shadow.md) — propose → agree/veto pattern
- [n210-ai-judgment-observe.md](n210-ai-judgment-observe.md) — prior fixed-stake walker pattern
