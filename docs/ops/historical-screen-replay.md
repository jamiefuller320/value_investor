# Historical screen replay (pre-registered)

Point-in-time replay of the frozen value screen on 25 years of US data.
Closes L536 and L542; supersedes L565. Observe-only: never changes signals,
books, or knobs.

- Registration (frozen): `docs/data/historical_screen_replay_registration.json`
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
tier (buy + strong_buy) beat:

1. the equal-weight universe, and
2. a plain top-30% earnings-yield sort of the same names,

on total return after costs?

Question 1 asks whether the screen has an edge at all. Question 2 asks whether
our extra machinery adds anything over textbook value.

## Pre-registration (fixed before data is bought)

| Item | Registered value |
|------|------------------|
| Screen | Code fingerprint over `models/`, `scoring/__init__.py`, `model_families.py`, `model_weights.py`, `signals.py`, `sector_scoring.py`, `data_quality.py`, `signal_stability.py`. Default model weights; the 28-day learner is not run (N197) |
| Universe | S&P 500 members on each date, active and delisted (Sharadar `sp500`) |
| Fundamentals | Sharadar `fundamentals`, dimension `ART` (as reported, trailing twelve months), latest row filed at least 2 days before the date. As-reported, so later restatements cannot leak. Filings over 456 days old and non-USD reporters are dropped and counted |
| Prices | `closeadj` (splits, dividends, spinoffs) for total return. Market cap is the filing-date `marketcap` rolled forward by the split-adjusted close |
| Metric units | Yahoo conventions, as the live screen receives them: dividend yield and debt/equity in percent; margins, returns, and growth as fractions. Growth is quarterly year-on-year (`ARQ`); `*_prev` fields come from the `ART` row a year earlier |
| Rebalance | Last trading day of each month |
| Development window | Entries 2000-01 to 2012-12 |
| Holdout window | Entries 2013-01 to 2025-09, sealed until revealed once |
| Horizons | 30, 91, 365 days; exit on the first trading day on or after the horizon |
| Primary metric | 30-day buy tier minus universe, net of costs |
| Secondary metric | Buy tier minus the plain earnings-yield sort |
| Pass bar | Holdout 90% interval on the primary wholly above zero, and the 365-day net spread not wholly below zero |
| Costs | 0.53% per side (base) and 3% (stress), charged on measured buy-tier turnover |
| Delistings | Exit at the last adjusted close; sensitivity −30% for non-merger delistings |
| Forbidden | Threshold, weight, or model search on any window (N33). Per-model rank IC is report-only |

The primary is the 30-day horizon because non-overlapping monthly cohorts give
about 150 independent observations per window. Overlapping 365-day cohorts
give about 13, which only resolves very large edges; they confirm that the
monthly edge does not reverse.

Any change to the registration or to the fingerprinted code after the holdout is
revealed opens a new `registration_id`, and its results are exploratory.

## Decisions (agreed before the run)

| Holdout result | Meaning | Action |
|---|---|---|
| Beats universe and plain sort | Screen machinery adds value | Keep it; multi-year total return becomes the fitness test N197 asks for |
| Beats universe, not plain sort | Extras add nothing over textbook value | Simplify toward the published sorts; the AI layer must earn its keep separately |
| Does not beat universe | Premise fails in the US | Stop building forward machinery on this screen; rethink before stage 4 |

## Limits

- US results are evidence about the method, not proof for the FTSE 350.
- The AI judgment layer cannot be replayed: the model knows how 2000–2025 turned
  out. It stays forward-tested only (N39).
- The plain earnings-yield sort and the universe are costless comparators, so
  the net spread is conservative.
- The replay reproduces the live screen, quirks included. Live rows carry
  dividend yield in percent while the dividend models' floors (0.02–0.04) read
  as fractions, so those floors pass almost any payer. The replay feeds percent
  too, so it tests the screen as it actually runs (see the deferred store).

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
`screen_premise_backtest.json`. At registration all 42 values matched exactly.

### Phase 2 — licensed data (human gate)

Human checklist: `adhoc-historical-replay-data`. Personal-use licence only.

1. Subscribe to the Sharadar Core US Equities Bundle, full history, for **one
   month** (monthly plan). Bulk-download `fundamentals` (SF1), `stocks` (SEP),
   `actions`, `tickers`, `sp500` to a directory **outside the repository**
   (`.csv`, `.csv.gz`, or the vendor `.zip` files as downloaded).
2. Build the inputs:

   ```bash
   ftse-historical-replay build-panel --sharadar-dir ~/sharadar --out ~/hsr-build
   ```

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
4. Run the rule search on the development window and commit its selection
   ([historical-rule-search.md](historical-rule-search.md)). `--reveal-holdout`
   refuses until that selection is committed.
5. Reveal once: the same command with `--reveal-holdout`. Then the delisting
   sensitivity, which opens the holdout only because the baseline already did
   and never counts as a reveal:

   ```bash
   ftse-historical-replay run … --terminal ~/hsr-build/terminal_sensitivity.csv \
     --variant delisting_sensitivity
   ```

   Commit `docs/data/historical_screen_replay.json`. Then `ftse-rule-search
   reveal --build ~/hsr-build` and commit `docs/data/historical_rule_search.json`.
6. Cancel the subscription and delete every raw table and derived file
   (`~/sharadar`, `~/hsr-build`) within 30 days (licence). Keep the store.

`run` refuses inputs inside the repository: the repo is public, and the licence
forbids sharing the data or anything that reproduces it. The committed store
holds cohort-level aggregates only.

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

The same check carries the rule search's findings
([historical-rule-search.md](historical-rule-search.md#ops-monitor-findings)).
All `auto_fixable=False`.
