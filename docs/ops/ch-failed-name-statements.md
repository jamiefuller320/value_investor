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
