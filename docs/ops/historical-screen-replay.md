# Historical screen replay (pre-registered)

Point-in-time replay of the frozen value screen on 25 years of US data.
Closes L536 and L542; supersedes L565. Observe-only: never changes signals,
books, or knobs.

- Registration (frozen): `docs/data/historical_screen_replay_registration.json`
- Mid-cap sibling (hsr-mid-v1): `docs/data/historical_screen_replay_midcap_registration.json`,
  results in `docs/data/historical_screen_replay_midcap.json`
- Status and results (aggregates only): `docs/data/historical_screen_replay.json`
- Code: `src/value_investor/historical_screen_replay.py` (`ftse-historical-replay`)

## Why

Forward paper evidence cannot resolve a 3%/year edge for decades
(`track_statistics.json` years-to-detect 125–900; the weekly screen-premise
backtest needs about 95 weeks at 7 days). The published value premium is
already measured ([value-factor-base-rate.md](value-factor-base-rate.md)).
What nobody has tested is our residual: sector-relative ranks, the pass count
across 20 models, and the quality and risk vetoes. This replay tests that
residual on history that already happened.

## Learning question

In a survivorship-free point-in-time US universe, does the frozen screen's buy
tier (buy + strong_buy) beat a plain top-30% earnings-yield sort of the same
names, on total return after costs on both?

This asks whether our machinery (sector-relative ranks, the pass count, the
quality and risk vetoes) adds anything over textbook value. It is the part of
the result this project controls.

It deliberately does not ask whether the screen beats the market. Both
windows sit in value regimes: value did well for much of 2000–2012 and poorly
for much of 2013–2025, when growth and large tech led. A buy tier that lags the
market in the holdout could be a good value screen in a bad decade for value.
Whether value beats the market over the long run is the published factor
question ([value-factor-base-rate.md](value-factor-base-rate.md)). The plain
sort carries the same value exposure as the buy tier, so their difference
mostly cancels the regime.

The spread over the equal-weight universe is still reported as context, split
by value regime: each cohort is `value_led` when the plain sort beat the
universe and `value_lagged` otherwise.

## Pre-registration (fixed before data is bought)

| Item | Registered value |
|------|------------------|
| Screen | Code fingerprint over `models/`, `scoring/__init__.py`, `model_families.py`, `model_weights.py`, `signals.py`, `sector_scoring.py`, `data_quality.py`, `signal_stability.py`, `library_screen.py`. Default model weights; the 28-day learner is not run (N197) |
| Universe | S&P 500 members on each date, active and delisted (Sharadar `sp500`) |
| Fundamentals | Sharadar `fundamentals`, dimension `ART` (as reported, trailing twelve months), latest row filed at least 2 days before the date. As-reported, so later restatements cannot leak. Filings over 456 days old and non-USD reporters are dropped and counted |
| Prices | `closeadj` (splits, dividends, spinoffs) for total return. Market cap is the filing-date `marketcap` rolled forward by the split-adjusted close |
| Metric units | Yahoo conventions, as the live screen receives them: dividend yield and debt/equity in percent; margins, returns, and growth as fractions. Growth is quarterly year-on-year (`ARQ`); `*_prev` fields come from the `ART` row a year earlier |
| Rebalance | Last trading day of each month |
| Development window | Entries 2000-01 to 2012-12 |
| Holdout window | Entries 2013-01 to 2025-09, sealed until revealed once |
| Horizons | 30, 91, 365 days; exit on the first trading day on or after the horizon |
| Primary metric | 30-day buy tier minus the plain earnings-yield sort, each net of costs on its own turnover (`buy_minus_plain_value_net`) |
| Context metric | 30-day buy tier minus the equal-weight universe, net of costs (`buy_tier_spread_net`), with the `value_regime` split. Does not decide the verdict |
| Pass bar | Holdout 90% interval on the primary wholly above zero, and the 365-day primary not wholly below zero |
| Costs | 0.175% per side (base: the fair GBP-funded US cost in `market_trading_costs`, FX plus half-spread) and 3% (stress), charged on each leg's measured turnover |
| Delistings | Exit at the last adjusted close; sensitivity −30% for non-merger delistings |
| Forbidden | Threshold, weight, or model search on any window (N33). Per-model rank IC is report-only |

The primary is the 30-day horizon because non-overlapping monthly cohorts give
about 150 independent observations per window. Overlapping 365-day cohorts
give about 13, which only resolves very large edges; they confirm that the
monthly edge does not reverse.

Any change to the registration or to the fingerprinted code after the holdout is
revealed opens a new `registration_id`, and its results are exploratory.

## Decisions (agreed before the run)

| Holdout primary | Meaning | Action |
|---|---|---|
| Beats the plain sort | Screen machinery adds to textbook value after costs | Keep it; multi-year total return becomes the fitness test N197 asks for |
| Inconclusive | No measurable gain over the plain sort | Freeze the machinery (no new extras); the AI layer and forward evidence must earn their keep separately |
| Loses to the plain sort | The extras cost money | Simplify toward the published sort before stage 4 |

**In force after reveal:** hsr-v1 and hsr-mid-v1 holdout primaries were
`inconclusive`, so the freeze-extras action applies. Ops note and strand
catalog: [post-hsr-freeze-extras.md](post-hsr-freeze-extras.md) (store
`docs/data/post_hsr_policy.json`; daily `check_post_hsr_policy`). Strand A
(current stack) stays; orthogonal peer strands are named but not registered.

The market spread and its `value_regime` split are read beside the verdict,
never instead of it. A negative market spread in `value_lagged` cohorts with a
positive primary is a value-regime result, not a screen failure.

### Reading the result

* `buy_minus_plain_value_net` decides. `buy_minus_plain_value` (gross) and the
  `_stress` variant show how much costs matter; the plain sort usually trades
  more than the buy tier.
* `value_regime.value_led` / `value_lagged` give the primary and the market
  spread in each regime. A screen that only beats the plain sort in one regime
  is a regime bet, not a better value method; read the two before acting.
* `development_confirmation_verdict` / `holdout_confirmation_verdict` are the
  365-day primary. `fail` there means the monthly edge reverses over a year.

## Reporting kept for after deletion

The licence requires deleting every raw and derived file within 30 days of
cancelling, so anything we may want later must be computed or kept inside the
month. Beyond the verdicts, each run commits:

- `development_series` (and `holdout_series` once revealed) at the primary
  horizon: one row per monthly cohort with the universe return, buy-tier,
  plain-sort and avoid spreads, rank IC, both turnovers, and per-model
  `[pass_spread, rank_ic]`. Cohort-level means only, never a per-name value.
  Enough for the factor regression (L580), the value ETF comparison (L581),
  and regime re-cuts without the licensed data.
- `per_model` per window and horizon: each model's passers' spread over the
  universe, its score rank IC, and its pass share. Report-only: it never tunes
  the screen (N33). The cache keeps every model's pass flag and score.
- The rule search keeps book-level monthly returns for the frozen and chosen
  rules ([historical-rule-search.md](historical-rule-search.md)).
- The model-mix search (hms-v1) tests which models to combine, as its own
  pre-registered experiment, and keeps per-candidate monthly ICs and book
  returns ([historical-model-mix.md](historical-model-mix.md)). The replay
  itself still never tunes the screen.

### Exploratory: dividend units (L571)

`--variant dividend_units_fixed` re-screens with dividend yield as a fraction,
which is what the L571 fix will do at load. It has its own signal cache, opens
the holdout only after the baseline reveal, is marked `exploratory`, and is
never evidence. It shows whether the fix changes the result before the fix is
made live as a new epoch.

## Mid-cap sibling (hsr-mid-v1)

The live FTSE 350 is two thirds FTSE 250 mid caps; the S&P 500 is large caps
only, and value and quality screens behave differently by size. hsr-mid-v1
runs the same screen, windows, horizons, primary, and pass bar on US mid
caps:

- Universe: US domestic common stocks reporting in USD, ranks 501–1000 by
  point-in-time market cap on each date (the latest filing's market cap rolled
  by the split-adjusted close). Active and delisted. The `exchange` field is
  not used because it is today's listing.
- Base cost 0.225% per side (FX plus a wider mid-cap half-spread); stress 3%.
- Its holdout also waits for the committed rule-search and model-mix
  selections.
- Decisions: both sizes beat the plain sort → the machinery works across
  size; one size only → no live change, but FTSE 250 evidence is read
  separately before stage 4; neither → follow hsr-v1.

The rule search (hrs-v1) stays on the S&P 500. Use `--universe midcap` with
`build-panel`, `run`, and `register`.

## Limits

- US results are evidence about the method, not proof for the FTSE 350.
- The AI judgment layer cannot be replayed: the model knows how 2000–2025 turned
  out. It stays forward-tested only (N39).
- The universe comparator is costless, so the market context spread is
  conservative. The plain sort pays costs like the buy tier.
- The replay reproduces the live screen, quirks included. Live rows carry
  dividend yield in percent while the dividend models' floors (0.02–0.04) read
  as fractions, so those floors pass almost any payer. The replay feeds percent
  too, so it tests the screen as it actually runs (see the deferred store).
- Sector is today's classification from the `tickers` table, not the sector on
  each date (Sharadar keeps no sector history). Sector-relative ranks therefore
  carry a little look-ahead, mostly around the 2018 GICS move of media and
  internet names into Communication Services.
- The windows fall in different value regimes (see the learning question).
  The primary cancels most of that; it cannot cancel a regime in which our
  extras themselves behave differently, which the `value_regime` split shows.

## Phases

### Phase 0 — registration (done)

The registration file above. The fingerprint is checked daily.

### Phase 1 — harness and parity (done)

`replay_screen` writes each date's metrics into a scratch library root and runs
`run_library_screen` on it, so the replay scores with exactly the offline screen
code. `forward_returns` and `score_cohorts` use the same exit rule as
`screen_premise_backtest`.

Parity: ops-monitor re-scores the committed FTSE run-snapshot cohorts with the
harness and diffs buy-tier spread, avoid spread, and rank IC against
`screen_premise_backtest.json`. At registration all 42 values matched exactly. The harness
scores snapshot closes, so when the premise store credits dividends
(`return_basis: price_plus_dividends`) parity rebuilds the premise cohorts
price-only from the same snapshots, with no fetch, and compares those.

### Phase 2 — licensed data (human gate)

Human checklist: `adhoc-historical-replay-data`. Personal-use licence only.

#### The month, day by day

Compute is not the constraint: the screen pass takes about 25 minutes per
universe and the rule search about 20–30 minutes (timed on synthetic data at
scale). What cannot be redone after deletion is any question we forgot to
ask. Hence this order:

| When | Step |
|------|------|
| Before paying | Both PRs merged; ops-monitor shows no replay findings; dry run on the free sample (step 0, passed 2026-10-08) |
| Day 1 | Subscribe. Bulk-download **every** table in the bundle, not only the five the adapter reads, to `~/sharadar` |
| Day 1–2 | `build-panel` for both universes; check both build reports |
| Day 2 | Development runs for both universes, baseline and `--variant dividend_units_fixed` (caches both sets of signals; the variant's holdout stays sealed). Review; change nothing registered. Fix adapter bugs only here, and log them as amendments |
| Day 3 | Rule search and model-mix search; commit both selections |
| Day 3 | Reveal hsr-v1, then hsr-mid-v1; delisting sensitivity for both; rule-search and model-mix reveals; commit the stores |
| Day 4 | Re-run the exploratory `dividend_units_fixed` on both universes (its holdout is open now); commit |
| Day 4–5 | Check the stores hold the series and per-model blocks. Run any other question that needs the raw data now |
| Before renewal | Cancel |
| Within 30 days of cancelling | Delete `~/sharadar`, `~/hsr-build`, `~/hsr-mid-build` (caches included); `confirm-deleted` |

Vendor: sharadar.com direct (`https://api.sharadar.com/v1.0`), not Nasdaq
Data Link, so do not use the `nasdaqdatalink` / `quandl` libraries. Plans,
tables, and endpoints are summarised in
[sharadar.com/llms.txt](https://sharadar.com/llms.txt); licence at
[sharadar.com/terms](https://sharadar.com/terms). Licence points that bind
this workflow:

- Personal, non-professional use by an individual; the key and data are not
  shared with anyone (§2–4).
- Delete the data, caches, and anything that could rebuild the tables within
  30 days of cancelling; research outputs, backtest results, and summary
  statistics may be kept (§10). That is the `confirm-deleted` step.
- Do not publish conclusions about the data's quality or fitness without
  Sharadar's written approval (§8). `build_report.json` (coverage, fill rates)
  stays in the build directory and never goes into the repository, PRs, or
  deferred entries.

0. Dry run before paying (done 2026-10-08: the direct layout built a panel
   with 0.98 coverage). The documented public `test-api-key` returns only the
   free sample (AAPL, about five years), and bulk downloads need a paid key.
   To repeat it, fetch each table with `format=csv&ticker=AAPL&from=1998-01-01`
   into a directory outside the repository, run `build-panel`, then delete the
   directory. The sample is licensed too: never commit it.
1. Subscribe to the **Bundle, Full History**, monthly ($69; the $29 Bundle is
   5 years only) for **one month**. Keep the key in an environment variable
   on your own machine, never in the repository, chat, or cloud secrets.
   Bulk-download every table (`years=full` returns a 302 to a zip):

   ```bash
   mkdir -p ~/sharadar && cd ~/sharadar
   for t in fundamentals stocks tickers actions sp500 daily metrics events \
            descriptions funds insiders holdings holdings_ticker holdings_investor; do
     curl -fL -o "$t.csv.zip" \
       "https://api.sharadar.com/v1.0/data/$t?api_key=$SHARADAR_API_KEY&years=full"
   done
   ```

   The adapter reads `fundamentals`, `stocks`, `tickers`, `actions`, and
   `sp500` as `.csv`, `.csv.gz`, or the vendor `.zip` files, under either the
   direct names or the Nasdaq Data Link `SHARADAR_<CODE>_…` names.
2. Build the inputs:

   ```bash
   ftse-historical-replay build-panel --sharadar-dir ~/sharadar --out ~/hsr-build
   ```

   For the mid-cap sibling, add `--universe midcap --out ~/hsr-mid-build`.
   This writes `panel.csv.gz`, `prices.csv.gz`, `daily.csv.gz` (adjusted daily
   OHLC for the tactical replay), `terminal_baseline.csv`,
   `terminal_sensitivity.csv`, and `build_report.json` (counts only). Check the
   report before running: about 500 members per date, `panel_coverage` above
   0.9, and the drop counts small. The adapter is
   `src/value_investor/sharadar_replay_adapter.py`; it is tested on synthetic
   tables with Sharadar's column names.
3. Development run, holdout sealed:

   ```bash
   ftse-historical-replay run --panel ~/hsr-build/panel.csv.gz \
     --prices ~/hsr-build/prices.csv.gz --terminal ~/hsr-build/terminal_baseline.csv
   ```

   The first run screens every date once (about 25 minutes) and caches the
   signals beside the panel; later runs and the rule search reuse the cache.
   Review the development window. Do not change anything registered.
4. Run the development `--variant dividend_units_fixed` on both universes
   (model scores for the model-mix search). Run the rule search
   ([historical-rule-search.md](historical-rule-search.md)) and the model-mix
   search ([historical-model-mix.md](historical-model-mix.md)) on the
   development window and commit both selections. `--reveal-holdout` refuses
   until both are committed: the holdout series carry per-model results the
   model-mix search must not see.
5. Reveal once: the same command with `--reveal-holdout`. Then the delisting
   sensitivity, which opens the holdout only because the baseline already did
   and never counts as a reveal:

   ```bash
   ftse-historical-replay run … --terminal ~/hsr-build/terminal_sensitivity.csv \
     --variant delisting_sensitivity
   ```

   Repeat the development run, reveal, and sensitivity with `--universe
   midcap` on `~/hsr-mid-build`. Commit `docs/data/historical_screen_replay.json`
   and `docs/data/historical_screen_replay_midcap.json`. Then `ftse-rule-search
   reveal --build ~/hsr-build` and `ftse-model-mix reveal --build ~/hsr-build
   --midcap-build ~/hsr-mid-build`, and commit
   `docs/data/historical_rule_search.json` and
   `docs/data/historical_model_mix.json`. Last, re-run `--variant
   dividend_units_fixed` on both universes (exploratory; now with the holdout).
6. Cancel the subscription and delete every raw table and derived file
   (`~/sharadar`, `~/hsr-build`, `~/hsr-mid-build`, including every
   `signals_cache*.csv.gz` and `daily.csv.gz`) within 30 days (licence). Then run
   `ftse-historical-replay confirm-deleted`. Keep the stores.

`run` refuses inputs inside the repository: the repo is public, and the licence
forbids sharing the data or anything that reproduces it. The committed store
holds cohort-level aggregates only.

On Windows, set `git config core.autocrlf false` before checkout so screen
files stay LF. Registration fingerprints normalise CRLF when hashing, so a
CRLF checkout still matches; do **not** run `register` only because of line
endings.

### Phase 3 — results in the system

`historical_screen_replay.json` → assessment scoreboard context beside the
published hurdle. No knob or signal reads it.

### Phase 4 — UK (only if the US result justifies it)

Free UK iXBRL starts around 2021; a longer UK history needs a paid source with a
data-quality audit first (L11). Official FTSE 350 history is paid; use the top
350 London main-market names by market cap, excluding trusts, at each date.

## Is one run enough?

Yes, for the verdict. The holdout can only be spent once: re-running the same
years after a change is a search over history (N33, N35). Re-run only when:

- the screen code changes materially (ops-monitor raises the stale-verdict
  warning); the new run is exploratory unless it uses years after 2025, or
- enough new years have passed to form a fresh holdout (L-entry in the deferred
  store), which needs another one-month subscription.

## Ops-monitor findings

| Title | Severity | Meaning |
|-------|----------|---------|
| Historical screen replay harness disagrees with screen-premise backtest | warn | Harness and the FTSE backtest disagree; fix before any licensed run |
| Historical screen replay registration predates screen code | info | Screen code changed while the holdout is sealed; run `ftse-historical-replay register` |
| Historical screen replay verdict no longer describes the live screen | warn | Screen code changed after the holdout reveal |
| Historical screen replay holdout revealed more than once | warn | Only the first reveal is evidence |
| Licensed replay data deletion not confirmed | warn | 60 days after the first licensed run on either universe (one paid month plus the licence's 30 days) with no `confirm-deleted`; one confirmation covers both stores |
| Historical mid-cap replay registration predates screen code | info | As above for hsr-mid-v1; run `ftse-historical-replay register --universe midcap` |
| Historical mid-cap replay verdict no longer describes the live screen | warn | Screen code changed after the hsr-mid-v1 reveal |
| Historical mid-cap replay holdout revealed more than once | warn | Only the first hsr-mid-v1 reveal is evidence |

The same check carries the rule search's findings
([historical-rule-search.md](historical-rule-search.md#ops-monitor-findings))
and the model-mix search's
([historical-model-mix.md](historical-model-mix.md#ops-monitor-findings)).
All `auto_fixable=False`.
