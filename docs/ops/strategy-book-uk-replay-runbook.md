# UK/Europe strategy-book replay — runbook

Observe-only runner for plan step 3.3. Design:
[`strategy-book-uk-replay-design.md`](strategy-book-uk-replay-design.md). Draft
registration:
[`strategy-book-uk-replay-registration-draft.md`](strategy-book-uk-replay-registration-draft.md).
`influences_live` is false. No language model chooses an entry, an exit, or a review.

The walk is `strategy_book_observe.walk_book` in the US rehearsal mode. This
runner only builds the EODHD panel, the gates, and the delisting haircuts, then
calls that walker. Window medians, the family interval and the verdict helper
are the US rehearsal functions.

## What is committed

| File | Contents |
|---|---|
| `docs/data/strategy_book_uk_replay_registration.json` | Draft until the owner runs `seal`. `sealed` stays false in git until that stamp. |
| `docs/data/strategy_book_uk_replay.json` | Aggregates only: counts, medians, intervals, bar flags, bias shares, calls used. |

EODHD prices, statement values, dividend amounts and per-episode rows are not
committed. A run caches them under `UK_REPLAY_CACHE` (default: the system temp
dir `strategy_book_uk_replay`, or `uk-replay-cache/` on the Actions runner). Between
Actions runs the cache is kept only as `uk-replay-cache.tar.enc`, AES-256 encrypted with
the `EODHD_API_TOKEN` secret: Actions caches in a public repo can be restored by fork-PR
workflows, which never receive secrets.
That directory is gitignored. Development keeps the raw files: the reveal
walks the same cache (its fetch makes no calls once every symbol is done).
The reveal deletes the raw and FX files after the holdout write, and
`confirm-deleted` removes the rest by 2026-12-10. `develop` and `reveal` refuse
to write when the cache holds no records. The resume cursor keeps symbol
done-flags and the day's weighted-call count. It is not committed.

The Actions cache is evicted after 7 days unused. Each `development` or
`reveal` dispatch saves it again; if neither runs for 6 days, re-dispatch
`fetch` (no EODHD calls when complete) to keep it.

## Seal, then calls

No replay call to EODHD runs until the registration file has `sealed: true` and
`document_sha256` equals the sha256 of
`docs/ops/strategy-book-uk-replay-registration-draft.md`.

```bash
ftse-strategy-book-uk-replay seal --owner "<name>"
```

That records the sha256 and the owner stamp. It does not call EODHD. Target
date 2026-11-18. Change a proposed number in the constants block before this
stamp if the draft changes; do not seal from this runbook's author.

The reveal is a second stamp, after the development block is committed:

```bash
ftse-strategy-book-uk-replay stamp-reveal --owner "<name>"
```

`reveal` refuses without that stamp and without a committed development block.

## Workflow

`.github/workflows/strategy-book-uk-replay.yml` is `workflow_dispatch` only.
Input `phase` is `fetch`, `development`, or `reveal`. Secret
`EODHD_API_TOKEN`. A missing secret exits 0 and commits nothing. The job
commits only `docs/data/strategy_book_uk_replay.json`.

Soft cap: 90,000 weighted calls in a UTC day (fundamentals weigh 10). The LSE
plan is 86,818. Hitting the cap writes `status: partial` and a cursor. The
next UTC day resumes. It does not drop the unfinished names quietly. One probe
symbol is fetched first. A fundamentals or dividend response that carries a
call-weight header other than 10 or 1 stops the job before the loop.

Time limit: the LSE plan is about 26,700 requests at no more than 5 a second,
so one fetch can take several hours. The job limit is 350 minutes and the
runner stops itself after `UK_REPLAY_MAX_MINUTES` (320 in the workflow) with
`status: partial`, `stopped_by: time_budget`. Re-dispatch `fetch` to resume.
The cursor is saved every 25 names and every cache file is written atomically,
so a hard cancel loses at most 25 names of done-flags; those names are skipped
on resume because their files are already there. A cache file that does not
parse is fetched again. Re-dispatching on the same UTC day counts against the
same soft cap.

XETRA and PA that are still unfinished after 2026-11-24 are dropped.
`europe_not_fetched` is set and the scored book is LSE only.

```bash
ftse-strategy-book-uk-replay plan
ftse-strategy-book-uk-replay fetch
ftse-strategy-book-uk-replay develop
ftse-strategy-book-uk-replay reveal
ftse-strategy-book-uk-replay confirm-deleted
```

`plan` does not call EODHD. `confirm-deleted` stamps `licensed_data.deleted_at`
and removes the cache, including the resume cursor. A second `develop` after a
committed development block is refused. That pass would be an amendment, and
this runner does not rewrite the block.

## Memory and run time

The full cache is roughly 13.6k symbols. `develop` and `reveal` read one
symbol's JSON at a time and keep only what the walk reads: parsed statements,
share rows, dividends, splits and prices as columns
(`_slim_record` in `src/value_investor/strategy_book_uk_replay.py`). The
decline verdict is computed once per span of identical visible statements and
the sector table once per sector label and session. Outputs are pinned to the
pre-change runner by `tests/test_strategy_book_uk_replay_develop.py`
(change marker `develop-scale-v1`).

## Ops monitor

`check_strategy_book_uk_replay` in the daily ops-monitor pass. No finding when
the aggregate store is absent. Info with the phase and verdict when it reads.
Warn when the JSON is unreadable. `auto_fixable` is false. The check does not
call EODHD and does not heal the store.

## Companies House matching

The development and reveal walks read every name in
`docs/data/ch_failed_name_statements.json` at the development commit. A store
row is attached to an EODHD symbol only when its EPIC equals the symbol code
(or the code's `_`-suffixed delisted form) and its leaving date is within 31
days of the symbol's last bar. Rows without an EPIC need a name match plus the
leaving date. The seven hand-verified probe names carry neither and keep the
name match. Two candidates for one symbol match nothing. See
`match_ch_record` in `src/value_investor/strategy_book_uk_tape.py`.
