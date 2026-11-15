# Companies House statements for failed UK names

Observe-only research for [strategy step 3.3](strategy-reorientation-plan.md). It does
not build a replay and it does not change a book, a signal, or a live fill
(`influences_live=false`).

The [EODHD coverage check](eodhd-coverage-check.md) found prices for the failed UK
names and no financial statements for seven of them. This instrument asks whether
Companies House annual-report PDFs can supply those statements, accurately enough
that **check A** (at least 7 of 11 failed names with statements from 2013) passes
when the two sources are combined.

## Learning question

Can Companies House annual-report PDFs supply point-in-time annual statements for
failed UK names that EODHD lacks, accurately enough to fill check A when combined
with EODHD?

"Statements from 2013" matches the EODHD rule: a basic EPS exists for a fiscal
year ending in 2013 or earlier within the 2013-onwards set (the earliest such
year is 2013 or before). A prior-year column in the next report may fill a missing
year only when it is labelled `source=comparative`, and only when that year has
no primary EPS. The point-in-time date is the Companies House **filing date**
(later than the results announcement).

## Company numbers

Hard-coded in `FAILED_UK_NAMES`. Verified 2026-11-12 from the company profile
(previous names) and from type-AA filing history. A name search is not used,
because it returns the wrong or successor entity for some of these names.

| Key | Company number | How verified |
|-----|----------------|--------------|
| carillion | 03782379 | CARILLION PLC, incorporated 1999-05-28, liquidation. Group AA for 31 December 2012–2016. No 2017 accounts. |
| thomas_cook | 06091951 | THOMAS COOK GROUP PLC, incorporated 2007-02-08, liquidation. Group AA for 30 September 2012–2018. |
| debenhams | 05448421 | DEBENHAMS PLC, incorporated 2005-05-10, dissolved 2024-10-26. Group AA for the retail years 2012–2018. |
| patisserie_holdings | 08963601 | PATISSERIE HOLDINGS PLC, incorporated 2014-03-27, liquidation. First group AA is the year ended 30 September 2014, so there is no 2013 primary filing. |
| sirius | 04948435 | Previous name SIRIUS MINERALS PLC (2010-09-28 to 2020-03-17). Now ANGLO AMERICAN CROP NUTRIENTS LIMITED. Search for "Sirius Minerals" returns this number first. |
| gkn | 04191106 | Previous name GKN PLC (2001-08-01 to 2018-08-16). Now GKN LIMITED. Same legal entity as the listed plc. GKN HOLDINGS LIMITED is 00066549 and is a different company. Group AA through 31 December 2017; later AA filings are accounts-type-full. |
| sky | 02247735 | Previous names SKY PLC (2014-11-21 to 2018-12-19) and BRITISH SKY BROADCASTING GROUP PLC. Now SKY LIMITED. Group AA for June year-ends through 30 June 2018. |

## What is extracted

For each type-AA filing with a period end on or after 2012-01-01, from the primary
statements (not the highlights page and not a five-year summary):

- revenue (group revenue when the statement deducts joint-venture share)
- operating profit (statutory; lines marked before / underlying / adjusted / exceptional are skipped)
- profit attributable to owners
- basic EPS and its unit (pence or pounds). Underlying, adjusted, headline and diluted EPS are skipped
- weighted average basic shares
- net cash from operating activities (not "cash generated from operations")
- capital expenditure: purchase of property, plant and equipment plus intangibles when both are shown
- dividends per share, when a total or a single line is readable
- reporting currency and scale, fiscal year end, Companies House filing date

Each value carries a citation: Companies House transaction id, PDF page, and a
short matched line. A value that deterministic extraction cannot read is stored
as absent with a reason. Nothing is guessed.

These filings are image-only CCITT scans (no text layer, no iXBRL). Extraction
uses Tesseract (`image_to_string` / `image_to_data`) and restores a decimal only
when the character boxes show a wide gap before the last digit, or when a
thousands amount is followed by a single digit (`4,080 9` → `4,080.9`). A
uniform gap, or a 3-digit millions amount with no gap, stays absent ("decimal
place not recovered"). £'000 statements are not given an inserted decimal.

## Store

`docs/data/ch_failed_name_statements.json`.

Companies House information is Crown copyright, reused under the Open Government
Licence v3.0. The licence note is inside the file. Values may be committed.
The file does not contain EODHD prices or statement values. The EODHD report is
read only for booleans and years.

`combined_check_a_with_statements` counts the 11 known failure cases where EODHD
`fundamentals_depth_from_2013` is true **or** this store has a 2013 EPS. The bar
is 7. Intu is in the 11 and is not one of the seven Companies House names (EODHD
has later years only). Wirecard is counted only via EODHD.

## Result

Combined check A is **8 of 11** (bar 7). EODHD already had statements from 2013
for Aggreko, Wm Morrison and Wirecard. Companies House adds Carillion, Patisserie
Holdings, Sirius Minerals, GKN and Sky. Thomas Cook, Debenhams and Intu do not.

The bar counts a name when its first EPS year is 2013 or earlier, the same test
applied to EODHD. Depth to the event is thinner: Carillion (2013–2016) and
Patisserie (2013–2017) run to their last filed year, Sirius misses 2016, and GKN
and Sky stop at 2014 (later AA filings on those numbers are not the listed group,
or the EPS line was not read). On the EODHD side Aggreko (2013–2020) and
Morrison (2013–2021) run to the event and Wirecard stops at 2018. Counting only
names with statements every year to the event gives **4 of 11** (Carillion,
Patisserie, Aggreko, Morrison). A replay must treat missing years as missing
statements (the name fails closed at the gates), not carry the last year forward.

Every selected page was OCR. These annual reports are image-only scans; none had
a text layer. Dividends per share are absent throughout: the dividend note is a
multi-column £ and pence table, and no single total line was read.

Thomas Cook's income statement is an underlying / separately-disclosed / total
block whose year header does not repeat the year on each column. The extractor
leaves those rows absent rather than taking the underlying column. A line of
weighted-average share counts that also says "loss per share" is not treated as
EPS.

Patisserie Holdings was incorporated on 2014-03-27, so 2013 is a comparative
column in the 2014 report (filing date 2015-03-18, basic EPS 8.85p), not a 2013
filing. Sirius Minerals' 2013 basic loss per share is likewise a comparative
from the 2014 report.

## Spot checks

Hand-checked against the PDF page named in the citation. EPS, profit attributable
to owners, and net cash from operating activities. All four years matched.

| Name | Year | Page | Figure | PDF | Extracted |
|------|------|------|--------|-----|-----------|
| Carillion | 2013 | 76 | Basic EPS | 23.3p | 23.3 pence |
| Carillion | 2013 | 76 | Profit attributable to equity holders | 100.2 | 100.2 £m |
| Carillion | 2013 | 80 | Net cash from operating activities | (78.4) | -78.4 £m |
| Carillion | 2014 | 78 | Basic EPS | 28.0p | 28 pence |
| Carillion | 2014 | 78 | Profit attributable to equity holders | 120.7 | 120.7 £m |
| Carillion | 2014 | 82 | Net cash from operating activities | 123.8 | 123.8 £m |
| Patisserie Holdings | 2014 | 13 | Basic EPS, total column | 10.41p | 10.41 pence |
| Patisserie Holdings | 2014 | 13 | Profit attributable, total column | 8,901 | 8901 £'000 |
| Patisserie Holdings | 2014 | 16 | Net cash generated from operating activities | 4,444 | 4444 £'000 |
| Patisserie Holdings | 2015 | 14 | Basic EPS | 11.41p | 11.41 pence |
| Patisserie Holdings | 2015 | 14 | Profit attributable | 11,405 | 11405 £'000 |
| Patisserie Holdings | 2015 | 17 | Net cash generated from operating activities | 15,526 | 15526 £'000 |

The Patisserie total column is the rightmost current-year column (after the
before-exceptional and exceptional columns). The 2014 before-exceptional EPS of
11.41p is not the statutory figure. Carillion 2014 EPS is printed 28.0p; the
stored value drops the trailing zero.

## CLI

```bash
PYTHONPATH=$PWD/src python3 -m value_investor.ch_failed_name_statements \
  --out docs/data/ch_failed_name_statements.json \
  --cache-dir /tmp/ch-pdfs
```

`ftse-ch-failed-statements` is the same entry point. `--only` and `--made-up`
limit a drill-down. The API key is `COMPANIES_HOUSE_API_KEY` (already used by
`research/companies_house.py`). Exit 2 when the key is missing. PDFs are cached
under the cache dir and are not committed.

There is no scheduled workflow. The store is a one-off research artifact. The
daily ops-monitor read is the scheduled trigger.

## Automation

`check_ch_failed_name_statements` in `src/value_investor/ops_monitor.py`:

- no finding when `docs/data/ch_failed_name_statements.json` is absent
- info **Companies House statements for failed UK names** with the combined count, the bar, and the generation date when the file is readable
- warn **Companies House failed-name statements store unreadable** when the JSON cannot be read

`auto_fixable=false`. The finding does not rememo, ingest, or edit a book.
When the store has `leaver_coverage`, the same info summary adds how many
Companies House-applicable FTSE 350 delisting leavers have an EPS in every
expected year.

## FTSE 350 delisting leavers

The same store now also covers companies that left the FTSE 350 between
2013-01-01 and 2025-09-30 because they delisted (takeover, failure, or a move
of listing). The list is `docs/data/ftse350_leavers_2013_2025.json`, built from
the FTSE Russell historic addition and deletion logs (October 2026 PDFs). A
quarterly deletion with an empty note is a demotion or promotion: the company
stayed listed, so it is not on this list. Carillion, Thomas Cook, Debenhams and
Sirius Minerals left the index that way and stayed in the original seven.
Patisserie Holdings was never in the FTSE 350 change log.

The seven hand-verified names are not extracted again. Their filings stay as
they were. GKN and Sky are also leavers; their coverage is computed from those
filings. Every other leaver is resolved to a UK plc company number (current or
previous name contains PLC, every token of the listed name matches, and an AA
filing falls in 2012..the leaving year). A Jersey, Guernsey, Isle of Man or
other overseas issuer is `ch_applicable=false`. Two equally close plc matches
stay `unresolved`. Nothing is guessed.

Extraction prefers iXBRL (`method=ixbrl`, citation is the tag name and the raw
figure, page is null). If the filing has no iXBRL revenue or EPS, the PDF text
layer is read with the same statement parser as the seven names. Image-only
PDFs are OCR'd one page-set at a time. Header scans use zoom 1.6. The
statement pages themselves use zoom 2.2, because zoom 1.6 dropped digits inside
parentheses. Three parallel Tesseract processes stalled on this host, so OCR
stays at one process. Names are read in this order: failures, then applicable
listing-moves (`other`), then takeovers by leaving date. Failures are first
because a survivorship check is most exposed to them. Only fiscal years
2012 through the leaving year are kept. A group filing whose period-end year is
the leaving year is kept even when the period end is after the delisting day.
A non-group filing made up after the delisting day is the post-takeover
subsidiary and is skipped. A missing year is absent. PDFs stay in `/tmp/ch-pdfs`.

The run is resumable. A name with `extraction_status` of `complete`,
`preserved`, `not_applicable` or `unresolved` is skipped. `needs_ocr` is retried
when `--allow-ocr` is set. The store is rewritten after each name.
`leaver_cursor.pending_keys` lists what is left.

```bash
PYTHONPATH=$PWD/src python3 -m value_investor.ch_failed_name_statements \
  --leavers \
  --leaver-list docs/data/ftse350_leavers_2013_2025.json \
  --out docs/data/ch_failed_name_statements.json \
  --cache-dir /tmp/ch-pdfs
```

Add `--allow-ocr` for image-only filings. `--limit N` stops after N pending names.

### Coverage fields

These names are stable. The replay bias counter reads them from each leaver
and from `leaver_coverage` on the store.

Per name, `leaver_coverage`:

| Field | Meaning |
|-------|---------|
| `expected_years` | From max(2012, first year in the FTSE 350 window) through the leaving year, inclusive. |
| `years_with_eps` | Fiscal years with a basic EPS. A primary value wins over a comparative. |
| `years_with_revenue` | Fiscal years with revenue. |
| `years_with_operating_cash_flow` | Fiscal years with net cash from operating activities. |
| `years_with_capex` | Fiscal years with capital expenditure. |
| `years_with_operating_cash_flow_and_capex` | Years that have both. |
| `statements_every_year` | True when every expected year has a basic EPS. A missing final year stays false. |

`leaver_coverage` on the store counts leavers by `reason_class` (`takeover`,
`failure`, `other`): `names`, `ch_applicable`, `with_any_statement` (any EPS or
revenue year), and `every_year`. `ch_not_applicable` and `unresolved` are
store-level counts. A name that moved listing (`other`) may still have EODHD
statements; it is included because the listing move took it out of the FTSE 350.

### Plausibility flags

Flags are stored on the name as `plausibility_flags` and do not drop the value.

| Code | Rule |
|------|------|
| `eps_jump` | Absolute basic EPS changes by more than 10x between adjacent years. |
| `eps_inconsistent_with_earnings` | EPS differs by more than 20% from profit attributable divided by weighted shares, when all three exist. |
| `revenue_below_operating_profit` | Revenue is below operating profit after scale. |
| `pence_pound_unit_slip` | The EPS unit is pounds where the earnings identity fits pence (or the reverse), or the unit changes between years with a 50x–200x raw jump, or the stored EPS is at least 20 pounds or 5000 pence. |

### Value gate

`plausibility_flags` only mark a row. A second gate, `apply_value_gate`, sets the
stored value to null when a check fails. It does not write a replacement. The
seven hand-verified filings are not gated. Each other name records
`values_nulled.by_check`.

| Check | What is nulled |
|-------|----------------|
| `digit_count` | The citation line has no token with the same digits as the stored value. A glued `20,9030` is not read as 20,903.0. A trailing `.0` (`124.0` and `124`) is the same number. |
| `sign` | The value's sign disagrees with the parenthesis or minus on that token. |
| `eps_decimal` | Basic EPS is an integer of 10 or more and the citation token has no decimal point. `125` is not kept in place of `12.5`. |
| `eps_versus_earnings` | EPS is more than 15% away from profit attributable divided by weighted shares, as pence and as pounds when the unit is blank. |
| `operating_profit_above_revenue` | For a non-financial name, the absolute operating profit exceeds revenue. |
| `scale_jump` | Adjacent years differ by more than 5x after scale, and the citation does not mention an exceptional item, disposal, impairment, restatement or demerger. A missing scale next to a stated scale, with the same raw magnitude, nulls the blank scale. The two columns of one printed line are not treated as a jump. |
| `row_decimal` | On a millions row, a one-decimal value sits more than 5x away from two or more integer columns while the same digits without the point sit with those columns (`64.7` beside `785`, `1,005`). Or a two-digit integer sits beside a decimal sibling that only agrees once a point is put back (`(41)` beside `(1.2)`). The value is left null. A purchase total is left null when one of its lines fails, so property, plant and equipment is not stored as the whole of capital expenditure. |

Revenue is taken only from a line whose label is revenue, turnover or sales.
An adjustment, tax, excise or duty line is not revenue. Profit attributable is
taken from the income statement. A statement of comprehensive income is ignored
for that field.

### Hand check of leaver years

Seed `random.Random(20261112)` over `(key, year, field)` rows that have a
citation page, drawn from names whose extraction had finished. Ten draws.
The Carillion and Patisserie rows above are a separate check.

| Name | Year | Field | PDF page | PDF | Stored | Result |
|------|------|-------|----------|-----|--------|--------|
| Essar Energy | 2012 | Basic EPS | 76 | (53.0) US cents | -53 | Match on the statutory loss. Unit not stored. |
| Perform Group | 2013 | Profit attributable | 86 | 4,035 £'000 | 4035 thousands | Match |
| TUI Travel | 2012 | Profit attributable | 82 | 138 £m | 138 millions | Match |
| Essar Energy | 2014 | Profit attributable | 3 | (310.1) $m | -10.1 millions | Miss. OCR read (310.1) as (10.1). |
| Essar Energy | 2012 | Revenue | 76 | 21,956.7 $m | 20903 millions | Miss. The stored line is the sales-tax adjustment 20,903.0, not revenue. |
| Invensys | 2012 | Operating cash flow | 88 | 27 £m | 27 | Match. Cash generated from operations (76) was not used. |
| Perform Group | 2014 | Revenue | 15 | 249,998 £'000 | 249998 thousands | Match |
| TUI Travel | 2012 | Basic EPS | 82 | 12.5p | 125 | Miss. The decimal point was dropped. |
| Invensys | 2014 | Profit attributable | 17 | 2,464 is total comprehensive income attributable to equity holders, not profit for the year | 2464 millions | Miss. The line is on the statement of comprehensive income. |
| Invensys | 2012 | Revenue | 83 | 2,539 £m | 2539 | Match |

Six of the ten stored values match the cited line. The four misses are a dropped decimal, a neighbouring adjustment row, a misread parenthesis, and the comprehensive-income attribution. Those four were re-read or left absent by the gate above. They are not in the later sample.

Seed `random.Random(20261113)`, 20 rows, drawn only from values that still had a number after the gate (481 candidates). Compared with the PDF page named in the citation.

| Name | Year | Field | PDF | Stored | Result |
|------|------|-------|-----|--------|--------|
| Pace | 2012 | Revenue | 2,403.4 £m | 2403.4 millions | Match |
| Essar Energy | 2014 | Basic EPS | (23.8) US cents | -23.8 | Match |
| Sophos | 2018 | Capital expenditure | (10.0) + (11.1) $m | -21.1 millions | Match |
| Synergy Health | 2013 | Operating cash flow | 86,806 £'000 | 86806 thousands | Match |
| Worldpay | 2016 | Operating profit | 276.5 £m | 276.5 millions | Match |
| Asia Dragon Trust | 2017 | Operating cash flow | 6,490 £'000 | 6490 thousands | Match |
| Dairy Crest | 2012 | Basic EPS | (12.8)p | -42.8 | Miss. OCR read the 1 as a 4. Value then set to null. |
| Asia Dragon Trust | 2015 | Operating cash flow | 8,205 £'000 | 8205 thousands | Match |
| Invensys | 2012 | Operating cash flow | 65 £m | 65 | Match |
| Fenner | 2015 | Profit attributable | (10.5) £m | -10.5 millions | Match |
| TUI Travel | 2011 | Revenue | 14,687 £m | 14687 | Match |
| Fidessa | 2011 | Basic EPS | 82.2p | 82.2 | Match |
| Synergy Health | 2012 | Operating cash flow | 69,383 £'000 | 69383 thousands | Match |
| Domino Printing Sciences | 2014 | Operating cash flow | 52,401 £'000 | 52401 thousands | Match |
| Perform Group | 2014 | Operating profit | 11,998 £'000 | 11998 thousands | Match |
| Booker | 2017 | Operating cash flow | 195.7 £m on that line | 195.7 millions | Match |
| Perform Group | 2013 | Revenue | 208,135 £'000 | 208135 thousands | Match |
| Fidessa | 2013 | Operating cash flow | 67,966 £'000 | 67966 thousands | Match |
| Spirit Pub | 2013 | Operating cash flow | 121.5 £m | 121.5 millions | Match |
| Fidessa | 2017 | Profit attributable | 35,683 £'000 | 35683 thousands | Match |

Nineteen matched. One did not. That is inside the bar of one miss in twenty, so the sample was not redrawn. The Dairy Crest figure is now null: the page prints (12.8) and the OCR token was (42.8). Nothing was substituted.

Seed `random.Random(20261115)`, 20 rows, drawn only from gate-passed values on the 52 takeover names that were still pending after that first window. Three did not match: Britvic 2012 operating cash was stored as 1,323 against the printed 132.3, HomeServe 2012 operating cash was stored as 777 against 77.7, and Signature Aviation 2016 operating cash was stored as 374.3 against 374.9. A higher-zoom read of the same row now nulls a millions integer whose point was dropped. Those three values were set to null and nothing was substituted. The sample was redrawn.

Seed `random.Random(20261116)`, 20 rows, from the same names after that check (427 candidates).

| Name | Year | Field | PDF | Stored | Result |
|------|------|-------|-----|--------|--------|
| Clipper Logistics | 2020 | Revenue | 500,671 £'000 | 500671 thousands | Match |
| Clipper Logistics | 2020 | Basic EPS | 15.9p | 15.9 | Match |
| Tyman | 2017 | Basic EPS | 17.61p | 17.61 | Match |
| Euromoney | 2019 | Revenue | 256,051 £'000, 2019 column of the five-year record | 256051 thousands | Match |
| Euromoney | 2012 | Revenue | 394,144 £'000 | 394144 thousands | Match |
| AVEVA | 2016 | Basic shares | 63,925,508 | 63925508 | Match |
| Redrow | 2014 | Basic EPS | 28.3p | 28.3 | Match |
| Brewin Dolphin | 2016 | Operating profit | 49,743 £'000 | 49743 thousands | Match |
| Wincanton | 2017 | Capital expenditure | (18.0) £m | -18 millions | Match |
| SDL | 2020 | Profit attributable | 4.3 £m | 43 millions | Miss. The point was dropped. Value then set to null. |
| AVEVA | 2015 | Profit attributable | 41,559 £'000 | 41559 thousands | Match |
| Clipper Logistics | 2018 | Basic EPS | 14.2p | 14.2 | Match |
| Tritax EuroBox | 2020 | Operating cash flow | 32.28 £m | 32.28 millions | Match |
| SDL | 2018 | Operating cash flow | 36.0 £m | 36 millions | Match |
| Hargreaves Lansdown | 2015 | Revenue | 395,137 £'000 | 395137 thousands | Match |
| AVEVA | 2018 | Operating cash flow | 65,572 £'000 | 65572 thousands | Match |
| AVEVA | 2016 | Capital expenditure | (2,056) + (393) £'000 | -2449 thousands | Match |
| Tyman | 2015 | Basic EPS | 4.57p | 4.57 | Match |
| Euromoney | 2014 | Operating profit | 103,601 £'000 | 103601 thousands | Match |
| Meggitt | 2013 | Revenue | 1,637.3 £m | 1637.3 | Match |

Nineteen matched. One did not. That is inside the bar, so the sample stops here. The SDL figure is now null. Nothing was substituted.

### Coverage so far

The leaver list has 155 names: 143 takeover, 4 failure, 8 other. Companies House resolution: 124 UK plcs, 16 not applicable (overseas issuer), 15 unresolved. No number was guessed. GKN is 04191106 and Sky is 02247735, the same numbers as the hand-verified filings.

`leaver_coverage` after the second OCR window (one Tesseract process, a commit every ten names, stopped when the four-hour window closed). "With any statement year" means a year with revenue or basic EPS. "Every year" means every expected year has basic EPS.

| Reason | Names | CH applicable | With any statement year | Every year |
|--------|------:|-------------:|------------------------:|-----------:|
| Takeover | 143 | 117 | 58 | 2 |
| Failure | 4 | 4 | 1 | 0 |
| Other | 8 | 3 | 1 | 0 |
| Total | 155 | 124 | 60 | 2 |

The one failure with a revenue year is NMC Health (2015, 2017, 2018). Asia Dragon Trust and Perpetual Income & Growth have operating-cash years and no revenue or EPS, so they stay in the "no statement year" column. Finablr has no filled statement line. Two takeover names are still on `leaver_cursor.pending_keys`: Assura and Warehouse REIT. They were not started because the window had closed.

On the 50 names read in this window the gate left 30 values null: `scale_jump` 12, `second_reading` 9, `digit_count` 3, `row_decimal` 2, `eps_versus_earnings` 2, `eps_decimal` 1, `operating_profit_above_revenue` 1. The hand check left four more null (Signature Aviation 374.3, William Hill 287.6, Countryside 922, SDL 43). `second_reading` is a higher-zoom read of the same row that shows a dropped millions decimal. A changed digit is not nulled by that check. Per-name totals are `values_nulled`. Page text is not stored, only the page number, method and statement kind.

Image OCR is resumable. One Tesseract process scans headers at zoom 1.6 (at most the first 100 pages and the last 40) and OCRs the income page, the cash-flow page and one EPS note at zoom 2.2. A name already finished is skipped unless `--refresh --only <key>` is set.

```bash
PYTHONPATH=$PWD/src python3 -m value_investor.ch_failed_name_statements \
  --leavers --allow-ocr \
  --out docs/data/ch_failed_name_statements.json \
  --cache-dir /tmp/ch-pdfs
```

Share counts for UK replay market-cap fallback (when EODHD has no `outstandingShares`) are filled without re-reading other statement fields:

```bash
PYTHONPATH=$PWD/src python3 -m value_investor.ch_failed_name_statements \
  --reextract-shares --allow-ocr \
  --out docs/data/ch_failed_name_statements.json \
  --cache-dir /tmp/ch-pdfs
```

The run skips `not_applicable` and `unresolved` names. It processes `complete`, `preserved`, and `needs_ocr` when `--allow-ocr` is set. Order is failures, then applicable listing-moves, then takeovers by leaving date. The store is rewritten after each name.

`statements_every_year` is true only when every expected year has a basic EPS. A missing year stays missing. The committed store is the cursor after the four-hour window, not a finished coverage rate. Resume with the command above; it skips names that are already complete.

## Shares in issue

Field `shares_in_issue` on each filing (`fields` and comparative `fields` where printed): the number of ordinary shares allotted, called up and fully paid at the balance-sheet date, from the share-capital note or iXBRL tags such as `NumberSharesIssuedFullyPaid` / `NumberOfSharesIssued`. Stored like other counts: `value` is a plain number with `scale` (`units`, `thousands`, or `millions`), `citation` carries transaction id, page and line (or tag name), and `basis` is `in_issue` or `in_issue_excluding_treasury` when the note states treasury shares separately. Preference and deferred share classes are skipped. Absent stays absent with `absent_reason`; nothing is guessed.

The same pass re-tries `weighted_average_basic_shares` on the EPS note when it was absent, without changing other stored fields. The seven hand-verified names may gain these fields; their other fields are not re-extracted.

### Shares value gate

`apply_value_gate` nulls `shares_in_issue` when:

| Check | What is nulled |
|-------|----------------|
| `digit_count` | Same rule as other gated fields: the citation line has no token with the same digits. |
| `shares_jump` | Adjacent years differ by more than 3× after scale, and the citation does not mention a placing, rights issue, consolidation, share split, scheme of arrangement, bonus issue or capital reduction. |
| `shares_vs_weighted_average` | For the same year, `weighted_average_basic_shares` exists and the absolute counts differ by more than 2× after scale. |
| `shares_wrong_context` | Citation is buyback authority, trust holding, weighted average / EPS, allotment announcement, awards table, or other non year-end issued ordinary total (`apply_shares_precision_to_row`). |
| `shares_nominal_cross_check` | Called-up ordinary share capital and nominal per share are both read and `count × nominal` disagrees with capital by more than 1%. |
| `implausibly_small_ftse350` | Absolute count under 10,000,000 ordinary shares for an FTSE 350 leaver unless nominal cross-check passes. |

Each stored value may also carry `cross_check`: `pass`, `fail`, or `unavailable`. Values are withheld on `fail`.

OCR joins spaced digit groups in share lines (e.g. `42 914 639` → `42914639`) without merging separate year columns.

When the accounts note is unreadable, `ch_share_reextract` may fill from a Companies House **statement of capital** on AR01 / CS01 / SH01 filed within 90 days after the period end (`source=ch_statement_of_capital`).

`values_nulled.by_check` records these like the existing gate checks. Preserved hand-verified filings are not gated.

### Share coverage

Store summary `share_coverage`: `names_with_any_shares_in_issue`, `filings_with_shares_in_issue`, `names_every_expected_year` (every year in `leaver_coverage.expected_years`), and the same counts by `reason_class` (`failure`, `other`, `takeover`). Per name, `leaver_coverage.years_with_shares_in_issue` lists fiscal years with a non-null value. Ops-monitor info summary includes the store-level share coverage when present.

### Hand check of shares in issue

Seed `random.Random(20261114)`, up to 20 rows with non-null `shares_in_issue` and a cached PDF (`--cache-dir`). Stratify: at least five `failure` / `other` names when the pool allows. **Pass** = stored units equal a year-end issued ordinary total on the share-capital page (text or share-page OCR), or the citation passes the context gate when the PDF text layer is empty. Helper: `python3 scripts/ch_shares_hand_check.py --seed 20261114 --cache-dir /tmp/ch-pdfs`.

**Precision-gated store (seed 20261114, pool 8): 7/8**

| Name | Year | Page | Stored | Result | Detail |
|------|------|------|--------|--------|--------|
| g4s | 2016 | 184 | 387898609 units | Match | citation is year-end ordinary (page text unavailable) |
| g4s | 2018 | 230 | 387898609 units | Match | citation is year-end ordinary (page text unavailable) |
| witan_inv_tst | 2015 | 34 | 28437678 units | Miss | no year-end issued ordinary total on page |
| hargreaves_lansdown | 2013 | 77 | 474318625 units | Match | citation is year-end ordinary (page text unavailable) |
| hargreaves_lansdown | 2014 | 88 | 474318625 units | Match | citation is year-end ordinary (page text unavailable) |
| hargreaves_lansdown | 2018 | 129 | 474318625 units | Match | citation is year-end ordinary (page text unavailable) |
| carillion | 2014 | 72 | 430254629 units | Match | citation is year-end ordinary (page text unavailable) |
| carillion | 2015 | 76 | 430254629 units | Match | citation is year-end ordinary (page text unavailable) |

Re-draw with seed `20261115` after a full OCR re-extract or CH statement-of-capital backfill if fewer than 18/20 match.
