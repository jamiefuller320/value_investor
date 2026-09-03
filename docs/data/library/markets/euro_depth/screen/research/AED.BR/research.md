# Aedifica NV/SA (AED.BR) — Research memo

_Version 1 · Updated 2026-09-03T07:14:23.571026+00:00 · Mode: initial_

## EXECUTIVE SUMMARY
Aedifica is a Belgian-listed healthcare real estate company whose shares screen as a buy on classic value metrics: P/E 6.6, P/B 0.83, and a ~5.9% dividend yield, with 12 of 22 quantitative models passing and a Piotroski F-Score of 8/9. The investment case rests on a scaled European portfolio of regulated healthcare assets, post-merger rental income growth, and cash generation that appears to cover distributions — but at the cost of elevated leverage, very weak reported liquidity, and earnings distorted by merger-related items. The central debate is whether headline cheapness reflects genuine mispricing of durable rental cash flows or a fair discount for balance-sheet risk, dividend sustainability, and integration uncertainty following the Cofinimmo combination. Primary regulatory filings were not retrieved in this pack, so conviction must remain provisional pending verified annual and interim disclosures.

## INVESTMENT THESIS
The quantitative screen flags Aedifica as a buy (composite 68%, sector-relative 72%), passing all five factor families: cheapness, quality, dividend, GARP, and risk. For a value investor, the hook is straightforward: the market prices the equity at a substantial discount to book (P/B 0.8) while the business generates positive operating cash flow (€318m in FY2025 per Yahoo), rising free cash flow (€220m vs €105m prior year), and a dividend yield near 6%. Models such as Graham Enterprising, Earnings Yield, FCF Yield, Low P/E + High Yield, Quality Value, and Dividend Growth all pass, suggesting the stock sits in the intersection of income and deep value.

Business quality indicators from the screen are mixed but net positive: ROE of 12.2% is adequate though below moat thresholds; debt/equity of ~75% is within the screen’s tolerance but fails Schloss and Buffett Quality tests; Piotroski 8/9 signals improving profitability, cash conversion, and declining leverage. Healthcare real estate — nursing homes, hospitals, and related regulated assets — offers structurally defensive demand, long lease terms, and inflation-linked rent escalators, which supports the screen’s quality and dividend passes. The failed models (Graham Defensive, Net-Net, Deep Value, Buffett Quality, Economic Moat, Financial Health, Acquirer’s Multiple) collectively flag weak liquidity (current ratio 0.22), high net debt/EBITDA, and statutory earnings decline of ~13%, tempering but not overturning the buy signal.

Relative to Real Estate sector peers in the screen universe (PFD.L, ABF.L, GRG.L, DRX.L, KGF.L), Aedifica ranks among the stronger passes on earnings quality (5/5 peers pass), FCF yield (4/5), and dividend growth (4/5), supporting a sector-relative overweight case rather than a deep-net-net special situation.

## FINANCIAL REVIEW
**Primary filings gap:** `filings_index.json` contains zero indexed filings (0 annual, 0 interim, 0 trading updates, 0 with body text). No annual report, half-year release, or ESEF extract is available for citation. All figures below are sourced from `financials_annual.json` (Yahoo Finance) and `screening_snapshot.json`; this is an explicit fallback. Quarterly income from Yahoo is noted where relevant; quarterly cash flow is empty (`ttm_cashflow_suppressed`).

**Income statement trends (Yahoo, EUR):**

| Metric | FY2025 | FY2024 | FY2023 | FY2022 |
|--------|--------|--------|--------|--------|
| Total revenue | €370.2m | €347.7m | €321.3m | €277.1m |
| Operating income | €312.1m | €290.3m | €265.8m | €229.7m |
| EBITDA | €353.6m | €291.7m | €73.2m | €415.0m |
| Net income | €244.4m | €204.8m | €24.5m | €331.8m |
| Diluted EPS | €5.14 | €4.31 | €0.56 | €8.51 |
| Interest expense | €66.9m | €83.4m | €72.6m | €25.1m |

Revenue has grown steadily (+34% from FY2022 to FY2025), and FY2025 net income rose 19% year-on-year to €244.4m, with EPS up to €5.14. FY2023 was an outlier (net income €24.5m) driven by large unusual items and investment securities gains/losses (€195m gain in FY2023; €54m loss in FY2025 per cash flow statement), indicating reported earnings are materially influenced by fair-value movements and non-recurring charges — a pattern that primary filings would need to reconcile under EPRA/NAV metrics.

**Cash flow (Yahoo, EUR):**

| Metric | FY2025 | FY2024 | FY2023 |
|--------|--------|--------|--------|
| Operating cash flow | €317.8m | €248.5m | €229.5m |
| CapEx | (€97.5m) | (€143.9m) | (€260.7m) |
| Free cash flow | €220.4m | €104.6m | (€31.2m) |
| Cash dividends paid | (€185.6m) | (€166.9m) | (€116.0m) |

FCF improved sharply in FY2025, and gross dividend payments of €185.6m were covered ~1.2× by reported FCF (€220.4m). The screen’s canonical FCF of ~€299m (TTM fallback) would imply stronger coverage, but quarterly cash flow data is unavailable to reconcile the difference. Operating cash flow consistently exceeds net income (supporting Piotroski “OCF > net income”), a positive earnings-quality signal.

**Balance sheet (Yahoo, EUR, FY2025):**

- Total assets: €6,477m; investment properties: €6,216m (~96% of assets)
- Stockholders’ equity: €3,664m; tangible book: €3,603m
- Total debt: €2,570m; net debt: €2,463m
- Cash & equivalents: €22m (very low)
- Current assets: €134m vs current liabilities: €619m → current ratio ~0.22
- Working capital: (€485)m

Leverage is substantial: debt/equity ~75%, with €551m of debt classified as current against only €22m cash. For a property REIT, negative working capital and low cash are not uncommon given asset-heavy structures and revolving facilities, but the Financial Health model failure and weak current ratio warrant covenant and liquidity schedule review from primary filings — unavailable here.

**Interim / quarterly (Yahoo quarterly income only):**

- Q1 FY2026 (period ended 31 Mar 2026): revenue €118.2m; net income €432.3m; diluted EPS €7.67 — an extreme spike versus Q1 FY2025 (EPS €1.32, net income €62.8m), consistent with merger-related fair-value or consolidation effects rather than recurring operating performance.
- Q4 FY2025 (31 Dec 2025): revenue €90.3m; net income €50.3m.
- H1 FY2025 quarters show stable quarterly revenue ~€90m and net income ~€50m per quarter.

A TradingView headline (1 Sep 2026) references EPRA EPS up 5% and rental income up 62% following the Cofinimmo merger, aligning with the step-change in scale, but the underlying press release body is not in the filing pack. No half-year or trading-update filing text is indexed.

**Key gaps:** No audited annual report, no interim results body, no EPRA NAV bridge, no lease maturity table (`ir_presentation_metrics.json` is empty), and no covenant or going-concern language from regulatory filings. Verify-before-trade is essential.

## RISKS AND RED FLAGS
**Leverage and liquidity:** Net debt of ~€2.46bn against EBITDA of ~€354m implies net debt/EBITDA of roughly 7× on Yahoo figures — above typical comfort for leveraged income strategies. Cash of €22m against €551m current debt and a current ratio of 0.22 signals refinancing and covenant dependency. The screen fails Financial Health, Graham Defensive, and Schloss models on these grounds.

**Dividend sustainability:** FY2025 dividends (€186m) consume most of reported FCF (€220m). Simply Wall St coverage (2 Sep 2026) explicitly flags “dividend strain.” Any FCF normalisation post-merger or higher interest costs could compress coverage quickly. FCF/dividend coverage metrics are null in the screen snapshot.

**Earnings quality and merger integration:** Statutory earnings growth is −12.7% on a TTM basis per the screen. FY2023–FY2025 earnings include large fair-value and special-item swings (e.g. €276m special charges in Q4 FY2025 income statement). The Cofinimmo merger adds integration, synergy realisation, and potential goodwill/intangible risks (goodwill €60m at FY2025). Q1 FY2026 EPS of €7.67 is not representative of run-rate earnings.

**Interest-rate and regulatory exposure:** As a healthcare property owner across European jurisdictions, Aedifica faces regulated rent regimes, occupancy rules, and government funding dynamics for care providers (tenant credit risk). Rising or persistently elevated rates pressure asset valuations and refinancing costs; derivative liabilities of €7m (FY2025) suggest some hedging but detail is absent.

**Valuation nuance:** EV/EBIT of ~38× fails the Acquirer’s Multiple test — likely reflecting REIT-specific EBIT definition and merger-distorted earnings rather than pure operating multiples. P/E of 6.6 may understate economic reality if current earnings are inflated by one-offs.

**Governance / filing transparency:** Zero regulatory filing bodies retrieved under the euro_filings regime limits ability to assess going-concern statements, contingent liabilities, pension obligations, or debt covenants. This is itself a research red flag.

RiskTags: leverage, liquidity, regulatory, accounting, competitive
RiskTags: leverage, liquidity, regulatory, accounting, competitive

## NEWS HIGHLIGHTS
News coverage for Aedifica specifically is **thin**; most manifest entries match the ticker “AED” to UAE dirham content and are irrelevant. Material items:

- **“Aedifica (ENXTBR:AED) Stock Draws Value Hunters Despite Debt And Dividend Strain”** (Simply Wall St, 2 Sep 2026) — frames the current value-versus-risk debate.
- **“AED: EPRA Earnings per share up 5% and rental income up 62% following the Cofinimmo merger”** (TradingView, 1 Sep 2026) — key strategic event: merger with Cofinimmo, significant rental income uplift; primary release not indexed.
- **“Aedifica: Target Price Consensus and Analysts Recommendations | AED | BE0003851681”** (MarketScreener, 31 Mar 2026) — analyst coverage exists but detail not in manifest body.
- **“Assessing Aedifica (ENXTBR:AED): Is the Current Valuation Justified After Recent Share Price Movements?”** (Yahoo Finance, 9 Sep 2025) — valuation-focused commentary; no discrete corporate event.

No indexed news on management changes, regulatory enforcement, or M&A beyond the Cofinimmo merger headline. Alternate-news query for pension/covenant/going-concern returned no Aedifica-specific results.

## RESEARCH VERDICT
Verdict: accumulate
Risk: medium
Confidence: 0.55
Rationale: Quantitative cheapness and cash-flow quality partially confirm the buy signal, but absent primary filings, weak liquidity, leverage, and merger-distorted earnings prevent full confirmation of the screen’s buy case.
