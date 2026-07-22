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
7. **Companies House accounts** — free Public Data API (`COMPANIES_HOUSE_API_KEY`) for UK
   statutory accounts PDFs/iXBRL text. Ticker→company number map cached in
   `docs/data/companies_house_numbers.json` (search + manual override).
8. **Historical deepen for memo tickers** — `ftse-research --deepen-sources` (and gap-fill
   ingest with `deepen_history=True`) pulls up to five CH accounts years + more bodies.
   **Does not** backdate research revisions (avoids lookahead into the learning track).
9. **IR URL allowlist MVP** — optional direct results/annual PDFs in
   `docs/data/research_ir_urls.json` until a generic IR crawler exists.

## Still later

| Item | Why |
|------|-----|
| Generic IR PDF crawler (L56) | Prefer discovery over per-issuer allowlist hardcodes |
| Extend `FILINGS_LOOKBACK` beyond 800d (L55) | After CH bodies are routinely non-empty |
| Full multi-turn Q→A loops (L16) | After bodies are routinely non-empty |

## Setup

```bash
# Free key: https://developer.company-information.service.gov.uk/
export COMPANIES_HOUSE_API_KEY=...
```

## Commands

```bash
ftse-email --deep-analysis --research-docs --research-gap-fill
# or
ftse-research --gap-fill --gap-fill-cap 3

# Thicken sources for existing memos (no Cursor agent call):
ftse-research --deepen-sources
ftse-research --deepen-sources --tickers SHEL.L,BP.L
```

See `gap_fill_summary.json` → `fetch_attempts` / `follow_ups`, and
`deepen_sources_summary.json` after `--deepen-sources`.
