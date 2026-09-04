# Shell plc (SHELL.AS) — Research memo

_Version 1 · Updated 2026-09-04T07:38:11.098497+00:00 · Mode: initial_

## EXECUTIVE SUMMARY
Shell plc screens as a **strong buy** on the quantitative value model (15/22 models passed, composite 90%, conviction 88% over 11 weeks), anchored by a P/E of 9.9, P/B of 1.4, ~7.0% dividend yield and moderate leverage (D/E 40%). The investment case is a cash-generative integrated major returning capital aggressively—progressive dividends, buybacks and a shrinking share count—while repositioning toward LNG, Canadian Montney gas (ARC Resources) and selective upstream. The central debate is whether recent earnings momentum (notably a strong Q2 2026) reflects durable mid-cycle strength or a temporary uplift from refining, trading and geopolitical volatility that screens overstate as normalised value. Primary filing bodies lack extractable line-item financials; audit opinion and narrative 6-K disclosures partially offset that gap.

## INVESTMENT THESIS
For a value investor, Shell offers a rare convergence of **cheapness, income, GARP and balance-sheet quality** in a cyclical sector. The screen passes all five factor families—cheapness, quality, dividend, GARP and risk—with 20/20 data quality, and clears Graham Enterprising, Earnings Yield, FCF Yield, Lynch/Neff PEG, Dividend Growth, Magic Formula, Acquirer's Multiple, Dreman Contrarian, Composite Value, Earnings Quality and Financial Health. That breadth exceeds AEX/energy peers in the attached peer table and suggests the signal is not a single-ratio artefact.

Business quality supports the screen despite failing “moat” models (ROE 14.3% sits below the screen’s 18% hurdle). Shell remains a top-tier integrated major with scale in LNG, trading, chemicals and downstream. Capital discipline is evident: FY2025 capex fell to $18.9bn (Yahoo fallback) while the group returned $8.5bn in dividends and $13.9bn in buybacks. Diluted average shares fell from 6.36bn (FY2024) to 5.95bn (FY2025). Net debt of $17.1bn against $29.6bn cash leaves headroom, and the Piotroski F-Score of 5/9 reflects cyclical balance-sheet drift (leverage and margin trends) rather than distress—positive net income, positive OCF and OCF exceeding net income all pass.

The GARP and dividend passes imply the market prices mid-cycle earnings too pessimistically relative to cash-return capacity. Q1 and Q2 2026 results (Yahoo quarterly fallback) show net income of $5.7bn and $10.8bn respectively, with Q2 diluted EPS of $1.92 on revenue of $94.7bn—a step-up that aligns with Dutch press reporting of ~$10bn Q2 profit and strong refining (De Telegraaf, 30 July 2026). ARC completion ($16.5bn; yfinance, 2 September 2026) adds ~370 kboe/d and management targets 4% production CAGR through 2030 (6-K, 27 April 2026), reinforcing the per-share growth narrative behind the screen’s strong-buy rating.

## FINANCIAL REVIEW
**Primary filings — coverage and gaps**

The filings index (`euro_filings` regime via SEC 20-F/6-K) lists one annual filing (Form 20-F, filed 12 March 2026) and 37 interim 6-K entries. **Annual body gap:** the 20-F extract (`74018f3f90d5a582.txt`) contains only a table-of-contents index, not reconcilable income-statement or balance-sheet line items. **Interim body gap:** Q4 FY2025 (`9998c65631edd242.txt`), Q1 FY2026 (`1a2ddc2b6036d0f6.txt`) and Q2 FY2026 (`3f3dcb3198fe9969`, indexed 30 July 2026) reference unaudited condensed financial reports, but downloaded bodies are cover pages only—no interim P&L, cash flow or balance-sheet figures are available in `filings/bodies/`. **Partial annual primary source:** the auditor’s report extract (`6ffb979441659d4c.txt`, 6-K filed 12 March 2026) confirms directors’ going-concern basis is appropriate (assessment period to 30 June 2027), references Shell’s dividend resilience statement in Note 4, and notes climate litigation disclosure in Note 32 “Legal proceedings and other contingencies.” Numeric annual statement analysis below therefore **falls back to `financials_annual.json` (Yahoo)** unless otherwise cited from filing narrative.

**Annual trends (Yahoo fallback, USD)**

| Metric | FY2022 | FY2023 | FY2024 | FY2025 |
|--------|--------|--------|--------|--------|
| Revenue | $381.3bn | $316.6bn | $284.3bn | $266.9bn |
| Net income | $42.3bn | $19.4bn | $16.1bn | $17.8bn |
| Diluted EPS | $5.71 | $2.85 | $2.53 | $3.00 |
| Operating cash flow | $68.4bn | $54.2bn | $54.7bn | $42.9bn |
| Free cash flow | $45.8bn | $31.2bn | $35.1bn | $23.9bn |
| Capex | $22.6bn | $23.0bn | $19.6bn | $18.9bn |
| Net debt | $16.1bn | $15.5bn | $10.5bn | $17.1bn |

Revenue and operating profit have retraced materially from the 2022 commodity spike, yet FY2025 net income and EPS **recovered modestly** versus FY2024 (+11% net income; EPS $2.53 → $3.00). The concern is **FCF compression**: FY2025 FCF of $23.9bn is down 32% year-on-year and 48% from the 2022 peak, despite reduced capex. Dividends ($8.5bn) plus buybacks ($13.9bn) exceeded FY2025 FCF, pushing net debt from $10.5bn to $17.1bn—still manageable against equity of $174.4bn and cash of $29.6bn (Yahoo, FY2025).

Share count reduction remains a tangible per-share lever: diluted average shares fell from 7.41bn (FY2022) to 5.95bn (FY2025).

**Interim / quarterly (Yahoo quarterly fallback; filing bodies unavailable)**

| Period | Revenue | Net income | Diluted EPS | OCF | FCF |
|--------|---------|------------|-------------|-----|-----|
| Q1 2026 (Mar) | $69.7bn | $5.7bn | $1.00 | $6.1bn | $2.3bn |
| Q2 2026 (Jun) | $94.7bn | $10.8bn | $1.92 | $21.4bn | $17.4bn |

H1 2026 net income of ~$16.5bn and H1 diluted EPS of ~$2.92 (sum of quarters) represent a sharp acceleration versus FY2025 run-rate, driven by Q2 strength. TTM FCF per Yahoo quarterly cashflow is $31.5bn (OCF $49.1bn less capex $17.6bn), above FY2025 annual FCF—consistent with the screen’s TTM FCF input of ~$21.5bn only if the screen uses a different definition or timing; treat TTM FCF as **$31.5bn per Yahoo quarterly cache** pending reconciliation to Shell’s CFFO-based framework (management distributes 40–50% of CFFO through the cycle per ARC acquisition filing).

**Filing-sourced non-financial metrics**

From the ARC acquisition 6-K (27 April 2026): enterprise value ~$16.4bn; ARC production ~374 kboe/d; Shell targets ~1.4 mboe/d liquids through 2030; cash capex ceiling $20–22bn for 2027–28 unchanged; expected synergies ~$250m within one year of close; distributions policy 40–50% of CFFO with 4% progressive annual dividend growth.

**Balance sheet items (Yahoo fallback):** non-current pension and post-retirement obligations $7.1bn; defined benefit pension $5.1bn; long-term provisions $21.4bn—typical for a legacy major but not immaterial. Covenant detail, decommissioning schedules and litigation provisions cannot be verified from available filing bodies beyond auditor references to Note 32.

## RISKS AND RED FLAGS
**Cyclical and commodity:** Revenue is down ~30% from the FY2022 peak. Earnings remain highly sensitive to oil, gas and refining margins. News links share volatility to Middle East conflict and oil price spikes (De Telegraaf, 7 July 2026; Proactive, 2 March 2026). Screens may look attractive at a mid-cycle trough but deteriorate quickly in a downturn.

**Capital return vs FCF:** FY2025 distributions exceeded FCF, lifting net debt. The June 2026 buyback pause (6-K, 12 June 2026) for ARC-related securities-law requirements, and the $16.5bn ARC cash/stock consideration, temporarily constrain buyback pace—though management states skipped buybacks roll into remaining 2026 programmes.

**Geopolitical / operational:** Qatar LNG production shut down since early March 2026; attack on Ras Laffan/Pearl GTL facility reported 19 March 2026 (6-K)—damage assessment ongoing. Middle East exposure adds tail risk to LNG volumes and integrated gas earnings not fully captured by value screens.

**Regulatory and transition:** Auditor flagged climate-change litigation completeness (Note 32) and decommissioning/restoration provision risk under energy-transition scenarios; hypothetical IEA Net Zero impairment of $20–26bn cited in audit report (not recorded, but signals sensitivity). Shell’s 2050 net-zero target sits outside the planning period; management acknowledges material risk of non-achievement if society does not reach net zero by 2050 (standard Shell forward-looking caution in multiple 6-K filings).

**Leverage and liquidity:** Net debt rose in FY2025; current ratio 1.3 fails Graham Defensive threshold. Investment-grade rating is an explicit management aim (ARC filing), but leverage trend warrants monitoring post-ARC.

**Governance:** CEO pay controversy flagged in Dutch media (debelegger.nl, 24 June 2026). AGM held 19 May 2026 (6-K)—routine re-elections but climate resolutions remain contentious in press coverage.

**M&A integration:** ARC adds scale but integration, regulatory approval and ~$2.8bn assumed net debt/leases increase complexity; production CAGR uplift depends on Montney execution.

**Filing limitation:** Absence of extractable primary financial statement bodies means adjusted CCS earnings, segment cash flow, covenant headroom and detailed contingency quantification **cannot be verified** in this pass—despite a clean going-concern audit opinion.

RiskTags: regulatory, cyclical, governance, pension, competitive, leverage, litigation, other
RiskTags: regulatory, cyclical, governance, pension, competitive, leverage, litigation, other

## NEWS HIGHLIGHTS
Coverage over the past year is **moderately thick** on capital returns, M&A and geopolitics; thinner on granular operational metrics.

**M&A and portfolio:** Shell **completed the $16.5bn ARC Resources acquisition** (yfinance, 2–3 September 2026), adding ~370 kboe/d Montney production. Earlier agreement announced 27 April 2026. Shell took **30% stakes in BP exploration prospects** offshore Brazil and US Gulf, plus Conifer (yfinance, 3 September 2026)—expanding exploration optionality at lower capital intensity. **Tri Star Energy** US retail acquisition (320 sites; yfinance, 2 September 2026) deepens downstream footprint. Sprng Energy India renewables divestment noted earlier in cycle (July 2026 yfinance).

**Results and distributions:** Q2 2026 profit reported well above expectations with strong refining (De Telegraaf / AD.nl, 30 July 2026); interim dividend **$0.3906/share** announced for Q2 2026 (Investing.com, 30 July 2026). Ongoing LSE buyback programme with periodic suspensions for ARC (IEX.nl / De Telegraaf, 12 June 2026). Erste Group upgraded recommendation citing refining strength (Investing.com, 27 August 2026).

**Operational / geopolitical:** Qatar LNG shutdown and Pearl GTL incident (Shell 6-K, 19 March 2026; De AandeelHouder, 20 March 2026). Shell benefited from gas-trading dislocations during Iran conflict (De Telegraaf, 7 July 2026). Dragon offshore gas project tender for Q2 2027 (yfinance, 15 July 2026). Bahamas LNG terminal expansion (16 July 2026).

**Governance / audit:** Audit switch to PwC in 2027 after EY tenure (Stock Titan, 6 February 2026). CEO pay warning in Dutch press (debelegger.nl, 24 June 2026).

**Analyst / sentiment:** Mixed broker views—JPMorgan constructive (March 2026); Citi cut target to 3,200p, Neutral (July 2026 yfinance). Retail-oriented “value still reasonable after 175–194% five-year run” pieces recur (yfinance, July–September 2026).

**Noise:** Many headlines duplicate buyback notices or offer price predictions; material signal concentrates on ARC, Q2 earnings beat, Qatar disruption, and capital-return policy.

## RESEARCH VERDICT
Verdict: accumulate
Risk: medium
Confidence: 0.76
Rationale: Deep research corroborates the quantitative strong-buy case on cheap multiples, dividend yield, cash generation and capital return, but primary filing bodies lack line-item financials, cyclical/geopolitical exposure and FY2025 distribution-above-FCF dynamics prevent a full conviction upgrade.
