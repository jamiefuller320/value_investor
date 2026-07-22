# Closing research gaps: ask → fetch → record

## Problem

Gap-fill could *plan* alternate sources but usually had **zero filing bodies**
(PDF downloads were skipped; Google News wrappers have no text). The agent then
left questions `unresolved` and parked ingest suggestions.

## What we do now

1. **PDF text extract** (`pypdf`) for direct filing URLs (Ticker RNS / Investegate / IR).
2. **Issuer headline filter** — drop Google News rows that never mention the company/EPIC.
3. **OCF mapping** — Yahoo `operating_cashflow` aliases so Piotroski/risk models see cash flow.
4. **Pre-agent body refetch** — `refetch_missing_filing_bodies` before gap-fill answers.
5. **One follow-up agent turn** when new bodies were fetched and questions remain open.
6. **Market=`ftse350`** passed into email/CLI gap-fill so the UK source catalog applies.

## Still later

| Item | Why |
|------|-----|
| Companies House filed accounts API (L10/L35) | Needs company-number map + free API key |
| Generic IR PDF crawler | Prefer over per-issuer hardcodes (L38/L43) |
| Full multi-turn Q→A loops (L16) | After bodies are routinely non-empty |

## Commands

```bash
ftse-email --deep-analysis --research-docs --research-gap-fill
# or
ftse-research --gap-fill --gap-fill-cap 3
```

See `gap_fill_summary.json` → `fetch_attempts` / `follow_ups`.
