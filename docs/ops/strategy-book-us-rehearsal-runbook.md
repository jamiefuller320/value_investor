# Strategy-book US rehearsal — owner runbook

How to run `strategy-book-us-rehearsal-v0` (plan step 2.5) on your own Mac. The
rules are in [strategy-book-us-rehearsal-registration.md](strategy-book-us-rehearsal-registration.md);
this page is only the commands. The runner is `ftse-strategy-book-rehearsal`
(`src/value_investor/strategy_book_us_rehearsal.py`, inputs in
`src/value_investor/strategy_book_us_tape.py`).

Observe-only. No LLM, no network, no live writes. The forward bench, the live
book and the paper books are unchanged by anything here.

## What lives where

| Thing | Where | In git? |
|---|---|---|
| Sharadar API key | An environment variable in your shell | Never |
| Sharadar zips | `~/sharadar` | Never |
| Panels, prices, daily tape, signals caches | `~/hsr-build`, `~/hsr-mid-build` | Never |
| Per-episode rehearsal output | `~/hsr-build/strategy_book_rehearsal/` (or `--scratch`) | Never |
| Aggregate rehearsal store | `docs/data/strategy_book_us_rehearsal.json` | Yes, you commit it |

The repo is public and the licence is personal use. The runner refuses any
build, Sharadar or scratch path inside the repository, and it checks the store
before every write: no ticker, name, price, fundamental, per-episode return,
per-week vector, cache or panel row, home-directory path, the word "sharadar",
or the value of any `SHARADAR` / `NASDAQ` / `QUANDL` / `API_KEY` environment
variable. A cell with fewer than 5 episodes keeps its count and loses its
statistics. If the check fails, nothing is written and the command says which
field failed.

The ops-monitor warn **Strategy-book US rehearsal: licensed data deletion due**
runs from the first `develop` until `confirm-deleted`. It counts 30 days from
the first licensed run, which is earlier than the licence's 30 days from the
2026-11-09 cancellation (2026-12-09). Either date is fine; do not go past
2026-12-09.

## Before you start

- The parent registration (`owner-strategy-book-v0`) must be signed. The
  runner refuses otherwise.
- Run every command from the repository root on an up-to-date `main`, in the
  virtualenv you already use (`python3 -m pip install -e .`).
- Keep the key out of shell history files you sync. You do not need it again
  after the download.

## 1. Check the download

```bash
cd ~/sharadar
for f in *.zip; do unzip -tq "$f" >/dev/null && echo "ok   $f" || echo "BAD  $f"; done
```

Every line should say `ok`. Re-download any `BAD` file while access lasts
(before 2026-11-09). The runner reads `fundamentals`, `stocks`, `tickers`,
`actions` and `sp500` straight from the zips; you do not need to unzip them.

## 2. Build both panels

```bash
cd ~/path/to/value_investor
ftse-historical-replay build-panel --sharadar-dir ~/sharadar --out ~/hsr-build
ftse-historical-replay build-panel --universe midcap --sharadar-dir ~/sharadar --out ~/hsr-mid-build
```

Read each `build_report.json` locally (about 500 members per date for the S&P
500 build, `panel_coverage` above 0.9). Do not commit, paste or summarise it
(licence §8).

## 3. Build the baseline signals caches (no reveal)

The rehearsal reads `signals_cache.csv.gz` beside each panel. These runs build
them. **Do not pass `--reveal-holdout`.** The runs also rewrite the screen-replay
stores in the repo, so restore those straight after:

```bash
ftse-historical-replay run --panel ~/hsr-build/panel.csv.gz \
  --prices ~/hsr-build/prices.csv.gz --terminal ~/hsr-build/terminal_baseline.csv
ftse-historical-replay run --universe midcap --panel ~/hsr-mid-build/panel.csv.gz \
  --prices ~/hsr-mid-build/prices.csv.gz --terminal ~/hsr-mid-build/terminal_baseline.csv
git restore docs/data/historical_screen_replay.json docs/data/historical_screen_replay_midcap.json
git status --short docs/data
```

`git status` should print nothing. Each first run screens every date once
(roughly 25 minutes). Do not run `ftse-rule-search reveal` or
`ftse-model-mix reveal`.

If you skip this step, or rebuild a panel afterwards, `develop` stops with
"No baseline signals cache …" or "… built from a different panel or screen
code" and prints the command to run.

## 4. Development

```bash
ftse-strategy-book-rehearsal develop --build ~/hsr-build --mid-build ~/hsr-mid-build \
  --sharadar-dir ~/sharadar
ftse-strategy-book-rehearsal status
git add docs/data/strategy_book_us_rehearsal.json
git commit -m "Strategy-book US rehearsal: development block"
git push
```

This walks development signal sessions (2000–2012) twice, baseline and the
−30% delisting sensitivity, writes per-episode files under
`~/hsr-build/strategy_book_rehearsal/develop-<time>/`, and writes the
development block, its sensitivity copy, the development regime cuts and the
month series to the store. `licensed_data.first_used_at` is stamped on the
first run. Expect several minutes and several GB of memory (see
[Performance](#performance)).

## 5. Review

Read the development block (`status` prints the headline; the store has the
rest). Nothing registered changes now. If you find a runner or adapter bug,
log it as an amendment (registration section 9) and recompute:

```bash
ftse-strategy-book-rehearsal develop --build ~/hsr-build --mid-build ~/hsr-mid-build \
  --sharadar-dir ~/sharadar --amendment "what was wrong"
```

Without `--amendment`, a second `develop` refuses.

## 6. Reveal (once)

```bash
ftse-strategy-book-rehearsal reveal --build ~/hsr-build --mid-build ~/hsr-mid-build \
  --sharadar-dir ~/sharadar
ftse-strategy-book-rehearsal status
git add docs/data/strategy_book_us_rehearsal.json
git commit -m "Strategy-book US rehearsal: confirmation reveal"
git push
```

This walks through the end of the confirmation window (2013-01-01 to
2025-09-30) and writes the confirmation block, its verdicts, the confirmation
delisting sensitivity (a primary pass that fails it becomes
`pass_delisting_sensitive`), the confirmation regime cuts and the remaining
months. It recomputes the development block and records
`development_reproduced`. It refuses without a committed development block, a
second time, or when the panels or caches differ from the ones development
used. It does not reveal hsr-v2, hsr-mid-v2, hrs-v2 or hms-v2.

## 7. Delete (by 2026-12-09 at the latest)

```bash
rm -rf ~/sharadar ~/hsr-build ~/hsr-mid-build
```

That removes the zips, both builds, every `signals_cache*.csv.gz`,
`daily.csv.gz`, the panels and the rehearsal scratch. If you used `--scratch`,
delete that directory too. Also remove any copy in `~/Downloads`, empty the
Trash, and delete any Time Machine or cloud-sync snapshot that holds these
directories.

## 8. Confirm deletion and stamp the store

```bash
ftse-historical-replay confirm-deleted
ftse-strategy-book-rehearsal confirm-deleted --check ~/sharadar --check ~/hsr-build --check ~/hsr-mid-build
git add docs/data/historical_screen_replay.json docs/data/historical_screen_replay_midcap.json \
  docs/data/strategy_book_us_rehearsal.json
git commit -m "Confirm deletion of the Sharadar month's licensed files"
git push
```

The first command stamps the screen-replay stores. The second copies that
stamp into `licensed_data.deleted_at` of the rehearsal store; it refuses if a
`--check` path still exists, or if the screen-replay stamp is older than the
rehearsal's first run (pass `--at <ISO time>` to give the time yourself). The
deletion warn clears on the next ops-monitor run.

## Ops-monitor

`check_strategy_book_us_rehearsal` reads the committed store daily and never
writes it. The store is excluded from GHA artifact commits.

| Title | Severity | When |
|---|---|---|
| Strategy-book US rehearsal: development block committed | info | A development block is in the store |
| Strategy-book US rehearsal: confirmation revealed | info | The reveal is in the store |
| Strategy-book US rehearsal: licensed data deletion due | warn | `first_used_at` is set and `deleted_at` is not |
| Strategy-book US rehearsal store unreadable | warn | The store is not valid JSON |

All are `auto_fixable=false`. None triggers rememo, ingest or engineering work.

## Performance

`scripts/strategy_book_rehearsal_scale.py` builds synthetic Sharadar-shaped
SEP and fundamentals tables (random walks, Sharadar column names, no licensed
data), builds the gate tapes and specs the same way the runner does, then runs
the real `develop` and `reveal`:

```bash
python scripts/strategy_book_rehearsal_scale.py --names 1000 --sessions 6500
```

Measured 2026-11-06 on a 4-core Linux VM (Python 3.12), 1,000 names × 6,500
sessions (2000-01-03 to 2024-11-29), highs and lows present:

| Phase | Time | Peak memory after |
|---|---|---|
| Load SEP (543 MB CSV), fundamentals, sector and gate tapes, specs | 16 s | 1.6 GB |
| `develop` (two walks to 2012-12-31, statistics, guard, write) | 189 s | 2.3 GB |
| `reveal` (two walks to 2025-09-30, statistics, recomputed development) | 358 s | 2.9 GB |

4,282 mature primary development episodes and 4,138 confirmation episodes;
`development_reproduced` true; store 136 KB; scratch 75 MB. Peak RSS is
2.9 GB.

Time and memory grow roughly with total name-sessions walked. The real run
walks every name that was ever in either universe, active or delisted, so it
may be several thousand specs, most with shorter histories than 6,500
sessions. Budget about three times these figures (around 30 minutes and
9 GB for both steps) and close other large apps on a 16 GB Mac. The real run
also reads the panels and caches and computes `sp500` membership on every
session, which the synthetic run replaces with fixed sets.
