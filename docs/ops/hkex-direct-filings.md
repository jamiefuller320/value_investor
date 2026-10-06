# HKEX direct filings for hang_seng memos (L543)

`.HK` memo names in the `asia_filings` regime get results announcements and
annual / interim reports straight from HKEXnews (`source: hkex_direct`), with
direct PDF URLs and bodies. Before this, Asia discovery was Google News
headlines plus hand-seeded IR allowlist PDFs.

**Learning question:** does the HKEX direct feed give hang_seng buy-tier memos
a body-bearing latest annual and interim, where Google News discovery left
them thin or parked?

## What the feed holds

`research/hkex_direct.py` uses the public JSON behind the HKEXnews title-search
page (no key, no token):

1. `www1.hkexnews.hk/search/prefix.do` maps the five-digit code
   (`2382.HK` → `02382`) to HKEX's internal `stockId` (exact code match only,
   because the response also lists warrants). Cached in-process.
2. `www1.hkexnews.hk/search/titleSearchServlet.do`, two category queries per
   ticker over 800 days:
   - results group (`t1code=10000`, `t2Gcode=3`)
   - financial statements (`t1code=40000`)

The HKEX headline category decides `period` and is kept on the row as
`hkex_period`. Headlines such as "RESULTS FOR THE THREE MONTHS ENDED…" do not
classify reliably, so `_apply_headline_period` keeps the category value for
`hkex_direct` rows.

| HKEX category | `period` |
|---------------|----------|
| Final Results, Annual Report | `annual` |
| Interim Results, Quarterly Results, Interim/Half-Year Report, Quarterly Report | `interim` |
| Profit Warning | `trading_update` |
| ESG reports, Date of Board Meeting, dividend forms, everything else | dropped |

The feed returns at most 16 rows, newest first, and always keeps the latest
annual and interim. Document URLs use `https://www.hkexnews.hk`, the same host
as the IR allowlist. Allowlist rows whose PDF the feed already indexes are
dropped, so one document never takes two body slots. In merges the source
bonus is 27, the same as `asx_direct`.

Results announcements are a few hundred KB and carry the full statements,
including the cash-flow statement. Annual and interim reports are multi-MB;
their bodies are truncated at the 80,000-character body cap.

**SGX (`sti`) is not covered.** `api.sgx.com` announcements return 403 at the
edge and the site's frontend authenticates with a token taken from its
JavaScript. We do not work around that. `.SI` names stay on Google News plus
IR allowlist PDFs (`links.sgx.com` PDFs themselves fetch fine). Parked as a
deferred idea.

## How it is populated

| Path | When |
|------|------|
| `ingest_filings` (`asia_filings` regime, `.HK` only) | Every hang_seng memo ingest / re-ingest |
| Library discovery scan (`list_regime_filings_index_only`) | Each maintenance / sprint scan of hang_seng buy-tier. A new HKEX results row counts as a discovery hit and adds to that name's deepen priority |

Discovery merges now stamp the resolved regime on `filings_index.json`. They
used to write `uk_rns` for every market.

### Parked leftovers get one retry

Ingest target selection skips parked leftovers (`ingest_exhaustion.json`), and
they only unpark when coverage improves. So a new adapter would never reach
them on its own. Parked rows now carry `source_surface`
(`filing_source_surface()` in `research/filings.py`: regime plus any direct
adapter, e.g. `asia_filings+hkex_direct`).

`load_ingest_exhaustion` releases any parked row whose stamped surface (bare
regime for rows parked before stamping) differs from the current one. The
release is recorded in `surface_released`, and the next exhaustion refresh will
not re-park that name in the same pass. If the retry does not improve
coverage, the name parks again normally, stamped with the new surface.

When this shipped, all 12 parked hang_seng names were released. Parked names
in every other market are unchanged. A future adapter (e.g. L545 for
`asx`/`euro`) only needs to extend `filing_source_surface` to give its parked
names the same retry.

## Ops findings

Daily ops-monitor (`check_hkex_direct_coverage`) writes
`docs/data/hkex_direct_coverage.json`. It reads committed indexes only and
never fetches. The store holds per-name `hkex_rows`, bodies, annual / interim
body flags and the latest HKEX results date. Buy-tier is the current screen
shortlist.

| Title | Severity | Fires when |
|-------|----------|------------|
| **HKEX direct filings not yet on hang_seng buy-tier memos** | info | Under 80% of hang_seng buy-tier names have `hkex_direct` bodies for both an annual and an interim period |
| **HKEX direct feed silent on freshly ingested hang_seng memos** | info (1 name), warn (≥2) | A `.HK` index fully re-ingested in the last 7 days (its note names HKEXnews) has zero `hkex_direct` rows |
| **HKEX direct coverage observe failed** | warn | The refresh raised |

`auto_fixable=False`. Expect the coverage finding for the first runs after
merge while the ingest loop works through the names. If it persists past two
weeks, targets are not reaching these names. Check `surface_released` and
`unparked_leftover` in `docs/data/library/markets/hang_seng/ingest_exhaustion.json`.

The silent finding means HKEXnews changed its JSON shape or the stock lookup
failed. Run `fetch_filings_hkex_direct(ticker=…)` for a named ticker to see
which step returned nothing. The fallback is the Google News path, which does
not block ingest.
