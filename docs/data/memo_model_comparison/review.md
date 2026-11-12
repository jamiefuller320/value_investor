# Memo model comparison — owner calibration sample (blind)

Comparison `memo-model-comparison-2026-11`, rule v2. An LLM judge has scored every pair; you rate only these 4 names so the judge can be checked against you. Each name has two memos, **A** and **B**, written by two different models from the same frozen filing bodies, the same prompt and the same as-of date. Do not open `blind_key.json`, `results.json`, `judge_results.json`, `calibration.json`, `judgements/` or the `status.json` cost fields until every name here is rated.

Rate each memo 1 (poor) to 5 (excellent) on:

- `evidence` — Evidence grounding: claims are tied to the filings and nothing looks invented.
- `thesis_break` — Thesis breaks: it says concretely what would make this a do-not-own name.
- `verdict_justified` — Verdict justified: verdict and confidence match the evidence shown.

Then pick `preferred`: `A`, `B` or `tie` — which memo you would rather the strategy book act on. Copy `ratings_template.json` to `ratings.json` in this folder, fill it in and commit it to main. Automation never writes `ratings.json`.

## 1. Softcat plc (SCT.L) — ftse350

Screen `buy` on 2026-11-06; operating decline `clear`, sector `sound`; RSI 29.73; 67 filing bodies. Ratings key: `ftse350__SCT.L`.

### Memo A

- **Verdict:** accumulate · **Risk:** medium · **Confidence:** 0.73
- **Rationale:** FY2026 filings confirm strong cash conversion and £150.9m operating FCF, supporting the screen buy on quality/dividend, but rich multiples, margin compression, GDT-funded leverage and equity dilution cap conviction at accumulate.
- **Risk tags:** leverage, customer_concentration, competitive, cyclical

Evidence:
- [filings/bodies/1ab161025358253f.txt] "Underlying cash conversion 1 of 93.6%, with closing net cash and cash equivalents of £199.9m (FY2025: £182.3m)." — Strong profit-to-cash track record ahead of the GDT deal.
- [filings/bodies/1ab161025358253f.txt] "Net cash generated from operating activities 157.5 140.7" — Filing operating cash flow reconciles to the screen’s filing-aligned FCF bridge (FY2026 vs FY2025).
- [filings/bodies/1ab161025358253f.txt] "total ordinary dividend for the year to 31.5p per share (FY2025: 29.3p), amounting to £66.1m (FY2025: £53.9m)." — Progressive dividend policy; ordinary cash cost for cover vs operating FCF.
- [filings/bodies/1ab161025358253f.txt] "gross margin declining year-on-year to 13.1% (FY2025: 13.7%)." — Quality screen passes coexist with reported margin pressure.
- [filings/bodies/1ab161025358253f.txt] "estimated net debt leverage is forecast to be c.1.3x, and expected to be below 1.0x by July 2028." — Post-GDT leverage step-change versus historic net-cash balance sheet.
- [filings/bodies/1ab161025358253f.txt] "greater than 10% of the Group’s total revenue, and a considerably lower proportion of gross profit." — Single-customer revenue concentration disclosure.
- [filings/bodies/02c6f791c8e4abad.txt] "signed an agreement to acquire GDT Topco, L.P. (\" GDT \"), a leading US-based, multi-vendor IT solutions provider for an enterprise value of $1,050m (£785m [1] )" — Scale and integration risk behind the new leverage profile.

Numbers:
- Net cash from operating activities | 157.5 | FY ended 31 Jul 2026 | [filings/bodies/1ab161025358253f.txt]
- Underlying cash conversion | 93.6% | FY ended 31 Jul 2026 | [filings/bodies/1ab161025358253f.txt]
- Cash and cash equivalents | £199.9m | 31 Jul 2026 | [filings/bodies/1ab161025358253f.txt]
- Total ordinary dividend | 31.5p (£66.1m) | FY ended 31 Jul 2026 | [filings/bodies/1ab161025358253f.txt]
- Gross profit margin (GII basis) | 13.1% | FY ended 31 Jul 2026 | [filings/bodies/1ab161025358253f.txt]
- Forecast net debt leverage (post-GDT) | c.1.3x | post-completion (filing outlook) | [filings/bodies/1ab161025358253f.txt]
**Screen vs filings (reconciliation):** Screen FCF £150.9m (filing-aligned FY2026) matches preliminary cash flow (operating £157.5m less capex £6.6m). Yield 2.8% and dividend-family passes align with 31.5p ordinary DPS; filing ordinary dividends (£66.1m) sit well below operating FCF, so no sub-1.0× ordinary-dividend tension on filing figures (earnings growth on screen is Yahoo TTM ~14.1% vs underlying EPS growth ~19.7% in the preliminary release). `adjusted_signal` remains `buy`, same as raw—no automated research downgrade in the snapshot.

Thesis breaks:
- Audited accounts or a trading update showing underlying cash conversion persistently below the Group’s 85%–95% target range, with ordinary dividends maintained.
- GDT closing with net debt leverage materially above the c.1.3x outlook, or covenant stress disclosed in a subsequent filing.
- A FY2027 profit warning citing sustained gross margin below 12% on GII without a credible recovery path.
- Loss of the >10% revenue customer or a material bad-debt event against the stated £75m per-customer credit ceiling.

### Memo B

- **Verdict:** accumulate · **Risk:** medium · **Confidence:** 0.72
- **Rationale:** FY2026 filings confirm the quality cash-generation behind the screen buy, but pending GDT 1.3x leverage, a £502.2m customer, GP-margin mix-down and a nil special versus 16.1p keep the overlay at accumulate.
- **Risk tags:** regulatory, cyclical, competitive, leverage, customer_concentration, key_person

Evidence:
- [filings/bodies/1ab161025358253f.txt] "Underlying cash conversion 1 of 93.6%, with closing net cash and cash equivalents of £199.9m (FY2025: £182.3m)." — Supports the quality/financial-health buy: FY2026 cash conversion remains high and the year-end position is net cash (pre-GDT).
- [filings/bodies/1ab161025358253f.txt] "Net cash generated from operating activities 157.5 140.7" — Filing OCF £157.5m less PPE £6.0m and intangibles £0.6m equals FCF £150.9m, matching the snapshot filing-aligned figure; Yahoo/screen TTM FCF £144.8m is slightly lower (unflagged). Screen FCF yield still failed at 4.5%.
- [filings/bodies/1ab161025358253f.txt] "Special dividend (p) - 16.1p" — Dividend-family screens passed and filing FCF/dividends paid is 1.63× (snapshot net cover), not below 1.0×; interim DPS rose to 9.9p and is not flagged as a cut. The tension is FY2026 special DPS at nil versus 16.1p, while ordinary DPS rose to 31.5p. Snapshot gross cover of −0.06× is not a filing cash-flow figure. `adjusted_signal` remains buy.
- [filings/bodies/1ab161025358253f.txt] "gross margin declining year-on-year to 13.1% (FY2025: 13.7%)." — Mix-driven GP-margin compression; screen earnings growth of 14.1% (Yahoo TTM) is close to filing basic EPS 75.8p versus 66.6p, below underlying EPS 83.2p versus 69.5p.
- [filings/bodies/1ab161025358253f.txt] "Revenue generated from this customer in FY2026 was £502.2m, predominantly derived from the UK subsidiary." — One customer exceeded 10% of IFRS revenue (GP share described only as considerably lower); concentration is not in the screen metrics.
- [filings/bodies/02c6f791c8e4abad.txt] "Estimated net debt leverage of 1.3x at closing and forecast leverage to be below 1.0x by July 2028, in line with new target leverage range of 0.5-1.0x." — Screen D/E of 10% is pre-deal leases; GDT financing (cash, £550m facilities, equity) is still pending close (HSR/CFIUS), so the risk-family pass does not capture post-close leverage.
- [filings/bodies/02c6f791c8e4abad.txt] "For the year ended 31 December 2025, GDT reported attributable net income of $(58.4)m, as shown in its consolidated income statement." — Target was loss-making on US GAAP after amortisation and current-structure interest; completion, integration and key-person retention remain open.
- [filings/bodies/1ab161025358253f.txt] "Looking ahead, and excluding the contribution from GDT, business momentum remains strong and the Board expects to deliver high single-digit underlying operating profit growth in FY2027" — Organic growth is guided to slow after FY2026 underlying operating profit of £215.1m (+19.4%).

Numbers:
- Gross profit | 616.3 | year ended 31 July 2026 | [filings/bodies/1ab161025358253f.txt]
- Underlying operating profit | 215.1 | year ended 31 July 2026 | [filings/bodies/1ab161025358253f.txt]
- Net cash generated from operating activities | 157.5 | year ended 31 July 2026 | [filings/bodies/1ab161025358253f.txt]
- Cash and cash equivalents | 199.9 | 31 July 2026 | [filings/bodies/1ab161025358253f.txt]
- Total ordinary dividend (p) | 31.5p | year ended 31 July 2026 | [filings/bodies/1ab161025358253f.txt]
- GDT attributable net income | $(58.4)m | year ended 31 December 2025 | [filings/bodies/02c6f791c8e4abad.txt]

Thesis breaks:
- GDT is blocked by HSR/CFIUS, or post-close US GAAP losses persist without the guided c.$80m EBITDA, leaving the Group with 1.3x+ leverage and no earned accretion.
- The £502.2m customer is lost and the GP impact proves material rather than “considerably lower”.
- Organic FY2027 underlying operating profit falls versus the high-single-digit guide after the FY2025–FY2026 surge.
- Filing FCF covers ordinary dividends below 1.0×, or the ordinary DPS is cut (the FY2026 interim was 9.9p, up from 8.9p).

## 2. Volex plc (VLX.L) — ftse350

Screen `buy` on 2026-11-06; operating decline `clear`, sector `sound`; RSI 32.29; 59 filing bodies. Ratings key: `ftse350__VLX.L`.

### Memo A

- **Verdict:** accumulate · **Risk:** medium · **Confidence:** 0.7
- **Rationale:** FY2026 RNS and H1 FY2027 trading support the screen’s quality/GARP/risk pass (35.9% statutory EPS growth, 0.8× covenant leverage, 4.8p dividend, ~4× filing FCF cover), but adjusted hold remains: screen TTM FCF £6m vs filing-aligned ~£35m...
- **Risk tags:** cyclical, customer_concentration, competitive, leverage, accounting

Evidence:
- [filings/bodies/85f5b7d712418cd4.txt] "Statutory basic earnings per share 35.2c 25.9c 35.9%" — Confirms filing-aligned statutory EPS growth used by the GARP/quality screen (FY2026 vs FY2025).
- [filings/bodies/85f5b7d712418cd4.txt] "At 31 March 2026, the Group's covenant leverage was 0.8 times (30 March 2025: 1.0 times)." — Supports low covenant leverage and the risk-family pass; reconciles with screen D/E ~46%.
- [filings/bodies/85f5b7d712418cd4.txt] "was $38.8 million (FY2025: $36.8 million)." — Statutory free cash flow (pre-financing definition in the cash-flow commentary); basis for filing-aligned FCF vs screen TTM £6.0m.
- [filings/bodies/85f5b7d712418cd4.txt] "full-year dividend of 4.8 pence per share (FY2025: 4.5 pence per share), an increase of 6.7%." — Progressive dividend policy; filing cover is strong on statutory OCF−capex (~4.1× per screen), not a sub-1.0× cut case.
- [filings/bodies/85f5b7d712418cd4.txt] "Cash conversion was 63.9% (FY2025: 67.2%), reflecting working capital investment to support strong Data Centre revenue growth" — Explains weak earnings-quality/FCF-yield screen fails despite positive absolute FCF.
- [filings/bodies/9714011bf0d2995f.txt] "covenant leverage as at 30 September 2026 expected to be no more than 1.2x." — H1 FY2027 balance-sheet message; leverage still moderate but above year-end 0.8×.
- [filings/bodies/85f5b7d712418cd4.txt] "Volex's share of the estimated liability in respect of tax, interest and penalties accrued to 31 March 2026 amounts to $8.7m." — Associate tax uncertainty (Kepler SignalTek) as an accounting/governance watchpoint.

Numbers:
- Statutory basic earnings per share | 35.2c | FY ended 31 March 2026 | [filings/bodies/85f5b7d712418cd4.txt]
- Covenant leverage | 0.8 times | 31 March 2026 | [filings/bodies/85f5b7d712418cd4.txt]
- Free cash flow (statutory definition in RNS) | $38.8 million | FY2026 | [filings/bodies/85f5b7d712418cd4.txt]
- Full-year dividend | 4.8 pence per share | FY2026 | [filings/bodies/85f5b7d712418cd4.txt]
- Cash conversion | 63.9% | FY2026 | [filings/bodies/85f5b7d712418cd4.txt]
- H1 group revenue (expected) | at least $710 million | six months to 30 September 2026 | [filings/bodies/9714011bf0d2995f.txt]
*(Screen reconciliation: raw signal buy; `adjusted_signal` hold. Filing-aligned FCF £35m — source `financials_annual.json` / Yahoo FY2026 cash flow, GBP metric in `screening_snapshot.json` — vs screen TTM FCF £6.0m; dividend-family models fail on unresolved FCF/yield basis, not an interim cut.)*

Thesis breaks:
- Covenant leverage at or above 3.0× or sustained breach of banking covenants disclosed in a primary filing.
- FY statutory free cash flow (or OCF−capex) falling below total cash dividends such that progressive 4.8p policy is explicitly withdrawn or cut.
- H1/FY revenue or underlying operating profit materially below Board guidance (e.g. loss of Data Centre momentum after normalised supply conditions).
- Materialisation of Kepler SignalTek tax exposure well above the $8.7m accrued share, with a stated P&L or cash impact in regulated accounts.

### Memo B

- **Verdict:** accumulate · **Risk:** medium · **Confidence:** 0.72
- **Rationale:** FY2026 filings confirm the buy case (EPS +35.9%, 0.8× leverage, 4.8p dividend with ~4× statutory OCF−CapEx cover); screen hold overlay remains TTM FCF £6m vs filing $35m, not cover below 1.0×.
- **Risk tags:** cyclical, customer_concentration, competitive, key_person

Evidence:
- [filings/bodies/85f5b7d712418cd4.txt] "Basic earnings per share were 35.2 cents (FY2025: 25.9 cents), an increase of 35.9%." — Filing statutory EPS growth matches the screen’s 35.9% filing-basic-EPS input.
- [filings/bodies/85f5b7d712418cd4.txt] "Cash conversion was 63.9% (FY2025: 67.2%), reflecting working capital investment to support strong Data Centre revenue growth, with underlying free cash flow consistent at $42.3 million" — Dual FCF: management underlying $42.3m versus statutory OCF−CapEx ~$35m; conversion explains the Earnings Quality fail.
- [filings/bodies/85f5b7d712418cd4.txt] "Year-end covenant leverage improved to 0.8x (FY2025: 1.0x), providing substantial headroom and financial flexibility" — Supports the risk-family pass; headroom versus the 3.0× covenant.
- [filings/bodies/85f5b7d712418cd4.txt] "Together with an interim dividend of 1.6 pence per share paid in December 2025, this equates to a full-year dividend of 4.8 pence per share (FY2025: 4.5 pence per share), an increase of 6.7%." — Progressive dividend; no interim cut; cash paid $8.5m implies ~4× statutory cover, not sub-1.0×.
- [filings/bodies/85f5b7d712418cd4.txt] "Complex Industrial Technology was the largest growth contributor, with revenue growing 56.3% organically to $382.9 million, including strong Data Centre demand from a leading hyperscale customer" — Customer-concentration watchpoint; Data Centre is 63.0% of this end-market.
- [filings/bodies/5d778465510adb00.txt] "this particular dynamic may not recur at the same level in FY2027." — FY2026 Data Centre outperformance included non-recurring share gains while peers were supply-constrained.
- [filings/bodies/9714011bf0d2995f.txt] "Data Centre revenues were well ahead of the prior-year comparator, although below the second half of FY2026." — H1 FY2027 (unaudited) confirms normalisation, not a collapse; Group H1 revenue expected at least $710 million.
- [filings/bodies/85f5b7d712418cd4.txt] "Consumer Electricals organic revenue declined 7.8% to $242.4 million, against a strong prior-year comparative and amid intensified Chinese competition in Europe." — Cyclical/competitive offset to the quality/GARP case.

Numbers:
- Statutory basic earnings per share | 35.2 cents | year ended 31 March 2026 | [filings/bodies/85f5b7d712418cd4.txt]
- Underlying free cash flow | $42.3 million | FY2026 | [filings/bodies/85f5b7d712418cd4.txt]
- Net cash generated from operating activities | 69.8 | FY2026 ($'m) | [filings/bodies/85f5b7d712418cd4.txt]
- dividend payments | $8.5 million | FY2026 | [filings/bodies/85f5b7d712418cd4.txt]
- Year-end covenant leverage | 0.8x | 31 March 2026 | [filings/bodies/85f5b7d712418cd4.txt]
- screen_ttm | 6037500.0 | TTM (not filing-aligned) | [screening_snapshot.json]

Thesis breaks:
- Filing disclosure that the leading hyperscale Data Centre customer has been lost, or Data Centre revenue falls below the H1 FY2027 normalised run-rate without offset from other end-markets.
- Statutory OCF−CapEx dividend cover falling below 1.0×, or an announced interim or final dividend cut.
- Covenant leverage moving towards the 3.0× facility limit after further acquisitions or buybacks (H1 FY2027 expected no more than 1.2× after KST; statutory H1 accounts are not in this pack).
- A disclosed single-customer revenue share that would make the “diversified five end-market” case unsupportable (largest-customer percentage is unknown in these files).

## 3. BP p.l.c. (BP.L) — ftse350

Screen `buy` on 2026-11-06; operating decline `clear`, sector `headwind`; RSI 37.3; 23 filing bodies. Ratings key: `ftse350__BP.L`.

### Memo A

- **Verdict:** caution · **Risk:** high · **Confidence:** 0.64
- **Rationale:** Research weakens the buy: FY2025 statutory profit $0.1bn and FCF down 10%, 3Q26 transition impairments of $3.0-4.5bn, and a chair-removal; H1 cash and a 4% dividend rise leave FCF-definition and leverage gaps open.
- **Risk tags:** regulatory, cyclical, governance, leverage, key_person, litigation, accounting

Evidence:
- [filings/bodies/ch_00102498_MzUyMjUzNDU3OWFkaXF6a2N4.txt] "In 2025 we delivered a strong underlying financial performance with an underlying RC profit* of $7.5 billion*, despite a weaker price environment, and operating cash flow* of $24.5 billion." — FY2025 cash generation versus a $0.1bn statutory profit.
- [filings/bodies/ch_00102498_MzUyMjUzNDU3OWFkaXF6a2N4.txt] "the board's decision earlier this year to suspend the share buyback and fully allocate excess cash to our balance sheet." — Buybacks halted; surplus cash steered to deleveraging, not distributions.
- [filings/bodies/ch_00102498_MzUyMjUzNDU3OWFkaXF6a2N4.txt] "net cash provided by operating activities of $24.5 billion for 2025 and $27.3 billion for 2024 and total cash capital expenditure of $14.5 billion for 2025 and $16.2 billion for 2024" — Filing FCF analogue ~$10bn, down 10% YoY, versus screen TTM 17,024m.
- [filings/bodies/df6a1cd88bf86224.txt] "This follows serious concerns raised to the Board related to important governance standards, oversight and conduct." — Chair removed 26 May 2026; key-person and governance risk not closed by the later Tyler appointment.
- [filings/bodies/acc5f13b25ec0afb.txt] "We have not delivered consistently; we have written off too much value; and our costs and liabilities are not resilient enough in a low price environment." — CEO assessment of repeated impairments and weak low-price resilience.
- [filings/bodies/9e846a677d72f46e.txt] "The third quarter results are expected to include post-tax adjusting items relating to impairments in the range of $3.0 to 4.5 billion." — 3Q26 transition write-offs still hanging over statutory earnings; 3Q results themselves are not in the filing set.
- [filings/bodies/acc5f13b25ec0afb.txt] "2Q 2026 dividend per ordinary share of 8.66 cents, 4% increase." — Dividend raised, not cut; cover >1.0× so the failed dividend-family screens are an earnings-growth/FCF-basis issue, not a cover break.
- [filings/bodies/68220e3a16d9d65c.txt] "Total net proceeds to bp of c.$6 billion, including accelerated dividend payments, will be fully utilised to reduce net debt." — Castrol proceeds (completion still pending at 30 June 2026) are the main planned deleveraging bridge.

Numbers:
- Profit for 2025 attributable to bp shareholders | $0.1bn | FY2025 | [filings/bodies/ch_00102498_MzUyMjUzNDU3OWFkaXF6a2N4.txt]
- Net cash provided by operating activities | $24.5 billion for 2025 | FY2025 | [filings/bodies/ch_00102498_MzUyMjUzNDU3OWFkaXF6a2N4.txt]
- Total cash capital expenditure | $14.5 billion for 2025 | FY2025 | [filings/bodies/ch_00102498_MzUyMjUzNDU3OWFkaXF6a2N4.txt]
- Finance debt | $58.0bn | 31 December 2025 | [filings/bodies/ch_00102498_MzUyMjUzNDU3OWFkaXF6a2N4.txt]
- Profit for the period attributable to bp shareholders | 3,911 | 2Q 2026, $ million | [filings/bodies/acc5f13b25ec0afb.txt]
- Free Cash Flow | 11272000000.0 | 2025 (Yahoo fallback; screen TTM 17024000000.0) | [financials_annual.json]

Thesis breaks:
- A dividend cut versus the 2Q26 8.66 cents rate, or filing FCF (operating cash flow less total capital expenditure) covering dividends below 1.0×.
- The Castrol sale failing to complete, so the c.$6 billion of debt-reduction proceeds are not received.
- A further chair, CEO or board-level governance event after the 26 May 2026 removal of Albert Manifold.
- Net debt remaining at or above the FY2025 $22.2 billion level instead of falling toward the $14–18 billion end-2027 target (3Q26 guide $13.5–14.5 billion was a trading-statement estimate only).

### Memo B

- **Verdict:** accumulate · **Risk:** medium · **Confidence:** 0.64
- **Rationale:** The snapshot is **Hold** (not buy); filings support underlying cash, ~2.2× filing FCF dividend cover and deleveraging, but statutory EPS collapse, FCF vs TTM gap, leverage and governance weaken a full buy case.
- **Risk tags:** cyclical, leverage, governance, regulatory, other

Evidence:
- [filings/bodies/ch_00102498_MzUyMjUzNDU3OWFkaXF6a2N4.txt] "profit* of $7.5 billion*, despite a weaker price" — underlying 2025 earnings strength vs weak macro
- [filings/bodies/ch_00102498_MzUyMjUzNDU3OWFkaXF6a2N4.txt] "We reduced net debt * to $22.2 billion'" — year-end leverage anchor for screen debt metrics
- [filings/bodies/acc5f13b25ec0afb.txt] "Net debt* was $22.3 billion at the end of the second quarter" — interim balance-sheet progress
- [filings/bodies/68220e3a16d9d65c.txt] "Total net proceeds to bp of approximately $6.0 billion" — announced Castrol proceeds for debt reduction
- [filings/bodies/5e081f531bbecc85.txt] "raising gross proceeds of approximately NOK 9.83 billion ($1.06 billion)" — additional 2026 divestment cash
- [filings/bodies/df6a1cd88bf86224.txt] "unanimously decided that Albert Manifold should no longer serve as Chair and Director with immediate effect" — governance red flag
- [filings/bodies/9e846a677d72f46e.txt] "post-tax adjusting items relating to impairments in the range of $3.0 to 4.5 billion" — near-term transition/write-down risk
- [filings/bodies/cacf1f9924c4b859.txt] "net debt is expected to increase to between $25 to 27 billion" — 1Q26 working-capital volatility vs annual net-debt trend

Numbers:
- Free cash flow | 11272000000.0 | FY2025 | [financials_annual.json] *(Yahoo fallback; screen filing-aligned FCF)*
- Screen TTM free cash flow | 17024000000.0 | TTM (screen) | [screening_snapshot.json]
- FCF dividend coverage (net) | 2.2281083218027278 | FY2025 basis | [screening_snapshot.json]
- Statutory basic EPS growth | -0.8529411764705883 | filing basic EPS YoY | [screening_snapshot.json]
- Underlying RC profit | $7.5 billion* | FY2025 | [filings/bodies/ch_00102498_MzUyMjUzNDU3OWFkaXF6a2N4.txt]
- Net debt | $22.2 billion* | FY2025 | [filings/bodies/ch_00102498_MzUyMjUzNDU3OWFkaXF6a2N4.txt]

Thesis breaks:
- Confirmed statutory FY loss or material dividend cut with FCF/dividend cover sustained below 1.0× on filing cash flows.
- Castrol or other guided divestments fail to complete, leaving net debt above stated $14–18bn targets through 2027.
- Further board or senior leadership disruption beyond the May 2026 chair removal, with disclosed governance or conduct findings.
- Transition/low-carbon impairments materially above the 3Q26 $3.0–4.5bn guide, alongside repeated statutory EPS weakness vs underlying RC profit.

## 4. STX (STX) — nasdaq100

Screen `buy` on 2026-11-09; operating decline `clear`, sector `sound`; RSI 31.96; 69 filing bodies. Ratings key: `nasdaq100__STX`.

### Memo A

- **Verdict:** accumulate · **Risk:** medium · **Confidence:** 0.72
- **Rationale:** FY2026 filed OCF $3.67bn and FCF $3.11bn match the screen and cover dividends (~$634m); cyclical HDD demand, leverage, customer concentration and export/BIS risk temper conviction vs a blind buy.
- **Risk tags:** cyclical, customer_concentration, leverage, regulatory, competitive

Evidence:
- [filings/bodies/0e21ebab31a84200.txt] "In fiscal year 2026, one customer accounted for approximately 14% of our consolidated revenue." — material customer concentration risk
- [filings/bodies/0e21ebab31a84200.txt] "• We may not be able to generate sufficient cash flows from operations and our investments to meet our liquidity requirements, including servicing our indebtedness and continuing to declare our quarte" — dividend and debt hinge on cash generation
- [filings/bodies/0e21ebab31a84200.txt] "product transitions and periodic fluctuations in supply and demand." — industry cyclicality and pricing volatility
- [filings/bodies/0e21ebab31a84200.txt] "expectations regarding our ability to service debt, comply with debt covenants and continue to generate free cash flow" — management flags debt covenant and FCF linkage
- [filings/bodies/0e21ebab31a84200.txt] "settlement agreement with the U.S. Department of Commerce’s Bureau of Industry and Security (“BIS”); the impact of macro" — export-control / regulatory overhang
- [sec_companyfacts.json] — FY2026 XBRL cash-flow facts align with screen `operating_cashflow` and `free_cashflow` (not Yahoo TTM)

Numbers:
- Operating cash flow | 3674000000.0 USD | FY ended 2026-07-03 (10-K filed 2026-08-04) | [sec_companyfacts.json]
- PP&E capital expenditure | 569000000.0 USD | FY ended 2026-07-03 | [sec_companyfacts.json]
- Free cash flow (OCF − capex) | 3105000000.0 USD | FY ended 2026-07-03 | [sec_companyfacts.json]
- Dividends paid (common) | 634000000.0 USD | FY ended 2026-07-03 | [sec_companyfacts.json]
- Screen free cash flow | 3105000000.0 | snapshot (Yahoo-sourced FY) | [screening_snapshot.json]
- TTM free cash flow (Yahoo) | 4157000000.0 | quarterly TTM to 2026-09-30 | [screening_snapshot.json] — above filed FY2026; period basis differs

Thesis breaks:
- Filed annual FCF falling below cash dividends for two consecutive fiscal years without a disclosed, sustainable funding plan
- Disclosure that a single customer above ~14% of revenue materially reduced or ended purchases, with no offsetting volume elsewhere
- Public statement of debt covenant breach, inability to service indebtedness, or suspension/cut of the quarterly dividend despite prior guidance
- Failure to meet BIS settlement payment timing or a material new U.S./China export restriction on products or rare-earth supply called out in filings

### Memo B

- **Verdict:** accumulate · **Risk:** medium · **Confidence:** 0.68
- **Rationale:** Research confirms the buy on FY2026 statutory FCF of $3.1bn (4.9× dividend cover) and strong Q1 FY2027 cash generation, while HDD/cloud cyclicality, 14% customer concentration and empty screen model passes cap conviction.
- **Risk tags:** cyclical, competitive, customer_concentration, litigation, regulatory

Evidence:
- [filings/bodies/0e21ebab31a84200.txt] "In fiscal year 2026, one customer accounted for approximately 14% of our consolidated revenue." — FY2026 single-customer concentration.
- [filings/bodies/0e21ebab31a84200.txt] "The vast majority of our business is derived from the Data Center markets. Demand in these markets may fluctuate based on customer procurement and deployment schedules" — cloud/data-centre cyclicality of the earnings run-rate.
- [filings/bodies/0e21ebab31a84200.txt] "Our global competitors include HDD manufacturers such as Western Digital Corporation and Toshiba Electronics Devices & Storage Corporation along with NAND flash suppliers" — HDD oligopoly plus SSD substitution risk.
- [filings/bodies/0e21ebab31a84200.txt] "These reductions in demand have required us to significantly reduce manufacturing production plans and recognize factory underutilization charges in fiscal years 2024 and 2023." — prior-cycle FCF/utilisation collapse still in the record.
- [filings/bodies/550fe7f57dd99afc.txt] "During the September 2026 quarter, we shipped 220 exabytes of HDD storage capacity. We generated revenue of approximately $4.2 billion with a gross margin of 57.3% and net income of $1.8 billion." — Q1 FY2027 operating strength after FY2026.
- [filings/bodies/550fe7f57dd99afc.txt] "Net cash provided by operating activities 1,690 532" — Q1 FY2027 operating cash flow of $1,690m versus $532m a year earlier.
- [filings/bodies/550fe7f57dd99afc.txt] "On October 27, 2026, the Board of Directors of the Company declared a quarterly cash dividend of $ 0.76 per share" — dividend maintained and increased; no interim cut.

Numbers:
- operating_cashflow | 3674000000.0 | fiscal year ended 2026-07-03 | [sec_companyfacts.json]
- capital_expenditure | 569000000.0 | fiscal year ended 2026-07-03 | [sec_companyfacts.json]
- free_cashflow | 3105000000.0 | fiscal year ended 2026-07-03 | [sec_companyfacts.json]
- dividends_paid | 634000000.0 | fiscal year ended 2026-07-03 | [sec_companyfacts.json]
- Net cash provided by operating activities | 1,690 | three months ended October 2, 2026 | [filings/bodies/550fe7f57dd99afc.txt]
- free_cashflow_ttm | 4157000000.0 | Yahoo TTM (not 10-K aligned) | [screening_snapshot.json]

Thesis breaks:
- A full fiscal year in which statutory OCF−PP&E capex falls below dividends paid (cover under 1.0×), as utilisation charges in FY2023–24 showed is possible.
- Loss, multi-quarter deferral or export-block of the customer that was about 14% of FY2026 revenue, without an offsetting hyperscale win.
- Failed or delayed HAMR/Mozaic qualification that hands nearline share to Western Digital or Toshiba, or a step-change in SSD substitution in data-centre nearline.
- A further BIS/export-control or tariff shock that interrupts Asia manufacturing or CSP shipments on a scale comparable to the $300m Huawei settlement still being paid.
