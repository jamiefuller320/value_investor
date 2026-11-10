# Strategy book bench-seal review (proposed)

**Status: CLOSED 2026-11-10 — nothing sealed.** The exit lab ran on 2026-11-09 and no variant met the choice rule ([outcome](#outcome-2026-11-09)). The fourth bench slot was left free; it was filled on 2026-11-10 by the filter challenger `trend_not_falling` ([bench-fill review](strategy-book-bench-fill-review.md)).  
**Book:** `owner-strategy-book-v0` ([registration](strategy-book-registration.md))  
**Deferred idea:** N259 (exit challenger scored on capital-days return, trend-led exits, no fixed time cap)  
**Lab:** `ftse-strategy-book-rehearsal exit-lab` ([runbook](strategy-book-us-rehearsal-runbook.md#6b-exit-lab-exploratory-before-deletion))  
**Human checklist:** `adhoc-strategy-bench-seal-review` (removed 2026-11-10 when the review closed)

## What this review is

A version review limited to one act: sealing **one exit challenger** into the bench's free fourth slot before the forward book has any score.

The plan puts the first version review at the thickness gate ([plan, single track](strategy-reorientation-plan.md#single-track-to-live-owner-2026-11-04), item 4), and new bench challengers are sealed only at a review ([registration section 8](strategy-book-registration.md#8-scoring)). This review is an owner exception to that timing, for the empty bench slot only. The first full version review stays at the thickness gate.

## Why now

- **The exit is the weak part.** In the US rehearsal (descriptive, not tests), the 63-session fail-to-launch deadline cost the primary in both windows (L687). Recovery-labelled trades rarely recovered and held about a third of capital-days (L688). The leave-tier control, which holds while the name stays cheap, made about 17pp more per episode, though that figure is not capital-adjusted.
- **A challenger needs time to score.** The bench bar is 48 counted mature episodes, the same sign in both halves of the forward period, and capital-days return no lower than the primary's. A challenger sealed at the thickness-gate review starts scoring then, so it cannot reach that bar until a later review. Sealed now, it scores on every forward entry from the first.
- **No forward score exists.** The forward book dry-runs (`forward_live: false`) and `strategy_book_observe.json` holds no episodes, so "sealed before any of its scores are read" holds.
- **The owner's aim is turnover, not a holding period** (2026-11-07). Capital should get several attempts a year when trades work. A trade closes when its exit criteria are met and runs on while a strong uptrend shows no sign of breaking. Capital-days return rewards that through the score, so no variant has a time cap.

## What it may and may not do

| May | May not |
|---|---|
| Seal at most one exit challenger: a different exit on the primary's own entries, scored in pairs like the comparison exits | Promote anything, or change the primary entry, exit, gates, thresholds or learning question |
| Write the challenger's rule text and its hash into the seal before any of its scores exist | Change the three sealed filter challengers or the bench rules (four slots, 2.5 standard errors, both halves, one promotion per review) |
| Leave the slot empty if no lab variant meets the choice rule | Count as the thickness-gate review, or read any forward score |

## Candidate source: the exit lab

The lab walks the US rehearsal's **development** signal sessions only (2000–2012) and scores eight variants as paired columns on the primary's entries. The 2013–2025 window is spent, so the lab chooses; it is not evidence. Evidence comes only from forward marks.

Every variant keeps the section 5 thesis breaks and reviews (every 63 sessions, without the four-review cap) and has no time cap. A close at +10% launches a trade, as on the primary.

| Column | After launch | Before launch |
|---|---|---|
| `lab_ladder_newlow252` | The primary's checkpoint ladder | Sell on a close below the lowest close of the prior 252 sessions |
| `lab_trail15_deadline63` | Sell on a close 15% below the highest close since the fill | The primary's 63-session deadline |
| `lab_trail15_newlow252` | 15% below the peak | New 252-session low |
| `lab_trail25_newlow252` | 25% below the peak | New 252-session low |
| `lab_sma50_newlow252` | A close below the 50-session average | New 252-session low |
| `lab_low55_newlow252` | A close below the lowest close of the prior 55 sessions | New 252-session low |
| `lab_trail15_newlow252_b5` | 15% below the peak | More than 5% below the prior 252-session low |
| `lab_trail15_none` | 15% below the peak | No price rule; thesis breaks and reviews only |

The first two each change one part, so the lab can show which part matters.

### Choice rule (fixed before the lab runs)

1. A variant is **eligible** when, on development signals:
   - its paired mean return minus the primary's is above zero in both calendar halves of the window;
   - its capital-days return is above the primary's in both halves;
   - its median matched excess is not below the primary's on the whole window.
2. Among eligible variants, the one with the highest whole-window capital-days return is the **pick**.
3. If none is eligible, nothing is sealed. The slot stays free and N259 stays queued.

The owner may decline the pick. The owner may not seal a different variant. Turnover (median holding sessions, turns per slot-year) is reported beside each variant and is not a criterion; capital-days return already rewards it.

## After a signature

The next package wires the picked rule into the forward walker as a bench exit column (the lab's step function is the implementation), adds it to the bench board, and records the seal entry: the rule text, its hash, the lab store's `computed_at`, and the owner's note. The forward book's primary and its first 26 sealed weeks are unchanged.

## Timeline

| Step | When |
|---|---|
| Run the exit lab on the laptop | Before the licensed data is deleted (due 2026-12-07) |
| Read the lab table and apply the choice rule | After the lab store is pushed |
| Owner signs or declines | Before `forward_live` is set, so the challenger scores from the first forward entry |

If the Phase 1 gate review would set `forward_live` first, the owner can hold `forward_live` for the few days the seal takes, or seal later with a note that the challenger scores only from its seal date.

## Outcome (2026-11-09)

The lab ran on the owner's laptop on 2026-11-09 (`docs/data/strategy_book_exit_lab.json`, `computed_at` 2026-11-09T22:32Z). Its primary reproduced the committed development block: 3,802 mature episodes, the same fair-cost median.

**Choice rule: no eligible variant, so nothing is sealed.** Every variant's median matched excess was below the primary's (−0.11%). `lab_sma50_newlow252` also failed on first-half capital-days return.

What the lab showed (development signals 2000–2012; exploratory):

| Column | Capital-days return | 20-slot book a year (random-order median) | Max drawdown | Paired mean vs primary (t) | Median held sessions | Turns per slot-year |
|---|---|---|---|---|---|---|
| `primary` | 9.8% | 11.2% (11.8%) | −39% | — | 56 | 4.8 |
| `lab_ladder_newlow252` | 12.2% | 9.0% (9.6%) | −33% | +1.1pp (4.1) | 41 | 3.9 |
| `lab_trail15_deadline63` | 12.2% | 9.5% (10.0%) | −36% | +2.1pp (6.0) | 64 | 2.9 |
| `lab_trail15_newlow252` | 13.9% | 9.6% (10.1%) | −33% | +4.0pp (7.1) | 55 | 2.3 |
| `lab_trail25_newlow252` | 13.5% | 7.3% (8.4%) | −32% | +5.6pp (7.7) | 64 | 1.8 |
| `lab_sma50_newlow252` | 10.6% | 10.5% (10.4%) | −35% | +0.4pp (1.1) | 41 | 4.4 |
| `lab_low55_newlow252` | 11.9% | 9.6% (10.7%) | −37% | +1.9pp (5.0) | 56 | 3.1 |
| `lab_trail15_newlow252_b5` | 13.4% | 10.4% (11.3%) | −30% | +4.9pp (8.7) | 75 | 1.9 |
| `lab_trail15_none` | 13.0% | 10.9% (11.0%) | −29% | +4.9pp (8.6) | 80 | 1.9 |

- **Per trade, trend-led exits did better.** Every variant beat the primary's mean return on the same entries in both halves, and most had a higher capital-days return. The gain came from letting winners run: means rose while medians fell, and only 15–40% of entries did better than under the primary.
- **The 20-slot book did not improve.** No variant beat the primary's 20-slot book. Longer holds took 585–1,111 trades against the primary's 1,139, and every variant trailed on the random-order median. With 70% of signals already skipped for want of a slot, the fastest recycler kept the capacity-bound book ahead, even though each trade earned less.
- **Drawdowns were shallower.** Trailing variants had a 20-slot maximum drawdown of −29% to −33%, against the primary's −39%.

The primary's ladder already gives about 4.8 attempts per slot-year. What limits the book in this history is which signals it takes when all 20 slots are full, not how long each trade is held. That is queued for the version review (deferred store).
