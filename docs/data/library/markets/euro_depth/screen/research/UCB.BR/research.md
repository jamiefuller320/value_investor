# UCB (UCB.BR) — Research memo

_Version 1 · Updated 2026-08-21T21:44:21.900011+00:00 · Mode: initial_

## EXECUTIVE SUMMARY
UCB S.A. (ENXTBR:UCB) is a Belgian biopharmaceutical group in a growth inflection driven by Bimzelx (bimekizumab) and a neurology/immunology portfolio, with the quantitative screen rating the name a buy (10/22 models; composite 55%). The value hook is quality-plus-GARP: strong earnings momentum (Yahoo: net income USD 1.56bn in FY2025 vs USD 1.07bn in FY2024), a perfect Piotroski F-Score (9/9), and low PEG metrics (PEG 0.15), offset by rich absolute valuation (P/E 19.6, FCF yield 2.6%, fails Graham/deep-value screens). The central debate is whether pipeline-led growth and recent M&A (Candid, Neurona) justify a premium multiple, or whether legacy-product erosion, rising H2 costs, and “no-moat” competitive dynamics (Morningstar, 31 Jul 2026) cap upside. Primary regulatory filings were not retrieved in this pack—a material verification gap.

## INVESTMENT THESIS
The screen’s buy signal rests on five passing factor families—cheapness (relative), quality, dividend, GARP, and risk—not classic deep value. UCB passes Lynch PEG, Neff PEGY, Quality Value, Buffett Quality, Economic Moat, Dividend Growth, Magic Formula, Piotroski F-Score, Earnings Quality, and Financial Health. Statutory earnings growth of ~135% (screen input) reflects the step-change from FY2023 net income of USD 343m to FY2025 USD 1.56bn (Yahoo fallback), as Bimzelx scaled and operating leverage improved. ROE of 20.6% and operating cash flow of USD 2.29bn (screen TTM) indicate a business converting growth to cash, with debt/equity of ~31% and a current ratio of 1.38 supporting the Financial Health pass.

For a value investor, the case is not net-net or asset-based; it is “quality at a reasonable growth price.” The company fails Graham Defensive, Deep Value, FCF Yield, and Acquirer’s Multiple (EV/EBIT 22.1), signalling the market already prices success. The opportunity is that reported fundamentals may still lag the product cycle: H1 2026 net sales rose 23% to EUR4.1bn with Bimzelx at EUR1.5bn (yfinance headline, 1 Aug 2026), and guidance was upgraded—yet the share price has traded below its 2026 start (Ad-hoc-news.de, 19 Aug 2026), suggesting sentiment lagging fundamentals. Balance-sheet repair (net debt reduced; cash USD 2.25bn vs total debt USD 2.25bn at FY2025 year-end per Yahoo) adds optionality for bolt-on M&A already underway.

## FINANCIAL REVIEW
**Primary filings gap.** `filings_index.json` contains zero annual, interim, or other entries and no body extracts under `filings/bodies/`. All figures below are sourced from `financials_annual.json` (Yahoo); interim/H1 2026 operating metrics are referenced from news headlines only and cannot be reconciled to filing text in this pack.

**Income statement trend (Yahoo, USD).**

| Year | Revenue | Operating income | Net income | Diluted EPS |
|------|---------|------------------|------------|-------------|
| 2025 | 7,741m | 2,004m | 1,558m | 8.03 |
| 2024 | 6,152m | 846m | 1,065m | n/a |
| 2023 | 5,252m | 633m | 343m | 1.76 |
| 2022 | 5,517m | 701m | 418m | 2.14 |

Revenue grew ~26% in FY2025 and net income ~46%, continuing the recovery from the FY2023 trough. Gross margin expanded (gross profit USD 5,751m on revenue USD 7,741m in 2025 vs USD 4,400m on USD 6,152m in 2024). R&D remained elevated at USD 1,822m (24% of revenue), consistent with a pipeline-led pharma model. EBITDA was USD 2,577m in 2025 vs USD 1,963m in 2024.

**Balance sheet (Yahoo, FY2025).** Total assets USD 18.16bn; shareholders’ equity USD 10.87bn; total debt USD 2.25bn; cash and equivalents USD 2.25bn (roughly net-cash at year-end). Goodwill and intangibles total USD 8.54bn (~47% of assets), leaving tangible book value of USD 2.33bn. Non-current pension and post-retirement obligations: USD 159m. Working capital: USD 1.65bn.

**Cash flow (Yahoo, USD).**

| Year | Operating CF | CapEx | Free CF | Dividends paid |
|------|-------------|-------|---------|----------------|
| 2025 | 2,291m | 449m | 1,842m | 264m |
| 2024 | 1,242m | 322m | 920m | 259m |
| 2023 | 761m | 316m | 445m | 252m |

FCF more than doubled in two years; FY2025 FCF comfortably covered dividends (~7× gross coverage). The company repaid USD 641m of long-term debt and repurchased USD 121m of stock in 2025. OCF exceeded net income in 2025 (USD 2.29bn vs USD 1.56bn), supporting the screen’s earnings-quality pass.

**Interim / H1 2026 (news only; not in filings index).** Yahoo Finance headline (1 Aug 2026) cites H1 2026 net sales growth of 23% to EUR4.1bn, Bimzelx revenue doubling to EUR1.5bn, and upgraded full-year guidance. Reuters (30 Jul 2026) noted shares fell despite the guidance upgrade as the CEO flagged higher second-half costs. These interim figures cannot be audited against filing bodies in this pack.

**Data quality notes.** The screen reports dividend yield of 67.0% (`dividend_yield_raw`: 0.67), which is inconsistent with USD 264m dividends on ~194m diluted shares and a EUR246 share price; treat as a likely data error. Quarterly cash-flow series are empty (`ttm_cashflow_suppressed`: true). No IFRS 16 lease maturity or segment splits were extracted (`ir_presentation_metrics.json` empty).

## RISKS AND RED FLAGS
**Competitive and pipeline.** Morningstar (31 Jul 2026) classifies UCB as “no-moat,” with growth products offsetting declining legacy-drug sales—a profile screens do not fully capture. Valuation increasingly depends on Bimzelx, FINTEPLA, and pipeline assets (e.g. new Lennox–Gastaut data, simplywall.st, 19 Aug 2026).

**M&A and integration.** UCB agreed to acquire Candid Therapeutics for up to USD 2.2bn (Genetic Engineering & Biotechnology News, 5 May 2025) and Neurona Therapeutics for up to USD 1.2bn (BioPharma Dive, 17 Apr 2025). These expand TCE/cell-therapy exposure but add execution risk, goodwill pressure, and integration cost—potentially linked to the CEO’s H2 cost warnings (Reuters, 30 Jul 2026).

**Regulatory.** Standard pharma exposure: approval timelines, label expansions, pricing/reimbursement, and pharmacovigilance. No filing-body language on contingencies or going-concern was available to review.

**Balance sheet.** Large intangible base (USD 8.54bn) creates impairment sensitivity if pipeline assets underperform. Pension/post-retirement liabilities of USD 159m (non-current) are modest relative to equity but unverified in annual-report narrative.

**Governance / capital allocation.** Active share buybacks (UCB announcements, Mar/Apr 2025) and divestiture of the China drug business to CBC Group/Abu Dhabi wealth fund (Asia Asset Management, 11 Mar 2025) reflect strategic repositioning; benefits depend on reinvestment returns from acquired assets.

**Verification gap.** Absence of annual report and interim filing bodies means covenants, litigation reserves, related-party transactions, and auditor emphasis-of-matter paragraphs could not be assessed. Proceed with verify-before-trade discipline.

RiskTags: competitive, regulatory, leverage, key_person, accounting, other
RiskTags: competitive, regulatory, leverage, key_person, accounting, other

## NEWS HIGHLIGHTS
Coverage over the past year is adequate for a large-cap pharma name, though Google News queries frequently conflate UCB S.A. with unrelated “UCB” tickers (US regional banks, Bangladesh banks); material items below are filtered to UCB S.A./ENXTBR:UCB.

**Results and guidance.** H1 2026 earnings (yfinance, 1 Aug 2026): record sales, Bimzelx at EUR1.5bn, guidance upgraded. FY2025 results (yfinance, 3 Mar 2026; UCB press release “Strong Execution Fueling Sustained Company Growth,” 26 Feb 2026): record growth narrative. Market reaction was sceptical—Endpoints News (31 Jul 2026) and Reuters (30 Jul 2026) reported the stock falling despite beats, citing concern that guidance may be too optimistic and higher H2 costs.

**Pipeline and data.** Fierce Pharma (27 Feb 2026): Bimzelx crossed blockbuster threshold in hidradenitis suppurativa. Neurology focus at AAN 2026 with 21 abstracts (yfinance, Apr 2026). FINTEPLA Lennox–Gastaut data (simplywall.st, 19 Aug 2026).

**M&A and portfolio.** Candid (up to USD 2.2bn, May 2025) and Neurona (up to USD 1.2bn, Apr 2025) expand immunology/neurology. China commercial business divestiture (Mar 2025). Ongoing share repurchases (Mar/Apr 2025).

**Valuation commentary.** GuruFocus (19 Aug 2026): “7.2% overvalued” on GF Value with dividend sustainability questions. Ad-hoc-news.de (19 Aug 2026): stock below 2026 start, valuation “leans on pipeline expectations.” Zacks upgrades to Strong Buy (Apr/Sep 2025) sit alongside StockStory “3 Reasons to Avoid UCB” (17 May 2025).

**Noise to ignore.** United Community Banks (US), United Commercial Bank (Bangladesh), and similar headlines are ticker collisions, not relevant to ENXTBR:UCB.

## RESEARCH VERDICT
Verdict: accumulate
Risk: medium
Confidence: 0.58
Rationale: Deep research broadly confirms the screen’s quality-and-GARP buy case—strong earnings/FCF trajectory and Bimzelx-led growth—but primary filing absence, rich absolute valuation, M&A execution risk, and sceptical post-results market reaction prevent full confirmation of the quantitative signal.
