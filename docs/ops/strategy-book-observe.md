# Strategy book observe

Observe-only forward book. No live screen, knob, paper book, strand A, N200, or
`decision-review --apply`. No model calls.

Primary orders are copied, observe-only, onto a Trading 212 practice account
by [strategy-book-demo-mirror.md](strategy-book-demo-mirror.md). That ledger
does not feed this book.

The seven step 3.2 proof bars are scored, observe-only, by
[strategy-book-proof.md](strategy-book-proof.md). That board does not feed
this book. Meeting every bar lets the owner consider step 5.5 and opens nothing.

Registration: [strategy-book-registration.md](strategy-book-registration.md)
sections 9(b), 11 and 12. Ops row: [ops-monitor.md](ops-monitor.md).

## Schedule

Named weekday workflow [`.github/workflows/strategy-book-forward.yml`](../../.github/workflows/strategy-book-forward.yml):

```
45 17 * * 1-5
30 21 * * 1-5
```

UTC, timeout 90 minutes. The primary trigger is cron-job.org
`workflow_dispatch` (`scripts/import_cron_jobs.py` keys
`strategy-book-forward-europe` and `strategy-book-forward`, re-imported by
`import-ingest-crons.yml` when the script or this workflow changes). The
GitHub `schedule:` lines are a backup. In the week of 2026-11-02 GitHub
created both scheduled runs 3.5–6 hours late (`createdAt` 01:03 UTC Saturday
for the Friday slot, 03:43 UTC Tuesday for the Monday slot), so it is not
the primary.

The 17:45 slot was approved by the owner on 2026-11-10 ("A second 17:45 run is fine").
The partial-bar clip and refresh trim below are logged as change marker
`owner-strategy-book-v0-partial-bar-clip-v1` in `docs/data/strategy_book_registration.json`
(bug fix, no rule change; owner: "Yes - log the partial-bar clipping").

The 17:45 slot exists for London and continental Europe. Yahoo's daily
history has those bars intraday and for some hours after the close, then
drops the just-completed bar overnight until about the next session. Chart
history shows it: European bars present at 17:55 and 18:08 UTC (2026-09-21,
09-23), but absent for every continental exchange at 23:42 UTC (2026-10-30)
and for London and the continent at 03:45 UTC (2026-11-10, Swiss and US
present). The 21:30 slot covers New York and Toronto and retries anything
the first slot missed.

Both slots are the same job. Each fetches only charts behind a market's
latest completed session and drops bars dated after it, so a second, late,
or weekend run is a safe catch-up and does not write a partial intraday bar.

The job refreshes due charts, then runs the forward walk so the walk sees the
new closes. Decline and sector stores are already refreshed by the 07:45 UTC
ops-monitor. The walk reads their dated copies under `docs/data/gate_history/`,
one gate observation per version date, not the live files, so a refresh dated
today never decides an earlier close. `check_strategy_book_observe` only reads the status those runs
leave. It does not download and it does not walk.

### Why this is not ops-monitor

Measured on 2026-11-05.

A local last-close scan of 1,269 chart files took 0.17 seconds and read
25,476,302 bytes (about 21 KB each). 1,139 of those files already ended on
2026-10-30. The refresh does not rebuild a chart whose last close is the
latest completed session. It covers graduated-market buy-tier names, open
episodes, and benchmark basket members, not all 1,269 files. One Yahoo batch
per market goes through `ensure_price_charts` (`period=2y`, `auto_adjust=True`).
A two-year window is about 500 bars. `MAX_CHART_POINTS` (280) thins a series
only at 560 bars or more, so this call keeps the daily tape.

The existing chart rebuild is `ensure_price_charts(fetch=True)` inside
email-report publish. That workflow is `workflow_dispatch` only, timeout 360
minutes. Recent whole-job durations (screen plus publish, so an upper bound on
the chart step): 189.5 min failure (2026-11-04), 124.7 min (2026-11-01),
165.9 min (2026-10-30), 159.0 min (2026-10-28), 210.4 min failure (2026-10-26),
88.8 min (2026-10-25), 132.9 min (2026-10-18), 78.3 min (2026-10-11).

Ops-monitor crons are `30 2 * * *`, `45 7 * * *`, and `15 13 * * *` UTC. The
gate skips a later same-day success after 06:00 UTC, so the run that matters
is 07:45 UTC. Recent real runs: 7.0 min (2026-11-05 07:45), 10.1 min (02:30),
6.2 min (2026-11-04 20:24), 32.3 min failure (2026-11-04 15:44). 07:45 UTC is
before the London 16:30 close and the New York 16:00 close, and 15 minutes
before the Hong Kong 08:00 UTC close. It can refresh the previous completed
session. It cannot refresh today's cash close, and a Yahoo fetch of the buy
tier does not belong on a 7–10 minute job that then sends mail.

17:45 UTC is after the London and continental closes (16:30 UTC in winter,
15:30 UTC in summer). 21:30 UTC is after New York 16:00 in both EST (21:00 UTC)
and EDT (20:00 UTC). Hong Kong 16:00 is 08:00 UTC, so that session is already
closed at both slots. The per-run cap is 500 names, with a one-second pause between market
batches. Those caps are ops limits, not registration thresholds.

## Close refresh

`ftse-strategy-book-prices` lists charts that would refresh. `--apply` downloads
and writes `docs/data/strategy_book_closes.json` with `closes_through` per
market. A current chart is left byte-for-byte. Due lists use each market's
latest completed session, not the wall clock: a Friday slot that starts on
Saturday still fetches Friday's closes. A weekend run with nothing due
fetches and writes nothing (`skipped: weekend`). Fetched bars dated after
`closes_through` are dropped.

`short_of_session` per market counts buy-tier charts that still end before
`closes_through` after the fetch (usually Yahoo has not published that
session's bar yet). It is reported as info **Strategy book closes short of
session** and the next slot retries those charts. It is not the registration
stale rule below.

After the fetch, a market is **Strategy book closes stale** when more than a
tenth of its buy tier (`STALE_CLOSE_MAX_SHARE`) is still more than one session
behind. One session behind does not warn. The denominator is the buy tier.
Open episodes and basket members are refreshed and are not in that share.

## Forward job

`ftse-strategy-book-forward` calls `walk_book` and `build_boards` with
`options_for("forward")` and `entry_not_before` set from the seal. The first
session is `forward_start`, else `start_date`, else `observe_start`, else the
`signed_at` calendar date, else the decision date. It does not reach back to
August–October. That window is the archive replay.

Screen files opened for the walk are those dated in the 14 days before the
start, plus the single newest run strictly before the scored session. That
14-day bound is an ops limit so this job does not read the archive.

## Go-live

`forward_live` lives on `docs/data/strategy_book_registration.json` and is read
with the same signature test as `spend_enabled`. The two flags are independent.
A missing file, a missing key, or any value other than boolean true is false.
This includes the string `"true"`.

The go-live commit sets `forward_live: true` and `forward_start` to the go-live
date (YYYY-MM-DD) together. Owner, 2026-11-10: "Lets align the forward start
and live dates", so `forward_start` will equal the go-live date (recorded on the
seal as `phase1_gate_decision.forward_start_alignment`). Without it the walk
would start on the `signed_at` date and replay the sessions before go-live as
late signals ([forward job](#forward-job)).

**Live since 2026-11-11 (owner).** The go-live commit set `forward_live: true`
and `forward_start: "2026-11-10"`, the last completed session at go-live, so
the 2026-11-10 signals were first seen by a manual live run that morning,
before their fill close (`operational_switches`, `forward_live` row). The book
stays observe-only (`influences_live` false).

Phase 1 governs go-live only. While `forward_live` is false the job still runs
on the current sessions, writes `docs/data/strategy_book_forward_status.json`
(counts, phase span, mature count, freshness), and writes no observe store and
no gate log. Stdout is the same counts. It has no returns.

The status file also carries a `candidates` roster for the strategy dashboard's
Candidates tab. One row per name the forward job loaded, plus a current buy-tier
name that never loaded because it has no usable chart or no session on or after
the start. The row is that name's latest chart session in the window. Verdicts
are the ones the walk already uses (the gate-log in-force rule, the entry-low
price flags, and the tally's blocked reason). There are no prices, returns, or
scores. `candidates_session_by_market` is the latest of those sessions per
market, or the scored session when a market's rows have no bar.

The book's screen stays the history snapshot. A same-stamp `signals_*.csv`
can still list a buy-tier name that snapshot omits. That name is a roster row
only: it is not loaded as a spec and the book cannot buy it. `decline`,
`sector`, `gate_as_of`, `f9`, and `price_rule` are null on these rows. `signal`
and `adjusted_signal` come from the CSV.

- `market`, `ticker`, `session` — `session` is that latest bar as an ISO date, or null when the name has no bar in the window.
- `signal`, `adjusted_signal` — the screen row in force for that session (a run dated strictly before it). When `session` is null, the same rule is applied to the market's scored session. Null when no run is in force.
- `decline`, `sector` — the part 2 and part 3 verdicts in force for that same session: the dated gate version ([dated verdict history](operating-decline-gate.md#dated-verdict-history)) with the latest date strictly before the session. `gate_as_of` is that version's date. When no version is dated before the session, both are null and `gate_as_of` is the earliest later version's date, or null when there is no gate.
- `f9` — `pass`, or the list of failing binds, copied from the gate-log row for the scored session. Null when that row was not built.
- `price_rule` — true when the registered short-term low (RSI below 35 and a 10-session close low) fires on that session, false when it does not, null when there is no chart.
- `outcome` — the signal event kind when the name signalled (`filled`, `pending_fill`, `late_signal`, `memo_not_ready`, `memo_blocked`, and the other signal kinds). Otherwise the blocked reason the tally already records (`no_chart`, `not_buy_tier`, `gate`, `f9`, `price`, and the rest). A declining or headwind name is `gate`; the verdict is `decline` or `sector`. A miss of the short-term low is `price`. `learning_pool_excluded` means the signals CSV lists the name and the history snapshot omits it because it is in that market's learning-pool exclusion, so it is not in the book's universe. `not_in_book_screen` means the signals CSV lists the name and the snapshot omits it for any other reason, so it is not in the book's universe.

The reader defaults `forward_live` to false. The owner set it true on
2026-11-11 after the Phase 1 gate review (human task
`adhoc-strategy-book-memo-spend`).
`spend_enabled` is already true: the owner switched memo spend on on 2026-11-10,
before go-live ([memo job spend gate](strategy-book-memo-job.md#spend-gate)).
Neither job flips its own flag.

When both the signature and `forward_live` are true, `--apply` writes
`docs/data/strategy_book_observe.json` and appends
`docs/data/strategy_book_gate_log.jsonl`.

`ftse-strategy-book-replay --persist` writes `docs/data/strategy_book_replay.json`
(boards, counts and episode counts per arm) and
`docs/data/strategy_book_replay_episodes.json.gz` (every episode and event, compact)
when the registration is signed. The full payload is about 30 MB as JSON, so the
per-episode rows ship gzipped. A fixture outside `docs/data` still writes
under the fixture. The first replay ran on 2026-11-06 after the seal reached main.

`ftse-strategy-book --replay` and `--forward` dispatch the two jobs.
`--no-persist` skips writes. `--as-of` sets the forward clock.

## Gate log and provenance

Append-only, and only while live. One session row per name actually scored,
plus entry, exit, and review rows for that session. Each row has `inputs`
(`path`, `sha256`) and `data_commit` (the commit the run started from, context
only). A same-day rerun does not append again once `gate_logged_through`
covers that session.

The observe store is rebuilt from the start date on every run, so an earlier
session reads its F9-B binds and memo from this log, not from today's stores.
Each session row carries `f9` (pass or gap list), `memo_at` and `memo_verdict`
as the job saw them that day; signal-day memos also come from
`strategy_book_memo_log.jsonl`. Today's stores are used only for the session
being scored. A session the log never covered has no F9-B fact and cannot
open an entry. Without this, the store dated today's binds after every earlier
signal, and a fill vanished on the next run (change marker
`owner-strategy-book-v0-forward-history-fix-v1`).

The `memo_recent` entry in a row's `f9` list is judged at the signal close and
is a label only. The memo bind decides once, at the fill (registration
section 2): the latest memo finished before the fill session's close, under
21 days old, with a verdict that is not failed; otherwise `memo_not_ready` or
`memo_blocked`. A signal-day memo written overnight therefore counts. Until
2026-11-11 the walk also demanded a fresh memo at the signal close, which
blocked every signal-day memo (change marker
`owner-strategy-book-v0-memo-at-fill-fix-v1`).

The daily re-hash compares each stored digest to the blob in the commit that
holds the row: the first commit after `data_commit` that touches the gate log,
which is the run's own commit (this workflow is the log's single writer).
`data_commit` itself is only where the run started; the close refresh rewrites
charts before the walker reads them, so comparing there reported every
refreshed chart as a mismatch (52 on the first live run, 2026-11-11). A row
whose run is not committed yet, or whose commit is not in the clone (the
workflow's shallow checkout), is `pending_commit`, not a mismatch. Per-episode
`provenance_missing` is decided inside the run from the bytes it read, and is
not affected. The check does not rewrite the log, and it does not compare a
later HEAD to yesterday's hash. Ops-monitor
reads `provenance_mismatches` on the status. It does not run `git show`.

What this check does not do: re-hash the blob in the commit that first
contains the log line. That needs the commit created after the log is pushed.
Until then a same-day file stays `pending_commit`.

## Memo-free shadow

A separate report sits beside this book. It scores the same primary entry and
primary exit without the memo bind, and it records early marks at 10 and 20
sessions. It does not write this store and it does not count here. See
[strategy-book-memo-free-shadow.md](strategy-book-memo-free-shadow.md).

## Reviews

Closed episodes are not reviewed inside this walker. The daily ops-monitor
check reads this store and the gate log and writes
`docs/data/strategy_book_review_queue.json`. See
[strategy-book-reviews.md](strategy-book-reviews.md). The walker does not
write that queue, and a review never changes the book.

## Findings

All `auto_fixable` false. Stable titles:

| Title | Severity | When |
|---|---|---|
| Strategy book observe refreshed | info | Status is at or after the latest 21:30 UTC weekday slot. Names counts and the first tickers. |
| Strategy book observe failed | warn | Missed that slot, the status has errors, or `provenance_mismatches` is non-zero. |
| Strategy book 26-week interim read published | info | Once, when the walk first publishes the interim read. The job stamps `interim_announce`. The check does not write. |
| Strategy book thickness gate ready for review | info | Live observe store exists, the gate is ready, and no disposition is stored. |
| Strategy book memo routine falling behind | warn | Walk share: `memo_not_ready / (filled + memo_not_ready + memo_blocked) > 0.2`. |
| Strategy book closes short of session | info | After an applied refresh, some buy-tier charts still end before that market's `closes_through`. Names the market, count and first tickers. The next slot retries. |
| Strategy book closes stale | warn | After the refresh, more than a tenth of a market's buy tier is more than one session behind. |
| Strategy book late signals | warn | `late_signal / signals > 0.1`. No warn when there are no signals. |
| Strategy book Trading 212 catalogue stale | warn | Catalogue missing or older than 35 days. Not the 14-day "Trading 212 catalogue stale" finding. |
| Strategy book forward go-live pending | info | `forward_live` is false. |

The memo job already emits **Strategy book memo job not run on a weekday** and,
while spend is on, its own **Strategy book memo routine falling behind** for
budget skips. This check does not repeat the missed-run title. The two checks
together cover the registration's "memo share or the job has not run" line
without firing the same title twice for one missed run.

## Writers

`strategy-book-forward.yml` owns, and email-report excludes:

- `docs/data/strategy_book_observe.json`
- `docs/data/strategy_book_replay.json`
- `docs/data/strategy_book_replay_episodes.json.gz`
- `docs/data/strategy_book_gate_log.jsonl`
- `docs/data/strategy_book_closes.json`
- `docs/data/strategy_book_forward_status.json`
- `docs/data/strategy_book_demo_ledger.json` (practice-account mirror; see [strategy-book-demo-mirror.md](strategy-book-demo-mirror.md))
- `docs/data/strategy_book_proof_board.json` (step 3.2 proof bars; see [strategy-book-proof.md](strategy-book-proof.md))
- `docs/data/strategy_book_memo_free_shadow.json` (memo-free shadow; see [strategy-book-memo-free-shadow.md](strategy-book-memo-free-shadow.md))

One writer each. They are not on the ops-monitor optional or owned lists.
`docs/data/charts` is owned here so a close refresh is committed, and email-report
still publishes charts. The JSON stores are not shared.

## Dashboard

Analysis → Observe, hash `#analysis/observe/strategy-book`. The strip reads
`strategy_book_forward_status.json`: phase span, mature count, freshness.
The same file's `candidates` roster is the per-name list for the strategy
dashboard's Candidates tab (field list under Go-live). Read-only. No promote
button. No strand A writes. The score store is not rendered.

## Tests

No network. Price fetch is mocked. Do not point `--apply` at a live source
from a test. The replay of committed data waits until the seal is merged.
