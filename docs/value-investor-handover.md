---
cursor:
  subagentId: "bc-896389f2-595c-57e8-8195-d3e944eb0748"
---

# Data-gap handover

Maintainer note for `jamiefuller320/value_investor`. This file only records gaps already written in:

- `docs/value-investor-batch-1.md` (global roster ranks 1–10, none of them on the live FTSE 350 screen)
- `docs/ftse350-batch-1.md` (FTSE ranks 1–10)
- `docs/ftse350-batch-2.md` (FTSE ranks 11–20)
- `docs/ftse350-batch-3.md` (FTSE ranks 21–30)
- `docs/ftse350-batch-4.md` (FTSE ranks 31–40)
- `docs/ftse350-batch-5.md` (FTSE ranks 41–50)
- `docs/ftse350-batch-6.md` (FTSE ranks 51–60)
- `docs/ftse350-batch-7.md` (FTSE ranks 61–70)
- `docs/ftse350-batch-9.md` (FTSE ranks 81–90)
- `docs/ftse350-batch-10.md` (FTSE ranks 91–100)
- `docs/ftse350-batch-11.md` (FTSE ranks 101–110)
- `docs/ftse350-batch-12.md` (FTSE ranks 111–120)
- `docs/ftse350-batch-13.md` (FTSE ranks 121–130)

Those notes are the source. Do not treat this handover as a new pass over the filings. Every figure below is taken from them. Where those notes do not give a count, this file does not invent one.

## 1. Statement files do not label their currency

**What is wrong.** `financials_annual.json` has no currency field. A London price in pounds divided by an unlabeled EPS, equity, or dividend is not a multiple. Memos sometimes name `$`, `£`, `€`, or `US$`, and the screen free-cash-flow object can still say `GBP` on the same statement.

**Where.**

- Every FTSE statement cited in the two FTSE notes. The notes say the file itself does not label currency.
- `SHEL.L`: memo uses `$`. Pound price £37.935 over diluted EPS 3.0 is 12.6; the same EPS at the repo GBPUSD rate of 1.3317 is 16.8. Screen P/E is 11.2. `SHELL.AS` trailing P/E is 11.95. None of those is 11.2.
- `FRES.L`: the memo’s financial-review table labels total revenue US$4,561.2m, equal to the statement revenue 4,561,231,000. The screen still labels the matching free-cash-flow figure GBP. Pound P/E is 14.7; the dollar reading is 19.5; the screen P/E is 11.9.
- `EDV.L`: the memo calls filing free cash flow $1.13bn and screen TTM $1.76bn. The screen object labels the canonical figure GBP. Pound P/E is 15.1; the dollar reading is 20.1; the screen P/E is 16.3.
- `SN.L`: the memo uses `$`. The screen labels the matching 852 million free-cash-flow figure GBP. A dollar reading of the dividend and the book sits beside the screen yield and P/B. Neither a pound nor a dollar reading of EPS hits the screen P/E of 18.6.
- `IMB.L`: the memo uses `£`, and the statement still has no currency field. A pound reading misses the screen (P/E 10.7 vs 12.5, yield 7.27% vs 6.3%, P/B 4.44 vs 5.2). Applying the repo EURUSD 1.124 and GBPUSD 1.3317 rates lands beside the screen (P/E 12.7, yield 6.14%, P/B 5.26) and is not equal to it. Net income over equity is 42.9% either way; the screen ROE is 37.2%.
- `ULVR.L` / `UNA.AS`: the statement has no currency field and the memo does not name one. Pound P/E is 10.8; an euro conversion is 12.8 beside the screen P/E of 12.7; `UNA.AS` trailing P/E is 13.98.
- `TSM`: stored revenue 3,809,054,300,000 matches 2025 New Taiwan dollar sales, not US dollars, and is stored on the same row as a $422.25 ADR price and a $2.19 trillion cap. Stored net income, cash, and enterprise value sit on the NT$ scale. Stored price-to-book 65.88 is the dollar price divided by stored book value 6.41, which is not the ADR share count that reconciles price to market cap.

**What to change.** Persist the filing currency on `financials_annual.json`. Do not set the screen free-cash-flow currency to GBP unless that field is GBP. Do not form a P/E, P/B, or yield from a London price and a statement line until both sides name the same currency. Keep the ADR ratio on `TSM` so the share count, the price, and the cap share a unit, and do not mix NT$ statement lines into that dollar cap.

## 2. London history prices are in pence

**What is wrong.** Prices in `docs/data/history` for these FTSE names are in pence. The pound price used for multiples is that figure divided by 100. A cap built as price times shares, without the division, is a hundred times too large. The FTSE notes build every pence-times-shares cap as price × ordinary shares / 100.

**Where.** The notes show the same print both ways. Shell’s 11 Oct 2026 history price is 3,793.5 pence and the London price used for the multiple is £37.935. The same split is in the other FTSE notes (Rio 7,126.0 pence and a £71.26 price; Tesco 503.8 pence and £5.038; Sage 1,071.5 pence and £10.715).

**What to change.** Store `price_unit: pence` on LSE history rows, and divide by 100 before market cap, P/E, P/B, and yield. Do not leave callers to remember the scale.

## 3. Dividend yield is scaled two different ways

**What is wrong.** On the global names, stored `dividend_yield` is between 0 and 1, and the repo rescales that field only when the raw value is above 1. A stored 0.32 can therefore be read as a 32% fraction. On the FTSE names, library `dividend_yield` between 0 and 1 is a fraction (0.0294 means 2.94%), while the London screen prints a percent. Several of those screen percents are not the filing dividend divided by the cap in any unit the notes tried.

**Where.**

- `AAPL`: stored yield 0.32. The memo says the screen’s “32%” yield misstates a yield of about 0.32%. FY2025 dividends of $15.421 billion over the $4.991 trillion cap are 0.31%.
- `AVGO`: stored yield 0.76. The memo says the screen buy rests on a 73% yield artefact. FY2025 dividends over the cap are 0.68%.
- `NVDA`: stored yield 0.46. FY2026 dividends of $0.974 billion over the $5.245 trillion cap are 0.019%.
- `GOOGL` / `GOOG`: FY2025 dividends over each class cap are 0.24%. Stored Class A yield is 0.25. Stored Class C yield is 0.26.
- `MSFT`: FY2026 dividends over the cap are 0.66%. Stored yield is 0.73.
- FTSE screen yields that match none of the pound, dollar, or euro readings in the notes: `RIO.L` screen 4.9% (pound 5.31%, dollar 3.99%, euro 4.48%; `RIO.AX` fraction 0.0435); `FRES.L` raw 4.06 / displayed 4.1% (pound 3.22%, dollar 2.42%); `ABF.L` raw 3.43 / displayed 3.4% against a pound dividend/cap of 5.02%, and the memo labels that statement’s revenue in pounds; `SBRY.L` raw 4.08 / displayed 4.1% against 7.57% if pounds; `EDV.L` raw 3.48 / displayed 3.5% (pound 2.90%, dollar 2.18%).
- Close but not the filing ratio: `HLN.L` cash dividends 612 million are 1.97% of the cap, screen yield 2.1%, and `Common Stock Dividend Paid` is missing. `GSK.L` pound dividend/cap 3.65% vs screen 3.9%. `BT-A.L` 4.25% vs raw 4.32, displayed 4.3%. `CNA.L` 3.56% if pounds vs raw 3.85, displayed 3.9%. `SGE.L` 2.02% vs raw 2.1.
- `Common Stock Dividend Paid` is missing, and only `Cash Dividends Paid` is present, for `FRES.L`, `HLN.L`, and `EDV.L`.
- `IAG.L` has no filing dividend. Screen raw 2.05 displays as 2.0%, and the Madrid metrics yield is the fraction 0.02.

**What to change.** Store yield as a decimal fraction, and format percent only at display. Do not treat “raw > 1” as the only rescale. Recompute the screen yield from the dividend line actually present (`Common Stock Dividend Paid`, else `Cash Dividends Paid`) and a market cap in the same currency. If the currency is missing, leave the yield unchecked instead of printing a percent.

## 4. Screen free cash flow is not the filing line

**What is wrong.** The displayed free-cash-flow figure is sometimes a screen TTM, sometimes a company-adjusted policy figure, and sometimes a foreign metrics row. The filing line (operating cash flow minus capital expenditure) and the statement’s own TTM field are often different numbers, both still in the file. A divergence flag is stored even when the canonical figure equals the filing, because the TTM does not.

**Where the screen figure is not the filing year, and a filing exists.**

- `NVDA`: screen free cash flow $41.810 billion. FY2026 filing free cash flow $96.676 billion. The last four filing quarters sum to $127.006 billion. Screen operating cash flow does match the filing year. Screen revenue and net income are the year ended January 2026, while the trailing P/E uses the later four quarters.
- `AAPL`: screen free cash flow $107.722 billion. FY2025 filing $98.767 billion. The last four filing quarters sum to $136.683 billion. The memo says the screen’s about $108 billion misstates filing free cash flow of about $99 billion.
- `GOOGL` and `GOOG`: screen free cash flow $22.665 billion. FY2025 filing $73.266 billion. The June 2026 quarter’s free cash flow was −$5.855 billion because capital expenditure $44.924 billion exceeded operating cash flow $39.069 billion.
- `MSFT`: screen free cash flow $16.546 billion. FY2026 filing $66.987 billion. Screen operating cash flow matches the filing $182.935 billion, so the capex inside the screen free-cash-flow figure is not the filing capex.
- `GSK.L`: filing free cash flow is operating cash flow 7,741 million minus capital expenditure 2,985 million, which is 4,756 million. The displayed figure is 5,406 million, tagged `auto_majority_company_adjusted`. Screen TTM is 3,482,625,024.
- `RTO.L`: filing free cash flow 703 million, also stored as `filing_aligned`. The statement’s own TTM is 707 million. Displayed free cash flow is 615 million, `policy_fcf` on basis `company_adjusted`, tagged `auto_majority_company_adjusted`. Screen TTM is 1,050,875,008.
- `CNA.L`: filing free cash flow 141 million, also stored as `filing_aligned`. Displayed figure 167 million, `policy_fcf` on basis `company_adjusted`. The statement’s own TTM is −172 million, the same number as the 2026-06-30 quarterly free cash flow. Screen TTM is 2,141,874,944.
- `ULVR.L`: displayed 6,732,624,896, tagged `auto_fallback_screen_ttm`, equals `UNA.AS` metrics `free_cashflow`. Filing free cash flow is 6,759 million.
- `REL.L`: displayed 2,232,375,040 equals `REN.AS` metrics `free_cashflow`. Filing free cash flow is 2,311 million.
- `CCEP.L`: displayed 1,583,000,064 equals the Nasdaq `CCEP` metrics `free_cashflow`. Filing free cash flow is 2,003 million.

**Where the canonical figure matches the filing, and the screen TTM does not.** The notes flag this for `SHEL.L` (canonical 23,916 million, TTM 21,458,374,656), `RIO.L` (4,497 million vs 3,595,500,032), `BP.L` (11,272 million vs 12,878,874,624), `TSCO.L` (2,240 million vs 2,131,374,976), `HLN.L` (2,221 million vs 1,801,750,016), `IMB.L` (3,166 million vs 2,502,374,912), `FRES.L` (1,889,566,000 vs screen TTM 1,999,836,928, and the statement’s own TTM is 2,264,498,000), `BT-A.L` (filing and the statement’s own TTM are both 1,861 million; screen TTM is 1,200,375,040), `ABF.L` (canonical 997 million, statement TTM 1,059 million, screen TTM 737,124,992), `SGE.L` (canonical 469 million, statement TTM 479 million, screen TTM 632,249,984), `EDV.L` (canonical 1,131,300,000, statement TTM 1,433 million, screen TTM 1,763,975,040), `SN.L` (canonical 852 million, statement TTM 855 million, screen TTM 1,059,000,000), `SBRY.L` (filing and the statement’s own TTM are both 923 million; screen TTM is 821,875,008). `IMB.L`’s memo says a filing–screen gap remains; the canonical figure does not differ from the filing, and the TTM figure does. Batch 2 stores `fcf_divergence_flagged` true on the names whose TTM differs.

**Where there is no filing to check.**

- `AMZN`: free cash flow $3.219 billion against operating cash flow $139.514 billion. No research folder. The file does not say which period those fields cover.
- `META`: free cash flow $21.554 billion against operating cash flow $115.800 billion. No filing. Nothing in the repo identifies the gap.
- `SPCX`: free cash flow is empty. No filing.
- `IAG.L`: displayed 1,088,749,952 is tagged `auto_fallback_screen_ttm`, labeled GBP, and also stored as `filing_aligned`. There is no filing. Screen operating cash flow is 6,588,000,000 with no statement line beside it.

**What to change.** Keep three figures distinct and named: filing free cash flow (operating cash flow minus capital expenditure), the statement file’s own TTM, and the screen TTM. When `policy_fcf` is `company_adjusted` or `screen_ttm`, do not present it as the filing line. The displayed metric should be `filing_aligned` when that field exists, and the policy basis should stay visible. Do not write `filing_aligned` when no filing exists. For `MSFT` and `NVDA`, do not pair a matching operating-cash-flow figure with a free-cash-flow figure that uses a different capex.

## 5. Foreign-listing figures are copied onto the London screen

**What is wrong.** A `.L` screen field equals a metrics field on another listing, with no conversion and, for free cash flow, a GBP label.

**Where.**

- `SHEL.L` screen TTM free cash flow 21,458,374,656 equals `SHELL.AS` metrics `free_cashflow`.
- `RIO.L` screen TTM 3,595,500,032 equals `RIO.AX` metrics `free_cashflow`.
- `ULVR.L` displayed free cash flow equals `UNA.AS` metrics `free_cashflow`, not the Amsterdam filing line of 6,759 million. There is no `ULVR.L` research folder. The statement and the share count are `docs/data/library/markets/euro_depth/screen/research/UNA.AS`.
- `REL.L` displayed free cash flow equals `REN.AS` metrics `free_cashflow`, not the filing line of 2,311 million. No `REL.L` folder. Statement: `.../euro_depth/screen/research/REN.AS`.
- `CCEP.L` displayed free cash flow equals Nasdaq `CCEP` metrics `free_cashflow`, not the filing line of 2,003 million. The screen P/E of 20.4 matches the Nasdaq trailing P/E of 20.33, not the London price over filing EPS (18.5 if the EPS is pounds, 21.9 if euros, 24.6 if dollars). No `CCEP.L` folder. Statement: `docs/data/library/markets/nasdaq100/screen/research/CCEP`.
- `IAG.L` displayed free cash flow equals `IAG.MC` metrics `free_cashflow` and is labeled GBP. The screen P/E of 7.3 sits beside the Madrid trailing P/E of 7.41. There is no London statement, so book, ROE, and a London-price multiple are unchecked.
- `GOOGL` has no research folder. Its accounts are the `GOOG` folder. The two classes are stored as two full market caps, $4.271 trillion and $4.218 trillion. They must not be added.
- `TSM` is the ADR row in `us_adr_asia` only. Price times shares is 5.00 times the stored market cap, so the share count is about five ordinary shares per ADR.

**What to change.** If a `.L` field is copied from another ticker, store that ticker as the source and convert into the London currency before display. Do not label a copied euro or dollar metrics figure as GBP. Do not score a London P/E off another listing’s trailing P/E. Ingest a `.L` statement for Unilever, RELX, Coca-Cola Europacific Partners, and IAG, or mark the London screen as using the foreign statement. Keep GOOGL and GOOG as separate rows and do not sum the caps. Store the TSM ADR ratio next to the share count.

## 6. Share counts, FX rates, and the pound-cap fix

**What is wrong.** A pound cap in the batch notes is either pence × ordinary shares / 100, or a same-name foreign market cap converted with a rate the repo actually stores. Those notes use GBPUSD 1.3317 and EURUSD 1.124. They state that the repo has no HKD rate and no SEK rate. Without shares, or without a rate, they leave the pound figure missing or substitute a foreign cap.

**Where the batch notes still stand.**

- `IAG.L`: London prices exist (415.9 pence on 11 Oct 2026). Ordinary shares are missing in those notes, so there is no pound cap from the London price. The roster cap is the `IAG.MC` market cap 21,306,484,736 converted at the repo euro and pound rates, £17.98B. The pound-cap fix left that method in the original 100.
- `ULVR.L`, `REL.L`, and `CCEP.L` have no `.L` share count in the batch notes. Shares are taken from `UNA.AS` (2,179,482,192), `REN.AS` (1,819,061,446), and `CCEP` (448,645,963).
- `HLN.L`: diluted EPS is missing, so the screen P/E of 19.4 is unchecked.
- `BT-A.L`: the income statement has no EPS line, so the screen P/E of 17.5 is unchecked.
- `AMZN`, `META`, `TSM`, and `SPCX` have no research folder and no filing. `GOOGL` has no folder of its own. `RTO.L` has a statement and filing bodies, and `research.json` is missing. `IAG.L` has no folder, no statement, and no memo.

**Pound-cap fix.** The follow-up write-up says 250 of 350 pound caps are now computable, up from 100. 150 ordinary-share counts were added for names that already had an 11 Oct 2026 London price and no share count. Those counts are in `docs/data/ftse350_ordinary_shares.json`. Of them, 144 are Yahoo Finance `quoteSummary` `sharesOutstanding`, fetched 2026-10-16. `III.L` and `VEIL.L` are Yahoo `marketCap` divided by the Yahoo GBp price (Financial Times displayed 1.02bn and 121.38m). `CRDA.L`, `HLMA.L`, and `ITRK.L` are from the Financial Times tearsheet, because Yahoo had neither a share count nor a market cap. Compass (`CPG.L`) and IHG (`IHG.L`) are USD quotes. Baltic Classifieds (`BCG.L`) and Metlen (`MTLN.L`) are EUR quotes. The other 146 new counts are pence quotes.

`PNN.L` is the Pennon exception. The count is the Pennon RNS of 1 Oct 2026 (capital as at 30 Sep 2026): 471,987,051 issued ordinary shares minus 5,628 treasury shares. The 11 Oct price is before the rights-issue admission expected on 12 Oct. Yahoo’s 521,463,945 matched neither the pre-issue count nor the post-issue count.

HSBC and AstraZeneca did not need an HKD or SEK rate. Their London prices and the new share counts give £238.68bn (`HSBA.L`) and £186.08bn (`AZN.L`).

100 names still have no pound cap. They have no price in the 11 Oct 2026 history run and no library cap in GBP, USD, EUR, AUD, or CAD. A share count alone cannot price them. They are the trust-screen names other than `GROW.L` and `HMSO.L`, which already had a convertible cap:

`AAS.L`, `AGT.L`, `AIE.L`, `ALW.L`, `ASL.L`, `ATR.L`, `ATT.L`, `BBOX.L`, `BGFD.L`, `BNKR.L`, `BPCR.L`, `BRGE.L`, `BRSC.L`, `BRWM.L`, `BUT.L`, `BYG.L`, `CGT.L`, `CLDN.L`, `CORD.L`, `CTY.L`, `DLN.L`, `EDIN.L`, `EMG.L`, `ESCT.L`, `EWI.L`, `FCIT.L`, `FCSS.L`, `FEML.L`, `FEV.L`, `FGEN.L`, `FGT.L`, `FSV.L`, `GPE.L`, `GSCT.L`, `HANA.L`, `HFEL.L`, `HGT.L`, `HICL.L`, `HRI.L`, `HSL.L`, `HVPE.L`, `IAD.L`, `ICGT.L`, `JAM.L`, `JCH.L`, `JEDT.L`, `JEGI.L`, `JEMI.L`, `JFJ.L`, `JGGI.L`, `JMGI.L`, `LAND.L`, `LMP.L`, `LWDB.L`, `MNKS.L`, `MNTN.L`, `MRC.L`, `MRCH.L`, `MUT.L`, `MYI.L`, `NAIT.L`, `NAS.L`, `NBPE.L`, `OCI.L`, `PCGH.L`, `PCT.L`, `PEY.L`, `PHI.L`, `PHP.L`, `PIN.L`, `PINT.L`, `PNL.L`, `PPET.L`, `RCP.L`, `RICA.L`, `RTW.L`, `SAFE.L`, `SAIN.L`, `SDP.L`, `SEIT.L`, `SEQI.L`, `SGRO.L`, `SHC.L`, `SMT.L`, `SOI.L`, `SSIT.L`, `SUPR.L`, `TEM.L`, `TFIF.L`, `THRL.L`, `TMPL.L`, `TRIG.L`, `TRY.L`, `UEM.L`, `UKW.L`, `USA.L`, `UTG.L`, `VOF.L`, `WKP.L`, `WWH.L`.

**What to change.** Do not add an HKD or SEK rate in order to price HSBC or AstraZeneca. Those two caps now use the London price and the new share count. For the 100 tickers above, do not invent a pound cap from a share count alone. They need a stored 11 Oct 2026 London price, or a library cap in GBP, USD, EUR, AUD, or CAD. Keep recording the source ticker when a share count is borrowed (`UNA.AS`, `REN.AS`, `CCEP`). Leave P/E blank when the statement has no EPS (`HLN.L`, `BT-A.L`). Ingest filings for `AMZN`, `META`, `TSM`, `SPCX`, and `IAG.L` before a screen multiple is treated as checked.

## 7. Price history is only a short window

**What is wrong.** The global notes’ valuation history is the library snapshot window, not a multi-year price history: 52 daily files from 2026-07-18 through the 2026-10-16 snapshot. The FTSE history archive inside the 18 Jul–16 Oct 2026 window is 25 runs from 2 Aug through 11 Oct 2026. There is no FTSE price in the repo on 18 Jul or 16 Oct.

**Where.** That window is what the trailing-P/E bands in the global notes are built from (for example NVDA trailing P/E from 26.65 to 34.48, GOOGL from 26.85 on 18 July to a low of 15.95 with the price only moving from $346.77 to $349.22). The FTSE notes’ high and low prints are inside those 25 runs only.

**What to change.** Keep history that starts before 18 Jul 2026 and that includes a print on the days the screen is dated. Do not describe a three-month snapshot band as a multi-year valuation range.

A ticker can also be missing from runs inside that 25-run archive. The span above is the archive’s dates, not a price path for every name.

**Where.** `YNGA.L` is in 1 of the 25 runs: 996.0 pence on 11 Oct 2026 only. There is no 2 Aug price and no other print. `HFD.L` is absent from the 2 Aug run and present in the other 24. `ASC.L` is in 3 of the 25 runs: 498.0 pence on 4 Oct, 456.0 on 7 Oct, and 466.0 on 11 Oct. There is no 2 Aug price. `AMRQ.L` is in 1 of the 25 runs: 117.0 pence on 11 Oct 2026 only.

**What to change.** Do not treat the 2 Aug–11 Oct span as a stored path for a name that is missing from runs inside it. Record which of the 25 runs contain the ticker before using a 2 Aug print, a high, or a low.

## 8. Enterprise value is missing or does not reconcile

**What is wrong.** The London screen stores no enterprise value for the twenty FTSE names in these notes. Where a foreign metrics row has one, it is not equal to market cap + debt − cash on that same row. Two global rows mix units or break that identity by a wide margin.

**Where.**

- No London enterprise value: all twenty FTSE names in the two FTSE notes. `BP.L` also has no enterprise-value row in the library metrics read for that pass.
- Same-row gaps, in the listing’s own figures: `SHELL.AS` 301.05 billion vs 305.52 billion; `RIO.AX` 267.84 vs 265.32; `UNA.AS` 153.49 vs 151.40; `REN.AS` 68.62 vs 68.16; Nasdaq `CCEP` 59.33 vs 58.43; `IAG.MC` 26.33 vs 26.00.
- `SPCX`: cap + debt − cash is $1.899 trillion. Stored enterprise value is $3.858 trillion.
- `TSM`: stored enterprise value is 15,433,971,269,632. Cap plus the stored debt minus the stored cash is negative, because cash is on the NT$ scale of the stored revenue, not the dollar cap.

**What to change.** Store enterprise value on the London screen in one currency, equal to market cap + debt − cash, and store the residual when the vendor figure differs. Do not write an enterprise value from NT$ cash against a dollar cap. Do not store the SpaceX enterprise value while it is about twice cap + debt − cash, without a named adjustment.

## 9. One-off items distort the multiples the screen shows

**What is wrong.** Trailing P/E, ROE, earnings growth, and margin use a net-income figure that includes a gain, an impairment, unusual items, or discontinued operations. The screen then shows a multiple that is not the statutory EPS, or a positive multiple on a statutory loss. Forward and trailing multiples, and fiscal-year revenue versus later quarters, are also mixed in the global notes.

**Where.**

- `GOOGL` and `GOOG`, quarter ended 30 June 2026: gain on sale of securities $98.839 billion, total unusual items $98.839 billion, net income $112.193 billion, operating income $40.770 billion. Trailing P/E fell from about 26 to 17.5 (`GOOGL` from 26.85 on 18 July to a low of 15.95) while the Class A price only moved from $346.77 to $349.22. Earnings growth is 2.94. The 54.8% margin is those four quarters of net income ($244.205 billion) over those four quarters of revenue ($445.867 billion). The `GOOG` memo says the 294% growth is from one-offs. Both classes share that screen free cash flow, growth, and margin.
- `BP.L`: pretax income 7,746 million, tax 6,451 million, total unusual items −5,393 million, impairment of capital assets 5,738 million, net income 55 million, diluted EPS 0.0034. Net income over equity is 0.10%. The screen ROE is 8.9% and the screen P/E is 23.5. Pound price over that EPS is about 1,724 if the EPS is pounds, and about 2,296 if it is dollars. Neither is 23.5.
- `CNA.L`: net income −72 million, diluted EPS −0.015, unusual items −817 million, impairment of capital assets 508 million, pretax income 112 million. Statutory net income over equity is −2.33%. The screen P/E is 9.8 and the screen ROE is 19.9%. Normalized income 540,750,000 is 17.5% of equity and a pound P/E of 12.3. Neither is the screen figure. The 2026-06-30 quarterly free cash flow is −172 million.
- `EDV.L`: total unusual items −419,400,000 against net income 679,200,000. Net income over equity is 22.4%. The screen ROE is 31.3%.
- `RTO.L`: net income 470 million, of which discontinued operations are 180 million and continuing net income is 290 million. Diluted EPS 0.1854. Pound price over that EPS is 16.3. Price over continuing net income per share is 26.3. Normalized income per share gives 22.3. A dollar reading of diluted EPS is 21.8. The screen P/E is 33.7. Screen ROE is 6.0% against net income over equity of 8.55%. Tangible book is −3,421 million. Screen P/B is 1.8, against 1.39 if equity is pounds and 1.85 if equity is dollars.
- `FRES.L`: net income over equity is 29.9%. Operating income over equity is 49.5%. The screen ROE is 53.0%. The screen stores `adjusted_eps_filing_screen_divergence_warning` true and a growth divergence of 940.9 percentage points. Screen P/E 11.9 matches neither the pound reading 14.7 nor the dollar reading 19.5.
- `SGE.L`: price over stockholders’ equity is 14.2. Tangible book is −1,705 million, so price over tangible book is negative. The screen P/B is 45.0. Net income over equity is 51.3%. The screen ROE is 75.6%. EBIT over equity is 74.9%, beside that ROE and not equal to it. Total debt over equity is 219%. The screen input `debt_to_equity` is 919.091. Screen P/E is 26.8 against a pound reading of 28.8.
- `REL.L`: net income 2,065 million over equity 2,366 million is 87.3%. The screen ROE is 1.3%. Price over book is 20.9 if equity is pounds, about 28 if dollars, and about 25 if euros. The screen P/B is 38.4. Screen P/E 21.8 is not the pound price over EPS 1.12 (24.3) and not the `REN.AS` trailing P/E of 24.81.
- `AVGO`: earnings growth 2.153. The memo says the Nasdaq buy rests on Yahoo 215% growth and the yield artefact. Trailing P/E is 45.37, down from 61.70 on 18 July, with forward P/E 17.75. Stored revenue is still the FY2025 $63.887 billion. The latest quarter alone, ended 31 July 2026, is revenue $29.591 billion. Nasdaq signal buy, S&P signal hold.
- `AMZN`: earnings growth 2.423, with no filing. Trailing P/E fell from 29.90 to 19.79 while the price only moved from $247.23 to $254.76. Market cap over the trailing P/E of 20.50 implies about $134 billion of earnings, against stored net income of $77.670 billion. The file does not say which period is which.
- `META`: stored earnings growth −0.134 while trailing P/E rose from 23.47 on 18 July to 27.76 and the price went from $646.01 to $736.72. Market cap over the trailing P/E is about $67.6 billion, against stored net income of $60.458 billion. No filing, so the file does not say which period is which.
- `TSCO.L`: pound price over diluted EPS 0.271 is 18.6. The screen P/E is 16.8. A euro or dollar conversion moves further away. ROE 15.6% vs screen 17.0%. The quarterly statement is one period, not the annual line. The same “one period, not a full year” note applies to the quarterly income statement on `GSK.L` and to `EDV.L`’s 2026-06-30 quarter.
- `ABF.L`: the memo labels revenue in pounds. Pound P/E 13.0 vs screen 13.8, P/B 1.18 vs 1.1, ROE 9.27% vs 8.5%. A euro or dollar conversion does not land on the screen P/E or the screen yield.
- `SN.L` is the case where ROE does match (11.8% vs 11.9%) and the dollar reading of yield and book sits beside the screen, while P/E still does not. That is a currency gap, not a one-off. It is listed in section 1.

**What to change.** When unusual items, an impairment, a securities gain, or discontinued operations are large relative to net income, store the earnings basis next to P/E, ROE, growth, and margin. Do not publish a positive P/E on a negative statutory EPS unless that basis is named (`CNA.L`). Do not let one quarter’s gain set the trailing multiple and the growth rate (`GOOGL`, `GOOG`). Keep fiscal-year revenue and the later quarters that drive trailing P/E as separate fields (`NVDA`, `AVGO`). For `SGE.L` and `REL.L`, do not display P/B or ROE that cannot be formed from stockholders’ equity, tangible book, and the London price in one currency. For `RTO.L`, do not display a P/E that matches none of diluted EPS, continuing net income per share, or normalized income per share.

## 10. Other pipeline splits the global batch showed

**What is wrong.** Two index screens of the same ticker disagree, two sector labels disagree, and a rationale is stored cut off. Those are pipeline outputs, not a view of the business.

**Where.**

- Nasdaq-100 and S&P 500 signals differ on the same ticker: `AAPL` buy vs hold, `GOOG` buy vs hold, `MSFT` buy vs hold, `AVGO` buy vs hold. Both screens of `GOOGL` say hold. The buy on Alphabet exists only on the Nasdaq screen of the class that has the memo.
- `SPCX`: the Nasdaq-100 constituent row says sector Telecommunications Services. The metrics row says Industrials. The name strings differ (SpaceX vs Space Exploration Technologies Corp.). No trailing P/E in any of the 52 snapshots. No chart and no research folder. The repo has no ingested 10-K or S-1 body. Net income is −$4.937 billion on the stored figures.
- `MSFT` and `AVGO`: the stored research rationale is cut off at the end.

**What to change.** Keep both index signals when they differ. Do not collapse them to one composite. Give `SPCX` one sector, and do not screen it as if a filing had been ingested. Store the full rationale, or store that it was truncated.

## 11. The statement field called TTM free cash flow is the latest quarter

**What is wrong.** On these names the statement field called TTM free cash flow equals the latest quarterly free-cash-flow line. It is not a trailing twelve months. Section 4 already records one case of that equality, on `CNA.L`. Batch 3 shows the same identity on seven more names, including one where the annual filing line and that field are far apart.

**Where.** `BTRW.L` annual filing free cash flow is 8.7 million. The statement’s own TTM free cash flow is 422.7 million, the same number as free cash flow on the 2026-06-30 quarterly cash-flow statement. The same identity, statement TTM equal to the latest quarterly free-cash-flow line, is on `KGF.L` (810 million, quarter 2026-07-31), `ABDN.L` (297 million, quarter 2026-06-30), `BBY.L` (565 million, quarter 2026-06-30), `JD.L` (1,032 million, quarter 2026-07-31), `SCT.L` (184,612,000, quarter 2026-01-31), and `HIK.L` (191 million, quarter 2026-06-30).

**What to change.** Do not label that statement field as trailing twelve months when it is the latest quarterly free-cash-flow line. Keep it separate from the annual filing line. On `BTRW.L`, do not let 422.7 million stand in for the annual 8.7 million.

## 12. Computacenter’s divergence flag is false while the displayed figure is not the filing

**What is wrong.** `CCC.L` stores `fcf_divergence_flagged` false. The displayed free cash flow is the screen TTM, 287,937,504. The filing free cash flow and the statement’s own TTM are both 257.6 million. `PAF.L` is the other way around: the flag is also false, and the displayed figure is the filing line.

**Where.**

- `docs/data/research/CCC.L`. The canonical figure is the filing line, tagged `auto_majority_filing_aligned`. The displayed figure is the screen TTM, not that canonical figure. The flag does not mark the difference.
- `PAF.L`. Filing free cash flow 340,848,000 is the displayed figure. The statement’s own TTM is the same 340,848,000. The screen TTM is 327,180,512, the same number as the AIM metrics `free_cashflow`. The flag does not mark that difference.

**What to change.** Set `fcf_divergence_flagged` when the screen TTM is not the filing line, whether or not the displayed figure is the screen TTM. Do not display Computacenter’s 287,937,504 as if it were the 257.6 million filing figure. On `PAF.L`, do not treat a false flag as agreement between the filing line and the screen TTM.

## 13. Memos cite a cash-flow figure that is not on the statement

**What is wrong.** Memos state a cash-flow amount that is not a line in the statement file. One of them also names a fiscal year the statement year key does not use.

**Where.**

- `CCC.L`: the memo states filing free cash flow of £206.9m. The statement line is 257.6 million. The prior-year free-cash-flow line is 385.6 million, which is also not £206.9m.
- `KGF.L`: the memo states H1 free cash flow of £339m. That figure is not the annual line (1,032 million) and not the statement TTM (810 million).
- `SCT.L`: the memo says FY2025 statutory operating cash flow of £140.7m. The statement’s latest operating-cash-flow line is 115,608,000. The 2026-01-31 quarterly operating-cash-flow line is 195,891,000. Neither is £140.7m. The statement year key is 2024. The memo calls the accounts FY2025.
- `BWY.L`: the memo states FY26 statutory operating cash of £337m and net cash of £158m. Neither is a line in the statement file. The year split on that file is in section 15.

**What to change.** Do not treat a memo cash-flow sentence as the statement line when the numbers differ. Point the memo at the statement field it is quoting, or drop the figure. For `SCT.L`, do not call the statement FY2025 while its year key is 2024.

## 14. Batch 3 has no library metrics row, and IG Group’s screen ROE is missing

**What is wrong.** No library metrics row is stored for the ten names in `docs/ftse350-batch-3.md`. `IGG.L` also has no screen ROE, while net income and equity are in the statement.

**Where.** The ten are `CCC.L`, `KGF.L`, `ABDN.L`, `BBY.L`, `JD.L`, `BTRW.L`, `SCT.L`, `RS1.L`, `HIK.L`, and `IGG.L`. On `IGG.L`, net income is 380.4 million and equity is 1,842.4 million. Net income over that equity is 20.6%. The screen ROE is missing.

**What to change.** Do not read a missing library metrics row as a stored zero. For `IGG.L`, do not leave screen ROE empty when the statement has both net income and equity. Store the ratio from those lines, or store that the screen left it unchecked.

## 15. Bellway’s 2025 statement does not cover a full set of accounts

**What is wrong.** `BWY.L`’s 2025 income statement has only EPS and share counts. The balance sheet and the cash flow stop at 2024. The screen P/E uses the 2025 EPS. The screen free cash flow is the 2024 line.

**Where.** `docs/data/research/BWY.L`. The 2025 income-statement key has diluted EPS 1.318, basic EPS 1.328, diluted average shares 119,533,715, and basic average shares 118,644,063. Revenue, net income, and operating income are missing on that year. The balance sheet and the cash flow have no 2025 key. Their latest year is 2024. Price £19.48 over the 2025 diluted EPS of 1.318 is 14.8, and the screen P/E is 14.8. The 2024 free-cash-flow line is −66.9 million, and that is the displayed screen free cash flow. The memo’s £337m operating cash and £158m net cash are not on the statement. That memo gap is also listed in section 13.

**What to change.** Do not pair a 2025 EPS with a 2024 cash-flow line and present both as one year’s screen. Leave revenue, net income, and operating income missing on 2025 until those lines exist. Do not treat the 2024 free-cash-flow line as a 2025 or FY26 figure.

## 16. Inchcape stores leverage figures that disagree

**What is wrong.** `INCH.L` stores several leverage figures that are not the same ratio. None of the screen leverage fields is total debt over equity.

**Where.** `docs/data/research/INCH.L`. Total debt 1,264 million over equity 1,257 million is 100.6%. Total debt minus cash of 635 million is 629 million. The screen input `debt_to_equity` is 0.080. The key metrics store `D/E (Yahoo)` 273%, `D/E (screen)` 0%, and `Leverage (filing)` £1.0m adjusted net debt.

**What to change.** Store one named leverage figure, with the debt and cash lines it uses. Do not show 273%, 0%, £1.0m, and 0.080 as if they were the same ratio. Total debt over equity on this statement is 100.6%, and debt minus cash is 629 million.

## 17. Berkeley has no capital-expenditure line

**What is wrong.** `BKG.L` has no capital-expenditure line. Free cash flow equals operating cash flow. Purchase of PPE is 0.

**Where.** `docs/data/research/BKG.L`. Filing free cash flow 260.3 million equals the screen canonical figure and equals operating cash flow. Purchase of PPE is 0. The capital-expenditure line is missing.

**What to change.** Do not treat free cash flow as operating cash flow minus capital expenditure when the capital-expenditure line is absent. Store that the line is missing, and do not read Purchase of PPE of 0 as a researched capex figure unless the filing says so.

## 18. B&M’s screen yield is a per-share dividend, not the cash-dividend line

**What is wrong.** `BME.L`’s screen yield equals the memo’s ordinary dividend of 9.6p over the 264.6 pence price, which is 3.63%. The cash-dividend line over the cap is 5.00%.

**Where.** `docs/data/research/BME.L`. The dividend of 133 million is 5.00% of the cap. Screen `dividend_yield_raw` is 3.63 and the displayed yield is 3.6%. The financial review’s ordinary dividend of 9.6p over the 264.6 pence price is 3.63%.

**What to change.** Do not present the per-share ordinary dividend over the London price as the same yield as cash dividends over the market cap. If the screen uses 9.6p, label that basis. The cash-dividend line on this statement is 5.00% of the cap.

## 19. Greggs has no statement TTM, and the screen still stores one

**What is wrong.** `GRG.L` has no statement TTM free cash flow, and `quarterly_cashflow` is empty. The screen still stores a TTM figure, marked unverified, and also marked as a suppressed filing mismatch.

**Where.** `docs/data/research/GRG.L`. The statement’s own TTM free cash flow is missing. `quarterly_cashflow` is empty. The screen TTM is 101,225,000. The screen stores `screen_ttm_unverified` true and `ttm_suppressed_screen_filing_mismatch` true.

**What to change.** Do not store a screen TTM when the statement TTM is missing and the quarterly cash-flow file is empty. If a figure is kept, keep `screen_ttm_unverified` and `ttm_suppressed_screen_filing_mismatch` on it, and do not present 101,225,000 as a filing trailing twelve months.

## 20. Grafton and Clarkson reviews say the quarterly file is empty, and it is not

**What is wrong.** The financial reviews for `GFTU.L` and `CKN.L` say the quarterly cash-flow file is empty and TTM is suppressed. Both statement files have a quarterly free-cash-flow line, and that line is the statement TTM. Both screens store `ttm_suppressed_screen_filing_mismatch` false.

**Where.** `docs/data/research/GFTU.L`: the statement TTM is 198,154,000, the same number as free cash flow on the 2026-06-30 quarterly cash-flow statement. The review says the Yahoo quarterly cash flow is empty and TTM is suppressed. `docs/data/research/CKN.L`: the statement TTM is 112.2 million, the same number as free cash flow on the 2026-06-30 quarterly cash-flow statement. The review says the quarterly cash-flow series is empty and TTM cash flow is suppressed. Both screens store `ttm_suppressed_screen_filing_mismatch` false.

**What to change.** Do not write that the quarterly file is empty, or that TTM is suppressed, when the statement has a quarterly free-cash-flow line. Set `ttm_suppressed_screen_filing_mismatch` only when that line is actually missing. On these two names the quarterly line is the statement TTM.

## 21. Hammerson’s trust screen is not the euro metrics row

**What is wrong.** `HMSO.L` is on the trust screen. That screen is not the `HMSO.IR` metrics row. On that euro row, last price times shares is not the stored market cap. There is no statement under `HMSO.L` or `HMSO.IR`.

**Where.** The trust screen key metrics are Discount 17.7%, P/E 8.2, P/B 0.82, and Yield 5.6%. ROE is missing. There is no free-cash-flow object. The `HMSO.IR` metrics row, stored under `euro_depth` and `iseq20`, has trailing P/E 8.75, price-to-book 0.883, dividend yield 0.0521, `return_on_equity` 0.1056, and free cash flow 10,037,500. None of those is the London screen figure. `last_price` 3.5 times `shares_outstanding` 529,736,620 is 1,854,078,170, not the market cap 2,041,640,448.

**What to change.** Do not treat the trust-screen discount, P/E, P/B, or yield as the euro metrics row, and do not copy one onto the other without naming the source. Do not store a market cap that is not last price times shares on that same row. Leave the London multiples unchecked until a statement exists under `HMSO.L` or `HMSO.IR`.

## 22. Bodycote, Atalaya, and Ashmore store a screen TTM and mark it verified

**What is wrong.** `BOY.L`, `ATYM.L`, and `ASHM.L` have the same missing statement TTM and empty `quarterly_cashflow` as Greggs. The screen still stores a TTM, and sets both `screen_ttm_unverified` and `ttm_suppressed_screen_filing_mismatch` to false. Greggs sets both flags true.

**Where.** `docs/data/research/BOY.L`: statement TTM missing, `quarterly_cashflow` empty, screen TTM 96,062,496, both flags false. `docs/data/research/ATYM.L`: statement TTM missing, `quarterly_cashflow` empty, screen TTM 127,294,496, the same number as the AIM metrics `free_cashflow`, both flags false. `docs/data/research/ASHM.L`: statement TTM missing, `quarterly_cashflow` empty, screen TTM 23,087,500, both flags false.

**What to change.** When the statement TTM is missing and the quarterly cash-flow file is empty, do not set `screen_ttm_unverified` or `ttm_suppressed_screen_filing_mismatch` to false. Keep both true, as on Greggs, and do not present 96,062,496, 127,294,496, or 23,087,500 as a filing trailing twelve months. On Atalaya, label 127,294,496 as the AIM `free_cashflow` if that figure is kept.

## 23. FirstGroup shows three free-cash-flow figures

**What is wrong.** `FGP.L` stores a filing line, a displayed company-adjusted figure marked stale, and a different canonical figure. The auto policy lists `company_adjusted` as discarded, and the key metric still shows that discarded figure.

**Where.** `docs/data/research/FGP.L`. The filing free-cash-flow line is 362.6 million. That equals `filing_aligned` and `cashflow_metrics_free_cashflow`. The screen object stores `company_adjusted` 73.8 million, `company_adjusted_stale_year` true, and `company_adjusted_snapshot` 113.5 million. The canonical figure is 113.5 million, tagged `policy_company_adjusted`. The displayed free cash flow is 73.8 million, which is `policy_fcf` and `primary_fcf`. The auto policy lists `company_adjusted` as discarded.

**What to change.** Keep the filing line, the stale `company_adjusted`, and the snapshot as three named figures. Do not show 73.8 million as the key metric when the policy discards `company_adjusted` and the canonical figure is the snapshot, 113.5 million. Do not present either company-adjusted figure as the filing line of 362.6 million.

## 24. Gamma has no Total Debt line, and the screen still stores leverage

**What is wrong.** The 2025 balance sheet for `GAMA.L` has no Total Debt field. The screen still stores a debt-to-equity input. The AIM row stores a total-debt figure. The review states a net-debt figure. None of those is a statement line.

**Where.** `docs/data/research/GAMA.L`. Total Debt is missing on the 2025 balance sheet. The screen input `debt_to_equity` is 11.519. The AIM row stores `total_debt` 42 million. The review states FY2025 net debt of (£9.3m).

**What to change.** Do not store `debt_to_equity` 11.519, AIM `total_debt` 42 million, or the review’s (£9.3m) as a statement Total Debt line when that field is missing. If any of those figures is kept, name its source. Leave leverage unchecked until the statement has a Total Debt field.

## 25. A filing-body count can be short of the set

**What is wrong.** A research folder can store filing bodies and still be short of the set. The handover already records names with no folder. It does not record a partial count.

**Where.** `docs/data/research/COST.L`: 86 of 90 filing bodies are stored. `docs/data/research/BAG.L`: 60 of 61 filing bodies are stored.

**What to change.** Do not treat “filing bodies are stored” as a complete set when the note gives a short count. Keep the stored count and the set size, 86 of 90 and 60 of 61. The notes do not name the missing bodies.

## 26. Cash can be stored under a different field name

**What is wrong.** `GCP.L` has no `Cash And Cash Equivalents` field. Cash is stored under another name, and net debt does not subtract it.

**Where.** `docs/data/research/GCP.L`. `Cash And Cash Equivalents` is missing. Cash of 12.0 million is stored as `Cash Cash Equivalents And Federal Funds Sold`. Net debt is 19.3 million, equal to total debt, so that field does not subtract the stored cash.

**What to change.** Read cash from `Cash Cash Equivalents And Federal Funds Sold` when `Cash And Cash Equivalents` is missing, and name that field. Do not treat net debt of 19.3 million as total debt minus that 12.0 million. On this statement those two figures are equal, so the stored cash was not subtracted.

## 27. The report flag and the object flag disagree

**What is wrong.** On `POLN.L` and `BOWL.L`, `fcf_divergence_flagged` is true while the free-cash-flow object’s `filing_screen_mismatch` is false. The screen TTM is not the filing line. Section 12 covers a report flag that stays false. It does not cover these two stored flags disagreeing.

**Where.** `docs/data/research/POLN.L`. Filing free cash flow is 46,660,000. The screen TTM is 35,976,876. The screen stores `fcf_divergence_flagged` true and `filing_screen_mismatch` false. `docs/data/research/BOWL.L`. Filing free cash flow is 37,017,000. The screen TTM is 43,811,376. The screen stores `fcf_divergence_flagged` true and `filing_screen_mismatch` false.

**What to change.** Do not store `filing_screen_mismatch` false while `fcf_divergence_flagged` is true and the screen TTM is not the filing line. On these two names the object flag should agree with the report flag.

## 28. An operating name can have a price and still no pound cap

**What is wrong.** Operating names have an 11 Oct 2026 London price and no ordinary-share count, so the pound cap is missing. For the first six, the roster reason still says “no price, share count, or convertible cap”. Section 6’s list of 100 names with no pound cap is the trust names that have no 11 Oct price. It does not cover an operating name whose price is stored and whose share count is missing.

**Where.** `3IN.L` 388.0 pence, `AAF.L` 290.2 pence, `AAL.L` 4,170.0 pence, `ADM.L` 3,624.0 pence, `AJB.L` 592.5 pence, and `AMRQ.L` 117.0 pence. Also `ANTO.L` 3,770.0 pence, `APN.L` 273.5 pence, `ATG.L` 472.8 pence, `AUTO.L` 488.7 pence, `AV.L` 677.0 pence, `AVON.L` 2,330.0 pence, and `AZN.L` 11,998.0 pence. Ordinary shares are missing on each. The roster cap is missing on each. On `AZN.L` the roster line points at the `AZN.ST` market cap, and the repo macro file has no SEK rate, so the pound figure is missing for that reason as well.

**What to change.** Do not file these names with the trust names that have no price. The 11 Oct price is stored. The missing piece is the ordinary-share count. Until that count is stored, leave the pound cap missing rather than citing “no price”. On `AZN.L`, do not treat the `AZN.ST` market cap as a pound cap while the macro file has no SEK rate.

## 29. AJ Bell has operating cash flow and no free-cash-flow figure

**What is wrong.** `AJB.L` stores an operating-cash-flow figure and a free-cash-flow object that has no source, no canonical figure, and no screen TTM. Key metrics omit free cash flow. Both verification flags are false.

**Where.** There is no `docs/data/research/AJB.L` folder. The screen’s operating cash flow is 86,485,000. The free-cash-flow object has source `none`. The canonical figure is missing. The screen TTM is missing. Free cash flow is missing from the key metrics. The screen stores `screen_ttm_unverified` false and `ttm_suppressed_screen_filing_mismatch` false.

**What to change.** Do not leave both verification flags false when the free-cash-flow object has source `none`, no canonical figure, and no screen TTM. Do not omit free cash flow from the key metrics while operating cash flow of 86,485,000 is stored, and do not present that operating-cash-flow figure as free cash flow.

## 30. AstraZeneca’s Stockholm row is stored twice

**What is wrong.** `AZN.ST` is stored twice, in `omxs30` and in `euro_depth`. The two rows have different market caps and different last prices, the same share count, and the same enterprise value. Price times shares matches neither cap.

**Where.** The `omxs30` row stores `market_cap` 2,565,198,053,376 and `last_price` 1,654.0. The `euro_depth` row stores `market_cap` 2,598,542,508,032 and `last_price` 1,675.5. Both store `shares_outstanding` 1,550,760,380 and enterprise value 2,626,157,543,424. On the `omxs30` row, that price times those shares is 2,564,957,668,520, not the stored market cap. On the `euro_depth` row, that price times those shares is 2,598,299,016,690, not the stored market cap.

**What to change.** Keep one `AZN.ST` row, or name which market the other copy belongs to. Do not store two market caps and two last prices against one share count and one enterprise value. Do not store a market cap that is not last price times shares on that same row.

## 31. Baltic Classifieds prices are not on one scale

**What is wrong.** `BCG.L` is in all 25 history runs, and the stored prices are not on one scale. Section 2 says London history prices are in pence. It does not cover one ticker whose prints change scale inside that archive.

**Where.** The stored prices are 199.0 on 2 Aug and 213.8 on 30 Aug, then 2.43 on 2 Sep and 2.352 on 11 Oct. The low is 2.05 and the high is 213.8.

**What to change.** Do not use 213.8 and 2.352 as prints on one scale. Do not take a high of 213.8 and a low of 2.05 as a range until the scale of each print is named. The note does not give a cause.
