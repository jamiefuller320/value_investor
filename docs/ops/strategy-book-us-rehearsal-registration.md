# Strategy book US point-in-time rehearsal registration

**Status: DRAFT — parent `owner-strategy-book-v0` signed 2026-11-05; this registration awaits its own owner signature before the first development score. No development score exists. No licensed file has been read for this registration.**  
**registration_id (proposed):** `strategy-book-us-rehearsal-v0`  
**Parent:** `owner-strategy-book-v0` in [`strategy-book-registration.md`](strategy-book-registration.md)  
**Plan step:** 2.5 in [`strategy-reorientation-plan.md`](strategy-reorientation-plan.md)  
**Screen replay:** [`historical-screen-replay.md`](historical-screen-replay.md)  
**Human checklist:** `adhoc-strategy-us-pit-rehearsal` in [`human-tasks-checklist.md`](human-tasks-checklist.md#ad-hoc-when-triggered)  
**Seal draft:** [`../data/strategy_book_us_rehearsal_registration.json`](../data/strategy_book_us_rehearsal_registration.json)

This document freezes the US rehearsal before any score is computed and before any Sharadar file is read. It does not run the rehearsal, does not change the Sharadar adapter, and does not write a results store. The owner has Sharadar access until **2026-11-09**. The licence and the day plan are in section 8.

`strategy-book-us-rehearsal-v0` is an observe instrument. `influences_live` is false. It does not write strand A, `buy_tier_level`, knobs, `decision-review --apply`, `strategy_book_observe.json`, or `strategy_book_replay.json`.

The signed parent registration is the rule book. This registration maps those rules onto the licensed US tape. Where this file names a parent number, that number is the parent's draft value on 2026-11-05 and **follows the signature**. Section 10 is the rule for a number the owner changes in the signature note. US-only choices are marked **proposed** and freeze under section 9.

The later runner calls the strategy-book walker (`strategy_book_observe.py`) and the registered rules (`strategy_book_rules.py`). It does not re-implement the entry, the ladder, the comparison exits, the shadows, or the bench. This package does not add that runner. If the walker and the signed parent text ever differ, the signed parent text wins.

## 1. Question and status

The rehearsal asks one question about the **method**:

On a survivorship-free US tape, with the signed entry, the signed checkpoint ladder, and the mappings in sections 3 and 4, do the mature episodes show a positive median fair-cost return and a positive median matched excess over holding that universe's buy tier for the same dates?

**What a result is.** Evidence about the method, from US names, on history that includes the 2000–02, 2008–09, 2020 and 2022 falls. The confirmation verdict in section 6 is that evidence. It is the only pass or fail this registration issues.

**What a result is not.**

| Claim | Status of this rehearsal |
|---|---|
| A pass of parent section 1 | Out of scope. Parent section 1 is the forward book. |
| The thickness gate (48 counted mature episodes, 6 per entry week) | Out of scope. US episodes never enter that count. |
| Plan step 3.2, the live-capital bar | Out of scope. Tail, drawdown, sterling, and the tradable subset are not verdicts here. |
| Proof for the FTSE 350 or for any library market | Out of scope. US evidence stays US evidence. |
| A promotion or a retirement on the forward bench | Out of scope. Section 6 says what a pass or a fail means for that bench. |
| A reveal of hsr-v2, hsr-mid-v2, hrs-v2, or hms-v2 | Forbidden. Those holdouts stay sealed. |

The two-year archive rehearsal in parent section 9(a) paints today's buy tier backward and has no point-in-time gates. This rehearsal is the point-in-time one. The two results are never averaged.

No language model chooses an entry, an exit, or a review.

## 2. Universe

Two universes, one pooled book. Per-market boards are report-only. A name that qualifies in both universes on the same session is an `sp500` episode, and it is dropped from `sp400` for that session. The scratch count is `overlap_excluded_from_sp400`. The committed store may keep that count. It keeps no tickers.

| Item | Value | Status |
|---|---|---|
| Book | One pooled book. The cap, the one-open-episode rule, and the primary median cross both universes. | Existing. Parent section 6, with these two universes in place of the forward markets. |
| `sp500` members | S&P 500 members on the session date, active and delisted. Sharadar `sp500` table. | Existing. Same universe as hsr-v2. |
| `sp500` timing | `membership_on`: the latest `historical` snapshot on or before the date, then `added` and `removed` events through that date. Before the first snapshot, undo later events from the `current` list. Evaluated on every session date. | Existing adapter rule. The screen build asks only for month-ends; this rehearsal asks for every session date. The function already takes a date list. |
| `sp400` members | US domestic common stocks reporting in USD, active and delisted, market-cap ranks 501–1000 (1 = largest) at the month-end on or before the session. The `exchange` field is not a filter. | Proposed proxy. The adapter has no S&P MidCap 400 constituent table. This is the hsr-mid-v2 universe. `universe_basis` is `cap_rank_501_1000`. |
| `sp400` timing | The month-end rank set is carried until the next month-end. | Proposed. The adapter ranks month-ends only. |
| `sp400` market id | `sp400` for costs, the stake currency, and the boards. | Existing market id in `market_trading_costs`. |
| Rank inputs | Latest ART `marketcap` filed at least 2 days before the month-end and at most 456 days old, rolled forward by the split-adjusted close. | Existing. `FILING_LAG_DAYS` 2, `STALE_FILING_DAYS` 456, `cap_rank_membership`. |
| Common-stock filter | `sp400` only: `category` starts with `Domestic Common Stock` and `currency` is USD, listed or delisted. `sp500` uses index membership, financials and real estate included. | Existing. hsr-v2 and hsr-mid-v2. |
| Non-USD reporter inside the index | Dropped by the screen panel. No signal, so not eligible. | Existing adapter exclusion. |
| Leaving the universe | Stops a new entry. An open episode stays open until its own exit. | Existing. Parent section 2, leaving the buy tier. |
| Overlap | Index membership wins. The name is not also an `sp400` episode. | Proposed. |

A true point-in-time S&P MidCap 400 constituent list is a new `registration_id`. It is not a silent swap of `universe_basis` after the first development score. Queued behind P1/P2 as L676.

## 3. How each part of the entry rule is read

Eligibility and the price rule are both required, as in parent sections 2 and 3. One failure, or a missing input that the mapped check needs, means the name is not eligible. `insufficient_data` is not a pass.

The value set is monthly. The price rule is daily. A cache row dated *D* applies to sessions strictly after *D*, until the next cache row. It does not qualify session *D*. That is the parent section 2 screen rule, with month-end cache rows in place of weekly runs.

### 3.1 Part 1 — the value set

Part 1 reads the historical screen replay's **baseline** signals cache. It does not rescreen, and it does not read a spent epoch.

| Item | Value | Status |
|---|---|---|
| `sp500` cache | `signals_cache.csv.gz` beside the hsr-v2 panel. Variant `baseline`. | Existing cache name. `SIGNAL_CACHE_NAME`. |
| `sp400` cache | `signals_cache.csv.gz` beside the hsr-mid-v2 panel. Variant `baseline`. | Existing. The mid-cap screen run records `market_id` `sp500` because that is the screen's id. Episodes are still labelled `sp400`. The two caches are not mixed. |
| Field | Raw `signal`. | Existing. Parent section 13, question 2, default. |
| Pass | `buy` or `strong_buy`. | Existing. `BUY_SIGNALS`. |
| Epoch | hsr-v2 and hsr-mid-v2, fingerprint equal to the current screen fingerprint when the cache is built. | Existing active epochs. |
| Spent epochs | hsr-v1 and hsr-mid-v1 are not read. | Existing. Those holdouts are spent, and the dividend-yield units differ. |
| `dividend_units_fixed` | Not read. Under hsr-v2 the variant is an identity and is never evidence. | Existing. |
| Fingerprint mismatch | Rebuild the baseline cache in the licensed month. Do not score a stale cache. | Proposed operational rule. |
| Thesis `avoid` | Two consecutive cache rows whose `signal` is `avoid`. | Existing confirm count 2 (`DEFAULT_EXIT_CONFIRM_SCREENS`). The observations are monthly, because that is the cache. |

`adjusted_signal` is absent from the cache. The cash-flow agreement board is the single bucket `missing`. The bench column `fcf_agrees` is not computed and is not a test (parent section 13: the US rehearsal has no adjusted signal).

### 3.2 Part 2 — the decline gate

The verdict uses the gate's own rule: any hard reason means `declining`; two soft reasons mean `declining`; otherwise `insufficient_data` when annual revenue is not evaluable or neither the margin nor an EPS check is evaluable; otherwise `clear`. Those constants are stamped below so a later edit to the gate module does not move this rehearsal. A Phase 1 signature that changes one of them is copied under section 10 before the first development score.

Point in time: dimensions **ART** and **ARQ** only. The filing date is `datekey`, or `date` when `datekey` is absent (existing adapter choice). A row is visible when its filing date is at least 2 days before the session. `lastupdated` is not an availability date. **MRT, MRQ, MRY, and ARY are not read.** ART is trailing twelve months, so an "annual" check is the TTM change to the ART row whose `calendardate` is one year earlier, not a fiscal-year statement. `statement_basis` is `art_ttm`.

| Check | Rehearsal reading | Verdict | Status |
|---|---|---|---|
| `revenue` | ART `revenue` against the ART row one year earlier in `calendardate`. Hard `revenue_decline` when the change is below −5% (`REVENUE_DROP_PCT` 0.05). Hard `revenue_two_year_decline` when this change and the prior year's change are both below −1% (`REVENUE_FLAT_TOLERANCE_PCT` 0.01). Prior revenue must be positive. | Maps. Hard. | Existing thresholds. Proposed TTM reading. |
| `interim_revenue` | ARQ `revenue` against the ARQ `calendardate` closest to one year earlier and within 45 days (`INTERIM_YOY_WINDOW_DAYS`). The prior row's filing date is on or before the cutoff. The current period is at most 460 days old (`INTERIM_MAX_AGE_DAYS`). Hard `interim_revenue_decline` when the change is below −5%. | Maps from ARQ. Hard. | Existing thresholds. |
| `operating_margin` | ART `opinc` / ART `revenue`, else ART `ebit` / ART `revenue`. Hard `operating_margin_drop` when the margin falls by more than 3 percentage points (`MARGIN_DROP_PP` 0.03). The label records which pair was used. | Maps. Hard. | Existing threshold. Existing Sharadar indicator names. A missing column leaves the check not evaluable. |
| `eps_annual` | ART `epsdil`, else ART `eps`, against one year earlier. Soft `eps_decline_annual` when the prior is positive and the latest is below the prior times 0.80 (`EPS_ANNUAL_DROP_PCT` 0.20). | Maps. Soft. | Existing threshold. |
| `eps_interim` | ARQ `epsdil`, else ARQ `eps`, with the same 45-day year-ago match and the 460-day age cap. Soft `eps_decline_interim` when the prior is positive and the latest is below the prior times 0.90 (`EPS_INTERIM_DROP_PCT` 0.10). | Maps from ARQ. Soft. | Existing threshold. |
| `fcf` | ART `fcf` against one year earlier. Hard `fcf_turned_negative` when the prior is positive and the latest is negative. Soft `fcf_sharp_fall` when the prior is positive and the latest is below the prior times 0.50 (`FCF_SHARP_FALL_PCT` 0.50). | Maps. | Existing thresholds. |
| `dividend` | The live check is the boolean `interim_dividend_cut_flagged` on a screen row. No Sharadar field is that boolean. | Absent. Does not fire. | Proposed. No DPS substitute. |
| `profit_warning`, `impairment_or_downgrade` | The live check classifies filings-index headlines. The bundle has no such index. The `events` table is not a headline scan. | Absent. Does not fire. | Proposed. |

Also absent, so they cannot be the source that makes an interim check evaluable:

| Live source | Why it is absent |
|---|---|
| Half-year filing extract | UK filings bodies. Not in the Sharadar fundamentals. |
| Filing interim highlights and half-year prose | Same. |
| Screen-row interim EPS and the dividend-cut flag | The signals cache has no such columns. |
| Headline phrases and the 180-day warning lookback | No filings index. |

The soft reasons that can fire are `eps_decline_annual`, `eps_decline_interim`, and `fcf_sharp_fall`. The bar stays two soft reasons. Dividend and headlines cannot supply one.

A gate observation is one session. The verdict for session *t* uses filings at least 2 days old and prices through *t*, and it is the eligibility fact for *t*. Two consecutive `declining` sessions confirm a thesis break. `insufficient_data` blocks a new entry. Mid-hold, it is not by itself a thesis break. At a review date it exits `review_insufficient_data`, as in parent section 5.

`revenue_growing` keeps entries whose mapped revenue check has `change_pct` above zero. A revenue check that is not evaluable is not kept. That is the signed bench column, read from this mapping.

The selection snapshot may store the check figures (changes, which soft reasons fired). Those figures stay in the scratch directory. Section 7 says what of them is committed.

### 3.3 Part 3 — the sector gate, price breadth only

Sharadar keeps no sector history. The sector label is `tickers.sector` on the download, one label per ticker, applied on every date. The panel and the signals cache copy that same label. `sector_label_basis` is `tickers_current`. This is look-ahead, including around the 2018 GICS move, as [`historical-screen-replay.md`](historical-screen-replay.md#limits) already records. The rehearsal does not correct it.

Members of a sector on a date are the names in that universe on that date with that label. `sp500` sectors and `sp400` sectors are scored apart. There is no regional pool. `sp400` is not in the forward book's `north_america` group, and this registration does not add it.

Part 3 uses the price trigger only. The thresholds are the gate's existing constants.

| Input | Value | Status |
|---|---|---|
| Breadth | Share of members whose `closeadj` is below the mean of their own last 200 `closeadj` bars. A member needs 200 bars to count. | Existing. The live gate uses a stored SMA200 when it has one, and this mean otherwise. |
| Breadth headwind | Share at or above 0.65 (`PRICE_BREADTH_HEADWIND`). | Existing. |
| Trend | Equal-weight mean of `closeadj[t] / closeadj[t−126] − 1` across members with 127 bars. | Existing. `RETURN_LOOKBACK_126D` 126. |
| Trend headwind | Mean below −0.10 (`SECTOR_RETURN_126D_HEADWIND`). | Existing. |
| Coverage | At least 4 members and at least 60% of the sector (`MIN_MEMBERS_WITH_DATA`, `MIN_COVERAGE_SHARE`), separately for breadth and for trend. | Existing. |
| Headwind | Breadth and trend both in headwind, and both coverages met. | Existing price trigger. |
| Sound | Both coverages met, and the price trigger is false. | Proposed for this rehearsal. The live gate also requires an earnings-breadth coverage before it will say sound. |
| Otherwise | `insufficient_data`. | Existing fail-closed outcome. |
| `sector_basis` | `price_only` on every episode. | Proposed. |

These do not change the sector verdict here:

| Live input | Treatment |
|---|---|
| Operating-decline breadth | Not a sector trigger. Part 2 still scores each name. |
| Earnings breadth, including the screen `earnings_growth` fallback | Not used. |
| Regional pooling (`own_market` / `regional`) | Not used. |
| Drawdown | Not a trigger. The live gate computes one and does not promote on it. |

A missing sector label is `sector_missing` and the name is not eligible. `headwind` and `insufficient_data` both fail entry. A sector shadow opens only for `headwind`, as in parent section 8. `insufficient_data` names are counted and not shadowed.

### 3.4 F9-B and research

Neither exists on this tape.

| Column | Label on every episode | Effect |
|---|---|---|
| F9-B | `f9_unverified` | The four binds are absent. The label is not a pass and is not an eligibility failure. F9-B does not block an entry and does not sell. Same label as the archive episodes in parent section 9(a). |
| Research verdict | `absent` | Does not block an entry. Is not a thesis break. At a review, a missing verdict leaves the hold standing when the mapped gates are `clear` and `sound` and the signal is not `avoid`. Parent section 5. |
| Memo | `not_applicable` | `memo_not_ready` and `memo_blocked` are not used. |
| `adjusted_signal` | `absent` | Stored as missing. Does not gate. |
| `t212_listed` | `not_applicable` | Today's catalogue is not painted backward. The tradable board is not computed. |
| `late_signal` | `not_applicable` | There is no decision clock. A signal with a next session inside the gap rule can fill. |
| `provenance_missing` | Not used | The forward flag needs hashes of files that remain. Licensed inputs are deleted. |

### 3.5 What the walker applies unchanged

The runner feeds daily bars and an eligibility row for session *t*. The walker decides the price entry, the ladder, the comparison exits, the shadows, the controls, and the bench filters. This registration does not restate the checkpoint table. The signed parent sections 3 to 8 are that table.

| Rule | Draft value this rehearsal follows | Status |
|---|---|---|
| RSI | 14, below 35, Wilder `_rsi` on closes through *t* | Existing parent. Follows signature. |
| Short-term low | Close equal to the minimum of the 10 sessions ending at *t* | Existing parent. Follows signature. |
| Alternative column | RSI below 40 and close at least 3% under SMA(10). Report-only. Not a family test. | Existing parent. Follows signature. |
| Fill | Next session's close. No fill when the next session is more than 5 calendar days after *t*, or when *t* is the last bar. | Existing parent. The session is a SEP date of that name. |
| Primary exit | Signed checkpoint ladder, fail-to-launch at session index 63, time cap at 252 | Existing parent. Follows signature. |
| Comparison exits | `draft_v0_exit` and `ladder_no_deadline` on the same entries | Existing parent. |
| Thesis confirm | 2 consecutive observations | Existing. |
| Recovery label | 8% under the fill before launch. The label sells nothing. | Existing parent. |
| Cooldown | 10 sessions after the exit fill | Existing parent. |
| Stake | 100 USD per entry | Existing fixed-stake default. Episode percent does not use the stake. |
| Maturity | Fill at least 63 sessions before the scoring date | Existing parent. |
| Shadows | `decline_rejected_shadow`, `sector_rejected_shadow` | Existing parent. |
| Controls | Buy-on-signal, and leave-tier | Existing parent. Screen runs are the cache dates. |
| Bench | `deep_dip` (8% below the close 20 sessions earlier) and `revenue_growing` | Existing parent. `fcf_agrees` is omitted here. |
| Channels | `channel_columns`, version `channel_v0` | Existing. The runner calls that function. |
| Price features | 60-session volatility, close versus the 200-session average, fall from the 252-session high, 126-session return, position in the 126-session high–low range, 20-session return, RSI(14), on the prefix through *t* | Existing parent list. The high–low range and the 252-session high use adjusted highs and lows when `hl_basis` is `high_low`, and closes when it is `closes`. |
| Regime split | At least half of the universe's names with 200 bars closed above their 200-session average. Fewer than 5 such names is `regime_unknown`. | Existing parent section 8. |

A name whose successive SEP dates have more than 5% of gaps longer than 5 calendar days is `chart_not_daily` and is not traded. That share is the parent's proposed chart check.

## 4. Prices, fills, costs, and the matched basket

| Item | Value | Status |
|---|---|---|
| Tape | `daily.csv.gz` from `daily_adjusted_ohlc`. One row per name per SEP date. | Existing adapter output. `prices.csv.gz` is the screen's sparse horizon file and is not this tape. |
| Total return | `close` on that file is SEP `closeadj` (splits, dividends, spinoffs). | Existing. hsr price basis, and the parent's adjusted-close basis. |
| Session | A date present on that name's SEP rows. A US holiday is not a session and is not a gap. | Proposed mapping of "chart session". |
| High and low | Adjusted `high` and `low` (`raw * closeadj / close`) when the export contains those columns. | Existing `daily_adjusted_ohlc`. SEP's published columns include them. |
| `hl_basis` | `high_low` when the export has `high` and `low`. `closes` when either column is absent. `partial` when `channel_columns` finds a mix on the recent window. | Existing `channel_columns` labels. Proposed detection: the runner checks the export headers **before** `load_stocks` copies `close` into a missing high or low. |
| Open | The daily file has an adjusted open. Fills stay at the next close. | Existing parent fill. The open is unused. |
| Decisions | One pass over one download. Launch, floor, exit, and recovery are decided once. A closed return is the pair of `closeadj` values from that download. | Existing parent section 7, on a single file rather than a daily refresh. |
| Gap | No fill across more than 5 calendar days. A Friday signal fills Monday, or Tuesday when Monday is a holiday. A hole longer than 5 calendar days drops the signal. | Existing parent rule on the US calendar. |
| Delisting, baseline | A name whose prices end before the required fill, and whose `tickers.isdelisted` is `Y` or whose `actions` row is a merger exit, exits at the last `closeadj`. Haircut 0. Label `delisted` when no exit was already signalled. An exit already signalled keeps its label; the delist price is the fill. | Proposed fill, so a dead name does not stay open forever. Haircut 0 is the existing hsr baseline. |
| Delisting, sensitivity | The same path with haircut −0.30 for a delisting that is not a merger. Mergers stay at 0. Merger actions: `acquisitionby` and `mergerto` on `ticker`, `mergerfrom` and `acquisitionof` on `contraticker`. | Existing hsr sensitivity. |
| No delist flag and a hole | The episode stays open. A missing quote is a blank mark, not a zero. | Existing parent mark rule. |
| Entry that cannot fill because the name has already delisted | No episode. Scratch count `delisted_before_fill`. | Existing parent: no next bar, no entry fill. |
| Warm-up | Daily bars from 420 calendar days before the first screen date (`DAILY_HISTORY_DAYS`). A name is not eligible until the rule's own history exists. | Existing adapter constant. |

Costs are the strategy book's US rows, not the mid-cap screen replay's 0.225% per side. That 0.225% prices a screen-spread. This book prices an episode.

| Market | Buy | Sell | Round trip | Status |
|---|---|---|---|---|
| `sp500` | 0.175% | 0.175% | 0.35% | Existing. `costs_for_market("sp500")`, source `t212_invest_fair_v1`. 0.15% FX plus 0.025% half-spread each side. |
| `sp400` | 0.175% | 0.175% | 0.35% | Existing. `costs_for_market("sp400")`, same components. |
| Stress | 3% per side, report-only | | | Existing. `LEGACY_STRESS_TRADE_COST_PCT`. |

Episode return is `exit_fill / entry_fill − 1 − buy − sell`. The stamp is these two rows. There is no FX series in the adapter, so no sterling translation is computed. The step 3.2 sterling slot book is not a board here.

**Matched basket.** For each episode, the equal-weight gross return of every name in **that episode's universe** whose raw cache `signal` was `buy` or `strong_buy` on the cache row carried onto the signal session, the traded name included, from the episode's fill session to its exit session, on `closeadj`. Matched excess is the episode's gross return minus that basket return. Costs cancel. A basket with fewer than 5 priced names uses that universe's whole carried screen instead, and the episode records `basket_fallback`. A basket name that delists uses the same haircut as the variant then being scored. These are the parent section 1 basket rules, with the universe in place of the forward market.

## 5. Windows and the reused confirmation bar

An episode belongs to the window that contains its **signal session**, not its fill and not its exit.

| Window | Signal sessions | Role | Status |
|---|---|---|---|
| Development | 2000-01-01 through 2012-12-31 | Rank features and the two bench candidates. Descriptive intervals only. | Existing hsr split, on daily signal sessions. |
| Confirmation | 2013-01-01 through 2025-09-30 | Confirm or reject, once. | Existing hsr split. |
| After 2025-09-30 | No new signal session. | An exit or a fill from a signal inside a window may use later prices, through the download's last session. | Proposed, so a September 2025 entry is not censored at the window's last day. |

The first hsr development rebalance is 2000-01-31. This registration does not extend the screen to 1999. Sessions in January 2000 have no prior cache row, so the first entries fall after that first cache date. The window bound is still 2000-01.

Development episodes may exit on 2013 prices. Those episodes stay in the development block. They are not confirmation entries.

### The confirmation window is reused

The window is **reused** for the value screen and **unscored** for this book's entry, exits, and gates. It is not sealed.

| Instrument | What it did with 2013-01 to 2025-09 | Status |
|---|---|---|
| hsr-v1 | Revealed 2026-10-10 (`holdout_reveals` at 2026-10-10T14:13:52Z). Spent. Its own primary was inconclusive. | Revealed. |
| hsr-mid-v1 | Revealed 2026-10-10 (2026-10-10T14:18:50Z). Spent. | Revealed. |
| hrs-v1 | Revealed 2026-10-10 (2026-10-10T14:23:41Z). Spent. | Revealed. |
| hms-v1 | Revealed 2026-10-10 (2026-10-10T14:25:45Z). Spent. | Revealed. |
| hsr-v2 | Holds the window. `holdout_reveals` is empty. | Sealed for its own reveal. |
| hsr-mid-v2 | Holds the window. `holdout_reveals` is empty. | Sealed for its own reveal. |
| hrs-v2 | Holds the window. `holdout_reveals` is empty. | Sealed for its own reveal. |
| hms-v2 | Holds the window. `holdout_reveals` is empty. | Sealed for its own reveal. |

The parent amendment names hsr-v1, hsr-v2, and hrs-v2. The table adds the mid-cap sibling and the model-mix search because they used the same dates. None of them scored this book's ladder, gates, or bench. Their reveals are why this window is called reused. They are not extra factors in the family size below.

### Bonferroni family

The uncorrected interval is the 90% interval (family error 0.10). Each test uses a two-sided interval at coverage `1 − 0.10 / m`.

| Test | Statistic on confirmation entries | Status |
|---|---|---|
| Primary | Median matched excess of mature episodes. | The one primary test. |
| `deep_dip` | Mean fair-cost return of the kept entries minus the mean of all book entries. | One bench test. |
| `revenue_growing` | The same difference, on its own kept set. | One bench test. |

**Family size m = 3** (proposed count of the tests above). Coverage is `1 − 0.10 / 3` = **96⅔%**. Each tail is `0.10 / 3 / 2`. The parent's worked example, 5 tests and a 98% interval, is the same formula with a different count. `fcf_agrees` is not in the family.

These are computed and kept, and they are **not** tests: the fair-cost median (it is a companion of the primary, section 6), per-market boards, both comparison exits, both shadows, both controls, the alternative entry, the four regime cuts, the 200-session regime split, the delisting sensitivity, the capital view, the channel splits, the selection fifths, and the stress view.

The interval is 10,000 resamples of whole ISO entry weeks of the signal session (the step 3.2 resampling count; it follows the signature if that count changes). The committed result is the point estimate and the two percentiles. The week-level vector is not committed.

A candidate also needs the same sign of its point estimate in both confirmation halves: signal sessions 2013-01-01 through 2019-06-30, and 2019-07-01 through 2025-09-30 (proposed split). The halves are a condition of that candidate's verdict. They are not two more tests.

## 6. Pre-registered outputs and verdicts

Development is scored and reviewed before any confirmation aggregate is written. The runner refuses a confirmation aggregate until the reveal step. Building a signals cache writes screen signals for every date onto local disk. That cache stays outside the repository. Committing hsr, hrs, or hms holdout results is not part of this run.

### Computed on development

The development block of the results store, and nothing from confirmation:

- Counts, the fair-cost median and mean, the matched-excess median and mean, the entry-week standard error, the share above zero, and the uncorrected 90% interval, labelled `development_descriptive`.
- Launch, floor, fail-to-launch, thesis, review, time cap, recovery, and baseline delisting counts.
- Selection-board fifths for the features in section 7, and the rank of those features by the gap between the top fifth and the bottom fifth of median fair-cost return.
- The two bench candidates' development differences, labelled descriptive. A high development rank does not add, drop, or retune a candidate.
- Comparison exits, shadows, controls, channel splits, the price regime split, the capital view, stress, and per-market boards.
- Regime cuts whose signal sessions fall in 2000-01-01–2002-12-31 and 2008-01-01–2009-12-31.
- The development delisting sensitivity (haircut −30% on non-merger delistings).

The 2020 and 2022 cuts are confirmation outputs. They are not written in the development block.

### Sealed before the reveal

The committed development block. After that commit, the runner overwrites it only under a logged amendment that says the block was recomputed because the code was brought into line with this text. The owner review changes no registered number.

### The single reveal

One reveal step writes the confirmation block: the same boards for confirmation signal sessions, the 2020 and 2022 regime cuts, and the verdicts below. A second reveal is exploratory and is not evidence. The store records one `reveal.at` and `reveal.evidence` true only for the first.

The reveal does not reveal hsr-v2, hsr-mid-v2, hrs-v2, or hms-v2. It does not commit screen spreads, rank IC, or per-model results.

| Verdict | When it is issued | What it means for the forward bench |
|---|---|---|
| Primary `pass` | The 96⅔% interval of median matched excess lies wholly above zero, and the fair-cost median is above zero. | Method evidence that the signed timing rule beat holding the US buy tier on this window. The bench is unchanged. No promotion. Parent section 1 is not passed. The thickness gate does not count these episodes. |
| Primary `fail` | That interval lies wholly below zero, or the fair-cost median is zero or below. A costs failure with the excess interval still above zero is `fail_costs`. An excess failure is `fail_excess`. | Method evidence against the timing rule on this window. The forward book still runs under the signed id. The next version review reads the fail before it promotes a filter that only reshapes the same entry. The fail does not open a new registration by itself. |
| Primary `inconclusive` | The interval covers zero, and the fair-cost median is above zero. | No bench consequence. |
| Candidate `pass` | That candidate's 96⅔% interval lies wholly above zero, and both confirmation halves have a positive point estimate. | Method evidence for the filter. The slot stays. Promotion still requires the forward bar on forward episodes. |
| Candidate `fail` | The interval lies wholly below zero. | Method evidence against the filter. The slot stays until a version review. That review does not promote it on forward evidence without this fail written beside the forward score. The rehearsal does not retire the slot. |
| Candidate `inconclusive` | The interval covers zero, or the halves disagree in sign. | No bench consequence. |

### Delisting sensitivity

After the reveal, the confirmation primary is scored again with the −30% non-merger haircut. This is not a second reveal and not a fourth test. A primary `pass` that is not a `pass` under the sensitivity is stored as `pass_delisting_sensitive` and is not a clean pass. The clean-pass flag is withdrawn. The baseline verdict remains in the store next to it.

### Regime cuts

Report-only. Signal-session cohorts, not holding-period cohorts. Median fair-cost return, median matched excess, counts, and launch share, for:

| Cut | Signal sessions | When it is written |
|---|---|---|
| 2000–02 | 2000-01-01 through 2002-12-31 | Development block |
| 2008–09 | 2008-01-01 through 2009-12-31 | Development block |
| 2020 | 2020-01-01 through 2020-12-31 | Reveal |
| 2022 | 2022-01-01 through 2022-12-31 | Reveal |

The parent section 8 split (share of names above the 200-session average) is a separate report-only board, on both windows.

### Kept as description, not as a verdict

Computed on each window before deletion, because they cannot be rebuilt later: the 5th percentile of the fair-cost return, the reference slot book's maximum drawdown, and the month series in section 7. None of them is a family test. The slot book uses 20 slots, ties by ticker, and 15 orders from seed `20261104` (proposed). It does not change an episode return.

## 7. What is kept after deletion

The licence allows research outputs and summary statistics. It requires deletion of raw tables, caches, and anything that could rebuild the tables. It forbids publishing a judgement of the data's quality. `build_report.json`, column fill rates, and vendor-coverage tables stay in the build directory and are never committed.

A committed cell with fewer than 5 episodes (proposed) publishes the count and suppresses return statistics. A single name's return is a per-name value and is not kept.

### Store written by this package

`docs/data/strategy_book_us_rehearsal_registration.json`

The seal draft. Rules, windows, family, mappings, and status. No results and no market data.

### Store the runner commits later

`docs/data/strategy_book_us_rehearsal.json`

No other path is a rehearsal store. Fields:

| Field | Contents |
|---|---|
| `registration_id` | `strategy-book-us-rehearsal-v0` |
| `parent_registration_id` | The signed parent id |
| `screen_code_fingerprint` | Fingerprint the caches were built with |
| `universe_basis` | `sp500_members` and `cap_rank_501_1000` |
| `family` | `m`, coverage, and the three test names |
| `development` | The development block in section 6 |
| `confirmation` | Null until the reveal, then the confirmation block |
| `reveal` | Null, or one `{at, evidence}` |
| `delisting_sensitivity` | Development copy, and the confirmation copy after the reveal |
| `regime_cuts` | The four cuts, each in the block section 6 allows |
| `month_series` | Per calendar month of signal sessions: `month`, `episodes`. When `episodes` is at least 5: `fair_cost_median`, `matched_excess_median`. |
| `licensed_data` | `first_used_at`, `deleted_at` |
| `amendments` | Logged markers |

Inside a window block, and only as aggregates:

| Group | Fields |
|---|---|
| Counts | Episodes, mature episodes, entry weeks, and counts by market, exit reason, shadow, control, `hl_basis`, `sector_basis`, `basket_fallback`, `f9_unverified`, `research_absent`, `delisted`, `chart_not_daily` |
| Primary | Fair-cost median and mean, matched-excess median and mean, entry-week standard error, share above zero, mature count, entry weeks, interval `{coverage, low, high}` |
| Companion | Fair-cost median interval, labelled descriptive and not a second test |
| Slices | Launch share, median sessions to launch, floor-exit count and median, fail-to-launch count and median, thesis count by reason code, review and time-cap counts, recovery count |
| Paired columns | For each comparison exit, shadow, control, and the alternative entry: difference of means, entry-week standard error, counts |
| Bench | For each of the two candidates: kept share, mean difference, interval, halves' signs, verdict (confirmation only; development verdict is null) |
| Selection | For each feature: fifth index 1–5, count, and median fair-cost return when the count is at least 5. No feature value that identifies a name. |
| Channels | Counts and medians by 6-month band bucket and by 6-month direction |
| Regime | Counts and medians for above, below, and `regime_unknown` |
| Capital | Capital-days return, recovery-hold share of stake-days, slot-book annualised return, drawdown, and the median across the 15 orders. No holdings list. |
| Tails | 5th percentile of the fair-cost return |
| Flags | `single_market_dependence`, `pass_delisting_sensitive` |

Forbidden in either committed file: ticker, name, a price, a fundamental, a per-episode return, a per-week return vector, a signal-cache row, a panel row, a path under `~/sharadar`, and an API key.

## 8. Owner run plan

Personal-use licence only. The key stays in an environment variable on the owner's machine. It is not put in the repository, in chat, or in cloud secrets. Raw and derived files stay outside the repository. The repo is public.

Access ends **2026-11-09**. Treat that date as the cancellation date unless the owner cancels earlier. Deletion is due within 30 days, which is **2026-12-09** if access ends on 2026-11-09.

### Before 2026-11-09 — download

Download **every** table in the bundle, not only the five the adapter reads. The same list as the [screen-replay day plan](historical-screen-replay.md#the-month-day-by-day):

`fundamentals`, `stocks`, `tickers`, `actions`, `sp500`, `daily`, `metrics`, `events`, `descriptions`, `funds`, `insiders`, `holdings`, `holdings_ticker`, `holdings_investor`.

```bash
mkdir -p ~/sharadar && cd ~/sharadar
for t in fundamentals stocks tickers actions sp500 daily metrics events \
         descriptions funds insiders holdings holdings_ticker holdings_investor; do
  curl -fL -o "$t.csv.zip" \
    "https://api.sharadar.com/v1.0/data/$t?api_key=$SHARADAR_API_KEY&years=full"
done
```

Vendor: sharadar.com direct, not Nasdaq Data Link. Full history (`years=full`). The adapter reads `fundamentals`, `stocks` (SEP), `tickers`, `actions`, and `sp500`. The other tables are downloaded so a question that needs them can still be asked inside the month. This registration does not score them.

Do this download even if the parent is still unsigned and the walker is not merged. The walk can wait. The download cannot.

### After access ends, inside the 30 days

Anything that reads the local files can run after 2026-11-09. The API is not required once the zips are on disk. If the walker is still missing when the 30 days end, the files are deleted anyway and this registration is not scored.

The order is **development, review, reveal**. Copy-paste commands for these steps are in the [owner runbook](strategy-book-us-rehearsal-runbook.md).

| Step | What happens |
|---|---|
| Build | `ftse-historical-replay build-panel` for the S&P 500 universe and again with `--universe midcap`. Outputs stay under home-directory build dirs, not in the repo. |
| Caches | Baseline signals caches for hsr-v2 and hsr-mid-v2. Do not pass `--reveal-holdout`. Do not run `ftse-rule-search reveal` or `ftse-model-mix reveal`. |
| Development | The walker on development signal sessions only. Commit the development block of `strategy_book_us_rehearsal.json`. |
| Review | The owner reads that block. No registered number changes. An adapter bug fix is an amendment (section 9), then development is recomputed before the reveal. |
| Reveal | The one reveal step. Then the confirmation delisting sensitivity. Commit the confirmation block. |
| Delete | Delete `~/sharadar` and every derived directory: both build dirs, every `signals_cache*.csv.gz`, `daily.csv.gz`, panels, and the rehearsal scratch. |
| Confirm | `ftse-historical-replay confirm-deleted`, and set this store's `licensed_data.deleted_at` to that same timestamp. |

`confirm-deleted` already has a `deleted_at` from the October 2026 screen-replay month, so the ops-monitor deletion warning does not arm itself again for this download. The checklist item is the reminder. The rehearsal store's own `deleted_at` is the record for this month. Re-arming that warning is queued behind P1/P2 as L677.

`build_report.json` is read locally and is not committed (licence §8).

## 9. Freeze and amendments

**Frozen by this draft, before any score:** the question in section 1, the universe mapping, the part-by-part reading, the price and cost basis, the windows, the family and its coverage, the verdicts, the kept fields, and the deletion list.

**One adjustment before the first development score.** The owner may change a **proposed** number in this file once, in a note, before `strategy_book_us_rehearsal.json` contains a development block. The owner may not add a test, a price stop, or a third bench column except by the parent signature rule in section 10.

**After the first development score is committed:**

| Change | What happens |
|---|---|
| A bug fix that makes the runner or the adapter match this text | A logged amendment on this same `registration_id`. The note says what was wrong. The development block is recomputed only when the note says so. History is not quietly rewritten. |
| An adapter fix discovered before the reveal | The same kind of amendment, logged **before** the reveal. The reveal then uses the corrected development block. |
| Any registered number, the family, the windows, or which column is a test | A new `registration_id`. The old store stays under the old id. |
| A second confirmation look after the reveal | Exploratory. Not evidence. |

No registered number changes after the first development score. That includes RSI, the ladder, the windows, the family size, the haircuts, the cost rows, and the gate thresholds stamped in section 3.

## 10. Dependencies

Two things have to be true before the first development score:

1. **The parent signature.** `owner-strategy-book-v0` is signed, and `docs/data/strategy_book_registration.json` exists with that note. This rehearsal's rules are frozen there.
2. **The walker package.** `strategy_book_observe.py` walking `strategy_book_rules.py`. The runner imports that walker.

**Default when the signature changes a parent number.** The rehearsal follows the signed number. This file is amended to that number before the first development score, one amendment listing each changed number. The rehearsal does not keep the pre-signature draft beside a different signed value. A signature that arrives after the first development score does not edit this id. The signed value would be a new `registration_id`.

The same default covers a Phase 1 signature that changes a decline-gate or sector-gate constant stamped in section 3.

The download in section 8 does not wait on either dependency. Scoring does.

This package does not add an ops-monitor finding. There is no runner yet. The human checklist is the gate. The runner package wires the scheduled finding when it lands.

## 11. Where the adapter does not have what the rules read

| Gap | What the rules ask for | Proposed handling |
|---|---|---|
| No S&P MidCap 400 constituent history. Tables the adapter loads are `fundamentals`, `stocks`, `tickers`, `actions`, `sp500`. | `sp400` members on each date. | Cap ranks 501–1000, `universe_basis` `cap_rank_501_1000`, carried from month-end to month-end. Costs and boards still use market id `sp400`. |
| `build_replay_inputs` asks `membership_on` for month-ends only. | `sp500` membership on every session. | Call `membership_on` with every SEP date. The function already accepts that list. |
| `load_stocks` copies `close` into a missing `high` or `low`. | Highs and lows, or an honest `hl_basis`. | SEP's columns include high and low, and `daily_adjusted_ohlc` writes adjusted highs and lows. If a header is absent, detect it before that copy and record `hl_basis` `closes`. |
| `ACTIONS` is loaded only to classify mergers. | A corporate-action ledger (dividend pay dates, split events, spinoff shares) if a raw-price book needed one. | This book scores `closeadj`, which already includes splits, dividends, and spinoffs. Actions other than the four merger labels are not applied again. The phase 5.1 raw-price ledger is not this rehearsal. |
| The daily file contains `open`. | The parent fill is the next close. | Open is unused. Next-open fills stay the later twin (L667). |
| `build_panel` does not write `opinc`, `epsdil`, `eps`, or `fcf` through to a daily file. It does load ART and ARQ while it builds. | The decline checks in section 3.2. | The runner reads those indicators from the fundamentals export with the lag rules in section 3.2. This package does not change the adapter. A missing column leaves that check not evaluable. |
| ARY is not loaded. | The live gate's fiscal-year comparison. | Annual checks use ART TTM, `statement_basis` `art_ttm`. |
| No filings-index headlines. `events` is in the bundle and is not classified. | Profit-warning and impairment checks. | Absent. They do not fire. |
| No `interim_dividend_cut_flagged`. | The dividend soft check. | Absent. `dps` is not a substitute. |
| No half-year extracts, highlights, or screen interim fields. | The live interim priority list. | Interim revenue and interim EPS use ARQ only. |
| `tickers.sector` is the sector on the download. | A sector label as of the session. | Use it on every date. `sector_label_basis` `tickers_current`. Part 3 is price breadth only. |
| No research verdict, memo, F9 bind, or `adjusted_signal`. | Parent sections 2 and 5. | Labels in section 3.4. `fcf_agrees` is not a test. |
| No historical Trading 212 catalogue and no FX series. | `t212_listed`, and a sterling slot book. | Both `not_applicable`. |
| Signals-cache columns are `as_of`, `ticker`, `signal`, `conviction_score`, `sector`, `earnings_yield`, `composite_score`, `data_quality_score`, plus `pass__*` and `score__*`. | The parent selection-board list. | Section 12, question 4, is the default for panel fields. `signal_rank`, `signal_trend`, `roic_proxy`, and every research feature stay absent. |
| `prices.csv.gz` is not a daily tape. | Daily closes. | Use `daily.csv.gz`. |

## 12. Open questions

Each default is what this draft seals if the owner is silent. A change is the one pre-score adjustment in section 9, or the signature rule in section 10.

1. **`sp400` membership.** Default: hsr-mid cap ranks 501–1000, carried month to month, market id `sp400`, overlaps kept in `sp500` only. A constituent history is a new id.
2. **Sector pooling.** Default: none. Price-only, each universe alone. `sector_basis` is `price_only`.
3. **Dividend and headlines.** Default: the checks stay absent and do not fire. No DPS rule and no `events` phrase scan.
4. **Panel fields on the selection board.** Default: the carried panel row may fill a listed feature the cache does not hold. Allowed fills: `market_cap`, `profit_margins`, `debt_to_equity`, `revenue_growth`, `earnings_growth` from the panel; `fcf_yield` as panel `free_cashflow / market_cap` when market cap is positive; `ev_ebit` as panel `enterprise_value / ebit` when ebit is positive. Label `source` `panel` or `panel_ratio`. These fills do not change eligibility. `earnings_yield` is the cache column of that name.
5. **Counts derived from the cache.** Default: `weeks_at_signal` is the number of consecutive month-end cache rows, through the carried row, with `signal` in `{buy, strong_buy}`. `models_passed` is the count of true `pass__*` flags. `signal_rank` and `signal_trend` stay absent.
6. **Trading 212.** Default: `not_applicable`. Today's catalogue is not painted backward.
7. **Confirmation halves.** Default: 2013-01-01 through 2019-06-30, and 2019-07-01 through 2025-09-30.
8. **Small cells.** Default: under 5 episodes, publish the count and suppress the return.
9. **Primary statistic.** Default: one test, the confirmation median matched excess, at the Bonferroni coverage. The fair-cost median must be above zero or the verdict is `fail`. Per-market medians are not extra tests. The other instruments in section 5 are not extra factors.
10. **Parent signature.** Default: follow the signed numbers. Amend this file before the first development score.
11. **January 2000.** Default: do not build a December 1999 screen. Entries start after the first development cache date.
12. **Prices after 2025-09-30.** Default: allowed as fills and exits of signal sessions inside a window. No new signal session after 2025-09-30.
13. **Delisting and a clean pass.** Default: a primary pass that fails the −30% sensitivity is `pass_delisting_sensitive` and is not a clean pass.
14. **Slot-book seed.** Default: seed `20261104`, 15 orders, ties by ticker. Descriptive only.
15. **Sterling.** Default: not computed.
