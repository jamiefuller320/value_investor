# ME Group International plc (MEGP.L) — Research memo

_Version 2 · Updated 2026-07-20T20:51:04.188992+00:00 · Mode: gap_fill_

## EXECUTIVE SUMMARY
ME Group International operates a global network of photobooths and unattended laundry machines, generating recurring, asset-heavy cash flows from high-footfall locations. The quantitative screen flags a **strong buy** on cheapness (P/E 7.6, yield 7.3%), quality (ROE 28.2%), and balance-sheet strength (debt/equity ~28%), yet the shares sit below their 200-day moving average after a sharp June 2026 sell-off tied to a profit-guidance cut. The central debate is whether trailing financial strength and laundry expansion offset cyclical photobooth softness, governance scrutiny, and a dividend that now exceeds reported free cash flow. Primary RNS filing bodies were not available in the source pack, limiting verification of management’s revised FY2026 outlook.

---

## INVESTMENT THESIS
The screen’s **strong buy** (14/22 models passed; composite score 78%; sector-relative 87%) rests on a rare combination for a UK small/mid-cap industrial: deep value multiples, high returns on equity, a covered-looking earnings yield, and passing scores across cheapness, quality, dividend, GARP, and risk families. Yahoo-sourced financials (fallback — see Financial Review) show five years of revenue and profit growth, material deleveraging, and operating cash conversion well above net income.

For a value investor, the hook is a profitable, installed-base business trading at roughly **7–8× earnings** with a **7%+ dividend yield**, where capital is redeployed into laundry roll-out and booth refresh rather than speculative growth. The laundry segment — including the April 2026 Asda collaboration — offers a second leg that is less discretionary than photobooth usage and is currently offsetting weaker booth trading per recent news flow. Peel Hunt reiterated a buy rating on 13 July 2026, aligning with the quantitative signal despite near-term guidance uncertainty.

The screen’s **new** signal (one week at strong buy; conviction 49%) and **neutral timing** (RSI ~57, price below 200-day MA) suggest fundamental appeal without a confirmed price inflection — appropriate for phased accumulation rather than aggressive chasing.

---

## FINANCIAL REVIEW
**Primary source gap unchanged:** `filings/bodies/` contains **zero** extracts; `filings_index.json` lists 52 RNS items (`with_body: 0`) including interim *Trading Update* (1 Jun 2026) and *Q1 2026 Financial Statements — Unaudited* (13 Jul 2026), but no downloadable text. Several indexed headlines appear mis-attributed (e.g. Abri Group, SEGRO). **All figures below cite Yahoo `financials_annual.json` or screen fetch unless noted.**

### Trailing statutory trend (Yahoo fallback; FY September)

| Metric | FY2023 | FY2024 | FY2025 |
|--------|--------|--------|--------|
| Revenue (£m) | 297.7 | 307.9 | 315.4 |
| Net income (£m) | 50.7 | 54.1 | 56.6 |
| Diluted EPS (p) | 13.31 | 14.27 | 14.91 |
| Operating cash flow (£m) | 87.7 | 85.9 | 90.8 |
| Free cash flow (£m) | 33.7 | 31.3 | 25.2 |
| Cash dividends (£m) | 23.4 | 27.8 | 29.8 |
| Total debt (£m) | 90.5 | 59.8 | 43.0 |
| Cash (£m) | 103.7 | 77.5 | 56.5 |

Statutory earnings **continued to grow** through FY2025 (+4.6% net income YoY), but **FCF fell** for a third year (£33.7m → £25.2m) as capex rose to **£65.6m**. FY2025 **dividends exceeded FCF** (cover 0.84×) while **OCF cover remained ~3.0×** — the dividend sustainability debate hinges on whether investors trust operating cash (maintenance capex timing) or reported FCF (after growth capex).

### Screen-time metrics (fetch / `screening_snapshot.json`)

- **P/E 7.6**, **P/B 2.2**, **yield 7.3%**, **ROE 28.2%**, **D/E 28%**
- **Earnings growth −3.9%** (yfinance trailing; contradicts statutory FY2025 growth — likely reflects H1/guidance momentum)
- **FCF yield 3.6%** (TTM FCF ~£15.6m vs market cap ~£429m) — **fails** FCF Yield model (5% threshold)
- **Piotroski 4/9** — fails ROA improvement, OCF>NI, current-ratio improvement, asset-turnover improvement; partly distorted because **operating cash flow is not populated** in the fetch row despite Yahoo showing £90.8m

### Interim colour (news / alternate news only — not verified from RNS bodies)

- **1 Jun 2026:** H1 FY2026 revenue reportedly **+2%**; profit guidance **lowered** after weak April consumer demand (France); shares fell ~22% (*ME Group shares fall 22%…*, Yahoo Finance UK).
- **13 Jul 2026:** H1 results narrative — **laundry drives EBITDA growth**; **photobooth softness** and **lower equipment sales**; management **on track for revised FY profit** (*ME Group International H1 Earnings Call Highlights*, yfinance; *MEGP: Laundry growth offset photobooth softness…*, TradingView).
- **13 Jul 2026:** Alternate news flags **profit before tax and cash generation declined** in H1 (*MEGP: Laundry-driven growth lifted EBITDA, but profit before tax and cash generation declined*, TradingView) — supports screen momentum flags but **no primary figures** available locally.

### Remaining gaps

- No audited/interim RNS body for H1 PBT, EPS, segment revenue, or dividend declaration
- No covenant, pension, or going-concern language from filings
- `macro_context.json` absent
- `quarterly_income` empty in Yahoo cache

---

## RISKS AND RED FLAGS
**Evidenced (this gap-fill pass)**

| Risk | Evidence | Status |
|------|----------|--------|
| Cyclical / venue-traffic exposure | June 2026 guidance cut tied to France/April slowdown; photobooth softness in H1 news | **Open — operational** |
| Earnings momentum vs trailing accounts | Screen **−3.9%** earnings growth vs Yahoo FY2025 **+4.6%** NI growth | **Open — timing mismatch** |
| FCF / dividend tension | FCF yield **3.6%** (fail); FY2025 FCF **< dividends**; H1 cash generation reportedly down | **Open — elevated** |
| Piotroski weakness | **4/9**; deteriorating ROA, current ratio, asset turnover | **Open** (OCF inputs incomplete in pipeline) |
| Price / sentiment | **16% below 200-day MA**; post-H1 sceptical commentary (simplywall.st, Kalkine, 20 Jul 2026) | **Open** |
| Governance | *The boardroom problem behind Me Group's share price tumble* (Investors' Chronicle, 4 Jun 2026) | **Open — unverified from filings** |
| Capex / working capital | FY2025 capex **£65.6m**; inventory **£47.7m** (+£9.6m YoY, Yahoo) | **Open** |
| Filing catalogue quality | Mis-attributed RNS headlines; **zero** body extracts | **Structural data risk** |

**Still open — alternate source to close**

- **Dividend cut risk:** Company IR presentation PDF or H1 RNS dividend statement → explicit payout policy and board declaration
- **Covenant / going concern:** Companies House annual report PDF → borrowings note and auditor emphasis
- **Segment peak earnings:** IR slides → photobooth vs laundry revenue/margin bridge for H1 FY2026
- **Governance severity:** Corporate Governance Report RNS body (indexed 17 Jun 2026, body missing) → board composition and related-party disclosures

---

## NEWS HIGHLIGHTS
Coverage over the past year is **moderate but event-driven**; many items are generic “penny stock/dividend” listicles rather than deep company analysis.

**Material events**

| Date | Headline | Relevance |
|------|----------|-----------|
| 1 Jun 2026 | *ME Group shares fall 22% after French consumer slowdown hits profits* (Yahoo Finance UK) | Profit guidance lowered; H1 revenue +2%; major share-price catalyst. |
| 1 Jun 2026 | *ME Group Lowers 2026 Profit Expectations Following Weaker Consumer Demand in April* (Yahoo Finance UK) | Confirms macro/France weakness as driver. |
| 4 Jun 2026 | *The boardroom problem behind Me Group’s share price tumble* (Investors’ Chronicle) | Governance scrutiny. |
| 9 Apr 2026 | *Me Group climbs on Asda washing machine collaboration* (Proactive Investors) | Strategic laundry partnership. |
| 13 Jul 2026 | *ME Group International H1 Earnings Call Highlights* (Yahoo Finance) | Management says on track for **revised** FY profit; laundry growth offsets weak photobooth/equipment. |
| 13 Jul 2026 | *Me Group jumps as trading improves after France wobble* (Yahoo Finance UK) | Partial recovery sentiment post-H1. |
| 13 Jul 2026 | *ME Group International's (MEGP) Buy Rating Reiterated at Peel Hunt* (MarketBeat) | Sell-side support maintained. |
| 15 Jul 2026 | *REG - ME Group Intl. Schroders PLC - Holding(s) in Company* (TradingView) | Institutional holding disclosure. |
| 20 Jul 2026 | *We Think That There Are Some Issues For ME Group International Beyond Its Promising Earnings* (simplywall.st) | Critical post-earnings take. |
| 20 Jul 2026 | *Why Is ME Group International Raising Fresh Questions After Earnings?* (Kalkine Media) | Post-results scepticism. |
| 3 May 2026 | *ME Group International Is About To Go Ex-Dividend, And It Pays A 5.9% Yield* (simplywall.st) | Dividend/income narrative. |
| 22 Jul 2025 | *Me Group shares stuck in a cycle* (Investors’ Chronicle) | Longer-term valuation/trading pattern commentary. |

**Coverage quality:** Thin on primary-detail reporting; heavy reliance on RNS-driven market wraps. No M&A or major regulatory action identified in the manifest. Recent narrative arc: **guidance cut → governance concern → H1 stabilisation → analyst buy reaffirmation → sceptical post-earnings commentary.**

---

## RESEARCH VERDICT
Verdict: caution
Risk: medium
Confidence: 0.62
Rationale: Gap-fill confirms the quant cheapness/quality case but strengthens red flags on negative earnings momentum, sub-5% FCF yield, H1 cash-generation pressure, and absent primary filings, weakening the strong-buy signal without fully invalidating trailing balance-sheet strength.

## Weekly updates

### 2026-07-20T20:51:04.188992+00:00
Q: Photo-booth/industrial services revenue is highly cyclical and venue-traffic dependent; negative earnings growth (-3.9%) and weak Piotroski (4/9) may signal a peak-earnings trap; dividend sustainability at 7.3% yield with 3.6% FCF yield is an open question.
Status: partially_resolved
Evidence: Live fetch via `screening_snapshot.json` / fetch pipeline confirms **earnings growth −3.9%**, **FCF yield 3.6%** (FCF ~£15.6m vs market cap ~£429m), and **Piotroski 4/9** (fails on ROA, OCF>NI, current ratio, asset turnover; passes on positive NI, leverage decline, no dilution, gross margin). Yahoo `financials_annual.json` shows statutory net income still rose **+4.6%** FY2024→FY2025, so the −3.9% figure reflects yfinance trailing/forward momentum, not full-year accounts — a peak-earnings read is plausible but not proven. Alternate news (*MEGP: Laundry-driven growth lifted EBITDA, but profit before tax and cash generation declined*, TradingView, 13 Jul 2026) corroborates near-term cash/earnings pressure despite laundry EBITDA growth.
SourcesTried: filings_bodies, filings_index, yahoo_financials, news_manifest, alternate_news, screening_snapshot
NextSources: Company IR / results presentation PDF (`gap_fill_source_map.json` → `company_ir_presentation`) for H1 PBT, segment cash flow, and capex/dividend policy; Companies House annual report PDF for dividend cover and going-concern language

Q: Is the 7.3% yield sustainable given -3.9% earnings growth, 3.6% FCF yield, and a price downtrend below the 200-day MA?
Status: partially_resolved
Evidence: `screening_snapshot.json` shows **yield 7.3%**, **P/E 7.6**, **price ~16% below 200-day MA**, neutral timing. Yahoo fallback: FY2025 **dividends £29.8m** vs **FCF £25.2m** (cover 0.84×) but **operating cash flow £90.8m** (cover ~3.0×); screen TTM FCF ~£15.6m implies cover closer to **0.5×** at current payout. June 2026 trading-update headlines (*ME Group Lowers 2026 Profit Expectations…*, Yahoo Finance UK, 1 Jun 2026) and July H1 cash-generation decline (alternate news) argue payout headroom is tightening, but no RNS body states a cut or policy change.
SourcesTried: filings_bodies, filings_index, yahoo_financials, news_manifest, alternate_news, screening_snapshot
NextSources: Company IR presentation PDF for interim dividend declaration and management payout guidance; full Investegate RNS re-pull for H1 2026 cash-flow statement

Q: (Industrials) — 14/22 models (composite 78%, sector-relative 87%) with P/E 7.6, P/B 2.2, yield 7.3%, ROE 28.2%, D/E 28%. Passes Low P/E + High Yield, Buffett Quality, Economic Moat, High Dividend Yield, Magic Formula, and Financial Health; fails FCF Yield (3.6%), Lynch PEG (negative earnings growth -3.9%), and Piotroski F-Score (4/9). Price is below 200-day MA in a downtrend despite neutral timing. Sector concentration risk: one of two industrials in the top five. Verdict: watchlist — valuation and quality metrics are compelling, but shrinking earnings and sub-5% FCF yield reduce confidence.
Status: partially_resolved
Evidence: `screening_snapshot.json` and live model evaluation confirm pass/fail split: **14/22 passed** including High Dividend Yield and Financial Health; **FCF Yield**, **Lynch PEG**, and **Piotroski F-Score** fail at stated thresholds. Conviction **49%**, signal **new** (1 week). Price **16% below 200-day MA**, RSI ~57, timing **neutral**. MEGP ranks **4th of top-five** strong buys in `output/deep_analysis_payload.json`; **MGNS.L** is the second industrial (5th). Qualitative overlay aligns with **watchlist/accumulate with caution**, not full conviction.
SourcesTried: filings_bodies, filings_index, yahoo_financials, news_manifest, alternate_news, screening_snapshot
NextSources: Company IR presentation PDF to reconcile screen momentum (−3.9%) with statutory FY2025 growth (+4.6%); exchange filing full-text re-pull for interim segment margins

Q: MGNS.L (Industrials) — Fewest passes at 11/22 (composite 71%, sector-relative 75%) with P/E 13.3, P/B 3.0, yield 3.3%, ROE 25.1%, FCF yield 6.1%, D/E 18%. Passes Graham Enterprising, FCF Yield, Lynch PEG (0.49), Quality Value, Buffett Quality, Magic Formula, and Financial Health; fails Earnings Yield (7.5%), Low P/E + High Yield, Economic Moat (thin margins), High Dividend Yield, and Dreman Contrarian. Lowest conviction in the group (43%). Sector concentration risk: second industrial name alongside MEGP.L. Verdict: watchlist — solid ROE and leverage profile, but weaker pass rate and margin flags vs peers.
Status: partially_resolved
Evidence: `output/deep_analysis_payload.json` top-candidate record for **MGNS.L** matches quoted metrics (**11/22**, composite **71%**, conviction **43%**, passes include **FCF Yield** and **Lynch PEG**). MEGP.L scores higher on cheapness/yield (**14/22**, **78%**, **49%** conviction) but fails FCF Yield and Lynch PEG where MGNS passes — the two industrials are **complementary, not redundant**: MEGP is cheaper income with weaker cash-flow momentum; MGNS is higher-quality cash conversion at a richer multiple. Sector clustering (2/5 top names) remains a portfolio-level consideration, not resolved by company-specific sources.
SourcesTried: screening_snapshot (MEGP.L only local); cross-reference via deep_analysis_payload.json for MGNS.L
NextSources: MGNS.L company IR / half-year RNS (separate research pack) if comparing industrial pair trade; none required to close MEGP-specific gap

Q: This FTSE screen is broadly cautious: 164 holds and 47 avoids dwarf 9 strong buys and 22 buys, so quantitatively attractive names are a small subset of the universe. All five top candidates are new strong buys (first week at signal) with conviction scores of 43–51%, passing all five model families (cheapness, quality, dividend, GARP, risk) on 19/20 metrics. Sector clustering is modest but visible: two industrials (MEGP.L, MGNS.L) sit alongside one each in communication services, consumer defensive, and healthcare. One caution: several models flag missing balance-sheet or cash-flow inputs (NCAV, operating cash flow), and every top name fails or skips Earnings Quality and Piotroski F-Score checks — headline value scores may overstate cash-flow durability.
Status: partially_resolved
Evidence: `output/deep_analysis_payload.json` confirms **signal_distribution**: 9 strong buy, 22 buy, 164 hold, 47 avoid; top five all **strong_buy**, **new**, conviction **43–51%**, all pass **five factor families**. For MEGP specifically, live fetch shows **`operating_cashflow` is None** in the metrics row despite Yahoo FY2025 OCF £90.8m — explaining Piotroski/Earnings Quality failures driven by **missing inputs**, not necessarily weak cash generation. FCF Yield fail (3.6%) is substantive, not a data gap.
SourcesTried: screening_snapshot, macro_context (absent), fetch pipeline validation
NextSources: Ingest fix for Yahoo operating cash flow into `CompanyMetrics` (pipeline change, not external source); Companies House accounts for NCAV verification on MEGP.L

---
