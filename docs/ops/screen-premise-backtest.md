# Screen premise backtest (L530, first version)

Observe-only instrument for one learning question:
**do the screen's buy-tier names (`buy` + `strong_buy`) out-earn the rest of the
screened FTSE universe over the following weeks?**

Every overlay, AI gate and knob sits on top of this premise. The paper books
cannot test it in a useful time: on 3-name books a 3%/yr edge needs 125+ years
of marks (see [track statistics](track-statistics.md), L529). A cross-sectional
test compares ~60 buy-tier names with ~250 screened names every week, so it
gathers evidence far faster.

This instrument never changes signals, books, knobs or gates.

## What it computes

Daily ops-monitor (`check_screen_premise_backtest` in `collect_ops_findings`)
reads the weekly run snapshots in `docs/data/history/` (signals and prices frozen
at run time, so point-in-time by construction) and writes
`docs/data/screen_premise_backtest.json`.

Cohorts are runs at least 6 days apart. For each horizon (7 and 28 days) and
each cohort with an exit run at or after the horizon:

| Field | Meaning |
|-------|---------|
| `buy_tier_spread` | Equal-weight buy-tier forward return minus the equal-weight screened-universe return. This is the spread that judges the screen. The daily refresh adds ex-date dividends (dividend ÷ prior close, capped at 15%) between the entry and exit runs |
| `price_buy_tier_spread` | The same spread on price return only |
| `avoid_spread` | Same for `avoid` names; negative if the screen works |
| `rank_ic` | Spearman correlation of `conviction_score` with forward return |
| `ai_gate_spread` | Buy-tier names the live AI gate would take (`research_verdict == accumulate`) minus buy-tier names it would reject (other verdicts or no memo). Needs at least 3 names on each side |
| `ai_gate_pass_share` | Share of the buy tier the gate takes. Close to 100% means the gate barely binds and the spread cannot be measured well |
| `conviction_half_spread` | Top half of the buy tier by `conviction_score` minus the bottom half. Within-cohort halves, so the 2026-09 conviction rescale does not bias it |
| `dropped_unit_flips` | Names dropped because the forward return exceeded ±50% (pence/pound flips in frozen prices) |
| `sector_splits` | Buy-tier forward return minus the screened universe, split into Financial Services, Real Estate, and the rest. A slice needs 3 names |

`financials_real_estate_split` is the 28-day decision. Industrial models stay inclusive unless those two sectors are at least 15% of the buy tier **and** dropping them moves the buy-tier spread by at least 1 percentage point. A shortfall on either bar leaves `exclude_from_industrial_models` false. The backtest does not edit the models.

Research verdicts come from the snapshot row when present. Older snapshots
(before the 2026-10 fix) have empty research fields, so the verdict is looked up
in the memo revision archive (`docs/data/research/<ticker>/revisions`) strictly
as of the run (`get_research_as_of`): a memo written after the run is never
used. Cohorts before the first memo (2026-08-02, 2026-08-09) have no gate
figures.

### Why the snapshots had no research verdicts

`ftse-email` runs the screen first, and the screen saves its run snapshot and
copies it to `docs/data/history/`. Committed memos are only seeded into
`output/research` afterwards, so on CI the screen's research overlay saw an
empty store and every snapshot row had `research_verdict = None`. After its
final research enrichment, `ftse-email` now fills the empty research fields
(`research_verdict`, `research_confidence`, `research_as_of`) of that run's
snapshot in both `output/history/` and `docs/data/history/`
(`backfill_snapshot_research`). `adjusted_signal` keeps the screen's overlay chain.

Each horizon summary reports cohort count, `effective_n` (cohorts × 7 ÷ horizon,
discounting overlapping windows), mean, standard deviation and a 90% interval.
Intervals and `weeks_to_detect_3pct_annual` are withheld until `effective_n`
reaches 4, because overlapping windows understate the spread's volatility.
`weeks_to_detect_3pct_annual` is the number of weekly cohorts a 3%/yr buy-tier
edge needs before its 90% interval excludes zero, at the observed volatility.

### Limits

- Weeks of history (first snapshot 2026-08-02), and only names that were
  screened at the time. The judging spread adds ex-date dividends when Yahoo
  has them. A name with no dividend history keeps its price return and is
  listed in `dividends_skipped_tickers`. `price_buy_tier_spread` is the
  price-only figure.
- Not the multi-year test L530 asks for. That needs dated fundamentals and
  delisted names (L11 / L542), which the project does not have.
- The 28-day view needs about 16 weekly cohorts before its interval is shown.

## Ops finding

| Title | Severity | Fires when |
|-------|----------|------------|
| **Value screen buy tier trails screened universe** | warn | The buy-tier spread's 90% interval lies wholly below zero at 7d or 28d |
| **AI research gate picks trail rejected buy-tier names** | warn | The `ai_gate_spread` 90% interval lies wholly below zero at 7d or 28d |
| **Screen premise backtest observe failed** | warn | The refresh raised (unreadable snapshots) |

`auto_fixable=False`. Response: question the screen and its tier thresholds
before tuning overlays or AI gates. Do not change live signals or tighten the AI
gate from these findings alone.

### First reading (2026-10-06, 8 weekly cohorts)

- The gate passes about 92% of the buy tier (3–8 names rejected a week), so
  `ai_gate_spread` is noise so far: 7d mean +0.81%, 90% CI −0.74% to +2.35%.
  A binding gate is parked as N189.
- `conviction_half_spread` is negative: the higher-conviction half of the buy
  tier trailed the lower half by 0.46% a week (90% CI −0.96% to +0.03%) and by
  1.7% over 28 days (interval not yet shown). Conviction ranking inside the buy
  tier is not yet shown to help.

## Related

The same change fixes `backtest_health.json`. `run_backtest_health` looked for
snapshots in `docs/data/history/history`, so its pooled per-signal forward
returns (`horizons_computed`) were always empty.
