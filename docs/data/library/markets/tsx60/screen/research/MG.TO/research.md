# Magna International Inc. (MG.TO) — Research memo

_Version 1 · Updated 2026-07-18T12:54:53.691264+00:00 · Mode: initial_

## EXECUTIVE SUMMARY
# Magna International Inc. (MG.TO) — First-Pass Research Memo

**Sources reviewed:** `screening_snapshot.json`, `financials_annual.json`, `news_manifest.json`, `filings_index.json`, `filings/bodies/` (8 extracts), `macro_context.json` (colour only).

**Critical data note:** SEC filing bodies in this folder are **Mistras Group, Inc. (NYSE: MG, CIK 1436126)**, not Magna International. The index labels the issuer as Magna, but every downloadable 10-K/10-Q body identifies **Mistras Group** (~$724m revenue, asset-integrity services). **No usable Magna primary filings are present.** Financial figures below are from **`financials_annual.json` (Yahoo)** unless stated otherwise. SEDAR+/Canadian interim releases for Magna are also absent from the index (only unrelated Google News hits).

---

## EXECUTIVE SUMMARY

Magna International is a global tier-one auto supplier trading at a modest absolute valuation (P/B ~1.5×, FCF yield ~8.2%, dividend ~2.9%) against a cyclical but essential franchise. The quantitative screen rates the name a **buy** on cheapness and balance-sheet risk metrics, though reported ROE (~6%) and trailing P/E (~28×) reflect weak earnings quality rather than deep cyclical trough pricing. Revenue has stabilised near **US$42bn**, but net income has fallen from **US$1.21bn (2023)** to **US$829m (2025)** amid impairments and restructuring; Q1 2026 showed a small net loss. The central debate is whether North American production recovery, ADAS/electronics wins, and strong cash conversion can re-rate a stock held back by auto-cycle risk, EV programme churn, and governance noise linked to founder Frank Stronach’s 2026 conviction.

## INVESTMENT THESIS

For a value investor, the case rests on **asset-backed cash generation at a discount to book**, not on peak earnings. The screen passes **FCF Yield, Magic Formula, Composite Value, and Financial Health** (4/22 models; composite **67%**, sector-relative **59%**; signal stable for five weeks). That aligns with Magna’s scale advantages: diversified OEM exposure, integrated body/chassis/powertrain/electronics capability, and **US$2.29bn free cash flow in 2025** (Yahoo) after capex of **US$1.31bn**—supporting a **~2.9% yield** and net debt reduction (**net debt US$3.1bn** vs **US$3.87bn** in 2024).

Business quality is **adequate, not elite**: operating margins are mid-single-digit, ROE is low, and reported earnings are noisy (2025 included **US$736m** of unusual charges, including **US$615m** asset impairments and **US$118m** restructuring per Yahoo). The screen’s “buy” therefore captures **balance-sheet and cash-yield value** more than earnings momentum. Offsetting positives include product wins such as a **European OEM Driver and Occupant Monitoring System programme** (May 2026 news) and sell-side views that North American demand is improving (Citi, June 2026; TD Securities Buy maintained, May 2026). The stock fits a **patient accumulate** profile: cheap on FCF and book, cyclically leveraged, with a credible path to normalisation if volumes hold.

## FINANCIAL REVIEW

**Source limitation:** Primary filing bodies cannot be used—they belong to Mistras Group. All figures below are from **`financials_annual.json` (Yahoo fallback)**. No Magna annual report, MD&A, or SEDAR+ interim text is available in this library.

### Annual trend (Yahoo)

| Year | Revenue (US$m) | Net income (US$m) | Diluted EPS | Operating income (US$m) | Free cash flow (US$m) |
|------|----------------|-------------------|-------------|-------------------------|------------------------|
| 2022 | 37,840 | 592 | 2.03 | 1,573 | 414 |
| 2023 | 42,797 | 1,213 | 4.23 | 2,038 | 601 |
| 2024 | 42,836 | 1,009 | 3.52 | 2,116 | 1,456 |
| 2025 | 42,010 | 829 | 2.93 | 2,110 | 2,285 |

**Revenue** recovered from the 2022 trough and has plateaued around **US$42–43bn**—flat in 2024–25, suggesting volume/mix stability but limited organic growth. **Reported earnings peaked in 2023** and declined **~32%** by 2025; normalised earnings (Yahoo: **US$1.33bn** in 2025 vs reported **US$829m**) indicate recurring charges are material.

**Cash flow is the bright spot.** Operating cash flow was **US$3.60bn** in 2025; FCF nearly doubled year-on-year to **US$2.29bn**, helped by working-capital release (receivables **+US$835m** change per Yahoo) and lower capex (**US$1.31bn** vs **US$2.18bn** in 2024). The company returned **US$544m** in dividends and **US$137m** in buybacks while reducing net debt.

### Balance sheet (Yahoo, year-end)

- **2025:** Total assets **US$31.4bn**; stockholders’ equity **US$12.5bn**; total debt **US$6.7bn**; cash **US$1.6bn**; net debt **US$3.1bn**; working capital **US$2.7bn**.
- **2024:** Net debt **US$3.9bn**; equity **US$11.5bn**.

Leverage is manageable for an auto supplier; net debt/FCF is roughly **1.3×** on 2025 FCF. Employee benefit liabilities (**US$554m** non-current) and capital leases (**US$2.0bn**) add fixed obligations typical of the sector.

### Interim / quarterly (Yahoo `quarterly_income`)

The library holds misattributed 10-Q bodies only. Yahoo quarterly data shows:

- **Q1 2025:** Revenue **US$10.63bn**; net income **US$379m**; EPS **US$1.35**.
- **Q1 2026:** Revenue **US$10.38bn**; **net loss US$12m**; EPS **(US$0.04)**; operating income **US$444m** but **US$525m** special charges including **US$485m** loss on sale of business and **US$26m** restructuring.

The Q1 2026 loss flags near-term earnings volatility; underlying operating income remained positive.

### Gaps

- No Magna **10-K, annual report, or SEDAR+ interim** in `filings_index.json` with usable bodies.
- Cannot verify going-concern language, covenant headroom, pension footnotes, or contingency disclosures from primary Magna filings.
- Yahoo quarterly coverage in the library is limited to 2025 and 2026 Q1 only.

## RISKS AND RED FLAGS

**Filing data gap:** Risk language from indexed SEC bodies (debt covenants, multi-employer pensions, acquisition restrictions under credit agreement) applies to **Mistras**, not Magna, and is excluded here.

**Earnings quality and cyclicality (Yahoo):** Three-year earnings decline despite flat revenue; recurring restructuring (**US$118m** in 2025) and impairments (**US$615m**). Q1 2026 net loss driven by disposal-related charges. Auto production cycles, OEM pricing pressure, and EV programme shifts are structural risks not fully captured by static value screens.

**Returns:** ROE **~6%** (screen) is below cost of equity for most investors; P/E **~28×** on trailing reported earnings is not statistically cheap on earnings alone—the value case depends heavily on FCF and book.

**Governance and reputational:** *Frank Stronach, Magna International Founder, Is Found Guilty in Sex-Crimes Case* (WSJ via yfinance, **19 June 2026**). Stronach is no longer operational leadership, but the verdict is a material governance/reputation overhang for a founder-linked Canadian corporate icon.

**Competitive / strategic:** Tier-one suppliers face margin compression from electrification (fewer powertrain parts), Chinese OEM localisation, and OEM insourcing of software/ADAS. Magna’s mirror-integrated DMS win (May 2026) is positive but insufficient alone to offset programme losses elsewhere.

**Macro (colour only):** CAD/USD **0.713** and TSX Composite level are noted; tariff/trade-policy uncertainty affects cross-border auto supply chains. Not used to override the screen signal.

**News noise:** Several indexed headlines (M&G plc, unrelated SEDAR items) are false positives; Magna-specific coverage is moderate but not thin.

## NEWS HIGHLIGHTS

Material Magna-related items from `news_manifest.json` (past year):

| Date | Headline | Relevance |
|------|----------|-----------|
| **15 Jul 2026** | *Why Magna International Inc stock is rising today* (Wealth Awesome) | Sentiment/flow; no fundamental detail in manifest. |
| **14 Jul 2026** | *Will Magna (MGA) Beat Estimates Again in Its Next Earnings Report?* (yfinance) | Positive earnings-surprise track record cited. |
| **13 Jul 2026** | *Zacks Value Trader Highlights: Werner, Magna and Jabil* | Value-screen attention. |
| **7 Jul 2026** | *Is Magna International (MGA) Stock Undervalued Right Now?* (yfinance) | Value narrative in mainstream coverage. |
| **26 Jun 2026** | *Citi Sees Magna International (MGA) Benefiting From North American Demand Recovery* | Citi raised PT to **US$75** from **US$58**; **Neutral** rating. |
| **19 Jun 2026** | *Frank Stronach, Magna International Founder, Is Found Guilty in Sex-Crimes Case* (WSJ/yfinance) | Major governance/reputation event. |
| **25 May 2026** | *Does Magna International (TSX:MG) Have A Mirror-Integrated Edge In Auto Safety Electronics?* | European OEM DMS/OMS programme award; ADAS differentiation. |
| **15 May 2026** | *Magna International Inc (MGA) Stock Down 4.6% but Still Overvalued -- GF Score: 78/100* (GuruFocus) | Contrarian value score vs “overvalued” label. |
| **14 May 2026** | *TD Securities Maintains Buy Rating on Magna International (MGA)* | Buy maintained; PT raised to **US$76**; positive Q1 commentary referenced. |
| **7 Jun 2026** | *Is Magna International Inc. (MGA) A Good Stock To Buy Now?* (yfinance) | Retail/value-investing interest; trailing P/E ~28×, forward ~9.75× cited. |

**Not Magna:** *UBS downgrades M&G to ‘neutral’* (17 Dec 2025) refers to UK insurer M&G plc, not MG.TO.

Coverage is **adequate** on valuation, analyst actions, and the Stronach verdict; **thin** on detailed operational updates (no Magna earnings release text in the manifest).

## RESEARCH VERDICT

Verdict: accumulate  
Risk: medium  
Confidence: 0.65  
Rationale: The quantitative buy signal is supported by FCF yield, book discount, and de-leveraging, but primary Magna filings are missing (SEC bodies are misattributed to Mistras), earnings are declining and volatile, and governance headlines warrant caution rather than full conviction.

## INVESTMENT THESIS


## FINANCIAL REVIEW


## RISKS AND RED FLAGS


## NEWS HIGHLIGHTS
