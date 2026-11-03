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
| Operating margin | `operating_margin_drop` | Operating income / revenue fell by more than 3 percentage points | hard |
| FCF | `fcf_turned_negative` | Latest annual free cash flow negative after a positive year | hard |
| Profit warning | `profit_warning` | A filings headline or summary in the last 180 days says profit warning, guidance cut / lowered guidance, or a trading update / statement below expectations | hard |
| EPS (annual) | `eps_decline_annual` | Diluted EPS (basic if missing) fell more than 20% from a positive prior year, or turned negative | soft |
| EPS (interim) | `eps_decline_interim` | Screen row `interim_eps_decline_pct` is at least 10% | soft |
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

FCF is never taken direct for one year and derived for another. Banks and insurers often lack operating income; they stay evaluable on EPS.

## Inputs (committed files only, no network)

| Input | Path | Used for |
|---|---|---|
| Screen rows | `docs/data/latest.json` `reports` | signal, sector, `interim_eps_decline_pct`, `interim_dividend_cut_flagged` |
| Annual statements | `docs/data/research/{TICKER}/sources/financials_annual.json` | revenue, operating income, EPS, FCF by fiscal year |
| Filings index | `docs/data/research/{TICKER}/sources/filings/filings_index.json` | headline and summary scan (bodies are not read) |
| Library markets | `docs/data/library/markets/{market}/screen/latest_signals.csv` and `screen/research/{TICKER}/sources/` | same statements and index; no interim fields on library rows |

Scope in v0: every FTSE 350 screen row (`market` = `ftse350`), plus every admitted library market name that has a `financials_annual.json` under its research sources (about 525 names across 21 markets). Library names without research sources are not scored. If a ticker appears in both, the FTSE row wins. Buy-tier means `buy` or `strong_buy`; the summary counts FTSE names only.

Only about 108 of 248 FTSE names have a filings index, so the profit-warning check is evaluated for those names only. Headlines are matched, not bodies. Third-party news items (index `source` starting `google_news`) are skipped because they often describe other companies. Expect low recall on warnings until body scanning is added.

## Point in time

- `as_of` defaults to today (UTC). Use `--as-of YYYY-MM-DD` to re-judge a past date.
- Filings dated after `as_of`, undated filings, and filings older than 180 days are ignored.
- Fiscal years after the `as_of` year are ignored. A statement file fetched after `as_of` is not usable (the file may contain restated or later-reported data), so the name fails closed to `insufficient_data` with `why: financials_fetched_after_as_of`.
- Screen-row flags (`interim_*`) are dropped when the `latest.json` run is dated after `as_of`.
- Annual data more than one fiscal year old (two in January to March) is treated as stale.

Because statement files are overwritten on each fetch, a past `as_of` is mainly useful against archived trees. Real historical replay needs dated snapshots of the statements (plan step 2.2).

## Store

`docs/data/operating_decline_gate.json`:

```text
{ schema_version: 1, generated_at, as_of, observe_only: true, influences_live: false,
  learning_question,
  summary: { names, clear, declining, insufficient_data, buy_tier_names, buy_tier_covered,
             names_with_interim_eps, latest_fiscal_year_counts },
  names: { TICKER: { market, sector, signal, verdict,
                     reasons: [ {code, detail, source} ],
                     checks: { revenue, operating_margin, eps_annual, eps_interim,
                               fcf, dividend, profit_warning } } } }
```

`buy_tier_covered` counts FTSE buy-tier names whose verdict is `clear` or `declining`. `names_with_interim_eps` counts names with an interim EPS comparison on the screen row. `latest_fiscal_year_counts` maps the latest fiscal year used for revenue to the number of names, so stale statements are visible. The sector headwind gate reads this file; keep the keys stable and bump `schema_version` for any change.

Each check carries `evaluable`, `fired`, and `strength` (when evaluable) or `why` (when not), plus the numbers it used. The store is about 750 KB because it keeps every check for every name. Raw store JSON commits with ops-monitor.

## Ops findings

Daily `collect_ops_findings` calls `check_operating_decline_gate` (before the observe-instrument block). All findings are `auto_fixable=False`.

| Title | Severity | When |
|---|---|---|
| **Operating-decline gate refreshed (observe)** | info | Every run: counts, FTSE buy-tier coverage, the first five buy-tier names flagged `declining` with reason codes, names with interim EPS, and the latest-fiscal-year spread |
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

## Known limitations

- **Mostly annual-only.** Interim data is thin (only a handful of FTSE screen rows carry `interim_eps_decline_pct`; see `names_with_interim_eps`). Most verdicts rest on annual statements that can lag by up to a year, so fresh deterioration shows first through headlines. Interim ingestion is a P1 follow-up, not part of this instrument.
- **Revenue hard checks flag commodity and cyclical names in a down year** (for example oil majors). That matches the owner's "no operating decline" rule but is a known false-positive source for a recovery thesis. The owner decides at the Phase 1 gate whether to adjust.
- **Headline scan covers only names with a filings index** (about 108 of 248 FTSE names), matches headlines and summaries only, and skips third-party news. Expect low recall on profit warnings.
- **Statements are overwritten on fetch**, so a past `as_of` fails closed (`financials_fetched_after_as_of`) against current files. Real historical replay needs dated snapshots.
