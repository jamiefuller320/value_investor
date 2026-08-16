# Recordati Industria Chimica e Farmaceutica S.p.A. (REC.MI) — Research memo

_Version 1 · Updated 2026-08-16T12:33:41.193351+00:00 · Mode: initial_

## EXECUTIVE SUMMARY
Recordati is a mid-cap Italian specialty pharmaceutical group with a multi-year track record of revenue and earnings growth, supported by rare-disease and established branded portfolios. The quantitative screen flags a buy on quality, GARP, and cash-generation metrics (PEG 0.77, ROE 24.9%, FCF yield 5.0%), though classic deep-value and balance-sheet screens fail on P/B (5.0×), leverage, and EV/EBIT. The central debate is whether the stock still offers public-market upside after CVC Capital Partners and Groupe Bruxelles Lambert’s May 2026 take-private approach (€10.7bn / ~$12.5bn), which may cap the valuation floor while introducing deal-completion and governance uncertainty. **Critical gap:** primary regulatory filings in the research pack are mis-attributed to UK-listed Record plc (currency manager), not Recordati; financial analysis below relies on Yahoo fallback data and must be verified against Borsa Italiana / issuer filings before trading.

---

## INVESTMENT THESIS
For a value-oriented investor, Recordati fits the “quality compounder at a reasonable growth price” bucket more than classic net-net or deep-value criteria.

**Why the screen says buy**
- Passes 10 of 22 models across five families: cheapness, quality, dividend, GARP, and risk.
- **FCF Yield**, **Lynch PEG** (0.77), **Neff PEGY**, **Buffett Quality**, **Economic Moat**, **Dividend Growth**, **Magic Formula**, **Piotroski F-Score** (7/9), **Composite Value**, and **Earnings Quality**.
- Key metrics: P/E 22.1, P/B 5.0, dividend yield 2.7%, ROE 24.9%, statutory earnings growth 28.6%, FCF ~$541m (screen TTM).
- Piotroski components show positive net income, positive OCF, OCF > net income, declining leverage, no dilution, and improving asset turnover — consistent with an asset-light, cash-generative pharma franchise rather than a cyclical commodity.

**Business quality (inferred from financial profile)**
- Revenue has grown from ~$1.85bn (2022) to ~$2.62bn (2025) per Yahoo — a double-digit CAGR — with gross margins around 68% and operating margins near 27%, typical of specialty pharma with pricing power on niche products.
- R&D spend of ~$341m (~13% of revenue) supports pipeline replenishment; selling & marketing at ~$559m reflects commercial intensity in rare disease and hospital channels.
- 2025 free cash flow rebounded to ~$512m after a 2024 trough (large intangible/asset purchases), with operating cash flow ~$597m — aligning with the screen’s FCF-yield pass.

**Why it is not a pure deep-value name**
- Fails Graham, Schloss, Deep Value, Acquirer’s Multiple, and Financial Health models owing to P/B 5.0×, P/E above Graham thresholds, EV/EBIT ~17.6×, and debt/equity ~109%.
- Negative tangible book (~$1.27bn) reflects goodwill and intangibles from acquisitions — common in pharma but limits asset-based downside protection.

**Valuation hook:** Growth (screen: 28.6%) at a sub-1.0 PEG, with quality and cash conversion, in a defensive healthcare sector — attractive if earnings durability holds and no take-private floor already prices the upside.

---

## FINANCIAL REVIEW
### Primary filings — not usable for Recordati

The `filings_index.json` catalog contains 50 entries sourced via Investegate under ticker slug `record--rec`. **All annual, interim, and trading-update bodies with text extracts refer to Record plc**, the UK specialist currency/asset manager (AUM, pence-denominated EPS, FCA-regulated entity), **not** Recordati Industria Chimica e Farmaceutica S.p.A.

Examples of mis-attribution:
- “Annual Financial Report” (19 Jun 2026): Record plc FY26, AUM $114.6bn, revenue £40.1m.
- “Half-year Financial Report” (7 Nov 2025): Record plc H1 FY26, revenue £19.2m.
- “First Quarter AUM Update” (23 Jul 2026): Record plc Q1 FY27 AUM $122.0bn.

**No valid Recordati annual report, interim report, or trading update filing bodies are present in this pack.** Interim and annual Italian/Euro issuer filings are missing for the correct entity. Going-concern, contingency, covenant, and pension disclosures from primary sources **cannot** be cited here.

All figures below are from **`financials_annual.json` (Yahoo Finance fallback)**. Currency appears to be USD as reported by Yahoo; confirm against EUR reporting in issuer filings.

### Income statement trend (Yahoo fallback)

| Year | Revenue ($m) | Net income ($m) | Diluted EPS ($) | Operating income ($m) | EBITDA ($m) |
|------|-------------|---------------|-----------------|----------------------|-------------|
| 2022 | 1,853 | 312 | 1.49 | 494 | 559 |
| 2023 | 2,082 | 389 | 1.86 | 566 | 709 |
| 2024 | 2,342 | 417 | 1.99 | 660 | 796 |
| 2025 | 2,618 | 444 | 2.12 | 720 | 887 |

- Revenue CAGR 2022–2025: ~12% — steady top-line compounding.
- Net income growth 2024–2025: ~6.5%; normalized net income (ex-unusual items) ~$484m in 2025 vs reported $444m, indicating restructuring/M&A-related charges (~$52m unusual items).
- R&D rose from ~$220m (2022) to ~$341m (2025), consistent with pipeline investment.

**Interim / quarterly (Yahoo cached quarterly income — fallback only):**
- Q1 2026 (period label “2026” in file): revenue ~$713m, net income ~$153m, diluted EPS $0.73 — implying strong YoY momentum vs Q1 2025 (revenue ~$632m, NI ~$110m, EPS ~$0.73 annualised basis differs; quarterly EPS $0.73 vs prior-year quarter not directly comparable without share count — use with caution).
- No half-year filing for Recordati is available in the index.

### Cash flow and capital allocation (Yahoo fallback)

| Year | Operating CF ($m) | CapEx/intangibles ($m) | Free cash flow ($m) | Dividends paid ($m) | Net debt issuance ($m) |
|------|-------------------|------------------------|---------------------|---------------------|------------------------|
| 2022 | 462 | — | 365 | 231 | +621 |
| 2023 | 485 | — | 102 | 246 | +80 |
| 2024 | 570 | (851) | **(281)** | 254 | +664 |
| 2025 | 597 | (85) | **512** | 268 | (16) |

- 2024 FCF was deeply negative, driven by ~$812m intangible purchases (likely acquisition-related) and ~$35m PPE capex — a one-off investment year rather than operational deterioration.
- 2025 FCF recovery (~$512m) supports the screen’s FCF-yield signal; OCF exceeded net income (Piotroski pass).
- Dividends stable-to-rising (~$268m in 2025); buybacks ~$157m.
- Working-capital drag in 2025: inventory +$135m, receivables +$63m — monitor for channel stuffing or integration effects.

### Balance sheet (Yahoo fallback, 2025)

- Total assets: ~$5.25bn; equity: ~$1.92bn.
- Total debt: ~$2.47bn (long-term ~$2.13bn; current portion ~$337m).
- Cash: ~$429m → **net debt ~$2.04bn**.
- Debt/equity (Yahoo): ~129%; screen D/E 108.6% — elevated for a value screen, failed Financial Health and Quality Value models.
- Goodwill + intangibles: ~$3.19bn → **tangible book value negative ~$1.27bn**.
- Interest expense ~$99m; EBIT ~$681m → interest coverage ~6.9× — adequate but not conservative.
- Pension/post-retirement liabilities: ~$232m (current + non-current) — moderate; no defined-benefit going-concern language available from filings.

### Alignment with quantitative screen

Screen TTM FCF ~$541m vs Yahoo 2025 FCF ~$512m — broadly consistent. Earnings growth 28.6% may reflect TTM vs fiscal-year basis or recent quarterly acceleration; reconcile before relying on PEG.

**Gaps:** No Recordati primary annual/interim filings; no segment breakdown (Rare Disease vs General Medicines); no pipeline/clinical milestone disclosure; no EUR/constant-currency figures; no debt maturity or covenant data.

---

## RISKS AND RED FLAGS
**Leverage and acquisition footprint**
- High debt/equity and negative tangible equity increase sensitivity to rate rises, integration setbacks, or EBITDA misses. 2024’s large intangible spend suggests ongoing M&A activity — execution and goodwill impairment risk (2025 impairments ~$10m on capital assets plus restructuring charges).

**Regulatory and pricing**
- Specialty/rare-disease portfolios face EU/Italian pricing pressure, HTA scrutiny, and patent-cliff risk. No primary filing language on specific product exposures; Yahoo shows heavy S&M and R&D — commercial and regulatory risk is material.

**Take-private / M&A overhang (May 2026)**
- CVC + GBL bid (~€10.7bn / $12.5bn per news) introduces event risk: deal failure could de-rate the stock; deal success caps public-market upside and raises fairness/governance questions for minority holders.

**Data integrity in research pack**
- Filing corpus is entirely wrong-entity (Record plc). Any verify-before-trade workflow must re-source Recordati filings from Borsa Italiana, the company’s investor relations site, or SEC 20-F if dual-listed — do not rely on this pack’s regulatory extracts.

**Customer / product concentration**
- Typical specialty-pharma concentration in key brands (e.g. rare endocrine, cardiovascular franchises) — not quantified in available sources.

**Screen failures as red flags**
- Graham/Deep Value/Acquirer’s Multiple failures flag that the stock is **not** statistically cheap on asset or earnings-yield metrics; value case rests on growth and quality, not margin of safety on book.

No going-concern, covenant breach, or litigation disclosures from Recordati primary filings are available in this pack.

RiskTags: regulatory, leverage, competitive, governance, other

---
RiskTags: regulatory, leverage, competitive, governance, other

## NEWS HIGHLIGHTS
Coverage is **thin on company-specific operational news**; most headlines are generic European “undervalued stocks” listicles. Material items:

| Date | Title | Relevance |
|------|-------|-----------|
| 22 May 2026 | **CVC Teams Up With GBL for $12.5 Billion Bid to Take Recordati Private** (WSJ/Yahoo) | Defining event — PE consortium take-private at ~$12.47bn valuation. |
| 22 May 2026 | **Private Equity Prescribes a Delisting for Recordati** (Yahoo) | Confirms €10.7bn deal framing; “shield from public market tremors.” |
| 28 May 2026 | **3 European Stocks That May Be Undervalued In May 2026** (Yahoo) | Generic screen mention — low informational value. |
| Apr 2026 (multiple) | European undervalued-stock listicles (Yahoo) | No Recordati-specific operational detail — **news coverage is thin** beyond the PE bid. |

No manifest entries on pipeline readouts, FDA/EMA decisions, management changes, or earnings surprises. Strategy shift = potential delisting; regulatory approval and minority-holder treatment of the CVC/GBL offer are unresolved in available sources.

---

## RESEARCH VERDICT
Verdict: accumulate
Risk: medium
Confidence: 0.58
Rationale: Yahoo-backed financials support the screen’s quality/GARP buy case (growth, ROE, FCF recovery, PEG < 1), but absent correct primary filings and with a live take-private bid limiting upside and adding event risk, conviction is moderate rather than high — confirm issuer filings and deal terms before sizing the position.
