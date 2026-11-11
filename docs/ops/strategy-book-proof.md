# Strategy book proof board

Observe-only score of the seven bars in plan step 3.2. The owner signed the
numbers on 2026-11-05. They are fixed in the plan section **Step 3.2 proof
numbers** and copied in `docs/data/strategy_book_registration.json` under
`step_3_2_proof_numbers`. This board reads that copy. It does not edit it.

A **proof board** is this score. A **bar** is one of the seven requirements.
**Matched excess** is the episode's price return minus the equal-weight
buy-tier basket over the same holding. A **counted mature episode** is a
primary episode that has been open for the book's maturity window.
`provenance_missing` episodes are left out, as the signed section says. The
thickness gate (48 counted episodes, at most 6 per entry week) is a different
test and is not applied here.

`influences_live` is false. The board does not change the forward observe
store, any sealed board, the thickness gate, or the registration.

## What meeting the bars means

Meeting every bar lets the owner **consider** plan step 5.5 (small live
capital). It does not open live capital by itself. The store says the same
thing in `owner_note`, and `opens_live_capital` is false. `all_bars_met` is
true only when all seven forward bars pass and the sealed section still
matches the registration.

The archive block in the same file is labelled `archive_replay_report_only`.
It is the buy-tier-only arm of the archive replay (plan step 2.2). That replay
is survivorship-biased. It is not the proof, and a pass there does not set
`all_bars_met`.

## The seven bars

Read on the forward book's counted mature primary episodes:

| Bar | Passes when |
|---|---|
| Uncertainty | The 90% interval of the median matched excess, from 10,000 resamples of whole ISO entry weeks, lies wholly above zero |
| Tail loss | The 5th-percentile fair-cost episode return is at or above −20% |
| Drawdown | The sterling reference slot book's largest peak-to-trough fall is at most 1.5 times the matched buy-tier basket's fall, in sterling, over the same dates |
| Market spread | Median matched excess stays above zero after the market with the most counted episodes is removed |
| Regime spread | Median matched excess is at or above zero both above and below the 200-session average, with at least 12 counted episodes in each half |
| Sterling slot book | The 20-slot reference book, in sterling after fair costs and FX, has a positive total return and beats the matched basket over the same dates |
| Tradable subset | Median matched excess on `t212_listed` episodes is above zero |

Each bar is `pass`, `fail`, or `insufficient_data`, with `n`, the statistic,
the threshold, and reasons. `regime_unknown` episodes sit out of the regime
bar. They are not a failure by themselves. Episodes that are not
`t212_listed` sit out of the tradable bar.

The fair-cost episode return used for the tail is `decision_return_floor`
(the same field the observe board calls median fair-cost). The slot book
still reads `fair_cost_return`, which is what the existing reference book uses.

## Uncertainty

Entries in the same ISO week are not independent. The board resamples **whole
entry weeks**: each of the 10,000 draws picks as many weeks as the counted
set has, with replacement, and keeps every matched excess in a drawn week. A
week drawn twice is included twice. The generator is Python's `random.Random`
with seed `20261105` (the day the bars were signed). The seal does not name a
seed. The 90% interval is the linear 5th and 95th percentiles of those 10,000
medians (rank `(pct/100) × (n − 1)`). The bar passes only when the lower end
is above zero.

## Sterling, FX, and the same dates

The **reference slot book** is the 20-slot cash book already implemented as
`_slot_book` in `strategy_book_observe.py` (seed `20261104`, order by fill
date then ticker). The 15 random orderings that function also computes are
not part of these bars.

**Same dates** means both legs use that function on the same counted
episodes and the same fill and exit sessions. Net asset value is marked on
the union of those dates. The slot leg earns each episode's fair-cost return
after it has been turned into sterling. The basket leg earns that episode's
`basket_gross` (the equal-weight buy-tier price return from fill to exit)
turned into sterling with the same two rates. Total return is end net asset
value minus 1, from a start of 1.0 in cash. The peak-to-trough fall is the
size of `max_drawdown` (nav divided by its peak, minus 1, on those event
dates). An open position is marked at its full holding return from the fill,
which is how `_slot_book` already works.

A whole-screen fallback basket (`basket.fallback`) is not the buy-tier basket
the bar names. Those two bars are then `insufficient_data`.

Sterling for a local return is `(1 + local return) × (sterling per unit on
the exit date ÷ sterling per unit on the fill date) − 1`. An open episode
uses the store's scoring date as the exit date. GBP needs no rate (a pence
quote is the same currency once the figure is a return).

### Where the rates come from

Daily FX history in this repo is the dated macro snapshots
`docs/data/library/macro/YYYY-MM-DD.json`. Each file holds the latest close
the fetch saw that day:

| Currency | Marker | Meaning |
|---|---|---|
| GBP | `uk.gbp_usd` | US dollars per 1 pound |
| EUR | `euro.eur_usd` | US dollars per 1 euro |
| AUD | `au.aud_usd` | US dollars per 1 Australian dollar |
| CAD | `ca.cad_usd` | US dollars per 1 Canadian dollar |

USD uses 1. Sterling per unit is the currency's dollars-per-unit divided by
the pound's dollars-per-unit.

The rate's date is the marker's `as_of` day, not the file name and not a live
quote. For a past date the board uses the latest `as_of` on or before that
date, separately for the currency and for the pound. A later snapshot is never
used for an earlier day. `fx.fetch_fx_rates` (today's Yahoo spot) is not
called.

CHF, SEK, HKD and SGD have no daily series in those snapshots. If a counted
episode is in one of those currencies, the drawdown and sterling bars are
`insufficient_data` and the reason names the gap. No rate is invented.

## Schedule and store

`strategy-book-forward.yml` runs `ftse-strategy-book-proof` after the forward
walk. That step is `continue-on-error`, so a proof failure cannot block the
forward commit. The job writes `docs/data/strategy_book_proof_board.json` and
commits it. Email-report excludes that file so it has one writer.

```bash
ftse-strategy-book-proof --repo-root .
ftse-strategy-book-proof --repo-root . --no-write
```

## Ops-monitor

`check_strategy_book_proof` reads the store. It does not rescore.

| Title | Severity | When |
|---|---|---|
| Strategy book proof board | info | The file is readable and `generated_at` is within 5 days. The summary names how many of the seven bars pass and the counted episode count. A failing bar stays info. |
| Strategy book proof board missing | warn | The file is not there. |
| Strategy book proof board unreadable | warn | The file is not a proof board. |
| Strategy book proof board stale | warn | `generated_at` is missing or older than 5 days. |

All four are `auto_fixable: false`. Nothing is re-memoed or ingested from this finding.

## Owner sign-off

Human task `adhoc-strategy-book-proof-signoff`. Read the forward block of
`docs/data/strategy_book_proof_board.json`. Sign, or say what still fails.
Signing does not open live capital. Step 5.5 stays a separate owner decision.
N13 (live broker automation) and N14 (live Trading 212) revisit when
`forward.all_bars_met` is true. That flag only means the owner may consider
step 5.5.

Plan status: built, awaiting this sign-off. Step 3.2 is not done.
