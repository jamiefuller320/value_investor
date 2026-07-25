# Yancoal Australia Ltd (YAL.AX) — Research memo

_Version 1 · Updated 2026-07-25T13:06:24.370197+00:00 · Mode: initial_

## EXECUTIVE SUMMARY
Yancoal Australia is a pure-play ASX coal producer that the quantitative screen rates as a buy on cheapness (P/B 0.79), dividend yield (3.4%), GARP, and balance-sheet metrics, with eight of 22 models passing and a 62% composite score. The value case rests on net-cash positioning (~A$2.0bn on Yahoo FY2025 data), tangible book backing, and record operational output through a severe earnings downcycle—FY2025 net income fell to A$440m from A$3.6bn at the 2022 peak. The central debate is whether trough-cycle economics and a US$2.4bn Kestrel acquisition (shifting mix toward metallurgical coal) represent a cyclical entry point, or a structural reset with dividend and capital-allocation risk as management prioritises M&A over payouts. Primary ASX filing bodies remain unavailable despite annual and interim announcements being indexed, limiting verification of rehabilitation provisions, covenants, and contingency disclosures.

---

## INVESTMENT THESIS
The screen flags YAL across all four factor families—cheapness, dividend, GARP, and risk—with persistent signal stability (four weeks, conviction 47%). Passed models include Schloss Low P/B, Deep Value, FCF Yield, Neff PEGY, Dividend Growth, Magic Formula, Acquirer's Multiple, and Financial Health. Headline metrics: P/E 16.3, P/B 0.79, yield 3.4%, ROE 4.8%, D/E ~1%, and FCF ~A$543m (screen) / A$506m (Yahoo FY2025).

For a value investor, the hook is asset-backed cheapness at a commodity trough: the stock trades below tangible book (~A$8.9bn per Yahoo) while holding minimal leverage (total debt A$84m against equity of A$9.0bn). FY2025 free cash flow remained positive (A$506m) despite revenue falling 46% from the FY2022 peak (A$10.5bn → A$5.7bn). News coverage cites record ROM production of 67m tonnes in FY2025 and a Q2 FY2026 production beat with guidance reaffirmed (Jul 2026), suggesting operational execution has held up even as margins compressed. The risk-family pass aligns with net-cash balance-sheet strength; the cheapness and FCF-yield passes suggest the market may be pricing permanent impairment rather than normal cyclicality—a classic deep-value setup if coal prices stabilise or Kestrel improves the met-coal mix. Weak ROE (4.8%) and sub-50% screen conviction temper enthusiasm on business quality.

---

## FINANCIAL REVIEW
**Source limitation:** `filings_index.json` now catalogues seven ASX announcements (regime: `asx_announcements`)—one annual report (20 Feb 2025), one half-year report (19 Aug 2025), and five other items—but **zero filing body extracts** are available (`filings/bodies/` empty; refetch attempted 7/7, fetched 0). Interim figures cannot be cited from primary sources. All quantitative analysis below falls back to `financials_annual.json` (Yahoo Finance). Yahoo `quarterly_income` is also empty.

**Income statement — cyclical contraction (Yahoo fallback, A$m):**

| Metric | FY2022 | FY2023 | FY2024 | FY2025 |
|--------|--------|--------|--------|--------|
| Revenue | 10,517 | 7,558 | 6,766 | 5,728 |
| Operating income | 6,237 | 3,104 | 2,129 | 1,035 |
| EBITDA | 5,973 | 3,507 | 2,470 | 1,436 |
| Net income | 3,586 | 1,819 | 1,216 | 440 |
| Diluted EPS (A$) | 2.70 | 1.37 | 0.92 | 0.33 |

Revenue has fallen 46% from peak to FY2025; net income is down 88%. FY2025 pretax income was A$623m (tax provision A$183m). Operating income declined faster than revenue, consistent with lower realised coal prices and cost inflation referenced in FY2025 earnings news coverage. Simplywall.st (27 Feb 2026) flagged net margin compression toward 7.3%, challenging the "cash cow" narrative.

**Balance sheet — defensive but provisions opaque (Yahoo fallback, FY2025):**

- Total assets A$12,205m; stockholders' equity A$9,031m; tangible book value A$8,900m
- Cash and equivalents A$2,127m; total debt A$84m → **net cash ~A$2,043m**
- Working capital A$1,828m
- Long-term provisions A$1,294m (likely mine rehabilitation—magnitude and assumptions not verifiable without annual report notes)
- Employee/post-retirement benefits: A$114m non-current plus A$15m current

Equity has been broadly stable (A$8.0bn FY2022 → A$9.0bn FY2025) despite earnings decline, reflecting upcycle retained earnings offset by dividends and FX.

**Cash flow and capital returns (Yahoo fallback):**

| Metric | FY2022 | FY2023 | FY2024 | FY2025 |
|--------|--------|--------|--------|--------|
| Operating cash flow | 6,528 | 1,261 | 2,133 | 1,257 |
| CapEx | (550) | (622) | (705) | (751) |
| Free cash flow | 5,978 | 639 | 1,428 | 506 |
| Dividends paid | (1,626) | (1,413) | (429) | (769) |

FY2025 dividends (A$769m) exceeded both net income (A$440m) and FCF (A$506m)—a payout sustainability concern at trough earnings. CapEx has risen steadily (A$550m → A$751m), consistent with sustaining record production levels.

**Interim gap:** A half-year report is indexed (19 Aug 2025) but no body extract or Yahoo quarterly data is available; H1 FY2026 interim figures cannot be reported from primary or secondary sources in this library.

**Missing data gaps:** AISC/unit costs, reserve life, rehabilitation bonding, debt covenant terms, related-party transactions, going-concern language, and contingent liabilities cannot be assessed without downloadable filing bodies.

---

## RISKS AND RED FLAGS
**Cyclical and commodity risk:** Earnings are highly levered to global coal prices. The four-year revenue and EBITDA trajectory shows severe cyclicality; screens capture cheapness at a trough but cannot forecast price recovery. Thermal coal faces long-term demand uncertainty; the Kestrel pivot toward metallurgical coal mitigates but does not eliminate structural decline risk.

**Dividend and capital allocation:** FY2025 dividends exceeded net income and FCF (Yahoo). Market Index coverage (20 Aug 2025) described a "dividend drought" as the company hoards cash for M&A. Without filing disclosure, payout policy intent is unclear. The US$2.4bn Kestrel acquisition would consume substantially all FY2025 cash (A$2,127m) if balance-sheet funded, materially altering the net-cash profile underpinning the screen's risk pass.

**Rehabilitation and provisions:** Long-term provisions of A$1,294m (Yahoo) are typical for Australian coal miners but cannot be verified without annual report notes—discount rates, bonding requirements, and regulatory changes remain unassessed.

**M&A execution:** Kestrel is transformative relative to market capitalisation. Integration, funding structure, and returns on invested capital are unverified without transaction documents or filing extracts. The share price fell on announcement (Apr 2026 coverage).

**Governance:** No related-party or governance disclosures in the source set. Parent ownership structure (Yankuang Energy Group) is not assessable from available filings.

**Regulatory and ESG:** Australian coal mining faces environmental regulation, rehabilitation bonding, and export scrutiny. No specific enforcement actions in the news manifest, though Jul 2026 coverage references rising ESG scrutiny.

**Filing verification gap:** Going-concern statements, covenant compliance, and contingent liability language cannot be reviewed—seven announcements indexed, zero bodies retrieved.

**Screen limitations:** ROE 4.8% is weak; timing signal insufficient. Conviction remains sub-50% despite signal persistence.

---

## NEWS HIGHLIGHTS
Coverage over the past year is voluminous but **thin on primary corporate disclosure**—dominated by syndicated price-action articles (Kalkine, simplywall.st) rather than ASX announcement text.

**Material items:**

- **22 Jul 2026:** *"Why Yancoal Australia (ASX:YAL) Is Up 11.3% After Strong Q2 Production Beat And Guidance Reaffirmation"* (simplywall.st) — operational momentum signal.
- **20–21 Jul 2026:** *"Yancoal Australia (ASX: YAL) Climbs as Record Quarterly Output Lifts Market Attention"* (Kalkine); *"Looks Fully Valued After Stronger Q2 Coal Volumes"* (simplywall.st, webull.com) — mixed valuation reaction to production strength.
- **14–16 Apr 2026:** *"Yancoal signs $2.4bn deal for 80% stake in Kestrel Coal Mine"* (Yahoo Finance, Motley Fool, World Coal) — binding SPA for Kestrel Coal Group (Bowen Basin underground met coal) from EMR Capital and Adaro Capital; trading suspension noted (14 Apr, Kalkine).
- **26 Feb–6 Mar 2026:** FY2025 results — *"Full Year 2025 Earnings Call Highlights: Record Production Amid..."* (26 Feb, Yahoo) cites record output but revenue decline and inflationary pressures; *"Achieves Record Coal Production... 67 million tons ROM"* (6 Mar, Yahoo).
- **27 Feb 2026:** *"Margin Drop To 7.3% Challenges Cash Cow Narrative"* (simplywall.st).
- **20 Aug 2025:** *"Yancoal's dividend drought continues as company hoards cash for M&A"* (Market Index).
- **28 May 2026:** *"YAL:ASX Announcement - Results of Meeting"* (Market Index) — AGM outcome; no detail in manifest.

**Notable absences:** No management changes, regulatory enforcement, or divestiture news. Aug 2024 Market Index piece on dividend lessons (Yancoal/Deterra) is contextual only. Broader ASX dividend round-ups (Aug 2025, Yahoo) mention YAL peripherally.

---

## RESEARCH VERDICT
Verdict: accumulate
Risk: medium
Confidence: 0.60
Rationale: Deep research partially confirms the screen's cheapness and net-cash case and recent production momentum, but remains neutral on earnings quality, dividend sustainability, and unverified provision/M&A disclosures given zero downloadable filing bodies.
