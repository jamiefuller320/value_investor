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
| `buy_tier_spread` | Equal-weight buy-tier forward return minus the equal-weight screened-universe return |
| `avoid_spread` | Same for `avoid` names; negative if the screen works |
| `rank_ic` | Spearman correlation of `conviction_score` with forward return |
| `dropped_unit_flips` | Names dropped because the forward return exceeded ±50% (pence/pound flips in frozen prices) |

Each horizon summary reports cohort count, `effective_n` (cohorts × 7 ÷ horizon,
discounting overlapping windows), mean, standard deviation and a 90% interval.
Intervals and `weeks_to_detect_3pct_annual` are withheld until `effective_n`
reaches 4, because overlapping windows understate the spread's volatility.
`weeks_to_detect_3pct_annual` is the number of weekly cohorts a 3%/yr buy-tier
edge needs before its 90% interval excludes zero, at the observed volatility.

### Limits

- Weeks of history (first snapshot 2026-08-02), price return only (no
  dividends), and only names that were screened at the time.
- Not the multi-year test L530 asks for. That needs dated fundamentals and
  delisted names (L11 / L542), which the project does not have.
- The 28-day view needs about 16 weekly cohorts before its interval is shown.

## Ops finding

| Title | Severity | Fires when |
|-------|----------|------------|
| **Value screen buy tier trails screened universe** | warn | The buy-tier spread's 90% interval lies wholly below zero at 7d or 28d |
| **Screen premise backtest observe failed** | warn | The refresh raised (unreadable snapshots) |

`auto_fixable=False`. Response: question the screen and its tier thresholds
before tuning overlays or AI gates. Do not change live signals from this finding
alone.

## Related

The same change fixes `backtest_health.json`. `run_backtest_health` looked for
snapshots in `docs/data/history/history`, so its pooled per-signal forward
returns (`horizons_computed`) were always empty.
