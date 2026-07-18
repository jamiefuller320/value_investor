# CK Asset Holdings Limited (1113.HK) — Research memo

_Version 1 · Updated 2026-07-18T18:28:42.739694+00:00 · Mode: initial_

## EXECUTIVE SUMMARY
# CK Asset Holdings Limited (1113.HK) — First-Pass Research Memo

**Quantitative screen:** Buy (5/22 models, composite 59%)  
**Sources reviewed:** `screening_snapshot.json`, `financials_annual.json` (Yahoo fallback — no primary filings), `news_manifest.json`, `filings_index.json` (empty of company filings), `macro_context.json` (unavailable)

---

## EXECUTIVE SUMMARY

CK Asset Holdings is a Hong Kong–listed property conglomerate trading at a deep discount to book (P/B ~0.4) with a modest dividend yield (~3.8%) and a balance sheet that screens as conservative (D/E ~14%, net debt ~HK$9.6bn against equity of ~HK$404bn). The quantitative screen flags the name as a buy on cheapness, free-cash-flow yield, dividend growth, GARP, and financial health. The central debate is whether the market is correctly penalising low reported ROE (~2.7%) and a multi-year earnings slide, or whether hidden asset value — investment properties, overseas holdings, and a large cash pile — will eventually close the NAV gap. Primary regulatory filings were not retrieved in this research pack, limiting verification of impairments, fair-value assumptions, and management commentary; deep research therefore partially supports, but does not fully confirm, the screen signal.

---

## INVESTMENT THESIS

For a value investor, CK Asset presents a classic asset-rich, earnings-poor profile. The screen passes four factor families — cheapness, dividend, GARP, and risk — with standout metrics including P/B 0.42 (Schloss Low P/B), FCF yield ~6.0%, and D/E ~14% (Financial Health). At P/E ~15.3 on depressed earnings, the Neff PEGY pass suggests the market is not demanding a growth premium despite a portfolio spanning Hong Kong residential development, investment properties (~HK$152bn per Yahoo balance sheet), and substantial equity investments (~HK$93bn in long-term equity investments).

Business quality rests on scale, diversification beyond pure Hong Kong residential (UK, mainland China, Australia exposure historically), and capital discipline: net debt fell from ~HK$16.6bn (2024) to ~HK$9.6bn (2025) per Yahoo, while cash rose to ~HK$41.7bn. Dividend continuity (HK$6.1bn paid in FY2025 vs HK$7.1bn in FY2024) supports the Dividend Growth screen pass. The low ROE reflects fair-value accounting on investment properties, development-cycle timing, and recurring impairment charges rather than necessarily weak underlying cash generation — FY2025 FCF rebounded sharply to ~HK$16.2bn from ~HK$9.6bn in FY2024. The buy case is essentially a deep-value bet on asset backing and balance-sheet optionality at a time when Hong Kong property sentiment remains fragile but rate cuts may stabilise demand.

---

## FINANCIAL REVIEW

**Source gap:** `filings_index.json` contains zero annual or interim CK Asset filings and zero downloadable body extracts under `filings/bodies/`. The index returned two unrelated Google News items (Disney, Aviva). All figures below are sourced from `financials_annual.json` (Yahoo Finance); primary filing verification was not possible.

### Income and profitability trend (Yahoo, HK$ millions)

| Metric | FY2022 | FY2023 | FY2024 | FY2025 |
|--------|--------|--------|--------|--------|
| Revenue | 56,341 | 47,243 | 45,529 | 57,935 |
| Operating income | 17,227 | 11,926 | 10,079 | 10,658 |
| Net income | 19,826* | 17,626 | 13,942 | 11,133 |
| Diluted EPS (HK$) | 5.98 | 4.86 | 3.89 | 3.10 |
| EBITDA | 25,901 | 23,836 | 18,789 | 18,701 |
| Impairment of capital assets | 994 | 535 | 1,233 | 1,620 |

*FY2022 net income includes ~HK$2.1bn from discontinued operations.

Reported earnings have declined materially from the FY2022–FY2023 peak, with diluted EPS falling from HK$4.86 (2023) to HK$3.10 (2025), a ~36% drop over two years. FY2025 revenue recovered to HK$57.9bn (+27% YoY), yet operating income remained broadly flat (~HK$10.7bn), implying margin pressure or a less profitable revenue mix. Impairment charges persisted and increased to HK$1.62bn in FY2025, consistent with Hong Kong and overseas property revaluation headwinds. Interest expense rose from HK$1.17bn (2022) to HK$1.95bn (2025), reflecting higher-rate refinancing though still manageable relative to EBITDA (~HK$18.7bn).

### Balance sheet (Yahoo, HK$ millions, year-end)

| Metric | FY2024 | FY2025 |
|--------|--------|--------|
| Total assets | 501,781 | 509,498 |
| Stockholders' equity | 395,604 | 404,371 |
| Total debt | 57,632 | 56,609 |
| Net debt | 16,647 | 9,617 |
| Cash & equivalents | 36,069 | 41,743 |
| Investment properties | 150,708 | 151,694 |
| Inventory (development stock) | 129,776 | 122,799 |
| Long-term equity investments | 85,997 | 93,466 |

Equity grew modestly despite lower reported profit, suggesting fair-value adjustments and other comprehensive income partially offset earnings decline. Net debt improved materially in FY2025. Inventory remains large (~HK$123bn), representing both embedded value and cyclical risk if Hong Kong sales slow. Investment properties are stable to slightly higher, but without annual-report fair-value footnotes the quality of carrying values cannot be audited from primary sources.

### Cash flow (Yahoo, HK$ millions)

| Metric | FY2022 | FY2023 | FY2024 | FY2025 |
|--------|--------|--------|--------|--------|
| Operating cash flow | 6,574 | 378 | 11,865 | 18,670 |
| Free cash flow | 4,114 | (2,025) | 9,589 | 16,202 |
| Dividends paid | 8,080 | 8,171 | 7,053 | 6,090 |

FCF was volatile — negative in FY2023 amid working-capital outflows — but recovered strongly in FY2024–FY2025, supporting the screen's ~6% FCF yield. Dividends were trimmed in FY2025 (~HK$6.1bn vs ~HK$8.2bn peak in FY2023), consistent with earnings normalisation but still meaningful at the current yield.

**Interim results:** No half-year, trading update, or interim filing appears in `filings_index.json`. Latest interim trends cannot be assessed from primary sources.

---

## RISKS AND RED FLAGS

**Data and disclosure:** Absence of annual report and interim filing bodies in the research pack is itself a material limitation. Impairment methodology, related-party transactions, contingent liabilities, and going-concern language cannot be reviewed from primary filings.

**Hong Kong property cycle:** CK Asset remains heavily exposed to Hong Kong residential and commercial markets. FY2025 impairments of HK$1.62bn (Yahoo) and large development inventory (~HK$123bn) signal ongoing valuation and absorption risk. Early post-rate-cut sales (see news) showed only partial take-up (23% of units at two launches), suggesting demand recovery may be gradual.

**Low reported ROE:** Screen ROE ~2.7% reflects depressed earnings against a large equity base; if fair-value gains on investment properties do not recover, the NAV discount may persist rather than close.

**Earnings trajectory:** Four-year EPS decline from HK$5.98 to HK$3.10 raises questions about whether P/E ~15.3 is genuinely cheap or a value trap if normalised earnings are lower.

**Interest-rate and refinancing:** Interest expense has nearly doubled since FY2022 (Yahoo). Further rate stickiness or credit tightening in Hong Kong could compress margins on leveraged developments.

**Governance and control:** CK Asset is part of the Li-family corporate ecosystem (Victor Li). Concentrated control is standard in Hong Kong but warrants attention to related-party dealings and capital allocation — not assessable without annual report notes.

**Geographic and FX exposure:** Overseas assets (UK, Australia, mainland) introduce currency and regulatory risk; Yahoo data does not break down segment performance in this pack.

**Pension:** Yahoo shows defined pension benefit ~HK$626m (2025) — immaterial relative to group scale, but not zero.

No primary filing language on covenants, contingencies, or going concern was available for review.

---

## NEWS HIGHLIGHTS

News coverage in the manifest is **thin** — only two articles over the past year, both from yfinance:

1. **"Evaluating CK Asset Holdings (SEHK:1113): Is There Hidden Value in the Recent Recovery?"** (20 September 2025) — Generic valuation commentary; no specific corporate action or strategy shift disclosed.

2. **"Hong Kong's homebuyers brave storm signal at city's first post-rate cut property sales"** (19 September 2025) — CK Asset and New World Development sold 44 of 190 offered flats (~23%) at two launches shortly after Hong Kong's first rate cut; suggests cautious buyer return rather than a sharp rebound.

No manifest coverage of management changes, M&A, regulatory actions, or explicit strategy pivots. Material corporate developments may be under-represented in this feed.

---

## RESEARCH VERDICT

Verdict: accumulate  
Risk: medium  
Confidence: 0.58  
Rationale: Quantitative cheapness and balance-sheet metrics align with a deep-value accumulate case, but missing primary filings, declining reported earnings, ongoing impairments, and thin news coverage prevent full confirmation of the screen's buy signal.

---

**Note:** Macro context (`macro_context.json`) was unavailable in this pack and was not used to adjust the verdict. Recommend obtaining CK Asset's latest annual report and interim results from HKEX before sizing a position.

## INVESTMENT THESIS


## FINANCIAL REVIEW


## RISKS AND RED FLAGS


## NEWS HIGHLIGHTS
