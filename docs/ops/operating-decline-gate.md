# Operating-decline gate (observe)

**deferred:** N250  
**Strategy part served:** part 2, "not declining" ([`PROJECT_OBJECTIVE.md`](../PROJECT_OBJECTIVE.md#investment-strategy-owner-2026-11-03); plan step 1.1 in [`strategy-reorientation-plan.md`](strategy-reorientation-plan.md))  
**Mode:** observe-only. `influences_live` is false. Never edits signals, books, knobs, `max_positions`, `sector_cap` or `decision-review --apply`. Never writes `docs/data/paper_automation`.  
**Code:** `src/value_investor/operating_decline_gate.py`, CLI `ftse-operating-decline-gate`  
**Store:** `docs/data/operating_decline_gate.json`

## Learning question

For each name in the FTSE 350 screen (and admitted library markets where the same inputs exist), can we produce a cited, point-in-time-safe verdict of whether operating performance is declining, with coverage of every FTSE buy-tier name?

The gate answers one thing: is the business getting worse? It does not say whether the price is cheap or low. That is why a name can pass every value screen and still be `declining`.

## Verdicts

| Verdict | Meaning |
|---|---|
| `clear` | Enough data to judge, and no hard check and fewer than two soft checks fired. A single soft signal is still listed in `reasons`. |
| `declining` | Any hard check fired, or two or more soft checks fired. |
| `insufficient_data` | No adverse signal fired, and either revenue or (operating margin and EPS) could not be computed. Missing data never passes. |

Adverse evidence always wins: a profit warning on a name with no financials is `declining`, not `insufficient_data`.

## Checks and thresholds (v0)

Constants are at the top of the module. Annual figures come from the latest reported fiscal year against the consecutive prior year.

| Check | Reason code | Fires when | Strength |
|---|---|---|---|
| Revenue | `revenue_decline` | Latest annual revenue is more than 5% below the prior year | hard |
| Revenue | `revenue_two_year_decline` | Two consecutive annual declines, each worse than 1% | hard |
| Interim revenue | `interim_revenue_decline` | Latest interim revenue is more than 5% below the same period a year earlier (`INTERIM_REVENUE_DROP_PCT` = `REVENUE_DROP_PCT`) | hard |
| Operating margin | `operating_margin_drop` | Operating income / revenue fell by more than 3 percentage points | hard |
| FCF | `fcf_turned_negative` | Latest annual free cash flow negative after a positive year | hard |
| Profit warning | `profit_warning` | A filings headline or summary in the last 180 days says profit warning, guidance cut / lowered guidance, or a trading update / statement below expectations | hard |
| EPS (annual) | `eps_decline_annual` | Diluted EPS (basic if missing) fell more than 20% from a positive prior year, or turned negative | soft |
| EPS (interim) | `eps_decline_interim` | Latest interim EPS is at least 10% below the same period a year earlier (`EPS_INTERIM_DROP_PCT`) | soft |
| FCF | `fcf_sharp_fall` | Latest FCF is more than 50% below a positive prior year | soft |
| Dividend | `dividend_cut` | Screen row `interim_dividend_cut_flagged` is true | soft |
| Headlines | `impairment_or_downgrade` | A headline in the last 180 days mentions an impairment or a downgrade | soft |

Two soft signals together make a name `declining`. Hard checks are the ones that are hard to explain away as noise (a sales drop beyond 5%, margin compression, cash turning negative, the company itself warning). Soft checks are common one-offs (a write-down, a single weak half).

Each check compares every year on one row label. The label is the first in the preference list that has a finite value for the newest year and the prior year (revenue also uses the year before when present), and it is recorded as `label` on the check. Labels are never mixed across years: if none spans both years, the check is not evaluable.

| Check | Preference order |
|---|---|
| Revenue | `Total Revenue`, `Operating Revenue` |
| Operating income (margin) | `Operating Income`, `Total Operating Income As Reported`, `EBIT`, each over the revenue label order |
| EPS | `Diluted EPS`, `Basic EPS` |
| FCF | `Free Cash Flow`, then operating cash flow plus capital expenditure |
| Interim revenue | `Total Revenue`, `Operating Revenue`, `Revenue` on the latest interim period |
| Interim EPS | `Diluted EPS`, `Basic EPS`, then filing-interim adjusted EPS, then statutory EPS |

FCF is never taken direct for one year and derived for another. Banks and insurers often lack operating income; they stay evaluable on EPS.

Interim comparisons are year-on-year. The latest interim period is the newest `quarterly_income` period end on or before `as_of` that carries revenue or EPS. The prior period is the one within 45 days of that date minus one year. The same label has to be present on both periods. The adjacent quarter is not the comparison. If the latest period has revenue but no EPS, EPS does not slide back to an older quarter.

Interim EPS keeps a single slot. The first evaluable source replaces the others, so the screen-row flag is not counted again when a direct measurement exists:

1. Usable `quarterly_income` year-on-year pair.
2. `filing_interim_financials.json` `interim_highlights` adjusted EPS pair, else the statutory EPS pair, when the source filing is dated on or before `as_of`.
3. `parse_interim_eps_decline_pct` on the latest dated half-year / interim-results body (`period` = `interim`, results headline, published on or before `as_of`).
4. Screen-row `interim_eps_decline_pct`, when the screen run is dated on or before `as_of`.

A filing published more than 460 days before `as_of` is not used. Trading-update advertising revenue in the filing-interim file is not treated as group revenue.

## Inputs (committed files only, no network)

| Input | Path | Used for |
|---|---|---|
| Screen rows | `docs/data/latest.json` `reports` | signal, sector, `interim_eps_decline_pct` (fallback), `interim_dividend_cut_flagged` |
| Annual statements | `docs/data/research/{TICKER}/sources/financials_annual.json` | revenue, operating income, EPS, FCF by fiscal year; `quarterly_income` for interim year-on-year |
| Filing interim extract | `docs/data/research/{TICKER}/sources/filing_interim_financials.json` | interim EPS pair in `interim_highlights` when the source filing is dated |
| Filings index and bodies | `docs/data/research/{TICKER}/sources/filings/` | headline and summary scan; half-year results bodies for the interim EPS prose parser |
| Library markets | `docs/data/library/markets/{market}/screen/latest_signals.csv` and `screen/research/{TICKER}/sources/` | same statements, extract and index; no interim fields on library rows |

Scope in v0: every FTSE 350 screen row (`market` = `ftse350`), plus every admitted library market name that has a `financials_annual.json` under its research sources (about 525 names across 21 markets). Library names without research sources are not scored. If a ticker appears in both, the FTSE row wins. Buy-tier means `buy` or `strong_buy`; the summary counts FTSE names only.

Only about 108 of 248 FTSE names have a filings index, so the profit-warning check is evaluated for those names only. That check matches headlines and summaries, not bodies. Third-party news items (index `source` starting `google_news`) are skipped because they often describe other companies. Expect low recall on warnings until a wider body scan is added. Interim EPS does read one half-year results body per name, and only through the existing decline parser.

## Point in time

- `as_of` defaults to today (UTC). Use `--as-of YYYY-MM-DD` to re-judge a past date.
- Profit-warning filings dated after `as_of`, undated filings, and filings older than 180 days are ignored.
- Interim periods and half-year filings dated after `as_of` are ignored. An interim period end, or a results filing published more than 460 days before `as_of`, is stale and is not a comparison.
- Fiscal years after the `as_of` year are ignored. A statement file fetched after `as_of` is not usable (the file may contain restated or later-reported data), so annual checks and the quarterly series inside that file fail closed (`why: financials_fetched_after_as_of`).
- Screen-row flags (`interim_*`) are dropped when the `latest.json` run is dated after `as_of`. A direct interim measurement replaces the screen-row EPS flag; the flag is the fallback when no direct comparison exists.
- Annual data more than one fiscal year old (two in January to March) is treated as stale.

Because statement files are overwritten on each fetch, a past `as_of` is mainly useful against archived trees. Real historical replay needs dated snapshots of the statements (plan step 2.2).

## Store

`docs/data/operating_decline_gate.json`:

```text
{ schema_version: 2, generated_at, as_of, observe_only: true, influences_live: false,
  learning_question,
  summary: { names, clear, declining, insufficient_data, buy_tier_names, buy_tier_covered,
             names_with_interim_eps, names_with_interim_revenue, latest_fiscal_year_counts },
  names: { TICKER: { market, sector, signal, verdict,
                     reasons: [ {code, detail, source} ],
                     checks: { revenue, interim_revenue, operating_margin, eps_annual,
                               eps_interim, fcf, dividend, profit_warning } } } }
```

`buy_tier_covered` counts FTSE buy-tier names whose verdict is `clear` or `declining`. `names_with_interim_eps` and `names_with_interim_revenue` count names with a year-on-year comparison from any interim source, not only the screen row. `latest_fiscal_year_counts` maps the latest fiscal year used for revenue to the number of names, so stale statements are visible. Name records still carry `verdict`, `market`, `sector`, `reasons` and `checks`. The sector headwind gate reads `names[].verdict`. `schema_version` is 2 because interim revenue is a check and the summary gained `names_with_interim_revenue`.

Each check carries `evaluable`, `fired`, and `strength` (when evaluable) or `why` (when not), plus the numbers it used. The store is about 750 KB because it keeps every check for every name. Raw store JSON commits with ops-monitor.

## Ops findings

Daily `collect_ops_findings` calls `check_operating_decline_gate` (before the observe-instrument block). All findings are `auto_fixable=False`.

| Title | Severity | When |
|---|---|---|
| **Operating-decline gate refreshed (observe)** | info | Every run: counts, FTSE buy-tier coverage, the first five buy-tier names flagged `declining` with reason codes, names with interim EPS and interim revenue, and the latest-fiscal-year spread |
| **Operating-decline gate coverage gap** | warn | Fewer than 80% of FTSE buy-tier names have a `clear` or `declining` verdict, or no buy-tier names were scored |
| **Operating-decline gate failed** | warn | The refresh raised (unreadable inputs) |

A coverage gap is an input-quality signal for P1 (annual statements missing for buy-tier names). It does not trigger rememo or ingest spray by itself.

## CLI

```bash
ftse-operating-decline-gate                       # refresh and persist, print summary
ftse-operating-decline-gate --no-persist          # score without writing
ftse-operating-decline-gate --ticker SHEL.L       # reasons and per-check numbers (read-only)
ftse-operating-decline-gate --as-of 2026-09-30    # point-in-time re-judgement
ftse-operating-decline-gate --json                # full store to stdout
```

`--output-dir` (default `docs/data`) points at a tree holding `latest.json`, `research/` and `library/`; `--store` overrides the store path.

## Constraints and later use

- Observe-only. Nothing reads this verdict to size, buy, sell or hold until an owner phase gate says so.
- Never edits books or knobs; never calls the network.
- Later use, after the Phase 1 owner gate in the plan: (1) entry filter for the strategy book (only `clear` names are bought); (2) thesis-break trigger for a recovery hold (a held name that turns `declining` ends the hold). The same function serves both, so the hold rule and the entry rule cannot drift apart.
- Thresholds are v0 defaults. The owner may adjust them once at the Phase 1 gate (logged); do not tune them against outcomes in between.

## Interim coverage diagnosis (FTSE buy-tier)

Counted on the 65 `buy` / `strong_buy` rows in `docs/data/latest.json` (run `2026-11-01`), as of `2026-11-03`. All 65 have `financials_annual.json` and a filings index. The classes overlap.

| What is on disk | Names | What a year-on-year check can use |
|---|---:|---|
| `quarterly_income` usable (an EPS or revenue line) | 8 | Nothing yet. Each series is 4 period-ends and none sits within 45 days of a year before the latest. Tickers: IAG, BGEO, GSK, ATYM, SHEL, NWG, BARC, BP |
| `quarterly_income` empty | 57 | No Yahoo interim series |
| `quarterly_income` present but no EPS or revenue label | 0 | — |
| `filing_interim_financials.json` present | 9 | `interim_highlights` is empty on all 9. ITV alone has trading-update advertising revenue (1,247 vs 1,313). The stored `change_pct` is -66, the £m gap, not a percent. The same update says group revenue +2% YTD, so the gate does not treat advertising revenue as interim group revenue |
| `filing_interim_financials.json` absent | 56 | No committed interim extract |
| Dated half-year / interim-results body | 48 | The existing EPS-decline parser matches 2: MEGP 3.9% (published 2026-07-13, period 2026-04-30) and DNLM 7.3% (published 2026-02-10, period 2025-12-27). Both were already on the screen row and both are under the 10% soft bar |
| Dated `period=interim` body that is not a results headline | 11 | Not read as a results body |
| No dated interim body | 6 | EZJ, IMB, TW, BARC, BKG, BP. BARC and BP still have the short Yahoo series above |

Three of 248 FTSE screen rows carry `interim_eps_decline_pct` (MEGP, DNLM, and PETS, which is `hold`). The statutory highlights parser also matches the ITV half-year body (adjusted EPS 2.2p vs 1.8p), but that extract is not in the committed JSON: the index `body_path` points at `output/research/...` while the file sits under `filings/bodies/` by basename.

After this gate reads those sources, FTSE buy-tier interim coverage is unchanged: EPS 2/65 (the same two names, now cited from the results body) and revenue 0/65. Across all scored names, interim EPS comparisons went from 3 to 26 and interim revenue from 0 to 27, almost all from library `quarterly_income` series that already hold a prior-year period. Four non-buy FTSE names already have that prior-year quarter (TBCG, STAN, ITH, ENOG).

## Known limitations

- **Buy-tier interim coverage is still annual.** The gate now reads interim sources, and the buy-tier set still has no year-on-year revenue pair and only two EPS comparisons, neither of which fires. Most verdicts rest on annual statements. The ingest follow-up is below, not a new job in this instrument.
- **Revenue hard checks flag commodity and cyclical names in a down year** (for example oil majors). That matches the owner's "no operating decline" rule but is a known false-positive source for a recovery thesis. The owner decides at the Phase 1 gate whether to adjust.
- **Headline scan covers only names with a filings index** (about 108 of 248 FTSE names), matches headlines and summaries only, and skips third-party news. Expect low recall on profit warnings.
- **Statements are overwritten on fetch**, so a past `as_of` fails closed (`financials_fetched_after_as_of`) against current files. Real historical replay needs dated snapshots. The same overwrite is why Yahoo `quarterly_income` keeps about four recent periods and drops the quarter a year earlier.

## Ingest follow-up (not built here)

No new fetch and no change to how the screen computes `interim_eps_decline_pct`.

1. **Keep the prior-year quarter in `quarterly_income`.** 19 of 248 FTSE names have a usable series; 4 already contain a same-period prior year, and none of those 4 are buy-tier. Storing that missing quarter would make interim revenue evaluable for the 8 buy-tier names above. Interim EPS would follow for 6 of the 8: BGEO and NWG have no EPS line on the latest quarter, so a longer history does not score EPS until that quarter carries one.
2. **Resolve half-year body paths and re-extract `filing_interim_financials.json`.** Index paths under `output/research/` miss bodies that exist as `filings/bodies/<basename>`. Re-running the current statutory highlights parser after that fix picks up ITV's EPS pair (a rise, so the soft check would not fire) and, on this buy-tier set, no other results body. It still does not extract revenue.
3. **Structured current-vs-prior revenue and EPS from the 48 buy-tier half-year results bodies.** That is the coverage ceiling for names Yahoo does not quarter. The prose parsers already in the repo match two EPS declines, both under 10%. A broader extractor has to return levels for one period and the same period a year earlier; a loose "revenue down N%" phrase match is not that. Expected gain is up to those 48 names, and the yield is unproven until the parser is written.
