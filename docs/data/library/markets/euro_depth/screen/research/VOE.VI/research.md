# Voestalpine AG (VOE.VI) — Research memo

_Version 1 · Updated 2026-08-21T22:09:57.956892+00:00 · Mode: initial_

## EXECUTIVE SUMMARY
Voestalpine AG screens as a Strong Buy on cheapness (P/B 0.99, P/E 14.8), cash generation (FCF yield), and financial health (Piotroski 7/9, D/E ~25%), with earnings recovering sharply from the 2024–25 trough. The value hook is a cyclical steel and technology group trading roughly at book after a multi-year revenue decline, now showing FY2026 net income of €425m and improving free cash flow, against a Greentech Steel capex cycle that absorbs much of operating cash. The central debate is whether the current recovery is mid-cycle normalisation or a peak before steel demand softens again — compounded by absent primary filings in the research pack, which limits covenant, pension, and contingency verification. We lean constructive but flag material evidence gaps.

## INVESTMENT THESIS
The quantitative screen fires across five families — cheapness, quality, dividend, GARP, and risk — with 11 of 22 models passing at a 71% composite score (sector-relative 72%). The Schloss Low P/B and Deep Value models align with P/B 0.99 and net debt falling to €1.0bn (from €1.6bn prior year, Yahoo FY2026 balance sheet). FCF Yield and Lynch/Neff PEG models benefit from FCF of €557m (Yahoo FY2026) against depressed earnings that rebounded ~177% year-on-year (net income €154m → €425m). Financial Health, Earnings Quality, Magic Formula, and Piotroski F-Score (7/9: positive NI, OCF, improving ROA, OCF > NI, declining leverage, no dilution, improving gross margin) support balance-sheet resilience despite cyclicality.

Business quality is mixed rather than compounder-grade: ROE 6.6% fails Buffett, Economic Moat, and Quality Value screens, reflecting thin margins and capital intensity typical of European steel. However, for a value investor the setup is classic cyclical deep value — asset-heavy producer at book value, deleveraging, rising OCF (€1.54bn FY2026), and dividend continuity (1.7% yield) — with Greentech Steel positioning as a long-dated optionality rather than near-term earnings driver. The screen's Strong Buy is therefore credible on price and balance-sheet metrics, not on franchise quality.

## FINANCIAL REVIEW
**Primary filings:** The `filings_index.json` contains zero entries (no annual reports, interim results, or trading updates indexed; no body extracts under `filings/bodies/`). All figures below are sourced from `financials_annual.json` (Yahoo Finance) with explicit fallback. Quarterly income and cash-flow series supplement where noted.

**Revenue and profitability (FY ends March; Yahoo labels):**

| Metric | FY2023 | FY2024 | FY2025 | FY2026 |
|--------|--------|--------|--------|--------|
| Revenue | €18.23bn | €16.68bn | €15.74bn | €15.06bn |
| Operating income | €1.52bn | €548m | €441m | €709m |
| EBITDA | €2.61bn | €1.74bn | €1.40bn | €1.53bn |
| Net income | €1.06bn | €101m | €154m | €425m |
| Diluted EPS | €6.01 | €0.59 | €0.90 | €2.44 |

Revenue has fallen four consecutive years (−17% from FY2023 peak), consistent with post-pandemic normalisation and weaker steel markets. FY2026 marks a clear earnings inflection: net income more than doubled versus FY2025, operating income rose 61%, and EBITDA recovered 9%. Gross margin improved to ~20.0% (€3.01bn on €15.06bn revenue) from ~18.0% in FY2025, though still well below the FY2023 peak of ~19.9% on a much larger revenue base.

**Cash flow and capital allocation (Yahoo):**

| Metric | FY2023 | FY2024 | FY2025 | FY2026 |
|--------|--------|--------|--------|--------|
| Operating cash flow | €956m | €1.45bn | €1.42bn | €1.54bn |
| Capex | €(752)m | €(1,082)m | €(1,109)m | €(983)m |
| Free cash flow | €204m | €366m | €312m | €557m |
| Dividends paid | €(214)m | €(257)m | €(120)m | €(103)m |

OCF has been resilient above €1.4bn for three years despite revenue contraction, aided by working-capital release (inventory down €196m FY2026). FCF improved materially in FY2026 as capex moderated slightly. Dividend was cut in FY2025–26 versus FY2024, consistent with the earnings trough. Screen-reported TTM FCF of ~$521m (USD) is broadly consistent with Yahoo's €441m TTM figure in `cashflow_metrics`.

**Balance sheet (Yahoo FY2026):**

- Total assets: €16.0bn; shareholders' equity: €7.58bn; tangible book: €6.27bn
- Total debt: €2.41bn; net debt: €1.02bn (down from €1.59bn FY2025)
- Working capital: €1.97bn; current ratio ~1.35 (screen input)
- Pension and post-retirement obligations: €817m non-current + €82m current ≈ €899m
- Inventory: €4.47bn (28% of assets — cyclical working-capital risk)
- Construction in progress: €1.23bn (Greentech/capacity investment)

Leverage is moderate (D/E 25% per screen; gross debt/equity ~32% on Yahoo). Net debt/EBITDA ≈ 0.7x on FY2026 EBITDA — comfortable if earnings hold.

**Interim / quarterly (Yahoo quarterly income; news context):**

Q1 FY2026/27 (quarter ended 31 March 2026, per Yahoo `quarterly_income` 2026): revenue €3.92bn, operating income €253m, net income €170m. News headline (*Voestalpine increased revenue by 2.4% y/y in Q1 2026/2027*, GMK Center, 6 Aug 2026) confirms modest top-line growth but reports a first-quarter miss versus expectations; management maintained full-year guidance (*Voestalpine maintains guidance despite first quarter miss*, Investing.com, 5 Aug 2026). Without interim filing bodies, margin bridge and segment detail are unavailable.

**Annual results context (news only — no filing bodies):**

FY2025/2026 full-year headlines cite EBITDA +10.3% and net income +137.6% (*VOE: EBITDA up 10.3% and net income up 137.6%*, TradingView, 2 Jun 2026), and Q4 EPS beating expectations (*Earnings call transcript: Voestalpine Q4 2025/2026 beats EPS expectations*, Investing.com, 3 Jun 2026). These align directionally with Yahoo FY2026 data but cannot be reconciled line-by-line without primary filings.

**Gaps:** No annual report, half-year report, or ad hoc release text is available in the research pack. Covenant language, going-concern statements, segment breakdowns, and Greentech Steel capex commitments cannot be verified from filings. IR presentation metrics (`ir_presentation_metrics.json`) contain no segment splits, FCF bridges, or lease maturity tables.

## RISKS AND RED FLAGS
**Cyclical exposure:** Revenue down ~17% from FY2023 peak; steel and metal engineering earnings remain highly sensitive to European industrial demand, auto production, and energy costs. The screen's cyclical overlay did not flag exposure, but the financial trajectory is unmistakably cyclical.

**Low return profile:** ROE 6.6% and thin margins fail multiple quality screens (Buffett Quality, Economic Moat, Quality Value). Recovery may already be partly reflected in a ~113% one-year share-price move cited in news (*Is It Too Late To Consider Voestalpine*, Yahoo Finance, 15 Feb 2026).

**Pension and legacy liabilities:** ~€899m pension/post-retirement obligations on the balance sheet (Yahoo FY2026) represent a material off-P&L commitment; no filing language on funding status or deficit trends is available.

**Capex and Greentech Steel:** FY2026 capex €983m versus OCF €1.54bn absorbs ~64% of operating cash before working-capital changes. Earnings-call summary (*Q1 2027 Earnings Call Highlights*, Yahoo Finance, 5 Aug 2026) references trade uncertainties and project delays — capex overruns or green-steel transition costs could compress FCF.

**Working capital:** Inventory €4.47bn (28% of assets) creates downside risk if steel prices fall and volumes weaken.

**Governance / disclosure:** Zero indexed regulatory filings severely limits assessment of related-party transactions, contingencies, and audit emphasis-of-matter paragraphs.

**Liquidity:** Current ratio 1.35 is below Graham Defensive threshold (screen failure: current ratio < 2); not alarming for an investment-grade industrial but worth monitoring.

**Filing gaps:** Without primary documents, going-concern, covenant headroom, and litigation contingencies cannot be assessed — a material red flag for verify-before-trade.

RiskTags: cyclical, pension, leverage, competitive, other
RiskTags: cyclical, pension, leverage, competitive, other

## NEWS HIGHLIGHTS
News coverage is moderate but noisy: many headlines reference the US ticker "VOE" (Vanguard Mid-Cap Value ETF) rather than Voestalpine AG — company-specific signal is thinner than the 54-article count suggests.

**Material company news (past year):**

- **Q1 FY2026/27 results (Aug 2026):** Revenue +2.4% y/y (*GMK Center*, 6 Aug 2026); Q1 miss but guidance maintained (*Investing.com*, 5 Aug 2026); stock weakness on results day (*Why is Voestalpine stock sliding today?*, Investing.com, 5 Aug 2026). Earnings-call summary highlights Greentech Steel progress, trade uncertainties, and project delays (*Yahoo Finance*, 5 Aug 2026).
- **FY2025/2026 full-year (Jun 2026):** EBITDA +10.3%, net income +137.6% on resilient performance and green-steel investment (*TradingView*, 2 Jun 2026); Q4 EPS beat (*Investing.com*, 3 Jun 2026); full-year press conference transcript indexed (*GuruFocus*, 3 Jun 2026).
- **Valuation debate (Feb–Jul 2026):** Multiple articles questioning whether value remains after strong momentum (*Yahoo Finance/Zacks*, Jul–Aug 2026); 113% one-year surge raises timing questions (*Yahoo Finance*, 15 Feb 2026).
- **Strategy:** Greentech Steel transformation repeatedly cited as the strategic anchor; no M&A or management-change headlines identified in the manifest.

**Coverage quality:** Thin on operational detail and largely absent on regulatory or governance matters. No material litigation or regulatory-action headlines found. Recommend direct pull from voestalpine.com investor relations and Wiener Börse ad hoc filings before sizing a position.

## RESEARCH VERDICT
Verdict: accumulate
Risk: medium
Confidence: 0.58
Rationale: Quantitative cheapness and balance-sheet metrics are corroborated by Yahoo financials showing earnings recovery, deleveraging, and strong OCF, but absent primary filings and low ROE prevent full confirmation of the Strong Buy case.
