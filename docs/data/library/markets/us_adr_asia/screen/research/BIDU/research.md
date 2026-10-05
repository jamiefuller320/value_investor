# Baidu, Inc. (BIDU) — Research memo

_Version 1 · Updated 2026-07-18T18:32:54.153026+00:00 · Mode: initial_

## EXECUTIVE SUMMARY
# Baidu, Inc. (BIDU) — Research Memo

**Quantitative screen:** Buy (6/22 models, composite 66%, sector-relative 61%)  
**Sources:** SEC 20-F (annual), 6-K (interim), `screening_snapshot.json`, `financials_annual.json` (Yahoo fallback where noted), `news_manifest.json`  
**Macro context:** Not available (`macro_context.json` missing)

---

## EXECUTIVE SUMMARY

Baidu screens as a deep-value China ADR: price-to-book near 0.9x, debt-to-equity near 32%, and six quantitative models passed (cheapness and risk families). The investment case rests on a large balance sheet—cash, short-term investments, and equity stakes—plus AI/cloud and Apollo Go optionality, against a market that has de-rated the name after weak reported 2025 earnings.

Reported FY2025 net income collapsed on large investment and asset impairments, while normalised earnings remain materially higher; the central debate is whether book value and strategic assets are being masked by one-offs, or whether structural pressure in search advertising, iQIYI, and China tech regulation is eroding core returns. Hong Kong dual-primary listing plans and an Apple AI partnership have refreshed the narrative, but VIE structure, geopolitical listing risk, and robotaxi regulatory friction remain overhangs.

---

## INVESTMENT THESIS

The quantitative screen flags Baidu as cheap on asset-based and free-cash-flow metrics: P/B 0.92 (Schloss/Deep Value pass), D/E 32% (Financial Health pass), and positive screen FCF of roughly RMB 8.0bn (~US$1.1bn at recent rates). Composite score 0.66 with high data quality (17/20 metrics) supports a value entry, though conviction is still “new” (one week at signal).

Business quality is mixed but not distressed at the balance-sheet level. Baidu remains China’s dominant search and AI infrastructure operator, with Ernie LLM, AI cloud, and Apollo Go among the more credible autonomous-driving programmes globally (Wedbush, July 2026, ranks Baidu alongside Waymo). The VIE structure means ADR holders own a Cayman holding company, not direct mainland operating assets—a structural discount the screen partially captures via low P/B but not fully.

For a value investor, the hook is sum-of-the-parts: consolidated equity of roughly RMB 290bn (Yahoo fallback, FY2025) against a sub-book market capitalisation, with Trip.com, iQIYI, and a large investment portfolio embedded. The screen buy is credible on asset coverage and leverage, but earnings quality in FY2025 weakens the “quality at a price” dimension; position sizing should reflect China ADR and governance risk rather than treating this as a plain deep-value compounder.

---

## FINANCIAL REVIEW

### Source note

**Annual filings:** Two Form 20-F annual reports are indexed—FY2024 (filed 28 March 2025) and FY2025 (filed 17 March 2026), both with body extracts. **Interim filings:** 36 Form 6-K interim filings are indexed (Oct 2024–Jul 2026); 12 have body extracts, but these are mostly cover pages, exhibit indexes, or corporate announcements—**not** full earnings tables. Interim releases referenced include Q3 2024 (6-K, 21 Nov 2024), Q4/FY2024 (6-K, 18 Feb 2025), and debt-offering notices (Mar 2025). **Gap:** Press-release exhibit bodies with revenue/EPS figures were not captured in the extracts; headline interim numbers below use Yahoo (`financials_annual.json` quarterly cache) with explicit fallback labelling.

**Income statement trend (Yahoo fallback — RMB):**

| Year | Revenue | Operating income | Net income | Diluted EPS |
|------|---------|------------------|------------|-------------|
| 2023 | 134.6bn | 21.9bn | 20.3bn | 55.12 |
| 2024 | 133.1bn | 21.3bn | 23.8bn | 65.92 |
| 2025 | 129.1bn | 10.4bn | 5.6bn | 11.76 |

Revenue has drifted lower for three years (~4% from 2023 to 2025). FY2025 reported net income fell ~76% year-on-year; Yahoo attributes RMB 18.4bn in total unusual items, including RMB 16.2bn impairment of capital assets and RMB 16.7bn asset impairment in the cash-flow statement. **Normalised net income** (Yahoo fallback) was RMB 20.6bn in FY2025—closer to prior-year run-rate—suggesting reported earnings understate underlying cash generation, but also that investment/write-down risk is real and recurring in nature.

**Filing-sourced qualitative items (20-F bodies):**
- VIEs generated **45%, 44%, and 50%** of external revenues in 2023, 2024, and 2025 respectively (FY2025 20-F)—concentration rose in 2025.
- The group recognised **impairment charges on long-term investments** in both 2024 and 2025 (FY2025 20-F); the FY2024 20-F notes similar charges in 2023 and 2024.
- **Income taxes paid** in FY2025: RMB 3.2bn (US$461m) in Chinese mainland (FY2025 20-F).
- iQIYI-related **PAG loan facilities** totalled up to US$523m plus US$114m (FY2025 20-F footnote references)—related-party complexity around the streaming subsidiary persists.
- Produced-content impairment at iQIYI: RMB 68m / 253m / 95m in 2022–2024 (FY2024 20-F).

**Balance sheet (Yahoo fallback, FY2025 year-end):**
- Total assets: RMB 449.2bn; total equity (incl. minority): RMB 289.7bn
- Cash and equivalents: RMB 24.6bn; short-term investments: RMB 90.7bn
- Total debt: RMB 97.1bn; net debt: RMB 64.9bn
- Tangible book: RMB 205.1bn

Liquidity remains strong in gross terms, but net debt rose from RMB 46.2bn (2024) to RMB 64.9bn (2025) as cash fell and debt increased. Long-term equity investments of RMB 24.6bn (plus available-for-sale securities) embed mark-to-market and impairment sensitivity.

**Cash flow (Yahoo fallback):**

| Year | Operating CF | CapEx | Free cash flow |
|------|-------------|-------|----------------|
| 2023 | 36.6bn | (11.3bn) | 25.3bn |
| 2024 | 21.2bn | (8.3bn) | 13.0bn |
| 2025 | (3.0bn) | (13.4bn) | **(16.4bn)** |

FY2025 operating cash flow turned negative, driven by a RMB 42.0bn working-capital outflow (Yahoo). This **conflicts** with the screen’s positive FCF input (~RMB 8.0bn), likely reflecting a different measurement window or pre-impairment basis—an important diligence flag for FCF Yield model validity.

**Interim / recent quarter (Yahoo fallback, labelled 2026 in cache — likely Q1 2026):**
- Revenue RMB 32.1bn vs RMB 32.7bn prior-year quarter (~flat)
- Net income RMB 3.4bn vs RMB 7.3bn (down ~53%)
- News headline: *“Baidu beats first-quarter forecasts as AI business drives strong growth (BIDU)”* (18 May 2026) — operational momentum in AI/cloud may be stabilising even as reported profitability compresses.

**Annual filing coverage:** Complete. **Interim filing coverage:** Filings exist but **financial tables are missing** from indexed body extracts; interim analysis relies on Yahoo and news headlines.

---

## RISKS AND RED FLAGS

**Corporate structure / VIE (20-F):** Baidu is a Cayman holding company; mainland operations run through VIE contractual arrangements that “have not been tested in the courts.” Deconsolidation would be material: “the value of the securities… diminish substantially or even become worthless.” No going-concern language was found in available body extracts.

**China regulatory and listing risk (20-F):** Extensive risk-factor disclosure on CSRC offshore filing rules, cybersecurity review, antitrust, and foreign-investment interpretation of VIE structures. HFCAA/PCAOB inspection risk is noted; PCAOB access was restored in 2022 and Baidu was removed as a Commission-Identified Issuer, but re-listing risk remains if access lapses.

**Earnings quality:** FY2025 impairments and negative operating cash flow undermine screen ROE (0.3%) and raise questions about recurring write-downs in the investment portfolio and iQIYI.

**iQIYI / related parties:** Continued funding and loan facilities to iQIYI (PAG facilities per 20-F) tie group fortunes to a struggling streaming asset; produced-content impairments are ongoing.

**Robotaxi regulation:** *“BIDU Stock In For A Rough Ride: China Reportedly Hits Brakes On Robotaxi Licenses After 100 Apollo Go Cars Stall In Wuhan”* (29 Apr 2026, Stocktwits)—policy risk to the Apollo narrative.

**Geopolitical / US defence list:** *“Pentagon said to have named Alibaba, Baidu, and BYD for inclusion in U.S. CMC list”* (26 Nov 2025, Seeking Alpha)—potential capital-markets and sentiment overhang.

**Governance:** Interim CFO (Junjie He) signs filings; audit committee chair transition (Brent Callinicos out, Xiaodan Liu in, Feb 2025, 6-K body). Dual-primary Hong Kong listing may improve governance perception but adds execution risk.

**Pension:** No pension-related disclosures surfaced in available extracts.

---

## NEWS HIGHLIGHTS

Coverage over the past year is **moderate-to-heavy**, skewed toward AI, listing, and robotaxi themes rather than deep fundamental analysis.

**Strategy / AI:**
- *“Will Baidu’s Hong Kong Dual-Primary Listing and Apple AI Deal Change Baidu's (BIDU) Narrative”* (17 Jul 2026, Yahoo Finance)
- *“Apple clears key hurdle for iPhone AI launch in China”* (15 Jul 2026) — Apple AI rollout in China involves Baidu as partner
- *“How Apple Is Boosting Baidu and Other Chinese Tech Stocks”* (16 Jul 2026, Barron’s)
- *“Baidu beats first-quarter forecasts as AI business drives strong growth (BIDU)”* (18 May 2026, Yahoo Finance)
- *“Alphabet's Waymo, Baidu Ahead of Competitors in Robotaxi Space, Wedbush Says”* (17 Jul 2026)

**Capital markets / listing:**
- *“Baidu Stock Rises 3.2% as Dual-Primary Listing Opens Path to China Investors”* (16 Jul 2026)
- *“Baidu (BIDU) Announces Dual Primary Listing on Hong Kong Stock E”* (16 Jul 2026, GuruFocus)
- 6-K filings (Mar 2025): proposed CNY-denominated senior notes (RMB 10bn priced, 6 Mar 2025) and exchangeable bonds

**Autonomous driving / M&A:**
- *“Uber and Lyft Partner With Baidu (BIDU) to Launch Driverless Taxi Trials in the UK”* (25 Dec 2025)
- *“Baidu Inc. (BIDU) Boosts Global Ride-Hailing Presence”* (20 Feb 2026)
- 6-K (25 Feb 2025): *“Baidu Acquires JOYY’s Live Streaming Business in China”*

**Analyst / flow:**
- JP Morgan maintained, PT lowered to $205 (17 Jul 2026, GuruFocus)
- Cathie Wood’s ARK bought BIDU (24 Sep / 24 Oct 2025, Investing.com)

**Regulatory concern:**
- *“Baidu CMC Listing Raises Questions On Policy Risk And Investor Sentiment”* (10 Jun 2026, simplywall.st)

---

## RESEARCH VERDICT

Verdict: accumulate  
Risk: high  
Confidence: 0.68  
Rationale: Deep research confirms the screen’s cheapness and balance-sheet support but weakens the buy case on FY2025 reported earnings, negative operating cash flow, and unresolved China/VIE/regulatory overhangs that screens underweight.

## INVESTMENT THESIS


## FINANCIAL REVIEW


## RISKS AND RED FLAGS


## NEWS HIGHLIGHTS
