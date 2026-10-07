# Historical rule search (pre-registered, hrs-v1)

A pre-registered search over the rules applied **after** the frozen screen, plus
a replay of the trade plan's tactical slice, both run on the same licensed build
as the [historical screen replay](historical-screen-replay.md). Closes L573 and
L574. Observe-only: no book, signal, or knob reads it.

- Registration (frozen): `docs/data/historical_rule_search_registration.json`
- Results (config-level aggregates only): `docs/data/historical_rule_search.json`
- Code: `src/value_investor/rule_search.py` (`ftse-rule-search`),
  `src/value_investor/tactical_replay.py`
- Daily status: the `rule_search` block of `docs/data/historical_screen_replay.json`

## Learning question

On the frozen screen's output, which selection rule, core exit rule, and
tactical variant gives the highest probability of beating the cap-weighted
universe over 36 months? Does holding the core until a thesis break (the PR
#1021 core sell trigger) beat selling on leaving the selection, and does a
re-rating exit stop open-ended holding without giving that up? Does the
tactical slice add anything to the core once its idle cash and costs are
counted?

The objective is not maximum profit. It is the lower confidence bound of the
probability that the book is ahead of the market after a set holding period.

## What is searched

| Dimension | Values |
|-----------|--------|
| Tier | `buy_tier` (buy + strong_buy), `strong_buy` |
| Top N by conviction | all, 40, 20 |
| Core exit rule | `tier1`, `tier3`, `rerate50`, `rerate30`, `thesis` (see below) |
| Tactical limit | shallow 0.97, default 0.95, deep 0.92 × spot |
| Tactical stop | tight (0.99 support, 1.5 ATR), default (0.97, 2.0), wide (0.94, 3.0) |
| Tactical target | near (1.06 / 1.05 / R:R 1.0), default (1.10 / 1.08 / 1.5), far (1.15 / 1.12 / 2.0) |
| Tactical off | core only (the whole position is core) |

840 rule sets. The screen itself (thresholds, weights, models) is frozen and not
searched (N33). The frozen live rules are `buy_tier`, all names, `tier1`,
default tactical.

### Core exit rules

Ordered from quickest to most patient sell. The plateau steps along this order.

| Rule | Sells the core when |
|------|---------------------|
| `tier1` | 1 monthly screen outside the selection, or a single `avoid` (the live `buy_tier_level` rule; its 2 weekly confirm screens are closest to 1 monthly screen) |
| `tier3` | 3 screens outside the selection, or a single `avoid` |
| `rerate50` | `thesis`, or 2 consecutive screens outside the selection with the earnings yield below the median of the names screened that date |
| `rerate30` | The same with the 30th percentile: sells only once the name is clearly dear |
| `thesis` | 2 consecutive `avoid` screens (PR #1021). Leaving the selection is not a sell |

Every rule also sells a name that leaves the screened universe (left the S&P
500, or no fresh price): no later screen could confirm a sell, so holding it
would be open-ended. These are counted as `left_universe`.

`thesis` replays only the screen leg of the PR #1021 trigger. The research
verdict leg (`pass` / `sell` / `avoid` / `exit`) comes from the AI layer, which
cannot be replayed (N39), so the replayed rule sells less often than the live
one would. The `rerate` rules are the candidate fix for open-ended holding: a
value thesis ends when the name is no longer cheap, not only when it breaks.
Their thresholds are tuned by this search on the development window; the
holdout then tests the chosen one once.

## How a rule set is simulated

* **Core.** Monthly rebalance on the screen dates. Each held name gets an equal
  share, split core : slice by the trade plan's `core_allocation_pct` at entry
  (1 : 0 when tactical is off). The core is bought and sold at the month-end
  close.
* **Tactical slice.** Plans are rebuilt on the last trading day of each week with
  the live `assign_timing_signal` and `compute_trade_plan`, only while the latest
  monthly screen has the name in the buy tier. Indicator parity with the live
  one-year window is tested. While the core is held, the slice waits in cash for
  the active plan's limit, fills at min(open, limit), then exits at the stop
  (checked first; a gap fills at the open) or the target. After an exit it
  re-arms only on a newer plan, so **one holding can run several buy/sell
  cycles**. An open slice closes with the core, or at a delisting with the
  haircut.
* **Costs.** 0.53% per side (3% stress) on core turnover, on every slice fill
  and exit, and on monthly slice resizing while the slice is in position.
* **Benchmarks.** The screened universe on each date, cap-weighted (primary) and
  equal-weighted.

Simplifications are listed in the registration: idle slice cash earns zero, plans
are weekly rather than per screen run, and there is no fill on the core's exit
day.

## Metrics

Per rule set, on each window:

* `p` and `p_lower` at 12, 36, and 60 months: P(cumulative log excess over the
  cap-weighted universe > 0) = Φ(μ√H / σ), where σ is the Newey–West long-run
  standard deviation (lag 12). `p_lower` uses μ − z·σ/√T (z = 1.645 in the
  search, 1.96 at the holdout).
* The empirical overlapping hit rate (reported, not optimised), annualised
  return and excess, and the information ratio.
* Holding: median, 90th percentile, and longest holding in months, episodes
  still open at the window end, and sells by reason (`avoid`, `left_selection`,
  `thesis_break`, `rerated`, `left_universe`).
* Tactical: round trips, round trips per holding-year, win rate, exits by kind,
  and the **tactical increment** (combined minus core-only monthly return) with
  its interval.

Across the grid: the probability of backtest overfitting (CSCV, 16 blocks) and
the deflated Sharpe ratio of the chosen rule set.

## Selection and reveal order

1. `ftse-rule-search search` scores every rule set on the development window
   (2000-01 to 2012-12). It picks the highest **plateau** score (median of the
   rule set and its one-step neighbours). Ties go to core only, then to the
   fewest departures from the frozen rules.
2. Commit `docs/data/historical_rule_search.json` with the selection **before
   any holdout reveal**. `ftse-historical-replay run --reveal-holdout` refuses
   until the selection is committed beside its store.
3. Reveal hsr-v1, then `ftse-rule-search reveal`. The reveal covers frozen and
   chosen rules, each with and without the tactical slice, at base and stress
   costs. Only the first reveal is evidence.

## Decisions (agreed before the run)

| Holdout result | Action |
|---|---|
| Chosen passes and beats frozen | Propose a cold-start paper twin with a frozen epoch (L572 path); no live book changes on backtest evidence alone |
| Frozen passes, chosen does not | Keep the live rules; the search found noise |
| Chosen uses a `rerate` or `thesis` exit and passes | Propose that exit for the core sell trigger (`core_sell_trigger.py`) through a cold-start twin; the replayed thresholds are starting values, not a live edit |
| Tactical increment costs or is inconclusive | Keep tactical levels as alerts only; do not build a cycling slice into paper books |
| Neither passes | Follow the hsr-v1 decision |

Pass bar: holdout 36-month `p_lower` ≥ 0.5 at base cost. A high PBO (above 0.5)
or a low deflated Sharpe means the development ranking should not be trusted
even if the holdout passes.

## Running it (inside the Phase 2 month)

```bash
ftse-historical-replay build-panel --sharadar-dir ~/sharadar --out ~/hsr-build
ftse-historical-replay run --panel ~/hsr-build/panel.csv.gz \
  --prices ~/hsr-build/prices.csv.gz --terminal ~/hsr-build/terminal_baseline.csv
ftse-rule-search search --build ~/hsr-build
git add docs/data/historical_rule_search.json && git commit -m "Record the hrs-v1 search selection"
ftse-historical-replay run … --reveal-holdout
ftse-rule-search reveal --build ~/hsr-build
```

The first `run` screens every date once (about 25 minutes for 309 dates) and
caches the signals beside the panel (`signals_cache.csv.gz`), keyed by the
screen fingerprint and the panel. The search and reveals reuse the cache, so
they cost minutes rather than another screening pass. `build-panel` also writes
`daily.csv.gz` (adjusted daily OHLC) for the tactical replay.

Licence: the build directory must sit outside the repository (both tools
refuse otherwise). The cache, daily prices, and per-name trades never leave it.
The committed store holds config-level aggregates only. Delete the build within
30 days of cancelling.

If the screen or rule code changes before the run, run `ftse-rule-search
register` (refused after a reveal). `ftse-rule-search status` prints the
fingerprints, selection, and reveals.

## Ops-monitor findings

Raised by `check_historical_screen_replay` from the `rule_search` block.

| Title | Severity | Meaning |
|-------|----------|---------|
| Historical rule search registration predates rule code | info | Screen, trade-plan, or search code changed while the holdout is sealed; run `ftse-rule-search register` |
| Historical rule search verdict no longer describes the live rules | warn | Code changed after the reveal |
| Historical rule search holdout revealed more than once | warn | Only the first reveal is evidence |

All `auto_fixable=False`.
