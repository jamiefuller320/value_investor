# Capstone Copper Corp. (CSC.AX) — Research memo

_Version 1 · Updated 2026-09-09T07:41:35.538331+00:00 · Mode: initial_

## EXECUTIVE SUMMARY
Capstone Copper Corp. is an Americas-focused copper producer (Pinto Valley, Cozamin, Mantos Blancos, Mantoverde) with a district-scale growth pipeline centred on Mantoverde Optimized, Santo Domingo, and recent San Pietro consolidation in Chile. FY2025 delivered a step-change in operating performance—copper production up 22% to 224,764 tonnes, C1 costs down to $2.44/lb, and adjusted EBITDA of $952.7 million—supported by higher realised copper prices and Mantoverde/Mantos Blancos ramp-ups. The quantitative screen rates CSC.AX as a **buy**, but published screen metrics are effectively empty (0 models passed, no composite score), so the signal rests on the label rather than disclosed factor detail. The central debate is whether record earnings and a visible growth pipeline justify accumulation after a strong share-price run, against cyclical copper exposure, heavy 2026 capex ($495 million plus $225 million capitalised stripping), rising net debt, and site-specific operational risks (Pinto Valley water constraints, Chile labour history, permitting timelines).

## INVESTMENT THESIS
For a value-oriented investor, the case rests on **earnings power inflecting ahead of the market’s full credit for 2027+ growth**, not on a deep-value trough multiple.

**Business quality.** Capstone operates four producing mines across the US, Mexico, and Chile, with FY2025 consolidated production of 224,764 tonnes at C1 cash costs of $2.44/lb and a realised price of $4.66/lb (primary filing). Adjusted EBITDA rose from $496.1 million (2024) to $952.7 million (2025)—a near-doubling driven by volume, cost improvement, and price. Management met 2025 guidance and has extended a record adjusted-EBITDA streak into 2026 (seven consecutive quarters per Q2 2026 earnings commentary in news sources). Growth options—MV Optimized (sanctioned, ~$176 million capex, ramp targeted early 2027), Santo Domingo (Orion partnership de-risking funding; FID targeted H2 2026), Mantos Blancos Phase II (EIA submitted June 2026), and San Pietro (completed August 2026)—provide multi-year copper volume optionality in tier-one jurisdictions.

**Link to quantitative screen.** The screen assigns **buy**, but `screening_snapshot.json` shows **0 of 5 model families passed**, **0 metrics present**, **null composite score**, and **insufficient_data** timing—so the buy label is not corroborated by disclosed factor-level evidence in the pack. What *does* align with a value/cash-flow screen is the operational trajectory: Yahoo-sourced TTM free cash flow of ~$295 million (FY2025 FCF $166 million per Yahoo, up from negative in 2024), operating cash flow of $685 million in 2025, and net income of $316 million ($0.41/share). Production growth plus declining unit costs improve the through-cycle earnings and FCF base that screens typically target, even if the screen’s own metric payload is missing here.

**Valuation hook (qualitative).** The investment angle is **mid-cycle producer with accelerating EBITDA and a funded growth pipeline**, trading in a market still debating peak copper margins vs structural demand. Without screen composite or peer multiples in the pack, conviction rests on operating delivery rather than a quantified discount.

## FINANCIAL REVIEW
**Source hierarchy.** Annual and Q4 FY2025 figures are from the Capstone primary filing body (`6b94f25824505d73.txt`, “Capstone Copper Reports Record Fourth Quarter 2025 Results”, 2 March 2026). Revenue and H1 2026 interim figures are **not present in available filing bodies** and are cited from `financials_annual.json` (Yahoo) with explicit fallback noted. The Q2 2026 interim ASX announcement (`1bb9ed6d2cd6de8a.txt`, 31 July 2026) contains only NI 52-109 certificates; unaudited statements were filed “under separate cover” and are **not** in the indexed body extract—a material gap for interim primary-source review.

**Annual trend (FY2025 vs FY2024) — primary filing**

| Metric | FY2025 | FY2024 | Source |
|--------|--------|--------|--------|
| Copper production | 224,764 t | 184,460 t | Filing |
| C1 cash cost | $2.44/lb | $2.76/lb | Filing |
| Realised copper price | $4.66/lb | $4.16/lb | Filing |
| Net income (attributable) | $315.9m ($0.41/sh) | $82.9m ($0.11/sh) | Filing |
| Adjusted net income | $163.6m ($0.21/sh) | n/a in extract | Filing |
| Adjusted EBITDA | $952.7m | $496.1m | Filing |
| OCF before WC changes | $891.3m | n/a in extract | Filing |
| Net debt (31 Dec 2025) | $780.1m | — | Filing |
| Cash | $304.2m | — | Filing |
| Total liquidity | $1,015.2m | — | Filing |

Reported net income ($315.9m) exceeds adjusted net income ($163.6m), indicating significant non-recurring or non-cash items in GAAP earnings—worth treating adjusted figures as the cleaner operating read.

**Revenue — Yahoo fallback.** The FY2025 filing headline cites a record revenue but does not state the dollar amount in the extracted body. Yahoo (`financials_annual.json`) shows total revenue of **$2,359.9 million (2025)** vs **$1,599.2 million (2024)**, consistent with higher volumes and prices.

**Balance sheet and cash flow — Yahoo fallback (cross-check to filing).** Yahoo reports FY2025: operating cash flow **$685.2m**, capex **$519.1m**, free cash flow **$166.1m** (vs FCF **-$49.4m** in 2024); total debt **$1,332m**, net debt **$749.7m** (Yahoo) vs filing net debt **$780.1m** at year-end—directionally consistent, minor definitional/timing differences expected. Working capital was a **$108.9m** headwind in Q4 per the filing (receivable timing).

**Interim / H1 2026 — gap and Yahoo fallback**

- **Primary gap:** No H1 2026 or Q2 2026 financial statement body is indexed; only officer certifications exist for the period ended 30 June 2026.
- **Yahoo quarterly (fallback):** Q1 2026 (Mar): revenue **$652.5m**, net income **$102.5m**, diluted EPS **$0.13**. Q2 2026 (Jun): revenue **$739.7m**, net income **$74.3m**, diluted EPS **$0.10**. Combined H1 revenue ~**$1,392m**; H1 net income ~**$177m**.
- **Operational colour (news/filing cross-reference):** Q2 2026 production of **51,800 tonnes** copper with record adjusted EBITDA (seventh consecutive quarter), per Yahoo earnings summaries in `news_manifest.json`—consistent with the H1 revenue trend but not independently verified from a primary interim filing body.

**2026 guidance (primary filing, unchanged per Q4 release)**  
Production **200,000–230,000 tonnes**; C1 costs **$2.45–$2.75/lb**; sustaining + expansionary capex **$495m** plus **$225m** capitalised stripping; exploration **$70m**.

**Trend summary.** Financials show a clear **volume + margin + price** upswing from 2024 to 2025, with FCF turning positive but still absorbing heavy growth capex. H1 2026 Yahoo data suggest continued top-line strength, though reported net income is below Q1 levels in Q2 (mix, tax, or non-operating items not visible in primary interim filings). Net debt rose through FY2025; liquidity remains adequate ($1.0bn+) but the 2026 capex programme will test balance-sheet discipline.

## RISKS AND RED FLAGS
**Filing index contamination.** A large share of indexed “annual” and “interim” entries are Chesterfield Special Cylinders (UK), not Capstone Copper. Any automated screen or research pipeline pulling those bodies would mis-state CSC.AX fundamentals—this is a governance/data-integrity red flag for the research pack itself, not Capstone’s accounts.

**Cyclical / commodity.** Forward-looking statements in Capstone filings emphasise sensitivity to copper, gold, and silver prices, treatment charges, and inflation in inputs (sulphuric acid, diesel, power). FY2025 benefited from a **$4.66/lb** realised price; a copper correction would compress EBITDA quickly despite cost improvements.

**Operational.** Pinto Valley: **26% lower 2025 production**, drought-related water constraints, C1 costs **$3.72/lb** (+33% YoY). Mantoverde: mill motor downtime in Q4 2025; **strike from 2 January 2026** (resolved with new three-year agreement announced 5 February 2026 per Q4 filing). Cathode business C1 costs rose to **$4.07/lb** on lower heap grades and acid costs.

**Leverage and capex.** Net debt **$780m** at year-end; **$495m** planned mine/project capex plus **$225m** stripping in 2026. Filing language flags **compliance with financial covenants** and surety bonding—standard but relevant given debt-funded growth (Santo Domingo FID, MV Optimized).

**Regulatory / permitting.** Mantos Blancos Phase II submitted to Chilean EIA (June 2026); production not expected until **2030–2031**. Santo Domingo FID targeted H2 2026 with permitting and financing workstreams outstanding. Delays or adverse EIA outcomes are material.

**Legal / counterparties.** Yahoo/news reference **ongoing legal action around royalty claims linked to Cozamin** and potential sale process— not detailed in indexed Capstone filing bodies; treated as unresolved until primary disclosure reviewed.

**Labour / social licence.** Chile labour relations (Mantoverde strike, Mantos Blancos agreements ratified June 2026) and community employment dependencies (Mantos Blancos ~92% local workforce) are recurring risk vectors.

**Screen-specific.** Buy signal with **zero disclosed passing models** and **null composite score** weakens automated conviction; deep research cannot fully validate the quant case from the pack alone.

RiskTags: cyclical, regulatory, leverage, liquidity, litigation, other
RiskTags: cyclical, regulatory, leverage, liquidity, litigation, other

## NEWS HIGHLIGHTS
Coverage over the past year is **moderate-to-heavy on price/momentum commentary** (numerous Kalkine, Motley Fool, Market Index pieces) with **material company-specific items** as follows:

- **3 March 2026:** “Capstone Copper Reports Record Fourth Quarter 2025 Results” (ASX PDF / filing)—record production, EBITDA, FY2025 guidance achieved. Related: “ASX copper producer falls after record Q4 performance” (Motley Fool, 3 Mar 2026)—market reaction vs strong fundamentals.
- **30 July 2026:** Q2 2026 results / “Capstone Copper Q2 Earnings Call Highlights” (Yahoo, 1 Aug 2026)—seventh consecutive record adjusted EBITDA quarter; **51,800 tonnes** Q2 production.
- **30 April 2026:** “This ASX 200 copper stock is pushing higher on record profits” (Motley Fool)—Q1 2026 earnings reaction.
- **21 June 2026:** “Capstone Announces Labour Agreement at Mantos Blancos” (ASX)—three-year union agreements ratified.
- **19 June 2026:** “Capstone Submits Environmental Permit for Mantos Blancos Phase II” (ASX).
- **31 August 2026:** “Capstone Completes Acquisition of San Pietro Copper Concessions” (ASX)—~$25m share consideration; **492Mt** inferred resource at 0.23% Cu.
- **October 2025 (prior year in window):** Orion partnership on Santo Domingo (up to **$360m** consideration structure per Q4 filing)—de-risking project funding.
- **January–February 2026:** Mantoverde strike and resolution (filing + “How Did Capstone Copper Address Mantoverde Disruptions Amid Strike?”, Kalkine, 23 Jan 2026).
- **August 2026:** “Does Capstone Copper (TSX:CS) Look Overvalued After Its 202% Run?” (Yahoo, 25 Aug 2026)—valuation debate; mentions Cozamin royalty litigation.
- **Broker sentiment:** Jefferies Buy / C$22 target (Yahoo, 19 Jun 2026); UBS buy mention (Motley Fool, 17 Dec 2025); Morgans coverage (Oct 2025).

News is **not thin**, but much is **repetitive trading commentary** rather than incremental fundamental disclosure. Primary strategic news flow (San Pietro, Mantos Blancos EIA, Mantoverde labour, record earnings) supports the growth-and-execution narrative.

## RESEARCH VERDICT
Verdict: accumulate
Risk: medium
Confidence: 0.62
Rationale: Deep research largely confirms improving operating earnings and a credible Americas copper growth pipeline, partially validating the screen’s buy label, but contaminated filing data, missing interim filing bodies, heavy capex/leverage, and an empty quantitative metric payload prevent stronger conviction.
