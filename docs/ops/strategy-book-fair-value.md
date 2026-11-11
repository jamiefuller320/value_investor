# Strategy book fair-value range

Observe-only range for plan step 4.1. It asks whether, at the strategy book's
signal session, a larger margin of safety against a point-in-time fair-value
range goes with better episode outcomes, and whether a mis-timed entry's
prices reach that range during the hold.

It does not change the book. `influences_live` is false. It does not edit
memos, research prompts, the walker, the registration, or
`docs/data/strategy_book_observe.json`. Memo text still says not to give
buy or sell price targets. This pass does not call a model and does not
spend on an API.

The store is `docs/data/strategy_book_fair_value.json`. The forward workflow
refreshes it after the walk. Ops-monitor reads the file and does not
recompute it.

## What it computes

For every episode in the forward observe store (the primary column is listed
first; comparison columns are kept and are not pooled into the primary
score):

1. A fair-value **range** in the chart's price units: low, mid and high.
2. A **margin of safety** of `1 - entry_reference_price / mid`.
3. The entry reference is the **signal-session close** (`signal_session_close`).
   A positive margin means that close is below the mid. A negative margin
   means it is above the mid.

The v0 method is **normalised earnings**: the arithmetic mean of up to five
annual diluted EPS figures (basic EPS if diluted does not have enough years),
times a fixed multiple band. Free-cash-flow per share (free cash flow divided
by diluted average shares, for the same years) is used only when the EPS
average is missing or not positive and the cash-flow average is positive.
When both exist, the range is the earnings range and the cash-flow range is
a cross-check.

A **reverse DCF** cross-check, when the latest year is positive, values that
latest per-share figure as a no-growth perpetuity. It is not the range. It
is `inside_band` when its mid sits between the range low and high, and
`outside_band` otherwise. There is no growth estimate and no screen trailing
P/E: the cited screen history does not carry one.

This is not the DCF screen model (N5). Nothing here changes a signal.

## v0 constants

These were set before any episode outcome was read. Do not retune them on
returns. They are copied into the store under `constants`.

| Constant | Value |
|---|---|
| Years | 3 to 5 annual figures, newest kept |
| Multiples | 10 / 15 / 20 (low / mid / high) |
| Reverse DCF growth | 0 |
| Reverse DCF discounts | 10% / 8% / 6% (low value / mid / high value) |
| Bucket minimum | 12 mature or closed episodes with a range |
| Margin buckets | below 0; 0 to 0.33 inclusive; above 0.33 |
| London scale | 100 pence per pound |

## Point-in-time rule

Only figures dated on or before the signal session are used.

- Fiscal years after the signal year are dropped. That is the same year rule
  as the operating-decline gate (`year > signal year` is out).
- `financials_annual.json` is used only when `fetched_at` is on or before the
  signal session. A later `fetched_at` is replaced by the last git blob of
  that file on or before the session, when one exists.
- Statement currency comes from an explicit source: `fcf.currency` on the
  screening snapshot (the snapshot's git commit must be on or before the
  session, because the snapshot has no `fetched_at`), or a SEC company-facts
  row whose `first_filed` and file `fetched_at` are on or before the session,
  or the filing-currency symbol in the screen action note of the history run
  the episode already cites. If those sources disagree, or none of them
  states a currency, the episode is `insufficient_data`. The pass does not
  assume a currency from the ticker suffix.
- The entry price is the chart close dated on the signal session. Later bars
  are not the entry.
- Recovery uses chart closes after the signal session and up to the exit
  session, inclusive. Closes after the exit are ignored.
- FX is the committed macro history already used by the proof board (latest
  marker on or before the session). Live spots are not fetched.

A missing or non-positive input is `insufficient_data` with a cited reason.
The pass does not fill a gap with a guessed value.

## Units

London charts (`*.L`) are in pence (GBX), including when the chart's
currency field says GBP. Statement EPS and free cash flow are in major
currency units (pounds, dollars, euros). A pound figure is multiplied by 100
after any FX conversion into pounds. A US listing quoted in dollars is left
in dollars. A dollar EPS on a London name is converted to pounds with the
macro GBPUSD rate, then into pence.

## Scoring

Primary episodes that have a range and are mature or closed are split into
the three margin buckets. Each bucket reports `n`, the median fair-cost
return and the median matched excess once it has at least 12 episodes.
Below that, the bucket verdict is `insufficient_data` and the medians are
left blank. The primary scoring verdict is `scored` only when every bucket
has reached 12. Comparison columns are scored on their own and are not added
into the primary buckets, because they are the same entry under a different
exit.

For a closed episode with a range, the recovery label is:

- `reached_mid` — a close in the holding window was at or above the mid
  (that also counts as reaching the low)
- `reached_low_only` — a close reached the low and not the mid
- `not_reached` — neither
- `no_closes_in_window` — the episode is closed but the chart has no close
  strictly after the signal and on or before the exit
- `not_closed` — the episode is still open, which is not a miss

The recovery verdict is `insufficient_data` until 12 closed primary episodes
have a range. The forward book is young, so that is the expected verdict.

## What it never does

- It never edits a memo, a prompt, a verdict, a knob, or a book.
- It never places an order or reads a Trading 212 key.
- It never treats the range as an exit, a recovery target that the walker
  acts on, or a screen.
- It never calls a model.

Using the range as a live exit is a version-review question. It is queued,
not built.

## Where it runs

`strategy-book-forward.yml` runs `ftse-strategy-book-fair-value` after the
forward walk, with `continue-on-error: true`. Email-report does not commit
the store. A dry run passes `--no-write`.

```bash
ftse-strategy-book-fair-value --repo-root .
ftse-strategy-book-fair-value --repo-root . --no-write
```

Ops-monitor `check_strategy_book_fair_value` is info when the store is
readable and `generated_at` is within 5 days. It warns when the file is
missing, unreadable, or older than 5 days. `auto_fixable` is false. The info
line reports how many primary episodes have a range, how many are
`insufficient_data`, and the primary median margin.
