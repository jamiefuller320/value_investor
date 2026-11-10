# Strategy book bench-fill review (2026-11-10)

**Status: SIGNED 2026-11-10 — `trend_not_falling` sealed into the fourth bench slot.** The bench is now full.  
**Book:** `owner-strategy-book-v0` ([registration](strategy-book-registration.md))  
**Review id:** `bench-fill-2026-11-10`  
**Seal record:** `bench_seals` in [`docs/data/strategy_book_registration.json`](../data/strategy_book_registration.json)  
**Deferred idea:** L689 (falling-trend entry filter), closed by this seal

## What this review is

A bench-fill review under plan item 4 ([single track](strategy-reorientation-plan.md#single-track-to-live-owner-2026-11-04)): it seals one challenger into a free slot and promotes nothing. It is not the thickness-gate review. The primary entry, exit, gates, thresholds, the three initial challengers and the bench rules (four slots, 2.5 standard errors, both halves, one promotion per review) are unchanged.

New bench challengers are sealed only at a version review and before any of their scores are read ([registration section 8](strategy-book-registration.md#8-scoring)). The forward book dry-runs (`forward_live: false`) and `strategy_book_observe.json` does not exist yet, so the challenger scores on every forward entry from the first.

## The sealed rule

The text below is hashed into the seal (`rule_sha256`):

> trend_not_falling is a filter challenger. It keeps a primary entry when the entry's 6-month channel direction (ch126_direction, channel_v0, computed at the signal session from closes on or before that session) is rising or sideways. An entry whose direction is falling, or that has no 6-month channel, is not kept. It opens no episode and is scored under the section 8 bench rules: 48 counted mature episodes, a mean difference above 2.5 standard errors, the same sign in both halves, and a capital-days return not below the primary's.

`ch126_direction` is the frozen channel column from section 8: `rising` or `falling` when a 126-session log-price regression fits with enough strength, `sideways` otherwise. Code: `strategy_book_rules.REVIEW_BENCH` and `strategy_book_observe._bench_flags`.

## Why this candidate

The US rehearsal recorded the channel columns on every entry (descriptive, not a registered test there):

| Window | 6-month direction | Mature entries | Fair-cost median | Matched-excess median |
|---|---|---|---|---|
| Development 2000–2012 | falling | 733 (19%) | 1.1% | +0.10% |
| | rising | 1,857 | 2.1% | −0.28% |
| | sideways | 1,212 | 2.2% | +0.05% |
| Confirmation 2013–2025 | falling | 691 (17%) | 0.9% | −0.33% |
| | rising | 2,030 | 2.0% | −0.26% |
| | sideways | 1,389 | 1.6% | +0.18% |

- **The fair-cost gap repeated.** Falling-channel entries earned about 1 point less at the median in both windows.
- **Matched excess did not repeat.** Against the same-dates basket, falling entries were the best group in development and the worst in confirmation. Part of the fair-cost gap may therefore be market timing rather than the name. The forward bar includes capital-days return, not matched excess, so the review reads matched excess beside the bar.
- **It fits the strategy.** Part 4 buys names at short-term lows. This filter asks whether a dip inside a 6-month downtrend is a worse entry than a dip inside a flat or rising one.

## What to expect

The filter drops about 18% of entries. With a gap of about 1 point on those, the kept entries' mean moves only about 0.2 points above the whole book's, which is small against the bench bar. A clear answer is unlikely before the thickness-gate review and may take more than a year of forward marks. A null result is also an answer: it says the falling-trend split is not worth a rule.

## After the seal

- The forward walker records `trend_not_falling` on every primary entry, and the bench board scores it beside the other three.
- Ops-monitor reports "Strategy book bench challenger cleared its promotion bar" if it clears the bar, and the owner may then call a version review.
- If it is promoted at a later review, it becomes the entry filter of a **new** `registration_id`. This id's scores stay as they are.
