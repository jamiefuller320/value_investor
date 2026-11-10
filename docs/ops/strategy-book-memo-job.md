# Strategy book signal-day memo job

Observe-only job for registration [section 11](strategy-book-registration.md#11-data-compute-and-the-launch-queue). It asks for a memo when a buy-tier name passes every check except a fresh memo, and on review dates of launched episodes. It does not place a fill, edit a screen, a knob, a paper book, strand A, or N200, and it does not run `decision-review --apply`.

The forward walker is plan step 2.3 and is not built yet. This job and that walker share one entry signal, `src/value_investor/strategy_book_signals.py`. The registration's later name `strategy_book_memo.py` is the package that will read walker output; this step ships the shared signal and the job that evaluates it directly.

## Schedule

`check_strategy_book_memo_job` runs inside `collect_ops_findings`, immediately after the decline check and the sector check. No separate cron.

A session is due when the market's local calendar date (the zone in `session_defaults_for_market`; FTSE and any unmapped market use Europe/London) is after that session. That is "the close has passed" without inventing a close clock. The existing ops-monitor crons already cover the window the registration asks for (after each close, before the next):

- **02:30 UTC** runs before the next Asia / Australia close (ASX cash opens around 23:00 UTC the previous evening and the next local date is already under way by about 05:00 UTC). The workflow gate ignores pre-06:00 UTC successes, so this run does not suppress the morning run (`.github/workflows/ops-monitor.yml`).
- **07:45 UTC** scores the US and European previous session before those markets' next close.
- **13:15 UTC** is the email catch-up. It also calls `collect_ops_findings` when that slot runs.

A forward chart whose latest bar is more than 5 calendar days behind the UTC decision date produces no signal that day (`STALE_CHART_CALENDAR_DAYS = 5`, registration section 3). The cursor advances only through a close that was scored, so a stale chart does not consume the replay window. The CLI `--latest` / `--allow-stale` flags replay those bars for measurement and are not the scheduled path. `--no-persist` leaves the log and the cursor unchanged.

## What it scores

Universe: FTSE 350 (`ftse350`, always included) plus each library market with `is_graduated` true in `docs/data/market_status.json` (registration section 2).

For each due close *t*, every current buy-tier name (`signal` `buy` or `strong_buy` on the newest screen run whose calendar date is strictly before *t*) gets one structured result. Missing input fails closed. Files dated after *t* are not read as a pass. A screen run and a gate store apply only to sessions strictly after their own calendar date (a store dated *t* is `verdict_not_in_force`; a store dated after *t* is `store_after_session`).

| Check | Pass | Constant | Registration |
|-------|------|----------|--------------|
| Part 1 | raw `signal` in `{buy, strong_buy}` | `paper_fund.BUY_SIGNALS` | section 2 |
| Primary RSI | RSI(14) of closes through *t* strictly below 35, via `technical_analysis._rsi` | `RSI_PERIOD = 14`, `RSI_LEVEL = 35` | section 3 |
| Primary low | close equals the minimum of the 10 chart sessions ending at *t* (ties count; shorter history does not fire) | `LOW_WINDOW_SESSIONS = 10` | section 3 |
| Part 2 | operating-decline `verdict` exactly `clear` | — | section 2 |
| Part 3 | `names_by_market[market][ticker].sector_verdict` exactly `sound` | — | section 2 |
| F9-B | `key_filing_bodies`, `fcf_basis_bound`, `overlay_bound`. Library FCF is `free_cashflow` on `screen/latest_signals.csv` when `latest_summary.json` `run_at` is on or before the session close (the inventory's dating). A later CSV is `screen_fcf_after_session`; a missing figure is `screen_fcf_missing`. History run rows do not carry the figure. FTSE still uses the boolean `fcf_basis_overlay` on the run row | — | section 2 |
| Memo | missing, or older than 21 days at the next session | `MEMO_MAX_AGE_DAYS = 21` | section 2 |
| Fill gap | no memo when the next stored bar is more than 5 calendar days after *t*. No stored next bar is not a drop: the memo is for the next close, which may not be on disk yet | `MAX_FILL_GAP_CALENDAR_DAYS = 5` | section 3 |

The pre-registered alternative (RSI(14) below 40 and the close at least 3 percent under SMA(10); `ALT_RSI_LEVEL = 40`, `ALT_SMA_WINDOW = 10`, `ALT_SMA_DISTANCE = 0.03`) is reported as `alternative_entry` and does not request a memo and does not open an episode (section 3). The primary rule has no SMA distance test.

A thinned chart (median calendar gap between stored dates greater than 1 day) fails closed. The registration refuses a thinned tape because it changes RSI(14).

Review dates are session indexes 63, 126 and 189 (`REVIEW_INDEXES`) on launched episodes in `docs/data/strategy_book_observe.json` (section 5). The file does not exist yet, so this path yields nothing. Memo age for a review is read at the review session itself. A review memo does not re-check the price rule or the F9-B binds. Fixture shape the walker can write later: `episodes[]` with `market`, `ticker`, launched (`launched`, `launched_at`, `launch_session`, or `state` `launched`), not closed, and `reviews: [{index, session}]` or `review_sessions` keyed by index.

## Replays on past closes

The decline store, the sector store, filings indexes, and each library market's `latest_signals.csv` (dated by `latest_summary.json`) are single overwritten snapshots. A point-in-time replay of a close before those dates correctly finds nothing: the files are not yet in force, and the job does not pretend they were. The forward job reads the same files after each refresh and before the next close, which is when their dates sit on the session being scored. There is no dating-override flag.

## Spend gate

**Spend is on since 2026-11-10 (owner).** `spend_enabled()` in `strategy_book_memo_job.py` reads `docs/data/strategy_book_registration.json` and returns true only when that file exists, `spend_enabled` is boolean true, and a signature is present (`signed_at`, `signed: true`, or a non-empty `signature` string or object). The flag alone does not turn spend on. While it is false every request is logged `action: dry_run` with `estimated_spend_usd` 0.40 and no model call.

The owner turned spend on before forward go-live: "From a spending point of view I am willing to be generous and resource this as much as necessary initially, assess what is useful (and used) and if budget demands prove excessive economise later," then "Lets switch it on now." The switch is logged in `operational_switches` on the seal with the quote, the budget and the review date. It supersedes the signature note and the sealed registration's status line ("spend stays off until go-live"), which recorded the owner's choice at signature; section 11's rule makes this flag the switch, and the sealed text is not edited. `forward_live` is unchanged (false). This job never reads `forward_live`, so memos are written while the forward book still dry-runs.

**Budget.** The `weekly_ops` cap is $124.50 (`budget.weekly_ops_cap_usd` in `docs/data/library/policy.json`). `budget.strategy_book_memo_raise` is $40 a week, 100 memos at $0.40, up from $16 (40 memos) on 2026-11-05. It sits in `previous_weekly_ops_cap_usd` too, so reverting the cycle-surplus bump keeps it. Sizing: with every gate passing, 29–44 distinct buy-tier names a week hit the entry rule with a missing or stale memo (ISO weeks 43–45 of 2026), $12–18 a week. The registration's after-gates estimate is 25–35 ($10–14). The pool is shared with the Sunday bundle and ladder research, so the headroom check below still applies.

The job asks only for buy-tier names that already pass `key_filing_bodies` and the other F9-B binds, so spend does not reach thin memos without filing bodies. N138 (off-buy-tier zero-filing memos) is untouched.

**Zero requests at switch-on are not low demand.** On the 2026-11-10 run every entry-rule hit (83 in ISO week 45) failed Part 2 and Part 3 as `store_after_session`. `check_operating_decline_gate` and `check_sector_headwind_gate` rewrite their stores with `as_of` set to the run date just before this job, and this job scores closes before the run date, so the in-force rule (a verdict applies strictly after its `as_of`) never passes. `all_but_memo` and `memo_needed` stay 0 and no memo is requested until the job reads the store version that was in force at each close. The forward job's gate shows the same thing.

When the flag is on, the job checks `weekly_ops` headroom first (`weekday_rememo.DEFAULT_MIN_HEADROOM_USD` of $8 plus the $0.40 estimate, and not `constraining`). A short budget is `action: skipped`, `skip_reason: memo_not_ready_budget` (the registration's label is `memo_not_ready`; the log uses the budget-specific reason). A request calls `research.runner._process_ticker`, the same runner admitted rememo uses. The as-of-only instruction is already appended inside the research agent (plan step 1.3); the job does not build a second prompt. It does not delete an existing memo. Estimated spend is recorded on `weekly_ops` only after a successful `requested` row.

A second run for the same `(market, ticker, kind, session)` does not append another row. A `dry_run` does not block a later `requested` row if signature turns spend on for that same close. A `requested` or `skipped` row does block a repeat.

## Memo routine falling behind

Registration section 12 asks for a warn when `memo_not_ready` exceeds a fifth of a week's otherwise-eligible signals (`MEMO_NOT_READY_MAX_SHARE = 0.2`, strict greater-than, so exactly one fifth does not fire). Otherwise-eligible is `all_but_memo`. `memo_routine_falling_behind` returns no finding while `spend_enabled` is false, because dry runs are not budget skips. The function is called on every ops-monitor pass and is live since spend went on (2026-11-10). The finding does not rememo or ingest.

## Spend review

Generosity at switch-on is not a silent default. Every 4 weeks (first 2026-12-08; the date is `operational_switches[].review.next_review_on` on the seal) the owner reviews spend against use ([human task](human-tasks-checklist.md#monthly) `monthly-strategy-book-memo-spend-review`) and keeps, lowers or raises `budget.strategy_book_memo_raise`.

Input: the info finding **Strategy book memo spend this week** (`strategy_book_memo_spend.memo_spend_finding`, called from `check_strategy_book_memo_job`). It reports the latest ISO week's `requested` memos and their $0.40 estimate, budget skips, memo-needed count, the total since switch-on, the `weekly_ops` cap and remaining headroom, and whether the review is due. It is silent while spend is off.

Whether a memo then fed an entry decision (a fill, or `memo_blocked`) or went unused is not tracked yet (queued with `ftse-defer`). Until it is, judge use from the forward book's filled versus `memo_not_ready` counts once `forward_live` is on.

## Stores and findings

| Path | Role |
|------|------|
| `docs/data/strategy_book_memo_log.jsonl` | Append-only. Ticker, market, kind (`signal_day` / `review_date`), session, action (`dry_run` / `requested` / `skipped`), skip reason, memo finish time and verdict when a model ran, estimated spend, `inputs` (repo-relative path and SHA-256 of each file read), `data_commit`. |
| `docs/data/strategy_book_memo_job.json` | Last run per market, counts by ISO week and market (signals, all-but-memo, memo needed, dry-run requests, estimated spend), and that week's memo-needed count versus the 25–35 estimate (registration section 11). |

Both paths are in `GHA_COMMIT_OPTIONAL` (`scripts/gha_commit_ops_monitor.sh`). Ops-monitor commits them with the other observe stores.

Findings (`category: research`, `auto_fixable: false`):

| Title | Severity | When |
|-------|----------|------|
| Strategy book memo job refreshed | info | Every run. Counts and the first few tickers. |
| Strategy book memo job failed | warn | The job raised, or a market reported an error. |
| Strategy book memo job not run on a weekday | warn | UTC weekday and `last_run_at` is missing or before today. A weekend does not warn. |
| Strategy book memo routine falling behind | warn | Spend is on and budget skips exceed one fifth of the week's otherwise-eligible signals. Inert while spend is off. |
| Strategy book memo spend this week | info | Spend is on. Week's requested memos and estimated spend, budget skips, total since switch-on, `weekly_ops` headroom, review date ([spend review](#spend-review)). |

None of these findings rememo, ingest, or mint an engineering task.

## CLI

Drill-down only. `ftse-strategy-book-memo` (`strategy_book_memo_cli`). `--latest N` replays the last N qualified closes per market, including stale charts, and `--no-persist` prints the summary without writing the log. Do not point a measurement replay at the committed log: it would advance `last_session` and mix a one-time historical burst into the week's rate.
