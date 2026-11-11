# Memo-free forward shadow

Owner, 2026-11-11. Report-only strategy-book component. It does not open
episodes on the sealed book (`owner-strategy-book-v0`), it does not change
that book's store, and it does not count toward the thickness gate or the
bench. `influences_live` is false. A rule change to the book still needs a
new `registration_id`.

The learning question: if the book only kept the filters the owner named
(cheap on the price rule, no operating decline, no sector-wide trouble), how
many more episodes would it have, and how would those episodes have looked at
10 and 20 sessions?

## What is hard, and what is only a label

The shadow uses the sealed primary entry and the sealed primary exit. Same
costs, same next-close fills, same 5-day gap rule, same late-signal rule, one
open episode per name, the same 10-session cooldown, and the same 100-unit
fixed stake (fixed-stake v0: a fixed amount per entry, not a share of a fund).

Hard filters, same as the book:

- price rule: RSI(14) below 35 and a 10-session closing low
- operating-decline gate must be `clear` (the name's own results are not deteriorating)
- sector-headwind gate must be `sound` (the sector as a whole is not in trouble)
- research verdict is not a failed verdict (`pass`, `sell`, `avoid`, `exit`)
- the name is in the buy tier (`buy` or `strong_buy`)

Dropped as hard filters, kept as labels on `failed_binds`:

| Label | Meaning |
|---|---|
| `key_filing_bodies` | No filing body on the name (F9-B: the input-quality binds) |
| `fcf_basis_bound` | Free-cash-flow basis not bound |
| `overlay_bound` | Research overlay not bound |
| `memo_recent` | No research memo fresh enough for the book (within 21 days) |
| `memo_verdict` | A fresh memo would have failed the book's verdict check |

Why drop all four F9-B binds, not only the memo: the owner's strategy names
the price rule, operating performance and the sector. Filing bodies, the
cash-flow basis, the overlay and the memo are checks that the inputs are good
enough to trust, which is why the sealed book still requires them. Most
entry-rule hits were stopping on those checks, and the memo job only asks for
a memo after every other check has passed, so the book was not learning the
strategy it named. Labelling the failures lets a later read split "would have
failed the memo only" from "would also have failed a filing body".

The decline and sector gates stay hard. An episode the gates refuse is not a
shadow episode. The book already has its own gate-rejected columns for that
question.

## Markets

Coverage is whatever the daily close refresh already keeps current. That job
(`strategy_book_prices.py`) walks the FTSE 350 plus each graduated library
market, and it refreshes a market only when that market has a cash-close time.
`euro_depth` and `sp400` have no cash-close row, so they are not in this
shadow. This change does not extend the refresh.

Graduated means the market has finished its ingest bar (`is_graduated` on
`market_status.json`). The shadow's `markets_covered` list is that set, minus
any market with no cash close.

## Past sessions are not relabelled

The store is rebuilt from `forward_start` on every run, the same window as the
book (2026-11-10 at go-live). For every session before the one being scored,
filing, cash-flow, overlay and memo facts come from
`docs/data/strategy_book_gate_log.jsonl` and
`docs/data/strategy_book_memo_log.jsonl`. A fact dated today is not in force
on an earlier session.

A session the log never covered does not fill. Two rules do that, both already
used by the book:

- if no logged fact is in force yet, the entry fails closed
- if the session was never logged, the time the signal was "seen" is this run,
  which is after the next close, so the fill is a late signal and is dropped

Today's session uses today's stores, as the book does. The next run will read
that session back from the log.

## Early marks

`early_marks` is on each shadow episode, and the same shape is computed for
each primary episode of the sealed book into `book_early_marks` in this store.
The sealed observe store is only read.

The fill is session index 0, matching the book. `s10` is 10 chart sessions
after the fill. `s20` is 20.

| Field | Meaning |
|---|---|
| `available` | False, with `reason` `not_yet` or `no_fill_bar` or `no_chart`, when that session does not exist yet |
| `return_from_fill` | Gross close divided by the fill close, minus 1. This is the same change the launch test uses |
| `max_drawdown` | Worst close versus the highest close from the fill through this bar. Zero if the close never fell. A fall of 4% is `-0.04` |
| `launch_progress` | `return_from_fill` divided by 0.10. 1 means the close is exactly +10% from the fill |
| `launched` | True once any close from the fill through this bar is at least +10% |
| `channel_direction_at_fill` | 6-month channel direction (`ch126`) at the fill: `rising`, `falling` or `sideways` |
| `channel_direction_at_mark` | The same channel at this bar |
| `channel_direction_change` | True when both directions exist and they differ |

`outcome_63` is the fair-cost return (after the market's buy and sell cost)
at 63 sessions after the fill. If the episode closed at or before that bar,
the value is the realized fair-cost return (`outcome_63_basis` =
`realized_exit`). Otherwise it is a mark of the close on that bar
(`mark_at_s63`). `not_yet` means the episode is still open and has not reached
63 sessions.

## Pending fills

A signal on the latest stored bar has no next close yet. It is `pending_fill`,
not an episode, which is the same rule as the book. The pending row already
carries `failed_binds` from the signal session. The memo verdict is labelled
only once the fill exists. Counted, open and mature stay on filled episodes.

## Boards

`boards` on the shadow episodes:

- counted, open, mature (mature means the fill is at least 63 sessions old)
- median fair-cost return and median matched excess, mature episodes only
  (matched excess is the episode's return minus an equal-weight basket of that
  market's buy tier over the same dates)
- launch share: share of counted episodes that have launched, including ones
  still open
- capital-days return: fair-cost profit divided by stake-days, times 365
- the same figures by market
- the same figures by `failed_binds` label (an episode with two labels is
  counted under each) and by the exact label set (`by_failed_bind_set`, where
  `none` means every bind would have passed)

`early_outcomes` relates those early states to `outcome_63`:

- median outcome by the s10 return bucket and by the s20 return bucket
- median outcome for episodes that had launched by s20, and for those that had not
- buckets: under −5%, −5% to 0, 0 to +5%, +5% to +10%, +10% or more
- each cell shows `n`. Below 8 episodes the cell is `insufficient_data` and
  the median is null. The board's own `status` is `insufficient_data` until
  at least one cell reaches 8

`book_early_marks.outcome_board` is the same board for the sealed book's
primary episodes. Those rows are not mixed into the shadow medians.

## Schedule and files

Weekdays, in `.github/workflows/strategy-book-forward.yml`, after the forward
walk (17:45 and 21:30 UTC, cron-job.org primary). The step is
`continue-on-error`, so a shadow failure does not block the book's commit.

```bash
ftse-strategy-book-memo-free-shadow --repo-root .           # counts only
ftse-strategy-book-memo-free-shadow --repo-root . --apply   # write the store
```

Writes `docs/data/strategy_book_memo_free_shadow.json` only. That file is on
the forward workflow's commit list. Email-report does not commit it.

Module: `src/value_investor/strategy_book_memo_free_shadow.py`.

## Ops-monitor

`check_strategy_book_memo_free_shadow` runs inside `collect_ops_findings`.
It does not walk and it does not download.

| Title | Severity | When |
|---|---|---|
| Strategy book memo-free shadow refreshed | info | Store exists and `generated_at` is at or after the latest 21:30 UTC weekday slot |
| Strategy book memo-free shadow missing | warn | No store file |
| Strategy book memo-free shadow stale | warn | Store is older than that slot |
| Strategy book memo-free shadow unreadable | warn | File is not valid JSON |

`auto_fixable` is false. The finding does not rememo, ingest, or open a book
episode.

## What this is not

It is not a new route to live capital. Adopting any of these entries into the
sealed book is a version review and a new `registration_id`. It is not the
bench: bench columns score filters on the book's own entries. It does not
spend on memos. It does not ask the memo job to write for names that failed
only the memo.
