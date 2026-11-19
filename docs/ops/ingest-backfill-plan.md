# Ingest backfill and cutoff protection

Weekday **ingest-loop** runs bounded ingest-improvement against buy-tier names in
`docs/data/latest.json`. When the Python runtime budget is exhausted, work is
**not lost** — artifacts commit and the backlog carries remaining tickers forward.

Each ticker already inside a fetch is hard-capped at
`min(per_ticker_max_seconds, time left in the slot)` with `SIGALRM`. Hitting the
per-ticker cap aborts that ticker (bodies already written stay on disk) and the
pass moves on. Hitting the slot cap, or `SIGTERM` from the workflow's
`timeout --signal=TERM 75m`, flushes a partial summary and
`/tmp/ingest_loop.json` so the commit and chain steps still run. The in-progress
ticker stays deferred. A per-ticker abort is recorded as done for this pass so
the same chain does not start it again.

## Library spare and maintenance slices

The FTSE loop above commits because the Python budget ends before
`timeout-minutes`, and the commit step still runs. The library sprint and
maintenance workflows used to commit once, after every name in the slot. A
GitHub job timeout at `timeout-minutes` cancelled that step and dropped the
pass. That is the failure a per-name commit matches.

Spare streams and maintenance now fetch one name, commit the library
artifacts, and fetch the next name until the same ceiling or an idle queue.
Ceilings are unchanged: spare streams 24 names and 2100 seconds, maintenance
one shared 3600-second slot (not 3600 seconds per market), predecessor wait
2400 seconds. `timeout-minutes` stays 110 on the sprint workflows and 120 on
maintenance. A timeout can drop only the name still in progress.

Stream 2 waits on euro and stream 1 only while one of those runs is actually
fetching. A later wave that is queued is not, by itself, a reason to skip.
When stream 2's seated backlog is idle, that same slot takes one unheld
Trading 212 stock and records the seconds. It does not start a second name
in the same slot, and it does not add a stream.

## Runtime budget

| Setting | Default | GHA limit |
|---------|---------|-----------|
| `max_runtime_seconds` | **2100** (35 min) | Step timeout 35 min |
| `per_ticker_max_seconds` | **320** | — |
| `max_targets` | **12** | — |
| Bodies per ticker refetch | **20** (burst: **40** via `max_bodies`) | — |
| `bootstrap_seed_cap` | **6** (burst drain: **0**) | — |

Dispatch overrides:

```bash
gh workflow run ingest-loop.yml -f max_targets=8 -f max_runtime_seconds=2100 -f max_bodies=40 -f bootstrap_seed_cap=0 -f force=true
```

## Backlog resume (`docs/data/ingest_backlog.json`)

On `runtime_cutoff`, the pass writes `remaining_tickers` from the planned batch.
The next run **prepends** those tickers before fresh ranking so deferred names
(e.g. TPK.L after a Monday morning cutoff) are not dropped.

When a pass completes without cutoff, the backlog file is removed.

## Automatic chunk chain

If a scheduled run ends with `runtime_cutoff` and `targets_deferred > 0`, the
workflow dispatches a second `ingest-loop` (no `force`) with `max_targets` capped
at 8, using the remaining daily slot (2 successes/day gate).

Manual `force=true` dispatches do **not** auto-chain (avoids runaway bursts).

`force=true` bypasses the **daily success cap** only — another ingest-loop run
that is already active or queued will still block dispatch (single-flight).

## Tuning loop

Health log entries now include `targets_planned`, `targets_completed`,
`targets_deferred`, `runtime_cutoff`, and `cutoff_reason`. Ops monitor warns on
cutoff with deferred count (distinct from zero-body stall).

Suggested ramp:

1. If cutoff is rare and `runtime_seconds` &lt; 85% of budget → consider slightly
   higher `max_targets`.
2. If cutoff is frequent with `targets_deferred` &gt; 3 → rely on backlog + chain;
   avoid only raising `max_targets`.
3. Strong-buy backfill bursts: `max_targets=6–8`, `force=true`, repeat until
   backlog clears for Tier A names (HIK, FGP, MEGP, GFTU, ITV, AEP, BREE).

## Related

- Workflow: `.github/workflows/ingest-loop.yml`
- Code: `src/value_investor/ingest_backlog.py`, `ingest_improvement.py`, `ingest_loop.py`
- Volume plan: `docs/ops/market-scrutiny.md`
