# Decision-input inventory (observe)

**Strategy part served:** F9-B input quality for named stocks (filing bodies, free-cash-flow basis, research overlay, memo recency). Plan step 1.9 in [`strategy-reorientation-plan.md`](strategy-reorientation-plan.md) is the library half.
**Mode:** observe-only. `influences_live` is false. Neither check rememos, ingests, edits signals, or opens an engineering task. Neither writes paper books or `decision-review --apply`.
**Code:** `src/value_investor/decision_input_inventory.py` (FTSE) and `src/value_investor/library_decision_input_inventory.py` (library)
**CLI:** `ftse-ingest-audit --decision-inputs` and `ftse-ingest-audit --library-decision-inputs` (one at a time)

## FTSE holdings and buy tier

`check_decision_input_inventory` refreshes `docs/data/decision_input_inventory.json` for names that are in the primary paper holdings or on the FTSE buy tier (`buy` / `strong_buy`).

| Bind | True when |
|---|---|
| `key_filing_bodies` | The filings index has an annual body, and an interim body when interim rows are indexed (`key_bodies`) |
| `fcf_basis_bound` | The screen row's `fcf_basis_overlay` is a boolean, so the divergence check was evaluated. True and false both count |
| `overlay_bound` | A research verdict is present and `adjusted_signal` is set |
| `memo_recent` | The memo's last activity (`updated_at`, else `created_at`) is within 21 days |

The finding **FTSE decision-input utilization gap** warns only when the largest gap covers at least three names. A quiet result is `P1 green-enough`. It does not rememo.

## Library buy-tier names

Learning question: for every buy-tier name in every graduated library market, are those four binds true, computed from that name's research folder and library screen with the same meanings, and which binds are the gaps?

`check_library_decision_input_inventory` runs in the daily ops-monitor pass. It reads `is_graduated` from `docs/data/market_status.json` (it does not keep its own market list) and writes `docs/data/library_decision_input_inventory.json`. Rows are keyed by market and ticker, so a name that sits in two graduated markets is two rows. A market that is not graduated is skipped.

The finding **Library decision-input binds (observe)** is an info summary of the counts. `auto_fixable` is false. It does not rememo, ingest, or open an engineering task. Memo recency is expected to be the common gap; that is a report, not a work order.

### Where each field comes from

Buy-tier membership is `signal` of `buy` or `strong_buy`.

- When `screen/latest_summary.json` has a `run_at` on or before the as-of time, membership and the screen `free_cashflow` come from `screen/latest_signals.csv`. That file has no `adjusted_signal`, `research_verdict`, or `fcf_basis_overlay`.
- Otherwise membership comes from the newest `screen/history/run_*.json.gz` on or before the as-of time. A later run is ignored.
- `adjusted_signal` and `research_verdict` always come from that history run. If the run has an adjusted signal but no verdict, the verdict may fall back to `research.json` when that memo's timestamp is on or before the as-of time. A memo rewritten after the as-of time does not supply the verdict.
- The research folder is `docs/data/library/markets/<market>/screen/research/<TICKER>/`. Filing bodies and memo times use the same helpers as the FTSE inventory (`_index_meta`, `_research_doc_times`). An index or memo with no timestamp, or a timestamp after the as-of time, does not count.

| Bind | True when |
|---|---|
| `key_filing_bodies` | Same `key_bodies` rule as the FTSE inventory, and the index fetch time is on or before the as-of time |
| `fcf_basis_bound` | The library free-cash-flow check below was evaluated |
| `overlay_bound` | A research verdict is present and `adjusted_signal` is set |
| `memo_recent` | Last memo activity on or before the as-of time is within 21 days (`DEFAULT_MEMO_MAX_AGE_DAYS`) |

A missing research folder, a missing index, or a missing free-cash-flow input makes the affected bind false. Missing data never counts as a pass.

### Library free-cash-flow bind

On the FTSE screen, `fcf_basis_overlay` is the boolean result of the free-cash-flow divergence check (`enrich_signals_with_fcf_basis_overlay`). The inventory treats any boolean — divergence or not — as bound, because the check ran. Library screen files do not store that flag. None of the current library buy-tier folders carry `sources/fcf_bridge.json`.

Library folders usually have annual statements and, for US names, SEC company facts. A reviewed bridge file is optional. The bind is true only when that same check can be evaluated from files dated on or before the as-of time:

1. A numeric `free_cashflow` on the point-in-time screen row (the trailing figure the live check calls screen TTM).
2. A filing-side figure, in this order:
   - `sources/financials_annual.json`, using operating cash flow plus capital expenditure, or the reported Free Cash Flow line when those two are absent (`compute_filing_aligned_fcf`)
   - otherwise `sources/sec_companyfacts.json` `latest.free_cashflow` (filed operating cash flow minus capital expenditure, used for US names)
   - otherwise a resolved `sources/fcf_bridge.json` with a numeric company-adjusted or policy figure

The evaluated yes/no is stored as `fcf_basis_overlay`. The bind is the fact that a boolean was produced. If either side is missing, or the file has no timestamp or a timestamp after the as-of time, the bind is false and `fcf_basis_overlay` is null. A false overlay is not invented to make the bind true.

The 25% filing-versus-screen mismatch and the 50% basis-pair divergence are the same predicates the live check uses. Library history runs do not carry the per-model pass frame, so the live path that also requires a yield-model pass is not re-run. This check does not write `fcf_basis_overlay` back onto the screen.

### What the store records

For each market and ticker: the four binds, the gap list, memo age and timestamp, the research verdict and adjusted signal, the screen-run file and time those two came from, and the filings totals. The summary has overall and per-market counts of names, names with all four binds, and each bind's gap count.

`observe_only` is true and `influences_live` is false. The store is a snapshot, not a history. The FTSE file is a separate instrument and is not rewritten by this check.
