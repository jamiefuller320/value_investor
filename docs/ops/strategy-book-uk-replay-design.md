# Strategy book UK/Europe point-in-time replay — design

**Status: design only.** Plan step 3.3. The draft registration is
[`strategy-book-uk-replay-registration-draft.md`](strategy-book-uk-replay-registration-draft.md).
The registration was **sealed on 2026-11-12** (owner accepted the defaults, with the Companies House scope and last-call-day changes recorded in the registration). `influences_live` is false. The dispatch-only runner that
follows this design is [`strategy-book-uk-replay-runbook.md`](strategy-book-uk-replay-runbook.md).
It refuses every EODHD call until the owner seals the registration.

Parent rules: [`strategy-book-registration.md`](strategy-book-registration.md)
(`owner-strategy-book-v0`, signed 2026-11-05). Template:
[`strategy-book-us-rehearsal-registration.md`](strategy-book-us-rehearsal-registration.md).
The US rehearsal was revealed 2026-11-07: 4,113 mature confirmation episodes,
median matched excess **−0.10%** (96⅔% interval −0.55% to +0.23%), primary
`inconclusive`. Development was −0.11% on 3,802 mature episodes.

The paid EODHD ALL-IN-ONE month started **2026-11-12** (100,000 API calls a
day; a fundamentals request weighs 10). The token is the GitHub Actions secret
`EODHD_API_TOKEN`. It is not on this machine, and this design makes no EODHD
call. Treat the month as ending **2026-12-10** (sealed last call day) unless the EODHD dashboard shows
an earlier end.

L664 stays open until a reveal is committed. Scaling Companies House statements
to every FTSE 350 leaver is already queued as L716.

## 1. Learning question

On a survivorship-free UK tape (and XETRA and Paris if that fetch finishes),
with the signed entry, the signed checkpoint ladder, and the mappings in the
draft registration, do the mature holdout episodes show a positive median
fair-cost return and a positive median matched excess over holding that
market's buy tier for the same dates?

The US tape answered that question `inconclusive`, with a matched-excess
median of −0.10%. This replay asks whether the home market separates from zero
where that tape did not. It is evidence about the method. It does not pass the
parent learning question, it does not enter the 48-episode thickness count, and
it does not open live capital or step 5.5.

| Holdout result | What the owner does with it |
|---|---|
| **Clean pass.** The 97.5% interval of median matched excess lies wholly above zero, the fair-cost median is above zero, and none of the dirty flags in section 6 is set. | The version review can treat the US null as specific to that tape. The timing rule has once cleared a matched-excess bar on a survivorship-free UK/Europe history. The forward book still has to pass on its own episodes. |
| **Null (`inconclusive`).** The interval covers zero and the fair-cost median is above zero. | The US figure was not a US-only quirk. The version review does not keep the timing rule on the grounds that the UK has never been measured. No rule change follows from this registration. |
| **Negative.** The interval lies wholly below zero (`fail_excess`), or the fair-cost median is zero or below (`fail_costs` when the excess interval is still above zero). | The version review reads the fail before it promotes a filter that only reshapes this same entry. The forward book keeps running under the signed parent id. |

A pass that is dirty (delisting haircut, tail, drawdown, market spread, regime
spread, or a missing sterling FX series) is stored as a pass with `clean_pass`
false. It is not the clean pass in the table. No minimum edge beyond "the
interval lies above zero" is set. The tape starts in 2013, so a pass says
nothing about 2008.

No language model chooses an entry, an exit, or a review.

## 2. Universe

There is no historical FTSE 350 membership file. Membership is a month-end
market-cap rank, including names that later delist.

**Who is ranked.** For each exchange, the EODHD symbol list
`exchange-symbol-list/{exchange}?type=common_stock`, once for listings and once
with `delisted=1`. Measured on 2026-11-12: LSE **3,794** active and **2,884**
delisted common stocks (6,678 names). XETRA and PA counts are not known until
those four list calls run. The list is the ranking set. The episode set is the
subset that ever lands inside the rank. A planning figure of about **700**
distinct LSE names ever inside the top 350 is the walk set after the rank
exists. Fetching 700 names cannot build the rank, because a name outside an
arbitrary 700 might have been larger. The call budget in section 5 is the full
list.

**Rank.** On the last session of each calendar month (a date that has a close
on that exchange):

1. Drop funds and investment trusts before they take a seat (below).
2. Market cap = raw `close` that session × shares outstanding × the FX factor
   into the rank currency. LSE ranks in GBP. XETRA and PA rank in EUR.
3. Shares are the latest `outstandingShares` row, quarterly preferred over
   annual, whose `dateFormatted` is on or before the session and whose `shares`
   is positive. A bare year in `date` is ignored. That field is what made check
   D read 0% before the 2026-11-12 fix.
4. A split row dated after the shares date and on or before the session, with
   `split` parsed as `new/old`, scales the shares. An unparsed split in that
   window makes the cap not computable for that month.
5. Rank 1 is the largest cap. Ties break by symbol code ascending, so the cut
   is one name wide. The count of ties broken this way is kept.
6. Keep ranks 1–**350** on LSE (`ftse350`), 1–**40** on XETRA (`dax`), 1–**40**
   on PA (`cac40`). The month-end set is carried until the next month-end. A
   panel row dated month-end *D* qualifies sessions strictly after *D*.

**Cap not computable.** No raw close, no usable shares row, non-positive
shares, an unparsed split in the window, or a missing FX rate. The name is
left out of that month's rank. It is counted (`cap_not_computable`). It is not
filled from last month's cap, and it is not ranked as zero. Leaving the rank
stops a new entry. An open episode stays open until its own exit.

**Currency.** Most LSE closes are quoted in pence. The listing unit is EODHD
`General.CurrencyCode`: `GBX` (or `GBp`) divides the close by 100 before the cap,
`GBP` needs no conversion. A missing or unrecognised code is not computable that
month. A cap above GBP 500bn or below GBP 1m is not computable either and is counted
(`cap_unit_implausible`), since it is almost always a pence/pound slip. EUR on LSE uses `EURGBP.FOREX`
(GBP per 1 EUR). USD on LSE uses `USDGBP.FOREX` (GBP per 1 USD). A USD name on
XETRA or PA uses USDGBP / EURGBP. Any other currency is not computable that
month. Before any rank is kept, the first 2024 session of `EURGBP.FOREX` must
sit between 0.70 and 0.95, and `USDGBP.FOREX` between 0.65 and 0.90. A close
outside the band stops the job. The pairs are not inverted in code.

**Investment trusts and non-common stock.** The symbol list is already
`type=common_stock`. A row whose `General.Type` is present and is not
`Common Stock` is dropped and counted. Funds and investment trusts are dropped
with the existing `classify_fund_or_trust` rules on `General.Name`,
`General.Sector`, `General.Industry`, and `General.Type`: sector and industry
fragments, quote type ETF or mutual fund, and a name that says "investment
trust" or "fund" (not "fund management"). REITs stay in, matching the decline
gate. The live per-ticker override file is not applied; those tickers are
Yahoo codes. The official FTSE 350 includes investment trusts. This rank does
not, so it holds operating companies only and is labelled
`lse_operating_cap_rank_1_350`.

A name in two of these markets on the same session is an `ftse350` episode and
is dropped from the others for that session. The scratch count is
`overlap_excluded`. The committed store keeps the count and no tickers.

## 3. Point-in-time inputs

Eligibility and the price rule are both required. One failure, or a missing
input the check needs, means the name is not eligible. `insufficient_data` is
not a pass. The value set is monthly. The price rule is daily.

Annual statements are fiscal-year rows, not trailing twelve months. The US
rehearsal used Sharadar ART (`statement_basis` `art_ttm`). This replay's
`statement_basis` is `eodhd_annual`. The two tapes are not the same accounting
construction.

**When a statement is visible.** `filing_date` on the EODHD row when it parses
as a date. Otherwise the period end plus a lag: **180 days** for an annual
row (`STATEMENT_LAG_DAYS`), **90 days** for a quarterly row
(`INTERIM_STATEMENT_LAG_DAYS`). 180 days is the UK public-company filing
deadline, used for LSE, XETRA, and PA so one constant is sealed. The row is
then visible on a session at least **2 days** after that availability date
(`FILING_LAG_DAYS`, the same lag as the US rehearsal). A row whose period end
is more than **456 days** before the session is stale (`STALE_FILING_DAYS`)
and is not used. `Highlights` are today's snapshot and are not read.

A prior-year comparative printed inside a statement that is already visible
may fill a year that has no primary row. It is labelled `source=comparative`,
and it becomes visible on the later statement's availability date. A missing
year is missing. It is never copied forward from the last year on file.

### 3.1 Cheap on fundamentals (part 1)

Part 1 is the same screen the parent book uses: raw `signal` of `buy` or
`strong_buy` from `assign_signal`, on a month-end panel. The panel columns are
the Sharadar replay columns. Each model runs on those columns. A model whose
column is null does not pass. Thresholds copied from the signed screen:
strong buy needs at least `max(5, 35% of models)` passing, blended composite
at least 0.70, and at least 3 families; buy needs at least `max(3, 22%)`,
blended composite at least 0.55, and at least 2 families. Analysis requires
data quality at least 0.50; strong buy requires 0.65; buy requires 0.50.

`data_quality_score` on this tape is 1 when `market_cap`, `total_revenue`, and
`net_income` are all present, and 0 otherwise (`data_quality_basis` =
`three_fields`). The live quality formula reads filing inventories this tape
does not have.

| Panel column | EODHD field | Rule when the field is absent |
|---|---|---|
| `market_cap` | Raw `close` × shares × FX, as in section 2 | Row cannot be buy. Cap rank also skips the name. |
| `total_revenue` | `Income_Statement.yearly.totalRevenue` | Revenue checks and many cheapness models do not pass. |
| `ebit` | `ebit`, else `operatingIncome` | Models that need EBIT do not pass. |
| `ebitda` | `ebitda` | That model does not pass. |
| `net_income` | `netIncomeApplicableToCommonShares`, else `netIncome` | Earnings yield is not computed. |
| `interest_expense` | `interestExpense` | That model does not pass. |
| `gross_margin` | `grossProfit / totalRevenue` | Null when either figure is missing. |
| `free_cashflow` | `Cash_Flow.yearly.freeCashFlow` when that key is numeric. Else `totalCashFromOperatingActivities + capitalExpenditures` only when capex is zero or negative. | Null. A positive capex figure is not flipped. |
| `operating_cashflow` | `totalCashFromOperatingActivities` | Null. |
| `total_assets`, current assets, liabilities, current liabilities | `totalAssets`, `totalCurrentAssets`, `totalLiab`, `totalCurrentLiabilities` | The ratio that needs them is null. |
| `total_debt` | `shortLongTermDebtTotal`, else short-term plus long-term debt | Enterprise value is null. Debt is not treated as zero. |
| `total_cash` | `cashAndShortTermInvestments`, else `cash` | Enterprise value is null. Cash is not treated as zero. |
| Equity, book | `totalStockholderEquity` | Price to book is null. |
| `shares_outstanding` | Balance-sheet `commonStockSharesOutstanding`, else the shares row used for the cap | Null. |
| `dividend_yield` | Sum of `div/{symbol}` cash amounts with an ex-date in the 365 days up to the session, divided by the raw close | Null, and `high_dividend` / `dividend_growth` do not pass. |
| Growth fields | This fiscal year over the prior fiscal year, prior positive, both visible | Null. |
| `sector` | `General.Sector`, else `General.GicSector` | `sector_missing`. The name is not eligible. |

`trailing_pe` is `market_cap / net_income` when net income is positive.
`enterprise_value` is cap + debt − cash, and only when debt and cash are both
present. `dividend_yield` feeds the screen. It does not feed the decline
gate's dividend-cut check.

`adjusted_signal` does not exist on this tape. The cash-flow agreement board
is the single bucket `missing`. The bench column `fcf_agrees` is not a test.
That is how the US rehearsal handled the same gap.

Thesis `avoid` is two consecutive month-end panels whose `signal` is `avoid`.

### 3.2 Operating-decline gate (part 2)

The verdict rule is the gate's own rule, stamped so a later edit to the module
does not move this replay. Any hard reason means `declining`. Two soft reasons
mean `declining`. Otherwise `insufficient_data` when annual revenue is not
evaluable or neither the margin nor an EPS check is evaluable. Otherwise
`clear`.

| Check | Reading | Threshold | Kind |
|---|---|---|---|
| Revenue | This fiscal year against the prior fiscal year. Prior revenue positive. | Below −5% (`REVENUE_DROP_PCT` 0.05). Two-year hard reason when this change and the prior change are both below −1% (`REVENUE_FLAT_TOLERANCE_PCT` 0.01). | Hard |
| Interim revenue | Quarterly `totalRevenue` against the quarter whose period end is within 45 days of one year earlier (`INTERIM_YOY_WINDOW_DAYS`). Current period at most 460 days old (`INTERIM_MAX_AGE_DAYS`). | Below −5%. | Hard |
| Operating margin | `operatingIncome / totalRevenue`, else `ebit / totalRevenue`. The same pair in both years. | Fall of more than 3 percentage points (`MARGIN_DROP_PP` 0.03). | Hard |
| EPS, annual | `Earnings.Annual` `epsActual` for that fiscal year, visible only once the matching income statement is visible. Else net income ÷ shares on that statement. | Prior positive and latest below prior × 0.80 (`EPS_ANNUAL_DROP_PCT` 0.20). | Soft |
| EPS, interim | `Earnings.History` `epsActual`, available on `reportDate` or `date`, same 45-day and 460-day rules. | Prior positive and latest below prior × 0.90 (`EPS_INTERIM_DROP_PCT` 0.10). | Soft |
| Free cash flow | The FCF figure in the table above, against the prior year. | Hard when prior is positive and latest is negative. Soft when prior is positive and latest is below prior × 0.50 (`FCF_SHARP_FALL_PCT` 0.50). | Hard or soft |

A year-on-year EPS pair is evaluable only when both years carry the same
`eps_basis` (`vendor_eps` or `net_income_over_shares` or `companies_house_basic`).
A mixed pair does not fire and is counted `eps_basis_mismatch`.

These checks do not fire. Nothing is substituted for them:

| Live check | Handling |
|---|---|
| Dividend cut (`interim_dividend_cut_flagged`) | Absent. The dividend history used for yield is not a cut rule. |
| Profit-warning and impairment headlines | Absent. EODHD has no filings-index headline scan. |
| Half-year filing extract and screen-row interim fields | Absent. Interim revenue and interim EPS use quarterly statements and `Earnings.History` only. |

`insufficient_data` blocks a new entry. Mid-hold it is not by itself a thesis
break. At a review date it exits `review_insufficient_data`. Two consecutive
`declining` sessions confirm a thesis break. `revenue_growing` keeps entries
whose mapped revenue `change_pct` is above zero.

**Companies House, failed names only.** The committed store
`docs/data/ch_failed_name_statements.json` may be read. It is Crown copyright
under the Open Government Licence and contains no EODHD prices. It covers
seven UK names. A Companies House year is used only when EODHD has no annual
income row for that fiscal year. One source per year: lines are not mixed.
Availability is the Companies House filing date, plus the 2-day lag. A
comparative column is visible from the filing date of the report that contains
it (Patisserie's 2013 EPS is a comparative in the 2014 report, filed
2015-03-18, so it is visible from 2015-03-20). Mapping: revenue; statutory
operating profit; profit attributable to owners; basic EPS; weighted-average
basic shares; net cash from operating activities; capital expenditure as a
positive purchase, so free cash flow is operating cash flow minus that
purchase. A negative Companies House capex leaves FCF null. Balance-sheet
fields are not in that extract, so enterprise value and book stay null for a
Companies House year. Dividends per share were not read. A missing year fails
closed.

On the 11 probe names the coverage check and the Companies House note already
measured: EODHD statements from 2013 on **3 of 11**; Companies House adds five,
so **8 of 11** have a 2013 first year; **4 of 11** have a statement every year
to the event (Carillion, Patisserie, Aggreko, Morrison). Thomas Cook,
Debenhams, and Intu stay without a 2013 EPS.

### 3.3 Sector gate (part 3)

`General.Sector` (else `GicSector`) is the label on the download, applied on
every date. `sector_label_basis` is `eodhd_general_current`. That is
look-ahead, the same limitation as Sharadar `tickers.sector` on the US tape.
Sectors are scored inside one market. There is no regional pool.

Price inputs match the live gate: share of members whose adjusted close is
below the mean of their own last 200 adjusted closes; equal-weight 126-session
return; headwind when the share is at least **0.65** and the return is below
**−0.10**; each side needs at least **4** members and **60%** coverage.

Decline breadth uses the part 2 verdicts of the sector's members. Headwind
when at least 60% of operating members have a verdict and at least **50%** of
those verdicts are `declining` (`EARNINGS_BREADTH_HEADWIND` 0.50). There is no
screen `earnings_growth` fallback. That field is not a historical series here.

| Situation | Verdict | `sector_basis` |
|---|---|---|
| Price trigger fires, or decline breadth fires | `headwind` | `price_and_decline` when both coverages met, otherwise the side that fired |
| Price coverage met, price trigger false, decline coverage met, decline breadth under 50% | `sound` | `price_and_decline` |
| Price coverage met, price trigger false, decline coverage not met | `sound` | `price_only` |
| Price coverage not met, and decline breadth did not fire | `insufficient_data` | — |
| Sector label missing | Not eligible | `sector_missing` |

`price_only` is the US rehearsal's sound rule, used here only when decline
coverage fails. Missing statements then do not by themselves blank the sector.
The bias report in section 4 shows how often that happened. `headwind` opens
the sector shadow. `insufficient_data` is counted and not shadowed.

### 3.4 F9-B, memos, and the other labels

The four F9-B binds, the research verdict, and the memo do not exist as
point-in-time series on this tape. The US rehearsal's labels are copied.

| Column | Label on every episode | Effect |
|---|---|---|
| F9-B | `f9_unverified` | Does not block an entry and does not sell. |
| Research verdict | `absent` | Does not block an entry. Is not a thesis break. At a review, a missing verdict leaves the hold standing when the mapped gates are `clear` and `sound` and the signal is not `avoid`. |
| Memo | `not_applicable` | `memo_not_ready` and `memo_blocked` are not used. |
| `adjusted_signal` | `absent` | Does not gate. `fcf_agrees` is not a test. |
| `t212_listed` | `not_applicable` | Today's catalogue is not painted backward. |
| `late_signal` | `not_applicable` | There is no decision clock. |
| `provenance_missing` | Not used | Licensed inputs are deleted. |

### 3.5 Price rule and the rest of the book

The runner feeds daily bars and an eligibility row. The signed parent walker
applies the price entry, the ladder, the comparison exits, the shadows, the
controls, and the bench filters. Copied constants, all signed on the parent
unless marked proposed:

| Rule | Value |
|---|---|
| RSI | 14, below 35, Wilder `_rsi` on adjusted closes through *t* |
| Short-term low | Adjusted close equal to the minimum of the 10 sessions ending at *t* |
| Alternative column | RSI below 40 and close at least 3% under SMA(10). Report-only. |
| Fill | Next session's adjusted close. No fill across more than 5 calendar days, or off the last bar. |
| Primary exit | Checkpoint ladder. Launch at +10%. Floors: +10→+5, +15→+10, +20→+15, +25→+20, +30→+25, +40→+30, +50→+40, +75→+50, +100→+75. Fail to launch at session index 63. Time cap at 252. |
| Comparison exits | `draft_v0_exit` and `ladder_no_deadline` |
| Thesis confirm | 2 consecutive observations |
| Recovery label | 8% under the fill. The label sells nothing. |
| Cooldown | 10 sessions |
| Stake | 100 GBP on LSE, 100 EUR on XETRA and PA. Episode percent does not use the stake. |
| Maturity | Fill at least 63 sessions before the scoring date |
| Shadows | Decline-rejected and sector-rejected |
| Controls | Buy-on-signal, and leave-tier. Screen runs are the month-end panels. |
| Bench tests | `deep_dip` (8% below the close 20 sessions earlier), `revenue_growing`, `trend_not_falling` (6-month `channel_v0` direction `rising` or `sideways`) |
| Bench omitted | `fcf_agrees` |
| Channels | `channel_v0`, on adjusted highs and lows when both exist, otherwise closes |
| Regime | At least half of the market's names with 200 bars closed above their 200-session average. Fewer than 5 such names is `regime_unknown`. |
| Daily tape | More than 5% of successive gaps longer than 5 calendar days is `chart_not_daily` and is not traded. |

Warm-up prices start **420** calendar days before 2013-01-01.

## 4. Survivorship

A delisted name enters the rank in any month it still has a raw close and a
computable cap inside the cut. It leaves the month after its last close. An
open episode whose symbol is on the delisted list, and whose prices have ended,
exits at the last `adjusted_close`. Baseline haircut **0**. Label `delisted`
when no exit was already signalled. An exit already signalled keeps its label.
An entry that cannot fill because the name has already delisted is not an
episode (`delisted_before_fill`). A hole on a symbol that is still on the
active list leaves the episode open. A missing quote is a blank mark.

EODHD has no merger-action table. The 11 probe names are classified in the
registration, from the coverage note, before any score:

| Class | Names |
|---|---|
| Failure | Carillion, Thomas Cook, Debenhams, Patisserie Holdings, Intu, Wirecard (6) |
| Takeover | Sirius Minerals, GKN, Sky, Aggreko, Wm Morrison (5) |

Every other delisting is `unclassified`. The sensitivity scores the holdout
primary again with haircut **−0.30** on failures and on unclassified
delistings. Takeovers stay at 0. A primary pass that is not a pass under that
haircut is `pass_delisting_sensitive` and is not a clean pass.

Patisserie's prices stop at the October 2018 suspension, more than 10 trading
days before the administration date used as its event. The exit is still that
last price. The probe counter `price_ended_before_known_event` records it. No
synthetic administration price is used.

**How many names.** The full delisted common-stock list is 2,884 on the LSE.
Only those that reach rank 1–350 while listed enter the book. This draft does
not forecast that count. The committed store reports `delisted_exits`, split
into the known failures, the known takeovers, and unclassified. The planning
figure for distinct LSE names ever in the rank is about 700.

**How missing statements bias the result.** Failures are the names most likely
to lack statements. A missing year makes the decline gate `insufficient_data`,
which blocks an entry and does not open the decline shadow. The book then
trades a set that still has accounts. The store reports the share of
universe-months (one ranked name on one month-end) whose annual revenue check
is not evaluable, split three ways:

- `still_listed` — on the active symbol list at the download
- `later_delisted` — on the delisted symbol list, including months before the exit
- `list_unknown` — on neither list

A higher share on `later_delisted` than on `still_listed` is the bias. No
scalar is applied to "correct" it. On the 11 probe names, 7 of 11 lack a
statement every year to the event, so that bias is expected on the known
failures. Companies House is the fallback for the seven names already
extracted. It is not extended to every leaver in this replay (L716).

## 5. Licence and call budget

EODHD data is not redistributable. The replay runs in GitHub Actions, reads
`EODHD_API_TOKEN` from the secret, and writes raw responses only to the job's
temp directory and a same-day resume cursor in the Actions cache. The cursor
stores symbol codes and a done flag. It is not committed. Temp files are
deleted at the end of each job. A later job fetches again. Per-episode rows,
prices, fundamentals, dividend amounts, and panel rows are not committed.

The committed file, when the runner exists, is
`docs/data/strategy_book_uk_replay.json`: episode counts, medians, intervals,
bar flags, and the bias shares. A cell with fewer than 5 episodes publishes
the count and suppresses return statistics. The 11 probe keys may appear with
booleans only (in the rank, had an exit, statement every year). Those keys are
already in the coverage note.

**Weights.** Symbol list, EOD, dividends, and splits weigh 1. Fundamentals
weigh 10. Soft stop at **90,000** weighted calls in a UTC day
(`DAILY_CALL_BUDGET_SOFT_CAP`), under the 100,000 limit. The daily reset is
planned as 00:00 UTC. A job does not run across that midnight. One probe symbol
is fetched first. If that fundamentals response did not weigh 10, or the
dividend response did not weigh 1, the job stops before the loop.

**LSE, the required fetch.** 3,794 + 2,884 = 6,678 names.

| Request | Count | Weight | Calls |
|---|---:|---:|---:|
| Symbol lists (active, delisted) | 2 | 1 | 2 |
| EOD from 2011-11-08 (`420` days before 2013-01-01) | 6,678 | 1 | 6,678 |
| Fundamentals | 6,678 | 10 | 66,780 |
| Dividends | 6,678 | 1 | 6,678 |
| Splits | 6,678 | 1 | 6,678 |
| FX (`EURGBP.FOREX`, `USDGBP.FOREX`) | 2 | 1 | 2 |
| **LSE day** | | | **86,818** |

86,818 is under 90,000, with headroom of 3,182 calls for retries of
names the cursor has not marked done. HTTP requests are 2 + 6,678 × 4 + 2 =
26,716. At 5 requests a second that is about 90 minutes, inside one Actions
job. If the soft cap or a dead job stops the day, the next UTC day resumes
after the cursor.

Fetching only the planning figure of 700 names would be 700 × 13 + 2 = 9,102
calls. That fetch is not the plan. It cannot identify the 700.

**XETRA and PA.** Day 2 starts with four symbol-list calls. Let *N* be
active plus delisted common stocks on the two exchanges. The fetch is
4 + 13*N* weighted calls, and it uses the FX series already stored in the
runner's memory that day (a fresh job refetches the two FX series, 2 calls).
One day holds *N* up to (90,000 − 6) / 13 = 6,922. Above that, the cursor
splits the remainder onto the next UTC day. If XETRA and PA are not finished
by **2026-11-24**, they are dropped, the store records `europe_not_fetched`
and the symbol-list counts, and the scored book is LSE only. An LSE-only
result is labelled `ftse350`. It is not described as a Europe result.

The development job and the reveal job each fetch. Two LSE passes are two
UTC days, each under the cap. The month can hold that. Raw files are not kept
between the jobs.

## 6. Windows, bars, timetable

An episode belongs to the window that contains its **signal session**.

| Window | Signal sessions | Role |
|---|---|---|
| Development | 2013-01-01 through 2018-12-31 | Machinery check. Descriptive intervals. No test is added or dropped from these ranks. |
| Holdout | 2019-01-01 through 2025-09-30 | Confirm or reject, once. Contains 2020 and 2022. |
| After 2025-09-30 | No new signal. | Fills and exits of a signal inside a window may use later prices. |

The first panel is the last session of January 2013. Sessions before that
panel has a prior row do not enter. Development episodes may exit on 2019
prices and stay in the development block. The calendar overlaps the US
confirmation window. The names do not. This window is unscored for these
rules. It is not a second look at the US result, and it does not reveal any
Sharadar holdout.

**Family.** Uncorrected family error 0.10. Four tests, so each interval is
97.5% (`1 − 0.10 / 4`), from 10,000 resamples of whole ISO entry weeks.

| Test | Statistic |
|---|---|
| Primary | Median matched excess of mature holdout episodes |
| `deep_dip` | Mean fair-cost return of the kept entries minus the mean of all book entries |
| `revenue_growing` | The same difference on its kept set |
| `trend_not_falling` | The same difference on its kept set |

`trend_not_falling` is on the parent bench (sealed 2026-11-10). The US family
had three tests because that seal came after the US registration.
`fcf_agrees` is absent, so it is not a fifth test. A candidate also needs the
same sign in both holdout halves: 2019-01-01 through 2021-12-31, and
2022-01-01 through 2025-09-30. The halves are a condition, not two more tests.

**Sealed proof bars, reused as dirty flags rather than extra tests.** The
numbers are the step 3.2 bars. They are computed on the holdout and stored.
They do not enlarge the family. `clean_pass` is false when any flag is set.

| Bar | Flag when it fails |
|---|---|
| 5th-percentile fair-cost return no worse than −20% | `tail_breach` |
| 20-slot book max drawdown no more than 1.5 times the matched basket over the same dates | `drawdown_breach` |
| Median matched excess stays above zero with the largest market removed | `single_market_dependence` |
| Median matched excess at or above zero in both regime halves, each with at least 12 mature episodes | `regime_spread_miss` |
| Sterling 20-slot book, after fair costs and FX, has a positive total return and beats the matched basket in sterling | `sterling_slot_miss`, or `sterling_fx_missing` when the FX series is absent |
| Delisting sensitivity still a pass | `pass_delisting_sensitive` |
| Trading 212 listed subset | Not computed. `t212_listed` is `not_applicable`. |

The sterling book converts EUR at the `EURGBP.FOREX` close. A session with no
FX close may use the previous close within 5 calendar days. Beyond that the
sterling book is `not_computed`. LSE episodes are already sterling. The slot
book uses 20 slots, ties by symbol, 15 orders, seed `20261104`. Matched excess
itself stays in the listing currency. Costs cancel, and FX is not inside the
primary statistic.

Costs, from the signed table: FTSE 350 buy 0.525% and sell 0.025%; DAX and
CAC 40 buy 0.175% and sell 0.175%. Stress is 3% per side, report-only.

**Order of work.** Development is committed before any holdout aggregate is
written. The runner refuses a holdout aggregate until the reveal step. One
reveal. A second reveal is exploratory and is not evidence.

| Date | What happens | Owner |
|---|---|---|
| 2026-11-12 | Subscription started. Coverage check already run (564 calls). This draft exists. | |
| By 2026-11-18 | Read the draft. Sign it, or change a proposed number once. No replay call before this stamp. | **Sign-off 1: registration seal** |
| 2026-11-19 | LSE fetch, 86,818 weighted calls, resume cursor, soft cap 90,000. | |
| 2026-11-20 | Finish LSE if needed. Otherwise start XETRA and PA. | |
| 2026-11-21 to 2026-11-24 | Resume buffer. Europe not finished by 2026-11-24 is dropped and labelled. | |
| 2026-11-25 | Development walk only. Commit the development block. Delete temp files. | |
| 2026-11-26 to 2026-12-02 | Read the development block. No registered number changes. A bug fix is an amendment, and development is recomputed before any reveal. | |
| 2026-12-03 | Fresh fetch if the cache has expired, then the single holdout reveal and the delisting sensitivity. | **Sign-off 2: reveal** |
| 2026-12-04 to 2026-12-09 | Only a recomputation the reveal stamp already allowed. | |
| 2026-12-10 | Last day calls are allowed. Delete temp files and the resume cache. Stamp `licensed_data.deleted_at`. | |

The human checklist item is `adhoc-strategy-uk-replay-reveal`.

## 7. Out of scope

Left out of this registration, and queued behind P1/P2 except where noted:

| Item | Where it sits |
|---|---|
| The runner, the Actions workflow, the aggregate store, and the ops-monitor finding | Shipped as the dispatch-only runner in [strategy-book-uk-replay-runbook.md](strategy-book-uk-replay-runbook.md). It does not run until the owner seal. Not a daily cron. L664 stays open until a reveal is committed. |
| Editing the plan status row for step 3.3 | The owner updates the plan. |
| Editing the signed parent registration | Frozen. |
| Official FTSE 350, DAX, and CAC constituent histories | Queued as L717. Cap rank is the proxy this draft seals. |
| Point-in-time sector labels | Queued as L718. The current `General.Sector` is used on every date. |
| A dated Trading 212 catalogue, so the tradable-subset bar could be scored | Queued as L719. |
| A dividend-cut rule | Queued as N271. The check does not fire. Dividend history is used for yield only. |
| A profit-warning headline scan | Queued as L720. The check does not fire. |
| Companies House for every leaver | Already queued as L716. This replay reads the seven-name store only. |
| Exchanges beyond LSE, XETRA, and PA | Queued as N272. |
| A tape before 2013, including a 2008 window | Queued as L721. EODHD depth from 2013 is the reason the window starts there. |
| LLM memo verdicts on the entry, the exit, or the review | Out of the method. |
| Passing the thickness gate, step 3.2 as a live-capital decision, or step 5.5 | Out of this instrument. |
| Revealing hsr-v2 or any other Sharadar holdout | Forbidden. |
| Committing prices, statements, or per-episode rows | Forbidden by the licence. |
