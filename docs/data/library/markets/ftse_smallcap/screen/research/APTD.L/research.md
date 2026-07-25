# Aptitude Software Group plc (APTD.L) — Research memo

_Version 1 · Updated 2026-07-25T12:00:24.729119+00:00 · Mode: initial_

## EXECUTIVE SUMMARY
Aptitude Software Group plc (APTD.L) is a UK-listed financial and enterprise performance-management software provider that the quantitative screen rates as a **buy**, chiefly on cash generation and quality metrics rather than growth. The valuation hook is an ~8.8% FCF yield, Piotroski and earnings-quality passes, and a Neff PEGY of 0.11, set against a headline P/E of 28.7, ROE of 7.2%, and reported revenue growth of −9.7%. The central debate is whether strong FY2025 free cash flow, net cash of roughly £21m, and an active **formal sale process** under the Takeover Code justify accumulation, or whether two years of top-line contraction, goodwill-heavy intangibles, and the absence of parsed annual or interim filing bodies leave the value case unverified. Primary regulatory extracts in the source pack contain only Takeover Code disclosures — not audited accounts — so financial trends below rely on Yahoo fallback.

## INVESTMENT THESIS
The FTSE Small Cap screen rates APTD.L **buy** (5/22 models, composite 52%, sector-relative 57%), passing all four factor families — cheapness, quality, GARP, and risk — with full metric completeness (20/20). Passed models (**FCF Yield**, **Neff PEGY**, **Magic Formula**, **Piotroski F-Score**, **Earnings Quality**) point to a cash-generative, financially stable small-cap rather than a deep cyclical bargain.

For a value investor, the case rests on three pillars visible in secondary data. First, **cash economics**: Yahoo-sourced FY2025 free cash flow of **£9.3m** on an implied market capitalisation of roughly **£120–125m** (54.6m shares × ~226p from May 2026 Form 8 (DD) dealings) supports the screen’s FCF yield pass despite reported earnings pressure. Second, **balance-sheet optionality**: cash of **£29.6m** against total debt of **£8.3m** (Yahoo, FY2025) implies net cash, limited refinancing risk, and capacity for dividends (~£3.0m paid in FY2025) and buybacks (~£5.1m repurchased). Third, **event-driven upside**: filing bodies and news confirm the company is an **offeree** under the Takeover Code following a strategic review including a **formal sale process** (marketscreener headline, 27 May 2026), with repeated Form 8.3 disclosures from Invesco (~1.72% stake), Schroders, and others.

Business quality is mixed. Aptitude operates in **financial data solutions** for regulated enterprises (Kalkine Media, 17 Dec 2025), where switching costs can be sticky. Operating income has held up (**£6.6m** in FY2025 vs **£6.5m** in FY2024 per Yahoo) even as revenue fell, and gross margin expanded to **55.7%** from **47.8%**, suggesting cost discipline. However, ROE of **7.2%**, recurring restructuring charges (£0.9–1.8m annually), and **negative tangible book value** (~£−3.8m) temper the quality narrative. The screen’s buy signal is therefore a **cash-yield plus optionality** call more than a classic earnings compounder.

## FINANCIAL REVIEW
**Source limitation (primary filings):** `filings_index.json` lists **five Companies House annual accounts** (filed April 2022 through June 2026) but **none have downloadable body extracts** (`has_body: false` for all). **No interim or half-year RNS results** are indexed (`interim: 0`). The ten available filing bodies under `filings/bodies/` are exclusively **Takeover Code disclosures** (Form 8.3 major-holding notifications; Form 8 (DD) director dealings; deferred bonus plan exercise) — they confirm a sale process and share prices (~226p) but contain **no revenue, profit, balance-sheet, going-concern, covenant, or pension disclosures**. All financial figures below are from **`financials_annual.json` (Yahoo Finance fallback)**.

**Income statement trends (Yahoo, FY2022–FY2025; year-end assumed 31 December from DBP RNS reference to “year ended 31 December 2023”)**

| Metric | FY2022 | FY2023 | FY2024 | FY2025 |
|--------|--------|--------|--------|--------|
| Revenue | £74.4m | £74.7m | £70.0m | **£65.0m** |
| Operating income | £4.1m | £6.3m | £6.5m | £6.6m |
| Reported net income | £2.6m | £4.1m | £5.0m | **£4.0m** |
| Normalised net income | £2.9m | £5.0m | £5.7m | £5.6m |
| Basic EPS | 4.5p | 7.2p | 8.8p | **7.3p** |
| EBITDA (reported) | £8.2m | £9.9m | £10.8m | £9.7m |
| Restructuring / M&A charges | £0.4m | £1.1m | £0.9m | **£1.8m** |

**Annual observations:** Revenue peaked in FY2023 and has contracted for two consecutive years (−6.2% in FY2024, −7.3% in FY2025), consistent with the screen’s **−9.7% growth** flag. Reported net income fell **19%** year-on-year in FY2025 despite stable operating income, driven by higher restructuring costs (£1.8m). Normalised earnings (~£5.6m) are more stable than reported, supporting the screen’s **Earnings Quality** pass and third-party commentary that **conservative accounting may explain soft headline earnings** (Simply Wall St, 17 Apr 2026). Gross profit recovered to **£36.2m** in FY2025 (from £33.5m in FY2024) even as revenue fell, reflecting margin expansion.

**Balance sheet (Yahoo, FY2024 → FY2025)**

- Total assets: £114.8m → **£106.4m**
- Shareholders’ equity: £57.9m → **£54.2m**
- Cash and equivalents: £30.4m → **£29.6m**
- Total debt: £10.1m → **£8.3m** (includes ~£2.4m capital lease obligations)
- **Net cash:** approximately **£21m**
- Goodwill: **£46.0m** (unchanged); other intangibles **£12.0m**
- **Tangible book value:** £−3.5m → **£−3.8m**
- Working capital: £−3.0m → **£0.6m** (improved)
- Share count (basic average): 56.8m → **55.4m** (buybacks reducing float)
- Retained earnings: £−0.02m → **£−2.4m** (cumulative deficit)

The balance sheet is **cash-rich but intangible-heavy**. Goodwill and intangibles of **£57.9m** exceed total equity, leaving negative tangible net assets — a material impairment risk if trading or sale-process outcomes disappoint. Debt is modest relative to cash; **covenant terms, pension obligations, and lease commitments cannot be assessed** from available filing bodies.

**Cash flow (Yahoo)**

| | FY2022 | FY2023 | FY2024 | FY2025 |
|--|--------|--------|--------|--------|
| Operating CF | £3.2m | £11.0m | £6.8m | **£10.1m** |
| CapEx | £0.8m | £0.6m | £1.6m | **£0.7m** |
| Free cash flow | £2.3m | £10.4m | £5.2m | **£9.3m** |
| Dividends paid | £3.1m | £3.1m | £3.1m | **£3.0m** |
| Share repurchases | — | £0.2m | £4.1m | **£5.1m** |

FY2025 FCF rebounded strongly (+79% year-on-year), driven by working-capital release (£1.1m) and lower capex, underpinning the screen’s **FCF Yield** pass. FCF has been volatile historically (£2.3m → £10.4m → £5.2m → £9.3m), warranting caution on sustainability. A **£33.1m business acquisition in FY2021** (Yahoo cash-flow note) explains the large goodwill base.

**Interim / trading updates:** **None indexed and no interim filing bodies available.** Recent price-sensitive activity is limited to Takeover Code disclosures and executive share-plan exercises (DBP RNS, 29 May 2026). No H1 2026 revenue or profit figures are in the source pack.

**Gaps:** No annual report or interim results body; no audit opinion; no going-concern, contingency, covenant, or pension language accessible. Companies House annual metadata exists but was not ingested as text. FY2025 Yahoo figures should be treated as indicative until verified against the next full RNS annual results.

## RISKS AND RED FLAGS
**Takeover / strategic uncertainty:** Filing bodies frame Aptitude as an **offeree** under the Takeover Code, with a **formal sale process** underway (news, 27 May 2026). Outcomes range from a premium bid to process failure and renewed standalone execution risk. Invesco’s Form 8.3 filings show **sales** at ~234p (19 May 2026) while holding ~1.72% — indicative of active position management during the process, not necessarily a directional view.

**Revenue decline:** Two years of top-line contraction challenge the GARP and Magic Formula passes; a software model typically requires re-acceleration or sustained cost-out to protect margins.

**Intangible asset and impairment risk:** Goodwill of **£46.0m** on **£54.2m** equity and **negative tangible book** mean a failed sale or weaker trading could trigger write-downs. **Impairment testing language is unavailable** in filing bodies.

**Returns on capital:** Screen ROE **7.2%** and third-party concern over **returns on capital** (Yahoo Finance, 10 Sep 2025) align with a low-growth, acquisition-legacy profile.

**Earnings vs cash divergence:** Strong FY2025 FCF (£9.3m) vs reported net income (£4.0m) supports the value case but may reflect working-capital timing; prior-year FCF volatility shows this is not uniformly smooth.

**Governance / insider activity:** CEO Alexandra Curran exercised deferred bonus shares and sold **754 shares at 226.6p** to cover tax (Form 8 (DD), 29 May 2026) — routine, not necessarily negative, but insider holdings remain small (0.02%). Large LTIP overhang (~369k shares under option/award per correction filing, 1 Jun 2026) creates future dilution.

**Primary filing red flags:** **Not assessable.** No going-concern, contingency, covenant, or pension disclosures in available bodies. Companies House accounts are listed but not parsed.

**Small-cap liquidity:** FTSE Small Cap name with event-driven volatility during a sale process.

**Competitive / cyclical:** Financial software for regulated enterprises faces competition from larger ERP/analytics vendors; IT budget cycles can defer renewals — not quantified in sources but consistent with revenue softness.

## NEWS HIGHLIGHTS
Coverage over the past year is **thin on fundamental developments** and **dominated since May 2026 by Takeover Code Form 8.3 dealing notices** (Invesco, Schroders, CGAML — multiple entries Jul 2026). Material APTD-specific items:

- **27 May 2026** — “Aptitude Software Group plc Provides Update on Strategic Review, Including Formal Sale Process” (marketscreener.com): **most significant item** — confirms active sale process following strategic review.
- **26 Jun 2026** — “REG - Aptitude Software Schroders PLC - Notification of Major Holdings” (TradingView): major-holder disclosure during offer period.
- **29 May / 1 Jun 2026** — DBP exercise and Form 8 (DD) director dealings (also in filing bodies): CEO share exercises at ~£2.27.
- **17 Apr 2026** — “Aptitude Software Group's (LON:APTD) Conservative Accounting Might Explain Soft Earnings” (Simply Wall St): third-party view on earnings quality.
- **20 Jan 2026** — “Shareholders in Aptitude Software Group (LON:APTD) are in the red if they invested five years ago” (Yahoo Finance): long-term total-return disappointment.
- **24 Dec 2025** — “Is Aptitude Software Group plc (LON:APTD) Trading At A 26% Discount?” (Yahoo Finance): third-party DCF suggesting fair value ~£3.81 — unverified in primary sources.
- **1 Oct 2025** — “Weak Financial Prospects Seem To Be Dragging Down Aptitude Software Group plc (LON:APTD) Stock” (Yahoo Finance).
- **10 Sep 2025** — “Some Investors May Be Worried About Aptitude Software Group's (LON:APTD) Returns On Capital” (Yahoo Finance).
- **17 Dec 2025** — “Aptitude Software Group plc Operating Across FTSE All-Share in Financial Data Solutions” (Kalkine Media): sector context only.

Several yfinance “UK Penny Stocks” listicles mention APTD without company-specific analysis — **noise**. No regulatory enforcement, pension crisis, or management departure headlines appear. **News coverage is thin on operational detail** and heavily skewed to the sale process and holder disclosures since May 2026.

## RESEARCH VERDICT
Verdict: accumulate
Risk: medium
Confidence: 0.58
Rationale: The quantitative buy is partially confirmed by strong FY2025 FCF, net cash, and sale-process optionality, but primary filing gaps and two years of revenue decline prevent full confirmation of earnings quality and balance-sheet risks.
