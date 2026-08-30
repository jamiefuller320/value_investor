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
5. **Multi-attempt retry loop** (`DEFAULT_GAP_FILL_ATTEMPTS = 3`):
   - First agent pass on open questions from deep-analysis red flags.
   - While questions remain `unresolved` or `partially_resolved` and attempts remain:
     - If the initial refetch already fetched bodies, run a follow-up agent turn immediately.
     - Otherwise call `execute_planned_alternate_sources()` (re-ingest CH / Investegate /
       SEC / IR, then refetch bodies) and follow up only when new bodies arrive.
   - Stop early when all questions resolve or no new bodies can be fetched.
6. **Market=`ftse350`** passed into email/CLI gap-fill so the UK source catalog applies.
7. **Companies House accounts** — free Public Data API (`COMPANIES_HOUSE_API_KEY`) for UK
   statutory accounts PDFs/iXBRL text. Ticker→company number map cached in
   `docs/data/companies_house_numbers.json` (search + manual override).
   When PDFs are image-only, OCR (tesseract + pymupdf) extracts text; iXBRL/xhtml
   is preferred when CH offers both formats.
8. **Investegate / iXBRL / SEC enrichment** — direct RNS HTML scrape, CH iXBRL narrative
   extraction, SEC inline-XBRL narrative (with UK dual-list homonym guard). Wired into
   `uk_rns` ingest and `refetch_missing_filing_bodies` via `enrich_filing_rows()`.
9. **Historical deepen for memo tickers** — `ftse-research --deepen-sources` (and gap-fill
   ingest with `deepen_history=True`) pulls up to five CH accounts years + more bodies.
   **Does not** backdate research revisions (avoids lookahead into the learning track).
10. **IR URL allowlist MVP** — optional direct results/annual PDFs in
    `docs/data/research_ir_urls.json` until a generic IR crawler exists.
11. **Memo source-quality scoring** — after each gap-fill save, `attach_memo_quality()`
    records a 0–1 `source_quality_score` (filing bodies, financials, news, evidence
    ladder, gap resolution) on `ResearchDocument.memo_quality`. Dashboard shows a Sources
    grade badge; historical replay carries the score for attribution.

## Sunday email order (required)

`ftse-email` runs **ingest-improvement before research-docs / gap-fill**, then seeds
thickened `docs/data/research/*/sources` into `output/research` so memo agents and
`memo_quality` scores see full filing bodies. Do not reorder back to
research-docs-first — that left adequate Sources grades on memos written against
thin corpora while bodies landed afterward.

Manual rememo of an adequate set (after bodies already exist):

```bash
python3 scripts/rememo_adequate_tickers.py
```

## Retry flow (summary)

```
prepare_gap_fill_source_pack()  →  body_refetch
run_gap_fill_research_agent()
for attempt in 1..3:
  if no unresolved questions: break
  if attempt==1 and initial refetch got bodies: use those
  else: execute_planned_alternate_sources() → stop if fetched==0
  run_gap_fill_research_agent(follow_up=True)
attach_memo_quality() → store.save()
```

Inspect `gap_fill_summary.json` → `fetch_attempts`, `follow_ups`, `question_outcomes`.

## Still later

| Item | Why |
|------|-----|
| Generic IR PDF crawler (L56) | Prefer discovery over per-issuer allowlist hardcodes |
| Extend `FILINGS_LOOKBACK` beyond 800d (L55) | After CH bodies are routinely non-empty |
| Deeper multi-turn Q→A beyond body refetch (L16) | When alternate fetchers routinely exhaust |

## Setup

```bash
# Free key: https://developer.company-information.service.gov.uk/
export COMPANIES_HOUSE_API_KEY=...

# Image-only CH accounts PDFs need OCR (system package + Python deps in pyproject.toml)
sudo apt install tesseract-ocr   # Debian/Ubuntu; brew install tesseract on macOS
export COMPANIES_HOUSE_OCR=1       # default on; set 0 to skip OCR
export COMPANIES_HOUSE_OCR_MAX_PAGES=12  # optional cap per filing
```

## Commands

```bash
ftse-email --deep-analysis --research-docs --research-gap-fill
# or
ftse-research --gap-fill --gap-fill-cap 3

# Thicken sources for existing memos (no Cursor agent call):
ftse-research --deepen-sources
ftse-research --deepen-sources --tickers SHEL.L,BP.L

# Backfill source-quality scores on existing memos (no agent call):
python3 scripts/backfill_memo_quality.py
```

See `gap_fill_summary.json` → `fetch_attempts` / `follow_ups`, and
`deepen_sources_summary.json` after `--deepen-sources`.

Architecture overview: [`docs/architecture.md`](../architecture.md).
