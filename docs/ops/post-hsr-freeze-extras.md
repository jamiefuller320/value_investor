# Post-hsr freeze-extras policy

Observe-only ops note for the directional shift parked in **PR #1035**
(deferred **L583** / **L584** / **L585**, candidates **N200** / **N201**).

Does **not** change live signals, paper books, knobs, or decision-review
`--apply`. P1 live-path utilization and P2 offline ingest cascade stay the
spend priorities.

- Policy store: `docs/data/post_hsr_policy.json`
- Code: `src/value_investor/post_hsr_policy.py`
- Daily check: `check_post_hsr_policy` in ops-monitor

## Why this exists

The US holdout suite (hsr-v1, hsr-mid-v1, hrs-v1, hms-v1) asked whether our
screen extras beat textbook plain value after costs. The pre-registered
decisions said: on an **inconclusive** primary, **freeze the machinery** (no
new extras); the AI layer and forward evidence must earn their keep
separately. See [historical-screen-replay.md](historical-screen-replay.md#decisions-agreed-before-the-run).

Committed verdicts (aggregates only):

| Instrument | Result |
|------------|--------|
| hsr-v1 primary (`buy_minus_plain_value_net`, 30d holdout) | `inconclusive` |
| hsr-mid-v1 primary | `inconclusive` |
| hrs-v1 chosen vs plain value | `inconclusive` (selection preferred `tac=off`) |
| hms-v1 | `no_gain_over_frozen_mix` |

That is a null on “richer composite extras,” not a null on value itself, and
not a mandate to throw away the live stack.

## Policy (in force)

1. **Freeze screen extras.** Do not add new models, vetoes, composite knobs,
   or isomorphic screen/overlay variants that only re-mix the same identity
   without a new sealed `registration_id` and a pinned learning question.
2. **Keep strand A.** The current overarching model (composite / buy-tier
   stack and its experiment grid) stays. The holdout did not authorize a
   silent rewrite of the live book.
3. **Add orthogonal strands, not near-copies.** New strategy work enters as
   peer strands on the shared data engine (filings, fundamentals, panels),
   each with its own sealed learning loop.
4. **Share timing experiments.** Entry/exit and cost probes can be factorial
   across strands once registered; identity freezes stay per-strand.
5. **Prune near-duplicates.** Prefer deleting or parking isomorphic
   screen/overlay/paper-track variants over growing another copy of strand A.

## Strand catalog

| Strand | Status | Role |
|--------|--------|------|
| **A — current stack** | Active | Live / paper experiment grid on the existing framework |
| **B — plain-value + technical timing** (N200) | Named, not registered | Identity = plain value (or buy-tier); technical timing for entry/exit as observe-only |
| **C — short-horizon value+momentum** (N201) | Named, not registered | Global breadth → small-weight ~3m holds; distinct from patient value book |

Registration (learning question + `registration_id`) is a later step. Do
**not** open paper tracks, sleeve forks, or AI-judgment shards for B/C until
those are pinned and P1/P2 capacity allows.

## What this is not

- Not a live capital-path change.
- Not a pause of P1 filing/FCF/overlay/memo utilization or P2 ingest cascade.
- Not permission to back-label prior NAV as evidence for B/C.
- Not a fourth equal sprint stream.

## Ops-monitor

`check_post_hsr_policy` refreshes `docs/data/post_hsr_policy.json` and emits:

| Finding | Severity | When |
|---------|----------|------|
| **Post-hsr freeze-extras policy in force** | info | `freeze_extras` true (normal after inconclusive holdouts) |
| **Post-hsr freeze-extras not declared after inconclusive holdout** | warn | Holdouts inconclusive but store says freeze off |
| **Post-hsr freeze-extras ops note missing** | warn | Freeze on but this runbook file is gone |
| **Post-hsr candidate strands not listed** | warn | Freeze on but `candidate_strands` empty |

All findings are `auto_fixable=False` (observe / warn-only).

## Next engineering steps (parked until ready)

1. Pin one learning question and `registration_id` for strand B **or** C
   (not both at once) — revisit **N200** / **N201**.
2. Cap concurrent live/paper sleeves when the first alternate registers
   (**L583**).
3. Only then share timing experiments across strands (**L584**).

Until then, spend stays on P1/P2.
