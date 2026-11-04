# Quarterly history (Yahoo income and cash flow)

**Strategy part served:** plan step 1.6 in [`strategy-reorientation-plan.md`](strategy-reorientation-plan.md) (deferred N252)
**Code:** `src/value_investor/quarterly_history_backfill.py`, wired into `ingest_research_sources` and `write_fetched_statement`
**CLI:** `ftse-quarterly-backfill` (drill-down and one-shot git backfill)

## What this is for

The operating-decline gate compares the latest `quarterly_income` period with the same period a year earlier (45-day window). Yahoo's quarterly frame is about four periods, and each fetch used to overwrite `sources/financials_annual.json`, so the prior-year quarter disappeared.

Two paths keep it:

1. **Ongoing accumulation.** On every financials write, `quarterly_income` and `quarterly_cashflow` are merged with the file already on disk. The union is by period-end date. The newly fetched row wins when the same period is in both. At most 12 periods are kept (about three years), newest first. Annual statements, `cashflow_metrics` and every other key stay on the new payload. `quarterly_history_kept` is the longer of the two stored series. A fetch that returns an empty quarterly object does not delete periods already stored.
2. **One-shot git backfill.** Those files are committed, so older blobs still hold the quarters that rolled off. The CLI merges them in. Values already in the working tree win. A period is added only when it is older than the newest dated period already on that series. Keys that are not a `YYYY-MM-DD` period end (including a bare fiscal year) are ignored. A `quarterly_cashflow_source` that contains `(trailing)` is left unchanged: that block is one trailing-twelve-month figure, and an extra period would make the cash-flow reader sum it. Keys that are not period ends (a bare fiscal year already stored on the file) stay as they are. The backfill does not copy those keys out of older commits, and it does not delete them.

`FINANCIAL_QUARTERS` stays 4. That is the fetch window and the slice used by trailing-twelve-month cash flow and the screening snapshot summary. Storing 12 periods does not widen that slice. A series that already has four newest periods keeps the same four in those readers. A series that had fewer than four, or a single trailing-twelve-month proxy, can change those readers when older periods are added. That is reported when the backfill is applied; scoring code is unchanged.

Point-in-time: `fetched_at` still moves on a live fetch, so a past `as_of` still fails closed against the current file. The backfill does not rewrite a period that is already stored and does not invent a dated snapshot.

Library market fetches use the same writers (`ingest_research_sources` for research ingest, `write_fetched_statement` for the FTSE statement gap fill). They accumulate the same way the next time that file is fetched.

## CLI

Dry-run is the default. `--apply` writes. A shallow clone prints `history unavailable` and writes nothing.

```bash
ftse-quarterly-backfill                         # FTSE screen rows, then library research dirs
ftse-quarterly-backfill --no-library            # FTSE screen rows only
ftse-quarterly-backfill --tickers SHEL.L,BP.L   # named tickers (comma-separated, repeatable)
ftse-quarterly-backfill --limit 10              # cap the file count
ftse-quarterly-backfill --apply --no-library    # write FTSE files whose quarterly series change
ftse-quarterly-backfill --json                  # machine-readable report
```

`--repo` is the git working tree (default: the current directory). `--max-versions` (default 60) caps `git log` commits per file. `--keep` (default 12) is the period cap. `--as-of` only affects the same-quarter prior-year count in the report; it does not drop periods.

The report's "gained" count is files whose `quarterly_income` series did not have a same-quarter prior year and does after the merge. The window matches the gate (`INTERIM_YOY_WINDOW_DAYS`).

## What runs on the schedule

The merge is inside the existing ingest write, so the next scheduled fetch keeps periods already on disk. There is no separate cron and no ops-monitor finding: a daily git walk would rewrite research files. The CLI is the one-shot repair and the ad-hoc check.

After a backfill, refresh the observe store with `ftse-operating-decline-gate`. Coverage for the gate is in [`operating-decline-gate.md`](operating-decline-gate.md#interim-coverage-diagnosis-ftse-buy-tier).
