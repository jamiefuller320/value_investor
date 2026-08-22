# VIENNA INSURANCE GROUP AG (VIG.VI) — Research memo

_Version 1 · Updated 2026-08-21T22:11:29.394057+00:00 · Mode: initial_

## EXECUTIVE SUMMARY
Vienna Insurance Group (VIG) screens as a buy on cheapness, quality, dividend, GARP, and risk families, with a composite score of 65% (sector-relative 62%) at roughly 10.9× P/E, 1.3× P/B, 2.5% yield, and 12.4% ROE. The value case rests on a diversified Central and Eastern European (CEE) insurer trading below many Western peers, with earnings and operating cash flow improving materially in the latest reported year. The central debate is whether headline multiples and Yahoo-derived trends reflect true underwriting and solvency strength, or whether insurer-specific metrics (combined ratio, embedded value, investment spread) are obscured by the absence of annual report and interim filing bodies in the research pack. Conviction is constrained by zero indexed regulatory filings and news noise from ticker collision with the Vanguard VIG ETF.

## INVESTMENT THESIS
The quantitative screen flags VIG as a buy across five factor families—cheapness, quality, dividend, GARP, and risk—passing 11 of 22 models including Graham Enterprising, Earnings Yield, FCF Yield, Lynch/Neff PEG variants, Quality Value, Dividend Growth, Acquirer's Multiple, Dreman Contrarian, and Earnings Quality. At 10.9× P/E and 1.3× P/B with 12.4% ROE and 2.5% dividend yield, the stock offers a classic value-plus-income profile without deep distress pricing (P/B above 1.0; Deep Value and Schloss models fail).

Business quality, as inferred from secondary data, appears reasonable for a regional composite insurer: revenue has grown from €9.0bn (2022) to €14.8bn (2025, Yahoo), net income from €472m to €835m, and operating cash flow recovered from negative territory in 2023 to €842m in 2025. Free cash flow turned positive at €476m in 2025 versus roughly breakeven in 2024, supporting dividend continuity (cash dividends paid €222m in 2025 vs €200m in 2024). Debt/equity of 33% and positive FCF yield screen inputs align with the risk-family pass, though insurer balance-sheet leverage is structurally high and screen liquidity metrics (current ratio 1.6; Financial Health fail) are less informative for insurers than for industrials.

For a value investor, the hook is a profitable, dividend-paying CEE franchise at a low-teens multiple with improving earnings momentum (statutory earnings growth ~63% per screen inputs) and modest book premium—without requiring net-net or deep-value thresholds. The screen's new signal (one week, conviction 36%) suggests early-stage identification rather than a long-established pattern.

## FINANCIAL REVIEW
**Primary filings gap:** `filings_index.json` contains zero entries (0 annual, 0 interim, 0 trading updates; 0 body extracts under `filings/bodies/`). No annual report, half-year release, or ESEF/iXBRL text is available for citation. IR presentation metrics (`ir_presentation_metrics.json`) are also empty (no segment splits, FCF bridges, or lease tables). All figures below are sourced from Yahoo `financials_annual.json`; treat as indicative until verified against VIG's official results releases.

**Income statement trends (Yahoo fallback):**

| Metric | 2022 | 2023 | 2024 | 2025 |
|--------|------|------|------|------|
| Total revenue (€m) | 8,971 | 11,649 | 12,928 | 14,781 |
| Net income (€m) | 472 | 559 | 626 | 835 |
| Diluted EPS (€) | 3.63 | 4.31 | 4.83 | n/a |
| EBIT (€m) | 681 | 871 | 964 | 1,246 |

Revenue has compounded strongly (+65% from 2022 to 2025). Net income rose ~77% over the same period, with a notable step-up in 2025 (+33% YoY). Each year includes special charges/impairments (€48–116m), so reported earnings understate normalised profit; normalised income was €979m in 2025 vs €828m in 2024 per Yahoo. EPS progression through 2024 (€3.63 → €4.83) supports the screen's earnings-growth input; 2025 diluted EPS is not populated in the feed.

**Balance sheet (Yahoo fallback):**

- **2025:** Common equity €7.17bn; total liabilities €47.0bn; long-term debt €1.59bn; cash €1.37bn; other short-term investments €26.4bn (typical insurer investment portfolio); goodwill €1.19bn; tangible book €5.27bn.
- **2024:** Total assets €51.2bn; equity €6.41bn; long-term debt €1.51bn.
- Equity grew ~12% YoY (2024→2025). Debt levels are moderate relative to equity but liabilities are dominated by insurance contract obligations—not captured cleanly by industrial D/E screens.

Pension/post-retirement provisions of €195m appeared in 2022 balance-sheet data; later years do not break this out in the Yahoo feed—an reporting gap for pension risk assessment.

**Cash flow (Yahoo fallback):**

| Metric | 2022 | 2023 | 2024 | 2025 |
|--------|------|------|------|------|
| Operating CF (€m) | −404 | −139 | 346 | 842 |
| Free cash flow (€m) | −807 | −541 | −17 | 476 |
| Cash dividends (€m) | 194 | 186 | 200 | 222 |

Operating cash flow swung sharply positive in 2025 after weak 2022–23 periods driven by large working-capital and investment-portfolio movements (insurer cash flows are volatile). FCF of €476m in 2025 covers dividends roughly 2.1× on a gross basis. The screen cites TTM FCF of ~$720m (USD); Yahoo reports €476m for FY2025—currency and basis differences are unresolved without filing reconciliation. Quarterly cash-flow series are empty (`quarterly_cashflow: {}`); TTM cash-flow suppression is flagged in the source.

**Interim coverage:** No half-year or Q1/Q3 releases are indexed. H1 2025 or H1 2026 trading momentum, combined ratio, and solvency II ratio cannot be assessed from this pack.

**What filings would add:** Combined ratio, net investment income trend, Solvency II coverage, geographic segment profitability, catastrophe exposure, and management guidance—all absent here.

## RISKS AND RED FLAGS
**Regulatory and geographic:** VIG operates across multiple CEE jurisdictions (Austria hub plus Poland, Czech Republic, Slovakia, Romania, Baltic states, etc.). Regulatory regimes, tax treatment, and capital requirements differ by market; no filing language on going concern, contingencies, or covenant compliance is available in this pack.

**Investment and rate sensitivity:** Insurers derive a large share of profit from investment portfolios (interest income €261m in 2025 vs €3m in 2024 per Yahoo—high volatility). Rising or falling rates affect both bond portfolio marks and spread income; Euro STOXX context (~6,422) and EUR/USD (~1.17) are backdrop only and do not override the screen.

**Screen-flagged weaknesses:** Piotroski F-Score 5/9 (fail); Financial Health model fail (high leverage, weak liquidity on industrial metrics); Buffett Quality and Economic Moat fails (ROE 12.4% below 18% hurdle; margins below moat thresholds). For an insurer, these may overstate risk on leverage/liquidity but understate risk on underwriting cycle and reserving adequacy—neither verifiable here.

**Earnings quality:** Recurring special charges and impairments (€96m in 2025; capital-asset impairments €24m) warrant scrutiny. Without filing footnotes, reserve releases vs genuine underwriting improvement cannot be separated.

**Governance and news:** No material company-specific news on management changes, M&A, or regulatory actions in the past year (see News Highlights). Governance assessment is not possible from indexed sources.

**Data and accounting risk:** Entire financial review relies on Yahoo secondary data with no primary filing cross-check; insurer-specific accounting (DAC, reserves, fair-value through P&L) increases misinterpretation risk.

RiskTags: regulatory, cyclical, competitive, accounting, leverage
RiskTags: regulatory, cyclical, competitive, accounting, leverage

## NEWS HIGHLIGHTS
**Coverage is thin and heavily polluted by ticker collision.** The majority of indexed headlines (40+ articles) refer to Vanguard Dividend Appreciation ETF (ticker VIG), not Vienna Insurance Group—e.g. "SCHD vs. VIG: Which Dividend ETF Is Better?" (25 Jun 2025), "VIG Hit A New High. Resist The Urge To Act." (7 Jul 2026), options-chain items on Moomoo (Aug 2026). These are not relevant to VIG.VI.

**Company-relevant items (limited):**

- *"Vienna Insurance Group (WBAG:VIG): Is the Current Valuation Justified After Recent Volatility?"* — Yahoo Finance, 10 Sep 2025. Notes increased attention and sideways price action without a headline catalyst; frames valuation debate.
- *"Attendo And 2 Other Undiscovered Gems In Europe With Strong Potential"* — Yahoo Finance, 4 Jun 2026. Lists VIG among European names with strong fundamentals (screening-style mention, no operational detail).
- *"European Dividend Stocks To Consider For Your Portfolio"* — Yahoo Finance, 20 Nov 2025; *"European Dividend Stocks To Consider In October 2025"* — 1 Oct 2025. Generic dividend-stock roundups; no VIG-specific strategy or results commentary.

**Not observed in indexed news:** Management changes, M&A, regulatory fines, catastrophe losses, capital raises, or strategy pivots. Material event monitoring requires direct IR/regulatory feeds, not this manifest.

## RESEARCH VERDICT
Verdict: accumulate
Risk: medium
Confidence: 0.55
Rationale: Quantitative cheapness and improving Yahoo-reported earnings/FCF support the buy screen, but the complete absence of primary filings and company-specific news prevents confirmation of underwriting quality, solvency, and reserve adequacy before full conviction.
