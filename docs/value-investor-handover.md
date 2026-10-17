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
- `docs/ftse350-batch-14.md` (FTSE ranks 131–140)
- `docs/ftse350-batch-15.md` (FTSE ranks 141–150)
- `docs/ftse350-batch-16.md` (FTSE ranks 151–160)
- `docs/ftse350-batch-17.md` (FTSE ranks 161–170)
- `docs/ftse350-batch-18.md` (FTSE ranks 171–180)
- `docs/ftse350-batch-19.md` (FTSE ranks 181–190)
- `docs/ftse350-batch-20.md` (FTSE ranks 191–200)
- `docs/ftse350-batch-21.md` (FTSE ranks 201–210)
- `docs/ftse350-batch-22.md` (FTSE ranks 211–220)
- `docs/ftse350-batch-23.md` (FTSE ranks 221–230)
- `docs/ftse350-batch-24.md` (FTSE ranks 231–240)
- `docs/ftse350-batch-25.md` (FTSE ranks 241–250)
- `docs/ftse350-batch-26.md` (FTSE ranks 251–260)
- `docs/ftse350-batch-27.md` (FTSE ranks 261–270)
- `docs/ftse350-batch-28.md` (FTSE ranks 271–280)
- `docs/ftse350-batch-29.md` (FTSE ranks 281–290)
- `docs/ftse350-batch-30.md` (FTSE ranks 291–300)
- `docs/ftse350-batch-31.md` (FTSE ranks 301–310)
- `docs/ftse350-batch-32.md` (FTSE ranks 311–320)
- `docs/ftse350-batch-33.md` (FTSE ranks 321–330)
- `docs/ftse350-batch-34.md` (FTSE ranks 331–340)
- `docs/ftse350-batch-35.md` (FTSE ranks 341–350)
- `docs/ftse350-growth-batch-2.md` (second pass on pound-cap ranks 11–20)
- `docs/ftse350-growth-batch-7.md` (second pass on pound-cap ranks 61–70)
- `docs/ftse350-growth-batch-8.md` (second pass on pound-cap ranks 71–80)
- `docs/ftse350-growth-batch-9.md` (second pass on pound-cap ranks 81–90)
- `docs/ftse350-growth-batch-10.md` (second pass on pound-cap ranks 91–100)
- `docs/ftse350-growth-batch-11.md` (second pass on pound-cap ranks 101–110)
- `docs/ftse350-growth-batch-12.md` (second pass on pound-cap ranks 111–120)
- `docs/ftse350-growth-batch-13.md` (second pass on pound-cap ranks 121–130)
- `docs/ftse350-growth-batch-14.md` (second pass from pound-cap rank 131 through rank 148)
- `docs/ftse350-growth-batch-15.md` (second pass from pound-cap rank 149 through rank 160)
- `docs/ftse350-growth-batch-16.md` (second pass from pound-cap rank 161 through rank 173)
- `docs/ftse350-growth-batch-17.md` (second pass from pound-cap rank 174 through rank 190)
- `docs/ftse350-growth-batch-19.md` (second pass from pound-cap rank 201 through rank 210)
- `docs/ftse350-growth-batch-22.md` (second pass from pound-cap rank 231 through rank 240)
- `docs/ftse350-growth-batch-25.md` (second pass from pound-cap rank 261 through rank 270)
- `docs/ftse350-closer-look-batch-1.md` (repeat closer-look read of the first ten: GSK.L, REL.L, HLN.L, FRES.L, SGE.L, SN.L, RTO.L, CCC.L, ABDN.L, BBY.L)
- `docs/ftse350-closer-look-batch-3.md` (repeat closer-look read of the next ten, starting at PFD.L: PFD.L, RAT.L, CURY.L, ATYM.L, BREE.L, GAMA.L, TRST.L, JUP.L, MOON.L, DSCV.L)

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
- `HAS.L` stores `dividend_yield_raw` 0.68 and displays 68.0%. The statement dividend is 7.0 million.
- `HLMA.L` stores `dividend_yield_raw` 0.7 and displays 70.0%. There is no statement.
- `HTWS.L` stores `dividend_yield_raw` 0.56 and displays 56.0%. There is no statement.
- `HWG.L` stores `dividend_yield_raw` 0.98 and displays 98.0%. There is no statement.
- `IWG.L` stores `dividend_yield_raw` 0.57 and displays 57.0%. There is no statement.
- `OXIG.L` stores `dividend_yield_raw` 0.8 and displays 80.0%. There is no statement.
- `RR.L` stores `dividend_yield_raw` 0.87 and displays 87.0%. There is no statement.
- `ROSE.L` stores `dividend_yield_raw` 1.0 and displays 100.0%. Raw 1.0 is not above 1. The displayed figure is 100 times the raw figure. There is no statement.
- `SPI.L` stores `dividend_yield_raw` 0.61 and displays 61.0%. There is no statement.
- `VLX.L` stores `dividend_yield_raw` 0.7 and displays 70.0%. There is no statement.
- `ATYM.L` stores `dividend_yield_raw` 0.96 and displays 96.0%. The cash dividend is 10.1 million, which is 0.67% of the cap if the dividend is pounds and 0.56% if it is euros. The AIM metrics yield is the fraction 1.0.
- `CVSG.L` stores `dividend_yield_raw` 0.77 and displays 77.0%. There is no statement. The AIM dividend yield is the fraction 0.73.
- `ALFA.L` stores `dividend_yield_raw` 0.93 and displays 93.0%. The cash dividend is 26.0 million, which is 5.46% of the cap. The review’s ordinary dividend of 1.5p plus special dividend of 3.1p is 4.6p, which is 2.86% of the 160.8 pence price. The review states a screening snapshot yield of 89%.
- `AAL.L` stores `dividend_yield_raw` 0.69 and displays 69.0%. There is no statement, so there is no cash-dividend figure.
- `AVON.L` stores `dividend_yield_raw` 0.79 and displays 79.0%. There is no statement, so there is no cash-dividend figure.
- `BAB.L` stores `dividend_yield_raw` 0.82 and displays 82.0%. There is no statement, so there is no cash-dividend figure.
- `DPLM.L` stores `dividend_yield_raw` 0.81 and displays 81.0%. The statement dividend is 80.7 million.

**What to change.** Store yield as a decimal fraction, and format percent only at display. Do not treat “raw > 1” as the only rescale. Recompute the screen yield from the dividend line actually present (`Common Stock Dividend Paid`, else `Cash Dividends Paid`) and a market cap in the same currency. If the currency is missing, leave the yield unchecked instead of printing a percent. For `ATYM.L`, `CVSG.L`, `ALFA.L`, `AAL.L`, `AVON.L`, `BAB.L`, `DPLM.L`, and `HAS.L`, do not invent a corrected screen yield. For `AAL.L`, `AVON.L`, and `BAB.L`, do not invent a cash-dividend figure.

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
- `HSBA.L` operating cash flow 29,766,000,000 equals the `0005.HK` operating cash flow, with no conversion. Screen ROE 13.1% matches `return_on_equity` 0.13104999. Screen P/B 1.9 matches price-to-book 1.8876421. Displayed yield 4.0% matches dividend yield 0.0397. Screen P/E 13.4 is not trailing P/E 13.647167.
- `AZN.L` free cash flow 5,120,999,936 equals the `AZN.ST` `free_cashflow` figure and is labeled GBP. There is no filing under `AZN.L`. Screen ROE 22.0% matches `return_on_equity` 0.21965 at one decimal. Screen P/E is 24.0. The Stockholm trailing P/E figures are 25.53 and 25.86. Screen P/B is 4.9. The Stockholm price-to-book figures are 51.01 and 51.67. The Stockholm dividend yield is 0.018. Screen `dividend_yield_raw` is 1.99.
- `GOOGL` has no research folder. Its accounts are the `GOOG` folder. The two classes are stored as two full market caps, $4.271 trillion and $4.218 trillion. They must not be added.
- `TSM` is the ADR row in `us_adr_asia` only. Price times shares is 5.00 times the stored market cap, so the share count is about five ordinary shares per ADR.

**What to change.** If a `.L` field is copied from another ticker, store that ticker as the source and convert into the London currency before display. Do not label a copied euro or dollar metrics figure as GBP. Do not score a London P/E off another listing’s trailing P/E. For `AZN.L`, do not invent a conversion. Leave the two `AZN.ST` rows and the missing SEK rate where they already are. Ingest a `.L` statement for Unilever, RELX, Coca-Cola Europacific Partners, and IAG, or mark the London screen as using the foreign statement. Keep GOOGL and GOOG as separate rows and do not sum the caps. Store the TSM ADR ratio next to the share count.

## 6. Share counts, FX rates, and the pound-cap fix

**What is wrong.** A pound cap in the batch notes is either pence × ordinary shares / 100, or a same-name foreign market cap converted with a rate the repo actually stores. Those notes use GBPUSD 1.3317 and EURUSD 1.124. They state that the repo has no HKD rate and no SEK rate. Without shares, or without a rate, they leave the pound figure missing or substitute a foreign cap.

**Where the batch notes still stand.**

- `IAG.L`: London prices exist (415.9 pence on 11 Oct 2026). Ordinary shares are missing in those notes, so there is no pound cap from the London price. The roster cap is the `IAG.MC` market cap 21,306,484,736 converted at the repo euro and pound rates, £17.98B. The pound-cap fix left that method in the original 100.
- `ULVR.L`, `REL.L`, and `CCEP.L` have no `.L` share count in the batch notes. Shares are taken from `UNA.AS` (2,179,482,192), `REN.AS` (1,819,061,446), and `CCEP` (448,645,963).
- `HLN.L`: diluted EPS is missing, so the screen P/E of 19.4 is unchecked.
- `BT-A.L`: the income statement has no EPS line, so the screen P/E of 17.5 is unchecked.
- `AMZN`, `META`, `TSM`, and `SPCX` have no research folder and no filing. `GOOGL` has no folder of its own. `RTO.L` has a statement and filing bodies, and `research.json` is missing. `IAG.L` has no folder, no statement, and no memo.

**Pound-cap fix.** The follow-up write-up says 250 of 350 pound caps are now computable, up from 100. 150 ordinary-share counts were added for names that already had an 11 Oct 2026 London price and no share count. Those counts are in `docs/data/ftse350_ordinary_shares.json`. Of them, 144 are Yahoo Finance `quoteSummary` `sharesOutstanding`, fetched 2026-10-16. `III.L` and `VEIL.L` are Yahoo `marketCap` divided by the Yahoo GBp price (Financial Times displayed 1.02bn and 121.38m). `CRDA.L`, `HLMA.L`, and `ITRK.L` are from the Financial Times tearsheet, because Yahoo had neither a share count nor a market cap. Compass (`CPG.L`) and IHG (`IHG.L`) are USD quotes. Baltic Classifieds (`BCG.L`) and Metlen (`MTLN.L`) are EUR quotes. The other 146 new counts are pence quotes.

`PNN.L` is the Pennon exception. The count is the Pennon RNS of 1 Oct 2026 (capital as at 30 Sep 2026): 471,987,051 issued ordinary shares minus 5,628 treasury shares. The 11 Oct price is before the rights-issue admission expected on 12 Oct. Yahoo’s 521,463,945 matched neither the pre-issue count nor the post-issue count. The walk’s roster still has no pound figure for `PNN.L`, the 11 Oct price is 357.0 pence, and ordinary shares on `PNN.L` are missing in the data this batch read.

HSBC and AstraZeneca did not need an HKD or SEK rate. Their London prices and the new share counts give £238.68bn (`HSBA.L`) and £186.08bn (`AZN.L`). The walk’s roster still has no pound figure for `HSBA.L`: its line is the `0005.HK` market cap 2,553,021,726,720, the macro file has no HKD rate, the 11 Oct London price is 1,395.8 pence, and ordinary shares on `HSBA.L` are missing in the data this batch read.

100 names still have no pound cap. They have no price in the 11 Oct 2026 history run and no library cap in GBP, USD, EUR, AUD, or CAD. A share count alone cannot price them. They are the trust-screen names other than `GROW.L` and `HMSO.L`, which already had a convertible cap:

`AAS.L`, `AGT.L`, `AIE.L`, `ALW.L`, `ASL.L`, `ATR.L`, `ATT.L`, `BBOX.L`, `BGFD.L`, `BNKR.L`, `BPCR.L`, `BRGE.L`, `BRSC.L`, `BRWM.L`, `BUT.L`, `BYG.L`, `CGT.L`, `CLDN.L`, `CORD.L`, `CTY.L`, `DLN.L`, `EDIN.L`, `EMG.L`, `ESCT.L`, `EWI.L`, `FCIT.L`, `FCSS.L`, `FEML.L`, `FEV.L`, `FGEN.L`, `FGT.L`, `FSV.L`, `GPE.L`, `GSCT.L`, `HANA.L`, `HFEL.L`, `HGT.L`, `HICL.L`, `HRI.L`, `HSL.L`, `HVPE.L`, `IAD.L`, `ICGT.L`, `JAM.L`, `JCH.L`, `JEDT.L`, `JEGI.L`, `JEMI.L`, `JFJ.L`, `JGGI.L`, `JMGI.L`, `LAND.L`, `LMP.L`, `LWDB.L`, `MNKS.L`, `MNTN.L`, `MRC.L`, `MRCH.L`, `MUT.L`, `MYI.L`, `NAIT.L`, `NAS.L`, `NBPE.L`, `OCI.L`, `PCGH.L`, `PCT.L`, `PEY.L`, `PHI.L`, `PHP.L`, `PIN.L`, `PINT.L`, `PNL.L`, `PPET.L`, `RCP.L`, `RICA.L`, `RTW.L`, `SAFE.L`, `SAIN.L`, `SDP.L`, `SEIT.L`, `SEQI.L`, `SGRO.L`, `SHC.L`, `SMT.L`, `SOI.L`, `SSIT.L`, `SUPR.L`, `TEM.L`, `TFIF.L`, `THRL.L`, `TMPL.L`, `TRIG.L`, `TRY.L`, `UEM.L`, `UKW.L`, `USA.L`, `UTG.L`, `VOF.L`, `WKP.L`, `WWH.L`.

**What to change.** Do not add an HKD or SEK rate in order to price HSBC or AstraZeneca. Those two caps now use the London price and the new share count. For the 100 tickers above, do not invent a pound cap from a share count alone. They need a stored 11 Oct 2026 London price, or a library cap in GBP, USD, EUR, AUD, or CAD. Keep recording the source ticker when a share count is borrowed (`UNA.AS`, `REN.AS`, `CCEP`). Leave P/E blank when the statement has no EPS (`HLN.L`, `BT-A.L`). Ingest filings for `AMZN`, `META`, `TSM`, `SPCX`, and `IAG.L` before a screen multiple is treated as checked.

## 7. Price history is only a short window

**What is wrong.** The global notes’ valuation history is the library snapshot window, not a multi-year price history: 52 daily files from 2026-07-18 through the 2026-10-16 snapshot. The FTSE history archive inside the 18 Jul–16 Oct 2026 window is 25 runs from 2 Aug through 11 Oct 2026. There is no FTSE price in the repo on 18 Jul or 16 Oct.

**Where.** That window is what the trailing-P/E bands in the global notes are built from (for example NVDA trailing P/E from 26.65 to 34.48, GOOGL from 26.85 on 18 July to a low of 15.95 with the price only moving from $346.77 to $349.22). The FTSE notes’ high and low prints are inside those 25 runs only.

**What to change.** Keep history that starts before 18 Jul 2026 and that includes a print on the days the screen is dated. Do not describe a three-month snapshot band as a multi-year valuation range.

A ticker can also be missing from runs inside that 25-run archive. The span above is the archive’s dates, not a price path for every name.

**Where.** `YNGA.L` is in 1 of the 25 runs: 996.0 pence on 11 Oct 2026 only. There is no 2 Aug price and no other print. `HFD.L` is absent from the 2 Aug run and present in the other 24. `ASC.L` is in 3 of the 25 runs: 498.0 pence on 4 Oct, 456.0 on 7 Oct, and 466.0 on 11 Oct. There is no 2 Aug price. `AMRQ.L` is in 1 of the 25 runs: 117.0 pence on 11 Oct 2026 only. `MNO.L` is in 3 of the 25 runs. The named prints are 129.0 pence on 4 Oct and 123.5 pence on 11 Oct. There is no 2 Aug price. The note does not name the third day. `VLX.L` is in 8 of the 25 runs. The first print is 627.0 pence on 21 Sep. The 11 Oct print is 688.0. The low is 627.0 and the high is 694.362. There is no 2 Aug print. `ATG.L` has no price in the 2 Aug run. The first stored price is 455.6 pence on 3 Aug. It is in 24 of the 25 runs. The 11 Oct price is 472.8 pence.

**What to change.** Do not treat the 2 Aug–11 Oct span as a stored path for a name that is missing from runs inside it. Record which of the 25 runs contain the ticker before using a 2 Aug print, a high, or a low.

## 8. Enterprise value is missing or does not reconcile

**What is wrong.** The London screen stores no enterprise value for the twenty FTSE names in these notes. Where a foreign metrics row has one, it is not equal to market cap + debt − cash on that same row. Two global rows mix units or break that identity by a wide margin.

**Where.**

- No London enterprise value: all twenty FTSE names in the two FTSE notes. `BP.L` also has no enterprise-value row in the library metrics read for that pass.
- Same-row gaps, in the listing’s own figures: `SHELL.AS` 301.05 billion vs 305.52 billion; `RIO.AX` 267.84 vs 265.32; `UNA.AS` 153.49 vs 151.40; `REN.AS` 68.62 vs 68.16; Nasdaq `CCEP` 59.33 vs 58.43; `IAG.MC` 26.33 vs 26.00.
- `SPCX`: cap + debt − cash is $1.899 trillion. Stored enterprise value is $3.858 trillion.
- `TSM`: stored enterprise value is 15,433,971,269,632. Cap plus the stored debt minus the stored cash is negative, because cash is on the NT$ scale of the stored revenue, not the dollar cap.
- `0005.HK`: stored enterprise value 2,156,879,544,320 is not market cap 2,553,021,726,720 plus total debt 837,577,998,336 minus total cash 1,219,653,009,408. That sum is 2,170,946,715,648.

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
- `DNLM.L`: net income over equity of 148.5 million is 104.7%. The 2026 net income is 155.5 million. The screen ROE is 1.2%. That is the same shape as `REL.L`. The screen ROE cannot be formed from that net income and that equity.
- `AVGO`: earnings growth 2.153. The memo says the Nasdaq buy rests on Yahoo 215% growth and the yield artefact. Trailing P/E is 45.37, down from 61.70 on 18 July, with forward P/E 17.75. Stored revenue is still the FY2025 $63.887 billion. The latest quarter alone, ended 31 July 2026, is revenue $29.591 billion. Nasdaq signal buy, S&P signal hold.
- `AMZN`: earnings growth 2.423, with no filing. Trailing P/E fell from 29.90 to 19.79 while the price only moved from $247.23 to $254.76. Market cap over the trailing P/E of 20.50 implies about $134 billion of earnings, against stored net income of $77.670 billion. The file does not say which period is which.
- `META`: stored earnings growth −0.134 while trailing P/E rose from 23.47 on 18 July to 27.76 and the price went from $646.01 to $736.72. Market cap over the trailing P/E is about $67.6 billion, against stored net income of $60.458 billion. No filing, so the file does not say which period is which.
- `TSCO.L`: pound price over diluted EPS 0.271 is 18.6. The screen P/E is 16.8. A euro or dollar conversion moves further away. ROE 15.6% vs screen 17.0%. The quarterly statement is one period, not the annual line. The same “one period, not a full year” note applies to the quarterly income statement on `GSK.L` and to `EDV.L`’s 2026-06-30 quarter.
- `ABF.L`: the memo labels revenue in pounds. Pound P/E 13.0 vs screen 13.8, P/B 1.18 vs 1.1, ROE 9.27% vs 8.5%. A euro or dollar conversion does not land on the screen P/E or the screen yield.
- `SN.L` is the case where ROE does match (11.8% vs 11.9%) and the dollar reading of yield and book sits beside the screen, while P/E still does not. That is a currency gap, not a one-off. It is listed in section 1.

**What to change.** When unusual items, an impairment, a securities gain, or discontinued operations are large relative to net income, store the earnings basis next to P/E, ROE, growth, and margin. Do not publish a positive P/E on a negative statutory EPS unless that basis is named (`CNA.L`). Do not let one quarter’s gain set the trailing multiple and the growth rate (`GOOGL`, `GOOG`). Keep fiscal-year revenue and the later quarters that drive trailing P/E as separate fields (`NVDA`, `AVGO`). For `SGE.L` and `REL.L`, do not display P/B or ROE that cannot be formed from stockholders’ equity, tangible book, and the London price in one currency. For `DNLM.L`, do not display a screen ROE that cannot be formed from the 2026 net income of 155.5 million and equity of 148.5 million. Do not invent a cause, a currency, or a corrected ROE. For `RTO.L`, do not display a P/E that matches none of diluted EPS, continuing net income per share, or normalized income per share.

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

**What is wrong.** `CCC.L` stores `fcf_divergence_flagged` false. The displayed free cash flow is the screen TTM, 287,937,504. The filing free cash flow and the statement’s own TTM are both 257.6 million. `PAF.L` is the other way around: the flag is also false, and the displayed figure is the filing line. `BMY.L`, `BNZL.L`, `BPT.L`, `BRBY.L`, `CCH.L`, `CHG.L`, and `COA.L` are the same case as `CCC.L`. A statement now exists for each. The displayed figure is the screen TTM and not the statement line. `fcf_divergence_flagged` is false.

**Where.**

- `docs/data/research/CCC.L`. The canonical figure is the filing line, tagged `auto_majority_filing_aligned`. The displayed figure is the screen TTM, not that canonical figure. The flag does not mark the difference.
- `PAF.L`. Filing free cash flow 340,848,000 is the displayed figure. The statement’s own TTM is the same 340,848,000. The screen TTM is 327,180,512, the same number as the AIM metrics `free_cashflow`. The flag does not mark that difference.
- `BMY.L`. The displayed free cash flow is 27.8 million beside the statement line of 31.9 million. The statement TTM is that same 31.9 million. The displayed figure is tagged `auto_fallback_screen_ttm` and also stored as `filing_aligned`. `fcf_divergence_flagged` is false.
- `BNZL.L`. The displayed free cash flow is 701,812,480 beside the statement line of 841.5 million. The statement TTM is 932.8 million. The displayed figure is tagged `auto_fallback_screen_ttm` and also stored as `filing_aligned`. `fcf_divergence_flagged` is false.
- `BPT.L`. The displayed free cash flow is 446,562,496 beside the statement line of 103.6 million. The statement TTM is 64.7 million. The displayed figure is tagged `auto_fallback_screen_ttm` and also stored as `filing_aligned`. `fcf_divergence_flagged` is false. The comparison with operating cash flow is in section 32.
- `BRBY.L`. The displayed free cash flow is 400,750,016 beside the statement line of 370.0 million. The statement TTM is that same 370.0 million. The displayed figure is tagged `auto_fallback_screen_ttm` and also stored as `filing_aligned`. `fcf_divergence_flagged` is false.
- `CCH.L`. The displayed free cash flow is 1,593,175,040 beside the statement line of 760.9 million. The statement TTM is 744.4 million. The displayed figure is tagged `auto_fallback_screen_ttm` and also stored as `filing_aligned`. `fcf_divergence_flagged` is false. The comparison with operating cash flow is in section 32.
- `CHG.L`. The displayed free cash flow is −84,750,000 beside the statement line of −11.2 million. The statement TTM is −15.2 million. The displayed figure is tagged `auto_fallback_screen_ttm` and also stored as `filing_aligned`. `fcf_divergence_flagged` is false. The comparison with operating cash flow is in section 48.
- `COA.L`. The displayed free cash flow is 181,512,496 beside the statement line of 192.6 million. The statement TTM is 186.5 million. The displayed figure is tagged `auto_fallback_screen_ttm` and also stored as `filing_aligned`. `fcf_divergence_flagged` is false.

**What to change.** Set `fcf_divergence_flagged` when the screen TTM is not the filing line, whether or not the displayed figure is the screen TTM. Do not display Computacenter’s 287,937,504 as if it were the 257.6 million filing figure. On `PAF.L`, do not treat a false flag as agreement between the filing line and the screen TTM. On `BMY.L`, `BNZL.L`, `BPT.L`, `BRBY.L`, `CCH.L`, `CHG.L`, and `COA.L`, do not treat a false flag as agreement between the displayed screen TTM and the statement line. Do not invent a cause or a corrected free-cash-flow figure. For `BPT.L` and `CCH.L`, keep the operating-cash-flow comparison in section 32. For `CHG.L`, keep the more-negative comparison in section 48.

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

**What is wrong.** `BWY.L`’s 2025 income statement has only EPS and share counts. The balance sheet and the cash flow stop at 2024. The screen P/E uses the 2025 EPS. The screen free cash flow is the 2024 line. `GNS.L` is the same shape. The 2026 income statement has only diluted EPS, basic EPS, and the two share-count lines. Revenue, net income, and operating income are missing on that year. The balance sheet and the cash flow stop at 2025. The screen free cash flow is the 2025 line.

**Where.** `docs/data/research/BWY.L`. The 2025 income-statement key has diluted EPS 1.318, basic EPS 1.328, diluted average shares 119,533,715, and basic average shares 118,644,063. Revenue, net income, and operating income are missing on that year. The balance sheet and the cash flow have no 2025 key. Their latest year is 2024. Price £19.48 over the 2025 diluted EPS of 1.318 is 14.8, and the screen P/E is 14.8. The 2024 free-cash-flow line is −66.9 million, and that is the displayed screen free cash flow. The memo’s £337m operating cash and £158m net cash are not on the statement. That memo gap is also listed in section 13.

`docs/data/research/GNS.L`. The 2026 income-statement key has diluted EPS 4.251, basic EPS 4.316, and the two share-count lines. Revenue, net income, and operating income are missing on that year. The balance sheet and the cash flow stop at 2025. The screen free cash flow is the 2025 line of 48.6 million.

**What to change.** Do not pair a 2025 EPS with a 2024 cash-flow line and present both as one year’s screen. Leave revenue, net income, and operating income missing on 2025 until those lines exist. Do not treat the 2024 free-cash-flow line as a 2025 or FY26 figure. For `GNS.L`, do not pair the 2026 EPS with the 2025 free-cash-flow line of 48.6 million. Leave revenue, net income, and operating income missing on 2026. Do not invent a 2026 revenue or profit figure. Do not add a cause.

## 16. Inchcape stores leverage figures that disagree

**What is wrong.** `INCH.L` stores several leverage figures that are not the same ratio. None of the screen leverage fields is total debt over equity.

**Where.** `docs/data/research/INCH.L`. Total debt 1,264 million over equity 1,257 million is 100.6%. Total debt minus cash of 635 million is 629 million. The screen input `debt_to_equity` is 0.080. The key metrics store `D/E (Yahoo)` 273%, `D/E (screen)` 0%, and `Leverage (filing)` £1.0m adjusted net debt.

**What to change.** Store one named leverage figure, with the debt and cash lines it uses. Do not show 273%, 0%, £1.0m, and 0.080 as if they were the same ratio. Total debt over equity on this statement is 100.6%, and debt minus cash is 629 million.

## 17. Berkeley has no capital-expenditure line

**What is wrong.** `BKG.L` has no capital-expenditure line. Free cash flow equals operating cash flow. Purchase of PPE is 0. `GCP.L` is the same shape. Capital expenditure is missing, and free cash flow equals operating cash flow.

**Where.** `docs/data/research/BKG.L`. Filing free cash flow 260.3 million equals the screen canonical figure and equals operating cash flow. Purchase of PPE is 0. The capital-expenditure line is missing. `GCP.L`: capital expenditure is missing, and free cash flow equals operating cash flow of 123.7 million. The cash-flow line Gain Loss On Investment Securities is 120.4 million in 2025.

**What to change.** Do not treat free cash flow as operating cash flow minus capital expenditure when the capital-expenditure line is absent. Store that the line is missing, and do not read Purchase of PPE of 0 as a researched capex figure unless the filing says so. For `GCP.L`, do not invent a capital-expenditure figure.

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

**Where.** `3IN.L` 388.0 pence, `AAF.L` 290.2 pence, `AAL.L` 4,170.0 pence, `ADM.L` 3,624.0 pence, `AJB.L` 592.5 pence, and `AMRQ.L` 117.0 pence. Also `ANTO.L` 3,770.0 pence, `APN.L` 273.5 pence, `ATG.L` 472.8 pence, `AUTO.L` 488.7 pence, `AV.L` 677.0 pence, `AVON.L` 2,330.0 pence, and `AZN.L` 11,998.0 pence. Also `ELM.L` 182.2 pence, `ENOG.L` 730.5 pence, `ENT.L` 426.9 pence, `EXPN.L` 2,682.0 pence, `EZJ.L` 680.0 pence, and `FAN.L` 665.0 pence. Also `FCH.L` 189.2 pence, `FRAS.L` 838.5 pence, and `FSG.L` 444.5 pence. Also `GAW.L` 16,390.0 pence, `GDWN.L` 14,220.0 pence, `GLEN.L` 584.6 pence, `GNC.L` 255.4 pence, `GRI.L` 162.0 pence, `HAS.L` 64.25 pence, and `HBR.L` 281.4 pence. Also `HFG.L` 713.5 pence, `HILS.L` 3,050.0 pence, `HLMA.L` 3,528.0 pence, and `HSX.L` 1,847.0 pence. Also `HTG.L` 396.0 pence, `HTWS.L` 216.0 pence, `HWDN.L` 762.5 pence, `HWG.L` 187.0 pence, `ICG.L` 1,808.0 pence, and `IHP.L` 378.5 pence. Also `III.L` 2,402.0 pence, `IMI.L` 3,092.0 pence, `INF.L` 895.6 pence, `INPP.L` 135.4 pence, `INVP.L` 593.0 pence, `IPO.L` 71.0 pence, `ITH.L` 285.4 pence, `ITRK.L` 5,890.0 pence, and `IWG.L` 183.7 pence. Also `JDW.L` 982.5 pence, `JMAT.L` 2,468.0 pence, and `KIE.L` 296.8 pence. Also `LGEN.L` 287.0 pence, `LLOY.L` 101.6 pence, `LRE.L` 646.5 pence, `LSEG.L` 8,694.0 pence, `MAB.L` 287.0 pence, `MKS.L` 397.0 pence, and `MNDI.L` 788.0 pence. Also `MNG.L` 304.3 pence, `MNO.L` 123.5 pence, `MRO.L` 444.5 pence, `MTO.L` 210.4 pence, and `MTRO.L` 155.0 pence. Also `NCC.L` 151.6 pence, `NG.L` 1,147.0 pence, `NWG.L` 642.6 pence, `NXT.L` 14,700.0 pence, and `OCDO.L` 297.0 pence. Also `ONT.L` 213.4 pence, `OSB.L` 486.6 pence, `OXB.L` 521.0 pence, `OXIG.L` 2,958.0 pence, `PAG.L` 701.0 pence, and `PAGE.L` 212.0 pence. Also `PLUS.L` 3,338.0 pence, `PRN.L` 327.5 pence, and `PRU.L` 898.4 pence. Also `PSH.L` 3,778.0 pence, `PSN.L` 1,199.0 pence, `PSON.L` 1,285.0 pence, `QLT.L` 176.4 pence, `QQ.L` 457.0 pence, `RKT.L` 5,132.0 pence, `RMV.L` 490.5 pence, and `ROR.L` 490.4 pence. Also `ROSE.L` 310.0 pence, `RPI.L` 664.5 pence, `RR.L` 1,385.2 pence, `RSW.L` 5,735.0 pence, `SAGA.L` 765.0 pence, and `SDLF.L` 848.5 pence. Also `SHAW.L` 286.5 pence, `SMIN.L` 2,730.0 pence, `SMWH.L` 374.2 pence, and `SPI.L` 247.0 pence. Also `SPX.L` 7,270.0 pence, `SRE.L` 88.4 pence, `SSE.L` 2,454.0 pence, `SSPG.L` 180.3 pence, `STAN.L` 2,119.0 pence, `STJ.L` 1,037.5 pence, `SVS.L` 973.0 pence, and `SVT.L` 3,094.0 pence. Also `SYNC.L` 123.2 pence, `TATE.L` 559.0 pence, `TBCG.L` 4,846.0 pence, `TCAP.L` 328.6 pence, and `THG.L` 27.2 pence. Also `UU.L` 1,423.0 pence, `VEIL.L` 721.0 pence, `VLX.L` 688.0 pence, and `VOD.L` 118.35 pence. Also `WEIR.L` 2,642.0 pence, `WIZZ.L` 1,013.0 pence, `WOSG.L` 682.5 pence, `WPP.L` 385.9 pence, `WTB.L` 2,478.0 pence, `XPP.L` 1,950.0 pence, `XPS.L` 308.5 pence, and `ZIG.L` 439.5 pence. Also `BA.L` 1,860.0 pence, `BAB.L` 913.2 pence, `BARC.L` 429.65 pence, `BATS.L` 4,194.0 pence, `BGEO.L` 12,380.0 pence, `BHMG.L` 419.0 pence, and `BLND.L` 388.6 pence. Also `BCG.L` 2.352 on 11 Oct. The note does not name that print as pence. The two price scales stay in section 31. `BHMG.L`’s P/E stays in section 34. The history file names the `LLOY.L` print as pence. The note writes the `SRE.L` print as pence. The note writes the `THG.L` print as pence. The note writes the `UU.L`, `VEIL.L`, `VLX.L`, and `VOD.L` prints as pence. The note writes the `WEIR.L`, `WIZZ.L`, `WOSG.L`, `WPP.L`, `WTB.L`, `XPP.L`, `XPS.L`, and `ZIG.L` prints as pence. Ordinary shares are missing on each. The roster cap is missing on each. On `AZN.L` the roster line points at the `AZN.ST` market cap, and the repo macro file has no SEK rate, so the pound figure is missing for that reason as well.

**What to change.** Do not file these names with the trust names that have no price. The 11 Oct price is stored. The missing piece is the ordinary-share count. Until that count is stored, leave the pound cap missing rather than citing “no price”. On `AZN.L`, do not treat the `AZN.ST` market cap as a pound cap while the macro file has no SEK rate.

## 29. AJ Bell has operating cash flow and no free-cash-flow figure

**What is wrong.** `AJB.L`, `HSBA.L`, `ICG.L`, `INVP.L`, `LLOY.L`, `MTRO.L`, `NWG.L`, `OSB.L`, `PAG.L`, `PLUS.L`, `ROSE.L`, `SHAW.L`, `STAN.L`, `TBCG.L`, `TCAP.L`, `WIZZ.L`, `BARC.L`, and `BGEO.L` each store an operating-cash-flow figure and a free-cash-flow object that has no source, no canonical figure, and no screen TTM. Key metrics omit free cash flow. Both verification flags are false.

**Where.** There is no `docs/data/research/AJB.L` folder. The screen’s operating cash flow is 86,485,000. The free-cash-flow object has source `none`. The canonical figure is missing. The screen TTM is missing. Free cash flow is missing from the key metrics. The screen stores `screen_ttm_unverified` false and `ttm_suppressed_screen_filing_mismatch` false. There is no `docs/data/research/HSBA.L` folder. The screen’s operating cash flow is 29,766,000,000. The free-cash-flow object has source `none`. The canonical figure is missing. The screen TTM is missing. Free cash flow is missing from the key metrics. The screen stores `screen_ttm_unverified` false and `ttm_suppressed_screen_filing_mismatch` false. There is no `docs/data/research/ICG.L` folder. The screen’s operating cash flow is 846,100,000. The free-cash-flow object has source `none`. The canonical figure is missing. The screen TTM is missing. Free cash flow is missing from the key metrics. The screen stores `screen_ttm_unverified` false and `ttm_suppressed_screen_filing_mismatch` false. There is no `docs/data/research/INVP.L` folder. The screen’s operating cash flow is −312,227,000. The free-cash-flow object has source `none`. The canonical figure is missing. The screen TTM is missing. Free cash flow is missing from the key metrics. The screen stores `screen_ttm_unverified` false and `ttm_suppressed_screen_filing_mismatch` false. There is no `docs/data/research/LLOY.L` folder. The screen’s operating cash flow is 5,701,000,000. The free-cash-flow object has source `none`. The canonical figure is missing. The screen TTM is missing. Free cash flow is missing from the key metrics. The screen stores `screen_ttm_unverified` false and `ttm_suppressed_screen_filing_mismatch` false. There is no `docs/data/research/MTRO.L` folder. The screen’s operating cash flow is −1,092,000,000. The free-cash-flow object has source `none`. The canonical figure is missing. The screen TTM is missing. Free cash flow is missing from the key metrics. The screen stores `screen_ttm_unverified` false and `ttm_suppressed_screen_filing_mismatch` false. There is no `docs/data/research/NWG.L` folder. The screen’s operating cash flow is 7,072,000,000. The free-cash-flow object has source `none`. The canonical figure is missing. The screen TTM is missing. Free cash flow is missing from the key metrics. The screen stores `screen_ttm_unverified` false and `ttm_suppressed_screen_filing_mismatch` false. There is no `docs/data/research/OSB.L` folder. The screen’s operating cash flow is 243,600,000. The free-cash-flow object has source `none`. The canonical figure is missing. The screen TTM is missing. Free cash flow is missing from the key metrics. The screen stores `screen_ttm_unverified` false and `ttm_suppressed_screen_filing_mismatch` false. There is no `docs/data/research/PAG.L` folder. The screen’s operating cash flow is −377,400,000. The free-cash-flow object has source `none`. The canonical figure is missing. The screen TTM is missing. Free cash flow is missing from the key metrics. The screen stores `screen_ttm_unverified` false and `ttm_suppressed_screen_filing_mismatch` false. There is no `docs/data/research/PLUS.L` folder. The screen’s operating cash flow is 284,700,000. The free-cash-flow object has source `none`. The canonical figure is missing. The screen TTM is missing. Free cash flow is missing from the key metrics. The screen stores `screen_ttm_unverified` false and `ttm_suppressed_screen_filing_mismatch` false. There is no `docs/data/research/ROSE.L` folder. The screen’s operating cash flow is −106,000,000. The free-cash-flow object has source `none`. The canonical figure is missing. The screen TTM is missing. Free cash flow is missing from the key metrics. The screen stores `screen_ttm_unverified` false and `ttm_suppressed_screen_filing_mismatch` false. There is no `docs/data/research/SHAW.L` folder. The screen’s operating cash flow is 1,067,900,000. The free-cash-flow object has source `none`. The canonical figure is missing. The screen TTM is missing. Free cash flow is missing from the key metrics. The screen stores `screen_ttm_unverified` false and `ttm_suppressed_screen_filing_mismatch` false. There is no `docs/data/research/STAN.L` folder. The screen’s operating cash flow is 36,841,000,000. The free-cash-flow object has source `none`. The canonical figure is missing. The screen TTM is missing. Free cash flow is missing from the key metrics. The screen stores `screen_ttm_unverified` false and `ttm_suppressed_screen_filing_mismatch` false. There is no `docs/data/research/TBCG.L` folder. The screen’s operating cash flow is 995,709,000. The free-cash-flow object has source `none`. The canonical figure is missing. The screen TTM is missing. Free cash flow is missing from the key metrics. The screen stores `screen_ttm_unverified` false and `ttm_suppressed_screen_filing_mismatch` false. There is no `docs/data/research/TCAP.L` folder. The screen’s operating cash flow is 191,000,000. The free-cash-flow object has source `none`. The canonical figure is missing. The screen TTM is missing. Free cash flow is missing from the key metrics. The screen stores `screen_ttm_unverified` false and `ttm_suppressed_screen_filing_mismatch` false. There is no `docs/data/research/WIZZ.L` folder. The screen’s operating cash flow is 1,179,600,000. The free-cash-flow object has source `none` and currency GBP. The canonical figure is missing. The screen TTM is missing. Free cash flow is missing from the key metrics. The screen stores `screen_ttm_unverified` false, `ttm_suppressed_screen_filing_mismatch` false, and `fcf_divergence_flagged` false. There is no `docs/data/research/BARC.L` folder. The screen’s operating cash flow is 18,739,000,000. The free-cash-flow object has source `none` and currency GBP. The canonical figure is missing. The screen TTM is missing. Free cash flow is missing from the key metrics. `screen_ttm_unverified`, `ttm_suppressed_screen_filing_mismatch`, and `fcf_divergence_flagged` are false. There is no `docs/data/research/BGEO.L` folder. The screen’s operating cash flow is 2,141,804,000. The free-cash-flow object has source `none` and currency GBP. The canonical figure is missing. The screen TTM is missing. Free cash flow is missing from the key metrics. `screen_ttm_unverified`, `ttm_suppressed_screen_filing_mismatch`, and `fcf_divergence_flagged` are false.

**What to change.** Do not leave both verification flags false when the free-cash-flow object has source `none`, no canonical figure, and no screen TTM. Do not omit free cash flow from the key metrics while operating cash flow of 86,485,000, 29,766,000,000, 846,100,000, −312,227,000, 5,701,000,000, −1,092,000,000, 7,072,000,000, 243,600,000, −377,400,000, 284,700,000, −106,000,000, 1,067,900,000, 36,841,000,000, 995,709,000, 191,000,000, 1,179,600,000, 18,739,000,000, or 2,141,804,000 is stored, and do not present that operating-cash-flow figure as free cash flow.

## 30. AstraZeneca’s Stockholm row is stored twice

**What is wrong.** `AZN.ST` is stored twice, in `omxs30` and in `euro_depth`. The two rows have different market caps and different last prices, the same share count, and the same enterprise value. Price times shares matches neither cap.

**Where.** The `omxs30` row stores `market_cap` 2,565,198,053,376 and `last_price` 1,654.0. The `euro_depth` row stores `market_cap` 2,598,542,508,032 and `last_price` 1,675.5. Both store `shares_outstanding` 1,550,760,380 and enterprise value 2,626,157,543,424. On the `omxs30` row, that price times those shares is 2,564,957,668,520, not the stored market cap. On the `euro_depth` row, that price times those shares is 2,598,299,016,690, not the stored market cap. On `0005.HK`, last price 149.3 times shares 17,139,885,525 is 2,558,984,908,882.5, not the stored market cap 2,553,021,726,720.

**What to change.** Keep one `AZN.ST` row, or name which market the other copy belongs to. Do not store two market caps and two last prices against one share count and one enterprise value. Do not store a market cap that is not last price times shares on that same row.

## 31. Baltic Classifieds prices are not on one scale

**What is wrong.** `BCG.L` is in all 25 history runs, and the stored prices are not on one scale. Section 2 says London history prices are in pence. It does not cover one ticker whose prints change scale inside that archive.

**Where.** The stored prices are 199.0 on 2 Aug and 213.8 on 30 Aug, then 2.43 on 2 Sep and 2.352 on 11 Oct. The low is 2.05 and the high is 213.8.

**What to change.** Do not use 213.8 and 2.352 as prints on one scale. Do not take a high of 213.8 and a low of 2.05 as a range until the scale of each print is named. The note does not give a cause.

## 32. Free cash flow is larger than operating cash flow, and there is no filing

**What is wrong.** `BPT.L`, `CCH.L`, `DCC.L`, `HBR.L`, `HAS.L`, `HSX.L`, `HWG.L`, `IHG.L`, `INF.L`, `IPO.L`, `LGEN.L`, `MRO.L`, `MTLN.L`, `MNO.L`, `ONT.L`, `OXIG.L`, `PAGE.L`, `PRU.L`, `PSON.L`, `RKT.L`, `RR.L`, `SAGA.L`, `SDLF.L`, `SMIN.L`, `STJ.L`, `THG.L`, `WPP.L`, `ZIG.L`, `ATG.L`, and `AV.L` each display a free-cash-flow figure larger than the screen’s operating cash flow. There is no filing, except that a statement now exists for `BPT.L` and `CCH.L`. On those two the displayed figure is still greater than operating cash flow. The statement-line comparison is in section 12. The notes do not give a cause.

**Where.** A statement now exists for `BPT.L`. The displayed free cash flow is 446,562,496. Operating cash flow is 135.9 million. The displayed figure is greater than that operating cash flow. The statement-line comparison is in section 12. A statement now exists for `CCH.L`. The displayed free cash flow is 1,593,175,040. Operating cash flow is 1,513.5 million. The displayed figure is greater than that operating cash flow. The statement-line comparison is in section 12. There is no `docs/data/research/DCC.L` folder. The displayed free cash flow is 1,308,650,880. The screen’s operating cash flow is 672,501,000. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/HBR.L` folder. The displayed free cash flow is 4,791,499,776. The screen’s operating cash flow is 3,386,000,000. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/HAS.L` folder. The displayed free cash flow is 111,587,504. The screen’s operating cash flow is 74,000,000. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/HSX.L` folder. The displayed free cash flow is 448,912,512. The screen’s operating cash flow is 72,800,000. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/HWG.L` folder. The displayed free cash flow is 6,438,125. The screen’s operating cash flow is −52,046,000. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/IHG.L` folder. The displayed free cash flow is 913,875,008. The screen’s operating cash flow is 898,000,000. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/INF.L` folder. The displayed free cash flow is 902,200,000. The screen’s operating cash flow is 876,300,000. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/IPO.L` folder. The displayed free cash flow is 92,500,000. The screen’s operating cash flow is −19,500,000. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/LGEN.L` folder. The displayed free cash flow is 7,687,000,064. The screen’s operating cash flow is 4,548,000,000. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/MRO.L` folder. The displayed free cash flow is 448,750,016. The screen’s operating cash flow is 214,000,000. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/MTLN.L` folder. The displayed free cash flow is 731,955,136. The screen’s operating cash flow is 445,876,000. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/MNO.L` folder. The displayed free cash flow is −14,504,258. The screen’s operating cash flow is −14,614,415. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/ONT.L` folder. The displayed free cash flow is −49,700,000. The screen’s operating cash flow is −70,600,000. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/OXIG.L` folder. The displayed free cash flow is 71,475,000. The screen’s operating cash flow is 54,400,000. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/PAGE.L` folder. The displayed free cash flow is 50,916,248. The screen’s operating cash flow is 49,622,000. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/PRU.L` folder. The displayed free cash flow is 4,138,874,880. The screen’s operating cash flow is 2,450,000,000. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/PSON.L` folder. The displayed free cash flow is 838,499,968. The screen’s operating cash flow is 656,000,000. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/RKT.L` folder. The displayed free cash flow is 3,094,000,128. The screen’s operating cash flow is 2,297,000,000. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/RR.L` folder. The displayed free cash flow is 4,602,500,096. The screen’s operating cash flow is 4,565,000,000. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/SAGA.L` folder. The displayed free cash flow is 328,087,488. The screen’s operating cash flow is 117,000,000. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/SDLF.L` folder. The displayed free cash flow is 38,990,999,552. The screen’s operating cash flow is −993,000,000. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/SMIN.L` folder. The displayed free cash flow is 1,153,874,944. The screen’s operating cash flow is 418,000,000. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/STJ.L` folder. The displayed free cash flow is 1,368,462,464. The screen’s operating cash flow is 1,067,200,000. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/THG.L` folder. The displayed free cash flow is 49,221,876. The screen’s operating cash flow is 33,403,000. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/WPP.L` folder. The displayed free cash flow is 744,249,984. The screen’s operating cash flow is 724,000,000. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/ZIG.L` folder. The displayed free cash flow is 437,306,496. The screen’s operating cash flow is −16,803,000. That figure is also stored as `filing_aligned`, and there is no filing. There is no `docs/data/research/ATG.L` folder. The displayed free cash flow is 77,769,504 beside screen operating cash flow of 63,817,000. The canonical figure is tagged `auto_fallback_screen_ttm`, labeled GBP, and also stored as `filing_aligned`. There is no filing. The screen TTM equals that free-cash-flow figure. `screen_ttm_unverified`, `ttm_suppressed_screen_filing_mismatch`, and `fcf_divergence_flagged` are false. There is no `docs/data/research/AV.L` folder. The displayed free cash flow is −2,287,000,064 beside screen operating cash flow of −2,563,000,000, so the free-cash-flow figure is the larger number and both are negative. The canonical figure is tagged `auto_fallback_screen_ttm`, labeled GBP, and also stored as `filing_aligned`. There is no filing. The screen TTM equals that free-cash-flow figure. `screen_ttm_unverified`, `ttm_suppressed_screen_filing_mismatch`, and `fcf_divergence_flagged` are false.

**What to change.** Do not present 1,308,650,880, 4,791,499,776, 111,587,504, 448,912,512, 6,438,125, 913,875,008, 902,200,000, 92,500,000, 7,687,000,064, 448,750,016, 731,955,136, −14,504,258, −49,700,000, 71,475,000, 50,916,248, 4,138,874,880, 838,499,968, 3,094,000,128, 4,602,500,096, 328,087,488, 38,990,999,552, 1,153,874,944, 1,368,462,464, 49,221,876, 744,249,984, 437,306,496, 77,769,504, or −2,287,000,064 as free cash flow while each is larger than its screen operating cash flow and no filing exists. Leave the pairs unchecked. The notes do not give a cause. Keep `AV.L` in this section. Both figures are negative, and the free-cash-flow figure is the larger number. A statement now exists for `BPT.L` and `CCH.L`. Do not present 446,562,496 or 1,593,175,040 as free cash flow while each is greater than operating cash flow. Do not invent a cause or a corrected free-cash-flow figure. The statement-line comparison stays in section 12.

## 33. A London history print can be a dollar quote

**What is wrong.** Section 2 treats London history prices as pence. The pound-cap fix labels Compass and IHG USD quotes. The Compass batch note writes that path as pence. The IHG history file does not name the unit as pence.

**Where.** `CPG.L`. The 11 Oct stored price is 31.2. The batch note writes that path as pence. Section 6 says Compass (`CPG.L`) is a USD quote, in the share-count paragraph. `IHG.L`. The stored prices are 160.7 on 2 Aug and 159.05 on 11 Oct. The low is 153.2 and the high is 162.65. The history file does not name the unit as pence. Section 6 says IHG (`IHG.L`) is a USD quote, in the share-count paragraph.

**What to change.** Name the unit on the Compass history print before dividing 31.2 by 100. Do not invent a conversion between that print and pounds. Do not write the IHG prints as pence. Do not invent a conversion for 159.05.

## 34. An unchecked screen P/E can equal the London price in pence

**What is wrong.** When there is no statement, the screen P/E is unchecked, and on these names that P/E equals the 11 Oct London price in pence.

**Where.** `AMRQ.L`: screen P/E 117.0 and price 117.0 pence. There is no statement. `BHMG.L`: screen P/E 419.0 and price 419.0 pence. There is no statement. `CSN.L`: screen P/E 322.0 and price 322.0 pence. There is no statement. `IWG.L`: screen P/E 183.7 and price 183.7 pence. There is no statement.

**What to change.** Do not treat an unchecked screen P/E that equals the London price in pence as a multiple. Leave it unchecked until a statement EPS exists.

## 35. A trust row can show only a P/E

**What is wrong.** `FCSS.L`, `JEMI.L`, `PCGH.L`, `SSIT.L`, and `USA.L` are on the trust screen. Each row’s key metrics are a P/E only. Discount, premium, P/B, and yield are missing. Metrics present are 7 of 11. There is no history price and no free-cash-flow object. The notes do not name the other metrics inside that 7.

**Where.** There is no `docs/data/research/FCSS.L` folder. There is no `FCSS.L` price in the 25 history runs. Key metrics are P/E 8.5. Discount, premium, P/B, and yield are missing. Metrics present are 7 of 11. There is no free-cash-flow object. There is no `docs/data/research/JEMI.L` folder. There is no `JEMI.L` price in the 25 history runs. Key metrics are P/E 5.0. Discount, premium, P/B, and yield are missing. Metrics present are 7 of 11. There is no free-cash-flow object. There is no `docs/data/research/PCGH.L` folder. There is no `PCGH.L` price in the 25 history runs. Key metrics are P/E 10.2. Discount, premium, P/B, and yield are missing. Metrics present are 7 of 11. There is no free-cash-flow object. There is no `docs/data/research/SSIT.L` folder. There is no `SSIT.L` price in the 25 history runs. Key metrics are P/E 5.0. Discount, premium, P/B, and yield are missing. Metrics present are 7 of 11. There is no free-cash-flow object. There is no `docs/data/research/USA.L` folder. There is no `USA.L` price in the 25 history runs. Key metrics are P/E 5.1. Discount, premium, P/B, and yield are missing. Metrics present are 7 of 11. There is no free-cash-flow object.

**What to change.** Do not treat these rows as a full trust screen while discount, P/B, and yield are missing. Do not name the other metrics inside that 7.

## 36. A screen operating-cash-flow figure can carry a fractional tail

**What is wrong.** `HILS.L` stores an operating-cash-flow figure with a fractional tail. There is no statement. The other screen cash figures in this batch are whole numbers.

**Where.** There is no `docs/data/research/HILS.L` folder. The screen’s operating cash flow is 183,000,727.155207. There is no statement.

**What to change.** Do not store that field with a fractional tail while the other screen cash figures in this batch are whole numbers. Do not round 183,000,727.155207.

## 37. Free cash flow can be stored while operating cash flow is missing

**What is wrong.** `III.L` stores a displayed free-cash-flow figure while operating cash flow is missing. There is no filing. Both verification flags are false. `3IN.L` and `BLND.L` each store a canonical free-cash-flow figure while operating cash flow is missing. There is no filing.

**Where.** There is no `docs/data/research/III.L` folder. The displayed free cash flow is 3,390,374,912, stored as `filing_aligned`, and there is no filing. Operating cash flow is missing. The screen stores `screen_ttm_unverified` false and `ttm_suppressed_screen_filing_mismatch` false. There is no `docs/data/research/3IN.L` folder. The canonical free cash flow is 221,250,000, tagged `auto_fallback_screen_ttm`, labeled GBP, and also stored as `filing_aligned`. There is no filing. Operating cash flow is missing. The screen TTM is 221,250,000. `screen_ttm_unverified`, `ttm_suppressed_screen_filing_mismatch`, and `fcf_divergence_flagged` are false. There is no `docs/data/research/BLND.L` folder. The canonical free cash flow is 218,375,008, tagged `auto_fallback_screen_ttm`, labeled GBP, and also stored as `filing_aligned`. There is no filing. Operating cash flow is missing. The screen TTM is 218,375,008. `screen_ttm_unverified`, `ttm_suppressed_screen_filing_mismatch`, and `fcf_divergence_flagged` are false.

**What to change.** Do not compare 3,390,374,912 with operating cash flow while that field is missing. Do not round 3,390,374,912. Do not compare 221,250,000 or 218,375,008 with operating cash flow while that field is missing. Do not invent a share count for `3IN.L`.

## 38. An unchecked screen P/B can be negative

**What is wrong.** When there is no statement, the screen P/B is unchecked, and on these names that P/B is negative.

**Where.** `IWG.L`: screen P/B is −5.7. There is no statement. `IHG.L`: screen P/B is −8.0. There is no statement. `SDLF.L`: screen P/B is −39.1. There is no statement and no P/E key. `TRST.L`: equity is −6.73 million. The screen P/B is −197.5. Price over that equity is −145 if the equity is pounds and −193 if it is dollars. The screen has no P/E key. `DOM.L`: stockholders’ equity is −88.3 million. The screen P/B is −10.5. Price over that equity is −9.8. `MOON.L`: stockholders’ equity is −54.2 million. The screen P/B is −15.9. Price over that equity is −15.8.

**What to change.** Do not treat a negative unchecked screen P/B as a multiple. Do not invent an equity figure. For `TRST.L`, `DOM.L`, and `MOON.L`, do not invent a book-value figure.

## 39. A London history print can be a euro quote

**What is wrong.** Section 2 treats London history prices as pence. The pound-cap fix labels Metlen a EUR quote. The history file does not name the unit as pence. The prints are on one scale. Section 31 covers a ticker whose prints change scale. It does not cover this series.

**Where.** `MTLN.L`. The stored prices are 46.22 on 2 Aug and 48.76 on 11 Oct. The low is 45.34 and the high is 50.75. The name is in all 25 runs. The history file does not name the unit as pence. Section 6 says Metlen (`MTLN.L`) is a EUR quote, in the share-count paragraph.

**What to change.** Do not write the Metlen prints as pence. Do not invent a conversion for 48.76. Do not treat this series as the scale change in section 31.

## 40. An unchecked trust P/E can sit in the thousands while the history price is missing

**What is wrong.** `NBPE.L` is on the trust screen. The screen P/E is 1,504.0. There is no history price. Section 34 covers an unchecked screen P/E that equals a London price in pence. There is no pence price for 1,504.0 to equal.

**Where.** There is no `docs/data/research/NBPE.L` folder. There is no `NBPE.L` price in the 25 history runs. Discount is 27.1%, P/B is 0.73, and yield is 4.6%. The screen P/E is 1,504.0. Metrics present are 11 of 11. There is no statement and no free-cash-flow object.

**What to change.** Do not treat 1,504.0 as a checked multiple. Do not invent a history price for `NBPE.L`.

## 41. A trust row can show a yield and a P/E while discount, premium, and P/B are missing

**What is wrong.** `SEQI.L` and `TFIF.L` are on the trust screen. Each row’s key metrics are a yield and a P/E. Discount, premium, and P/B are missing. Section 35 covers a trust row whose key metrics are a P/E only, with yield also missing. It does not cover these rows.

**Where.** There is no `docs/data/research/SEQI.L` folder. There is no `SEQI.L` price in the 25 history runs. Key metrics are Yield 8.2% and P/E 12.0. Discount, premium, and P/B are missing. Metrics present are 8 of 11. There is no free-cash-flow object. The note does not name the other metrics inside that 8. There is no `docs/data/research/TFIF.L` folder. There is no `TFIF.L` price in the 25 history runs. Key metrics are Yield 9.9% and P/E 15.6. Discount, premium, and P/B are missing. Metrics present are 8 of 11. There is no free-cash-flow object. The note does not name the other metrics inside that 8.

**What to change.** Do not fold `SEQI.L` or `TFIF.L` into section 35. Do not treat these rows as a full trust screen while discount, premium, and P/B are missing. Do not name the other metrics inside that 8.

## 42. An unchecked positive screen P/B can sit in the hundreds

**What is wrong.** `SSPG.L` stores an unchecked positive screen P/B in the hundreds. Section 38 covers a negative unchecked screen P/B. It does not cover this figure.

**Where.** There is no `docs/data/research/SSPG.L` folder. The screen P/B is 225.4. The 11 Oct price is 180.3 pence. There is no P/E key and no statement. The displayed free cash flow is 333,987,488. The screen’s operating cash flow is 742,200,000. Free cash flow is below operating cash flow.

**What to change.** Do not treat 225.4 as a checked multiple. Do not fold 225.4 into section 38. Do not invent a book-value figure.

## 43. An unchecked trust P/E can be stored as the string inf while the history price is missing

**What is wrong.** `UKW.L` is on the trust screen. The screen P/E is the string `inf`. There is no history price. Section 40 covers an unchecked trust P/E in the thousands while the history price is missing. It does not cover this string.

**Where.** There is no `docs/data/research/UKW.L` folder. There is no `UKW.L` price in the 25 history runs. Discount is 15.8%, P/B is 0.84, and yield is 9.3%. The screen P/E is the string `inf`. Metrics present are 11 of 11. There is no free-cash-flow object.

**What to change.** Do not treat `inf` as a checked multiple. Do not invent a number for `inf`. Do not fold `UKW.L` into section 40.

## 44. A diluted EPS can be stored as positive in a year when net income is negative

**What is wrong.** `EDV.L` stores a positive diluted EPS in years when net income is negative. Section 9 records total unusual items of −419,400,000 against 2025 net income of 679,200,000. It does not record the EPS sign. It does not cover these years.

**Where.** Diluted EPS is 0.940815 in 2023 beside net income −208,900,000. Diluted EPS is 0.932555 in 2024 beside net income −300,200,000. The 2025 diluted EPS is 2.74 and matches that year’s net income of 679,200,000.

**What to change.** Do not fold these years into section 9. Do not invent a share count. Do not treat the 2023 and 2024 EPS figures as the prior points of an earnings series.

## 45. Unusual-item fields on one year can disagree

**What is wrong.** On `JUP.L` in 2023 the unusual-item fields do not match. Section 9 records one-off items that distort the multiples the screen shows. It does not cover fields that disagree with each other.

**Where.** In 2023 the field named Total Unusual Items is 1.9 million, Total Unusual Items Excluding Goodwill is −74.3 million, and Special Income Charges is −78.4 million. Normalized income that year is 123.5 million beside net income of −12.9 million. In 2024 the two unusual-item fields match at 4.7 million. In 2025 they match at 8.3 million. On `MOON.L` in 2025 the field named Total Unusual Items is 0, Total Unusual Items Excluding Goodwill is −56.7 million, and Special Income Charges is −56.7 million. Normalized income is 88.9 million beside net income of −11.1 million. In 2026 total unusual items are zero and normalized income equals net income. On `GEN.L` in 2024 the field named Total Unusual Items is −7.2 million, Total Unusual Items Excluding Goodwill is −19.6 million, and Special Income Charges is −19.6 million. In 2025 the two unusual-item fields match at −9.2 million. On `HFD.L` in 2025 the field named Total Unusual Items is −20.5 million, Total Unusual Items Excluding Goodwill is −68.4 million, and Special Income Charges is −68.4 million. Normalized income that year is 65.6 million beside net income of −33.6 million. In 2026 total unusual items are −2.2 million and normalized income is 34.5 million. On `AO.L` in 2025 the field named Total Unusual Items is 0, Total Unusual Items Excluding Goodwill is −19.6 million, and Special Income Charges is −19.6 million. Normalized income is 44.0 million beside net income of 10.5 million. In 2026 the unusual-item fields match at 0. On `MEGP.L` in 2023 those three fields are −1.4 million, −2.1 million and −2.7 million, and normalized income is 53.0 million beside net income of 50.7 million. In 2024 they are 1.4 million, 0.3 million and 0.7 million, and normalized income is 54.8 million beside net income of 54.1 million. In 2025 the two unusual-item fields match at 2.1 million. On `JSG.L` in 2022 those three fields are 0.8 million, −0.6 million and −0.7 million. The note does not give a 2022 net income or normalized income. In 2023, 2024 and 2025 the `JSG.L` unusual-item fields match. On `CCH.L` in 2022 the field named Total Unusual Items is −205.3 million and Total Unusual Items Excluding Goodwill is −219.0 million. On `BPT.L` in 2025 the field named Total Unusual Items is 144.3 million, Total Unusual Items Excluding Goodwill is 144.3 million, and Special Income Charges is −8.9 million. Normalized income is −54.0 million beside net income of 41.5 million. On `DCC.L` in 2026 the field named Total Unusual Items is −27.2 million, Total Unusual Items Excluding Goodwill is −70.4 million, and Special Income Charges is −71.7 million. Normalized income is 369.2 million beside net income of 13.4 million. On `EMG.L` in 2025 the field named Total Unusual Items is −2.0 million, Total Unusual Items Excluding Goodwill is −2.0 million, and Special Income Charges is −83.0 million. Normalized income is 176.4 million beside net income of 175.0 million.

**What to change.** Do not fold `JUP.L`, `MOON.L`, `GEN.L`, `HFD.L`, `AO.L`, `MEGP.L`, `JSG.L`, `CCH.L`, `BPT.L`, `DCC.L`, or `EMG.L` into section 9. Do not invent which field the normalized income used, and do not invent a corrected unusual-items figure. Do not invent a 2022 net income or normalized income for `JSG.L`.

## 46. A zero screen yield can sit beside a statement dividend

**What is wrong.** A raw yield of 0.0 displayed as 0.0% is still not the scale bug in section 3. On `PTEC.L` the screen stores that zero beside a statement dividend.

**Where.** `PTEC.L` stores `dividend_yield_raw` 0.0 and displays 0.0% beside a statement dividend of 1,766.2 million. That dividend is 172% of the cap if it is pounds. The review states a special dividend of about €1.8bn. Filing free cash flow is −52.9 million. `EWG.L` displays 0.0% beside a dividend of 24.3 million. That dividend is 3.44% of the cap if it is pounds and 2.90% if it is euros.

**What to change.** Do not fold `PTEC.L` or `EWG.L` into section 3. Do not invent a yield. Do not decide that the zero excludes the special dividend unless the file says so.

## 47. A positive diluted EPS can be stored while the screen has no P/E key

**What is wrong.** `VCT.L`, `MGAM.L`, `EWG.L`, `VTY.L`, and `HWG.L` store a positive diluted EPS. The screen has no P/E key on each.

**Where.** `VCT.L` diluted EPS is 0.318, and the pound price over it is 29.6. `MGAM.L` diluted EPS is 0.075, and the pound price over it is 38.7. `EWG.L` diluted EPS is 0.0029, and the pound price over it is 351. `VTY.L` diluted EPS is 0.42, and the pound price over it is 5.2. `HWG.L` diluted EPS is 0.028.

**What to change.** Do not invent a screen P/E.

## 48. Free cash flow can be more negative than operating cash flow, and there is no filing

**What is wrong.** Section 32 covers a displayed free cash flow larger than the screen operating cash flow. It does not cover a displayed free cash flow that is more negative than that operating cash flow. `ADM.L` and `AMRQ.L` each store that more-negative pair as `filing_aligned`. There is no filing. `CHG.L` stores a displayed figure that is more negative than operating cash flow. A statement exists. The statement-line comparison is in section 12. `CSN.L` stores a displayed figure that is more negative than operating cash flow. A statement exists.

**Where.** There is no `docs/data/research/ADM.L` folder. The displayed free cash flow is −4,439,737,344 beside screen operating cash flow of 436,500,000. The canonical figure is tagged `auto_fallback_screen_ttm`, labeled GBP, and also stored as `filing_aligned`. There is no filing. The screen TTM equals that free-cash-flow figure. `screen_ttm_unverified`, `ttm_suppressed_screen_filing_mismatch`, and `fcf_divergence_flagged` are false. There is no `docs/data/research/AMRQ.L` folder. The displayed free cash flow is −78,940,464 beside screen operating cash flow of −6,025,383. The canonical figure is tagged `auto_fallback_screen_ttm`, labeled GBP, and also stored as `filing_aligned`. There is no filing. The screen TTM equals that free-cash-flow figure. `screen_ttm_unverified`, `ttm_suppressed_screen_filing_mismatch`, and `fcf_divergence_flagged` are false. A statement exists for `CHG.L`. The displayed free cash flow is −84,750,000 beside operating cash flow of 91.1 million. The displayed figure is more negative. The statement-line comparison is in section 12. A statement exists for `CSN.L`. The displayed free cash flow is −5,245,425,152, more negative than operating cash flow of −219.8 million. The statement line is −220.7 million. The statement TTM is 77.8 million. The displayed figure is tagged `auto_fallback_screen_ttm` and also stored as `filing_aligned`. `fcf_divergence_flagged` is false.

**What to change.** Do not fold `ADM.L` or `AMRQ.L` into section 32. Do not present −4,439,737,344 or −78,940,464 as free cash flow while each is more negative than its screen operating cash flow and no filing exists. Leave the pairs unchecked. Do not invent why the two cash figures differ. Do not fold `CHG.L` into section 32. Do not present −84,750,000 as free cash flow while it is more negative than operating cash flow of 91.1 million. Do not invent a cause or a corrected free-cash-flow figure. The statement-line comparison stays in section 12. Do not fold `CSN.L` into section 32. Do not present −5,245,425,152 as free cash flow while it is more negative than operating cash flow of −219.8 million. Do not invent a cause.

## 49. A trust row can store a discount, a P/B, and a P/E while the yield key is missing

**What is wrong.** Section 35 is a trust row whose key metrics are a P/E only. Section 41 is a trust row that shows a yield and a P/E while discount, premium, and P/B are missing. `ATT.L` stores a discount, a P/B, and a P/E while the yield key is missing. A premium counts as well as a discount. `EWI.L` stores a premium, a P/B, and a P/E while the yield key is missing.

**Where.** There is no `docs/data/research/ATT.L` folder. There is no `ATT.L` price in the 25 history runs. It is on the trust screen. Discount is 7.6%, P/B is 0.92, and P/E is 2.2. The yield key is missing. ROE is missing. Metrics present are 10 of 11. The free-cash-flow object is missing. `screening_inputs` is empty, so `dividend_yield_raw` is missing. `EWI.L` is on the trust screen. Premium is 17.1%, P/B is 1.17, and P/E is 4.0. The yield key is missing. Metrics present are 10 of 11. There is no free-cash-flow figure and no 11 Oct price. A statement revenue line is stored, from −541.2 million to 180.4 million. There is no operating-income line.

**What to change.** Do not fold `ATT.L` or `EWI.L` into section 35 or section 41. Do not invent a yield. Do not invent a dividend. For `EWI.L`, do not invent an operating-income line, and do not invent a cause.

## 50. An annual statement with revenue can sit on the trust screen

**What is wrong.** `BYG.L`, `DLN.L`, and `EMG.L` have an annual statement with revenue, and the screen row is on the trust list. The row stores a discount or a premium. A premium counts as well as a discount. There is no free-cash-flow figure, no quote file, and no 11 Oct price. Section 35 is a P/E only. Section 41 stores a yield and a P/E while discount, premium, and P/B are missing. Section 49 stores a discount or a premium, a P/B, and a P/E while the yield key is missing.

**Where.** `BYG.L`. Discount is 39.7%, P/B is 0.60, yield is 5.8%, and P/E is 12.7. Metrics present are 11 of 11. There is no ROE key and no free-cash-flow figure. There is no quote file and no 11 Oct price. Revenue is stored, from 188.8 million to 209.1 million. `DLN.L`. Discount is 43.8%, P/B is 0.56, yield is 4.7%, and P/E is 41.0. Metrics present are 11 of 11. There is no ROE key and no free-cash-flow figure. There is no quote file and no 11 Oct price. Revenue is stored, from 249.3 million to 388.7 million. `EMG.L`. Premium is 213.7%, P/B is 3.14, yield is 3.7%, and P/E is 16.2. Metrics present are 11 of 11. There is no free-cash-flow figure, no quote file, and no 11 Oct price. Revenue is stored: 1,732.0 million, 1,168.0 million, 1,434.0 million, and 1,405.0 million.

**What to change.** Do not treat these rows as a trust screen with no statement. Do not invent a free-cash-flow figure or an 11 Oct price. Do not fold `BYG.L`, `DLN.L`, or `EMG.L` into section 35, section 41, or section 49. Do not invent a cause.

## 51. Net income and normalized income in the same year can be stored at different magnitudes

**What is wrong.** `FRAS.L`, `GDWN.L`, and `HAS.L` store net income and normalized income for the same year at different magnitudes. Section 45 records unusual-item fields that disagree with each other. It does not cover these pairs.

**Where.** On `FRAS.L` in 2026, net income is 375.0 million and normalized income is 192,273,600. Total Unusual Items and Total Unusual Items Excluding Goodwill are 223.7 million, and Special Income Charges is −51.0 million. On `GDWN.L` in 2026, net income is 55,454,000 and normalized income is 4,768,754.87. Total Unusual Items and Total Unusual Items Excluding Goodwill are 993,000. Special income charges are missing. On `HAS.L` in 2026, net income is −58.2 million and normalized income is −21,150,000.

**What to change.** Do not convert either number. Do not fold `FRAS.L`, `GDWN.L`, or `HAS.L` into section 45. Do not invent a cause.

## 52. A positive screen P/E can sit beside a negative diluted EPS

**What is wrong.** Section 47 is a positive diluted EPS while the screen has no P/E key. `HBR.L`, `ELM.L`, and `ICGT.L` store a positive screen P/E beside a negative diluted EPS.

**Where.** `HBR.L` screen P/E is 23.4 beside diluted EPS of −0.16. `ELM.L` screen P/E is 20.2 beside diluted EPS of −0.078. `ICGT.L` screen P/E is 20.4 beside diluted EPS of −0.1335.

**What to change.** Do not fold `HBR.L`, `ELM.L`, or `ICGT.L` into section 47. Do not invent a corrected multiple.

## 53. A quote currency other than sterling can sit beside a chart labeled GBP

**What is wrong.** On `IHG.L` the quote currency is USD and the chart labels the same price GBP. The same shape exists for EUR. On `MTLN.L` and `BCG.L` the quote currency is EUR and the chart labels the price GBP. On `CPG.L` the quote currency is USD and the chart labels the price GBP. The rule is a quote currency other than sterling. Section 33 records that the IHG history file does not name the unit as pence. Section 39 records that the Metlen history file does not name the unit as pence. Neither records this quote-and-chart pair.

**Where.** `IHG.L`. The history price and the chart price are 159.05. The quote currency is USD. The heading cap is $23,953.8M. `MTLN.L`. The 11 Oct price is 48.76. The quote currency is EUR. The chart labels that price GBP. The heading cap is €6,973.8M. `BCG.L`. The stored 11 Oct price is 2.3519999980926514. The quote currency is EUR. The chart labels that price GBP. `CPG.L`. The stored 11 Oct price is 31.200000762939453. The quote currency is USD. The chart labels that price GBP.

**What to change.** Do not fold `IHG.L` or `CPG.L` into section 33. Do not fold `MTLN.L` into section 39. Do not fold `BCG.L` into section 31. Do not tidy 2.3519999980926514 or 31.200000762939453 into a different number. Do not invent a converted price or cap.

## 54. Net income and normalized income in the same year can have opposite signs

**What is wrong.** `HTG.L` and `IHP.L` store net income and normalized income for the same year with opposite signs. Section 51 records those two figures at different magnitudes. It does not cover opposite signs. Section 52 is a positive screen P/E beside a negative diluted EPS.

**Where.** On `HTG.L` in 2024, net income is −28,000,000 beside normalized income of 163,537,313.43. On `IHP.L` in 2025, net income is 51,300,000 beside normalized income of −1,981,350,000.

**What to change.** Do not convert either number. Do not fold `HTG.L` or `IHP.L` into section 51 or section 52. Do not invent a corrected figure.

## 55. A screen P/E can be stored when the latest income year has no diluted EPS line

**What is wrong.** `LRE.L`, `LWDB.L`, `INPP.L`, and `JEDT.L` store a screen P/E when the latest income year has revenue and net income and no diluted EPS line. Section 47 is a positive diluted EPS while the screen has no P/E key. Section 52 is a positive screen P/E beside a negative diluted EPS.

**Where.** On `LRE.L` the 2025 income statement has revenue and net income and no diluted EPS line. The screen P/E is 6.7. On `LWDB.L` the 2025 income statement has revenue and net income and no diluted EPS line. The screen P/E is 5.3. On `INPP.L` the 2025 income statement has revenue and net income and no diluted EPS line. The screen P/E is 10.4. On `JEDT.L` the 2026 income statement has revenue and net income and no diluted EPS line. The screen P/E is 5.3.

**What to change.** Do not invent a diluted EPS for that year. Do not invent a corrected P/E. Do not invent any other figure. Do not fold `LRE.L`, `LWDB.L`, `INPP.L`, or `JEDT.L` into section 47 or section 52.

## 56. One diluted-EPS year can sit on a different scale from the other stored years

**What is wrong.** On `OCI.L` and `OXB.L` one diluted-EPS year is on a different scale from the other stored years, while net income stays on one scale. Section 51 records net income and normalized income at different magnitudes. It does not cover this EPS scale.

**Where.** On `OCI.L` the 2023 diluted EPS is 0.0027 beside 1.26, 0.15 and 0.34. The 2023 net income is 47,488,000. On `OXB.L` the 2024 diluted EPS is −41.75 beside −0.4129, −1.6311 and −0.2692. The 2024 net income is −43,190,000.

**What to change.** Do not fold `OCI.L` or `OXB.L` into section 51. Do not invent a corrected earnings figure.

## 57. An 11 Oct history price and a chart labeled GBP can have no quote file

**What is wrong.** `GSK.L`, `REL.L`, `HLN.L`, `FRES.L`, `SGE.L`, `SN.L`, `RTO.L`, `CCC.L`, `ABDN.L`, and `BBY.L` each have an 11 Oct history price and a chart labeled GBP. None of the ten has a `price_quote.json`, so the heading cap is missing. Section 53 records a quote currency other than sterling beside a chart labeled GBP. That section assumes a quote file exists.

**Where.** The closer-look note for those ten names. Each stores an 11 Oct history price. The chart labels that price GBP. There is no quote file. The heading cap is missing.

**What to change.** Do not fold these ten into section 53. Do not invent a quote or a cap.

## 58. screen_ttm can differ from filing_aligned while the divergence flag is false

**What is wrong.** On `FRES.L`, `CCC.L`, `PAF.L`, `KLR.L`, `CURY.L`, and `DSCV.L`, `screen_ttm` differs from `filing_aligned`, `fcf_divergence_flagged` is false, and `filing_aligned` equals the statement line. Section 12 is the arm where `filing_aligned` equals the screen TTM and differs from the statement. `REL.L` is that arm.

**Where.** On `FRES.L`, `screen_ttm` is 1,999,836,928 beside `filing_aligned` of 1,889,566,000. `fcf_divergence_flagged` is false. `filing_aligned` equals the statement line. On `CCC.L`, `screen_ttm` is 287,937,504 beside `filing_aligned` of 257,600,000. `fcf_divergence_flagged` is false. `filing_aligned` equals the statement line. On `PAF.L`, `screen_ttm` is 327,180,512 beside `filing_aligned` of 340,848,000. `fcf_divergence_flagged` is false. `filing_aligned` equals the statement line. On `KLR.L`, `screen_ttm` is 189,575,008 beside `filing_aligned` of 168,000,000. `fcf_divergence_flagged` is false. `filing_aligned` equals the statement line. On `CURY.L`, `screen_ttm` is 321,249,984 beside `filing_aligned` of 346 million. `fcf_divergence_flagged` is false. `filing_aligned` equals the statement line. On `DSCV.L`, `screen_ttm` is 39,337,500 beside `filing_aligned` of 38.7 million. `fcf_divergence_flagged` is false. `filing_aligned` equals the statement line.

**What to change.** Do not fold `FRES.L`, `CCC.L`, `PAF.L`, `KLR.L`, `CURY.L`, or `DSCV.L` into section 12. Leave `REL.L` in that arm. Do not invent a corrected free-cash-flow figure.

## 59. Cash-flow metrics can store no free-cash-flow TTM beside an annual line

**What is wrong.** On `ATYM.L` and `GRG.L` the cash-flow metrics store no free-cash-flow TTM beside an annual free-cash-flow line. Section 19 records that Greggs has no statement TTM and the screen still stores one. Section 22 records that Atalaya has no statement TTM and an empty quarterly file. Neither records this cash-flow-metrics gap.

**Where.** On `ATYM.L` the cash-flow metrics store no free-cash-flow TTM. The latest annual free-cash-flow line is 110,835,000. On `GRG.L` the cash-flow metrics store no free-cash-flow TTM beside an annual free-cash-flow line.

**What to change.** Do not fold `ATYM.L` into section 22 or `GRG.L` into section 19. Do not invent a corrected free-cash-flow figure.

## 60. The screen free-cash-flow currency can be other than sterling while the chart labels the price GBP

**What is wrong.** On `ATYM.L`, `TRST.L`, and `HIK.L` the screen free-cash-flow currency is not GBP, the chart labels the price GBP, and there is no quote file. Section 53 records a quote currency other than sterling and assumes a quote file exists. Section 57 records a missing quote file and a missing heading cap. It does not record the free-cash-flow currency.

**Where.** On `ATYM.L` the screen labels free cash flow EUR. The chart labels the price GBP. There is no quote file. On `TRST.L` the screen labels free cash flow USD. The chart labels the price GBP. There is no quote file. On `HIK.L` the screen free-cash-flow currency is USD. The chart labels the price GBP. There is no quote file.

**What to change.** Do not fold `ATYM.L`, `TRST.L`, or `HIK.L` into section 53 or section 57. Do not invent a quote, a cap, or a corrected figure.

## 61. The screen free-cash-flow object can store no figure beside a statement line

**What is wrong.** The screen free-cash-flow object stores no figure beside a statement free-cash-flow line. `CMCX.L` stores that statement line and no screen figure. `ICG.L` is the earlier example: operating cash flow is stored and the screen has no free-cash-flow figure. Section 37 covers a stored free-cash-flow figure while the operating-cash-flow line is missing. It does not cover this.

**Where.** On `CMCX.L` the statement free cash flow is 35,980,000. The screen free-cash-flow object stores no figure. On `ICG.L` operating cash flow is 846.1 million. The screen stores no free-cash-flow figure.

**What to change.** Do not fold `CMCX.L` or `ICG.L` into section 37. Leave `ICG.L` in section 29. Do not invent a figure.

## 62. A later income year can store no revenue line

**What is wrong.** On `FAN.L` and `KIE.L` a later income year stores no revenue line. Section 15 records a later year that has only EPS and share counts for `BWY.L` and `GNS.L`.

**Where.** `docs/data/research/FAN.L/sources/financials_annual.json`. The 2025 income year stores diluted average shares and no revenue line. The 2024 income year stores Total Revenue. `docs/data/research/KIE.L/sources/financials_annual.json`. The 2025 income year stores diluted EPS of 0.121 and no revenue line. The 2026 income year stores diluted EPS of 0.135 and no revenue line. The 2024 income year stores Total Revenue.

**What to change.** Do not fold `FAN.L` or `KIE.L` into section 15. Do not invent a revenue figure for 2025 or 2026.
