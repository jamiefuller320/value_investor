# Cision direct filings for Swedish euro memos (L556)

Mapped Stockholm names (OMXS30 constituents, and the same `.ST` names in
`euro_depth`) in the `euro_filings` regime now get interim, year-end and
annual reports straight from the issuer's Cision newsroom
(`source: cision_direct`). Rows point at the report PDF that Cision distributes
with each release. Before this, Swedish discovery was ESEF packages, Google
News headlines and hand-seeded IR allowlist PDFs. Nasdaq Nordic news was no
substitute: only one OMXS30 buy-tier name publishes there (N191).

**Learning question:** does the Cision feed give Swedish buy-tier memos a
body-bearing latest annual and interim, where ESEF + Google News left OMXS30
thin?

## What the feed holds

`research/cision_direct.py` reads the public per-company RSS feed
`https://news.cision.com/<newsroom>/ListItems?format=rss&pageSize=400`. There
is no key, captcha or session, and `robots.txt` on `news.cision.com` allows all
paths. 400 items reach back two to four years even for high-volume issuers
(buy-back notices). Items carry title, link, date and a short description.

Report releases link the full report as the first `mb.cision.com/Main/…pdf`
attachment on the release page. `Public/` attachments are press-release PDFs
and spreadsheets and are skipped. Ingest fetches each kept release page once
and points the row at that PDF, falling back to the release page (Nordea
attaches no PDF; its release pages carry 5–23k characters of text). The
listing-only discovery scan does not fetch release pages
(`resolve_attachments=False`); its rows use the release page URL and the same
stable `id` (Cision release number), so they are not re-counted as new.

Issuers are keyed by the explicit `CISION_NEWSROOMS` map in
`research/cision_direct.py`. There is no name guessing, because a wrong
newsroom would import another company's reports. A row is kept only if its
link sits under the mapped newsroom.

| Not mapped | Why |
|------------|-----|
| `HM-B.ST`, `NIBE-B.ST` | Not on Cision (H&M's newsroom ends in 2004; NIBE has none) |
| `ABB.ST` | No results releases on Cision since early 2023 |
| `INDU-C.ST`, `LIFCO-B.ST` | Newsrooms stop in 2010 / 2023 |

Evolution (`EVO.ST`) is mapped, but its newsroom stops at June 2026, so it
gives older reports only. The silent / partial findings surface it if that
matters.

| Release headline | `cision_kind` | `period` |
|------------------|---------------|----------|
| Year-end report, Q4 / fourth quarter, full-year, January–December | `final_results` | `annual` |
| Annual (and sustainability) report published | `annual_report` | `annual` |
| Q2 / second quarter / half-year / January–June | `interim_results` | `interim` |
| Q1 / Q3 / first or third quarter / January–March or –September / nine months | `quarterly_update` | `trading_update` |
| Invitations, webcasts, "will be presented", CEO comments, 20-F filing notices, corrections, AGM, buy-backs, voting rights, M&A news without a report headline | — | dropped |

An undated "Interim report" headline falls back to the release month:
January–March is annual, July–September is interim, and anything else is
quarterly. `_apply_headline_period` keeps `cision_period` for `cision_direct`
rows. The same headline re-issued within 10 days is kept once (newest wins).
The feed keeps the newest 2 rows per kind, so at most 8 rows, under the
12-body ingest cap. In merges the source bonus is 27, the same as
`amf_direct`.

## Why not EQS, MFN or other feeds

Checked during L556 and parked (N195): EQS News (Germany) and MFN (Sweden)
both have ungated JSON feeds with ISIN / LEI filters, but `robots.txt`
disallows those paths (`/wp-json/`, `*.json`). The Oslo Børs newsreader API is
open, but no project market lists Oslo names. ESAP, the EU single access
point, is the long-term route for the other countries (L557).

## How it is populated

| Path | When |
|------|------|
| `ingest_filings` (`euro_filings` regime, `cision_eligible` tickers) | Every mapped Swedish memo ingest / re-ingest in omxs30 and euro_depth. Resolves report PDFs |
| Library discovery scan (`list_regime_filings_index_only`) | Each maintenance / sprint scan. Listing only. A new report release counts as a discovery hit |

`filing_source_surface()` returns `euro_filings+cision_direct` for mapped
names. Their parked leftovers in `ingest_exhaustion.json` are released for one
retry, recorded in `surface_released` (same mechanism as L543, see
[hkex-direct-filings.md](hkex-direct-filings.md#parked-leftovers-get-one-retry)).
Unmapped names keep their bare `euro_filings` surface and stay parked.

`cision_direct` is in `UNEXTRACTABLE_BODY_SOURCES`: a row still bodiless after
a body attempt is dropped and its URL is skipped for 30 days (see
[amf-direct-filings.md](amf-direct-filings.md#pdfs-without-a-text-layer)).

## Ops findings

Daily ops-monitor (`check_cision_direct_coverage`) writes
`docs/data/cision_direct_coverage.json`. It reads committed indexes only and
never fetches. The store holds per-name `cision_rows`, bodies, annual /
interim body flags and the latest Cision results date, per market. Summary
counts dedupe names that sit in both omxs30 and euro_depth. Buy-tier is the
current screen shortlist.

| Title | Severity | Fires when |
|-------|----------|------------|
| **Cision direct filings not yet on Swedish buy-tier memos** | info | Under 80% of mapped Swedish buy-tier names have `cision_direct` bodies for both an annual and an interim period |
| **Cision direct feed silent on freshly ingested Swedish memos** | info (1 name), warn (≥2) | A mapped Swedish index fully re-ingested in the last 7 days (its note names Cision newsroom RSS) has zero `cision_direct` rows |
| **Cision direct coverage observe failed** | warn | The refresh raised |

`auto_fixable=False`. Expect the coverage finding for the first runs after
merge while the ingest loop works through the names. If it persists past two
weeks, check `surface_released` and `unparked_leftover` in
`docs/data/library/markets/omxs30/ingest_exhaustion.json`.

The silent finding means a newsroom slug changed, the issuer switched
newswire, or the RSS format changed. Run
`fetch_filings_cision_direct(ticker=…)` for a named ticker and open
`https://news.cision.com/<newsroom>/ListItems?format=rss` to check. Fix the map
entry, or remove it if the issuer left Cision. The fallback is ESEF + Google
News, which does not block ingest.
