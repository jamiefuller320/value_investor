# Novabase S.G.P.S., S.A. (NBA.LS) — Research memo

_Version 1 · Updated 2026-08-23T06:17:29.103233+00:00 · Mode: initial_

## EXECUTIVE SUMMARY
Novabase S.G.P.S., S.A. (NBA.LS) is a Lisbon-listed technology group that screens as a buy on cheapness, dividend, GARP, and risk families (4/22 models; composite 59%), driven chiefly by a headline 15.3% dividend yield and 21.4% ROE. The quantitative overlay already downgrades the raw signal to Hold because FCF yield is missing and earnings-quality checks fail. Deep research cannot corroborate the case from primary filings: the euro filings index contains zero annual or interim entries and no body extracts. Yahoo fallback data shows improving continuing operations (FY2025 operating income €11.4m; continuing net income €12.5m) but sharply lower revenue (€124.5m, −7% YoY), heavy special-dividend distributions (€47.3m cash dividends in FY2025 vs €6.2m FCF), and a balance sheet increasingly reliant on receivables. The central debate is whether recent portfolio reshaping and capital returns mask a structurally thin-margin IT services business trading at P/E 28.8 and P/B 8.6, with a dividend policy that screens well but looks hard to sustain from recurring cash flow.

## INVESTMENT THESIS
The screen flags Novabase as a buy because it passes Neff PEGY (PEGY 0.02, incorporating the elevated yield), High Dividend Yield (15.3%), Magic Formula, and Financial Health, with moderate leverage (debt/equity 32%) and a current ratio of 1.67. For a value investor, the apparent hook is a cash-generative, asset-light technology services platform returning substantial capital to shareholders while reporting strong ROE.

Business quality, as inferable from Yahoo annual data only, is mixed. Continuing operations strengthened in FY2025—EBITDA rose to €19.6m from €13.9m in FY2024, and operating income reached €11.4m—but revenue retreated 7% to €124.5m after two years of growth. Gross margin held near 45%, yet operating margins remain below 10%, failing moat and quality screens. The FY2023 step-change in reported net income (€47.1m) was dominated by €44.0m from discontinued operations, consistent with a holding-company model of periodic asset sales rather than steady compounding. FY2025 free cash flow turned positive at €6.2m (from −€3.0m in FY2024), which supports the Financial Health pass, but cash fell from €62.7m to €30.7m as dividends and financing outflows absorbed disposal proceeds.

The buy case therefore rests on screening optics—high yield, low PEGY, acceptable leverage—rather than classic deep value (P/B 8.6, earnings yield 3.5%) or quality compounding. Without regulatory filing confirmation of dividend policy, segment mix, or recurring earnings power, the screen signal is suggestive but not fully validated.

## FINANCIAL REVIEW
Primary source gap: `filings_index.json` lists zero filings (0 annual, 0 interim, 0 trading updates; regime `euro_filings`). No body extracts exist under `filings/bodies/`. All figures below are from `financials_annual.json` (Yahoo); interim/quarterly data are absent (`quarterly_income` and `quarterly_cashflow` empty).

Revenue and profitability (Yahoo, FY2022–FY2025):
- Revenue: €120.4m → €132.6m → €134.2m → €124.5m (FY2025 −7.3% YoY).
- Operating income: €5.8m → €7.5m → €6.7m → €11.4m.
- EBITDA: €9.1m → €10.9m → €13.9m → €19.6m.
- Reported net income: €8.9m → €47.1m → €6.4m → €5.5m; continuing-operations net income: €3.7m → €3.4m → €6.6m → €12.5m.
- Diluted EPS: €0.30 → €1.71 → €0.21 → €0.14 (distorted by FY2023 disposal gains and FY2025 discontinued loss of €4.2m).

Balance sheet (FY2025 Yahoo):
- Total assets €128.8m; cash €30.7m (down from €62.7m in FY2024 and €80.3m in FY2023).
- Accounts receivable €39.9m (~31% of assets).
- Total debt €15.5m (long-term debt €4.0m; capital lease obligations €9.2m); common equity €50.4m; debt/equity ~31%.
- Current pension/post-retirement obligation €10.0m (current liabilities).
- Share count rose to ~37.7m ordinary shares (from ~35.1m in FY2024), following €14.0m gross equity issuance in FY2025 and €38.0m in FY2024.

Cash flow and dividends (Yahoo):
- Operating cash flow (direct method line): €8.1m in FY2025; FCF €6.2m (capex €1.9m).
- Cash dividends paid: €13.1m (FY2022), €11.0m (FY2023), €46.3m (FY2024), €47.3m (FY2025).
- FY2023 investing inflows included €48.9m business disposal proceeds; FY2025 €1.8m sale of business.
- FCF covered only ~13% of FY2025 dividends; cumulative distributions far exceed recurring FCF, implying reliance on balance-sheet cash and non-recurring proceeds.

Screening alignment: ROE 21.4% and leverage support the risk-family pass; Piotroski F-Score 4/9 (failed on operating cash flow, OCF > net income, current ratio trend, dilution, gross margin). Earnings-quality overlay failures (weak cash conversion, high accruals) are consistent with receivables build and dividend-heavy financing. No annual report or half-year release is available in the index to reconcile IFRS 16 lease maturity, segment splits, or management guidance (`ir_presentation_metrics.json` also empty).

## RISKS AND RED FLAGS
- Dividend sustainability: FY2025 cash dividends (€47.3m) dwarf FCF (€6.2m) and reported net income (€5.5m); the 15.3% screen yield likely reflects extraordinary distributions, not a recurring coupon—consistent with the screen’s dividend-yield overlay downgrade to Hold.
- Earnings quality: Piotroski 4/9; operating cash flow failed screen checks; large receivables (€39.9m) versus cash (€30.7m) raise working-capital and recognition risk—unverifiable without CMVM/Euronext filings.
- Portfolio/holding structure: material discontinued operations (FY2023 gain €44.0m; FY2025 loss €4.2m) make headline earnings volatile and complicate forward estimates.
- Dilution: share issuance in FY2024–FY2025 increased the share base; Piotroski “no share dilution” failed.
- Valuation: P/E 28.8 and P/B 8.6 fail deep-value and Graham criteria; earnings yield 3.5% is unattractive for a value mandate.
- Leverage and pensions: moderate financial debt, but €9.2m lease obligations and €10.0m current pension-related liability add fixed commitments not fully stress-tested here.
- Cyclical/customer concentration: IT services revenue fell 7% in FY2025; no segment or customer disclosure in available sources.
- Evidence gap: zero indexed regulatory filings; no going-concern, covenant, or contingency language available from primary sources.

RiskTags: accounting, liquidity, governance, cyclical, other
RiskTags: accounting, liquidity, governance, cyclical, other

## NEWS HIGHLIGHTS
Company-specific news coverage is very thin. Google News queries returned predominantly false positives on “NBA” (US basketball), not Novabase S.G.P.S.

Relevant yfinance commentary only:
- 8 May 2026 — “Here's Why We Think Novabase S.G.P.S (FRA:NVQ) Is Well Worth Watching” (positive tone; growth/watchlist framing).
- 11 Feb 2026 — “Novabase S.G.P.S., S.A. (FRA:NVQ) Is Up But Financials Look Inconsistent” (flags inconsistent financials despite share-price rise).
- 14 Jan 2026 — “Returns On Capital Are Showing Encouraging Signs At Novabase S.G.P.S (FRA:NVQ)” (positive on capital returns).
- 18 Dec 2025 — “Exploring Aplicaciones y Tratamiento de Sistemas And 2 Other European Small Caps with Solid Foundations” (Novabase mentioned among European small caps).
- 4 Dec 2025 — “Novabase S.G.P.S' (FRA:NVQ) investors will be pleased with their incredible 303% return over the last five years.”
- 6 Nov 2025 — “Undiscovered Gems in Europe for November 2025.”
- 3 Sep 2025 — “Is Novabase S.G.P.S., S.A.'s (FRA:NVQ) Stock Price Struggling As A Result Of Its Mixed Financials?”

No material headlines on strategy shifts, management changes, regulatory actions, or M&A were identified in the manifest. Treat news flow as insufficient for event-driven conviction.

## RESEARCH VERDICT
Verdict: caution
Risk: medium
Confidence: 0.48
Rationale: Deep research weakens the quantitative buy case: primary filings are absent, the headline dividend yield is not supported by recurring FCF, and earnings-quality flags persist despite improving continuing-operation profitability.
