# AMF direct filings for French euro memos (L545)

`.PA` names, and French issuers listed elsewhere, in the `euro_filings` regime
now get half-year financial reports and results press releases straight from
France's officially appointed mechanism (OAM), the AMF regulated-information
feed (`source: amf_direct`). Rows carry direct PDF URLs and bodies. Before
this, French discovery was ESEF packages, Google News headlines and
hand-seeded IR allowlist PDFs.

**Learning question:** does the AMF feed give French buy-tier memos a
body-bearing latest annual and interim, where ESEF + Google News discovery
left them thin or parked?

## What the feed holds

`research/amf_direct.py` queries the DILA open-data portal
`info-financiere.gouv.fr` (Opendatasoft API v2.1, dataset `flux-amf-new-prod`).
There is no key or token. Each record has a filing date, title, AMF subtype
code, language, issuer LEI / ISIN / AMF ticker and a direct
`fr.ftp.opendatasoft.com` PDF URL.

The issuer key is the AMF ticker for `.PA` names (`CAP.PA` → `CAP`). For
French issuers on other exchanges it is the cached LEI, used only when
`lei_country` is `FR`. The ticker is the primary key because some cached
`.PA` LEIs point at a subsidiary. For example, `SGO.PA` is cached as
Compagnie de Miraumont rather than Saint-Gobain, and the cached `DG.PA` LEI
has no AMF filings at all. If a reused AMF ticker returns several issuers,
only the most frequent LEI is kept.

There are two queries per issuer over 800 days:

1. Periodic reports plus results releases:
   - annual reports (`002002`, `003000`)
   - half-year reports (`002003`, `004000`)
   - quarterly information (`005000`–`005002`)
   - inside information `001007`, which is where issuers file results and
     revenue releases
2. The other inside-information subtypes (`001001`, `001002`, `001006`,
   `001008`, `015000`), filtered server-side to results headlines. Sanofi,
   for example, files results under `001006` among hundreds of product
   releases.

| AMF row | `amf_kind` | `period` |
|---------|------------|----------|
| Full-year results / Q4 release | `final_results` | `annual` |
| Annual report PDF; annual consolidated statements filed under a half-year code (LVMH) | `annual_report` | `annual` |
| H1 / half-year results release | `interim_results` | `interim` |
| Half-year financial report | `half_year_report` | `interim` |
| Q1 / Q3 / nine-month release, quarterly information | `quarterly_update` | `trading_update` |
| Availability / publication notices, URD filings, aide-mémoires, AGM, dividends, bonds, clinical results, own shares, voting rights | — | dropped |

A results headline decides the period from bilingual cues. Explicit full-year
wording is checked first, then Q1/Q3, then half-year, then other annual cues.
Generic titles such as "Inside Information / News release on accounts,
results" fall back to the filing month: January–March is annual, July–September
is interim, and anything else is quarterly. `_apply_headline_period` keeps
`amf_period` for `amf_direct` rows, because French titles ("Résultats du 1er
semestre") do not classify via the RNS rules.

Most items are filed in French and English. English wins per (day, subtype).
The same report re-filed within 10 days is kept once. The feed keeps the
newest 2 rows per kind, so at most 10 rows, under the 12-body ingest cap. In
merges the source bonus is 27, the same as `hkex_direct`.

**Full annual reports (URD) are not taken from AMF.** They are filed as ESEF
packages (`.xbri` / `.zip`) that `esef_direct` already indexes. The PDF annual
rows in AMF are almost always one-page "publication of the URD" notices, so
they are dropped. For most names the AMF annual body is therefore the
full-year results release, which carries the income statement, cash flow and
net debt.

## Other national registers (not shipped)

Each register was checked during L545 and parked with `ftse-defer`:

| Country / market | Register | Why not now |
|------------------|----------|-------------|
| Sweden (`omxs30`) | Nasdaq Nordic company news JSON | Public, but only Nasdaq GlobeNewswire customers publish there: 1 of 11 OMXS30 buy-tier names (Skanska). The others use Cision / MFN. Finansinspektionen's OAM has no API. Sweden is now covered by the Cision newsroom feed instead, see [cision-direct-filings.md](cision-direct-filings.md) |
| Germany (`dax`) | Unternehmensregister / Bundesanzeiger | Search sits behind a captcha (Unternehmensregister) or a stateful session form (Bundesanzeiger). Not worked around |
| Italy (`ftse_mib`) | eMarket STORAGE / 1Info | HTML portals with no documented API. 1Info's tables load from internal endpoints of an ASP.NET app |
| Spain (`ibex35`) | CNMV regulated information | ASP.NET `__VIEWSTATE` forms. Direct query URLs return 400/403 error pages |
| Austria (`atx`) | OeKB OAM (`my.oekb.at`) | Angular app behind an F5 bot-defence script, with no documented API. Not worked around |

## How it is populated

| Path | When |
|------|------|
| `ingest_filings` (`euro_filings` regime, `amf_eligible` tickers) | Every French memo ingest / re-ingest across cac40, euro_stoxx50, euro_depth and others |
| Library discovery scan (`list_regime_filings_index_only`) | Each maintenance / sprint scan. A new AMF results row counts as a discovery hit |

`filing_source_surface()` returns `euro_filings+amf_direct` for eligible
names. Their parked leftovers in `ingest_exhaustion.json` are released for one
retry, recorded in `surface_released` (same mechanism as L543, see
[hkex-direct-filings.md](hkex-direct-filings.md#parked-leftovers-get-one-retry)).
Parked names that are not eligible keep their bare `euro_filings` surface and
stay parked.

### PDFs without a text layer

Some issuers file PDFs with outlined text: VINCI's H1 2025 and Q3 2025
releases have 25 pages but only about 200 extractable characters. If an AMF row
is still bodiless after a body attempt, ingest drops it and records its URL
under `unextractable_body_urls` in `filings_index.json` (URL mapped to the
first-failure timestamp). Re-ingest, the discovery merge and the library scan
diff skip those URLs, so the rows don't come back as indexed-without-body or
as false discovery hits. Entries expire after 30 days
(`UNEXTRACTABLE_BODY_RETRY_DAYS`) and get one more fetch. OCR is out of scope.

## Ops findings

Daily ops-monitor (`check_amf_direct_coverage`) writes
`docs/data/amf_direct_coverage.json`. It reads committed indexes only and
never fetches. The store holds per-name `amf_rows`, bodies, annual / interim
body flags and the latest AMF results date, per market. Summary counts dedupe
names that sit in several euro markets. Buy-tier is the current screen
shortlist.

| Title | Severity | Fires when |
|-------|----------|------------|
| **AMF direct filings not yet on French buy-tier memos** | info | Under 80% of French buy-tier names have `amf_direct` bodies for both an annual and an interim period |
| **AMF direct feed silent on freshly ingested French memos** | info (1 name), warn (≥2) | A French index fully re-ingested in the last 7 days (its note names AMF open data) has zero `amf_direct` rows |
| **AMF direct coverage observe failed** | warn | The refresh raised |

`auto_fixable=False`. Expect the coverage finding for the first runs after
merge while the ingest loop works through the names. If it persists past two
weeks, check `surface_released` and `unparked_leftover` in each market's
`ingest_exhaustion.json`.

The silent finding means the `flux-amf-new-prod` dataset was renamed or
changed schema. Run `fetch_filings_amf_direct(ticker=…)` for a named ticker.
The fallback is ESEF + Google News, which does not block ingest.
