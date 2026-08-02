# FirstGroup plc (FGP.L) — Research memo

_Version 2 · Updated 2026-08-02T13:44:58.003151+00:00 · Mode: gap_fill_

## EXECUTIVE SUMMARY
FirstGroup is a UK-listed bus and rail operator undergoing a deliberate portfolio shift: First Bus (~78% of adjusted revenue) is scaling margins and electrification, while First Rail (~22%) is pivoting from DfT-contracted TOCs toward open access, TfL concessions, and ancillary services. The quantitative screen flags a Strong Buy on cheapness (P/E 9.2, earnings yield 10.8%, FCF yield 31%), quality (Piotroski F-Score 8/9, ROE 16.7%), dividend growth, and improving leverage trends, despite failing deep-value and balance-sheet screens (current ratio 0.73, debt/equity 161%).

Primary filings show a multi-year earnings upgrade — adjusted EPS rose from 11.6p (FY2023) to 16.7p (FY2024) to 19.4p (FY2025) — funded by operational improvement and aggressive buybacks, with adjusted net debt still modest at £86.9m at FY2025 year-end. The central debate is whether UK transport policy transition (rail nationalisation via Great British Railways, bus franchising, fare-cap politics) erodes the franchise value the market prices in, or whether FirstGroup’s diversification (London Overground, RATP London, open-access rail) sustains cash returns at current multiples.

---

## INVESTMENT THESIS
**Why the screen works here.** FirstGroup passes five factor families — cheapness, quality, dividend, GARP, and risk — with full data coverage (20/20 metrics). The name offers a rare combination of single-digit P/E, near-3.9% yield, and a Piotroski score of 8/9, with five of nine components tied to improving returns and declining leverage. FCF yield of 31% (screen input: £303m FCF) reflects cash-generative bus operations and low revenue-risk rail management fees, not a distressed liquidation profile.

**Business quality supports the signal.** FY2025 adjusted operating profit reached £222.8m on adjusted revenue of £1,370.0m (16.3% margin), up from £204.3m / £1,279.6m in FY2024. Management has executed against four strategic pillars — operational delivery, modal shift, sustainability, and portfolio diversification — with tangible outcomes: First Bus hit a 10% adjusted operating margin target (ex-London) in H2 FY2025; First Rail open-access operators carried 2.9m journeys with strong NPS; adjacent services revenue grew 23% to £270.8m. The £90m RATP London acquisition re-enters the capital’s bus market with an anticipated £300–350m annual revenue run-rate over five years.

**Capital allocation amplifies per-share value.** FY2025 returned c.£92m via buybacks (54.8m shares repurchased), lifting adjusted EPS to 19.4p despite only mid-single-digit profit growth. The progressive dividend rose to 6.5p (FY2024: 5.5p). Chairman’s statement describes the business as “cash generative” with “balance sheet capacity” to fund decarbonisation, growth, and shareholder returns — consistent with the screen’s FCF and dividend-growth passes.

**Where the screen overstates comfort.** Failures on Graham Defensive/Enterprising, Buffett Quality, Economic Moat, and Financial Health all cite leverage, thin margins, and weak liquidity — structural features of a lease-heavy transport operator that the cheapness models partially offset but do not eliminate.

---

## FINANCIAL REVIEW
**Source hierarchy.** Walked `gap_fill_source_map.json` evidence ladder. Primary: Companies House group accounts (FY2024, FY2025 annual reports). Secondary: Yahoo `financials_annual.json` for cash-flow bridges. News/alternate news for unverified FY2026/H1 commentary only.

**Adjusted earnings trend (filings — reliable).** FY2023 adjusted EPS 10.6p → FY2024 16.7p → FY2025 19.4p; adjusted operating profit £161.0m → £204.3m → £222.8m; adjusted revenue £1,279.6m → £1,370.0m. FY2025 highlights: First Bus adj. op. profit £96.0m; First Rail £148.8m; dividend 6.5p; c.£92m buybacks. Adjusted net debt moved from £64.1m net cash (FY2024) to £86.9m net debt (FY2025) — modest.

**Statutory vs adjusted divergence (explains screen tension).** FY2024 statutory loss before tax £(24.4)m included £146.9m LGPS pension termination charges (non-cash). FY2025 statutory EPS 21.3p exceeded adjusted 19.4p due to buyback benefit and absence of pension charge. Yahoo FY2026 statutory net income £118.3m (−7% YoY) drives the screen’s negative earnings growth; this is **not** mirrored in the latest filing-backed adjusted series.

**Cash flow and FCF yield (Yahoo fallback — latest period).**

| Metric | FY2026 (Yahoo) | FY2025 (Yahoo) | FY2025 filing context |
|--------|---------------|---------------|----------------------|
| Operating cash flow | £615.6m | £754.2m | Filing cites “strong cash conversion” |
| Free cash flow | £362.6m | £597.8m | Screen uses £302.8m → ~31% yield |
| Cash dividends paid | £38.9m | £34.2m | Policy: ~3× adjusted profit cover |
| Capex | £253.0m | £156.4m | Includes electrification, RATP integration |
| Net WC change | +£1.9m | +£46.8m | FY2026 not WC-driven |
| IFRS 16 lease liabilities | £850m (Yahoo) | £1,204m (filing FY2025) | Excluded from adjusted net debt |

FCF compression reflects investment cycle (capex +£97m; acquisitions £35m), not withdrawal of UK operational cash generation. Restricted cash £262m (Yahoo FY2026) relates to ring-fenced rail accounts — relevant for liquidity analysis but separate from parent adjusted net debt.

**Interim gaps (still open).** November 2025 Companies House interim is **parent-company only** (profit after tax £98.9m; dividend income £68.4m from subsidiaries) — not group trading. No consolidated H1 FY2026 or FY2026 annual body in `filings_index.json`. News (18 Jun 2026, `alternate_news.json`): FY2026 adjusted revenue +25%, profitability “flat,” dividend 7.2p, £100m buyback — **unaudited**; cannot merge with filing figures.

**Remaining gaps.** Financial Review (p. 26), consolidated cash-flow notes, viability/going-concern (p. 69), and covenant language are listed in FY2025 contents but **not present** in body extracts. Adjusted FCF definition and multi-year FCF bridge require IR presentation or full PDF ingest.

---

## RISKS AND RED FLAGS
**Evident from filings and Yahoo (high confidence).**

- **Lease-adjusted leverage.** IFRS 16 liabilities £1.2bn+; D/E 161%, current ratio 0.73 — screen failures are structural. Mitigant: adjusted net debt £86.9m (FY2025); Piotroski “leverage declining” pass; statutory net debt improved £1,269m → £975m (FY2024–FY2025).
- **Earnings growth headfake.** Statutory/TTM earnings declining (−5.9%) while adjusted EPS grew through FY2025; dividend screen passes on adjusted profit and FCF, not headline earnings momentum.
- **FCF cyclicality.** FCF yield 31% is elevated but FY2026 FCF fell 39% YoY on investment (capex, RATP). Receivables releases (+£188m) add timing sensitivity; normalized yield is lower though still likely double-digit at current prices.
- **UK policy transition.** FY2025 filing: GBR nationalisation, Railways Bill, bus franchising — earnings base diversifying (London Overground, open access) but contract economics uncertain.
- **Pension largely de-risked.** LGPS termination FY2024 (~£1bn gross liabilities removed/insured, no cash cost); residual DB balances small (Yahoo: £22m).

**Evident from news, unverified in filings (medium confidence).**

- H1 FY2026 share fall on “period of transition” (Proactive Investors, AskTraders, 18 Nov 2025) despite reported beats.
- “FirstGroup hit by cash outflow and rising debt” (Investors’ Chronicle, 18 Nov 2025) — **quantitative H1 cash/debt figures not in local sources.**

**Still open — alternate source needed.**

| Open item | Would unlock |
|-----------|-------------|
| FY2025 viability/going-concern + covenant note | Whether D/E 161% threatens dividend or buybacks under stress |
| H1 FY2026 consolidated interim RNS | Validates or refutes H1 cash-outflow narrative |
| FY2026 annual report / adjusted FCF table | Normalized FCF yield and FY2026 adjusted EPS trend |
| Company IR results presentation PDF | WC bridge, segment FCF, management adjusted cash metrics |

**Dividend + leverage interaction (gap-fill view).** Dividend appears sustainable: ~9× FCF cover (Yahoo FY2026), ~3× adjusted EPS cover (FY2025 filing policy), parent interim shows upstream dividend capacity. Risk is not immediate dividend cut but **competing capital calls** (buybacks, electrification capex, Overground guarantees £30m + £80m) if FCF normalizes lower while statutory leverage metrics remain elevated.

---

## NEWS HIGHLIGHTS
Coverage over the past year is **moderately thick** on capital returns and contract wins, thinner on deep operational analysis. Material items:

| Date | Headline | Significance |
|------|----------|-------------|
| 10 Dec 2025 | “FirstGroup wins £3bn contract to run London Overground” (proactiveinvestors.co.uk); “FirstGroup wins $4 billion London Overground rail contract” (Reuters) | Major TfL concession from May 2026; ~£3bn over eight years plus two-year option |
| 18 Jun 2026 | “FirstGroup boosted as it launches new buyback, confirms revenue growth” (proactiveinvestors.co.uk); “FirstGroup launches £100 million share buyback” (Globe and Mail) | FY2026 results day: revenue +25%, dividend to 7.2p, £100m buyback |
| 18 Nov 2025 | “FirstGroup falls 10% as results beat forecasts but 'period of transition' begins” (proactiveinvestors.co.uk) | H1 FY2026: market focused on transition risk despite beats |
| 27 Jul 2026 | “FirstGroup plc Completes Share Buyback, Repurchasing 2.77 Million Shares at 179.85p” (Kalkine Media) | Active capital return at ~180p |
| 30 Jul 2026 | “FirstGroup Shareholders Back Board, Dividend and Capital Actions at 2026 AGM” (TipRanks) | Governance endorsement of capital policy |
| 12 May 2026 | “FirstGroup can grow despite rail nationalisation, says broker” (proactiveinvestors.co.uk) | Sell-side framing of GBR as manageable |
| 22 Jul 2026 | “3 UK Transport Stocks Linked To The £2 Bus Fare Cap” (simplywall.st) | Policy sensitivity on bus economics post-fare-cap changes |

FY2025 full-year earnings call summary (Yahoo, 20 June 2026) cites 25% revenue growth and £100m buyback — consistent with Investegate commentary but **not independently audited in available filing bodies**.

Promotional “40–51% upside” pieces from DirectorsTalk Interviews appear frequently; treat as low signal weight.

---

## RESEARCH VERDICT
Verdict: accumulate
Risk: medium
Confidence: 0.74
Rationale: Gap-fill clarifies that negative earnings growth is a statutory/TTM artefact against rising adjusted EPS and strong FCF dividend cover, partially validating the Strong Buy cheapness signal, but missing consolidated interim/FY2026 filings and covenant extracts keep balance-sheet diligence incomplete before full sizing.

## Weekly updates

### 2026-08-02T13:44:58.003151+00:00
**Q: Negative earnings growth (−5.9%) despite dividend screen pass raises sustainability risk if the FCF yield (31%) reflects non-recurring items or lease accounting.**

Status: partially_resolved

Evidence: The screen’s −5.9% `earnings_growth_pct` aligns with Yahoo statutory net income falling from £127.5m (FY2025) to £118.3m (FY2026) — a real latest-period decline, not a filing artefact. This diverges from filing-backed **adjusted** EPS, which rose 16.7p → 19.4p (FY2024–FY2025) per `ch_SC157176_MzQ3MzQwMTk5MmFkaXF6a2N4.txt`. FY2023 filing states dividend policy targets payout “around three times covered by Group adjusted attributable profit”; FY2025 dividend 6.5p vs adjusted EPS 19.4p is ~3.0× cover. Piotroski confirms OCF (£615.6m) exceeds net income (£118.3m). The earnings-decline flag reflects statutory/TTM softness, not adjusted earnings erosion; FY2026 adjusted EPS is unavailable in filing bodies.

SourcesTried: filings_bodies, filings_index, yahoo_financials, news_manifest, alternate_news, screening_snapshot

NextSources: FirstGroup FY2026 Annual Report PDF (adjusted EPS bridge); company IR / results presentation PDF (`gap_fill_source_map.json` → `company_ir_presentation`) for adjusted vs statutory reconciliation

---

**Q: Does the 31% FCF yield reflect normalized UK/US bus-rail operations, or lease-adjusted, non-recurring working-capital releases—and can the dividend survive with D/E at 161%?**

Status: partially_resolved

Evidence: Operations are UK/Ireland bus and rail only — North America exited per FY2023–FY2025 filings; no current US revenue base. Yahoo FY2026 FCF £362.6m (screen input £302.8m, slightly more conservative) on OCF £615.6m less capex £253m. FCF fell from £597.8m (FY2025) mainly via higher capex (£253m vs £156m) and £35.3m acquisitions (RATP London), not lease reclassification — IFRS 16 lease liabilities £1,203.6m sit outside **adjusted** net debt (£86.9m, FY2025 filing). FY2026 net working-capital change was only +£1.9m; receivables contributed +£188m to OCF (Yahoo), so FCF is not predominantly a one-off WC windfall, though receivables timing adds cyclicality. Cash dividends paid £38.9m vs FCF £362.6m (~9× cover). D/E 161% includes ~£850m capital-lease obligations (Yahoo FY2026); bank debt is modest (£129.5m long-term). Dividend survivability looks adequate on cash metrics; covenant headroom and H1 FY2026 consolidated cash flow remain unverified.

SourcesTried: filings_bodies, filings_index, yahoo_financials, alternate_news, screening_snapshot, macro_context

NextSources: FY2026 consolidated cash-flow statement and note on adjusted FCF (annual report PDF); H1 FY2026 RNS / interim results announcement for the Investors’ Chronicle “cash outflow and rising debt” flag (18 Nov 2025, `alternate_news.json`)

---

**Q: (FirstGroup plc, Industrials) passes 11/22 models with 90% composite and all five factor families, but fails Graham Enterprising, Financial Health, Buffett Quality, and Economic Moat on leverage/liquidity. Verdict: watchlist — exceptional headline value, but balance-sheet diligence warranted before sizing.**

Status: partially_resolved

Evidence: `screening_snapshot.json` confirms Strong Buy: 11/22 models, composite 90.5%, all five families, P/E 9.2, FCF yield 31%, Piotroski 8/9 (leverage declining ✓, current ratio improving ✗). Failures are structural: D/E 161%, current ratio 0.73, thin margins — consistent with lease-heavy UK transport, not a data error. Gap-fill shows adjusted net debt £86.9m (FY2025 filing) vs statutory £974.8m — leverage risk is real on GAAP measures but manageable on management’s adjusted basis. FY2025 chairman describes “cash generative” operations with “balance sheet capacity.” Sector concentration with MEGP.L is a portfolio construction issue, not resolved by issuer filings.

SourcesTried: filings_bodies, filings_index, yahoo_financials, screening_snapshot, macro_context

NextSources: FY2025 viability/going-concern and covenant note (pages 58–69 listed in annual report contents but absent from body extract); credit-rating or bond prospectus summary if available

---

**Q: MEGP.L comparison — Industrials cluster peer with cleaner balance sheet (D/E 28%) but weaker FCF conversion. Portfolio-level context for FGP.L sizing.**

Status: partially_resolved

Evidence: MEGP metrics are out of scope for FGP source files; comparison is valid only at portfolio level. FGP offers superior FCF yield (31% vs MEGP ~3.7%) and Piotroski (8/9 vs 6/9) but carries materially higher lease-adjusted leverage (D/E 161% vs ~28%). No FGP-specific source resolves relative sizing; both names can coexist with sector caps and position limits.

SourcesTried: screening_snapshot, macro_context

NextSources: none for FGP issuer research; portfolio-level sector exposure limits (ops/scoring overlay)

---
