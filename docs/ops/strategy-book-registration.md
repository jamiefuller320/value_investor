# Strategy book registration

**Status: DRAFT — awaiting owner signature (Phase 2 gate).**  
**registration_id (proposed):** `owner-strategy-book-v0`  
**Deferred:** N249  
**Plan step:** 2.1 in [`strategy-reorientation-plan.md`](strategy-reorientation-plan.md)  
**Strategy spec:** [`PROJECT_OBJECTIVE.md`](../PROJECT_OBJECTIVE.md#investment-strategy-owner-2026-11-03)  
**Human checklist:** `adhoc-strategy-phase-gate` in [`human-tasks-checklist.md`](human-tasks-checklist.md#ad-hoc-when-triggered)

This document freezes the rules before any score is computed. It does not open a book, write a store, or run a replay. Step 2.2 (archive replay) and step 2.3 (forward book) wait until the owner signs, adjusts a listed number once, or rejects.

Every number in the rule tables is **proposed** unless the row says it is an existing constant that this book stamps unchanged. The owner may change a proposed number once, in the signature note, before any score store exists. After the first score store is committed, section 10 applies.

`owner-strategy-book-v0` means this first registration of the owner's seven-part strategy. It is an observe instrument. `influences_live` is false. It does not write strand A, `buy_tier_level`, knobs, or `decision-review --apply`.

No language model chooses an entry, an exit, or a review. The book reads the research verdict already logged on the screen row. A later package that adds a model veto stays a shadow until `authorize_live_llm_influence()` allows it ([`llm-live-path-evidence.md`](llm-live-path-evidence.md)).

## 1. Learning question

On FTSE 350 names that pass parts 1–3 and the current F9-B input-quality gate, does a fixed stake bought at the registered short-term low and sold at the registered short-term high — or held under the registered recovery rules — produce a **positive median fair-cost episode return**?

That question is false when, at the thickness gate in section 9, the median fair-cost return across all closed episodes is zero or below. The book then stays observe-only. A different rule is a new `registration_id`. This one is not edited to make the median positive.

Two results sit beside that and still mean stop or redesign, by a new registration:

- The swing-high median is positive and the combined median is zero or below. The recovery holds are what failed. A price stop is not added to this id. A price drop never sells.
- The forward book has run 26 weeks (proposed) and still has fewer than 48 closed episodes. The rule is too rare on this universe to answer the question. The thresholds stay as written.

A positive median on a thinner sample is not a pass. Forty-eight episodes are a look, not a measurement of a small annual edge. Forward paper evidence cannot resolve a 3% a year edge on a short window ([`historical-screen-replay.md`](historical-screen-replay.md#why) records years-to-detect of 125–900, and about 150 non-overlapping monthly cohorts before a 30-day screen spread is even discussable). Read a pass here as "this sample did not lose after fair costs."

The archive rehearsal in section 9 does not answer the question. It has no point-in-time operating-decline or sector verdicts.

## 2. Universe and eligibility

Parts 1–3 of the strategy, plus the input-quality gate the project already uses for named stocks (F9-B). All of them are true on the decision date. One failure, or a missing input, means the name is not eligible. `insufficient_data` is not a pass.

v0 is the live FTSE 350 screen only. Chart files for other markets stay out of the book. Phase 6 is where admitted markets can join, as a new registration.

| Check | Proposed value | Why |
|---|---|---|
| Universe | FTSE 350 names on the archived or live screen | The live screener stays on the FTSE 350. Charts cover about 1,269 names across markets; those other markets are a later book. |
| Part 1, cheap | Raw screen `signal` is `buy` or `strong_buy` | The owner's value set. Same pair as `BUY_SIGNALS` in `paper_fund.py`. |
| Part 2, not declining | Operating-decline verdict `clear` | Gate on main: `operating_decline_gate.py`. `declining` and `insufficient_data` both fail entry. |
| Part 3, sector sound | Sector verdict `sound` for the sector on that screen row | Gate runbook on `origin/cursor/sector-gate-to-main-567c` (`docs/ops/sector-headwind-gate.md`). The module is not on main yet. `headwind` and `insufficient_data` both fail entry. |
| F9-B | All four binds true: `key_filing_bodies`, `fcf_basis_bound`, `overlay_bound`, `memo_recent` | Same fields as `decision_input_inventory.py`. Memo age uses the existing 21-day maximum. |
| Missing chart, RSI, or a usable next bar | Not eligible | A rule that cannot be priced is not a trade. |

**Decision date.** For the forward book, the ops-monitor run date (UTC). For the archive, each chart session.

**When a weekly screen may be used.** Screen runs are weekly. A run applies to chart sessions strictly after the run's calendar date. The run dated 2026-11-01 qualifies later sessions. It does not qualify the 2026-10-30 close that had already happened. The latest such run is carried forward until the next one. Leaving the buy tier later does not close an open episode (section 4). It does stop a new entry.

**Gates.** A decline or sector verdict applies to sessions strictly after that store's `as_of` date. The name's sector is the sector on the screen run used for that session. A headwind in some other sector does not count. No dated verdict means not eligible.

**F9-B, computed the way the inventory does today.** Filing bodies from the filings index meta (`key_bodies`). FCF basis is bound when the screen row's `fcf_basis_overlay` is a boolean. Overlay is bound when a research verdict is present and `adjusted_signal` is set. The memo is recent when its last activity is within 21 days. The forward job computes this at run time from files dated on or before the decision date. The current `decision_input_inventory.json` snapshot is not a history.

`adjusted_signal` is stored on the episode. It does not decide part 1 under the default in section 13. Research `caution` and `neutral` leave the name eligible. A research verdict that `core_sell_reason` treats as failed (`pass`, `sell`, `avoid`, `exit`) makes the name **not eligible**: every fact that is a thesis break in section 5 also blocks entry, so the book never buys a name it would be obliged to sell. (Supervisor review, 2026-11-03.)

**Point in time.** Indicators on session *t* use that ticker's closes up through *t* only. The chart file also holds later closes. The walker slices them off.

## 3. Entry rule

One primary rule. One pre-registered alternative, scored only as a rehearsal column. The alternative does not open forward episodes on this `registration_id`.

The signal is computed from daily closes only, so the archive can replay it. The existing timing helpers are the source of the thresholds. They are not the signal itself. Reasons are in section 12.

### Primary rule (proposed)

On the close of chart session *t*, all of the following are true:

1. The name is eligible on date *t* (section 2).
2. The name has no open episode, and the re-entry cooldown in section 6 has elapsed.
3. The recovery-hold cap in section 6 is not blocking new entries.
4. RSI(14) of the closes through *t* is below **35**.
5. The close is the lowest close of the **10** chart sessions ending at *t* (ties count). A shorter history does not fire.

RSI is `technical_analysis._rsi`: Wilder smoothing via pandas `ewm(alpha=1/14, min_periods=14, adjust=False)`. That is the RSI behind the published trade plan. `n215_technical_veto_observe._rsi_wilder` seeds the average differently and is a different series. This book uses `_rsi` only. The walker runs it on the prefix of closes through *t*, not on a 10-day slice and not through `compute_indicators`.

`compute_indicators` returns no RSI until it has 200 bars (`MIN_BARS`). This rule needs a finite RSI(14), which `_rsi` produces after 15 closes. By the first archived screen (2026-08-02) the stored charts already have that history.

| Input | Proposed value | Why |
|---|---|---|
| RSI length | 14 | The period already implemented in `_rsi` and stored as `rsi_14`. |
| RSI level | below 35 | `TradePlanConfig.accumulate_rsi_limit_gate` is 35. Below that, an accumulate timing signal is allowed a market core order. 30 is the "oversold" point in `assign_timing_signal` and would fire less often. 35 stays inside the "below neutral" band, which starts at 45. |
| Low window | 10 chart sessions, close equal to the minimum | A short-term low. The trade plan's `recent_low_days` of 20 is a price level for a limit, not a signal. Ten sessions is about two weeks. Section 13 lets the owner set 20 once, at signature. |

### Fill (proposed)

The order is a market buy. It fills at the **next chart session's close**, not at the next open and not at a limit.

The committed charts have dates, closes, volumes, and sampled SMA50 / SMA200. They have no open, high, or low. Two files checked on this tree: `docs/data/charts/0001.HK.json` (493 bars, 2024-10-30 to 2026-10-30) and `docs/data/charts/IFX.DE.json` (507 bars, same span). Median gap is 1 day. There is no series to test a limit fill against, and `compute_trade_plan`'s tactical limit (5% under spot, the 20-day low, or a moving average) cannot be marked filled or missed from closes alone.

The entry price of the episode is that next close. The signal close is recorded and is not the fill. A gap up or down is filled and reported. It is not filtered.

No fill when the next stored session is more than **5** calendar days after *t*, or when *t* is the last bar. Five days covers a weekend and a holiday. A longer hole is a missing session. The signal is dropped. It is not filled on a later bar.

A forward chart whose latest bar is more than 5 calendar days behind the decision date produces no signal that day. The samples above were built on 2026-11-01 with a last bar of 2026-10-30, so lag of that size is real and must be counted.

### Pre-registered alternative (report-only)

RSI(14) below **40**, and the close at least **3 percent** under the 10-session simple average of closes through *t*. No 10-session-low test. Same exit, recovery, costs, and fill.

| Input | Proposed value | Why |
|---|---|---|
| RSI level | below 40 | `TradePlanConfig.accumulate_rsi_low` is 40, the level that already marks a deeper accumulate allocation. |
| Distance under the short average | 3 percent under SMA(10) | The other entry shape the brief allowed: a close below a short average. SMA(10) is computed in the walker from closes. The stored `sma50_series` is not the input. |

This column is the only alternative. There is no grid on 30 / 35 / 40 or on 5 / 10 / 20. It is frozen now, before any replay. It cannot replace the primary on this id, because the archive has no untouched holdout long enough to confirm a switch (section 10).

## 4. Normal exit

The normal exit is a short-term high on a position that has not become a recovery hold. Rank, top-N membership, and leaving `buy` / `strong_buy` do not close the episode. Those exits stay on the control described in section 8.

### Primary exit (proposed)

While the episode is still a swing, session *t* signals an exit when both are true:

1. The close is the highest close of the 10 chart sessions ending at *t* (ties count).
2. The close is at least the entry fill times `(1 + buy_cost_pct + sell_cost_pct)`.

The sell fills at the next chart session's close, with the same 5-day gap rule. No next bar means the episode stays open. The scored prices are the two fills.

The cost floor uses the fair FTSE table stamped in section 7. At today's table the round trip is 0.55%, so a fill at 100.00 needs a high of at least 100.55 before a swing exit can signal. The scored return subtracts the same costs again, via the usual episode formula, so a sale exactly at the floor scores about zero. A hit is a positive fair-cost return, which needs a slightly higher sale.

A 10-session high under that floor does not sell. If the close is also 8% under the fill, section 5 classifies a recovery hold instead. Between those two bands the episode simply stays a swing until a qualifying high, a recovery trigger, or a thesis break.

The trade plan's take-profit floors (`tactical_target_above_limit` 1.10, `tactical_target_above_spot` 1.08, plus a reward-to-risk floor) are pack levels for a tactical slice next to a core holding. They are not this exit. A fixed percent target would replace "sell the short-term high" with a different strategy.

| Input | Proposed value | Why |
|---|---|---|
| High window | 10 chart sessions | Same window as the entry low, so the swing is symmetric. |
| Cost floor | entry fill × (1 + fair buy + fair sell) | A high that does not clear the stamp and the spread is not a completed swing. Rates come from the table in section 7. |
| What does not exit | Leaving the buy tier, leaving a top-N list, a trade-plan stop, a trade-plan target | Part 5 of the strategy. The control in section 8 keeps the buy-tier exit so the difference can be reported. |

Worked swing. Fill 100. Cost floor 100.55. Session 6 prints a 10-session high at 103. The exit signals. The next close is the sale. Fair-cost return is `sale / 100 - 1 - 0.00525 - 0.00025`.

## 5. Recovery hold

A price drop never sells. It changes the label of the episode from swing to recovery hold. The hold then exits only on a recovery target, a thesis break, or the review rule below.

### When the swing becomes a hold (proposed)

On session *t*, if the episode is still a swing, it becomes a recovery hold when either is true:

- The close is at or below the entry fill times `(1 - 0.08)`.
- Fifteen chart sessions have passed after the fill session and the episode is still a swing. The fill session is index 0. The classification is evaluated when the session index reaches 15.

The 8% band reuses the distance already encoded as `tactical_target_above_spot` (8% above spot) and the neighbourhood of `support_floor_below_spot` (8% under spot). Here that distance classifies a hold. The trade plan's stop, which sells near that neighbourhood, stays unused.

The label does not flip back to swing if the price recovers. The exit is then a recovery exit, and the episode is scored on the recovery board.

### Recovery target (proposed)

The target is the **entry fill**. A later fair-value estimate is phase 4.1 (L662), not this registration.

A recovery hold signals an exit on session *t* when the close is at or above the entry fill. The sell fills at the next close. That sale can still be a small loss after costs, because the target is the gross entry price. The loss is reported. The target is not raised to cover stamp.

Once the target is the entry fill, a cost-clearing 10-session high is above the target, so the target is reached on the same bar or earlier. The high rule remains in force on a hold so part 5 and part 6 stay explicit. The target is the one that binds.

### Thesis break (proposed)

The same facts that forbid an entry can end a hold, and they can also end a swing before it ever becomes a hold. One implementation serves both, so the entry rule and the exit rule cannot drift. That is the constraint already written on the operating-decline gate.

A thesis break is any of:

| Fact | Source | Proposed reading |
|---|---|---|
| Operating verdict `declining` | The decline gate | Part 2 failed. |
| Sector verdict `headwind` | The sector gate, on this name's sector | Part 3 failed. |
| Screen `signal` is `avoid` | `core_sell_reason` in `core_sell_trigger.py` | Hard avoid. |
| Research verdict's first token is `pass`, `sell`, `avoid`, or `exit` | `core_sell_reason` | `pass` is this project's do-not-own verdict. |

`insufficient_data`, a missing store, a missing screen row, research `caution`, and research `neutral` are not breaks. A missing row leaves a streak where it is, which is what `note_thesis_streak` already does. `clear` and `sound` reset their own streaks. A one-day gap must not wipe a real decline, and it must not sell the hold.

Confirmation reuses `thesis_break_confirmed` with **2** consecutive observations, the live `DEFAULT_EXIT_CONFIRM_SCREENS`. Streaks are per reason. Screen and research observations are the weekly runs. Gate observations are successive `as_of` dates. Two weekly avoids sell. Two daily `declining` verdicts sell. One of each does not.

When a thesis exit and the recovery target signal on the same session, the label is `thesis_break`. A business that has failed is not scored as a successful recovery, even if the price happens to be back at the fill. The return can still be positive. It stays on the thesis-break slice.

### Review date (proposed)

The clock starts on the session that classifies the recovery hold. It does not start at entry. A swing that exits on a high never has a review.

| Review | Proposed action | Why |
|---|---|---|
| 63 chart sessions after classification, and again 63 after each roll | Re-read parts 2 and 3, the screen signal, and the research verdict. | 63 trading days is the patient horizon already sealed on N206. Here it is a review spacing, not an automatic sale. |
| Thesis already broken under the streak rule | Exit `thesis_break` at the next close. | The mid-hold rule has already fired, or fires on this read. |
| Decline is not `clear`, or sector is not `sound`, including missing and `insufficient_data` | Exit `review_insufficient_data` at the next close. | Mid-hold, a one-day gap does not sell. At the review, a long hold needs fresh evidence. A blank file ends the hold. |
| Screen row missing | Exit `review_insufficient_data`. | There is no current value-set fact. |
| Research verdict missing, while the gates are `clear` and `sound` and the signal is not `avoid` | Hold stands. | Research `pass` sells. A missing memo does not. Entry already required a fresh memo. |
| Gates `clear` and `sound`, signal not `avoid`, research not failed, and this is review 1, 2, or 3 | Roll the review forward 63 chart sessions. Record the roll. | The business case still stands. Part 6 says hold. |
| The same, on review 4 | Exit `review_cap` at the next close. | Part 6 names two exits: the recovery target and a thesis break. Part 7 also requires a review date so a hold cannot run without an end. Four reviews is 252 chart sessions, about a year. This third exit is the proposed end. Section 13 lets the owner replace it with a human hold at signature. |

Worked recovery. Fill 100. Close 91 on session 4. The episode becomes a recovery hold. No sale. Later the close prints 100.2. The target signals. The next close is the sale. If instead the next two decline-gate dates say `declining`, the sale is a thesis break even though the price never returned to 100.

Each session, the walker does these checks in order. The first one that acts ends the session for that name.

1. A confirmed thesis break signals an exit. The label is `thesis_break`.
2. A swing that prints a 10-session high at or above the cost floor signals a swing exit.
3. A swing that hits the 8% band or the 15-session mark becomes a recovery hold. No order.
4. A recovery hold whose close is back at the entry fill signals a `recovery_target` exit, unless step 1 already fired.
5. A review date applies the review table.

The exit reason is fixed on the signal session. The next close is only the price. A new fact on the fill day does not relabel an exit that was already signalled.

## 6. Limits

Fixed-stake v0, as in [`fair-cost-primacy.md`](fair-cost-primacy.md#fixed-stake-v0-default-new-observe--models). One stake per entry. No fund NAV, no cash balance, no equal weight, no DCA split. Episode percent does not depend on the stake. The stake is recorded so a later twin can scale it.

| Limit | Proposed value | Why |
|---|---|---|
| Stake | 100 GBP per entry | The standing fixed-stake default. FTSE prices are GBP (or a consistent pence series inside one chart; the return is a ratio on that one series). |
| Cash | No cash constraint | v0 parks fund construction. The recovery cap below is a count of episodes, not a cash rule. |
| Open episodes per name | 1 | A second signal while the episode is open is ignored and counted as `already_open_skip`. |
| Re-entry cooldown | 10 chart sessions after the exit fill | The same length as the entry window, so the sale session's own low cannot buy the name straight back. |
| Recovery-hold cap | Block new entries when recovery holds are at least 40% of open episodes and at least 5 episodes are open | Part 7. Stuck holds must not keep taking every new low. Below 5 open episodes the ratio is noise (1 of 2 is already 50%). |
| Cap action | Block, and count `cap_blocked` | Reporting the share without blocking does not do what part 7 asks. A blocked name is not queued. It has to signal again on a later day. |
| Names signalling on the same day | Take every name that passes | No top-N and no "cheapest first." The cap either allows the whole day or blocks the whole day. |

The cap is checked on the signal session, before a fill is scheduled. Recovery holds count as open episodes. The denominator is every open episode, swings included.

## 7. Costs

Primary costs are the fair FTSE 350 row in `market_trading_costs` (`costs_for_market("ftse350")`). The book stamps the table's buy and sell rates into the registration record when it seals. It does not invent a second schedule.

Today's table, which a seal on this tree would stamp:

| Leg | Value | Why |
|---|---|---|
| Buy | 0.525% (0.00525) | Existing table: 0.50% UK stamp plus 0.025% half-spread. No FX on a GBP book. |
| Sell | 0.025% (0.00025) | Existing table: half-spread only. Stamp is on the buy. |
| Round trip | 0.55% | Sum of the two legs. |
| Episode return | `exit_fill / entry_fill - 1 - buy - sell` | The same formula as `episode_return` in `n200_tech_timing_observe.py`. |
| Stress | 3% per side (0.03), report-only | `LEGACY_STRESS_TRADE_COST_PCT`. Subtract 0.06 from the gross return. Same role as on N200 and N206: a harsh churn view, not the decision number. |

Stress does not decide the learning question. It is published next to the fair-cost median.

Dividends are not added. Marks are price returns after trading costs. Total-return accounting is phase 3.1. Saying so here keeps a price rebound from being read as a total return.

## 8. Scoring

The decision number is one median: the fair-cost episode percent of **every closed episode**, swings and recovery holds together. A swing-only median is published beside it and cannot pass the gate on its own.

Open episodes are marked to the latest close for display, fair-cost as if closed. They are outside the median. A missing quote leaves the mark blank. It is not filled with zero.

| Board | Proposed contents | Why |
|---|---|---|
| Overall (primary) | Median fair-cost episode % of all closed episodes. Count. | The learning question. One number, after fair costs. |
| Swing highs | Count, hit rate (share with fair-cost return above zero), median return, median sessions from entry fill to exit fill. | "Did the short-term high work?" |
| Swing thesis breaks | Count and median return, separate from swing highs. | A thesis break during the swing is not a successful high and not yet a recovery loss. |
| Recovery target | Count, median sessions from classification to the target exit fill, median return. | Time to recovery, as the strategy asks. |
| Recovery thesis breaks | Count by reason code (`declining`, `headwind`, `screen_avoid`, `research_failed`), median return. | Loss on a broken business, kept off the recovery-success median. |
| Review exits | Count of `review_insufficient_data` and `review_cap`, with median return. | Included in the overall median. Shown on their own so a time cap is visible. |
| Stress | The same closed episodes at 3% per side. | Report-only. |
| Control | Paired episodes below. Difference of medians. | Report-only. No crown. |

**Control (report-only).** For each primary entry, a paired episode buys at the same fill. It sells when the raw `signal` has been outside `{buy, strong_buy}` for 2 consecutive archived runs, the live `exit_confirm_screens` value. The sale fills at the next chart close after the confirming run's date, with the 5-day gap rule. Same fair costs. If the name never leaves the buy tier, the control episode stays open and stays out of the control median.

That paired exit is the behaviour of `buy_tier_level` and of N200's leave-tier close. It is how this project already turns a buy-tier membership spell into a trade. The strategy book does not use it as an exit. The median difference is context for the owner. Beating the control is not the learning question, and losing to it does not by itself fail the question. Fair-cost primacy already treats control excess as report-only.

The control is not the live book's NAV. Live books have weights, cash, and a 3% stress stamp. Comparing NAVs would mix those choices with the timing rule.

**Archive versus forward.** The boards above are computed separately for the archive rehearsal and for the forward book. The two medians are never averaged. Only the forward book's overall median can meet the thickness gate.

## 9. Two evidence tracks

### (a) Archive replay — report-only

Step 2.2. It rehearses the price rules on history that already exists. It does not answer section 1, and it does not satisfy the thickness gate. It does not write a paper book.

**Prices.** `docs/data/charts/<TICKER>.json`, fields `dates` and `closes` only. On 2026-11-03 the tree holds 1,269 chart files. The shared writer is `build_price_chart_payload`. The two files read for shape are daily across about two years (section 3). The walker still checks each file: if more than 5% (proposed) of successive gaps are longer than 5 calendar days, the name is `chart_not_daily` and is not traded. Stored `sma50_series`, `sma200_series`, `levels`, `signal`, and `level_crossings` are ignored. Those levels are the trade plan at chart-build time (`levels_as_of` was 2026-11-01 on both samples). Using them for an older session would look ahead.

**Value set.** `docs/data/history/run_*.json.gz`, loaded the way N200 loads snapshots (`load_run_snapshots`). This tree has 30 run files, from `run_20260802_123417.json.gz` through `run_20261101_073321.json.gz`. Each has `run_at`, `signals`, and `prices`. The latest signals list has 248 rows, with `signal`, `adjusted_signal`, `research_verdict`, `sector`, `timing_signal`, and the trade-plan levels. Eligibility uses `signal`, `research_verdict`, and `sector` only, and only from a run dated before the session. Fills come from the chart closes. The snapshot `prices` map is a different series and can mix pence with pounds (`yahoo_price_units`). It is not a fill.

`docs/data/archive/` holds 23 dashboard bundles dated 2026-08-09 through 2026-11-01 (`2026-11-01.json` is a full publish, with `reports` and `run_at`). It is not a second signal source. A date that exists only there does not create an entry.

**How far back entries can go.** Closes start around 2024-10-30. Buy-tier runs start on 2026-08-02. Entries are allowed only on sessions that have a prior run, so the entry window is about thirteen weeks, not two years. The older closes warm RSI. They are not a hidden two-year test. There is no point-in-time value set for 2024 or 2025 in this repo.

**Gates.** The decline store on main is one snapshot, `as_of` 2026-11-03 (65 buy-tier names, 62 with a `clear` or `declining` verdict). The gate's own runbook says a past `as_of` fails closed, because statement files are overwritten on fetch. The sector gate is not on main. This replay therefore keeps three labelled results, and does not merge them:

| Result | What it applies | How to read it |
|---|---|---|
| `archive_buy_tier_only` | PIT buy tier, the price rules, and screen / research thesis breaks from the weekly row. No decline gate. No sector gate. F9 fields are absent on the run rows, so every episode is `f9_unverified`. | A rehearsal of parts 4–6 plus part 1. Not a test of parts 2–3. Not the strategy universe. |
| `archive_full_strategy` | The same, plus a committed decline verdict and a committed sector verdict whose `as_of` is usable for that session, plus F9 binds computed from files dated on or before that session. | This is the strategy. It stays empty until those dated verdicts exist. An empty board is published as empty. |
| `lookahead_current_gates` | Today's `clear` list and, once it exists, today's `sound` list, painted backward across the entry window. | Report-only. Lookahead. Never averaged into the other two. |

**Survivorship.** Charts exist for names that were charted at the build (`as_of` around 2026-11-01). A buy-tier name with no chart is counted as `no_chart` and is not an episode. Names that left the universe before they were charted are absent. This is not the survivorship-free tape used by the historical screen replay (active and delisted constituents). A chart that ends before the exit stays an open episode at the last close. No delisting price is invented.

**Lookahead, restated.** Price indicators are sliced at *t*. Screen facts come from an earlier run. Gate facts come from an earlier `as_of`, or they are left off. The chart's own `signal` field is the signal at build time and is not an entry. Today's decline verdicts describe current statements, including the latest fiscal year, and must not be treated as what an investor knew in August 2026.

**Dividends and opens.** Still absent, as in sections 3 and 7.

The alternative entry is scored only inside `archive_buy_tier_only`, as its own column, with the primary's exit and recovery rules. It does not share the one-name cap with the primary, because it is not a second book.

### (b) Forward observe book

Step 2.3, after this registration is signed and after the default in section 13 (wait for the Phase 1 signature, and wait until the sector store is refreshing on main).

The book then runs in daily ops-monitor, after the decline refresh and the sector refresh. It opens real observe episodes from that day forward. It does not backfill August–October 2026 into the forward median. Those months belong to the archive rehearsal.

Each day the job appends the verdicts it actually used (ticker, `as_of`, decline verdict, sector verdict, signal, research verdict, F9 pass or gap list). The live gate stores are overwritten in place. Without an append-only log, a later rebuild cannot show why a name was eligible. That log is part of step 2.3, not of this draft.

### Thickness gate (proposed) and the owner's decision

Both are required, on the **forward** book only:

| Gate | Proposed value | Why |
|---|---|---|
| Closed episodes | at least 48 | The figure named in the phase 2 plan, and the gate already used by N206. N200's 24 is a different instrument (membership spells, easier to accumulate). |
| Calendar span | at least 8 weeks (56 days) from the first entry fill to the latest chart session | Same "and 8 weeks" bar as N200 and N206. Eight weeks with 10 closes is not enough. |
| What does not count | Archive episodes, the alternative rule, open episodes, `pending_fill` | The gate is about a book that has been trading forward under signed rules. |

Until both are true, the result is inconclusive. The entry is not loosened to get to 48 faster.

When both are true, ops-monitor emits an info finding and the owner stamps one disposition. Nothing promotes itself (F8: an observe metric never applies knobs or fills, and it does not flip the primary learning track by itself).

| Disposition | When it fits | What it does |
|---|---|---|
| `design-open` | Overall fair-cost median above zero. | The owner may make this book the primary learning track. `buy_tier_level` and the matched-30 books stay controls. No live capital. No `decision-review --apply`. |
| `no-design` | Overall median at or below zero, or the owner rejects the book. | Stays observe-only. A redesigned rule is a new registration. |
| `ack` | The owner has seen the board and wants no design work. | Stays observe-only. The finding does not re-fire every day once the stamp is set. |

The control difference is on the board the owner reads. It does not choose the row.

## 10. Freeze and markers

**Sealed at signature:** the learning question, the primary entry, the one alternative, the exit, the recovery rules, the limits, the cost formula, the scoring boards, and the thickness gate. Signature writes, in the next package, `docs/data/strategy_book_registration.json` copied from this document plus the owner's note. This draft does not write that file.

**One adjustment at signature.** The owner may change proposed numbers in the tables, once, in the signature note, before any score store exists. The owner may not add a third entry rule or a price stop.

**After the first score store is committed** (`strategy_book_replay.json` or `strategy_book_observe.json`):

| Change | What happens |
|---|---|
| A bug fix that makes the code match this text | A logged change marker on the same `registration_id`. Same pattern as N200's `n200-fair-cost-primary-v1`. The marker says what was wrong. History is not quietly rewritten. |
| Any threshold, the learning question, or which rule is primary | A new `registration_id`. The old scores stay under the old id. |
| Adopting the alternative as the book | A new `registration_id`. Forbidden on this id. |

**Parameters that stay frozen after the first look at results.** All of them: RSI 35 and RSI 40, the 10-session windows, the 3 percent SMA distance, the 8% recovery band, the 15-session swing limit, the 63-session review, the 4-review cap, the 2-confirm streak, the 10-session cooldown, the 40% recovery share, the 5-episode arming level, the 5-day gap, the 100 GBP stake, the fair-cost formula, the 3% stress view, and the 48 / 8-week gate.

**No parameter search on this id.** A search was considered and is not registered. The usual holdout would be the most recent six months of entries. The point-in-time value set only starts on 2026-08-02, and the charts used here end on 2026-10-30. That is about thirteen weeks. Six months of entries do not exist, so there is nothing to hold out. Splitting those thirteen weeks in half after seeing the scores is not a holdout.

Any later rule change treats the first **26 weeks** (proposed) of the forward book as sealed evidence for v0. The new registration is written before its own scores are read. It does not mine those 26 weeks for a better RSI level.

**Later twins, each a new registration, none of them started here.**

- Fills at the next open, once chart payloads grow an `opens` array and the archive can see that open. Queued behind P1/P2 as L667.
- A fair-value recovery target, when phase 4.1 publishes one (L662).
- Dividend-inclusive episode returns, when phase 3.1 lands.
- The same rules on an admitted market, in phase 6, with that market's fair cost row.

## 11. Data, compute, and the launch queue

P1 still serves live holdings, then the sealed units already running (strand A buy tier and N200). This book does not ask Data to ingest filings, rememo names, or deepen a shortlist ahead of those. `launch_queue.data_deepen_requested` is false. On the launch queue it is a waiter, the same posture as N206, until the owner explicitly moves it.

Compute is a walk over the FTSE buy tier (65 names on the 2026-11-03 decline snapshot) and the stored closes. No network, no model call, no new price fetch. Daily ops-monitor is enough.

**Already produced and used.**

- Weekly FTSE screen snapshots since 2026-08-02, including signal, sector, and research verdict.
- Daily closes for charted names, about two years, enough to warm RSI(14) before that first screen.
- Operating-decline gate on main, one current snapshot, already in the daily refresh.
- Fair cost table for `ftse350`.
- `core_sell_reason` and `thesis_break_confirmed`.

**Not produced, and required before the matching board can be non-empty.**

| Gap | What blocks | What step 2.3 adds |
|---|---|---|
| Sector store not on main | Part 3. Forward entries stay at zero without it. | Nothing in this repo until the sector-gate package merges. Then the daily refresh. |
| Decline and sector stores are single snapshots | `archive_full_strategy` and any later rebuild of the forward book. | An append-only verdict log, written by the observe job. Not a new ingest. |
| F9 fields absent on `run_*.json.gz` | Archive cannot apply F9-B. Those episodes stay `f9_unverified`. | Forward book computes the four binds at run time. No backfill. |
| No screen archive before 2026-08-02 | No two-year test of part 1. | Accept the thirteen-week rehearsal. Do not buy a price history to invent signals. |
| No opens, highs, or lows | Next-open fills and ATR stops cannot be replayed. | Keep next-close fills. ATR is unused. |
| Statement files overwritten on fetch | The decline gate cannot re-score August from today's files. | Dated statement snapshots stay outside this package. The empty full-strategy archive is the honest result. |
| Chart downsample cliff | `MAX_CHART_POINTS` is 280. Step size is `len // 280`. A series of about 500 bars stays daily (step 1). Past about 559 bars the next chart write keeps every other day, and RSI(14) on that tape is a different indicator. | Step 2.3 reads stored closes and refuses non-daily files. It also raises or bypasses that cap before the 2-year window crosses the cliff. That is a small writer change, not a new market data feed. |

Buy-tier interim coverage is still thin (the decline-gate runbook: interim EPS on 2 of 65 buy-tier names). Many `clear` verdicts are annual. The book inherits that, including the known tendency to flag a commodity name in a down year. Thresholds of the decline gate are settled at the Phase 1 signature, not inside this registration.

## 12. Next package

Short brief for the implementer. Still observe-only. Still no live writes.

**Modules.** `src/value_investor/strategy_book_observe.py` owns the walker. It calls `technical_analysis._rsi`, `core_sell_reason`, `note_thesis_streak`, `thesis_break_confirmed`, and `episode_return` / `costs_for_market`. It does not call `assign_timing_signal`, `compute_indicators`, or `compute_trade_plan` to decide a trade. CLI `ftse-strategy-book` with `--replay`, `--forward`, `--no-persist`, and `--as-of`. Replay and forward write different stores and never mix medians.

**Stores**, committed by ops-monitor the same way N200 commits (`GHA_COMMIT_OPTIONAL`):

| Path | Role |
|---|---|
| `docs/data/strategy_book_registration.json` | Seal copy of this document plus the signature note. |
| `docs/data/strategy_book_replay.json` | The three archive results and the alternative column. |
| `docs/data/strategy_book_observe.json` | Forward episodes, boards, disposition, change markers. |
| `docs/data/strategy_book_gate_log.jsonl` | Append-only verdicts the forward job used. |

**Ops-monitor.** `check_strategy_book_observe` inside `collect_ops_findings`, after the decline check and the sector check. `auto_fixable` false. Findings: refreshed (info), failed (warn), thickness gate ready for review (info). A row in [`ops-monitor.md`](ops-monitor.md) points here. The refresh finding names counts and the first few tickers. It does not spray rememo or ingest.

**Dashboard.** An Analysis → Observe strip on the N206 pattern, hash `#analysis/observe/strategy-book`, reading the forward store. A compact queue-health line for phase span, closed count, and freshness. No strand A lifecycle writes. No promote button.

**Tests.** Entry fires only on RSI below 35 and a 10-session low. A buy-tier name with a high RSI does not enter. Leaving the buy tier does not exit. An 8% drop classifies a hold and does not sell. Two `avoid` rows sell; one does not. `insufficient_data` blocks entry and does not, by itself, break a hold mid-way. A gap over 5 days does not fill. Fair-cost math matches `episode_return` on a known pair. Archive output keeps the three result keys separate. A thinned chart is refused.

**Do not reuse these as the rule.** They conflict with the strategy spec, the chart files, or both.

| Existing piece | What it actually does | Conflict |
|---|---|---|
| `assign_timing_signal` | RSI below 30 is already +2 points, which is enough for `ACCUMULATE`. Price above SMA50 above SMA200 adds a point for an uptrend. | A low RSI can signal without a short-term low. The uptrend point prefers strength. Part 4 asks for a short-term low. |
| `compute_indicators` | Returns `insufficient_data` below 200 bars, then calls `assign_timing_signal`. | The 200-bar gate is the wrong eligibility test. The composite is the wrong signal. |
| `compute_trade_plan` | Tactical limit under spot, stop under support or ATR, take-profit at least 8% above spot and 10% above the limit. | The stop sells a dip. The target is a fixed percent. Charts have no high or low, so the ATR stop and the limit fill cannot be replayed. |
| N200 walker | Opens on a new buy-tier cross and closes on the first leave. `row_f9_eligible` passes when the four bind fields are absent. | Leaving the buy tier is this book's control, not its exit. Absent F9 fields are not a pass on the forward book. |
| `two_lot_replay` `full_exit` | Sells the whole position after 2 screens outside the buy tier. | Control behaviour. |
| `two_lot_replay` `core_thesis_exit` | Core waits for avoid or a failed research verdict. The tactical slice still sells on rank, target, or stop. | `core_sell_reason` is the right helper. The tactical sales are not this book. The helper does not know the decline or sector gates; the walker adds those reasons beside it. |
| Chart `signal` and `levels` | Values at chart build. | Using them for an older date looks ahead. |
| `price_charts._downsample` | Will thin series past about 559 bars. | A thinned tape silently changes RSI(14). Refuse it. |
| Live paper books | Exit on rank, size with weights, charge 3% stress, and can prefer `adjusted_signal`. | They remain controls. This book is a cold start. N249 records that live exit as leaving the top-N target set after 2 screens. |
| L652 `buy_support_bounce` | Fires when price vs SMA200 is between −12% and +3% and timing score is non-negative, or on a technical cite. Stub in `parallel_timing_lenses.py`. | That is "near the 200-day average," not a 10-session closing low. The lens keeps its own store. It is not this entry. |
| L652 `sell_target_reached` | Maps a target exit, or any return at or above 15%. | A fixed 15% band replaces the short-term high. |
| L652 `sell_tech_break` | Fires when price vs SMA200 is −8% or worse. | That sells a drop. Part 6 holds the drop. The 8% band in this book only changes the label to recovery hold. |
| L652 `sell_mechanical_leave` | Records a leave-buy-tier close. | Same family as the section 8 control. It is not this book's exit. |
| L541 hold-buffer twin | A longer confirm before the rank exit, on a cold-start fair-cost twin. | A longer wait before a rank sale. This book does not rank-sell. |

## 13. Open questions

Six decisions. Each default is what this draft seals if the signature note is silent.

1. **Entry and exit window.** Default: 10 chart sessions for the low and the high. The trade plan's 20-day figure is a limit level, and stacking it on RSI below 35 would make entries rarer on a 65-name buy tier. At signature the owner may set 20 once. After a score store exists, 20 is a new registration.

2. **Which signal is the value set.** Default: raw `signal` in `{buy, strong_buy}`. The owner's part 1 names that value set. `adjusted_signal` is stored and does not gate. Thesis-break `avoid` reads the same raw field, so entry and exit cannot diverge. At signature the owner may switch both reads to `adjusted_signal` once. Switching only one of them is not an option.

3. **What starts a recovery hold.** Default: either an 8% drop under the fill or 15 chart sessions after the fill with no exit. At signature the owner may drop the time trigger and keep only the 8% drop. A price stop is not one of the choices.

4. **Fourth review.** Default: reviews 1–3 roll 63 sessions when the thesis still stands; review 4 sells at the next close. A human decision on every review would leave episodes open until someone acts, and the thickness gate would wait on that. At signature the owner may replace review 4 with a human hold. The first three reviews stay mechanical either way.

5. **Recovery-hold cap.** Default: block new entries at 40% of open episodes, once 5 episodes are open, and publish the blocked count. Report-only would describe crowding and still allow it. At signature the owner may switch the cap to report-only.

6. **When the forward book starts, and on which market.** Default: start the forward book only after the Phase 1 signature, and only once the sector store is refreshing on main. Keep v0 on the FTSE 350. The archive rehearsal of the price rules may run as soon as this registration is signed. It still does not use today's gate verdicts as a pass.
