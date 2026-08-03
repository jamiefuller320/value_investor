# Hikma Pharmaceuticals PLC (HIK.L) — Research memo

_Version 2 · Updated 2026-08-03T21:34:43.328383+00:00 · Mode: gap_fill_

## EXECUTIVE SUMMARY
Hikma is a FTSE 100 generic and specialty pharmaceutical group with three engines — US/MENA/Europe Injectables, MENA Branded, and North American Hikma Rx — trading on low double-digit earnings multiples with a ~3.9% yield and active capital returns. FY2025 delivered 6% core revenue growth and 3% core operating profit growth to $741m, but reported operating profit fell 11% after a sodium oxybate antitrust settlement, and management has withdrawn medium-term margin guidance while guiding Injectables margins down to 27–28% in 2026. The value case rests on durable Branded momentum, a refocused Hikma Rx franchise, BBB-rated balance sheet strength, and a $250m buyback plus 5% dividend increase; the key debate is whether Injectables margin compression and weak statutory cash conversion are cyclical mix effects or a structural reset after November 2025’s guidance revision.

## INVESTMENT THESIS
The quantitative screen flags Hikma as a strong buy across five families — cheapness, quality, dividend, GARP, and risk — with full data quality (20/20 metrics) and sector-leading relative score (91%). At P/E 11.7, P/B 1.8, ROE 16.5%, debt/equity 62%, and 3.9% yield, the name passes classic value screens (Graham Enterprising, Earnings Yield, Low P/E + High Yield, Lynch/Neff PEG, Magic Formula, Acquirer’s Multiple, Dreman Contrarian, Composite Value, Financial Health). That cheapness is not purely mechanical: filings show core EBITDA of $853m (+4%), return on average invested capital of 16.0%, and investment-grade ratings (S&P and Fitch BBB/stable, per FY2025 results release).

Business quality is bifurcated in a way screens only partly capture. Branded grew core revenue 10% with core operating margin expanding to 26.4%; Hikma Rx held ~$1bn revenue with margin ahead of plan at 17.3%. Injectables remains the profit pool but is under pressure: core operating margin fell from 35.3% to 31.0% on US competition, Xellia mix dilution, euro strength, and inventory provisions. For a value investor, the hook is a cash-generative, geographically diversified generics platform trading below peer multiples while returning capital (84c total dividend, +5%; $250m 2026 buyback) — with the screen’s cash-conversion overlay (FCF yield 3.6% vs 5% hurdle; filing-aligned FCF $119m) already tempering the headline signal to adjusted Buy.

## FINANCIAL REVIEW
**Primary sources:** FY2025 audited results (`filings/bodies/ir_0e40d9707e30c3b7.txt`, 26 Feb 2026); H1 2025 interim presentation (`ir_a70365d580129295.txt`); 2025 annual report highlights (`ch_05557934_MzUxODk1NDgyN2FkaXF6a2N4.txt`). **Secondary:** Yahoo `financials_annual.json` for cash-flow line items and dividend cash paid. **Still missing:** April 2026 trading update body (`ir_a9733d0de6aec27d`, refetch attempted per `gap_fill_source_map.json`); alternate news confirms guidance reaffirmed (23 Apr 2026 headlines only).

**FY2025 (year ended 31 Dec 2025) — filings**

| Metric | 2025 | 2024 | Change |
|--------|------|------|--------|
| Revenue (reported) | $3,349m | $3,127m | +7% (+6% CC) |
| Core revenue | $3,349m | $3,156m | +6% (+5% CC) |
| Operating profit (reported) | $542m | $612m | −11% |
| Core operating profit | $741m | $719m | +3% |
| Core EBITDA | $853m | $824m | +4% |
| Profit attributable to shareholders | $402m | $359m | +12% |
| Core profit attributable | $503m | $495m | +2% |
| Basic / core EPS | 182c / 228c | 162c / 224c | +12% / +2% |
| Total dividend | 84c | 80c | +5% |
| Operating cash flow | $436m | $564m | −23% |

Segment core revenue: Injectables $1,423m (+7%), Branded $849m (+10%), Hikma Rx $1,037m (flat). Reported operating profit reflects the sodium oxybate antitrust settlement; total settlement-related cash outflows were $186m, with management citing ~10% underlying OCF growth excluding those payments.

**Cash flow and FCF reconciliation (gap-fill)**

| Line | Source | 2025 ($m) |
|------|--------|-----------|
| Operating cash flow | Filing + Yahoo | 436 |
| Capex — PPE (filing) | FY2025 release | 197 |
| Capex — Yahoo "Capital Expenditure" | Yahoo (PPE + intangibles + other) | 317 |
| **Filing-aligned FCF (OCF − Yahoo CapEx)** | `screening_snapshot.json` canonical | **119** |
| Yahoo Free Cash Flow line | Yahoo | 119 |
| Screen TTM FCF (pre-reconciliation) | `screening_snapshot.json` | **−66.1** |
| Cash dividends paid | Yahoo | 185 |

The **authoritative figure for screening key metrics and FCF yield is filing-aligned $119M** (FY2025, USD). The −$66.1M screen TTM is a preserved Yahoo trailing input that diverges from the latest fiscal year; its driver cannot be verified locally because `quarterly_income` / quarterly cash flow are empty in `financials_annual.json`. On narrow FCF, the 84c dividend (~$185M cash) is **not covered** (0.64×); on OCF it is comfortably covered (2.4×). Planned 2026 capital returns (5% higher dividend + $250m buyback) against reported OCF leave little headroom unless conversion improves or settlement cash flows do not repeat.

**Balance sheet (filing):** Net debt $1,387m; 1.6× net debt / core EBITDA (1.4× prior year); total debt $1,604m; cash $217m; working capital days 245. Refinancing completed (Jul–Nov 2025: $500m Eurobond, $250m IFC loan, $400m syndicated loan). Going concern assessment positive (Note 2 extract in FY2025 body).

**H1 2025 interim (filing presentation):** Core revenue $1,657m; core operating profit $429m; core EPS 122c; operating cash flow $161m (vs $198m H1 2024); net debt / core EBITDA 1.7× at Jun 2025. Injectables core margin compressed to 30.0% (36.3% H1 2024). Full-year guidance at interim (Group core OP $730–770m) was met at $741m.

**2026 outlook (filing, constant currency):** Revenue +2–4%; core operating profit $720–770m; Injectables margin 27–28%; medium-term Group and Injectables margin guidance withdrawn. Alternate news (Apr 2026) reports guidance reaffirmed and 503B compounding exit; **figures not verified** without the trading-update body.

**Remaining gaps:** Product-level revenue concentration; full cash-flow note reconciling PPE vs intangible spend; pension and covenant detail (annual report page 82+ not extracted); quarterly data to explain TTM FCF divergence.

---

## RISKS AND RED FLAGS
**Evident from filings and news**

- **Injectables margin reset (evidenced):** Core margin 31.0% (2025), guided 27–28% (2026); medium-term margin guidance withdrawn after Nov 2025 revision and Dec 2025 strategic review (`ir_0e40d9707e30c3b7.txt`).
- **Product and pricing pressure (evidenced):** US competition on testosterone, calcitonin; expected sodium oxybate erosion in Hikma Rx 2026; usual generic price erosion cited throughout FY2025 narrative.
- **Legal (evidenced, partially resolved):** $72m Xyrem® antitrust settlement charge; ~$186m total settlement cash flows; previously disclosed contingent liabilities now settled (`ir_0e40d9707e30c3b7.txt`, Note 5 extract).
- **Pipeline breadth without concentration data (partially evidenced):** 118 Injectables pipeline products, 84 launches, nine new Hikma Rx filings — but **no % revenue from top N products** in available extracts.
- **Regulatory/manufacturing (partially evidenced):** FDA-inspected plants referenced in annual report; Bedford commercial production not until 2028; China-sourced tariff impact ~$3m in 2025. **No active FDA Warning Letter or OAI language** in current bodies.
- **Capital allocation tension (evidenced):** $185m dividends + $250m buyback planned vs $119m filing-aligned FCF and $436m OCF; net debt rose ~$270m YoY; leverage 1.6× still moderate and BBB-rated.
- **Governance churn (evidenced):** CEO/CFO/Board restructuring Feb 2026; Brookfield Rule 2.8 no-offer statement (4 Feb 2026, `50e3a03fa9de81ca.txt`).
- **Patent-cliff exposure (news, not quantified locally):** Pfizer VYNDAMAX settlement with Hikma (Apr 2026 news) extends US patent to 2031 — relevant to generic pipeline timing but product-level P&L impact not in filings pack.

**Still open — source to close**

| Open item | Would unlock |
|-----------|----------------|
| Principal risks pages 82–90 (full annual report extract) | Quantified regulatory, geopolitical, and concentration disclosures |
| FDA enforcement database scrape | Site-specific GMP/action exposure |
| April 2026 trading update PDF body | Verified YTD cash flow, 503B exit financials, guidance bridge |
| Quarterly cash-flow series | Reconciliation of screen TTM −$66M vs FY $119M |
| Orange Book / IQVIA product share | Pipeline cliff and US generic concentration metrics |

**Macro (colour only):** GBP/USD 1.35 and FTSE 100 ~10,868 (`macro_context.json`); Hikma reports in USD with euro/MENA mix — FX remains an earnings translation risk, not a screen veto.

---

## NEWS HIGHLIGHTS
Coverage over the past year is moderate on company-specific fundamentals but heavier on sector rotation and broker commentary; many Google News hits are generic “healthcare stocks in London” pieces rather than Hikma-specific analysis.

**Material items (with dates/titles from `news_manifest.json`):**

- **26 Feb 2026:** “Hikma’s shares plummet after guidance cut” (Investors’ Chronicle); “Hikma Pharma tumbles on softer guidance as buyback fails to soften pill” (Yahoo Finance UK) — FY2025 results with softer 2026 outlook, $250m buyback, leadership changes.
- **24 Apr 2026:** “Hikma Pharmaceuticals Reiterates 2026 Guidance, Exits 503B Compounding in April Trading Update Call” (Yahoo) — encouraging start to 2026; guidance reaffirmed (body not in filing pack).
- **4 Feb 2026:** Brookfield Rule 2.8 statement — no offer for Hikma (Investegate/RNS).
- **16 Jul 2026:** “Citi starts Hikma at 'buy'” — strategy reset, £17 PT (Yahoo).
- **22–23 Jul 2026:** “Hikma recovery story still has further to run… Panmure” (Yahoo); “Hikma and Fresenius best positioned from Trump's generic drug tariffs, says Citi” (Yahoo); “Shares in Generic-Drug Makers Fall After Trump’s Tariff Plan” (WSJ/Yahoo).
- **28–30 Apr 2026:** Pfizer VYNDAMAX settlement with Hikma, Dexcel, Cipla extending US patent protection to 2031 (Yahoo) — limits near-term generic entry on tafamidis, relevant to Hikma’s pipeline ambitions.
- **5 Jun 2026:** “Generic drugmakers gain key victory in ‘skinny label’ patent case” (Yahoo) — sector-positive Supreme Court ruling.
- **2 May 2026:** “Independent Chairman… Victoria Hull Buys 241% More Shares” (Simply Wall St).
- **24 Jul 2026:** “Wellington Management… Lowers Stake… Below 5%” (kalkinemedia).
- **7 Aug 2025:** “Across The Markets: Hikma, IHG, Harbour Energy” (Investegate) — H1 2025 interims, operating profit down 26% on tough comps and mix; tariff concerns cited.

**Thin spots:** Limited RNS depth in the news manifest beyond results/guidance days; no detailed sell-side model revisions in primary filings; April 2026 trading update PDF not parsed.

## RESEARCH VERDICT
Verdict: accumulate
Risk: medium
Confidence: 0.71
Rationale: Gap-fill establishes positive FY2025 filing-aligned FCF ($119M) and OCF-backed dividend capacity, partially offsetting the negative screen-TTM artefact, but thin FCF versus combined dividend and buyback, Injectables margin guidance downgrades, and missing concentration/regulatory depth keep the case short of a clean strong-buy confirmation.

## Weekly updates

### 2026-08-03T21:34:43.328383+00:00
Q: Generic-drug and injectables businesses face patent-cliff and pricing/regulatory risk; the screen does not assess pipeline concentration or FDA/EMA action exposure.
Status: partially_resolved
Evidence: FY2025 results (`filings/bodies/ir_0e40d9707e30c3b7.txt`) cite 118 Injectables pipeline products (15 ready-to-use), 84 Group launches, US competition on testosterone and calcitonin, expected sodium oxybate competition in 2026, and a resolved Xyrem® antitrust settlement; the 2025 annual report extract (`ch_05557934_MzUxODk1NDgyN2FkaXF6a2N4.txt`) references US FDA-inspected plants but not revenue concentration by product or active FDA/EMA enforcement actions — the principal risks section is indexed to page 82 and not fully extracted.
SourcesTried: filings_bodies, filings_index, yahoo_financials, news_manifest, alternate_news, screening_snapshot, macro_context
NextSources: Full annual report page 82–90 risk extract (`ir_3a67962eb8770824`); FDA inspections/enforcement database (OAI/WL/483) for Hikma US sites; FDA Orange Book / EMA product register for top-generic revenue share; company IR pipeline slide deck (`planned_alternate_sources`: company_ir_presentation)

Q: FCF data is inconsistent (filing-aligned FCF $119M vs screen TTM −$66.1M); dividend sustainability with FCF yield 3.6% and weak earnings quality is an open question.
Status: partially_resolved
Evidence: `screening_snapshot.json` stores both figures under `fcf`: canonical $119M (`source`: `filing_aligned_ocf_capex`, fiscal year 2025) and `screen_ttm` −$66.1M; Yahoo `financials_annual.json` reconciles the canonical figure as OCF $436M plus Capital Expenditure −$317M = $119M, matching Yahoo's Free Cash Flow line; the FY2025 filing body reports statutory capex of $197M (PPE) versus Yahoo's broader $317M capex bucket (PPE $197M + intangibles $120M). Cash dividends paid were $185M in 2025 (Yahoo), exceeding filing-aligned FCF but covered ~2.4× by OCF ($436M); management states OCF would have risen ~10% excluding $186M legal-settlement cash flows (`ir_0e40d9707e30c3b7.txt`).
SourcesTried: filings_bodies, filings_index, yahoo_financials, screening_snapshot
NextSources: Hikma cash-flow statement bridge in full annual report (PPE vs intangible vs acquisition outflows); quarterly cash-flow ingest to explain Yahoo TTM −$66M (no quarterly rows in local `financials_annual.json`)

Q: Which FCF figure is authoritative (filing-aligned $119M vs screen TTM −$66.1M), and is the 3.9% dividend safe given weak free-cash conversion and the Buy downgrade on the cash-conversion overlay?
Status: partially_resolved
Evidence: For scoring and key metrics, **`screening_snapshot.json` treats filing-aligned $119M as canonical** (`fcf.canonical`, `key_metrics.FCF`); `screen_ttm` −$66.1M is the preserved Yahoo universe trailing input (`src/value_investor/scoring/fcf.py` priority: OCF−CapEx → Yahoo FCF line → screen TTM). The cash-conversion overlay still triggers on **`screen_ttm`**, not canonical FCF (`cash_conversion_overlay.py` uses `screen_ttm_from_row`), which explains Strong Buy → Buy despite positive FY2025 FCF. Dividend: 84c total ($185M cash paid) is ~1.6× filing-aligned FCF and ~0.4× core profit ($503M); 2026 planned returns ($250m buyback + continued dividend, per FY2025 release) sit against reported OCF of $436M with no settlement repeat assumed — near-term serviceable on OCF, tight on narrow FCF, and the screen correctly fails FCF Yield (3.6% vs 5%) and Earnings Quality.
SourcesTried: filings_bodies, yahoo_financials, screening_snapshot, macro_context
NextSources: 2026 interim cash-flow and capex run-rate; covenant/liquidity language from full annual report notes (not in current body extracts); April 2026 trading update PDF (`filings_index.json` id `ir_a9733d0de6aec27d`, body still missing after IR refetch)

Q: (Hikma Pharmaceuticals) — Healthcare. Thirteen of 22 models pass (composite 81%, sector-relative 91%)… Verdict: watchlist — attractive GARP and quality pass rate, but FCF conversion weakness and mixed Piotroski score argue for confirmation before accumulation.
Status: partially_resolved
Evidence: `screening_snapshot.json` confirms 13/22 passes, five families, P/E 11.7, P/B 1.8, yield 3.9%, ROE 16.5%, D/E 62%, Lynch PEG on 23.5% earnings growth; failures include FCF Yield, Piotroski 6/9 (leverage not declining; gross margin and asset turnover not improving), Earnings Quality, Economic Moat; adjusted signal Buy after cash-conversion overlay. Gap-fill clarifies FCF conversion is **positive but thin** on FY2025 filing-aligned basis ($119M), not negative — weakening the watchlist's "negative FCF" rationale but not removing Piotroski/Earnings Quality/FCF Yield failures; conviction remains modest (54%, new one-week signal).
SourcesTried: screening_snapshot, filings_bodies, yahoo_financials, news_manifest, alternate_news
NextSources: Two consecutive quarters of OCF and capex to confirm conversion trend; post-settlement H1 2026 interim (`ir_allowlist` interim slot)

Q: This FTSE screen is broadly neutral-to-cautious: 147 Hold vs 62 Buys… conviction scores modest (49–55%)… NCAV missing… tension between headline value and cash-flow quality.
Status: unresolved
Evidence: Hikma-specific snapshot confirms new signal (1 week), conviction 0.5364, Graham Net-Net fail (`missing NCAV`), and the headline FCF tension documented above; universe-level counts (147 Hold / 62 Buys / sector clustering of top five) are stated in the red-flag prompt but **not present in local HIK.L sources** — `macro_context.json` provides FX/index colour only (GBP/USD 1.35, FTSE 100 10,868) and explicitly excludes scoring use.
SourcesTried: screening_snapshot, macro_context, gap_fill_source_map
NextSources: Weekly universe screening export with cross-name conviction, family-pass counts, and NCAV availability flags; peer-set cash-flow reconciliation table (other FTSE Strong Buys: FGP.L, MEGP.L, MGNS.L, ITV.L)

---
