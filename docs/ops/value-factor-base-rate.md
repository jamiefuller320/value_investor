# Value-factor base rate and gap-closure plan

Observe-only summary of the published value premium, plus the order for
closing the gaps found against the autonomous multi-market value objective.

Store: `docs/data/value_factor_base_rate.json`.
Builder: `value_investor.value_factor_base_rate.build_value_factor_base_rate`
on a local cache of Ken French zips. The raw files are copyright Eugene F.
Fama and Kenneth R. French and are not committed. Source:
[Ken French Data Library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html),
data cut **202608**.

This does not change signals, books, knobs, or the live screen.

## The belief under test

Does this repository's screen beat a published value factor on a long history
that includes dividends and dead companies?

Two different measurements got collapsed into that sentence.

| Question | What can answer it | This run |
|----------|--------------------|----------|
| What premium does a published value portfolio earn, with dividends and (in the US) delistings? | French portfolios below | Answered |
| Does `assign_signal` / `composite_value` beat that portfolio? | A point-in-time replay of our models on the same names | Not run. French did not score our pass count, sector ranks, or quality veto |

## Result (arithmetic percent per year)

Returns are monthly percent, annualised as 12 × mean. `t` is the t-statistic
of that mean. Geometric figures are in the JSON.

### United Kingdom, local currency, value-weight, 1975-01 to 2025-12

MSCI to 2006, Bloomberg after. High minus the country market. This is the
long-only hurdle for a UK value book. It is weaker on dead companies than the
US CRSP sorts.

| Sort | Full sample | t | 2007–2020 | Last 10 years |
|------|-------------|---|-----------|---------------|
| Book-to-market | +1.52 | 1.25 | −1.98 | +3.39 |
| Earnings / price | +2.72 | 2.55 | +0.20 | +3.13 |
| Cash earnings / price | +3.24 | 2.73 | +0.38 | +3.75 |
| Dividend yield | +1.52 | 1.26 | +0.61 | +2.52 |

Earnings and cash-earnings sorts clear a conventional t ≈ 2 bar over fifty
years. Book-to-market and dividend yield do not. None of the 2007–2020 rows
do. The last ten years are positive and still short of that bar.

Large European value (big high book-to-market minus the European market,
1990-07 to 2026-08) is +1.64 (t = 1.45). European HML, which is long value
and short growth, is +4.24 (t = 2.83). Rebuilding HML from the six size and
book-to-market portfolios matches the published factor to the reported
precision, which is the parser check.

### United States, CRSP, delistings included

| Series | Full sample | t | Last 10 years |
|--------|-------------|---|---------------|
| HML (long value, short growth) | +4.22 since 1926-07 | 3.43 | −0.13 |
| Hi-30 book-to-market minus market, value-weight | +3.75 | 3.33 | +1.92 |
| Same, dividends excluded | −0.19 | −0.17 | −0.43 |
| Four-leg blend minus market, value-weight | +2.53 since 1951-07 | 3.23 | −0.79 |
| Four-leg blend minus market, equal-weight | +5.01 | 4.42 | −0.37 |

The four-leg blend is the monthly average of the high-30 book-to-market,
earnings/price, cashflow/price, and dividend-yield portfolios. That is the
closest published analogue of `composite_value`'s cheapness weights. It is
not our screen: French includes financials and utilities, uses value or
equal weights inside the leg, and does not apply a pass count or a quality veto.

The value-weight US book-to-market premium over the market is the dividend.
Drop dividends and the premium is about zero across a century. Equal-weight
cheapness earned more over the full sample, because it mixes in smaller names,
and has not shown that edge in the last ten years.

## What this says about the live books

A long-only UK value hurdle that is actually detectable in this history is
about **3%/year** from the earnings and cash-earnings sorts, and it is mostly
a total-return result. `buy_tier_level` and `ai_judgment_fair` are a few
months of concentrated holdings, scored on price against the FTSE 100 price
index. They cannot confirm or reject this premium. A bad year against `^FTSE`
is not evidence against the 1975–2025 UK earnings sort, and a good year is
not evidence for our screen.

HML is the wrong bar for these books. It shorts growth. The bar is the
long-only high portfolio minus the market.

## Gap-closure plan

Do these in order. Each step has one instrument. Later steps wait on the
exit of the earlier one.

### 1. Score the books on the return that contains the premium

**Closes:** L528, L538.

The US result says a price-only value-weight book-to-market premium is about
zero. Decision review still proposes knobs from price excess versus `^FTSE`,
and it marks open holdings at average cost. The total-return view already
computes dividends and `FTAL.L`. Make that the proposal metric on a **new
epoch**. Leave published history as it is.

**Exit:** a knob proposal cites total-return excess versus the All-Share
total-return proxy. The price-only figure stays context. No live-signal edit.

Shipped: `proposal_basis.json` plus `metrics.proposal` on FTSE decision reviews.
See [`decision-review.md`](decision-review.md#proposal-basis-total-return-vs-all-share).

### 2. Report the French hurdle beside the books

**Closes the measurement half of L532 and L537.** Does not close "our screen
beats value."

Keep `buy_tier_level` as the selection control (did the filter help?). Add
the UK high earnings/price and high cash-earnings/price premia from this
store as the **hurdle**, labelled as a published base rate, not as a holding
and not as a new paper book.

**Exit:** the assessment scoreboard shows the primary book's total-return
excess next to those two UK premia. Refresh this JSON when the French cut
is more than 18 months old (`check_value_factor_base_rate`).

Shipped: `value_hurdle` on the assessment scoreboard. See
[`assessment-scoreboard.md`](assessment-scoreboard.md).

### 3. Test only the part French did not already run

**Closes the observe half of L561. Leaves L536 and L542 as the residual.**

French already sorted on book-to-market, earnings, cash earnings, and
dividends, and the US sorts include delisted names and financials. Rebuilding
that panel from EDGAR companyfacts would repeat it without delisting returns.

The residual is ours: sector-relative ranks, the unweighted pass count, the
quality and risk vetoes, and whether banks, insurers, and REITs belong in
the industrial ensemble. Next instrument: split the existing screen-premise
backtest into Financial Services, Real Estate, and the rest, on the frozen
FTSE snapshots. No new book.

**Exit:** that split is in `screen_premise_backtest.json`. Exclude financials
and REITs from the industrial models only if the split shows those ratios
moving the buy tier. A paid CRSP or Sharadar replay of `assign_signal` waits
until steps 1 and 2 are the adoption metric, and only to test that residual.

Shipped: `sector_splits` and `financials_real_estate_split`. The exclusion
flag is true only when those sectors are ≥15% of the 28-day buy tier and
move its spread by ≥1pp. Otherwise industrial models stay inclusive. On the
snapshots in this store they are about 2% of the buy tier and move the
28-day spread by less than 0.1pp, so the flag is false and the industrial
models are unchanged. See [`screen-premise-backtest.md`](screen-premise-backtest.md).

### 4. Leave the 28-day weight learner disconnected

**Holds N197.**

`update_model_weights` correlates model scores with the next 28-day price
return. The US ex-dividend result says that is the part of value with no
premium. `assign_signal` and `conviction_score` already ignore the weight.
Keep it that way until a multi-year total-return score survives a holdout.

Shipped as a lock: `LIVE_SIGNAL_IGNORES_MODEL_WEIGHTS_WHEN_COMPOSITE_PRESENT`.
`assign_signal` keeps the same verdict when `composite_score` is present and
the learned weight swings from 0 to 1. The learner still runs.

### 5. Do not open a binding AI-gate book for this question

**Holds N189.**

The research gate passes about 92% of the buy tier. The faster test is the
cross-sectional accumulate-versus-reject spread already on the screen-premise
backtest. It is still noise. It becomes interesting after the buy tier itself
is scored on total return against the hurdle in step 2.

Shipped: `register_twin` refuses `ai_judgment_binding_gate` and any twin that
sets `binding_ai_gate`. No such book is opened.

### 6. Teach the paper ledger terminal corporate events

**Closes L562, when the trigger hits.**

Marks are shares times the latest price. A split, a cash bid, or a delisting
has to become cash on the event date before a multi-year paper path is
evidence. Do this at the first holding that leaves the screened universe for
one of those reasons. Until then, a longer paper history is not stronger
evidence.

Shipped: `settle_fund_corporate_actions` on the daily paper pass. Explicit
feed only. A terminal event with no cash amount stays open and ops-monitor
warns. The equity curve is not rewritten. See
[`corporate-actions.md`](corporate-actions.md).

### 7. Net investor tax into yield before any non-UK judgement

**Closes L563.**

After step 1, and before a non-UK shard is judged on total return or any
stage-6 allocation, rank foreign yield after withholding and after the ISA
versus taxable dividend treatment. Gross yield is the wrong cheapness input
for this investor.

Shipped as observe columns on non-UK library screens
(`investor_net_yield_isa`, `investor_net_yield_taxable`). Live FTSE signals
still use gross yield. See [`investor-yield.md`](investor-yield.md).

### 8. Write the halt on the paper books before unattended capital

**Closes the design half of L564. N13 stays: no live broker.**

Define a paper-only halt on peak-to-trough drawdown, single-name weight,
sector weight, and currency concentration. The action is freeze new buys or
flatten to cash, then wait for a human. Hypothesis integrity can keep
tolerating underwater names inside that bound. Ship the halt as an observe
rule first. Live capital does not start without it.

Shipped observe-only: `docs/data/paper_halt.json`. Thresholds are 20%
drawdown, 40% of NAV in one name, 50% in one sector, and the currency rules
in [`paper-halt.md`](paper-halt.md). A breach warns. The book is not frozen.

## Refresh

```bash
# Cache the public zips locally, then:
python3 -c "from pathlib import Path; from value_investor.value_factor_base_rate import build_value_factor_base_rate, write_value_factor_base_rate; write_value_factor_base_rate(build_value_factor_base_rate(Path('PATH_TO_ZIPS')))"
```

Daily ops-monitor only checks that the committed summary exists and that the
US data cut is inside 18 months. `auto_fixable=False`.
