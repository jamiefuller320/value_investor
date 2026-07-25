# Alcoa Corporation (AAI.AX) — Research memo

_Version 1 · Updated 2026-07-25T12:45:47.217509+00:00 · Mode: initial_

## EXECUTIVE SUMMARY
Alcoa Corporation trades on the ASX as AAI.AX, a CHESS Depositary Interest over NYSE-listed Alcoa (AA). The quantitative screen rates the name a **buy** (10/22 models; composite 55%, sector-relative 58%) on cheapness, quality, dividend, GARP, and risk. The investment case rests on a cyclical recovery in integrated bauxite–alumina–aluminium earnings at modest multiples (P/E 11.9, P/B 1.8, debt/equity 37%) following a swing from a US$651m net loss in FY2023 to reported net income of US$1.16bn in FY2025 (Yahoo fallback). The central debate is whether current profitability reflects durable operational improvement or a commodity up-cycle, and whether operational setbacks at Pinjarra (Western Australia), cut 2026 alumina guidance, and a large South32 upstream acquisition will compress the multiple. **Primary regulatory filings are absent from the source library** (`filings_index.json` returns zero entries; no body extracts under `filings/bodies/`), so all financial figures below rely on Yahoo and cannot be verified against ASX announcements or US SEC EDGAR filings in this pack.

---

## INVESTMENT THESIS
The screen identifies AAI.AX as a persistent buy with high data completeness (19/20 metrics) and five factor families passing: cheapness, quality, dividend, GARP, and risk. Passed models include Graham Enterprising, Earnings Yield, FCF Yield, Low P/E + High Yield, Neff PEGY, Quality Value, Buffett Quality, Dividend Growth, Dreman Contrarian, and Financial Health — a profile consistent with a value investor seeking cyclicals at reasonable prices rather than deep distress.

Business quality, as inferred from Yahoo financials, has improved materially. Revenue rose from US$10.55bn (2023) to US$12.83bn (2025), operating income turned positive (US$758m in 2025 vs an operating loss of US$227m in 2023), and free cash flow recovered to US$567m in 2025 from negative US$440m in 2023. Return on equity of 15.4% (screen) aligns with the earnings rebound. Balance-sheet metrics support the risk-family pass: net debt of US$842m against US$1.60bn cash (2025, Yahoo), total debt US$2.70bn, and debt/equity of 37% — manageable for an integrated miner at the upper end of the cycle.

The valuation hook is straightforward: at P/E 11.9 and P/B 1.8, the market prices Alcoa as a mid-cycle commodity producer rather than a peak-earnings story, despite FY2025 diluted EPS of US$4.42 (Yahoo). For a value investor, the screen’s cheapness and FCF-yield passes suggest the market may be discounting cyclical mean-reversion and recent operational noise. **Caveat:** the screen’s reported yield of 85.0% is almost certainly a CDI/data artefact; Yahoo cash-flow data shows only US$104m in common dividends paid in 2025 — treat the dividend signal with scepticism until verified from filings.

---

## FINANCIAL REVIEW
**Source gap:** `filings_index.json` (regime: `asx_announcements`) contains **zero filings** — no annual reports, no interim results, no trading updates, and no downloadable body extracts. Interim and annual primary-source analysis is therefore **not possible** in this pack. All figures below are from `financials_annual.json` (Yahoo), stated explicitly as fallback. Cross-reference against US SEC 10-K/10-Q or ASX price-sensitive announcements is required before trade.

### Income trend (Yahoo fallback, USD)

| Period | Revenue | Operating income | Net income | Diluted EPS |
|--------|---------|------------------|------------|-------------|
| FY2023 | $10.55bn | −$227m | −$651m | −$3.65 |
| FY2024 | $11.90bn | $828m | $60m | $0.26 |
| FY2025 | $12.83bn | $758m | $1.16bn | $4.42 |

FY2025 reported net income is **not fully representative of underlying operations**. Yahoo shows normalized income of US$786m vs reported US$1.16bn, driven by large non-operating items including a US$1.07bn gain on sale of securities and US$598m in special charges (restructuring, impairments, write-offs). Normalized EBITDA was US$1.38bn vs reported EBITDA US$1.85bn. FY2024 was similarly distorted (reported net income US$60m vs normalized US$374m). Trend analysis should prioritise operating income and normalized metrics over headline net income.

Operating income peaked at US$1.33bn in FY2022 before collapsing in FY2023, recovering in FY2024, then moderating to US$758m in FY2025 — consistent with volatile alumina/aluminium pricing and cost pressures rather than a smooth upward trajectory.

### Balance sheet (FY2025, Yahoo fallback)

- Total assets: US$16.13bn; stockholders’ equity: US$6.12bn  
- Cash: US$1.60bn; total debt: US$2.70bn; **net debt: US$842m**  
- Working capital: US$1.67bn  
- Pension and post-retirement obligations: US$684m non-current + US$383m current ≈ **US$1.07bn**  
- Derivative liabilities: US$1.13bn  
- Long-term provisions: US$1.36bn  
- Retained earnings: **−US$271m** (negative despite recent profitability, likely reflecting historical losses, dividends, and equity adjustments)  
- Goodwill written to zero in 2025 (was US$142m in 2024)

### Cash flow (Yahoo fallback)

| Period | Operating CF | CapEx | Free cash flow | Dividends paid |
|--------|-------------|-------|----------------|----------------|
| FY2023 | $91m | −$531m | **−$440m** | $72m |
| FY2024 | $622m | −$580m | $42m | $90m |
| FY2025 | $1.19bn | −$618m | **$567m** | $105m |

FCF recovery in FY2025 supports the screen’s FCF Yield pass (screen key metric: ~US$1.09bn — likely trailing or adjusted; Yahoo FY2025 FCF is US$567m). Working-capital swings were material: FY2025 saw a US$456m outflow from working-capital changes.

### Interim / quarterly (Yahoo fallback only; no filing confirmation)

Cached quarterly income in `financials_annual.json`:

- **Q2 2026** (period key `2026`): revenue US$3.19bn, operating income US$426m, net income US$425m, diluted EPS US$1.60 — a strong quarter on an operating basis.  
- **Prior quarter** (period key `2025`): revenue US$3.00bn, operating income US$51m — depressed by US$884m restructuring/special charges and offset by a US$1.04bn securities gain.

News headlines (not primary filings) report Q2 2026 adjusted EPS of **US$2.12** vs FactSet estimate US$2.25 (“Earnings Flash (AA)…”, marketscreener.com, 16 July 2026), with management cutting full-year alumina output guidance to **9.5–9.6 million tonnes** citing Pinjarra refinery issues. These interim data points cannot be reconciled to filing extracts in this pack.

---

## RISKS AND RED FLAGS
**Filing verification gap (critical):** With no ASX announcement bodies and no SEC extracts, going-concern language, debt covenants, contingent liabilities, and environmental provisions **cannot be assessed** from primary sources. This is the largest red flag in the pack.

**Cyclical and commodity exposure:** Alcoa’s earnings are highly levered to LME aluminium and API alumina prices. FY2023 losses and FY2025’s reliance on non-operating gains illustrate earnings volatility that screens understate.

**Operational execution:** Recent news consistently flags **Pinjarra refinery disruption** and a cut to 2026 alumina guidance (e.g. “Alcoa cuts production outlook, citing refinery issues”, Yahoo, 20 July 2026; “Alcoa Cuts 2026 Alumina Output Forecast to 9.5–9.6 Million Tons”, Yahoo, 17 July 2026). Upstream weakness partially offset stronger aluminium segment performance in Q2 2026 — a segment-mix risk as the company pivots strategy.

**Large M&A integration:** Alcoa announced a **South32 upstream transaction** with US$4.1bn upfront and up to US$750m additional (“Alcoa Enters South32 Deal With $4.1B Upfront, Up to $750M More”, Stock Titan, 16 July 2026). This materially increases scale but adds integration, leverage, and execution risk at a moment of operational stress. Market reaction post-Q2 was negative (“The Market Sold Alcoa After Earnings—But It May Be Missing the Real Story”, Globe and Mail, 18 July 2026).

**Pension and legacy liabilities:** Yahoo balance-sheet data shows ~US$1.07bn in pension/post-retirement obligations and US$1.36bn in long-term provisions — material off-balance-sheet-style commitments for a US$6.1bn equity base. Without filing footnotes, funding status and upcoming contributions are unknown.

**Governance / earnings quality:** Heavy reliance on normalized vs reported earnings, negative retained earnings, and large derivative balances (US$1.13bn liabilities) warrant scrutiny in the 10-K risk factors and MD&A — unavailable here.

**Screen data quality:** The 85.0% dividend yield and possible FCF metric discrepancy suggest CDI-related data quirks; do not treat dividend-model passes as confirmed without filing verification.

**Share-price volatility:** AAI.AX fell sharply in June 2026 after a strong multi-month rally (“Alcoa Shares Down 30% In Three Weeks”, thebull.com.au, 23 June 2026; “Why this ASX 200 stock is crashing after doubling in a year”, Motley Fool Australia, 11 June 2026), reflecting sentiment sensitivity to commodity forecasts and earnings events.

---

## NEWS HIGHLIGHTS
Coverage over the past year is **moderate-to-good** for a CDI (45 articles in `news_manifest.json`), though much is price commentary rather than fundamental disclosure. Material themes:

**Q2 2026 earnings (July 2026):** Alcoa reported higher revenue and adjusted earnings but **missed estimates** — adjusted EPS US$2.12 vs US$2.25 expected (“Earnings Flash (AA)…”, 16 July 2026; “Alcoa misses estimates as production issues weigh on results”, Investing.com UK, 16 July 2026). Shares fell despite improved underlying aluminium performance (“Alcoa Earnings Are Improving. The Stock Is Down Anyway.”, Barron’s, 16 July 2026). Management cut full-year **alumina production guidance** due to Pinjarra issues (WSJ/Yahoo, 16–20 July 2026) and highlighted record aluminium EBITDA on the Q2 call (“AA Q2 Earnings Call Highlights AliGroup Growth Plan”, Yahoo, 17 July 2026).

**South32 acquisition (July 2026):** Agreement to acquire South32 interests in Brazilian and Australian assets including Worsley Alumina and Hillside Aluminium — US$4.1bn upfront plus up to US$750m (“Alcoa Enters South32 Deal…”, Stock Titan, 16 July 2026; “Alcoa (AA) Following Its Asset Deal, Is The Undervalued Case Back In Focus?”, Yahoo, 14 July 2026). Market focus on deal size vs operational delivery drove post-earnings selloff.

**Strategic projects:** Final investment decision on a **gallium production plant** at Wagerup refinery, Western Australia, backed by Australia, Japan, and the US (“Alcoa Greenlights Gallium Plant in Australia With U.S. and Japan Backing”, Yahoo/WSJ, 14–15 July 2026). US$65m capital investment at Mosjoen, Norway announced (marketscreener.com, 12 May 2026). Smelter restarts in Spain, Brazil, and Norway noted ahead of Q2 (Yahoo, 15 July 2026).

**FY2025 / Q4 2025 results (January 2026):** Q4 2025 exceeded forecasts (“Alcoa Corporation Reports Q4 2025 Results, Demonstrates Operational Strength”, AlphaStreet, 22 January 2026; “Alcoa's Stock Mixed After Q4 Earnings Exceed Forecasts”, MLQ.ai, 23 January 2026), though shares dipped (“Alcoa shares dip despite 25% earnings boost in FY25”, Motley Fool Australia, 23 January 2026).

**Dividends:** Regular dividend announcements (March and June 2026, Motley Fool Australia).

**Broader sentiment:** UBS buy rating and aluminium supply-crunch narrative supported a May 2026 rally (“Alcoa Shares Surge on UBS Buy Rating and Aluminium Supply Crunch”, Discovery Alert, 25 May 2026). More recently, **aluminium surplus fears** have pressured the stock (“Alcoa (ASX: AAI) Extends Monthly Slide as Aluminium Surplus Fears Override Record Quarter”, Kalkine, 21 July 2026).

**Thin areas:** No primary ASX regulatory filings captured; pension/covenant/going-concern language not available from filing bodies. Several manifest entries are tangential (e.g. Empire Metals, 23 July 2026).

---

## RESEARCH VERDICT
Verdict: accumulate
Risk: high
Confidence: 0.58
Rationale: The quantitative buy signal aligns directionally with a Yahoo-backed earnings and FCF recovery at modest multiples, but absent primary filings, distorted reported earnings, fresh operational/guidance setbacks, and a large pending acquisition prevent full confirmation of the screen’s quality and dividend passes.
