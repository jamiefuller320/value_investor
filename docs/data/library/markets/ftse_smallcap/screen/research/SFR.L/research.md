# Severfield plc (SFR.L) — Research memo

_Version 1 · Updated 2026-07-18T12:40:18.703230+00:00 · Mode: initial_

## EXECUTIVE SUMMARY
# Severfield plc (SFR.L) — First-Pass Research Memo

**Quantitative screen:** Buy (4/22 models, composite 71%)  
**Sources:** `screening_snapshot.json`, `financials_annual.json` (Yahoo fallback — no filing bodies available), `filings_index.json`, `news_manifest.json`

---

## EXECUTIVE SUMMARY

Severfield plc is the UK’s leading structural steelwork contractor, and the quantitative screen flags it as a buy on deep asset cheapness: price-to-book of roughly 0.8, debt-to-equity below 50%, and a reported free-cash-flow yield near 38%. The stock trades well below stated book value after a sharp earnings deterioration driven by bridge-contract losses and rising provisions, with reported return on equity now negative at −21.6%. The central debate is whether the market is over-discounting a cyclical, contract-heavy business with recoverable operating economics, or whether goodwill, working-capital build, and elevated net debt after FY2025 reflect structural impairment. Primary RNS filing bodies were not available in the source library, so this review relies on Yahoo financials and news headlines; conviction is therefore tempered.

---

## INVESTMENT THESIS

For a value investor, the case rests on **balance-sheet cheapness rather than earnings momentum**. The screen passes four models—Schloss Low P/B, FCF Yield, Composite Value, and Financial Health—with cheapness and risk as the two families clearing thresholds. At P/B ≈ 0.77 against shareholders’ equity of £183.0m (Yahoo, FY2025 balance sheet), the market appears to price Severfield below net assets; tangible book was £82.6m against total assets of £400.9m, with goodwill of £97.6m a key swing factor.

Operating quality, by contrast, is mixed. Underlying operations still generated positive operating profit of £19.0m on revenue of £450.9m in FY2025 (Yahoo), but reported net loss was £14.1m after £33.0m of unusual/special charges—consistent with press coverage of bridge-contract difficulties. Normalised net income (Yahoo adjustment) was approximately £12.5m, suggesting the core fabricator franchise is not broken, but earnings power has clearly stepped down from FY2023 (£21.6m net profit on £491.8m revenue).

The screen’s FCF Yield pass (FCF cited at £43.0m, yield 38.3%) sits awkwardly against Yahoo’s FY2025 free cash flow of **−£8.4m** and operating cash flow of **−£0.5m**, following strong FCF in FY2024 (£33.8m) and FY2023 (£43.8m). Value investors should treat the yield metric as backward-looking or stale relative to the latest year’s cash burn, not as confirmation of current cash generation. The persistent buy signal (five weeks, stable trend) nevertheless indicates the market has not rerated the name despite recent results—creating a classic “cigar butt” setup if provisions peak and working capital normalises.

Business quality anchors include market leadership in UK structural steel, exposure to infrastructure and commercial construction (a thematic tailwind cited in sector press), and management alignment signals: the CEO increased his market purchase in July 2026, and the company extended its share buyback programme. These do not offset the earnings decline but support the case that insiders see mispricing.

---

## FINANCIAL REVIEW

**Source limitation:** `filings_index.json` lists 21 UK RNS entries under regime `uk_rns`, but **zero are classified as annual or interim**, and **no filing body extracts** exist under `filings/bodies/`. Headlines reference “Results for the year ended 28 March 2026” (June 2026) and director dealings, but numeric detail cannot be verified from primary filings. All figures below are from **`financials_annual.json` (Yahoo)**, stated explicitly as fallback.

### Income statement trend (March year-end)

| Metric | FY2022 | FY2023 | FY2024 | FY2025 |
|--------|--------|--------|--------|--------|
| Revenue (£m) | 403.6 | 491.8 | 463.5 | 450.9 |
| Operating income (£m) | 21.7 | 29.7 | 32.3 | 19.0 |
| Reported net income (£m) | 15.6 | 21.6 | 15.9 | **−14.1** |
| Diluted EPS (p) | — | 6.9 | 5.1 | **−4.7** |
| Normalised net income (£m) | — | 23.2 | 21.5 | 12.5 |

Revenue has fallen for two consecutive years (−8.3% from FY2023 peak). Operating margin compressed materially in FY2025. The swing to reported loss reflects £33.0m of unusual items in FY2025 (Yahoo: special charges including £34.0m “other special charges” partly offset by restructuring credits), aligning with news that Severfield “sinks to a loss on bridge challenges” (Investors’ Chronicle, 24 July 2025).

Partial FY2026 data in Yahoo shows diluted EPS of **−12.0p**, worse than FY2025’s −4.7p, indicating continued pressure; no full income statement is available for FY2026 in the source file.

### Balance sheet (FY2025 vs FY2024, Yahoo)

- **Total assets:** £400.9m (from £378.4m)
- **Shareholders’ equity:** £183.0m (from £220.8m) — **−17%**
- **Net debt:** £43.3m (from £9.6m) — leverage increased sharply
- **Total debt:** £79.3m (from £42.5m), including long-term debt issuance of £45.0m in FY2025
- **Goodwill:** £97.6m; **tangible book:** £82.6m
- **Current provisions:** £30.5m (from £11.8m) — likely contract-related; material red flag
- **Other receivables (current):** £89.5m (from £50.6m) — large working-capital item warranting filing-level scrutiny (unavailable)
- **Pension deficit (non-current):** £6.9m (from £11.5m) — improved but still present

Debt-to-equity on the screen (48%) is consistent with gross debt relative to diminished equity; net debt rose as cash remained modest (£15.5m) while debt funded operations and shareholder returns.

### Cash flow (Yahoo)

| Metric | FY2023 | FY2024 | FY2025 |
|--------|--------|--------|--------|
| Operating cash flow (£m) | 50.3 | 45.1 | **−0.5** |
| Capital expenditure (£m) | 6.5 | 11.3 | 7.8 |
| Free cash flow (£m) | 43.8 | 33.8 | **−8.4** |
| Dividends paid (£m) | 9.9 | 10.7 | 11.2 |
| Share buybacks (£m) | — | 3.1 | 8.6 |

FY2025 working-capital absorption was severe: receivables change **−£30.6m** (Yahoo). The company continued dividends and buybacks despite negative FCF—a governance/capital-allocation point that filing covenants and going-concern language would normally clarify; **those disclosures are absent from the source library**.

### Interim / latest results gap

The filings index contains a headline for **“Results for the year ended 28 March 2026”** (published 28 March 2026 / referenced June 2026 in news), plus routine PDMR, holdings, and buyback notices. Without body text, interim/H1 detail cannot be analysed. News (Investing.com, 31 March 2026) references an “in-line” year-end and FY2027 outlook, and Investors’ Chronicle (23 June 2026) reports a **strategy change as profits fall**—suggesting management is pivoting after a difficult year, but quantitative confirmation is unavailable.

---

## RISKS AND RED FLAGS

**Earnings and contract risk.** FY2025 reported loss and elevated provisions (£30.5m current) point to problem contracts—bridge work specifically in press coverage. Until provisions stop rising, book value is at risk of further write-downs.

**Goodwill and intangibles.** Goodwill of £97.6m exceeds tangible book (£82.6m). A further impairment would directly erode the asset backing that underpins the P/B-based buy case.

**Cash flow and capital allocation.** Negative FY2025 FCF alongside dividend growth and buybacks raises questions about sustainability; without filing extracts, covenant headroom and going-concern assessments cannot be verified.

**Leverage.** Net debt more than quadrupled to £43.3m; total debt £79.3m against reduced equity. D/E passes the screen threshold but direction of travel is unfavourable.

**Working capital.** Other receivables of £89.5m are unusually large relative to revenue (~20%); recovery or write-off risk is material.

**Pension.** £6.9m deficit is manageable in isolation but adds to fixed obligations in a cyclical sector.

**Cyclical / macro exposure.** UK construction and infrastructure demand drives order books; macro markers (FTSE 100 ~10,600, GBP/USD ~1.35) provide background only and do not alter the screen signal.

**Governance / disclosure gap.** No annual report body text means auditors’ emphasis of matter, contingent liabilities, and related-party transactions cannot be reviewed— a significant research gap for a contract-accounting business.

**Screen metric inconsistency.** Reported ROE of −21.6% directly conflicts with a quality earnings narrative; the FCF Yield pass appears inconsistent with FY2025 Yahoo FCF (−£8.4m vs screen FCF £43.0m), suggesting the screen may be using a lagged or alternate FCF definition.

---

## NEWS HIGHLIGHTS

**Material Severfield-specific coverage (past year):**

- **“Severfield changes strategy as profits fall”** — Investors’ Chronicle, 23 June 2026: strategy pivot following profit decline; most substantive operational headline in the manifest.
- **“REG - Severfield PLC - Results for the year ended 28 March 2026”** — TradingView, 22 June 2026: full-year results announcement (body not in library).
- **“Severfield shares outlook for fiscal 2027 after in-line year-end results”** — Investing.com, 31 March 2026: management outlook commentary.
- **“Severfield sinks to a loss on bridge challenges”** — Investors’ Chronicle, 24 July 2025: explains FY2025 loss drivers.
- **“Severfield CEO Increases Stake With Market Share Purchase”** — TipRanks, 14 July 2026: insider buying signal.
- **“Severfield Ties New Executive Share Awards to EPS and TSR Targets”** — TipRanks, 1 July 2026: remuneration aligned to earnings recovery and total shareholder return.
- **“Directorate Change”** — Investegate, 8 November 2024: board change (detail unavailable).
- **“3 UK Construction Stocks To Watch As Local Investment Spending Picks Up”** — simplywall.st, 11 July 2026: sector thematic; Severfield may be referenced among UK construction names.
- Yahoo Finance (Dec 2025): cited ~29% discount to estimated fair value of £0.41 vs ~£0.29 price.
- Filings index (July 2026): **“Transaction in own shares and Buy Back Extension”** — capital return programme ongoing.

**Coverage quality flag:** A substantial share of manifest entries concerns **Sandfire Resources (ASX:SFR)** or **Altice’s French telecom SFR**, not Severfield plc (LSE:SFR). Severfield-specific news is **thin** beyond results-related headlines and insider/dealing notices; deep operational insight requires annual report access not present in sources.

---

## RESEARCH VERDICT

Verdict: accumulate  
Risk: medium  
Confidence: 0.62  
Rationale: Deep research confirms the screen’s asset cheapness and balance-sheet headroom, but recent losses, provision build, negative FY2025 cash flow, and absent primary filings weaken confidence that earnings will normalise quickly enough to justify a stronger conviction overlay.

## INVESTMENT THESIS


## FINANCIAL REVIEW


## RISKS AND RED FLAGS


## NEWS HIGHLIGHTS
