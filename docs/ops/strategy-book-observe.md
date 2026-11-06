# Strategy book observe

Observe-only forward book. No live screen, knob, paper book, strand A, N200, or
`decision-review --apply`. No model calls.

Registration: [strategy-book-registration.md](strategy-book-registration.md)
sections 9(b), 11 and 12. Ops row: [ops-monitor.md](ops-monitor.md).

## Schedule

Named weekday workflow [`.github/workflows/strategy-book-forward.yml`](../../.github/workflows/strategy-book-forward.yml):

```
30 21 * * 1-5
```

UTC, timeout 90 minutes. GitHub's scheduler is best-effort, the same caveat as
email-report. There is no cron-job.org task.

The job refreshes due charts, then runs the forward walk so the walk sees the
new closes. Decline and sector stores are already refreshed by the 07:45 UTC
ops-monitor. `check_strategy_book_observe` only reads the status those runs
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

21:30 UTC is after London 16:30 and after New York 16:00 in both EST (21:00 UTC)
and EDT (20:00 UTC). Hong Kong 16:00 is 08:00 UTC, so that session is already
closed. The per-run cap is 500 names, with a one-second pause between market
batches. Those caps are ops limits, not registration thresholds.

## Close refresh

`ftse-strategy-book-prices` lists charts that would refresh. `--apply` downloads
and writes `docs/data/strategy_book_closes.json` with `closes_through` per
market. A current chart is left byte-for-byte. Weekends do not fetch.

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

Phase 1 governs go-live only. While `forward_live` is false the job still runs
on the current sessions, writes `docs/data/strategy_book_forward_status.json`
(counts, phase span, mature count, freshness), and writes no observe store and
no gate log. Stdout is the same counts. It has no returns.

The seal on the signature branch does not yet carry `forward_live`. The reader
defaults it to false. After the Phase 1 gate review, set `forward_live` true
and set `spend_enabled` true only if `weekly_ops` should pay for signal-day
memos. The human task is `adhoc-strategy-book-memo-spend`. Neither job flips
its own flag.

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

The daily re-hash compares each stored digest to the blob at `data_commit`
(`git show`). If that commit does not contain the path, the row is
`pending_commit`, not a mismatch: the starting commit does not hold files this
run wrote, which is the fourth-amendment case. The check does not rewrite the
log, and it does not compare a later HEAD to yesterday's hash. Ops-monitor
reads `provenance_mismatches` on the status. It does not run `git show`.

What this check does not do: re-hash the blob in the commit that first
contains the log line. That needs the commit created after the log is pushed.
Until then a same-day file stays `pending_commit`.

## Findings

All `auto_fixable` false. Stable titles:

| Title | Severity | When |
|---|---|---|
| Strategy book observe refreshed | info | Status is at or after the latest 21:30 UTC weekday slot. Names counts and the first tickers. |
| Strategy book observe failed | warn | Missed that slot, the status has errors, or `provenance_mismatches` is non-zero. |
| Strategy book 26-week interim read published | info | Once, when the walk first publishes the interim read. The job stamps `interim_announce`. The check does not write. |
| Strategy book thickness gate ready for review | info | Live observe store exists, the gate is ready, and no disposition is stored. |
| Strategy book memo routine falling behind | warn | Walk share: `memo_not_ready / (filled + memo_not_ready + memo_blocked) > 0.2`. |
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

One writer each. They are not on the ops-monitor optional or owned lists.
`docs/data/charts` is owned here so a close refresh is committed, and email-report
still publishes charts. The JSON stores are not shared.

## Dashboard

Analysis → Observe, hash `#analysis/observe/strategy-book`. The strip reads
`strategy_book_forward_status.json`: phase span, mature count, freshness.
Read-only. No promote button. No strand A writes. The score store is not rendered.

## Tests

No network. Price fetch is mocked. Do not point `--apply` at a live source
from a test. The replay of committed data waits until the seal is merged.
