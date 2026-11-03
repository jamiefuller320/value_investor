# SEC companyfacts for US memos (L544)

US memo names (`sp500`, `nasdaq100`, `sp400`, `us_adr_asia`) get a structured
primary-filing source next to the 10-K/10-Q bodies:
`sources/sec_companyfacts.json`. It is the US analogue of Companies House
iXBRL accounts for the memo FCF basis.

**Learning question:** does SEC-filed OCF − capex agree with the Yahoo-derived
`filing_aligned` FCF basis that the FCF overlay reads on US names?

Despite its name, `filing_aligned` in `scoring/fcf.py` is computed from Yahoo
annual cash-flow rows (`financials_annual.json`), not from filings. This
instrument measures how often that matters before anything in scoring changes.

## What the source holds

From `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`
(`research/sec_companyfacts.py`), up to five annual periods, newest first:

| Field | Concepts (first tagged wins per period) |
|-------|------------------------------------------|
| `operating_cashflow` | `us-gaap:NetCashProvidedByUsedInOperatingActivities`, `…ContinuingOperations`, `ifrs-full:CashFlowsFromUsedInOperatingActivities` |
| `capital_expenditure` | `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment`, `…ProductiveAssets`, `PaymentsForCapitalImprovements`, IFRS PP&E purchase concepts |
| `dividends_paid` | `us-gaap:PaymentsOfDividends`, `…CommonStock`, IFRS dividends paid concepts |
| `free_cashflow` | `operating_cashflow − capital_expenditure` (PP&E only) |

Only 10-K / 20-F / 40-F facts with a 340–380 day duration count (10-Ks also
carry 3-month Q4 facts). Each value keeps `form`, `accn`, `filed` (latest
filing, so restatements win) and `first_filed` (for point-in-time use).

## How it is populated

| Path | When |
|------|------|
| `ingest_filings` (`sec_edgar` regime) | Every US memo ingest / re-ingest |
| `run_library_ingest_maintenance` | Each maintenance slot that includes a US market: up to 40 memo names per market whose file is missing or older than 30 days (missing first, `strong_buy` first). Result in the maintenance JSON under `sec_companyfacts`. Committed with library ingest artifacts |

FTSE and other regimes are untouched (dual-listed UK names still use Companies
House; no companyfacts call).

## How it is used

- Memo prompts (initial, weekly update, structured verdict, gap-fill) list the
  file as a primary source **only when it exists**, with "cite over Yahoo for
  statutory OCF − capex and dividend cover".
- Gap-fill source map: `inventory.available.sec_companyfacts` when present, and
  `sec_companyfacts` heads the US `planned_alternate_sources` catalog (ranked
  first for FCF / cash / dividend questions).
- **Live path:** scoring, `reconcile_fcf`, the FCF basis overlay, paper books
  and decision review still read Yahoo annual cash-flow for `filing_aligned`.
- **L546 observe twin (shipped):** daily ops-monitor feeds SEC
  `free_cashflow` into `reconcile_fcf(..., filing_aligned_override=…)` for US
  memo names and writes `docs/data/sec_filing_aligned_twin.json`, comparing
  policy FCF / basis / mismatch flags vs the Yahoo path. Epoch id
  `sec-filing-aligned-twin-v0`. `influences_live=false` — never edits live
  scoring, overlays, books or memos.

## Ops findings

Daily ops-monitor (`check_sec_companyfacts_coverage`) writes
`docs/data/sec_companyfacts_coverage.json` (per-market memo / coverage /
compared / diverged counts, top 25 diverged rows).

| Title | Severity | Fires when |
|-------|----------|------------|
| **SEC filed FCF diverges from Yahoo basis on US buy-tier** | info (1–2 names), warn (≥3) | Latest SEC OCF − capex vs Yahoo `filing_aligned` for the same fiscal-year label differ by >25% (`\|sec − yahoo\| / max`) on a buy-tier memo name |
| **SEC companyfacts coverage below target on US memos** | info | Under 80% of US memo names have the file |
| **SEC companyfacts coverage observe failed** | warn | The refresh raised |
| **SEC filing_aligned twin would change reconcile_fcf policy on US buy-tier** | info (1–2 names), warn (≥3) | L546 twin: feeding SEC into `reconcile_fcf` `filing_aligned` would change policy FCF/basis or mismatch flags vs Yahoo on a buy-tier memo (`docs/data/sec_filing_aligned_twin.json`) |
| **SEC filing_aligned twin observe failed** | warn | The twin refresh raised |

`auto_fixable=False`. Some divergence is definitional: Yahoo capex can include
capitalised software or intangibles, while this source is PP&E only. Read the
named filings before treating a gap as a Yahoo error.

Coverage still under target a week after merge means the maintenance backfill
is not running for US markets (check the stagger cursor) or CIKs are not
resolving (`failed` reasons in the maintenance JSON).

## Promotion gate (live path still later)

**Shipped (L546 observe twin):** SEC values already enter the US
`filing_aligned` *slot* inside `reconcile_fcf` on an observe twin
(`influences_live=false`). That is the epoch/twin path — not a silent live edit.

**Still later (live cold-start):** flipping live Yahoo `filing_aligned` to SEC
would change US shard buy-tier and epoch-0 books. Do that only as a named
cold-start / capital epoch after twin evidence is thick (coverage ≥80% already
met; prefer several weekly twin snapshots naming buy-tier policy deltas). Follow-on
defer tracks the live flip.
