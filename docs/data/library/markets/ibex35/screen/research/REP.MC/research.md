# Repsol, S.A. (REP.MC) — Research memo

_Version 1 · Updated 2026-07-18T18:20:20.920246+00:00 · Mode: initial_

## EXECUTIVE SUMMARY
# Repsol, S.A. (REP.MC) — First-Pass Research Memo

**Quantitative screen:** Strong Buy (9/22 models, composite 74%)  
**Sources:** `filings_index.json`, `financials_annual.json` (Yahoo fallback), `screening_snapshot.json`, `news_manifest.json`  
**Note:** No Repsol regulatory filing bodies are available in the source library; financial figures below are from Yahoo unless stated otherwise.

---

## EXECUTIVE SUMMARY

Repsol screens as a Strong Buy on integrated value metrics: P/E 11.4, P/B 1.2, dividend yield 4.5%, debt/equity 49%, and passes all four model families (cheapness, dividend, GARP, risk). The investment case rests on a cyclically depressed but recovering earnings base, sustained shareholder returns, and asset rotation into lower-carbon businesses. The central debate is whether current multiples adequately compensate for normalised earnings well below the 2022 peak, rising net debt, and elevated country risk in Venezuela and Libya. Primary regulatory filings were not retrieved in the source pack, limiting verification of contingencies, pension obligations, and management guidance.

---

## INVESTMENT THESIS

For a value investor, Repsol offers a classic integrated-energy profile at a discount to sector norms: composite score 74% versus a sector-relative 68%, with nine of 22 quantitative models passing, including Graham Enterprising, Earnings Yield, Low P/E + High Yield, Lynch PEG, Neff PEGY, Dividend Growth, Dreman Contrarian, Composite Value, and Financial Health. The screen’s cheapness and dividend families align with a business that has returned capital consistently (dividends of roughly €1.0–1.2bn annually per Yahoo cash-flow data) whilst shrinking the share count from ~1.41bn (2022) to ~1.13bn (2025).

Business quality is mixed but defensible. Repsol operates across upstream, downstream, and low-carbon assets, with recent news pointing to disciplined portfolio management—selling a 49.99% stake in a 705 MW Spanish renewables portfolio to Masdar (June 2025)—alongside upstream optionality in Venezuela and Libya. ROE of 9.5% is modest for a cyclical name but acceptable at current book multiples. The risk screen pass (D/E 49%) suggests balance-sheet capacity, though net debt rose sharply in 2025 (see Financial Review). At 11.4x earnings and 4.5% yield, the market appears to price mid-cycle normalisation rather than a return to 2022 super-cycle profits—a setup the quantitative screen flags as attractive for patient value accumulation.

---

## FINANCIAL REVIEW

**Source gap:** The `filings_index.json` catalogue contains 40 entries under the `euro_filings` regime, but none are Repsol regulatory filings—results are noise from unrelated “Rep.” (congressional) and third-party annual reports. Zero entries have downloadable body extracts (`with_body: 0`; no `filings/bodies/` content). No Repsol annual report, CNMV filing, or interim/half-year release is available for direct citation. **All figures below fall back to `financials_annual.json` (Yahoo Finance).**

### Revenue and profitability (Yahoo, € millions)

| Year | Revenue | Operating income | EBITDA | Net income | Diluted EPS |
|------|---------|------------------|--------|------------|-------------|
| 2022 | 75,153 | 9,471 | 9,934 | 4,251 | €2.96 |
| 2023 | 58,948 | 4,275 | 7,251 | 3,168 | €2.46 |
| 2024 | 57,122 | 2,607 | 5,605 | 1,756 | €1.43 |
| 2025 | 54,861 | 2,580 | 5,728 | 1,899 | €1.62 |

Revenue has fallen ~27% from the 2022 peak, reflecting lower commodity prices and normalising refining margins. Net income troughed in 2024 (€1.76bn) before a modest recovery in 2025 (+8% to €1.90bn), aided by fewer large unusual charges (€314m in 2025 vs €732m in 2024 per Yahoo). Normalised income (Yahoo) was €2.13bn in 2025 versus reported €1.90bn, indicating underlying earnings somewhat above the headline figure. EPS recovered from €1.43 to €1.62 despite continued share buybacks.

### Cash flow and capital allocation (Yahoo, € millions)

| Year | Operating CF | CapEx | Free cash flow | Dividends paid | Net buybacks |
|------|-------------|-------|----------------|----------------|--------------|
| 2022 | 7,832 | (3,535) | 4,297 | (989) | (1,884) |
| 2023 | 6,511 | (4,289) | 2,222 | (979) | (1,775) |
| 2024 | 4,965 | (5,106) | **(141)** | (1,153) | (1,135) |
| 2025 | 5,365 | (3,746) | 1,619 | (1,197) | (1,485) |

2024 free cash flow turned negative (–€141m) as capex exceeded operating cash generation—a red flag partially reversed in 2025 (FCF €1.62bn). Dividend payments have held or grown through the downcycle, implying payout pressure when FCF is weak. The screen’s FCF figure (~€223m) appears to reflect a more recent trailing snapshot rather than full-year 2025.

### Balance sheet (Yahoo, € millions, year-end)

| Year | Total assets | Total equity | Total debt | Net debt | Long-term provisions |
|------|-------------|--------------|------------|----------|---------------------|
| 2022 | 59,964 | 25,294 | 13,359 | 3,924 | 3,553 |
| 2023 | 61,633 | 26,197 | 10,562 | 3,462 | 4,943 |
| 2024 | 63,186 | 26,489 | 12,185 | 3,822 | 5,137 |
| 2025 | 59,428 | 25,140 | 13,238 | **7,083** | 3,002 |

Net debt nearly doubled in 2025 to €7.1bn (from €3.8bn in 2024), driven by lower cash (€3.3bn vs €4.8bn) and higher gross debt. Net debt/EBITDA (2025) is approximately 1.2x—still manageable but trending less comfortably. Long-term provisions (decommissioning, environmental, legal) stood at €3.0bn at end-2025 per Yahoo; pension detail is not available in the source pack.

### Interim / quarterly trend (Yahoo quarterly income)

No Repsol interim filing is indexed. Yahoo cached quarterly data shows Q1 2026 (period label “2026”): revenue €15.6bn, net income €929m, diluted EPS €0.82, versus Q1 2025 net income €366m and EPS €0.30—a sharp year-on-year improvement, though quarterly figures include €515m special charges and should be treated as indicative only without a primary filing.

### Impairments and unusual items

Yahoo reports significant write-offs and impairments across the period: €2.70bn unusual items in 2022, €732m in 2024, and €314m in 2025. Without filing bodies, the specific asset triggers (upstream fields, refining, renewables) cannot be verified from primary sources.

---

## RISKS AND RED FLAGS

**Cyclical and commodity exposure.** Earnings and EBITDA remain ~55–60% below 2022 levels. A prolonged oil/gas price downturn would pressure dividends and capex flexibility.

**Leverage trend.** Net debt rose ~85% in 2025 (Yahoo). Further deterioration without FCF recovery would weaken the risk-screen pass.

**Country and sovereign risk.** News flow highlights expanded Venezuela operations (PDVSA JV, June 2025) and Libyan offshore exploration (June 2025). Venezuela carries expropriation, sanctions, and payment-default history; receivable/collection risk cannot be assessed without filings.

**Energy transition and regulatory.** EU decarbonisation policy, windfall taxes, and refining margin regulation remain structural overhangs. The Masdar renewables stake sale signals asset rotation but also dependence on partner capital for growth.

**Governance and disclosure gap.** The filing discovery failure means going-concern language, litigation contingencies, covenant terms, and pension deficits are **not** available for review. This is a material research limitation.

**Geopolitical / Spain exposure.** July 2025 headlines on U.S.–Spain trade tensions drove IBEX-wide selling; Repsol’s direct revenue linkage is unclear but sentiment risk is real.

**2024 FCF deficit.** Negative free cash flow alongside rising dividends and buybacks in 2024 warrants scrutiny of payout sustainability in weaker commodity environments.

**Impairment history.** Repeated write-offs (2022–2025) suggest portfolio optimisation but also capital allocation mistakes in prior cycles.

---

## NEWS HIGHLIGHTS

Coverage is moderate—12 articles in the manifest over roughly one year, with a cluster in June–July 2025.

**Strategy and portfolio:**
- *Repsol and Masdar to partner in €849 million renewables portfolio in Spain* (12 Jun 2025) — Masdar to acquire 49.99% of 705 MW wind/solar portfolio.
- *Repsol Sells 49.99% Stake in Renewable Asset Portfolio in Spain* (15 Jun 2025) — ~€150m consideration; asset rotation.
- *Repsol: Strong Buy Following Capital Markets Day* (11 Mar 2025, Seeking Alpha) — positive sell-side reaction to CMD.
- *Upgrade: Analysts Just Made A Massive Increase To Their Repsol, S.A. (BME:REP) Forecasts* (1 May 2025, simplywall.st).

**Upstream expansion:**
- *PDVSA and Repsol sign deal to boost oil and gas output in Venezuela* (17 Jun 2025).
- *Repsol Expands Venezuela Footprint With New Oil & Gas Deals* (18 Jun 2025).
- *MOL Group, Repsol, TPAO sign agreement for Libyan offshore exploration* (16 Jun 2025).

**Macro / sentiment:**
- *Spanish Stocks Drop After Trump Says He Wants to End Trade With Spain* (8 Jul 2025, Barron’s) — IBEX-wide risk; no Repsol-specific operational impact cited.
- *Energy & Utilities Roundup: Market Talk* (8 Jul 2025, WSJ) — mentions Repsol in sector context.

No material management-change or M&A headlines appear in the manifest. News on Venezuela is strategically relevant but thin on financial terms.

---

## RESEARCH VERDICT

Verdict: accumulate  
Risk: medium  
Confidence: 0.68  
Rationale: Quantitative cheapness, dividend yield, and balance-sheet metrics support the Strong Buy screen, but absent primary filings, rising net debt, cyclical normalisation, and Venezuela/Libya exposure prevent full confirmation of the signal at maximum conviction.

## INVESTMENT THESIS


## FINANCIAL REVIEW


## RISKS AND RED FLAGS


## NEWS HIGHLIGHTS
