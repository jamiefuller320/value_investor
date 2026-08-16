# Mapletree Pan Asia Commercial Trust (N2IU.SI) — Research memo

_Version 1 · Updated 2026-08-16T12:36:29.588455+00:00 · Mode: initial_

## EXECUTIVE SUMMARY
Mapletree Pan Asia Commercial Trust (MPACT; SGX:N2IU) screens as a **buy** on a pan-Asia commercial REIT trading at **0.7× book** with a **6.2% dividend yield** and **~5.3% FCF yield**, supported by strong cash conversion (Piotroski F-Score 8/9) and declining net debt. The value case rests on asset-backing and income rather than earnings momentum: statutory net income fell sharply in the latest fiscal year while revenue continues to drift lower amid portfolio recycling. The central debate is whether asset sales and Singapore resilience can stabilise distributions while Hong Kong and broader office markets remain under pressure — a question this pack cannot fully resolve without primary SGX/HKEX filings. Conviction is moderate pending verified covenant, valuation, and occupancy disclosures.

## INVESTMENT THESIS
The quantitative screen flags MPACT across five model families — **cheapness, quality, dividend, GARP, and risk** — with a **61% composite score** (5/22 models passed) and full data quality (20/20 metrics). The signal is **new** (one week, trend improving) but screen conviction is only **36%**, consistent with a name transitioning from long-held **hold** to **buy**.

For a value investor, the hook is structural rather than cyclical earnings power:

- **Price vs. assets:** P/B **0.74** implies the market prices the portfolio below carrying value — unusual for a REIT with investment properties of **~US$15.0bn** (Yahoo FY2026 balance sheet; no filing confirmation).
- **Income yield:** Dividend yield **6.2%** with TTM FCF of **~US$358m** (screen) / **US$585m** (Yahoo FY2026) versus cash dividends paid of **US$427m** — suggesting gross FCF covers distributions, though net coverage after financing costs is tighter.
- **Balance-sheet direction:** Net debt fell from **US$6.49bn** (FY2024) to **US$5.39bn** (FY2026) per Yahoo; debt/equity **62%** and declining leverage contributed to Piotroski passes.
- **Quality markers:** Passes **Earnings Quality** and **FCF Yield** despite **−11.4% earnings growth** — the screen is effectively saying cash flows and book value compensate for weak reported ROE (**2.7%**) and elevated P/E (**25.6×**).

What the screen does *not* capture well: REIT-specific fair-value volatility, geographic office-cycle exposure (Singapore vs. Hong Kong/China), and sponsor-related governance. The buy case is therefore a **discounted asset + yield** play, not a classic earnings-compounder.

## FINANCIAL REVIEW
**Primary filing gap:** `filings_index.json` contains **zero** entries (no annual reports, interim results, or trading updates; regime `asia_filings`). The `filings/bodies/` directory has **no extracts**. All figures below are sourced from **`financials_annual.json` (Yahoo Finance)** unless noted; interim analysis relies on Yahoo cached quarterly income only — not verified against SGX announcements.

**Income and operating trends (Yahoo, USD)**

| Metric | FY2024 | FY2025 | FY2026 | Direction |
|--------|--------|--------|--------|-----------|
| Revenue | 895.5m | 844.7m | 807.7m | ↓ ~10% over two years |
| Operating income | 672.3m | 633.0m | 604.1m | ↓ ~10% |
| Net income (common) | 577.9m | 584.2m | 261.3m | ↓ ~55% in FY2026 |
| Diluted EPS | 0.110 | 0.111 | 0.049 | ↓ |
| Interest expense | 295.3m | 252.3m | 166.0m | ↓ (refinancing / deleveraging) |
| Normalised EBITDA | 819.3m | 793.6m | 483.0m | ↓ (FY2026 affected by unusual items) |

Reported FY2026 net income includes **US$55.6m** of unusual items (Yahoo); normalised net income is **~US$299m** — still materially below FY2025. Operating income declined more modestly (~5% YoY), which is more representative of underlying property operations than statutory net profit, but the direction is still negative.

**Latest interim (Yahoo quarterly income — unverified against half-year filing)**

The most recent cached quarter (labelled 2026 in Yahoo) shows:
- Revenue **US$197.3m** vs **US$203.6m** in the prior-year comparable quarter
- Net loss to common unitholders **US$26.7m** (diluted EPS **−0.0051**)
- Operating income **US$146.9m** remains positive, but below-interest costs drive the quarterly loss

Without an indexed interim filing, it is unclear whether this reflects seasonal fair-value adjustments, disposal gains/losses, or deteriorating occupancy — treat as indicative only.

**Balance sheet and portfolio (Yahoo, USD)**

| Metric | FY2024 | FY2025 | FY2026 |
|--------|--------|--------|--------|
| Total assets | 16.66bn | 16.14bn | 15.42bn |
| Investment properties | 16.25bn | 15.73bn | 14.99bn |
| Common equity | 9.46bn | 9.61bn | 9.38bn |
| Total debt | 6.65bn | 6.00bn | 5.56bn |
| Net debt | 6.49bn | 5.83bn | 5.39bn |
| Cash | 157m | 171m | 164m |
| Current ratio | — | — | **0.39** (screen) |

The portfolio is shrinking: investment properties down **~US$1.3bn** over two years, consistent with an asset-recycling strategy. Net debt has fallen **~US$1.1bn** over the same period — deleveraging is real, but **liquidity is thin** (current ratio 0.39; working capital negative **US$448m**).

**Cash flow and distributions (Yahoo, USD)**

| Metric | FY2024 | FY2025 | FY2026 |
|--------|--------|--------|--------|
| Operating cash flow | 725.0m | 634.0m | 586.0m |
| Free cash flow | 724.7m | 633.0m | 585.0m |
| Cash dividends paid | 470.2m | 444.3m | 427.4m |
| Sale of investment properties | — | 762.4m | 390.6m |
| Purchase of investment properties | (64.8m) | (56.7m) | (86.6m) |

FCF exceeds cash dividends at the gross level in all three years (~1.4× in FY2026), supporting the screen’s dividend and FCF-yield passes. However, **interest paid** was **US$187m** (FY2026 financing cash flow), and operating cash flow is trending down — distribution sustainability depends on disposal proceeds and refinancing conditions not visible in this data set.

**Screening cross-check**

Screen TTM FCF **US$358m** is lower than Yahoo FY2026 FCF **US$585m** — possible timing/definition difference; neither is filing-verified. EV/EBIT **~20.5×** (screen failure on Acquirer’s Multiple) confirms the name is **not cheap on an earnings basis**, reinforcing that the buy signal is driven by yield, book, and cash-quality factors rather than deep earnings value.

## RISKS AND RED FLAGS
**Leverage and liquidity:** Debt/equity **62%**; net debt **~US$5.4bn** against equity **~US$9.4bn**. Current ratio **0.39** and negative working capital flag refinancing and short-term liability risk. The screen failed **Financial Health**, **Buffett Quality**, and **Schloss Low P/B** (leverage). No filing body text is available to assess debt covenants, maturity profile, or going-concern language.

**Cyclical / portfolio:** Revenue and operating income have declined for two consecutive years. Investment properties have shrunk materially — asset sales may be prudent de-risking or forced portfolio reduction; without filings, intent and pricing cannot be judged. Pan-Asia office markets (notably Hong Kong and mainland China) face structural headwinds from hybrid work and supply; Singapore exposure is cited in news as a relative bright spot but is unquantified here.

**Earnings quality / accounting:** FY2026 statutory net income halved; quarterly loss in the latest cached period. REIT fair-value movements and disposal gains can distort reported earnings — the screen passes **Earnings Quality** and **Piotroski** on cash metrics, but **ROE 2.7%** and failed **Economic Moat** / **Quality Value** models signal weak reported profitability. Unusual items of **US$55.6m** in FY2026 warrant filing-level reconciliation.

**Governance / sponsor:** News reports **~56% private-equity ownership** and Mapletree sponsor influence — related-party transactions, fee structures, and acquisition/disposal pricing are not reviewable without annual report disclosures.

**Valuation tension:** P/B discount coexists with P/E **25.6×**, earnings yield **3.9%**, and failed deep-value screens — the market may be discounting book because asset values and rental income are at risk of further write-downs.

**Data gaps:** Zero indexed annual or interim filings; no covenant, contingency, or litigation disclosures extracted. This pack should be treated as **verify-before-trade**.

RiskTags: cyclical, leverage, liquidity, governance, competitive, accounting
RiskTags: cyclical, leverage, liquidity, governance, competitive, accounting

## NEWS HIGHLIGHTS
News coverage is **thin** — only **four** articles in `news_manifest.json` over the past year, all from Yahoo Finance; `alternate_news.json` is empty.

- **29 Apr 2026** — *Mapletree Pan Asia Commercial Trust (MPCMF) (Q4 2026) Earnings Call Highlights: Navigating ...*: Overall revenue declined, but management emphasised **strategic asset sales** and **robust Singapore growth** to support financial stability.
- **3 Feb 2026** — *Is Now The Time To Put Mapletree Pan Asia Commercial Trust (SGX:N2IU) On Your Watchlist?*: Generic commentary on turnaround potential; no material corporate action disclosed.
- **7 Jan 2026** — *...stock most popular amongst private equity firms who own 56%, while individual investors hold 32%*: Highlights concentrated **PE ownership** and retail minority stake — relevant to governance and float dynamics.
- **14 Nov 2025** — *...investors are sitting on a loss of 2.2% if they invested five years ago*: Notes weak long-term total return; no operational detail.

No material M&A, management changes, or regulatory actions are captured in the manifest. Strategy shift toward **asset recycling** is the dominant theme, inferred from news and corroborated by Yahoo cash-flow disposal data — but not independently verified against SGX announcements.

## RESEARCH VERDICT
Verdict: accumulate
Risk: medium
Confidence: 0.58
Rationale: The screen’s buy signal on book discount, dividend yield, FCF quality, and deleveraging is partially confirmed, but missing primary filings and two-year declines in revenue, operating income, and statutory earnings prevent full confirmation of distribution sustainability and asset values.
