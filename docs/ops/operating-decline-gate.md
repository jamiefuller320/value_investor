# Operating-decline gate (observe)

**deferred:** N250  
**Strategy part served:** part 2, "not declining" ([`PROJECT_OBJECTIVE.md`](../PROJECT_OBJECTIVE.md#investment-strategy-owner-2026-11-03); plan step 1.1 in [`strategy-reorientation-plan.md`](strategy-reorientation-plan.md))  
**Mode:** observe-only. `influences_live` is false. Never edits signals, books, knobs, `max_positions`, `sector_cap` or `decision-review --apply`. Never writes `docs/data/paper_automation`.  
**Code:** `src/value_investor/operating_decline_gate.py`, CLI `ftse-operating-decline-gate`  
**Store:** `docs/data/operating_decline_gate.json`  
**Quarterly history:** [`quarterly-history.md`](quarterly-history.md) — how `quarterly_income` keeps the prior-year quarter

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
| Interim revenue | `Total Revenue`, `Operating Revenue`, `Revenue` on the latest interim period, then the half-year filing extract |
| Interim EPS | Filing adjusted EPS (half-year extract, then highlights), then `Diluted EPS`, `Basic EPS`, then filing statutory EPS (half-year extract diluted, basic, statutory, then highlights) |

FCF is never taken direct for one year and derived for another. Banks and insurers often lack operating income; they stay evaluable on EPS.

Interim comparisons are year-on-year. The latest interim period is the newest `quarterly_income` period end on or before `as_of` that carries revenue or EPS. The prior period is the one within 45 days of that date minus one year. The same label has to be present on both periods. The adjacent quarter is not the comparison. If the latest period has revenue but no EPS, EPS does not slide back to an older quarter.

Interim EPS keeps a single slot. The first evaluable source replaces the others, so the screen-row flag is not counted again when a direct measurement exists:

Adjusted EPS comes first (owner, 2026-11-05): statutory EPS carries one-off charges and gains, which can mark a business as declining when its underlying earnings grew (Rank on 2026-11-05: statutory basic EPS −25%, underlying +17%).

1. Adjusted EPS from a filing: `half_year_comparisons` adjusted (or underlying) pair, then the `interim_highlights` adjusted pair.
2. Usable `quarterly_income` year-on-year pair (diluted, then basic). Yahoo carries no adjusted EPS.
3. Statutory EPS from a filing: `half_year_comparisons` diluted, then basic, then statutory; then the `interim_highlights` statutory pair.
4. `parse_interim_eps_decline_pct` on the latest dated half-year / interim-results body (`period` = `interim`, results headline, published on or before `as_of`).
5. Screen-row `interim_eps_decline_pct`, when the screen run is dated on or before `as_of`.

The `interim_highlights` pairs count only when that extract's `extracted_at` and the source filing are both dated on or before `as_of`.

Interim revenue uses the quarterly series first. When that comparison is not evaluable (missing, no prior-year quarter, stale, or a non-positive prior), the gate uses the revenue pair on the same half-year extract. The threshold is the same 5% hard bar. A quarterly comparison that is evaluable is kept even when the filing says something else.

A filing published more than 460 days before `as_of`, or whose half-year period end is more than 460 days before `as_of`, is not used. Trading-update advertising revenue in the filing-interim file is not treated as group revenue.

## Half-year extract

UK companies report half-yearly, and the Yahoo quarterly series is empty for most of them. The text already on disk is the source. Each daily gate refresh re-reads half-year results bodies and writes `filing_interim_financials.json` before it scores, so a body ingested overnight is in the next verdict without a separate command. A read-only refresh (`--no-persist`) parses the same bodies in memory and does not write the file. The extract is refreshed inside the gate step, rather than only during ingest, because most of the bodies were already on disk before this parser existed and ingest does not re-run them every day.

`interim_highlights` is unchanged: it is still the narrow free-cash-flow / adjusted-EPS / statutory-EPS prose parse. The new figures live beside it:

| Key | Meaning |
|---|---|
| `half_year_comparisons` | One record per half-year results row (newest publication first), including rows that were not extracted and why |
| `half_year_comparison` | The newest record whose status is `extracted`, or null. The gate does not trust this alone: it re-selects from the list using `as_of` |

A row counts as a half-year results filing when `period` is `interim`, `has_body` is set, the headline or URL contains interim results, interim report, half-year, half year, half-yearly or half yearly, and the source is not third-party news. Companies House "accounts-with-accounts-type-interim" rows without those words are not parsed.

The body file is resolved in one place (`resolve_filing_body_path_for_row`), used by the extract and by the gate's older prose reader:

1. `filings/bodies/<basename of body_path>` (index paths often say `output/research/...`, which is not in the repo)
2. the stored `body_path`, if that file exists
3. `filings/bodies/<id>.txt`

For each extracted record the file stores: current half period end, prior-year half period end, whether that prior date was stated or inferred as one year earlier, revenue current and prior with the label used (Group revenue, Total revenue, Revenue, Turnover and the close variants), unit and currency, each EPS pair (diluted, basic, adjusted, statutory) with its label, unit and currency, the filing id, `published_at`, a short snippet of the matched line, and `parse_confidence` (`high` when both period ends are stated, `medium` when the prior date is inferred).

Fail closed. The status is `not_extracted` when any of these is true:

- current and prior figures are not both present
- the prior period is not about one year before the current period (within 45 days)
- revenue is not positive
- the column order is not explicit (no H1 / HY / six-months year pair one year apart, or the header mixes quarters and a half-year)
- a group total and a segment line disagree, or two readings of the same label disagree by more than 0.5%
- the period end is after the filing's publication date

Segment lines (advertising, studios, UK retail and the same sort of prefix) are dropped when a group total is present. A bare "customers 1 to 2" style line is not revenue. The gate then applies its own point-in-time rules: `published_at` on or before `as_of`, and neither the publication nor the period end older than 460 days. If the newest filing that passes those rules was not extracted, an older half is not used. A missing extract is not evaluable. It is never a pass.

## Inputs (committed files only, no network)

| Input | Path | Used for |
|---|---|---|
| Screen rows | `docs/data/latest.json` `reports` | signal, sector, `interim_eps_decline_pct` (fallback), `interim_dividend_cut_flagged` |
| Annual statements | `docs/data/research/{TICKER}/sources/financials_annual.json` | revenue, operating income, EPS, FCF by fiscal year; `quarterly_income` for interim year-on-year |
| Filing interim extract | `docs/data/research/{TICKER}/sources/filing_interim_financials.json` | `half_year_comparisons` for interim revenue and EPS; `interim_highlights` EPS pair when the half-year extract has no EPS |
| Filings index and bodies | `docs/data/research/{TICKER}/sources/filings/` | headline and summary scan; half-year results bodies, re-read on each gate refresh |
| Library markets | `docs/data/library/markets/{market}/screen/latest_signals.csv` and `screen/research/{TICKER}/sources/` | same statements, extract and index; no interim fields on library rows |

Scope in v0: every FTSE 350 screen row (`market` = `ftse350`), plus every admitted library market name that has a `financials_annual.json` under its research sources (about 525 names across 21 markets). Library names without research sources are not scored. If a ticker appears in both, the FTSE row wins. Buy-tier means `buy` or `strong_buy`; the summary counts FTSE names only.

Only about 108 of 248 FTSE names have a filings index, so the profit-warning check is evaluated for those names only. That check matches headlines and summaries, not bodies. Third-party news items (index `source` starting `google_news`) are skipped because they often describe other companies. Expect low recall on warnings until a wider body scan is added. Interim revenue and interim EPS also read the half-year results bodies, through `half_year_comparisons` on the filing-interim extract. The older prose decline parser remains the fallback when that extract has no EPS pair.

## Point in time

- `as_of` defaults to today (UTC). Use `--as-of YYYY-MM-DD` to re-judge a past date.
- Profit-warning filings dated after `as_of`, undated filings, and filings older than 180 days are ignored.
- Interim periods and half-year filings dated after `as_of` are ignored. An interim period end, or a results filing published more than 460 days before `as_of`, is stale and is not a comparison. `extracted_at` on the filing-interim file is when the parser ran, not when the company reported. Half-year rows are kept and selected by `published_at`. The older `interim_highlights` pair still fails closed when `extracted_at` is after `as_of`.
- Fiscal years after the `as_of` year are ignored. A statement file fetched after `as_of` is not usable (the file may contain restated or later-reported data), so annual checks and the quarterly series inside that file fail closed (`why: financials_fetched_after_as_of`).
- Screen-row flags (`interim_*`) are dropped when the `latest.json` run is dated after `as_of`. A direct interim measurement replaces the screen-row EPS flag; the flag is the fallback when no direct comparison exists.
- Annual data more than one fiscal year old (two in January to March) is treated as stale.

Because statement files are overwritten on each fetch, a past `as_of` is mainly useful against archived trees. Real historical replay needs dated snapshots of the statements (plan step 2.2).

## Store

`docs/data/operating_decline_gate.json`:

```text
{ schema_version: 3, generated_at, as_of, observe_only: true, influences_live: false,
  learning_question,
  summary: { names, clear, declining, insufficient_data, buy_tier_names, buy_tier_covered,
             names_with_interim_eps, names_with_interim_revenue,
             buy_tier_with_interim_revenue, buy_tier_with_interim_eps,
             latest_fiscal_year_counts },
  names: { TICKER: { market, sector, signal, verdict,
                     reasons: [ {code, detail, source} ],
                     checks: { revenue, interim_revenue, operating_margin, eps_annual,
                               eps_interim, fcf, dividend, profit_warning } } } }
```

`buy_tier_covered` counts FTSE buy-tier names whose verdict is `clear` or `declining`. `names_with_interim_eps` and `names_with_interim_revenue` count names with a year-on-year comparison from any interim source, not only the screen row. `buy_tier_with_interim_revenue` and `buy_tier_with_interim_eps` are those same counts restricted to FTSE `buy` / `strong_buy` names. `latest_fiscal_year_counts` maps the latest fiscal year used for revenue to the number of names, so stale statements are visible. Name records still carry `verdict`, `market`, `sector`, `reasons` and `checks`. The sector headwind gate reads `names[].verdict`. `schema_version` is 3 because the summary gained the two buy-tier interim counts.

Each check carries `evaluable`, `fired`, and `strength` (when evaluable) or `why` (when not), plus the numbers it used. The store is about 750 KB because it keeps every check for every name. Raw store JSON commits with ops-monitor.

## Ops findings

Daily `collect_ops_findings` calls `check_operating_decline_gate` (before the observe-instrument block). All findings are `auto_fixable=False`.

| Title | Severity | When |
|---|---|---|
| **Operating-decline gate refreshed (observe)** | info | Every run: counts, FTSE buy-tier coverage, the first five buy-tier names flagged `declining` with reason codes, names with interim EPS and interim revenue, the buy-tier-only interim counts, and the latest-fiscal-year spread |
| **Operating-decline gate coverage gap** | warn | Fewer than 80% of FTSE buy-tier names have a `clear` or `declining` verdict, or no buy-tier names were scored |
| **Operating-decline gate interim revenue coverage** | warn | At least 20 FTSE buy-tier names are scored and fewer than 45% of them have an evaluable interim revenue comparison. The 2026-11-05 backfill reached 30/65 (46%). The floor sits just under that, so a later drop is visible. It does not fire on a small fixture. |
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
| `quarterly_income` usable (an EPS or revenue line) | 8 | 4 now have a same-quarter prior year and evaluable interim revenue, none of which fires: GSK +4.0%, SHEL +36.2%, BARC +2.8%, BP +41.3% (period 2026-09-30 vs 2025-09-30). The latest quarter on those four has no EPS line. IAG, BGEO, ATYM and NWG still have no period within 45 days of a year before the latest; git history never stored that quarter |
| `quarterly_income` empty | 57 | No Yahoo interim series |
| `quarterly_income` present but no EPS or revenue label | 0 | — |
| `filing_interim_financials.json` present | 9 | `interim_highlights` is empty on all 9. ITV alone has trading-update advertising revenue (1,247 vs 1,313). The stored `change_pct` is -66, the £m gap, not a percent. The same update says group revenue +2% YTD, so the gate does not treat advertising revenue as interim group revenue |
| `filing_interim_financials.json` absent | 56 | No committed interim extract |
| Dated half-year / interim-results body | 48 | The existing EPS-decline parser matches 2: MEGP 3.9% (published 2026-07-13, period 2026-04-30) and DNLM 7.3% (published 2026-02-10, period 2025-12-27). Both were already on the screen row and both are under the 10% soft bar |
| Dated `period=interim` body that is not a results headline | 11 | Not read as a results body |
| No dated interim body | 6 | EZJ, IMB, TW, BARC, BKG, BP. BARC and BP still have the short Yahoo series above |

Three of 248 FTSE screen rows carry `interim_eps_decline_pct` (MEGP, DNLM, and PETS, which is `hold`). The statutory highlights parser also matches the ITV half-year body (adjusted EPS 2.2p vs 1.8p), but that extract is not in the committed JSON: the index `body_path` points at `output/research/...` while the file sits under `filings/bodies/` by basename.

Before the quarterly backfill, FTSE buy-tier interim coverage was EPS 2/65 (MEGP and DNLM, from the results body) and revenue 0/65. Across all scored names it was interim EPS 26 and interim revenue 27. Four non-buy FTSE names already had a prior-year quarter (TBCG, STAN, ITH, ENOG).

After `ftse-quarterly-backfill --apply` (git history, current values kept) and a gate refresh as of 2026-11-03: FTSE buy-tier interim revenue is 4/65 and interim EPS is still 2/65. FTSE screen interim revenue is 8/248 and interim EPS is 6/248. Across all scored names, interim revenue and interim EPS are both 68. Buy-tier covered stays 62/65. No FTSE verdict changed. Two library names did: FSLR (sp500, `clear` → `declining`) on interim revenue −22.8% for 2026-09-30 vs 2025-09-30, and HRL (sp500, `clear` → `declining`) because interim EPS −66.7% joined an existing annual EPS decline. Store counts moved from clear 549 / declining 191 to clear 547 / declining 193. Details: [`quarterly-history.md`](quarterly-history.md).

After the half-year extract backfill and a gate refresh as of 2026-11-05, on the same 65 FTSE buy-tier names:

| Check | Before | After | Still not evaluable |
|---|---:|---:|---|
| Interim revenue | 4 (all Yahoo `quarterly_income`) | 30 (26 from the half-year extract, 4 still Yahoo) | 35: 31 `interim_revenue_missing`, 4 `interim_prior_period_missing` |
| Interim EPS | 2 (half-year prose) | 33 (all from the half-year extract) | 32: 25 `interim_eps_not_on_screen_row`, 4 `interim_metric_missing_on_latest_period`, 3 `interim_prior_period_missing` |

None of the 30 buy-tier interim revenue pairs fell by more than 5%. Eight buy-tier interim EPS pairs fell by at least 10% (ABF, BREE, FGP, FOUR, GEN, IAG, RNK, VCT). Across every scored name, interim revenue is evaluable on 131 and interim EPS on 138. Buy-tier covered stays 62/65. The 45% interim-revenue floor is just under the 30/65 (46%) this run reached, so the coverage finding does not fire today.

## Known limitations

- **Buy-tier interim coverage is still short of the names that have a results body.** 30 of 65 buy-tier names now have a year-on-year interim revenue pair and 33 have interim EPS. The rest fail closed: the body has no explicit current-and-prior pair, the column order is ambiguous, or there is no half-year results body. None of the new revenue pairs fire. Eight EPS pairs do. Most verdicts still rest on annual statements.
- **Revenue hard checks flag commodity and cyclical names in a down year** (for example oil majors). That matches the owner's "no operating decline" rule but is a known false-positive source for a recovery thesis. The owner decides at the Phase 1 gate whether to adjust.
- **Headline scan covers only names with a filings index** (about 108 of 248 FTSE names), matches headlines and summaries only, and skips third-party news. Expect low recall on profit warnings.
- **`fetched_at` still moves on a live fetch**, so a past `as_of` fails closed (`financials_fetched_after_as_of`) against current files. Real historical replay needs dated snapshots. Quarterly income and cash flow are no longer replaced wholesale: each fetch merges period ends and keeps up to 12 quarters. See [`quarterly-history.md`](quarterly-history.md).

## Ingest follow-up

No new Yahoo fetch and no change to how the screen computes `interim_eps_decline_pct`.

1. **Keep the prior-year quarter in `quarterly_income`.** Built. The writer merges up to 12 quarters, and `ftse-quarterly-backfill` restored older period ends from git. That made interim revenue evaluable for GSK, SHEL, BARC and BP. It did not make interim EPS evaluable for them: the latest quarter has revenue and no EPS line. IAG, BGEO, ATYM and NWG still lack the prior-year quarter because no committed version of the file contains it (their latest period is 2026-06-30 and the oldest committed period is 2025-09-30). Runbook: [`quarterly-history.md`](quarterly-history.md).
2. **Resolve half-year body paths.** Built. `resolve_filing_body_path_for_row` looks in `filings/bodies/<basename>` and `filings/bodies/<id>.txt` before trusting a stored `output/research/...` path. The decline gate uses that same function. ITV's half-year body is found by basename.
3. **Structured current-vs-prior revenue and EPS from half-year results bodies.** Built. `half_year_comparisons` in `filing_interim_financials.json` holds the pair, the label, the unit, the filing id and the matched line. The daily gate refresh writes that file before it scores. Coverage after the 2026-11-05 backfill is in the diagnosis section below. A figure that fails the sanity rules stays `not_extracted`. It is not guessed.
