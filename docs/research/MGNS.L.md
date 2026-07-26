# Morgan Sindall Group plc (MGNS.L) — Research memo

_Version 1 · Updated 2026-07-26T18:30:31.172795+00:00 · Mode: initial_

## EXECUTIVE SUMMARY
Morgan Sindall Group is a diversified UK construction and regeneration contractor (Fit Out, Construction, Infrastructure, Property Services, Urban Regeneration, and housing-related activities) that the quantitative screen rates as a **strong buy** on cheapness, quality, dividend, GARP, and risk metrics (16/22 models; composite 75%). At roughly 11.8× P/E, 2.7× P/B, 3.6% yield, and 26.1% ROE, the stock screens as inexpensive relative to a multi-year record of profit and cash growth. Management has described H1 2026 (to 30 June) as a “record first half,” with infrastructure and fit-out offsetting housing weakness — but without statutory filing extracts, those interim figures cannot be verified here. The central debate is whether durable operational excellence and order-book visibility justify a quality-compounder label, or whether UK construction cyclicality, working-capital intensity, and the absence of primary filing disclosure leave the screen signal ahead of the evidence.

---

## INVESTMENT THESIS
For a value investor, MGNS combines **statistical cheapness with operational quality** in a sector that rarely passes both tests simultaneously.

**Quantitative alignment:** The screen passes five factor families — cheapness, quality, dividend, GARP, and risk — with full data coverage (20/20 metrics). Standout inputs include P/E 11.8, P/B 2.72, earnings yield, FCF yield (~£142m per screen; £171m per Yahoo FY2025), debt/equity ~18%, and Piotroski F-Score 8/9 (only asset-turnover improvement failed). Models passed span Graham Enterprising, Lynch/Neff PEG variants, Magic Formula, Acquirer’s Multiple, Buffett Quality, Dividend Growth, Composite Value, Earnings Quality, and Financial Health. Failures (Graham Defensive, Net-Net, Deep Value, Economic Moat, High Dividend Yield) are consistent with a profitable, going-concern contractor rather than a distressed or deep-net-asset play — not a contradiction of the strong-buy signal.

**Business quality (secondary evidence):** Yahoo annual data (see Financial Review) show revenue rising from £3.6bn (FY2022) to £5.0bn (FY2025), net income from £61m to £175m, and FY2025 free cash flow of £171m — a compounder-like trajectory outside COVID-disrupted years. Balance sheet metrics support the risk family pass: cash £591m versus total debt £133m at FY2025 year-end, and equity up 16% year-on-year to £749m. News flow over the past year reinforces operational momentum: full-year profit outlook upgrade (April 2026), upbeat trading updates, and July 2026 interim headlines citing record H1 performance and order-book support.

**Valuation hook:** Low-teens earnings multiple on high-teens ROE, positive FCF, and rising dividends is the classic “quality at a reasonable price” setup the screen is designed to surface. Timing is neutral (RSI ~39; price slightly below 200-day MA), suggesting the strong-buy signal is not momentum-chasing.

---

## FINANCIAL REVIEW
**Primary source gap:** `filings_index.json` lists **zero** UK RNS or Companies House filings (annual: 0, interim: 0, with_body: 0). No text extracts exist under `filings/bodies/`. Going-concern, pension, covenant, and contingency language from statutory accounts **cannot be cited**. Interim coverage is limited to news/RNS titles (e.g. “RESULTS FOR THE HALF YEAR (HY) ENDED 30 JUNE 2026”, 23 July 2026) without numeric body text.

**All figures below are from `financials_annual.json` (Yahoo) — explicit fallback.**

### Annual trend (FY2022–FY2025)

| Metric | FY2022 | FY2023 | FY2024 | FY2025 |
|--------|--------|--------|--------|--------|
| Revenue (£m) | 3,612 | 4,118 | 4,546 | 5,019 |
| Operating income (£m) | 84 | 125 | 180 | 226 |
| Net income (£m) | 61 | 118 | 132 | 175 |
| Diluted EPS (£) | 1.30 | 2.50 | 2.72 | n/a* |
| EBITDA (£m) | 113 | 176 | 209 | 272 |
| Free cash flow (£m) | 43 | 181 | 111 | 171 |
| Cash (£m) | 421 | 541 | 544 | 591 |
| Total debt (£m) | 134 | 144 | 119 | 133 |
| Shareholders’ equity (£m) | 496 | 568 | 647 | 749 |
| Working capital (£m) | 222 | 257 | 305 | 373 |

*Yahoo did not populate diluted EPS for FY2025 in the extract; implied EPS ≈ £3.75 on ~46.6m ordinary shares (175m ÷ 46.6m).

**Profitability:** Revenue CAGR FY2022–FY2025 ≈ 12%. Net income nearly tripled over the period. FY2025 operating margin ~4.5% (226/5,019) and net margin ~3.5% — modest in absolute terms but improving consistently and typical for UK contracting at scale.

**Cash and capital allocation:** FY2025 operating cash flow £187m; capex £17m; FCF £171m. Dividends paid £66m (up from £56m FY2024). Net share repurchases £28m (buybacks £41m less issuance £13m). The group appears to self-fund growth, dividends, and buybacks without balance-sheet strain.

**Balance sheet / working capital:** Net cash position (cash £591m less total debt £133m) ≈ **£458m** at FY2025. Debt/equity ~18% aligns with the screen. Working capital rose £68m YoY to £373m, driven by inventory/WIP (£603m, +27%) and receivables (£468m, +27%) — consistent with revenue growth but a watchpoint for cash conversion in a downturn. FY2025 FCF absorbed a £21m working-capital outflow.

**Quality checks:** Piotroski 8/9 (screen) corroborates improving ROA, declining leverage, OCF > net income, and no dilution. Unusual/write-off items (£2.5m FY2025; £21m FY2024) are immaterial relative to profit.

### Interim (H1 FY2026)

An RNS announcement for half-year results to **30 June 2026** is indexed in news (23 July 2026), and a Yahoo earnings-call summary describes a “record first half” with revenue, profit, and cash all rising, Fit Out/Construction/Infrastructure strong, housing-related markets weak. **No interim filing body is available; interim financials are not verified in this pack.**

### Gaps

- No FY2025 annual report, FY2024 annual report, or H1 2026 RNS body in the filing corpus.
- No segment breakdown, order-book figure, or pension/covenant disclosure from primary filings.
- `quarterly_income` in Yahoo is empty.
- `macro_context.json` missing — no offline regime overlay.

---

## RISKS AND RED FLAGS
**Filing disclosure vacuum:** The absence of statutory accounts and RNS body text is the largest research red flag. Pension obligations, banking covenants, contract provisions, related-party transactions, and going-concern assessments cannot be reviewed from primary sources in this pack.

**Cyclical and sector risks:** UK construction and regeneration demand is inherently cyclical. Public-sector pipeline visibility helps, but margin compression, project delays, and client insolvency remain sector-wide risks not fully captured by backward-looking screens.

**Working-capital intensity:** FY2025 inventory/WIP (£603m) and receivables (£468m) are large relative to equity (£749m). In a revenue slowdown, cash conversion could deteriorate quickly — the screen’s risk pass reflects low leverage, not immunity to WC swings.

**Segment mix:** News summaries flag **weakness in housing-related markets** (H1 2026 call) while infrastructure and fit-out carry results. A prolonged housing downturn could drag group returns even if other divisions hold up.

**Contract and execution risk:** Fixed-price contracting, supply-chain inflation, and labour availability can erode margins with limited screen visibility. FY2024–FY2025 write-offs (£21m; £2.5m) are small but remind that provisioning risk exists.

**Governance / capital structure:** A May 2026 headline references a “fresh share issue,” which warrants verification in the annual report (not available here). Founder/chair John Morgan’s long tenure and employee-ownership culture are positives for alignment but concentrate leadership dependency.

**Competitive positioning:** The screen **failed Economic Moat** — contracting is competitive; the investment case rests on execution track record rather than structural barriers.

**Pension:** Yahoo balance sheet shows negligible pension liabilities in recent years (£0.2m non-current in FY2022; zero in FY2023+), but this cannot be confirmed without Companies House accounts.

---

## NEWS HIGHLIGHTS
Coverage over the past year is **moderately rich on trading tone but thin on investigative depth**; much is syndicated “AD HOC NEWS” or dividend-listicles.

**Results and outlook**
- *“REG - Morgan Sindall Grp - RESULTS FOR THE HALF YEAR (HY) ENDED 30 JUNE 2026”* (23 July 2026) — interim release.
- *“Morgan Sindall Group H1 Earnings Call Highlights”* (23 July 2026, yfinance) — management cited a “record first half”; Fit Out, Construction, Infrastructure strong; housing-related markets weak.
- *“Morgan Sindall shares jump 10% after construction group upgrades full-year profit outlook”* (16 April 2026, Yahoo Finance UK / Proactive Investors).
- *“Morgan Sindall Group H2 Earnings Call Highlights”* (25 February 2026, yfinance) — “good year”; decade of record profits except COVID.
- *“Morgan Sindall jumps 7% after upbeat trading update”* (12 February 2026, Yahoo Finance UK).

**Strategy**
- *“Morgan Sindall looks to housing to drive growth”* (25 February 2026, Investors’ Chronicle).

**Capital markets**
- *“Morgan Sindall Group plc stock: fresh share issue keeps UK construction player in foc”* (21 May 2026, AD HOC NEWS) — share issuance flagged; details not in filing pack.

**Market commentary**
- Multiple simplywall.st and Yahoo pieces listing MGNS among UK dividend stocks (June–July 2026).
- Repeated AD HOC NEWS items (July 2026) citing order-book strength and infrastructure/fit-out demand.

**Not observed in manifest:** Material M&A, regulatory enforcement, or management departures. No pension/covenant-specific investigative coverage despite targeted alternate-news queries.

---

## RESEARCH VERDICT
Verdict: accumulate
Risk: medium
Confidence: 0.68
Rationale: Yahoo financials and consistent news of record trading support the screen’s cheap-quality strong-buy case, but the complete absence of primary filing bodies prevents verification of interim results, pensions, covenants, and segment risks before full conviction.
