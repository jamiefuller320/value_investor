# Sector headwind gate

**Strategy part:** 3, Sector sound  
**Deferred design:** N251  
**Mode:** observe-only; `influences_live` is false

## Learning question

For each sector of the FTSE 350 (and admitted library markets where inputs
exist), can we produce a cited, point-in-time-safe verdict of whether the
sector is in a broad price or earnings decline, covering every sector that
contains a buy-tier name?

The gate scores the FTSE 350 and every library market whose `is_graduated`
flag is true in `docs/data/market_status.json` at refresh time. The list is
read from that flag. It is not hard-coded. A market that is not graduated is
left unscored. On 2026-11-05 that was 21 library markets, plus the FTSE 350.

## Why sector-relative ranking is not enough

The existing composite ranks companies relative to sector peers. It can still
rank the cheapest company in a falling sector highly. This gate asks an
absolute question about the sector itself: are price and earnings declines
broad across its members?

## Components and thresholds

All chart observations are filtered to dates on or before that market's
decision date (`metrics.as_of` on the sector). The top-level `as_of` is the
FTSE decision date. A sector component needs at least four covered members
and at least 60% member coverage.

| Component | Measure | Headwind threshold |
|---|---|---|
| Price breadth | Share of members whose latest close is below the 200-trading-day average | At least 65%, together with the 126d trend threshold |
| Sector trend | Equal-weight member return over about 63 and 126 trading days; current drawdown from the trailing 252-trading-day sector high is diagnostic | 126d return below -10%, together with price breadth |
| Earnings/operating breadth (primary) | Share with `verdict: declining` in the operating-decline store; only `clear` and `declining` verdicts count as covered evidence | At least 50% |
| Screen-fields fallback | Used only when operating-decline coverage is missing or thin: `interim_eps_decline_pct` ≥10%, `yahoo_normalized_income_growth_pct` ≤-5%, or `adjusted_eps_growth_pct` ≤-5% | At least 50% |

There is one definition of declining when the operating-decline store has
sufficient coverage: its per-name verdict. The screen-fields rule is only a
materiality-based fallback. It imports the operating gate's 10% interim-EPS
threshold rather than defining another threshold. Missing or
`insufficient_data` operating verdicts are not evidence and do not enter the
coverage denominator.

## Verdict rule

- `headwind`: price breadth and 126d trend jointly cross their thresholds, or
  the selected earnings/operating breadth reaches 50%.
- `sound`: price breadth, 126d trend and the selected earnings/operating
  component all meet minimum coverage, and no headwind rule fires.
- `insufficient_data`: no headwind is established and a core component lacks
  minimum coverage. This is fail-closed and is not a pass.

The 63d return and one-year drawdown provide context but do not independently
set the v0 verdict.

## How a market is scored

Each market is scored on its own first. Membership, the sector label and the
buy tier come from that market's screen. Price breadth and the sector trend
come from that market's chart files (`docs/data/charts/{ticker}.json`, the
same files the FTSE gate uses). Operating-decline breadth comes from
`docs/data/operating_decline_gate.json`. `assess_sector` is the only scorer.
Thresholds are the table above. The minimum of four covered members at 60%
coverage is not relaxed. A sector smaller than that is `insufficient_data`
on its own market. It is rescored across a fixed region only when the failure
is the member-count rule. Chart-coverage and breadth failures are not
rescored. See [Fallbacks and signal risk](#fallbacks-and-signal-risk).

The decision date for a daily refresh is the later of the screen date and the
decline snapshot's `as_of`. Chart bars after that date are ignored. The
decline snapshot is used only when its `as_of` is on or before the decision
date, so the copy just written by the operating-decline check is inside the
cutoff, and a later copy is not. Passing `--as-of` pins every market to that
date. A decline snapshot dated after it is ignored, and earnings breadth falls
back to the screen fields that are allowed for that market.

## What each market's screen contributes

| Market | Screen | Sector label and buy tier | Price | Earnings breadth |
|---|---|---|---|---|
| FTSE 350 | `docs/data/latest.json` `reports`, dated `run_at` | `sector`, `signal` | Charts | Decline store when it covers the sector. Otherwise `interim_eps_decline_pct`, `yahoo_normalized_income_growth_pct` and `adjusted_eps_growth_pct` at the thresholds above |
| Graduated library market | `docs/data/library/markets/<market>/screen/latest_signals.csv`. The date is `run_at` in `screen/latest_summary.json`, or the newest `screen/history/run_*.json.gz` when the summary has no date | `sector`, `signal` | Charts for those tickers | Decline store per member. A member with no usable verdict may use `earnings_growth` from that CSV. See [Fallbacks and signal risk](#fallbacks-and-signal-risk) |

Library screen files do not carry the three v0 fallback fields. They do carry
`earnings_growth`. That column is the library earnings fallback below. It is
not used for FTSE names. When neither the decline store nor that fallback
covers four members and 60% of the sector, earnings breadth is missing. The
sector is then `insufficient_data` unless the price rule has already fired.
Missing data is not a pass.

## Cross-listings

A company can sit in more than one library market (a DAX name also in the
Euro Stoxx 50, a Nasdaq-100 name also in the S&P 500). Each market scores its
own sector. The verdict is per market and ticker, not per ticker alone.

Sector keys are `<market>:<sector>`, which is the FTSE form `ftse350:<sector>`
extended to library markets. `names_by_market` maps market, then ticker, to
the sector and the verdict. The flat `names` map is still the FTSE projection
only, so an existing reader that looks up a FTSE ticker keeps working.

The decline store keeps one row per ticker. When the same ticker was seen in
two markets, the row belongs to whichever market was stored first. Both sector
scores use that row. It is one company's operating verdict. Price breadth
still uses each market's own members.

## Dated sector labels

Library history files do not store a sector. The label lives on the current
`latest_signals.csv`. Each refresh appends to
`docs/data/sector_label_history.jsonl` only when a market and ticker is seen
for the first time, or when its sector text changes. A repeat of the same
label adds nothing. Each row has the market, ticker, sector, the screen date,
and the refresh decision date (`as_of`).

`sector_label_as_of(market, ticker, date)` returns the latest row whose
decision date is on or before the date asked. A label first recorded on
5 November is not applied to 3 November. No row means no label.

## Dated verdict history

Each refresh also writes a dated copy of `names` and `names_by_market` to
`docs/data/gate_history/sector_headwind/<date>.json.gz`. The strategy book
reads the copy dated strictly before each signal session, not the live store.
Dating, retention, the git bootstrap and the stale-history warning are shared
with the decline gate: see
[operating-decline-gate.md](operating-decline-gate.md#dated-verdict-history).

## Inputs and store

| Path | Use |
|---|---|
| `docs/data/latest.json` → `reports` | FTSE membership, sector, buy tier and fallback earnings breadth. Screen date is `run_at` |
| `docs/data/market_status.json` | `markets[].is_graduated` selects library markets |
| `docs/data/library/markets/<market>/screen/latest_signals.csv` | Library membership, sector, signal |
| `docs/data/library/markets/<market>/screen/latest_summary.json` | Library screen date (`run_at`) |
| `docs/data/charts/{TICKER}.json` | Point-in-time close, 200-day average and trend |
| `docs/data/operating_decline_gate.json` | Primary per-name operating-decline verdict |
| `docs/data/sector_headwind_gate.json` | Sector verdicts, per-market summary, FTSE `names`, `names_by_market` |
| `docs/data/sector_label_history.jsonl` | Append-only sector labels |
| `docs/data/gate_history/sector_headwind/<date>.json.gz` | Dated copies the strategy book reads |

`universe.included` lists the FTSE 350 and the graduated markets that were
scored. `universe.admitted_library_markets` is that library list.
`universe.not_scored` records markets that were skipped, with the reason
(`not_graduated`, or a missing screen). The summary has overall counts and
`by_market` counts: sectors, verdicts, buy-tier names by verdict, and each
buy-tier name left in an `insufficient_data` sector with the reason (too few
members, chart coverage, chart history, earnings breadth).

Both store files commit through the ops-monitor `GHA_COMMIT_OPTIONAL` lane.

## Measured on 2026-11-05

21 graduated library markets plus the FTSE 350. 211 sectors: 17 sound, 13
headwind, 181 `insufficient_data`. 443 buy-tier names counted per market
(a cross-listed name counts in each market): 80 in a sound sector, 40 in a
headwind sector, 323 in an `insufficient_data` sector.

Chart files covered every FTSE member. Library coverage of members was about
60% for the S&P 500 (304 of 503) and the ASX 200 (114 of 196), about 79% for
the Nasdaq-100, about 73% for the FTSE SmallCap, about 88% for the Hang Seng,
and 100% for most European markets. Where a sector still had four priced
members and 60% coverage, the price rule could fire. Where it did not, the
reason is chart coverage.

The common library failure before the fallbacks below was earnings breadth.
Decline-store coverage is thin outside the names that already have research
files, and the v0 screen fallback fields are absent. The other common failure
is size: many sectors in the smaller indices have fewer than four members.
Both now have a labeled fallback. The 2026-11-05 counts above are the
own-market baseline from before those fallbacks.

Buy-tier sectors are mostly `insufficient_data` in every graduated library
market except `us_adr_asia` (1 of 3). The coverage-gap finding names those
markets. It does not fetch charts, ingest filings, or rewrite memos.

## Fallbacks and signal risk

Two fallbacks exist so a library buy-tier name is not left unscored only
because its own sector is thin in the decline store or has fewer than four
members. Both are weaker than the primary inputs. Every name row carries the
labels, and the strategy book must store both on each episode and split its
board by them. The registration amendment that records those columns is
separate from this runbook.

`earnings_fallback_used` is true when the deciding sector row used
`earnings_growth` for at least one member. `sector_basis` is `own_market` or
`regional`. A regional name also has `region`. `own_market_verdict` keeps the
first score. `sector_verdict` is the verdict in force.

### Library earnings-growth fallback

For a library member only, earnings breadth uses a usable decline-store
verdict (`clear` or `declining`) when that member has one. When it does not,
the gate reads `earnings_growth` on that market's `latest_signals.csv`. The
column is Yahoo year-on-year quarterly earnings growth as a fraction, for
example `-0.12`. It declines at the same line as v0's non-interim screen
fields: `<= -0.05` (`SCREEN_EARNINGS_GROWTH_DECLINE_PCT`). Coverage is
unchanged: at least four covered members and 60% of the sector. FTSE names
do not use this column, even when `latest.json` carries it. FTSE still uses
the decline store for the whole sector when that store covers, and otherwise
the three v0 screen fields.

The CSV is a snapshot. It is used only when that market's screen date (the
date the gate already stores) is on or before the decision cutoff. Library
history runs (`screen/history/run_*.json.gz`) do not carry `earnings_growth`,
so an archive replay cannot reproduce this fallback.

Each sector records `earnings_breadth_sources` as
`{decline_store: n, screen_earnings_growth: n}` and
`earnings_fallback_used` when the second count is above zero. The reason code
`SCREEN_EARNINGS_GROWTH_FALLBACK` is on that sector row.

This fallback is weaker because the Yahoo figure is statutory, noisy, and one
quarter. It is not a point-in-time series in the screen archive.

### Regional fallback for small sectors

The own-market score is unchanged and is kept. Only an `insufficient_data`
result whose reason is `TOO_FEW_SECTOR_MEMBERS` (fewer than four members in
that market) is rescored. Low chart coverage, short chart history, and thin
earnings breadth do not trigger it.

The rescore calls the same `assess_sector`, with the same thresholds and the
same fail-closed rule. Members are the union of that exact sector string
across the region's scored markets, deduplicated by ticker. A cross-listed
name counts once. The kept row is the one from the earliest market in the
frozen list below. Sector labels must match exactly. `Industrials` and
`Industrial Goods` are not pooled. There is no map between label
vocabularies.

Only markets that are graduated at refresh, plus `ftse350`, contribute
members. A market that is not in the map gets no regional fallback. If the
regional group is still under four members, or it fails coverage, the verdict
stays `insufficient_data`, `sector_basis` is `regional`, and the reason is
kept.

The regional decision date is the earliest decision date among the markets
that contain that sector, so a later screen is not applied to an earlier
market. `earnings_growth` on a library member is read only when that member's
own screen date is on or before this regional date. Charts and the decline
snapshot are cut off the same way.

Regional rows are stored at `region:<region>:<sector>`. The frozen map is:

| Region | Markets |
|---|---|
| `uk` | ftse350, ftse_smallcap, aim |
| `europe` | aex, atx, bel20, cac40, dax, euro_stoxx50, ftse_mib, ibex35, iseq20, omxs30, psi20, smi |
| `north_america` | sp500, nasdaq100, tsx60 |
| `asia_pacific` | hang_seng, sti, us_adr_asia, asx200 |

This applies to FTSE sectors as well. A FTSE sector with fewer than four
members, such as Agriculture/Commodities, can be scored across `uk`.

A regional group mixes economies. `asia_pacific` is the loosest mix. The
label `sector_basis=regional` is how the strategy book keeps those episodes
separate from an own-market sector score.

Summary counts, per market and overall, split buy-tier names into own-market
versus regional, and into earnings-fallback used versus not used, by verdict.
Own-market sector rows stay in the store under `<market>:<sector>`. The
headline sector counts are those own-market rows. Buy-tier verdict counts use
the verdict in force.

## Measured after the fallbacks (2026-11-05)

Same 443 buy-tier listings. Verdict in force: 334 sound (was 80), 78 headwind
(was 40), 31 `insufficient_data` (was 323).

Of those, 397 keep an own-market basis (309 sound, 59 headwind, 29
`insufficient_data`) and 46 use a regional basis (25 sound, 19 headwind, 2
`insufficient_data`). 31 regional sector rows were stored: 16 sound, 8
headwind, 7 `insufficient_data`.

370 buy-tier names sit in a sector that used the earnings-growth fallback
(265 sound, 76 headwind, 29 `insufficient_data`). 73 do not (69 sound, 2
headwind, 2 `insufficient_data`). The flag is on the deciding sector, so one
member without a decline-store verdict marks every name in that sector.

FTSE buy-tier counts stayed 62 sound, 2 headwind, 1 `insufficient_data`. No
FTSE verdict string changed, and no FTSE name used the earnings-growth
fallback. `AEP.L` (Agriculture/Commodities, buy tier) and `ALW.L` (Closed
End Investments) are `sector_basis: regional` and still `insufficient_data`,
because each label has one member in the whole `uk` group.

## Automation and findings

Daily ops-monitor refreshes `check_operating_decline_gate` first, then calls
`check_sector_headwind_gate`, so the sector gate consumes the newly refreshed
per-name verdicts. It emits:

- **Sector headwind gate refreshed (observe)** with verdict counts, named
  headwind sectors and buy-tier exposure.
- **Sector headwind gate coverage gap** when an FTSE sector containing a
  buy-tier name is `insufficient_data`, and when a library market's buy-tier
  sectors are mostly `insufficient_data`. The finding names the FTSE sector
  and the library markets. It does not list every library sector.
- **Sector headwind gate refresh failed** if committed inputs cannot be read.
- **Sector headwind gate fallback reliance (observe)** with buy-tier counts
  by `sector_basis` (own-market vs regional) and by `earnings_fallback_used`,
  split by verdict. A rise in either fallback is the signal-risk line. It
  does not rememo, ingest, or fetch.

All findings have `auto_fixable=False`. Manual drill-down:

```bash
ftse-sector-headwind-gate
ftse-sector-headwind-gate --sector dax:Industrials --json
```

A bare sector name works only when one scored market uses it. Otherwise pass
the `market:sector` key.

## Constraints and later use

This instrument never edits screen signals, books, fills, rankings, knobs or
paper automation. It makes no network calls. It is not an entry veto and not a
sell instruction.

After the owner accepts the existing Phase 1 strategy gate, a future cold-start
strategy book may use the verdict as an entry filter. The same accepted gate
may later become a thesis-break trigger for recovery holds. Neither use is
enabled by v0.
