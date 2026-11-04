# Strategy book registration

**Status: DRAFT — awaiting owner signature (Phase 2 gate).**  
**registration_id (proposed):** `owner-strategy-book-v0`  
**Deferred:** N249  
**Plan step:** 2.1 in [`strategy-reorientation-plan.md`](strategy-reorientation-plan.md)  
**Strategy spec:** [`PROJECT_OBJECTIVE.md`](../PROJECT_OBJECTIVE.md#investment-strategy-owner-2026-11-03)  
**Human checklist:** `adhoc-strategy-phase-gate` in [`human-tasks-checklist.md`](human-tasks-checklist.md#ad-hoc-when-triggered)

**Revised 2026-11-04 (owner decision, before signature):** the universe is multi-market from v0 (section 2), a buy-on-signal control answers whether timing adds anything and a report-only capital view compares capital use and risk with buy-and-hold (section 8), the thickness gate counts at most 6 episodes per entry week (section 9), and the book asks for the launch-queue head (sections 11 and 13). This book is the single track to live capital ([plan](strategy-reorientation-plan.md#single-track-to-live-owner-2026-11-04)).

**Exit amended 2026-11-04 (owner decision, before signature):** the primary exit is a checkpoint ladder with a fail-to-launch deadline (section 4). The earlier draft exit (10-session high, recovery target, review cap) and the ladder without the deadline are scored as paired report-only exits on the same entries (section 4). The decision number counts mature episodes, so slow-closing winners cannot flatter it (sections 1 and 9). A paired interim read is published at 26 weeks (section 8). The ladder and the 63-session deadline were chosen after seeing a replay; section 10 records that.

This document freezes the rules before any score is computed. It does not open a book, write a store, or run a replay. Step 2.2 (archive replay) and step 2.3 (forward book) wait until the owner signs, adjusts a listed number once, or rejects.

Every number in the rule tables is **proposed** unless the row says it is an existing constant that this book stamps unchanged. The owner may change a proposed number once, in the signature note, before any score store exists. After the first score store is committed, section 10 applies.

`owner-strategy-book-v0` means this first registration of the owner's seven-part strategy. It is an observe instrument. `influences_live` is false. It does not write strand A, `buy_tier_level`, knobs, or `decision-review --apply`.

No language model chooses an entry, an exit, or a review. The book reads the research verdict already logged on the screen row. A later package that adds a model veto stays a shadow until `authorize_live_llm_influence()` allows it ([`llm-live-path-evidence.md`](llm-live-path-evidence.md)).

## 1. Learning question

On FTSE 350 names and names in graduated library markets that pass parts 1–3 and the current F9-B input-quality gate, does a fixed stake bought at the registered short-term low and sold under the registered checkpoint ladder — at a profit floor once the trade has launched, or at the fail-to-launch deadline if it never does — produce a **positive median fair-cost episode return**?

That question is false when, at the thickness gate in section 9, the median fair-cost return across all **mature** episodes is zero or below. An episode is mature once its fill is at least 63 chart sessions before the scoring date. By then it has either closed or launched (section 4), so the median cannot be flattered by winners that close early while losers are still open. The book then stays observe-only. A different rule is a new `registration_id`. This one is not edited to make the median positive.

Two results sit beside that and still mean stop or redesign, by a new registration:

- The floor-exit median is positive and the overall median is zero or below. The trades that fail to launch are what failed. A price stop is not added to this id.
- The forward book has run 39 weeks (proposed) and still has fewer than 48 counted mature episodes (section 9). The rule is too rare on this universe to answer the question. The thresholds stay as written.

A positive median on a thinner sample is not a pass. Forty-eight episodes are a look, not a measurement of a small annual edge. Forward paper evidence cannot resolve a 3% a year edge on a short window ([`historical-screen-replay.md`](historical-screen-replay.md#why) records years-to-detect of 125–900, and about 150 non-overlapping monthly cohorts before a 30-day screen spread is even discussable). Read a pass here as "this sample did not lose after fair costs."

The archive rehearsal in section 9 does not answer the question. It has no point-in-time operating-decline or sector verdicts.

## 2. Universe and eligibility

Parts 1–3 of the strategy, plus the input-quality gate the project already uses for named stocks (F9-B). All of them are true on the decision date. One failure, or a missing input, means the name is not eligible. `insufficient_data` is not a pass.

v0 is multi-market (owner, 2026-11-04). It reads the live FTSE 350 screen and the offline library screens of every market that has graduated from its ingest sprint. More markets give more closed episodes for the same rules, so the gate is reached sooner. The live screener itself stays on the FTSE 350; this is an observe book reading screens that already run.

| Check | Proposed value | Why |
|---|---|---|
| Universe | FTSE 350 names on the archived or live screen, plus names on the library screen of any market whose `is_graduated` is true in `docs/data/market_status.json` on the decision date | Investment eligibility is quality-driven (F9-B), not FTSE membership, and a book may only open on a market that has reached `sprint_ingest_complete` ([`AGENTS.md`](../../AGENTS.md#project-objective)). On 2026-11-04, 21 library markets are graduated. A market that graduates later joins by this rule without a new registration; a market that loses the flag stops new entries and keeps its open episodes. |
| Part 1, cheap | Raw screen `signal` is `buy` or `strong_buy` | The owner's value set. Same pair as `BUY_SIGNALS` in `paper_fund.py`. Library rows carry the same field. |
| Part 2, not declining | Operating-decline verdict `clear` | Gate on main: `operating_decline_gate.py`. It already scores library names that have research sources. `declining` and `insufficient_data` both fail entry. |
| Part 3, sector sound | Sector verdict `sound` for the name's sector **within its own market** | Gate on main: `sector_headwind_gate.py` ([runbook](sector-headwind-gate.md)). v0 of the gate scores FTSE sectors only; plan step 1.8 extends it to graduated markets. Until then a library name has no sector verdict and is not eligible. `headwind` and `insufficient_data` both fail entry. |
| F9-B | All four binds true: `key_filing_bodies`, `fcf_basis_bound`, `overlay_bound`, `memo_recent` | Same fields as `decision_input_inventory.py`. Memo age uses the existing 21-day maximum. The inventory reads FTSE screen rows only, and library rows carry no `fcf_basis_overlay`; plan step 1.9 computes the same four binds for library names from their research folders. Until then a library name fails F9-B. |
| Missing chart, RSI, or a usable next bar | Not eligible | A rule that cannot be priced is not a trade. |

**Decision date.** For the forward book, the ops-monitor run date (UTC). For the archive, each chart session.

**Library rows.** Library screen runs (`docs/data/library/markets/<market>/screen/history/run_*.json.gz`) carry `signal`, `adjusted_signal` and `research_verdict` but no `sector`. The only library sector label is the current one in that market's `screen/latest_signals.csv`. v0 treats a library sector label as static, the one approximation of this kind in the book; step 1.8 records the label on every sector-gate refresh so the forward book reads a dated value. Each episode records its `market_id`.

**When a weekly screen may be used.** Screen runs are weekly, for the FTSE screen and for each library market. A run applies to chart sessions strictly after the run's calendar date. The run dated 2026-11-01 qualifies later sessions. It does not qualify the 2026-10-30 close that had already happened. The latest such run is carried forward until the next one. Leaving the buy tier later does not close an open episode (section 4). It does stop a new entry.

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

## 4. Exit

Amended 2026-11-04 (owner, before signature). The primary exit lets a trade that has started to rise run until its momentum breaks, keeps most of the gain with a ratcheting profit floor, and releases capital from a trade that never starts. Rank, top-N membership, and leaving `buy` / `strong_buy` do not close the episode. Those exits stay on the control described in section 8.

All exit tests use closes only, like the entry. Percentages are of the **entry fill**, gross of costs. Every sale fills at the next chart session's close, with the 5-day gap rule from section 3. No next bar means the episode stays open. The scored prices are the two fills.

### Primary exit: checkpoint ladder (proposed)

**Launch.** The episode launches on the first close at or above the entry fill times 1.10 (the first checkpoint, +10%).

**Checkpoints and floors.** After launch, each close is compared with the checkpoints +10%, +15%, +20%, +25%, +30%, +40%, +50%, +75% and +100%. The highest checkpoint any close has reached sets the floor:

| Highest checkpoint reached on a close | Floor |
|---|---|
| +10% | +5% |
| +15% | +10% |
| +20% | +15% |
| +25% | +20% |
| +30% | +25% |
| +40% | +30% |
| +50% | +40% |
| +75% | +50% |
| +100% | +75% |

The floor only rises. Above +100% it stays at +75%.

**Floor exit.** A launched episode signals an exit on the first close at or below the entry fill times `(1 + floor)`. Label `floor_exit`, with the checkpoint reached. A gap can fill the sale under the floor. The fill is scored as it is and the shortfall is reported. It is not topped up.

**Fail to launch.** An episode that has not launched when the session index after the fill reaches **63** (the fill session is index 0) signals an exit on that session, whatever the price. Label `fail_to_launch`. In the replay below, about three quarters of these sales were below the entry fill. This is a time rule, not a price stop: no price level below the entry ever triggers a sale. It replaces the open-ended recovery hold for trades that do not start, so their capital goes to fresh entries.

**Time cap.** An episode still open when the session index reaches **252** (about a year) signals an exit. Label `time_cap`. Part 7 asks that no hold runs without an end.

**Thesis break and reviews.** Section 5 applies to every episode, launched or not.

| Input | Proposed value | Why |
|---|---|---|
| First checkpoint | +10% on a close | In a replay across graduated markets, a trade that had reached +10% reached +15% before falling back to +5% in 65% of 769 cases. The next checkpoint came first in 55–67% of cases at every level up to +40%, so waiting with a floor pays on average. |
| Step and floor | 5-point steps to +30%, then +40, +50, +75, +100; floor at the previous checkpoint, +5% at the first | Each step is the same size up and down, so the floor keeps the last checkpoint less one step. +5% clears every market's round trip in section 7. |
| Fail-to-launch deadline | 63 chart sessions after the fill | The patient horizon already sealed on N206. In the replay, cutting after 20 or 40 sessions sold many trades that were about to launch and did worse; 63 did best or near best in both universes. |
| Time cap | 252 chart sessions after the fill | The same year as the draft's four 63-session reviews. |
| What does not exit | Leaving the buy tier, leaving a top-N list, a trade-plan stop, a trade-plan target, a price drop below the fill | Part 5. The control in section 8 keeps the buy-tier exit so the difference can be reported. |

A checkpoint continuation model (estimating at each checkpoint whether to wait or sell) was tested and is not part of this rule. A simple momentum model trained on the first year never said "sell" on the second year, because every group continued more often than not. It is queued as L670, a challenger for a later version review.

Worked ladder (FTSE 350 name). Fill 100. Session 9 closes at 110.4: launched, floor 105. Session 20 closes at 116: floor 110. Session 26 closes at 109.8, at or below 110: the floor exit signals. The next close, 109.5, is the sale. Fair-cost return is `109.5 / 100 - 1 - 0.00525 - 0.00025` = 8.95%.

Worked failure. Fill 100. The best close in 63 sessions is 107.9. On session 63 the close is 96: the fail-to-launch exit signals. The next close, 95.6, is the sale, a fair-cost loss of 4.95%.

**Replay of this exact rule** (2024-10-30 to 2026-10-30 closes, today's buy tier painted back, no gates, no thesis breaks, no dividends, fair costs; median of 15 random funding orders for the 20-slot book):

| | FTSE 350 | All graduated markets |
|---|---|---|
| Closed episodes | 243 | 1,432 |
| Median / mean fair-cost return | +3.6% / +4.8% | +3.4% / +4.3% |
| Floor exits: count, median | 135, +10.6% | 746, +9.4% |
| Fail-to-launch exits: count, median | 107, −5.4% | 671, −6.5% |
| Return per year of capital invested | 20.8% | 18.7% |
| 20-slot book | 16.1% a year | 19.6% a year |
| Same rules with the draft exit | 17.8% per capital-year, 5.8% 20-slot | 10.0% per capital-year, −1.9% 20-slot |

Equal-weight buy-and-hold of the same names made 16.1% a year (FTSE) and 19.5% (all markets) on the same history. These figures choose nothing. They are why the owner picked this exit, which is also why they cannot count as evidence for it (section 10).

### Paired comparison exits (report-only)

Every primary entry also gets two comparison exits at the same fill. They are columns on the same entries, like the leave-tier control. They do not open entries, do not affect the primary's cooldown or cap, and never replace the primary on this id.

| Column | Rules |
|---|---|
| `draft_v0_exit` | The 2026-11-03 draft. While a swing, sell at the next close after a close that is the highest of the 10 sessions ending there and at least the fill times `(1 + buy + sell)`. The swing becomes a recovery hold on a close 8% under the fill, or at session index 15. A recovery hold sells at the next close after a close at or above the entry fill. Reviews every 63 sessions from the recovery classification, with the review table in section 5, and a sale at the fourth review. Thesis breaks as in section 5. |
| `ladder_no_deadline` | The primary ladder without the fail-to-launch deadline. An episode that has not launched stays open and follows the `draft_v0_exit` review timing (63-session reviews from an 8% or 15-session recovery classification, sale at the fourth). It does not sell at the entry fill. Thesis breaks as in section 5. |

`draft_v0_exit` answers "is the ladder better than the exit first drafted for part 5?" `ladder_no_deadline` answers "what does the 63-session deadline add?"

## 5. Thesis break, the recovery label, and reviews

A price drop below the fill never sells by itself. Under the primary exit, a trade that has not launched waits until the fail-to-launch deadline, a thesis break, or a review exit.

### The recovery label (proposed)

An episode that has not launched and has closed at or below the entry fill times `(1 - 0.08)` is labelled a recovery hold. The label is for reporting and for the recovery-hold share in section 6. It does not change the exit rule. It does not flip back if the price recovers. If the episode later launches, it keeps the label and also records the launch.

The 8% band reuses the distance already encoded as `tactical_target_above_spot` (8% above spot) and the neighbourhood of `support_floor_below_spot` (8% under spot). The draft's 15-session trigger is dropped from the primary label: under the ladder most trades have not launched after 15 sessions, and that is waiting, not a failed swing. `draft_v0_exit` keeps the 15-session trigger, as drafted.

There is no recovery target on the primary exit. A trade back at its entry price keeps waiting to launch until the deadline. A later fair-value target is phase 4.1 (L662), not this registration.

### Thesis break (proposed)

The same facts that forbid an entry can end any episode, launched or not, on the primary and on both comparison exits. One implementation serves entry and exit, so the entry rule and the exit rule cannot drift. That is the constraint already written on the operating-decline gate.

A thesis break is any of:

| Fact | Source | Proposed reading |
|---|---|---|
| Operating verdict `declining` | The decline gate | Part 2 failed. |
| Sector verdict `headwind` | The sector gate, on this name's sector | Part 3 failed. |
| Screen `signal` is `avoid` | `core_sell_reason` in `core_sell_trigger.py` | Hard avoid. |
| Research verdict's first token is `pass`, `sell`, `avoid`, or `exit` | `core_sell_reason` | `pass` is this project's do-not-own verdict. |

`insufficient_data`, a missing store, a missing screen row, research `caution`, and research `neutral` are not breaks. A missing row leaves a streak where it is, which is what `note_thesis_streak` already does. `clear` and `sound` reset their own streaks. A one-day gap must not wipe a real decline, and it must not sell the position.

Confirmation reuses `thesis_break_confirmed` with **2** consecutive observations, the live `DEFAULT_EXIT_CONFIRM_SCREENS`. Streaks are per reason. Screen and research observations are the weekly runs. Gate observations are successive `as_of` dates. Two weekly avoids sell. Two daily `declining` verdicts sell. One of each does not.

When a thesis exit and any other exit signal on the same session, the label is `thesis_break`. A business that has failed is not scored as a floor exit or a recovery, even if the price is above the fill. The return can still be positive. It stays on the thesis-break slice.

### Review date (proposed)

On the primary exit the clock starts at the fill. Reviews fall at session index 63, 126 and 189. At index 63 an episode that has not launched is already sold by the fail-to-launch deadline, so the reviews read launched episodes. Index 252 is the time cap. On `draft_v0_exit` and `ladder_no_deadline` the clock starts on the recovery classification instead, as drafted.

| Review | Proposed action | Why |
|---|---|---|
| Each review date | Re-read parts 2 and 3, the screen signal, and the research verdict. | 63 trading days is the patient horizon already sealed on N206. Here it is a review spacing, not an automatic sale. |
| Thesis already broken under the streak rule | Exit `thesis_break` at the next close. | The mid-hold rule has already fired, or fires on this read. |
| Decline is not `clear`, or sector is not `sound`, including missing and `insufficient_data` | Exit `review_insufficient_data` at the next close. | Mid-hold, a one-day gap does not sell. At the review, a long hold needs fresh evidence. A blank file ends the hold. |
| Screen row missing | Exit `review_insufficient_data`. | There is no current value-set fact. |
| Research verdict missing, while the gates are `clear` and `sound` and the signal is not `avoid` | Hold stands. | Research `pass` sells. A missing memo does not. Entry already required a fresh memo. |
| Gates `clear` and `sound`, signal not `avoid`, research not failed | Hold stands until the next review, the floor, or the time cap. Record the review. | The business case still stands. |
| `draft_v0_exit` and `ladder_no_deadline` only: the same, on review 4 | Exit `review_cap` at the next close. | The draft's end to a recovery hold, four reviews or about a year. Section 13 lets the owner replace it with a human hold at signature. |

Each session, the primary walker does these checks in order. The first one that acts ends the session for that name.

1. A confirmed thesis break signals an exit. The label is `thesis_break`.
2. The close updates the launch and the highest checkpoint reached.
3. A launched episode whose close is at or below its floor signals a `floor_exit`.
4. An episode that has not launched at session index 63 signals `fail_to_launch`.
5. An episode at session index 252 signals `time_cap`.
6. A review date applies the review table.
7. An episode that has not launched and closes 8% or more under the fill takes the recovery label. No order.

The comparison columns run the same thesis-break step first, then their own rules from section 4.

The exit reason is fixed on the signal session. The next close is only the price. A new fact on the fill day does not relabel an exit that was already signalled.

## 6. Limits

Fixed-stake v0, as in [`fair-cost-primacy.md`](fair-cost-primacy.md#fixed-stake-v0-default-new-observe--models). One stake per entry. No fund NAV, no cash balance, no equal weight, no DCA split. Episode percent does not depend on the stake. The stake is recorded so a later twin can scale it.

| Limit | Proposed value | Why |
|---|---|---|
| Stake | 100 units of the listing currency per entry (100 GBP on London names, 100 USD on US names, and so on) | The standing fixed-stake default of 100 local-currency units. Episode percent is a ratio on one chart's series, so currency and pence-versus-pound units do not change it. No FX translation of returns in v0. |
| Cash | No cash constraint | v0 parks fund construction. The recovery-hold share below is a count of episodes, not a cash rule. |
| Open episodes per name | 1 | A second signal while the episode is open is ignored and counted as `already_open_skip`. |
| Re-entry cooldown | 10 chart sessions after the exit fill | The same length as the entry window, so the sale session's own low cannot buy the name straight back. |
| Recovery-hold share | Recovery-labelled episodes (section 5) as a share of open episodes, once at least 5 episodes are open; a 40% line is drawn on the board | Part 7. Below 5 open episodes the ratio is noise (1 of 2 is already 50%). |
| Cap action | Report-only under the amended exit. `cap_would_block` counts the days the share was at or above 40% | The fail-to-launch deadline already ends every trade that has not launched within 63 sessions, so a stuck position cannot crowd out new entries for long. Section 13 (question 5) lets the owner switch the cap to block at signature. A blocked name would not be queued; it would have to signal again on a later day. |
| Names signalling on the same day | Take every name that passes | No top-N and no "cheapest first." If the owner switches the cap to block, it allows or blocks the whole day. |
| Markets | One pooled book; the cap and the per-name rule apply across all markets | Splitting the cap by market would make a rare-signal market wait on its own count. Per-market boards (section 8) show where the episodes come from. |

The share is measured on the signal session, before a fill is scheduled. The denominator is every open episode, launched or not.

## 7. Costs

Primary costs are each episode's own market row in `market_trading_costs` (`costs_for_market(market_id)`). The book stamps every market's buy and sell rates into the registration record when it seals. It does not invent a second schedule. A market that graduates later is stamped from the same table on the day its first episode opens, and the stamp is logged.

Today's table, which a seal on this tree would stamp (examples; the seal copies every graduated market):

| Market | Buy | Sell | Round trip | Why |
|---|---|---|---|---|
| FTSE 350 | 0.525% | 0.025% | 0.55% | 0.50% UK stamp on the buy plus 0.025% half-spread each side. No FX. |
| FTSE SmallCap | 0.55% | 0.05% | 0.60% | Stamp plus a wider half-spread. |
| AIM | 0.575% | 0.075% | 0.65% | Stamp plus the widest UK half-spread. Many AIM shares are stamp-exempt; the table keeps stamp on deliberately until a per-ticker exemption lands, so AIM returns are understated. |
| S&P 500, Nasdaq-100, ASX 200, TSX 60, DAX | 0.175% | 0.175% | 0.35% | 0.15% Trading 212 FX fee plus 0.025% half-spread each side. No stamp. |
| Hang Seng | 0.19% | 0.19% | 0.38% | FX fee plus a 0.04% half-spread. |

| Leg | Value | Why |
|---|---|---|
| Episode return | `exit_fill / entry_fill - 1 - buy - sell` | The same formula as `episode_return` in `n200_tech_timing_observe.py`, with that market's rates. |
| Stress | 3% per side (0.03), report-only | `LEGACY_STRESS_TRADE_COST_PCT`. Subtract 0.06 from the gross return. Same role as on N200 and N206: a harsh churn view, not the decision number. |

Stress does not decide the learning question. It is published next to the fair-cost median.

Dividends are not added. Marks are price returns after trading costs. Total-return accounting is phase 3.1. Saying so here keeps a price rebound from being read as a total return.

## 8. Scoring

The decision number is one median: the fair-cost episode percent of **every mature episode**, all exit reasons together. An episode is mature when its fill is at least 63 chart sessions before the scoring date. A mature episode is either closed, scored at its two fills, or open after launch, scored **at its current floor** as if sold there (fair costs subtracted). The floor is the least a launched trade is still expected to realise; the latest close is published beside it. A floor-exit-only median is published too and cannot pass the gate on its own.

Episodes younger than 63 sessions are shown, marked to the latest close, fair-cost as if closed. They are outside the median, because the ones that will fail to launch have not had their chance to. A missing quote leaves the mark blank. It is not filled with zero.

| Board | Proposed contents | Why |
|---|---|---|
| Overall (primary) | Median fair-cost episode % of all mature episodes, open launched ones at their floor. Count. The same median with open launched ones at the latest close, beside it. | The learning question. One number, after fair costs. |
| Launch | Share of mature episodes that launched; median sessions from fill to launch. | "Do the timed entries start to rise?" |
| Floor exits | Count, median return, and the highest checkpoint reached, as a distribution. Gap shortfall under the floor, summed. | "Does the ladder keep the gains?" |
| Fail to launch | Count, median return, share below the fill. | The cost of releasing capital at 63 sessions. |
| Thesis breaks | Count by reason code (`declining`, `headwind`, `screen_avoid`, `research_failed`), median return, split by launched or not. | Loss on a broken business, kept separate. |
| Review and time-cap exits | Count of `review_insufficient_data` and `time_cap`, with median return. | Included in the overall median. Shown on their own so a time limit is visible. |
| Recovery label | Count of recovery-labelled episodes, their launch share, and their median return. | Part 6: how often a trade that fell 8% still came good. |
| Paired exits | For each comparison exit in section 4, the median and mean of the per-entry difference (primary minus comparison) on mature entries, with each open episode valued as above on the primary and at the latest close on the comparison. Standard error from entry-week averages. | Answers "is the ladder better than the draft exit, and what does the deadline add?" on the same trades. Report-only. |
| Stress | The same mature episodes at 3% per side. | Report-only. |
| By market | The overall board for FTSE 350 alone, for each market with at least 10 mature episodes, and for all other markets pooled. | Shows whether one market carries the result. Report-only. |
| Single-market dependence | Flag `single_market_dependence` when the overall median is above zero but falls to zero or below once the market with the most mature episodes is removed. | The disposition finding carries the flag. It does not fail the question by itself. |
| Buy-on-signal control | Episodes below. Difference of medians against the overall board, and the same by market. | Answers "does the timing add anything over buying the signal and holding?" Report-only. |
| Leave-tier control | Paired episodes below. Difference of medians. | Report-only. No crown. |

**Buy-on-signal control (report-only).** On the same universe and the same eligibility rules (section 2, all parts), a control episode opens for every name that is eligible on a screen run after being ineligible, or absent, on that market's previous run. It buys at the next chart close after the run's date, with no timing test. It sells after 63 chart sessions, or when the name has been ineligible on 2 consecutive runs, whichever comes first, at the next chart close. Same market costs, same 5-day gap rule, one open control episode per name. This is the cue-consumer lab's policy (buy on the weekly cue, hold 63 trading days, exit on an identity break) applied to this book's universe, so the two books can be compared without a universe difference. The lab itself keeps running on the FTSE screen as an outside reference ([`cue-consumer-mft.md`](cue-consumer-mft.md#role-under-the-single-track-owner-2026-11-04)).

If the overall median is positive and the buy-on-signal control's median is at least as high, the timing rules added nothing on this sample. The disposition finding states that in plain words. It does not change the learning question.

**Leave-tier control (report-only).** For each primary entry, a paired episode buys at the same fill. It sells when the raw `signal` has been outside `{buy, strong_buy}` for 2 consecutive archived runs, the live `exit_confirm_screens` value. The sale fills at the next chart close after the confirming run's date, with the 5-day gap rule. Same fair costs. If the name never leaves the buy tier, the control episode stays open and stays out of the control median.

That paired exit is the behaviour of `buy_tier_level` and of N200's leave-tier close. It is how this project already turns a buy-tier membership spell into a trade. The strategy book does not use it as an exit. The median difference is context for the owner. Beating the control is not the learning question, and losing to it does not by itself fail the question. Fair-cost primacy already treats control excess as report-only.

**Interim read at 26 weeks (report-only).** When the forward book has run 26 weeks, ops-monitor publishes the paired-exit board against `draft_v0_exit` as an info finding: the mean per-entry difference, its standard error from entry-week averages, the number of mature entries and entry weeks, and the share of entries where the primary did better. It is an early read of whether the ladder is beating the exit first drafted for part 5. It is not the thickness gate, opens no disposition, and does not change any rule. Trades bought in the same week move together, so the entry-week standard error is the honest one. In a replay with today's buy tier painted back, the ladder led the draft by about 1.5–2 points per entry at 26 weeks across all markets, but the difference was more than two standard errors in only about a fifth of 26-week windows; at 52 weeks it was in about three fifths. Read the 26-week number as direction, not proof.

Neither control is the live book's NAV. Live books have weights, cash, and a 3% stress stamp. Comparing NAVs would mix those choices with the timing rule.

**Capital view (report-only, owner 2026-11-04).** A positive median episode does not show that the book uses capital well. A replay of the price rules with the draft exit (today's buy tier painted back, no gates, no dividends) had a +2.1% median FTSE episode over a median of 10 sessions. Return per year of capital actually invested was 18%. A 20-slot book taking signals first come made 4–7% a year. Equal-weight buy-and-hold of the same names made 16% a year. Recovery holds held over 60 days used 55% of the capital-days and lost money in total. The amended exit's replay is in section 4. These boards make that visible on the real book. None of them is the learning question, and none of them changes a rule:

| Board | Proposed contents | Why |
|---|---|---|
| Capital-days return | Sum of fair-cost episode returns divided by stake-days, times 365. Overall and by market. Open episodes are marked to the latest close. | Return per year of capital actually invested. Counts how long each stake was tied up, which the median ignores. |
| Recovery-hold capital share | Share of stake-days spent in recovery-labelled episodes and in episodes that had not launched, and the summed fair-cost return of each. The same for episodes held more than 60 sessions. | Shows whether trades waiting to launch are eating the floor-exit profits. Input to the version review. |
| Reference slot book | A 20-slot book that puts 1/20 of its current value into each signal in signal order (ties by ticker), skips a signal when no slot is free, and reinvests proceeds. Daily NAV, annualised return, maximum drawdown, annualised volatility, average idle cash, trades taken and skipped, and the combined P&L of the five worst names as a share of starting capital. Beside it, the median annualised return over 15 fixed random orders of same-day signals. | One concrete capital path for the same trades. In replays a single funding order moved the FTSE slot book between about 8% and 17% a year, so one order is mostly luck; the random-order median is the steadier figure. Equal slots are a fixed reference here, not a sizing decision; fixed-stake v0 still scores episodes. |
| Buy-and-hold reference | Equal weight in every name eligible on the book's first day, plus an equal stake in each name on the day it first becomes eligible, held to the scoring date. Same daily NAV, drawdown, volatility and worst-five-names figures. Price only, the same costs once in and once out. | The plain alternative for the same eligible names. It is diversified across all of them, so it tests timing against holding, not one stock pick against another. |

The slot book and the buy-and-hold reference are reported side by side on return and on risk (drawdown, volatility, worst-five-names loss). In the replay above buy-and-hold had the higher return and, across all markets, the lower drawdown and worst-five loss. The capital view lets the forward book confirm or overturn that with the gates applied.

Capital policies (a cash float sized for clustered signals, skimming profits into a reserve, pacing entries in a sell-off, choosing which signals to fund when oversubscribed) are not part of v0. They are a capital-path twin under [fixed-stake v0](fair-cost-primacy.md#fixed-stake-v0-default-new-observe--models), registered after the thickness gate. A replay of seven such policies on the same trades moved the FTSE result between 5% and 8% a year and none reached buy-and-hold; across all markets the book was fully invested about 95% of the time, so which signals get funded mattered more than how much float there was.

**Archive versus forward.** The boards above are computed separately for the archive rehearsal and for the forward book. The two medians are never averaged. Only the forward book's overall median can meet the thickness gate.

## 9. Two evidence tracks

### (a) Archive replay — report-only

Step 2.2. It rehearses the price rules on history that already exists. It does not answer section 1, and it does not satisfy the thickness gate. It does not write a paper book.

**Prices.** `docs/data/charts/<TICKER>.json`, fields `dates` and `closes` only. On 2026-11-03 the tree holds 1,269 chart files. The shared writer is `build_price_chart_payload`. The two files read for shape are daily across about two years (section 3). The walker still checks each file: if more than 5% (proposed) of successive gaps are longer than 5 calendar days, the name is `chart_not_daily` and is not traded. Stored `sma50_series`, `sma200_series`, `levels`, `signal`, and `level_crossings` are ignored. Those levels are the trade plan at chart-build time (`levels_as_of` was 2026-11-01 on both samples). Using them for an older session would look ahead.

**Value set.** `docs/data/history/run_*.json.gz`, loaded the way N200 loads snapshots (`load_run_snapshots`). This tree has 30 run files, from `run_20260802_123417.json.gz` through `run_20261101_073321.json.gz`. Each has `run_at`, `signals`, and `prices`. The latest signals list has 248 rows, with `signal`, `adjusted_signal`, `research_verdict`, `sector`, `timing_signal`, and the trade-plan levels. Eligibility uses `signal`, `research_verdict`, and `sector` only, and only from a run dated before the session. Fills come from the chart closes. The snapshot `prices` map is a different series and can mix pence with pounds (`yahoo_price_units`). It is not a fill.

Library markets keep their own weekly runs under `docs/data/library/markets/<market>/screen/history/run_*.json.gz`, from 2026-07-18 for the larger markets (for example 69 S&P 500 run files and 68 ASX 200 run files on 2026-11-04). Rows carry `signal`, `adjusted_signal` and `research_verdict`; sector comes from section 2's library rule. A library session uses that market's latest run dated before the session, and only while the market is graduated. Library runs before graduation are rehearsal-only like everything else here.

`docs/data/archive/` holds 23 dashboard bundles dated 2026-08-09 through 2026-11-01 (`2026-11-01.json` is a full publish, with `reports` and `run_at`). It is not a second signal source. A date that exists only there does not create an entry.

**How far back entries can go.** Closes start around 2024-10-30. Buy-tier runs start on 2026-08-02. Entries are allowed only on sessions that have a prior run, so the entry window is about thirteen weeks, not two years. The older closes warm RSI. They are not a hidden two-year test. There is no point-in-time value set for 2024 or 2025 in this repo.

**Gates.** The decline store on main is one snapshot, `as_of` 2026-11-03 (65 buy-tier names, 62 with a `clear` or `declining` verdict). The gate's own runbook says a past `as_of` fails closed, because statement files are overwritten on fetch. The sector gate is on main from 2026-11-04 with FTSE sectors only, also as a single snapshot. This replay therefore keeps three labelled results, and does not merge them:

| Result | What it applies | How to read it |
|---|---|---|
| `archive_buy_tier_only` | PIT buy tier, the price rules, and screen / research thesis breaks from the weekly row. No decline gate. No sector gate. F9 fields are absent on the run rows, so every episode is `f9_unverified`. | A rehearsal of parts 4–6 plus part 1. Not a test of parts 2–3. Not the strategy universe. |
| `archive_full_strategy` | The same, plus a committed decline verdict and a committed sector verdict whose `as_of` is usable for that session, plus F9 binds computed from files dated on or before that session. | This is the strategy. It stays empty until those dated verdicts exist. An empty board is published as empty. |
| `lookahead_current_gates` | Today's `clear` list and, once it exists, today's `sound` list, painted backward across the entry window. | Report-only. Lookahead. Never averaged into the other two. |

**Survivorship.** Charts exist for names that were charted at the build (`as_of` around 2026-11-01). A buy-tier name with no chart is counted as `no_chart` and is not an episode. Names that left the universe before they were charted are absent. This is not the survivorship-free tape used by the historical screen replay (active and delisted constituents). A chart that ends before the exit stays an open episode at the last close. No delisting price is invented.

**Lookahead, restated.** Price indicators are sliced at *t*. Screen facts come from an earlier run. Gate facts come from an earlier `as_of`, or they are left off. The chart's own `signal` field is the signal at build time and is not an entry. Today's decline verdicts describe current statements, including the latest fiscal year, and must not be treated as what an investor knew in August 2026.

**Dividends and opens.** Still absent, as in sections 3 and 7.

The alternative entry is scored only inside `archive_buy_tier_only`, as its own column, with the primary's exit. It does not share the one-name cap with the primary, because it is not a second book.

**Maturity in the archive.** The entry window is about 63 chart sessions long and the charts end on 2026-10-30, so only the earliest archive entries can be mature. The rehearsal publishes the young board and the paired-exit columns as they stand. It is a smoke test of the walker and the boards, not an early answer.

### (b) Forward observe book

Step 2.3, after this registration is signed and after the default in section 13 (wait for the Phase 1 signature, and wait until the sector store is refreshing on main).

The book then runs in daily ops-monitor, after the decline refresh and the sector refresh. It opens real observe episodes from that day forward. It does not backfill August–October 2026 into the forward median. Those months belong to the archive rehearsal.

Each day the job appends the verdicts it actually used (ticker, `as_of`, decline verdict, sector verdict, signal, research verdict, F9 pass or gap list). The live gate stores are overwritten in place. Without an append-only log, a later rebuild cannot show why a name was eligible. That log is part of step 2.3, not of this draft.

### Thickness gate (proposed) and the owner's decision

Both are required, on the **forward** book only:

| Gate | Proposed value | Why |
|---|---|---|
| Mature episodes | at least 48 **counted** mature episodes (section 8), counting at most 6 per ISO entry week | The figure named in the phase 2 plan, and the gate already used by N206. N200's 24 is a different instrument (membership spells, easier to accumulate). A multi-market book takes many entries in one sell-off: in a replay of the price rules across markets, the 5 busiest entry weeks held 19% of all entries. Those trades share one market event and are not 48 separate tests. Six per week means the count needs at least 8 distinct entry weeks. Every mature episode is still scored in the medians; the cap applies to the gate count only. In a replay of the frozen exit (today's buy tier painted back, no gates), the multi-market book had a median of 76 counted mature episodes after 26 weeks (lowest 53); the FTSE 350 alone had 27 after 26 weeks and 53 after 39. |
| Calendar span | at least 63 chart sessions from the first entry fill to the latest chart session | Implied by maturity; longer than the "and 8 weeks" bar of N200 and N206. |
| What does not count | Archive episodes, the alternative rule, either control, both comparison exits, episodes younger than 63 sessions, `pending_fill` | The gate is about a book that has been trading forward under signed rules. |

Until both are true, the result is inconclusive. The entry is not loosened to get to 48 faster.

When both are true, ops-monitor emits an info finding and the owner stamps one disposition. Nothing promotes itself (F8: an observe metric never applies knobs or fills, and it does not flip the primary learning track by itself).

| Disposition | When it fits | What it does |
|---|---|---|
| `design-open` | Overall fair-cost median above zero. | The owner may make this book the primary learning track. `buy_tier_level` and the matched-30 books stay controls. No live capital. No `decision-review --apply`. |
| `no-design` | Overall median at or below zero, or the owner rejects the book. | Stays observe-only. A redesigned rule is a new registration. |
| `ack` | The owner has seen the board and wants no design work. | Stays observe-only. The finding does not re-fire every day once the stamp is set. |

The control differences, the paired-exit differences, the per-market boards, any `single_market_dependence` flag and the capital view are on the board the owner reads. They do not choose the row.

The 39-week "too rare" line in section 1 is longer than the 26 weeks first drafted because maturity delays every count by 63 sessions, and library entries wait on plan steps 1.8 and 1.9. Until those land the book is FTSE-only in practice, and 26 weeks would almost always trip it.

## 10. Freeze and markers

**Sealed at signature:** the learning question, the primary entry, the one alternative, the primary exit, both comparison exits, the recovery label and reviews, the limits, the cost formula, the scoring boards, and the thickness gate. Signature writes, in the next package, `docs/data/strategy_book_registration.json` copied from this document plus the owner's note. This draft does not write that file.

**One adjustment at signature.** The owner may change proposed numbers in the tables, once, in the signature note, before any score store exists. The owner may not add a third entry rule, a third exit column, a price stop, or a checkpoint model.

**After the first score store is committed** (`strategy_book_replay.json` or `strategy_book_observe.json`):

| Change | What happens |
|---|---|
| A bug fix that makes the code match this text | A logged change marker on the same `registration_id`. Same pattern as N200's `n200-fair-cost-primary-v1`. The marker says what was wrong. History is not quietly rewritten. |
| Any threshold, the learning question, or which rule is primary | A new `registration_id`. The old scores stay under the old id. |
| Adopting the alternative as the book | A new `registration_id`. Forbidden on this id. |

**Parameters that stay frozen after the first look at results.** All of them: RSI 35 and RSI 40, the 10-session entry window, the 3 percent SMA distance, the +10% launch, the checkpoint list and floors, the 63-session fail-to-launch deadline, the 252-session time cap, the 63-session review spacing, the 63-session maturity, the 8% recovery label, both comparison exits as written (including the draft's 10-session high, 15-session swing limit, entry-price target and 4-review cap), the 2-confirm streak, the 10-session cooldown, the 40% recovery share and report-only cap, the 5-episode arming level, the 5-day gap, the 100-unit stake, the fair-cost formula and per-market cost stamps, the 3% stress view, the 48-mature-episode gate with its 6-per-week count and the 39-week rarity line, the 26-week interim read, the graduated-market universe rule, both controls, and the capital-view definitions (20 slots, tie order, 15 random orders, buy-and-hold construction).

**Chosen after seeing results.** The ladder, its +10% launch and 5-point steps, and the 63-session deadline were picked on 2026-11-04 after replays of the same two years of closes (today's buy tier painted back, no gates). Alternatives tried and not chosen: a 20-session high, a 5% trailing exit, a 5-session-low fade, a 63-session hold, price stops at −15%, staged loser sales, time stops at 30 and 63 sessions on the draft exit, deadlines of 20 and 40 sessions, sales at breakeven after the deadline, staged entries, and a checkpoint continuation model. Those replays are why the owner chose this exit. They are not evidence for it. Only the forward book can be, and the paired `draft_v0_exit` column is there so the forward book can also show if the choice was wrong.

**No parameter search on this id.** A search was considered and is not registered. The usual holdout would be the most recent six months of entries. The point-in-time value set only starts on 2026-08-02, and the charts used here end on 2026-10-30. That is about thirteen weeks. Six months of entries do not exist, so there is nothing to hold out. Splitting those thirteen weeks in half after seeing the scores is not a holdout.

Any later rule change treats the first **26 weeks** (proposed) of the forward book as sealed evidence for v0. The new registration is written before its own scores are read. It does not mine those 26 weeks for a better RSI level.

**Later twins, each a new registration, none of them started here.**

- Fills at the next open, once chart payloads grow an `opens` array and the archive can see that open. Queued behind P1/P2 as L667.
- A fair-value recovery target, when phase 4.1 publishes one (L662).
- Dividend-inclusive episode returns, when phase 3.1 lands.

Successor versions follow the version-review rule in the [plan](strategy-reorientation-plan.md#single-track-to-live-owner-2026-11-04): at most one challenger at a time, sealed before its scores are read.

## 11. Data, compute, and the launch queue

P1 still serves live holdings first, then the sealed units already running (strand A buy tier and N200). Under the default in section 13 (question 7) this book takes the **head of the launch queue** at signature, with `launch_queue.data_deepen_requested` true for a narrow scope: filing bodies and memo recency on names in this book's universe that already pass parts 1 and 2. That is the input-quality work its own eligibility needs. It does not ask for new markets, new ingest sprints, or rememo of names outside that scope, and it never takes capacity ahead of holdings or the running units.

The scope matters. On 2026-11-04, 346 library buy-tier names across graduated markets had a research memo folder, but only 48 had memo activity within 21 days (median age 49 days). Without the launch-queue head, most library names stay F9-B failures and the multi-market volume does not arrive. A replay of the price rules alone gave about 20 entries a week across all markets against about 4 on the FTSE 350; the gates and F9-B cut that before any forward trade.

Compute is a walk over the buy tier of every graduated market (65 FTSE names and 346 library names on the 2026-11-03 decline snapshot) and the stored closes. No network, no model call, no new price fetch. Daily ops-monitor is enough.

**Already produced and used.**

- Weekly FTSE screen snapshots since 2026-08-02, including signal, sector, and research verdict.
- Weekly library screen runs for each graduated market, from 2026-07-18 for the larger ones, with signal and research verdict.
- Daily closes for charted names, about two years, enough to warm RSI(14) before that first screen. Charts exist for 403 of the 407 buy-tier names across markets.
- Operating-decline gate on main, one current snapshot, already in the daily refresh, FTSE and library names.
- Sector headwind gate on main, FTSE sectors, in the daily refresh.
- Fair cost table for every graduated market.
- `core_sell_reason` and `thesis_break_confirmed`.

**Not produced, and required before the matching board can be non-empty.**

| Gap | What blocks | What step 2.3 adds |
|---|---|---|
| Sector gate scores FTSE sectors only | Part 3 for library names. Library entries stay at zero without it. | Nothing here. Plan step 1.8 extends the gate to graduated markets. |
| F9-B binds not computed for library names | Library names fail F9-B. | Nothing here. Plan step 1.9 computes the four binds from library research folders. |
| Decline and sector stores are single snapshots | `archive_full_strategy` and any later rebuild of the forward book. | An append-only verdict log, written by the observe job. Not a new ingest. |
| F9 fields absent on `run_*.json.gz` | Archive cannot apply F9-B. Those episodes stay `f9_unverified`. | Forward book computes the four binds at run time. No backfill. |
| No screen archive before 2026-08-02 | No two-year test of part 1. | Accept the thirteen-week rehearsal. Do not buy a price history to invent signals. |
| No opens, highs, or lows | Next-open fills and ATR stops cannot be replayed. | Keep next-close fills. ATR is unused. |
| Statement files overwritten on fetch | The decline gate cannot re-score August from today's files. | Dated statement snapshots stay outside this package. The empty full-strategy archive is the honest result. |
| Chart downsample cliff | `MAX_CHART_POINTS` is 280. Step size is `len // 280`. A series of about 500 bars stays daily (step 1). Past about 559 bars the next chart write keeps every other day, and RSI(14) on that tape is a different indicator. | Step 2.3 reads stored closes and refuses non-daily files. It also raises or bypasses that cap before the 2-year window crosses the cliff. That is a small writer change, not a new market data feed. |

Buy-tier interim coverage is still thin (the decline-gate runbook: interim EPS on 2 of 65 buy-tier names). Many `clear` verdicts are annual. The book inherits that, including the known tendency to flag a commodity name in a down year. Thresholds of the decline gate are settled at the Phase 1 signature, not inside this registration.

## 12. Next package

Short brief for the implementer. Still observe-only. Still no live writes.

**Depends on** plan steps 1.8 and 1.9 for library entries. FTSE entries need neither, so the walker may start on FTSE names and pick up library names when those steps land, with a logged marker; the universe rule does not change.

**Modules.** `src/value_investor/strategy_book_observe.py` owns the walker. It calls `technical_analysis._rsi`, `core_sell_reason`, `note_thesis_streak`, `thesis_break_confirmed`, and `episode_return` / `costs_for_market`. It does not call `assign_timing_signal`, `compute_indicators`, or `compute_trade_plan` to decide a trade. CLI `ftse-strategy-book` with `--replay`, `--forward`, `--no-persist`, and `--as-of`. Replay and forward write different stores and never mix medians.

**Stores**, committed by ops-monitor the same way N200 commits (`GHA_COMMIT_OPTIONAL`):

| Path | Role |
|---|---|
| `docs/data/strategy_book_registration.json` | Seal copy of this document plus the signature note. |
| `docs/data/strategy_book_replay.json` | The three archive results, the alternative column, and the buy-on-signal control. |
| `docs/data/strategy_book_observe.json` | Forward episodes with both comparison exits, boards (overall, launch, by market, paired exits, both controls, capital view), the 26-week interim read, disposition, change markers. |
| `docs/data/strategy_book_gate_log.jsonl` | Append-only verdicts the forward job used. |

**Ops-monitor.** `check_strategy_book_observe` inside `collect_ops_findings`, after the decline check and the sector check. `auto_fixable` false. Findings: refreshed (info), failed (warn), 26-week interim read published (info, once), thickness gate ready for review (info). A row in [`ops-monitor.md`](ops-monitor.md) points here. The refresh finding names counts and the first few tickers. It does not spray rememo or ingest.

**Dashboard.** An Analysis → Observe strip on the N206 pattern, hash `#analysis/observe/strategy-book`, reading the forward store. A compact queue-health line for phase span, mature count, and freshness. No strand A lifecycle writes. No promote button.

**Tests.** Entry fires only on RSI below 35 and a 10-session low. A buy-tier name with a high RSI does not enter. Leaving the buy tier does not exit. A close at +10% launches; the floor is +5%, then rises with each checkpoint and never falls. A close at or below the floor sells at the next close, and a gap fill under the floor is scored as filled. An episode that has not launched sells at session index 63 whatever the price; one that launched on session 62 does not. Session index 252 sells. An 8% drop takes the recovery label and does not sell. Both comparison exits run on every primary entry and never change the primary's entries, cooldown or recovery share; `draft_v0_exit` matches the draft rules on a constructed series. Two `avoid` rows sell; one does not. `insufficient_data` blocks entry and does not, by itself, break a hold mid-way. The decision median counts only mature episodes and values an open launched one at its floor. The interim read's standard error uses entry-week averages. A gap over 5 days does not fill. Fair-cost math matches `episode_return` on a known pair. Archive output keeps the three result keys separate. A thinned chart is refused. Each episode uses its own market's cost row. A library name in a market that is not graduated does not enter. A library run applies only to its own market. The buy-on-signal control opens on a newly eligible name, ignores price timing, and closes at 63 sessions or after 2 ineligible runs. The gate count caps at 6 per entry week while the medians use every mature episode. `single_market_dependence` fires on a constructed case. Capital-days return matches a hand-computed pair. The reference slot book skips a signal when all 20 slots are full and never changes an episode's return. The buy-and-hold reference adds a newly eligible name at an equal stake.

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
| L652 `sell_target_reached` | Maps a target exit, or any return at or above 15%. | A single fixed band sells at the target. The ladder keeps the position past each checkpoint and sells only when the ratcheted floor breaks. |
| L652 `sell_tech_break` | Fires when price vs SMA200 is −8% or worse. | That sells a drop. Part 6 holds the drop until the fail-to-launch deadline. The 8% band in this book only sets the recovery label. |
| L652 `sell_mechanical_leave` | Records a leave-buy-tier close. | Same family as the section 8 control. It is not this book's exit. |
| L541 hold-buffer twin | A longer confirm before the rank exit, on a cold-start fair-cost twin. | A longer wait before a rank sale. This book does not rank-sell. |

## 13. Open questions

Eight decisions. Each default is what this draft seals if the signature note is silent.

1. **Entry window.** Default: 10 chart sessions for the low. The trade plan's 20-day figure is a limit level, and stacking it on RSI below 35 would make entries rarer. At signature the owner may set 20 once. After a score store exists, 20 is a new registration. Under the amended exit the window no longer sets the exit; the 10-session high survives only inside `draft_v0_exit`, which stays as drafted whatever is chosen here.

2. **Which signal is the value set.** Default: raw `signal` in `{buy, strong_buy}`. The owner's part 1 names that value set. `adjusted_signal` is stored and does not gate. Thesis-break `avoid` reads the same raw field, so entry and exit cannot diverge. At signature the owner may switch both reads to `adjusted_signal` once. Switching only one of them is not an option.

3. **What sets the recovery label.** Default on the primary: an 8% drop under the fill before launch. The label sells nothing; it feeds the recovery board and the recovery-hold share. `draft_v0_exit` keeps the draft's 8% or 15-session trigger. A price stop is not one of the choices.

4. **Time cap.** Default: the primary sells any episode still open at session index 252, and the comparison exits sell at the fourth review, as drafted. A human decision would leave episodes open until someone acts, and the thickness gate would wait on that. At signature the owner may replace the 252-session cap with a human hold. Reviews at 63, 126 and 189 stay mechanical either way.

5. **Recovery-hold cap.** Default under the amended exit: report-only. The 40% share is drawn on the board and `cap_would_block` counts the days it was reached. The fail-to-launch deadline already ends every trade that has not launched within 63 sessions. At signature the owner may switch the cap to block new entries at 40% of open episodes, once 5 are open. That rule was not in the exit replay.

6. **When the forward book starts, and on which markets.** Default: start the forward book only after the Phase 1 signature, on the multi-market universe of section 2. FTSE names can enter from the start; library names enter once plan steps 1.8 and 1.9 land. The archive rehearsal of the price rules may run as soon as this registration is signed. It still does not use today's gate verdicts as a pass. At signature the owner may instead name a fixed list of markets once.

7. **Launch-queue position.** Default: head of the launch queue at signature, with the narrow data-deepen scope in section 11 (filing bodies and memo recency on universe names that already pass parts 1 and 2), still behind live holdings and the running units. At signature the owner may keep the book as a waiter instead; the library side then stays thin until memos refresh on their own schedule.

8. **Fail-to-launch deadline.** Default: 63 chart sessions, selling at the next close whatever the price. It bounds part 6 ("hold for recovery while the business case stands") at about three months for a trade that never reaches +10%; in the replay about three quarters of these sales were losses, with a median near −6%. The replay found earlier deadlines (20 or 40 sessions) worse. At signature the owner may instead set no deadline. The primary then follows the `ladder_no_deadline` rules (the draft's review cap ends unlaunched trades after about a year), and that column is dropped because it would duplicate the primary. `draft_v0_exit` stays either way.
