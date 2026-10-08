# Historical model-mix search (pre-registered, hms-v1)

A pre-registered test of **which screening models to combine**, run on the
same licensed builds as the [historical screen replay](historical-screen-replay.md)
(S&P 500 and the mid-cap sibling). Research only: no book, signal, weight, or
knob reads it.

- Registration (frozen): `docs/data/historical_model_mix_registration.json`
- Results (aggregates only): `docs/data/historical_model_mix.json`
- Code: `src/value_investor/model_mix_search.py` (`ftse-model-mix`)
- Daily status: the `model_mix` block of `docs/data/historical_screen_replay.json`

## Learning question

Which of the screen's 22 models, and five published signals they do not
cover, rank next month's total returns reliably in **both** US universes over
2000–2012? Does an equal-weight mix of only those beat the frozen screen's own
model mix (its `composite_score`) at the same breadth over 2013–2025, after
costs?

"Test many and keep the best" on one stretch of history mostly finds luck:
each window has about 150 monthly observations, and published signals lose
part of their edge once known. So the search has no fitted weights. It uses
one fixed rule on the development window, must hold in both universes, and
gets a single holdout test against the mix we already run.

N33 forbids tuning the screen on history unless there is an explicit decision
to run a controlled research experiment. This registration is that experiment
(requested 2026-10-08). It never writes to the screen. A winning mix is a
proposal for a cold-start twin.

## Candidates (27, fixed)

| Group | Candidates | Score |
|---|---|---|
| Screen models | All 22 in `models.ALL_MODELS` (Graham, Schloss, deep value, earnings and FCF yield, PEG, quality and moat, dividend, Magic Formula, Acquirer's Multiple, Dreman, Piotroski, composite value, earnings quality, financial health) | Each model's own 0–1 score from the `dividend_units_fixed` signal cache: the models as the next epoch will score them once L571 is fixed |
| Gross profitability | (gross margin × revenue) / total assets | Novy-Marx (2013); higher is better |
| Accruals | (net income − operating cash flow) / total assets | Sloan (1996); lower is better |
| Net share issuance | shares / shares a year earlier − 1 | Pontiff–Woodgate (2008); lower is better |
| Asset growth | total assets / a year earlier − 1 | Cooper–Gulen–Schill (2008); lower is better |
| Momentum 12-1 | close one month before / twelve months before − 1 | Jegadeesh–Titman (1993); value with momentum: Asness–Moskowitz–Pedersen (2013) |

The panel signals read the latest trailing-twelve-month filing and the one a
year earlier, filed at least 2 days before the rebalance. `build-panel` writes
`total_assets_prev` for asset growth. The screen does not read it.

## The rule

1. **Monthly rank IC.** On each month-end, the Spearman correlation between a
   candidate's score and the total return to the next month-end, across the
   names screened with a fresh price (at least 50).
2. **Eligible** only if, in every universe on the development window, all of
   the following hold:
   - The median share of names scored is at least 50%.
   - At least 60 months have an IC.
   - The 90% lower bound of the mean IC (Newey–West, lag 12) is above zero.
   - The mean IC is positive in each half of the window.
3. **Redundancy.** Order the eligible candidates by mean IC. Keep each one in turn
   unless its mean cross-sectional rank correlation with an already-kept
   candidate is above 0.8. This drops near-duplicates such as two cheapness
   ratios.
4. **Mix.** Equal-weight mean of the kept candidates' percentile ranks. A name
   needs at least half of the kept candidates scored.
5. **Book.** Top 30% by mix score, equal weight, monthly, costed on turnover
   (0.175% per side for the S&P 500, 0.225% for mid caps, 3% stress).

References, built the same way:

| Book | Role |
|---|---|
| `frozen_composite` | Top 30% by the frozen screen's `composite_score` (baseline cache). **The decision comparator**: equal breadth isolates the mix from the tiering that hsr-v1 tests |
| `plain_value` | The hsr-v1 plain value book (top 30% by earnings yield), as in hrs-v1 |
| `all_candidates` | Every candidate with enough coverage, averaged without the IC filter. Shows whether the selection beats averaging everything |
| market | Cap- and equal-weighted screened universe; context |

Overfitting, per universe: PBO (CSCV, 16 blocks) across the single-candidate
books, and the deflated Sharpe ratio of the mix against them.

## Reveal order

The replay's committed holdout series carry each model's holdout results, so
the selection must be committed **before** either replay holdout opens:

1. Development runs of both replay universes, baseline **and**
   `--variant dividend_units_fixed` (this caches the model scores; the
   variant's holdout stays sealed until the baseline reveal).
2. `ftse-model-mix search --build ~/hsr-build --midcap-build ~/hsr-mid-build`,
   then commit `docs/data/historical_model_mix.json`.
   `ftse-historical-replay run --reveal-holdout` refuses until this selection
   (and the rule search's) is committed. `ftse-model-mix search` refuses once
   either replay holdout is revealed.
3. After the replay reveals: `ftse-model-mix reveal --build … --midcap-build …`
   once, then commit. Base and stress cost, both universes.

## Decisions (agreed before the run)

| Holdout result | Action |
|---|---|
| Mix minus frozen composite is wholly above zero (95%) in **both** universes at base cost, and the mix does not fail against the plain value book | Propose the kept candidates as the composite of a cold-start FTSE 350 library-screen paper twin with a frozen epoch (a screen-code change, so a new replay registration). No live book changes on backtest evidence alone |
| Adds in one universe only, or adds but fails against the plain book (`partial`) | No change; record which size. Read FTSE 250 evidence separately before stage 4 |
| Inconclusive or below zero (`no_gain_over_frozen_mix`) | Keep the frozen mix; the development ranking was noise |
| Nothing eligible in both universes (`no_reliable_candidates`) | Keep the frozen mix |

Holdout ICs per candidate are reported after the reveal and never used to
re-select. A model reliably negative in both holdouts is a candidate for
removal in the next simplification review, through the same twin path.

### Reading the result

* `mix_minus_frozen_composite` decides. `mix_minus_all_candidates` shows
  whether the filter mattered. A high PBO or a low deflated Sharpe means the
  development ranking should not be trusted even if the holdout passes.
* The candidates include non-value signals (momentum, profitability). A mix
  that wins mainly through them is a different strategy from the value
  screen. Read the per-candidate ICs before proposing a twin.
* US evidence is about the method, not proof for the FTSE 350. The twin's
  forward FTSE results decide.

## Running it

```bash
ftse-model-mix search --build ~/hsr-build --midcap-build ~/hsr-mid-build
git add docs/data/historical_model_mix.json && git commit -m "Record the hms-v1 selection"
# … replay reveals (historical-screen-replay.md) …
ftse-model-mix reveal --build ~/hsr-build --midcap-build ~/hsr-mid-build
```

It reuses both signal caches, so it costs minutes, not another screening
pass. The builds must sit outside the repository (the tool refuses
otherwise). The committed store holds per-candidate IC summaries and monthly
IC means, book-level monthly returns, and correlations between candidates. No
per-name rows.

If the screen or mix code changes before the run, run `ftse-model-mix
register` (refused after a reveal). `ftse-model-mix status` prints the
fingerprints, selection, and reveals.

## Ops-monitor findings

Raised by `check_historical_screen_replay` from the `model_mix` block.

| Title | Severity | Meaning |
|-------|----------|---------|
| Historical model-mix search registration predates screen or mix code | info | Screen, mix-search, rule-search, or adapter code changed while the holdout is sealed; run `ftse-model-mix register` |
| Historical model-mix search verdict no longer describes the live code | warn | Code changed after the reveal |
| Historical model-mix search holdout revealed more than once | warn | Only the first reveal is evidence |

All `auto_fixable=False`.
