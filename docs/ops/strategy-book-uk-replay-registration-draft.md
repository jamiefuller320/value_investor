# Strategy book UK/Europe point-in-time replay registration

**Status: SEALED 2026-11-12. The owner accepted every section 12 default ("Happy to accept the defaults for the seal"), with the two changes the owner approved the same day and listed under Owner sign-off. No development score exists.**  
**registration_id:** `strategy-book-uk-replay-v0`  
**Parent:** `owner-strategy-book-v0` in [`strategy-book-registration.md`](strategy-book-registration.md), signed 2026-11-05  
**Plan step:** 3.3 in [`strategy-reorientation-plan.md`](strategy-reorientation-plan.md)  
**Design:** [`strategy-book-uk-replay-design.md`](strategy-book-uk-replay-design.md)  
**Human checklist:** `adhoc-strategy-uk-replay-reveal` in [`human-tasks-checklist.md`](human-tasks-checklist.md#ad-hoc-when-triggered)  
**Seal file:** `docs/data/strategy_book_uk_replay_registration.json` (sha256 of this file, owner stamp). The file keeps its `-draft` name because the runner reads that path.

## Owner sign-off

Two stamps. The registration seal is given (2026-11-12); the reveal stamp is not.

Changes from the proposed text, approved by the owner on 2026-11-12 before any replay call:

- **Companies House scope (question 5).** The owner approved extending Companies House statements to FTSE 350 leavers 2013–2025 (L716) for this replay. The fallback reads every name in `docs/data/ch_failed_name_statements.json` as committed at the commit the development run records, not only the seven probe names. A name is used only when its Companies House record names the same listed company as the EODHD symbol (EPIC and leaving date consistent); otherwise it is not matched. The store is frozen from the development run to the reveal.
- **Last call day.** The subscription began on or before 2026-11-12. The last call day is **2026-12-10**, two days inside one calendar month.

1. **Registration seal.** Sign this draft, or change a proposed number once, before any replay call to EODHD. Target **2026-11-18**. The coverage check already run (564 calls on 2026-11-12) is not a replay call.
2. **Reveal.** After the development block is committed, authorise the single holdout write. Target **2026-12-03**. The review changes no registered number. A bug fix is an amendment under section 9, and development is recomputed before the reveal.

`strategy-book-uk-replay-v0` is an observe instrument. `influences_live` is false. It does not write strand A, `buy_tier_level`, knobs, `decision-review --apply`, `strategy_book_observe.json`, or `strategy_book_replay.json`.

The signed parent is the rule book. Where this file copies a parent number, the status column says `signed parent`. UK-only choices say `proposed` and freeze under section 9. Gate thresholds stamped from the modules say `stamped`. If the walker and the signed parent text ever differ, the signed parent text wins.

No language model chooses an entry, an exit, or a review.

## 1. Question and status

On a survivorship-free LSE tape, plus XETRA and Paris when section 8 says they were fetched, with the signed entry, the signed checkpoint ladder, and the mappings in sections 3 and 4, do the mature holdout episodes show a positive median fair-cost return and a positive median matched excess over holding that market's buy tier for the same dates?

The US rehearsal (`strategy-book-us-rehearsal-v0`, revealed 2026-11-07) is the comparison, not an input. Its confirmation median matched excess was −0.10% on 4,113 mature episodes (96⅔% interval −0.55% to +0.23%), verdict `inconclusive`. Development was −0.11% on 3,802 mature episodes. Section 6 says what a pass, a null, and a negative result mean for the version review.

**What a result is.** Evidence about the method, from UK names, and from XETRA and Paris names when those markets were fetched. The holdout includes the 2020 and 2022 falls. It does not include 2008. The holdout verdict is the only pass or fail this registration issues.

**What a result is not.**

| Claim | Status of this replay |
|---|---|
| A pass of parent section 1 | Out of scope. Parent section 1 is the forward book. |
| The thickness gate (48 counted mature episodes, 6 per entry week) | Out of scope. These episodes never enter that count. |
| Plan step 3.2 as a live-capital decision, or step 5.5 | Out of scope. The step 3.2 numbers are dirty flags in section 6. They do not open capital. |
| A promotion or a retirement on the forward bench | Out of scope. Section 6 says what the version review is to read. |
| A reveal of hsr-v2, hsr-mid-v2, hrs-v2, or hms-v2 | Forbidden. |
| An average with the US rehearsal or with the two-year archive replay | Forbidden. The three results stay separate. |

## 2. Universe

One pooled book. Per-market boards are report-only. A name that qualifies in two markets on the same session is an `ftse350` episode and is dropped from the others. Scratch count `overlap_excluded`. The committed store keeps the count and no tickers.

| Item | Value | Status |
|---|---|---|
| Book | One pooled book. The cap, the one-open-episode rule, and the primary median cross the markets that were fetched. | Signed parent section 6, with these markets in place of the forward markets. |
| `ftse350` members | LSE common stocks, active and delisted, excluding funds and investment trusts, market-cap ranks 1–350 (1 = largest) at the month-end on or before the session. | Proposed. `universe_basis` `lse_operating_cap_rank_1_350`. |
| `dax` members | XETRA common stocks, same filters, ranks 1–40. | Proposed. Included only when the day-2 fetch finishes by 2026-11-24. |
| `cac40` members | PA (Paris) common stocks, same filters, ranks 1–40. | Proposed. Same condition as `dax`. |
| Rank currency | LSE in GBP. XETRA and PA in EUR. | Proposed. |
| Timing | The month-end rank set is carried until the next month-end. A panel row dated *D* applies to sessions strictly after *D*. | Proposed. Same carry as the US `sp400` rule. |
| Month-end | The last session of the calendar month on that exchange: a date with at least one raw close. | Proposed. |
| Tie break | Symbol code ascending. The cut is one name. Count `cap_tie_broken_by_symbol`. | Proposed. |
| Symbol list | `exchange-symbol-list/{exchange}` with `type=common_stock`, and the same call with `delisted=1`. | Proposed. |
| LSE list size | 3,794 active and 2,884 delisted, measured 2026-11-12. The fetch uses the lists returned on the replay day. | Measured. |
| Listed that month | A delisted symbol is eligible to rank on sessions on or before its last EOD date. | Proposed. |
| Leaving the rank | Stops a new entry. An open episode stays open until its own exit. | Signed parent. |
| Cap not computable | Excluded from that month's rank. Counted. Not filled from the previous month. Not ranked as zero. | Proposed. Fail closed. |
| `FTSE_RANK_COUNT` | 350 | Proposed. |
| `DAX_RANK_COUNT` | 40 | Proposed. |
| `CAC_RANK_COUNT` | 40 | Proposed. |

**Market cap.** Raw `close` on the session × shares × FX into the rank currency. `adjusted_close` is not used for the cap.

**Shares.** Latest `outstandingShares` row with `dateFormatted` on or before the session and `shares` > 0. Quarterly preferred over annual when both qualify; the later `dateFormatted` wins. A bare year or quarter in `date` is ignored. Field name `SHARES_DATE_FIELD` = `dateFormatted`.

**Splits.** `splits/{symbol}` rows with `split` parsed as `new/old`. A split dated after the shares `dateFormatted` and on or before the session scales the shares by `new/old`. A split in that window that does not parse makes the cap not computable for that month. Count `split_unparsed`. No single-number split is applied.

**Pence.** The listing unit is `General.CurrencyCode`. `GBX`/`GBp` closes divide by 100 into GBP before the cap; `GBP` is used as is; a missing or unrecognised code is not computable. A cap above GBP 500bn or below GBP 1m is not computable (`cap_unit_implausible`, counted). Episode returns are ratios, so the unit does not enter them.

**FX.** `EURGBP.FOREX` close is GBP per 1 EUR. `USDGBP.FOREX` close is GBP per 1 USD. USD into EUR is USDGBP / EURGBP. The first 2024 session of EURGBP must lie in [0.70, 0.95] and USDGBP in [0.65, 0.90], or the job stops. Pairs are not inverted in code. Any other listing currency is not computable that month.

**Funds, trusts, and non-common stock.** Drop `General.Type` when it is present and is not `Common Stock`. Drop a name `classify_fund_or_trust` marks from `General.Name`, `General.Sector`, `General.Industry`, and `General.Type`. REIT names and the real-estate sector stay in. The live override file is not applied. Counts: `excluded_not_common`, `excluded_fund_or_trust`.

## 3. How each part of the entry rule is read

Eligibility and the price rule are both required. One failure, or a missing input the mapped check needs, means the name is not eligible. `insufficient_data` is not a pass.

### 3.1 Part 1 — the value set

The month-end panel feeds the existing screen. Pass is raw `signal` `buy` or `strong_buy` (`BUY_SIGNALS`). The screen is not re-specified. A null column means the model that needs it does not pass.

`assign_signal` thresholds, copied from `signals.py`:

| Item | Value | Status |
|---|---|---|
| Strong-buy pass count | `max(5, floor(0.35 × model_count))` | Stamped. |
| Buy pass count | `max(3, floor(0.22 × model_count))` | Stamped. |
| Strong-buy blended composite | ≥ 0.70 | Stamped. |
| Buy blended composite | ≥ 0.55 | Stamped. |
| Strong-buy families | ≥ `max(2, min(3, family_count))`, which is 3 for the five families | Stamped. |
| Buy families | ≥ `max(1, min(2, family_count))`, which is 2 | Stamped. |
| Hold | Pass rate ≥ 0.15 or blended composite ≥ 0.45, when the buy tests fail | Stamped. |
| `MIN_QUALITY_FOR_ANALYSIS` | 0.50 | Stamped. |
| `MIN_QUALITY_FOR_BUY` | 0.50 | Stamped. |
| `MIN_QUALITY_FOR_STRONG_BUY` | 0.65 | Stamped. |
| Risk veto | Strong buy falls to buy when the risk family fails or its mean score is below 0.55. Buy falls to hold when the risk mean is below 0.35 or the risk family fails. | Stamped. |
| `data_quality_score` | 1 when `market_cap`, `total_revenue`, and `net_income` are all present, else 0. `data_quality_basis` `three_fields`. | Proposed. |
| Thesis `avoid` | Two consecutive month-end rows with `signal` `avoid`. `DEFAULT_EXIT_CONFIRM_SCREENS` 2. | Stamped. |
| `adjusted_signal` | Absent. Cash-flow agreement board is `missing`. `fcf_agrees` is not a test. | Proposed. Same label as the US rehearsal. |

Panel columns, from the latest visible annual statement (section 3.2) and the session's raw close. `statement_basis` is `eodhd_annual`.

| Column | Source | Null when |
|---|---|---|
| `market_cap` | Section 2 | Cap not computable. |
| `last_price` | Raw `close` | No raw close. |
| `total_revenue` | `Income_Statement.yearly.totalRevenue` | Key missing. |
| `ebit` | `ebit`, else `operatingIncome` | Both missing. |
| `ebitda` | `ebitda` | Key missing. |
| `net_income` | `netIncomeApplicableToCommonShares`, else `netIncome` | Both missing. |
| `interest_expense` | `interestExpense` | Key missing. |
| `gross_margin` | `grossProfit / totalRevenue` | Either missing or revenue ≤ 0. |
| `free_cashflow` | `freeCashFlow` when numeric. Else operating cash flow + `capitalExpenditures` only if capex ≤ 0. | Otherwise. A positive capex is not sign-flipped. |
| `operating_cashflow` | `totalCashFromOperatingActivities` | Key missing. |
| `total_assets` | `totalAssets` | Key missing. |
| `total_current_assets` | `totalCurrentAssets` | Key missing. |
| `total_liabilities` | `totalLiab` | Key missing. |
| `total_current_liabilities` | `totalCurrentLiabilities` | Key missing. |
| `total_debt` | `shortLongTermDebtTotal`, else short-term debt + long-term debt | Those keys missing. |
| `total_cash` | `cashAndShortTermInvestments`, else `cash` | Both missing. |
| `book_value` | `totalStockholderEquity` | Key missing. Equity ≤ 0 leaves price to book null. |
| `shares_outstanding` | `commonStockSharesOutstanding`, else the cap's shares row | Both missing. |
| `trailing_pe` | `market_cap / net_income` | Net income ≤ 0 or cap null. |
| `price_to_book` | `market_cap / equity` | Equity ≤ 0 or cap null. |
| `enterprise_value` | Cap + debt − cash | Cap, debt, or cash null. Debt and cash are not filled with zero. |
| `dividend_yield` | Sum of `div/{symbol}` cash dividends with ex-date in (session − 365 days, session], divided by raw close | No raw close, or no dated dividend rows. Absence does not invent a zero yield. |
| `current_ratio` | Current assets / current liabilities | Denominator ≤ 0 or either null. |
| `debt_to_equity` | `total_debt / equity × 100` | Equity ≤ 0 or debt null. The ×100 matches the Sharadar panel. |
| `return_on_equity` | `net_income / equity` | Equity ≤ 0. |
| `return_on_assets` | `net_income / total_assets` | Assets ≤ 0. |
| `profit_margins` | `net_income / total_revenue` | Revenue ≤ 0. |
| `revenue_growth`, `earnings_growth` | This year / prior year − 1 | Prior ≤ 0, or either year not visible. |
| `ncav` | Current assets − total liabilities | Either null. |
| Prior-year ratios the screen models read (`return_on_assets_prev`, `gross_margin_prev`, `current_ratio_bs_prev`, `leverage_prev`, `asset_turnover_prev`, `shares_outstanding_prev`, `total_assets_prev`) | The prior visible fiscal year, same formulas | That year not visible. |
| `sector` | `General.Sector`, else `General.GicSector` | `sector_missing`. Not eligible. |
| `name` | `General.Name` | Used for the fund rule. Not committed. |

`Highlights` are not read. They are a current snapshot.

### 3.2 Part 2 — the decline gate

Verdict: any hard reason → `declining`; two soft reasons → `declining`; else `insufficient_data` when annual revenue is not evaluable or neither margin nor an EPS check is evaluable; else `clear`. `SOFT_SIGNALS_TO_DECLINE` = 2.

**Availability.** `filing_date` when it parses. Otherwise period end + `STATEMENT_LAG_DAYS` **180** (annual) or period end + `INTERIM_STATEMENT_LAG_DAYS` **90** (quarterly). Visible when the session is at least `FILING_LAG_DAYS` **2** after that date. Stale when the period end is more than `STALE_FILING_DAYS` **456** before the session.

A comparative column inside a visible statement may fill a year with no primary row. Label `source=comparative`. Visible on the containing statement's date. A missing year is not carried forward.

| Check | Reading | Constant | Kind | Status |
|---|---|---|---|---|
| `revenue` | This fiscal year vs the prior fiscal year. Prior revenue > 0. | `REVENUE_DROP_PCT` 0.05 | Hard | Stamped. |
| `revenue_two_year_decline` | This change and the prior change both below −1%. | `REVENUE_FLAT_TOLERANCE_PCT` 0.01 | Hard | Stamped. |
| `interim_revenue` | Quarterly `totalRevenue` vs the quarter within 45 days of one year earlier. Age ≤ 460 days. | `INTERIM_YOY_WINDOW_DAYS` 45, `INTERIM_MAX_AGE_DAYS` 460, drop `INTERIM_REVENUE_DROP_PCT` 0.05 | Hard | Stamped. |
| `operating_margin` | `operatingIncome / totalRevenue`, else `ebit / totalRevenue`. Same pair both years. | `MARGIN_DROP_PP` 0.03 | Hard | Stamped. |
| `eps_annual` | `Earnings.Annual.epsActual`, visible only with the matching income statement. Else net income / shares. | `EPS_ANNUAL_DROP_PCT` 0.20. Prior > 0 and latest < prior × 0.80. | Soft | Stamped threshold. Proposed EPS source. |
| `eps_interim` | `Earnings.History.epsActual` on `reportDate`, else `date`. Same 45-day and 460-day rules. | `EPS_INTERIM_DROP_PCT` 0.10 | Soft | Stamped threshold. Proposed source. |
| `fcf` | Section 3.1 free cash flow vs the prior year. | Hard `fcf_turned_negative` when prior > 0 and latest < 0. Soft `fcf_sharp_fall` when latest < prior × 0.50. `FCF_SHARP_FALL_PCT` 0.50. | Hard or soft | Stamped. |
| `dividend` | Live boolean `interim_dividend_cut_flagged`. | Does not fire. | Soft | Proposed. No DPS cut rule. |
| `profit_warning`, `impairment_or_downgrade` | Live headline scan. | Do not fire. | Hard or soft | Proposed. |

EPS pair rule: both years share `eps_basis` (`vendor_eps`, `net_income_over_shares`, or `companies_house_basic`), or the check is not evaluable. Count `eps_basis_mismatch`.

**Companies House fallback.** Read `docs/data/ch_failed_name_statements.json` for every name it holds at the development commit (see Owner sign-off). Use a year only when EODHD has no annual income row for that fiscal year. One source for the whole year. Availability is the Companies House filing date, plus the 2-day lag. Mapping: revenue → `total_revenue`; statutory operating profit → operating income; profit attributable to owners → `net_income`; basic EPS → EPS with basis `companies_house_basic`; weighted-average basic shares → shares; net cash from operating activities → `operating_cashflow`; capital expenditure is a positive purchase, so FCF = operating cash flow − purchase. A negative purchase leaves FCF null. Balance-sheet fields stay null. Dividends per share stay absent.

Probe facts already measured, and pre-registered so the reveal does not rediscover them: EODHD statements from 2013 on 3 of 11; with Companies House, 8 of 11 have a 2013 first year; 4 of 11 have a statement every year to the event (Carillion, Patisserie Holdings, Aggreko, Morrison). Patisserie's 2013 EPS is a comparative in the report filed 2015-03-18.

`revenue_growing` keeps a positive mapped revenue `change_pct`. A revenue check that is not evaluable is not kept.

### 3.3 Part 3 — the sector gate

`sector_label_basis` = `eodhd_general_current`. One label per symbol, on every date. Markets are scored apart. No regional pool.

| Input | Value | Status |
|---|---|---|
| Breadth | Share of members whose adjusted close is below the mean of their last 200 adjusted closes. A member needs 200 bars to count. | Stamped. `PRICE_BREADTH_HEADWIND` 0.65. |
| Trend | Equal-weight mean of adjusted close[*t*] / adjusted close[*t*−126] − 1. | Stamped. `RETURN_LOOKBACK_126D` 126. `SECTOR_RETURN_126D_HEADWIND` −0.10. |
| Coverage | At least 4 members and 60% of the sector, separately for breadth, trend, and decline breadth. | Stamped. `MIN_MEMBERS_WITH_DATA` 4. `MIN_COVERAGE_SHARE` 0.60. |
| Price headwind | Breadth and trend both in headwind, both coverages met. | Stamped. |
| Decline breadth | Share of operating members with a part 2 verdict whose verdict is `declining`. | Stamped threshold `EARNINGS_BREADTH_HEADWIND` 0.50. Proposed source: part 2 only. |
| Earnings-growth fallback | Not used. | Proposed. |
| Headwind | Price trigger, or decline coverage met and decline breadth ≥ 0.50. | Proposed combination. |
| Sound, both sides | Price coverage met, price trigger false, decline coverage met, decline breadth < 0.50. `sector_basis` `price_and_decline`. | Proposed. |
| Sound, price only | Price coverage met, price trigger false, decline coverage not met. `sector_basis` `price_only`. | Proposed. |
| Otherwise | `insufficient_data`. | Stamped outcome. |
| Missing label | `sector_missing`. Not eligible. | Stamped. |

`headwind` opens `sector_rejected_shadow`. `insufficient_data` is counted and not shadowed.

### 3.4 F9-B and research

| Column | Label on every episode | Effect | Status |
|---|---|---|---|
| F9-B | `f9_unverified` | Does not block an entry and does not sell. | Same label as the US rehearsal and the archive. |
| Research verdict | `absent` | Does not block. Is not a thesis break. At a review, the hold stands when the gates are `clear` and `sound` and the signal is not `avoid`. | Signed parent section 5, missing-verdict row. |
| Memo | `not_applicable` | `memo_not_ready` and `memo_blocked` are unused. | Proposed. |
| `adjusted_signal` | `absent` | Does not gate. | Proposed. |
| `t212_listed` | `not_applicable` | Tradable board is not computed. | Proposed. |
| `late_signal` | `not_applicable` | No decision clock. | Proposed. |
| `provenance_missing` | Not used. | Licensed inputs are deleted. | Proposed. |

### 3.5 What the walker applies unchanged

| Rule | Value | Status |
|---|---|---|
| RSI period, level | 14, below 35. Wilder `_rsi` on adjusted closes through *t*. | Signed parent. |
| Short-term low | Adjusted close equals the minimum of the 10 sessions ending at *t*. | Signed parent. `LOW_WINDOW_SESSIONS` 10. |
| Alternative | RSI below 40 and close at least 3% under SMA(10). Report-only. | Signed parent. `ALT_RSI_LEVEL` 40. `ALT_SMA_WINDOW` 10. `ALT_SMA_DISTANCE` 0.03. |
| Fill | Next session adjusted close. | Signed parent. |
| Fill gap | No fill when the next session is more than 5 calendar days after *t*, or *t* is the last bar. | Signed parent. `MAX_FILL_GAP_CALENDAR_DAYS` 5. |
| Launch | First close at or above the fill × 1.10. | Signed parent. `LAUNCH_RETURN` 0.10. |
| Checkpoints and floors | +10/+5, +15/+10, +20/+15, +25/+20, +30/+25, +40/+30, +50/+40, +75/+50, +100/+75. Above +100% the floor stays +75%. | Signed parent. |
| Fail to launch | Session index 63. Fill session is index 0. | Signed parent. `FAIL_TO_LAUNCH_INDEX` 63. |
| Time cap | Session index 252. | Signed parent. `TIME_CAP_INDEX` 252. |
| Reviews | Session indexes 63, 126, 189. | Signed parent. |
| Comparison exits | `draft_v0_exit`, `ladder_no_deadline`. Draft high window 10, swing limit index 15, review spacing 63, sale at review 4. | Signed parent. |
| Thesis confirm | 2 consecutive observations. | Stamped. `THESIS_CONFIRM_OBSERVATIONS` 2. |
| Recovery label | 8% under the fill. Sells nothing. | Signed parent. `RECOVERY_DROP` 0.08. |
| Cooldown | 10 sessions after the exit fill. | Signed parent. `COOLDOWN_SESSIONS` 10. |
| Stake | 100 units of the rank currency. | Signed parent fixed-stake rule. `STAKE_UNITS` 100. |
| Maturity | 63 sessions. | Signed parent. `MATURITY_SESSIONS` 63. |
| Shadows | `decline_rejected_shadow`, `sector_rejected_shadow`. | Signed parent. |
| Controls | Buy-on-signal, leave-tier. | Signed parent. |
| `deep_dip` | Close at least 8% below the close 20 sessions earlier. | Signed parent. `DEEP_DIP_LOOKBACK` 20. `DEEP_DIP_DROP` 0.08. |
| `revenue_growing` | Mapped revenue `change_pct` > 0. | Signed parent. |
| `trend_not_falling` | 6-month `channel_v0` direction `rising` or `sideways`. Direction needs R² ≥ 0.25; below that the channel is `sideways` and is kept. | Signed parent bench, 2026-11-10. |
| `fcf_agrees` | Not computed. Not a test. | Proposed. |
| Channels | `channel_columns` version `channel_v0`. | Signed parent. |
| `hl_basis` | `high_low` when the EOD export has `high` and `low`. `closes` when either is absent. `partial` when the recent window mixes them. High and low are scaled by `adjusted_close / close` when `close` > 0. | Proposed scaling. Same labels as the US rehearsal. |
| Regime | Half of the names with 200 bars above their 200-session average. Fewer than 5 names is `regime_unknown`. | Signed parent. `REGIME_SMA_SESSIONS` 200. `REGIME_ABOVE_SHARE` 0.5. `REGIME_MIN_NAMES` 5. |
| Chart check | More than 5% of successive gaps longer than 5 calendar days → `chart_not_daily`, not traded. | Signed parent. `CHART_NOT_DAILY_GAP_SHARE` 0.05. `CHART_NOT_DAILY_GAP_DAYS` 5. |
| Warm-up | Prices from 420 calendar days before 2013-01-01. EOD `from` = 2011-11-08. | Proposed. `WARMUP_CALENDAR_DAYS` 420. `EOD_FROM` 2011-11-08. |

## 4. Prices, fills, costs, and the matched basket

| Item | Value | Status |
|---|---|---|
| Return tape | EOD `adjusted_close`. Splits and dividends are in that series. | Proposed. Matches the parent's adjusted-close basis. |
| Cap tape | EOD raw `close`. | Proposed. |
| Session | A date present on that name's EOD rows. | Proposed. |
| Open | Unused. Fills stay at the next adjusted close. | Signed parent. |
| Decisions | One pass over one download. A closed return is the pair of adjusted closes from that download. | Signed parent section 7. |
| Delist, baseline | Symbol on the delisted list and prices ended: exit at the last adjusted close. Haircut 0. Label `delisted` when no exit was already signalled. | Proposed fill. `DELIST_HAIRCUT_BASELINE` 0. |
| Delist, sensitivity | Haircut −0.30 on `known_failure` and `unclassified`. Haircut 0 on `known_takeover`. | Proposed. `DELIST_HAIRCUT_SENSITIVITY` −0.30. |
| No delist flag and a hole | Episode stays open. A missing quote is blank, not zero. | Signed parent. |
| Delisted before the fill | No episode. Count `delisted_before_fill`. | Signed parent. |
| Known event vs last price | Last price more than 10 trading days before `known_end` increments `price_ended_before_known_event`. The exit price is still the last close. | Proposed. `TRADING_DAYS_TOLERANCE` 10, the coverage-check constant. |

**Probe classes, sealed with this draft.**

| Key | `known_end` | Class |
|---|---|---|
| `carillion` | 2018-01-15 | `known_failure` |
| `thomas_cook` | 2019-09-23 | `known_failure` |
| `debenhams` | 2019-04-09 | `known_failure` |
| `patisserie_holdings` | 2019-01-10 | `known_failure` |
| `intu` | 2020-06-26 | `known_failure` |
| `wirecard` | 2020-06-25 | `known_failure` |
| `sirius` | 2020-03-03 | `known_takeover` |
| `gkn` | 2018-03-29 | `known_takeover` |
| `sky` | 2018-09-26 | `known_takeover` |
| `aggreko` | 2021-08-16 | `known_takeover` |
| `morrison` | 2021-10-04 | `known_takeover` |

Every other delisting is `unclassified`.

**Costs.** Episode return is `exit_fill / entry_fill − 1 − buy − sell`.

| Market | Buy | Sell | Round trip | Status |
|---|---:|---:|---:|---|
| `ftse350` | 0.525% | 0.025% | 0.55% | Signed table. Stamp 0.50% on the buy, half-spread 0.025% each side, no FX. |
| `dax` | 0.175% | 0.175% | 0.35% | Signed table. FX 0.15% plus half-spread 0.025% each side. |
| `cac40` | 0.175% | 0.175% | 0.35% | Signed table. Same components as `dax`. |
| Stress | 3% per side | | | Stamped. `LEGACY_STRESS_TRADE_COST_PCT` 0.03. Report-only. |

**Matched basket.** Equal-weight gross adjusted-close return of every name in that episode's market whose raw panel `signal` was `buy` or `strong_buy` on the panel carried onto the signal session, the traded name included, from the fill session to the exit session. Matched excess is the episode's gross return minus that basket return. Costs cancel. Fewer than 5 priced names (`BASKET_MIN_NAMES` 5) uses that market's whole carried screen, and the episode records `basket_fallback`. A basket name that delists uses the haircut of the variant being scored. FX is not inside this figure.

**Sterling slot book.** Descriptive. 20 slots (`SLOT_COUNT`), ties by symbol, 15 orders (`SLOT_RANDOM_ORDERS`), seed `20261104` (`SLOT_BOOK_RANDOM_SEED`). LSE cash is already sterling. EUR cash converts at the `EURGBP.FOREX` close. A missing FX close may reuse the previous close for at most `FX_CARRY_DAYS` 5 calendar days. Beyond that the sterling book is `not_computed`.

## 5. Windows and bars

An episode belongs to the window of its signal session.

| Window | Signal sessions | Role | Status |
|---|---|---|---|
| Development | 2013-01-01 through 2018-12-31 | Descriptive. `DEVELOPMENT_START` 2013-01-01. `DEVELOPMENT_END` 2018-12-31. | Proposed. |
| Holdout | 2019-01-01 through 2025-09-30 | The one confirm-or-reject window. `HOLDOUT_START` 2019-01-01. `HOLDOUT_END` 2025-09-30. | Proposed. The end date matches the US confirmation end. |
| After 2025-09-30 | No new signal. | Fills and exits may use later prices through the download's last session. | Proposed. |
| First panel | Last LSE session of January 2013. | No entry before a prior panel row exists. | Proposed. |
| Tape start | 2013-01-01. | EODHD annual depth measured from 2013. | Proposed. `TAPE_START` 2013-01-01. |

Holdout halves, a condition on each bench candidate, not extra tests: 2019-01-01 through 2021-12-31, and 2022-01-01 through 2025-09-30.

The calendar overlaps the US confirmation window. These names were not in that window. The overlap is recorded. This is not a second US reveal.

**Family.** `FAMILY_ERROR` 0.10. `FAMILY_SIZE` **4**. Coverage `1 − 0.10 / 4` = **0.975**. Each tail is 0.0125. Resamples: `RESAMPLE_COUNT` 10,000 whole ISO entry weeks. The week vector is not committed.

| Test | Statistic | Status |
|---|---|---|
| Primary | Median matched excess of mature holdout episodes. | The one primary test. |
| `deep_dip` | Mean fair-cost of kept entries minus mean of all book entries. | One bench test. |
| `revenue_growing` | The same on its kept set. | One bench test. |
| `trend_not_falling` | The same on its kept set. | One bench test. |

Not tests: the fair-cost median (a companion; it can still force `fail`), per-market boards, both comparison exits, both shadows, both controls, the alternative entry, regime cuts, the 200-session regime split, the delisting sensitivity, the capital view, channel splits, selection fifths, the stress view, and every dirty flag in section 6.

## 6. Pre-registered outputs and verdicts

Development is committed before any holdout aggregate is written. The runner refuses a holdout aggregate until the reveal step.

### Development block

Counts, fair-cost median and mean, matched-excess median and mean, entry-week standard error, share above zero, uncorrected 90% interval labelled `development_descriptive`. Exit-reason counts. Selection fifths. The three candidates' descriptive differences. Comparison exits, shadows, controls, channels, regime, capital view, stress, per-market boards. The 2018 calendar cut (signal sessions 2018-01-01 through 2018-12-31). The development delisting sensitivity. The bias shares in section 7.

The 2020 and 2022 cuts are holdout outputs. They are not written in the development block.

### Verdicts, issued once at the reveal

| Verdict | When | What the version review is told |
|---|---|---|
| Primary `pass` | The 97.5% interval of median matched excess lies wholly above zero, and the fair-cost median is above zero. | The US tape was `inconclusive` at −0.10%. This tape cleared the bar. `clean_pass` is a separate flag. No promotion. Parent section 1 is not passed. |
| Primary `fail_excess` | That interval lies wholly below zero. | Evidence against the timing rule on this tape. The forward book still runs. Read this fail before promoting a filter that only reshapes the same entry. |
| Primary `fail_costs` | The fair-cost median is zero or below, and the excess interval is wholly above zero. | The timing excess cleared and the costs did not. |
| Primary `fail` | The interval is wholly below zero and the fair-cost median is zero or below. Stored as `fail_excess`. The costs fact is a flag on the same row. | Both failed. |
| Primary `inconclusive` | The interval covers zero, and the fair-cost median is above zero. | The same shape as the US result. No rule change. |
| Candidate `pass` | That candidate's 97.5% interval lies wholly above zero, and both holdout halves have a positive point estimate. | Method evidence for the filter. Promotion still needs the forward bar on forward episodes. |
| Candidate `fail` | The interval lies wholly below zero. | Method evidence against the filter. The slot stays until a version review. This replay does not retire it. |
| Candidate `inconclusive` | The interval covers zero, or the halves disagree in sign. | No bench consequence. |

`clean_pass` is true only for a primary `pass` with every flag below unset.

| Flag | Set when |
|---|---|
| `pass_delisting_sensitive` | The primary is `pass` on the baseline and is not `pass` under the −30% sensitivity. |
| `tail_breach` | 5th-percentile fair-cost return is below −20%. `TAIL_BAR` −0.20. |
| `drawdown_breach` | The 20-slot book's largest peak-to-trough fall is more than 1.5 times the matched basket's over the same dates. `DRAWDOWN_MULTIPLE` 1.5. |
| `single_market_dependence` | Median matched excess is above zero and is zero or below once the market with the most mature episodes is removed. |
| `regime_spread_miss` | Either regime half has median matched excess below zero, or either half has fewer than 12 mature episodes. `REGIME_HALF_MIN_MATURE` 12. `regime_unknown` sits out. |
| `sterling_slot_miss` | The sterling slot book's total return is zero or below, or it does not beat the matched basket in sterling. |
| `sterling_fx_missing` | The sterling book is `not_computed`. |

The Trading 212 bar is not computed.

### Regime cuts

Report-only. Signal-session cohorts.

| Cut | Signal sessions | When written |
|---|---|---|
| 2018 | 2018-01-01 through 2018-12-31 | Development |
| 2020 | 2020-01-01 through 2020-12-31 | Reveal |
| 2022 | 2022-01-01 through 2022-12-31 | Reveal |

### Delisting sensitivity

After the reveal, the holdout primary is scored again with the −30% rule in section 4. Not a second reveal and not a fifth test.

### Kept as description

The 5th percentile, the slot-book drawdown, and the month series. None is a family test.

## 7. What is kept

`docs/data/strategy_book_uk_replay.json` is the only results store, written by the later runner, not by this draft. Cells with fewer than `SMALL_CELL` **5** episodes publish the count and suppress returns.

| Field | Contents |
|---|---|
| `registration_id` | `strategy-book-uk-replay-v0` |
| `parent_registration_id` | `owner-strategy-book-v0` |
| `universe_basis` | `lse_operating_cap_rank_1_350`, and `xetra_operating_cap_rank_1_40` / `pa_operating_cap_rank_1_40` when fetched |
| `markets_scored` | The market ids actually walked. `europe_not_fetched` when XETRA or PA was dropped, with the symbol-list counts. |
| `statement_basis` | `eodhd_annual` |
| `family` | `m` = 4, coverage 0.975, the four test names |
| `development` | Section 6 development block |
| `holdout` | Null until the reveal |
| `reveal` | Null, or one `{at, evidence}` |
| `delisting_sensitivity` | Development copy, and the holdout copy after the reveal |
| `regime_cuts` | The three cuts, each in the block section 6 allows |
| `bias` | Universe-months; share whose annual revenue check is not evaluable, split `still_listed`, `later_delisted`, `list_unknown`; mean `cap_not_computable` share; mean `excluded_fund_or_trust` count; `delisted_exits` split `known_failure`, `known_takeover`, `unclassified` |
| `probe` | The 11 keys, each with booleans only: `in_universe`, `had_exit`, `statement_every_year`, `price_ended_before_known_event` |
| `month_series` | `month`, `episodes`, and the two medians when `episodes` ≥ 5 |
| `licensed_data` | `first_used_at`, `deleted_at` |
| `calls` | Weighted calls and HTTP requests per UTC day, no symbol list |
| `amendments` | Logged markers |

Inside a window block: the same aggregate groups as the US rehearsal store (counts, primary, companion fair-cost interval labelled descriptive, exit slices, paired columns, bench, selection fifths, channels, regime, capital view, tails, flags). Selection fifths store a fifth index, a count, and a median when the count is at least 5. No feature value that identifies a name.

Forbidden in the committed file: ticker (other than the 11 probe keys), name, a price, a fundamental, a dividend amount, a per-episode return, a per-week return vector, a panel row, a path under the job temp directory, and the API token.

## 8. Call budget and timetable

Personal subscription, ALL-IN-ONE, started 2026-11-12. The last call day is **2026-12-10** (`SUBSCRIPTION_START` 2026-11-12, `SUBSCRIPTION_END` 2026-12-10), earlier if the dashboard shows an earlier end. Token: GitHub secret `EODHD_API_TOKEN`. The token is not committed, logged, or pasted into a command line that lands in the repo.

| Constant | Value | Status |
|---|---|---|
| `DAILY_CALL_LIMIT` | 100,000 weighted calls | Vendor plan. |
| `DAILY_CALL_BUDGET_SOFT_CAP` | 90,000 | Proposed. |
| `FUNDAMENTALS_CALL_WEIGHT` | 10 | Vendor. Confirmed on the coverage check. |
| `EOD_CALL_WEIGHT`, `DIV_CALL_WEIGHT`, `SPLIT_CALL_WEIGHT`, `LIST_CALL_WEIGHT` | 1 each | Proposed planning weights. |
| `MAX_REQUESTS_PER_SEC` | 5 | Stamped from the coverage client. |
| `RESET_TIMEZONE` | UTC. No job runs across 00:00 UTC. | Proposed. |
| `BUDGET_PROBE_SYMBOLS` | 1, before the loop. Stop if fundamentals did not weigh 10 or dividends did not weigh 1. | Proposed. |

LSE weighted calls, using the 2026-11-12 list sizes:

`2 + 6,678 × (1 + 10 + 1 + 1) + 2` = **86,818**.

That is lists + EOD + fundamentals + dividends + splits + two FX series. Headroom to the soft cap is 3,182 calls. HTTP requests: 26,716. At 5 per second, about 90 minutes.

XETRA + PA: 4 list calls + 13 per name + 2 FX calls. One UTC day holds up to 6,922 names under the soft cap. The cursor carries the rest to the next UTC day.

The development job and the reveal job each fetch. Temp files die with the job. The resume cursor lives in the Actions cache for that UTC day and is not committed.

| Date | Step |
|---|---|
| By 2026-11-18 | Owner seal. No replay call before it. |
| 2026-11-19 | LSE fetch. |
| 2026-11-20 | Finish LSE if the soft cap stopped it. Otherwise start XETRA and PA. |
| 2026-11-21 through 2026-11-24 | Resume. A European fetch unfinished at the end of 2026-11-24 is `europe_not_fetched`. |
| 2026-11-25 | Development walk. Commit the development block. |
| 2026-11-26 through 2026-12-02 | Owner reads development. |
| 2026-12-03 | Owner reveal stamp, then one holdout write and the delisting sensitivity. The job fetches again. |
| 2026-12-04 through 2026-12-09 | Only an amendment the owner already allowed. |
| 2026-12-10 | Last call day. Delete temp files and the cursor cache. Stamp `deleted_at`. |

The implementation that runs this table is a later package. It is dispatch-only, writes the aggregate store, and adds an ops-monitor finding with `auto_fixable` false. It is not a daily cron.

## 9. Freeze and amendments

**Frozen when the owner seals this draft:** the question, the universe, the part-by-part reading, the price and cost basis, the windows, the family and its coverage, the verdicts, the dirty flags, the kept fields, the probe classes, and the call budget.

**One adjustment before the first development score.** The owner may change a proposed number once, in a note on the seal, before the results store contains a development block. The owner may not add a test, a price stop, or a further bench column in that note.

**After the first development score is committed:**

| Change | What happens |
|---|---|
| A bug fix that makes the runner match this text | A logged amendment on this same id. Development is recomputed only when the note says so. |
| An adapter fix discovered before the reveal | The same kind of amendment, logged before the reveal. |
| Any registered number, the family, the windows, or which column is a test | A new `registration_id`. |
| A second holdout look | Exploratory. Not evidence. |

## 10. Dependencies

The parent is already signed. Scoring waits on this draft's own seal, not on another signature. The download waits on the seal too: unlike the US month, the subscription here runs to 2026-12-10 and the fetch is repeatable inside the month, so there is no reason to fetch before the rules are frozen.

The later runner calls the strategy-book walker and the registered rules. It does not re-implement the entry, the ladder, the comparison exits, the shadows, or the bench. Companies House values come from the committed store, frozen at the development commit. This replay does not call Companies House.

## 11. Where EODHD does not have what the rules read

| Gap | What the rules ask for | Handling |
|---|---|---|
| No historical index membership | FTSE 350, DAX, and CAC members on each date | Cap ranks in section 2. |
| No filing date on a statement row | The date an investor could have read it | Period end + 180 days annual, + 90 days quarterly, then the 2-day lag. |
| `Highlights` market cap and ratios | A point-in-time cheap screen | Not read. Cap is close × dated shares. |
| Shares `date` is a bare year | A day-accurate share count | Ignore `date`. Require `dateFormatted`. |
| No Sharadar action table | Takeover versus failure | The 11 probe classes in section 4. Everyone else is `unclassified` and takes the −30% sensitivity. |
| No as-reported TTM dimension | The US `art_ttm` construction | Fiscal-year rows. `statement_basis` `eodhd_annual`. |
| No F9-B, memo, or research verdict | Parent sections 2 and 5 | Labels in section 3.4. |
| No `adjusted_signal` | `fcf_agrees` | Omitted. Not a test. |
| No historical sector label | Sector as of the session | `General.Sector` on every date. `eodhd_general_current`. |
| No headline feed | Profit-warning and impairment checks | Do not fire. |
| No dividend-cut boolean | The soft dividend check | Does not fire. Dividend amounts are used for yield only. |
| No historical Trading 212 catalogue | The tradable-subset bar | `t212_listed` `not_applicable`. |
| No FX inside matched excess | A sterling primary statistic | Matched excess stays in the listing currency. Sterling is the slot book only. |
| Companies House balance sheet absent | Enterprise value on a failed-name year | Those fields stay null. The cheapness models that need them do not pass. |
| Statements missing on failed names | A decline verdict | Fail closed. Report the still-listed vs later-delisted shares. Do not carry a year forward. |
| Official investment-trust constituents | A seat inside the real FTSE 350 | Trusts are excluded and counted. The basis name says operating companies. |

## 12. Open questions

Each default is what this draft seals if the owner signs it unchanged. A change is the one pre-score adjustment in section 9.

1. **Markets.** Default: LSE ranks 1–350 required; XETRA ranks 1–40 and PA ranks 1–40 if the fetch finishes by 2026-11-24, otherwise LSE only and `europe_not_fetched`.
2. **Trusts.** Default: drop funds and investment trusts before the rank. REITs stay. No live override file.
3. **Cap gaps.** Default: a month with no computable cap leaves the rank. No carry-forward of last month's cap.
4. **Statement lag.** Default: filing date when present; otherwise 180 days annual and 90 days quarterly; then 2 days. Stale at 456 days.
5. **Companies House.** Sealed: every name in the store at the development commit (owner change, 2026-11-12), whole year, only when EODHD has no income row for that year and the record matches the same listed company. Missing years fail closed.
6. **Sector sound.** Default: `price_only` may say sound when decline coverage fails. Decline breadth fires when coverage is met and the share declining is at least 50%.
7. **Dividend cut and headlines.** Default: those checks do not fire. Dividend history fills `dividend_yield` only.
8. **F9-B and `fcf_agrees`.** Default: `f9_unverified`, research `absent`, `fcf_agrees` omitted.
9. **Family.** Default: four tests, 97.5% intervals, including `trend_not_falling`.
10. **Windows.** Default: development 2013–2018, holdout 2019-01-01 through 2025-09-30, halves split at 2022-01-01.
11. **Dirty flags.** Default: tail −20%, drawdown 1.5×, market spread, regime spread (12 episodes), sterling slot book, and the delisting sensitivity block `clean_pass` and are not extra tests.
12. **Delistings.** Default: baseline haircut 0. Sensitivity −30% on failures and unclassified names. Takeovers in the probe table stay at 0.
13. **FX pairs.** Default: `EURGBP.FOREX` and `USDGBP.FOREX` with the section 2 bands. A close outside the band stops the job.
14. **Data quality.** Default: `three_fields`.
15. **Small cells.** Default: under 5 episodes, publish the count and suppress the return.
16. **Slot-book seed.** Default: `20261104`, 20 slots, 15 orders.
17. **Trading 212.** Default: `not_applicable`.
18. **Prices after 2025-09-30.** Default: allowed as fills and exits. No new signal after that date.

## Appendix: every constant

Proposed unless the status says otherwise.

| Name | Value | Status |
|---|---|---|
| `registration_id` | `strategy-book-uk-replay-v0` | Proposed |
| `FTSE_RANK_COUNT` | 350 | Proposed |
| `DAX_RANK_COUNT` | 40 | Proposed |
| `CAC_RANK_COUNT` | 40 | Proposed |
| `TAPE_START` | 2013-01-01 | Proposed |
| `DEVELOPMENT_START` | 2013-01-01 | Proposed |
| `DEVELOPMENT_END` | 2018-12-31 | Proposed |
| `HOLDOUT_START` | 2019-01-01 | Proposed |
| `HOLDOUT_END` | 2025-09-30 | Proposed |
| `HOLDOUT_HALF_SPLIT` | 2022-01-01 | Proposed |
| `WARMUP_CALENDAR_DAYS` | 420 | Proposed |
| `EOD_FROM` | 2011-11-08 | Proposed |
| `FILING_LAG_DAYS` | 2 | Proposed, matches US |
| `STATEMENT_LAG_DAYS` | 180 | Proposed |
| `INTERIM_STATEMENT_LAG_DAYS` | 90 | Proposed |
| `STALE_FILING_DAYS` | 456 | Proposed, matches US |
| `SHARES_DATE_FIELD` | `dateFormatted` | Proposed |
| `REVENUE_DROP_PCT` | 0.05 | Stamped |
| `REVENUE_FLAT_TOLERANCE_PCT` | 0.01 | Stamped |
| `MARGIN_DROP_PP` | 0.03 | Stamped |
| `EPS_ANNUAL_DROP_PCT` | 0.20 | Stamped |
| `EPS_INTERIM_DROP_PCT` | 0.10 | Stamped |
| `INTERIM_REVENUE_DROP_PCT` | 0.05 | Stamped |
| `INTERIM_YOY_WINDOW_DAYS` | 45 | Stamped |
| `INTERIM_MAX_AGE_DAYS` | 460 | Stamped |
| `FCF_SHARP_FALL_PCT` | 0.50 | Stamped |
| `SOFT_SIGNALS_TO_DECLINE` | 2 | Stamped |
| `MIN_MEMBERS_WITH_DATA` | 4 | Stamped |
| `MIN_COVERAGE_SHARE` | 0.60 | Stamped |
| `PRICE_BREADTH_HEADWIND` | 0.65 | Stamped |
| `SECTOR_RETURN_126D_HEADWIND` | −0.10 | Stamped |
| `RETURN_LOOKBACK_126D` | 126 | Stamped |
| `EARNINGS_BREADTH_HEADWIND` | 0.50 | Stamped |
| `RSI_PERIOD` | 14 | Signed parent |
| `RSI_LEVEL` | 35 | Signed parent |
| `LOW_WINDOW_SESSIONS` | 10 | Signed parent |
| `ALT_RSI_LEVEL` | 40 | Signed parent |
| `ALT_SMA_WINDOW` | 10 | Signed parent |
| `ALT_SMA_DISTANCE` | 0.03 | Signed parent |
| `MAX_FILL_GAP_CALENDAR_DAYS` | 5 | Signed parent |
| `LAUNCH_RETURN` | 0.10 | Signed parent |
| `FAIL_TO_LAUNCH_INDEX` | 63 | Signed parent |
| `TIME_CAP_INDEX` | 252 | Signed parent |
| `REVIEW_INDEXES` | 63, 126, 189 | Signed parent |
| `DRAFT_HIGH_WINDOW` | 10 | Signed parent |
| `DRAFT_SWING_LIMIT_INDEX` | 15 | Signed parent |
| `DRAFT_REVIEW_SPACING` | 63 | Signed parent |
| `DRAFT_REVIEW_COUNT` | 4 | Signed parent |
| `RECOVERY_DROP` | 0.08 | Signed parent |
| `COOLDOWN_SESSIONS` | 10 | Signed parent |
| `STAKE_UNITS` | 100 | Signed parent |
| `MATURITY_SESSIONS` | 63 | Signed parent |
| `THESIS_CONFIRM_OBSERVATIONS` | 2 | Stamped |
| `BASKET_MIN_NAMES` | 5 | Signed parent |
| `DEEP_DIP_LOOKBACK` | 20 | Signed parent |
| `DEEP_DIP_DROP` | 0.08 | Signed parent |
| `REGIME_SMA_SESSIONS` | 200 | Signed parent |
| `REGIME_ABOVE_SHARE` | 0.5 | Signed parent |
| `REGIME_MIN_NAMES` | 5 | Signed parent |
| `CHART_NOT_DAILY_GAP_SHARE` | 0.05 | Signed parent |
| `CHART_NOT_DAILY_GAP_DAYS` | 5 | Signed parent |
| `DELIST_HAIRCUT_BASELINE` | 0 | Proposed |
| `DELIST_HAIRCUT_SENSITIVITY` | −0.30 | Proposed |
| `TRADING_DAYS_TOLERANCE` | 10 | Stamped from the coverage check |
| `FAMILY_ERROR` | 0.10 | Proposed |
| `FAMILY_SIZE` | 4 | Proposed |
| `FAMILY_COVERAGE` | 0.975 | Proposed |
| `RESAMPLE_COUNT` | 10000 | Signed parent, step 3.2 count |
| `TAIL_BAR` | −0.20 | Signed step 3.2 |
| `DRAWDOWN_MULTIPLE` | 1.5 | Signed step 3.2 |
| `REGIME_HALF_MIN_MATURE` | 12 | Signed step 3.2 |
| `SLOT_COUNT` | 20 | Signed parent |
| `SLOT_RANDOM_ORDERS` | 15 | Signed parent |
| `SLOT_BOOK_RANDOM_SEED` | 20261104 | Signed parent clarification |
| `FX_CARRY_DAYS` | 5 | Proposed |
| `SMALL_CELL` | 5 | Proposed, matches US |
| `ftse350` buy, sell | 0.00525, 0.00025 | Signed table |
| `dax` buy, sell | 0.00175, 0.00175 | Signed table |
| `cac40` buy, sell | 0.00175, 0.00175 | Signed table |
| `LEGACY_STRESS_TRADE_COST_PCT` | 0.03 | Stamped |
| `DAILY_CALL_LIMIT` | 100000 | Vendor |
| `DAILY_CALL_BUDGET_SOFT_CAP` | 90000 | Proposed |
| `FUNDAMENTALS_CALL_WEIGHT` | 10 | Vendor |
| `EOD_CALL_WEIGHT` | 1 | Proposed |
| `DIV_CALL_WEIGHT` | 1 | Proposed |
| `SPLIT_CALL_WEIGHT` | 1 | Proposed |
| `LIST_CALL_WEIGHT` | 1 | Proposed |
| `MAX_REQUESTS_PER_SEC` | 5 | Stamped |
| `BUDGET_PROBE_SYMBOLS` | 1 | Proposed |
| `LSE_WEIGHTED_CALLS` | 86818 | Computed from the measured list size |
| `EURGBP` sanity band | 0.70 to 0.95 | Proposed |
| `USDGBP` sanity band | 0.65 to 0.90 | Proposed |
| `SUBSCRIPTION_START` | 2026-11-12 | Owner |
| `SUBSCRIPTION_END` | 2026-12-10 | Sealed (owner change: two days inside the month) |
| `SEAL_TARGET` | 2026-11-18 | Proposed |
| `EUROPE_FETCH_DEADLINE` | 2026-11-24 | Proposed |
| `DEVELOPMENT_COMMIT` | 2026-11-25 | Proposed |
| `REVEAL_TARGET` | 2026-12-03 | Proposed |
| Strong-buy composite | 0.70 | Stamped |
| Buy composite | 0.55 | Stamped |
| Strong-buy pass fraction, floor | 0.35, 5 | Stamped |
| Buy pass fraction, floor | 0.22, 3 | Stamped |
| Hold pass rate, composite | 0.15, 0.45 | Stamped |
| Risk veto levels | 0.55 strong, 0.35 buy | Stamped |
| Quality floors | 0.50 analysis, 0.50 buy, 0.65 strong | Stamped |
| Channel direction R² | 0.25 | Signed parent `channel_v0` |
| Dividend yield lookback | 365 days | Proposed |
| Debt-to-equity scale | × 100 | Matches the Sharadar panel |
