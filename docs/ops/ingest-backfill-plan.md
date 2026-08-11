# Ingest backfill and cutoff protection

Weekday **ingest-loop** runs bounded ingest-improvement against buy-tier names in
`docs/data/latest.json`. When the Python runtime budget is exhausted, work is
**not lost** — artifacts commit and the backlog carries remaining tickers forward.

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
