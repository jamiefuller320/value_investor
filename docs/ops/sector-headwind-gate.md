# Sector headwind gate

**Strategy part:** 3, Sector sound  
**Deferred design:** N251  
**Mode:** observe-only; `influences_live` is false

## Learning question

For each sector of the FTSE 350 (and admitted library markets where inputs
exist), can we produce a cited, point-in-time-safe verdict of whether the
sector is in a broad price or earnings decline, covering every sector that
contains a buy-tier name?

The v0 computed universe is FTSE 350. Current library screen CSVs carry sector
labels, but not the same point-in-time interim and normalized-income fields
used here. V0 therefore records admitted markets as not scored instead of
silently treating a sector label and price history as complete evidence.

## Why sector-relative ranking is not enough

The existing composite ranks companies relative to sector peers. It can still
rank the cheapest company in a falling sector highly. This gate asks an
absolute question about the sector itself: are price and earnings declines
broad across its members?

## Components and thresholds

All chart observations are filtered to dates on or before the store's
`as_of`. A sector component needs at least four covered members and at least
60% member coverage.

| Component | Measure | Headwind threshold |
|---|---|---|
| Price breadth | Share of members whose latest close is below the 200-trading-day average | At least 65%, together with the 126d trend threshold |
| Sector trend | Equal-weight member return over about 63 and 126 trading days; current drawdown from the trailing 252-trading-day sector high is diagnostic | 126d return below -10%, together with price breadth |
| Earnings breadth | Share with a positive `interim_eps_decline_pct`, negative `yahoo_normalized_income_growth_pct`, or negative `adjusted_eps_growth_pct` | At least 50% |
| Operating-decline breadth | Share with `verdict: declining` in the optional operating-decline store | At least 50% |

The operating-decline component is optional while package 1.1 lands. Its
absence is cited and never manufactures a pass.

## Verdict rule

- `headwind`: price breadth and 126d trend jointly cross their thresholds, or
  either available earnings/operating-decline breadth reaches 50%.
- `sound`: price breadth, 126d trend and earnings breadth all meet minimum
  coverage, and no headwind rule fires.
- `insufficient_data`: no headwind is established and a core component lacks
  minimum coverage. This is fail-closed and is not a pass.

The 63d return and one-year drawdown provide context but do not independently
set the v0 verdict.

## Inputs and store

| Path | Use |
|---|---|
| `docs/data/latest.json` → `reports` | FTSE membership, sector, buy tier and earnings breadth |
| `docs/data/charts/{TICKER}.json` | PIT close, SMA200 and trend history |
| `docs/data/operating_decline_gate.json` | Optional per-name operating-decline verdict |
| `docs/data/sector_headwind_gate.json` | Persisted sector and name projection |

The store includes sector reasons, coverage and trend metrics, member and
buy-tier lists, plus a ticker-to-sector-verdict projection. It commits through
the ops-monitor `GHA_COMMIT_OPTIONAL` lane.

## Automation and findings

Daily ops-monitor calls `check_sector_headwind_gate` and refreshes the store.
It emits:

- **Sector headwind gate refreshed (observe)** with verdict counts, named
  headwind sectors and buy-tier exposure.
- **Sector headwind gate coverage gap** when a sector containing a buy-tier
  name is `insufficient_data`.
- **Sector headwind gate refresh failed** if committed inputs cannot be read.

All findings have `auto_fixable=False`. Manual drill-down:

```bash
ftse-sector-headwind-gate
ftse-sector-headwind-gate --sector Industrials --json
```

## Constraints and later use

This instrument never edits screen signals, books, fills, rankings, knobs or
paper automation. It makes no network calls. It is not an entry veto and not a
sell instruction.

After the owner accepts the existing Phase 1 strategy gate, a future cold-start
strategy book may use the verdict as an entry filter. The same accepted gate
may later become a thesis-break trigger for recovery holds. Neither use is
enabled by v0.
