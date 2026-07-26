# Ackermans & Van Haaren NV (ACKB.BR) — Research memo

_Version 1 · Updated 2026-07-26T17:32:45.837994+00:00 · Mode: initial_

## EXECUTIVE SUMMARY
Ackermans & Van Haaren is a Belgian listed holding company in Industrials, currently flagged as a **buy** on the quantitative screen (8/22 models; composite 58%; P/E 14.7, P/B 1.5, ROE 11.0%, dividend yield 1.7%). The value case rests on moderate absolute valuation, a Piotroski F-Score of 7/9, and passes across cheapness, quality, dividend, GARP, and risk factor families — though it fails several defensive and financial-health screens. Yahoo-sourced accounts show group earnings and EBITDA recovering through 2025 after a weaker 2023–24, but revenue dipped slightly year-on-year and free cash flow normalised sharply from an unusually strong 2024. The central debate is whether consolidated operating momentum and dividend capacity at the holding level justify the balance-sheet complexity — net debt of c.€8.8bn, negative working capital, and substantial minority interests — without primary annual or interim filing verification. News flow is thin and largely sentiment-driven; conviction on the screen signal should be treated as provisional pending Euronext/ESEF filing ingestion.

## INVESTMENT THESIS
For a value investor, ACKB offers a diversified industrial holding at a sub-market multiple rather than a pure-play operating company. The screen’s buy rating is driven by intersecting signals: **Graham Enterprising**, **FCF Yield**, **Lynch PEG**, **Neff PEGY**, **Dividend Growth**, **Magic Formula**, **Piotroski F-Score (7/9)**, and **Earnings Quality** — five factor families passed with full data quality (20/20 metrics). Key headline metrics — P/E 14.7, P/B 1.52, debt/equity 30%, FCF c.€541m — sit comfortably inside enterprising-value thresholds without deep distress pricing.

Business quality, as inferred from Yahoo consolidated accounts (no filing bodies available), shows operating income rising from €422m (2023) to €569m (2024) to €622m (2025), and EBITDA from €1.05bn to €1.54bn over the same span. Parent-company net income recovered to €593m in 2025 from €460m in 2024 and €399m in 2023, supported by dividend income from subsidiaries (€240m received in operating cash flow, 2025). The holding structure — long-term equity investments of €2.25bn, minority interests of €1.62bn, and recurring dividend upstream — is consistent with a compounding conglomerate model rather than a cyclical single-asset bet. The screen’s **improving** trend and **new** stability label (one week at signal; conviction score 36%) suggest the name has only recently re-entered model territory, which may offer entry before broader recognition — but also limits historical signal persistence as confirmation.

What the screen does *not* fully capture is holding-company opacity: consolidated figures blend operating subsidiaries, fair-value movements, and portfolio transactions (€535m business purchases in 2025 per cash-flow statement). A value buyer is effectively underwriting management’s capital allocation across stakes — attractive at 1.5× book and ~15× earnings if ROE and FCF generation are sustainable, less compelling if 2024’s €1.1bn FCF was an anomaly and leverage continues to rise (Piotroski “leverage declining” failed).

## FINANCIAL REVIEW
**Primary filings gap:** `filings_index.json` (regime: `euro_filings`) contains **zero** entries — no annual reports, no interim/half-year releases, and no downloadable body extracts under `filings/bodies/`. Interim and annual primary-source analysis is therefore **not possible** in this pack. All figures below are sourced from **`financials_annual.json` (Yahoo Finance)** and are stated explicitly as fallback. Quarterly income data in that file is empty.

**Income statement trend (Yahoo, consolidated, €000s unless noted)**

| Metric | 2022 | 2023 | 2024 | 2025 |
|--------|------|------|------|------|
| Revenue | 4,401,420 | 5,221,554 | 6,043,334 | 5,961,612 |
| Operating income | 292,271 | 421,700 | 568,687 | 621,853 |
| EBITDA | 1,286,540 | 1,053,415 | 1,248,085 | 1,540,372 |
| Net income (parent) | 708,655* | 399,194 | 459,871 | 592,548 |
| Diluted EPS (€) | 21.37* | 12.12 | 14.05 | n/a |

\*2022 parent net income and EPS are elevated by large unusual items (+€373m); normalised income that year was c.€380m per Yahoo.

Revenue grew strongly from 2022 to 2024 (+37%) but **edged down 1.4% in 2025** to €5.96bn. Profitability nonetheless improved: operating margin expanded and net income rose **29% YoY** in 2025. Group net income including non-controlling interests reached €779m (2025) vs €603m (2024). The gap between group and parent earnings (minority interests of €186m in 2025) reflects the partially owned subsidiary structure typical of AVH.

**Cash flow and capital allocation (Yahoo)**

| Metric | 2022 | 2023 | 2024 | 2025 |
|--------|------|------|------|------|
| Operating cash flow | 716,635 | 619,195 | 1,410,204 | 1,005,382 |
| CapEx | (514,530) | (433,989) | (310,160) | (469,425) |
| Free cash flow | 202,105 | 185,206 | 1,100,044 | 535,957 |
| Cash dividends paid | (91,085) | (102,511) | (111,301) | (124,432) |

FCF was **highly volatile**: a spike to €1.1bn in 2024 (working-capital release of €321m) normalised to €536m in 2025 as receivables absorbed cash (change in receivables: −€432m). 2025 investing outflows included **€535m in business acquisitions** and €469m capEx. Dividends paid at the parent level rose steadily to €124m, consistent with the screen’s Dividend Growth pass — though yield at 1.7% remains modest and the model **High Dividend Yield** failed.

**Balance sheet (Yahoo, year-end)**

| Metric | 2024 | 2025 |
|--------|------|------|
| Total assets | 20,291,367 | 21,263,042 |
| Stockholders’ equity | 5,278,248 | 5,701,080 |
| Total debt | 9,953,790 | 10,444,792 |
| Net debt | 8,326,712 | 8,760,963 |
| Working capital | (2,575,930) | (2,514,272) |
| Long-term equity investments | 2,149,654 | 2,246,407 |
| Minority interest | 1,537,881 | 1,618,825 |
| Cash & equivalents | 1,383,262 | 1,463,531 |

Net debt rose c.€434m in 2025; total debt exceeds equity by roughly 1.8× on a gross basis. **Working capital remains deeply negative** (~€2.5bn), driven by large current liabilities including c.€7.4bn current debt — a structural feature that warrants filing-level covenant and maturity disclosure, which is absent here. Non-current pension obligations are c.€65m (2025). Screen-reported debt/equity of 30% likely reflects a narrower definition at parent level; consolidated gross leverage is materially higher.

**Quality indicators:** Piotroski components confirm positive net income, positive OCF, OCF > net income, improving current ratio, no dilution, and improving gross margin — but **flag rising leverage and flat asset turnover**, aligning with the screen’s **Financial Health** failure.

**Interim coverage:** No half-year or trading-update filings are indexed; intra-year momentum cannot be verified from primary sources.

## RISKS AND RED FLAGS
**Source limitation:** Without filing body extracts, regulatory risk language (going concern, contingencies, covenant headroom, related-party transactions) **cannot be assessed** from this pack. The following risks are inferred from Yahoo accounts and screen outputs only.

1. **Balance-sheet complexity and leverage.** Net debt of c.€8.8bn against EBITDA of c.€1.54bn implies ~5.7× gross leverage on a consolidated basis; current debt of c.€7.4bn raises refinancing and liquidity monitoring requirements. The screen’s failed **Financial Health** model and Piotroski “leverage declining = false” corroborate this concern.

2. **Holding-company opacity.** €1.62bn minority interests and €2.25bn long-term equity investments mean parent earnings and group earnings diverge materially; portfolio fair-value swings and M&A (€535m acquisitions in 2025) can distort year-on-year comparability — as seen in 2022’s unusual-item-driven EPS spike.

3. **FCF volatility and working capital.** Negative working capital and large swings in receivables/other current assets (other receivables c.€4.5bn in 2025) make FCF an unreliable single-year metric; 2024’s €1.1bn FCF overstates normalised generation.

4. **Revenue deceleration.** The 2025 revenue decline of 1.4% may signal end-market softness in one or more operating verticals; without segment disclosure from filings, drivers are unidentified.

5. **Dividend vs. total return.** Yield of 1.7% is low for income-focused value mandates; the March 2026 headline of a **€150m special dividend for the 150th anniversary** (Trends-Tendances, 4 Mar 2026) suggests episodic returns rather than high ongoing yield — positive for total return, but not captured as a recurring yield screen pass.

6. **Governance and cyclical exposure.** As a long-duration Belgian family-linked holding, strategic decisions (portfolio rotation, capital calls at unlisted stakes) carry limited public interim disclosure in this data set. Cyclical exposure across marine construction, environmental services, and private-equity-like activities (inferred from typical AVH portfolio composition, **not verified in this pack**) could amplify downturn sensitivity.

7. **Valuation after multi-year run.** Yahoo Finance commentary (6 Jun 2026) notes the share at €267.8 with +19.6% one-year and +15.1% YTD returns, questioning remaining value — a sentiment risk if re-rating has front-run fundamentals.

## NEWS HIGHLIGHTS
News coverage in `news_manifest.json` is **thin** (five articles over the past year; one is a false match). Material items:

- **“Ackermans & van Haaren : 150 millions d’euros de dividendes pour les 150 ans du holding”** — Trends-Tendances, **4 March 2026.** Special dividend of €150m linked to the company’s 150th anniversary; signals shareholder-friendly capital return but is non-recurring.

- **“Ackermans & van Haaren monte sur des propos positifs de KBC Securities”** — Zonebourse, **15 July 2026.** Share rose on favourable sell-side commentary from KBC Securities; no operational detail in the manifest summary.

- **“Is It Time To Reassess Ackermans & Van Haaren (ENXTBR:ACKB) After Its Strong Multi‑Year Run?”** — Yahoo Finance, **6 June 2026.** Highlights strong recent share-price performance (+19.6% over one year) and asks whether valuation still offers margin of safety at €267.8.

- **“Ackermans & Van Haaren (ENXTBR:ACKB): Exploring Valuation After Recent Share Price Momentum”** — Yahoo Finance, **20 September 2025.** Similar valuation-reassessment framing after price momentum.

No manifest entries cover management changes, regulatory actions, or disposals/acquisitions by name. One article (**“American Express Co (AXPCL) - MSN”**, 21 July 2026) is **irrelevant** to ACKB. Overall, news flow is insufficient to corroborate or challenge the quantitative thesis beyond dividend signalling and broker sentiment.

## RESEARCH VERDICT
Verdict: accumulate
Risk: medium
Confidence: 0.58
Rationale: Yahoo-backed accounts show earnings and EBITDA recovery with reasonable valuation multiples that broadly support the screen’s buy signal, but absent primary filings, thin news, volatile FCF, and elevated consolidated leverage prevent full confirmation and warrant a staged rather than high-conviction entry.
