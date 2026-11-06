# Strategy-book US rehearsal — owner runbook

How to run `strategy-book-us-rehearsal-v0` (plan step 2.5) on your own machine. The owner's machine is a Windows laptop running Git Bash (MSYS2 UCRT64); the commands are bash and also work on macOS or Linux. The
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
- **Windows.** A plain clone fails on Windows because a few chart and research
  paths use reserved device names (`CON.DE`, `PRN.AX`, `PRN.L`; queued as L679).
  Use a sparse checkout that skips the bulk data folders, then a venv whose
  activate script is under `Scripts`:

  ```bash
  cd ~/value_investor
  git sparse-checkout init --no-cone
  git sparse-checkout set '/*' '!/docs/data/charts/' '!/docs/data/library/' \
    '!/docs/data/research/' '!/docs/data/archive/' '!/docs/data/history/'
  git checkout -f main
  py -3 -m venv .venv && source .venv/Scripts/activate && pip install -e .
  ```

  Commit only the stores named on this page from that checkout.
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
cd ~/value_investor
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
first run. Expect about five minutes and under 2 GB of memory with the default
`--batch-size 400` (see [Performance](#performance)). If it warns that
memory is short, close other programs or pass the smaller `--batch-size` it
suggests; the blocks do not depend on the batch size.

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
`daily.csv.gz`, the panels and the rehearsal scratch. The scratch also holds
the temporary daily-bar split (`_tapes-*` folders) while `develop` or `reveal`
runs; the runner deletes it at the end, but an interrupted run can leave one
behind, and this command removes it. If you used `--scratch`, delete that
directory too (including any `_tapes-*` folder in it). Also remove any copy in `~/Downloads` or the home folder
the download ran in, empty the Recycle Bin (or Trash), and delete any File
History, OneDrive, Time Machine or other backup or sync copy that holds these
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

`develop` and `reveal` walk the book in batches of names (`--batch-size`,
default 400). Whole-book tables stay in memory in compact form: screen rows,
universe membership, sector breadth, statements, and a cross-name tape of
closes and basket candidates that matched baskets and the regime read. Daily
bars are split once per run, by ticker batch, into binary files under the
scratch directory (`_tapes-*`, deleted at the end of the run) and loaded one
batch at a time. A ticker's `sp500` and `sp400` specs share a book key, so
batches group tickers rather than universes. Whole episodes stream to the
scratch files as each batch finishes. The blocks equal a whole-book walk's for
any batch size: the tests compare batch sizes 10,000, 50 and 3 on the
synthetic fixture.

Before walking, the runner checks available memory with psutil when it is
installed (`pip install psutil`). When the estimate for the chosen batch size
is above what is available, it prints a warning and suggests a smaller
`--batch-size`.

`scripts/strategy_book_rehearsal_scale.py` writes synthetic build directories
and Sharadar-shaped tables of the real shape and runs the load, `develop` and
`reveal`, each in a fresh process. No licensed data is used. It reports peak
resident memory: `ru_maxrss` on Linux and macOS, psutil `peak_wset` on
Windows, and the tracemalloc peak otherwise.

```bash
python scripts/strategy_book_rehearsal_scale.py                    # default batch size
python scripts/strategy_book_rehearsal_scale.py --batch-size 100
```

Measured 2026-11-06 on a 4-core Linux VM (Python 3.12, pandas 3.1). The data
was 1,068 `sp500` names over 5,180,716 daily rows and 3,380 cap-rank names
over 12,699,270 daily rows, with 309 month-ends from 2000-01 to 2025-09.
Listings and delistings were staggered, and 150 names moved from the cap-rank
set into `sp500`. That is 4,448 names walked over 6,717 sessions.

| Run | Load | `develop` | `reveal` |
|---|---|---|---|
| Before batching (whole book) | 66 s, 3.7 GB | 328 s, 4.5 GB | 542 s, 5.1 GB |
| `--batch-size 400` (default) | 54 s, 1.7 GB | 256 s, 1.5 GB | 387 s, 1.7 GB |
| `--batch-size 100` | 55 s, 0.9 GB | 247 s, 1.3 GB | 371 s, 1.4 GB |

Each figure is the time and peak memory of that step alone. `develop` and
`reveal` include their own load. The store blocks from `--batch-size 100` are
byte-identical to the whole-book run's, with 4,454 mature development and
4,265 mature confirmation primary episodes.

On a laptop with 8 GB of memory, the default is fine once other large
programs are closed. If the runner warns or Windows starts paging, use
`--batch-size 100`. Smaller batches cost almost no time. The synthetic run
skips the SEP cap-rank pass, which streams `stocks.csv.zip` in 2M-row chunks
twice. On Windows, check installed memory with
`systeminfo | findstr /C:"Total Physical"`.
