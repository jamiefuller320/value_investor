# Library ingest escalation (FTSE parity)

Reusable weekday filing-deepen escalation for **offline library markets**. The
`euro_depth` sprint is the first pilot; copy this pattern when adding the next
market shard (e.g. `asx200`, `sp500` offline depth).

Live FTSE reference: [`ingest-loop.yml`](../../.github/workflows/ingest-loop.yml),
[`docs/ops/horizon-scan.md`](horizon-scan.md) (gap-closure runs).

## Cascade model

```text
Stage 0 — Live FTSE 350
  ingest-loop.yml → ingest_health_log → stall → micro-compile ingest tasks
  gap-closure runs → eng queue → verify merged → ingest-loop rerun

Stage 1 — Library market pilot (euro_depth)
  euro-ingest-loop.yml → markets/{id}/ingest_health_log → stall → micro-compile
  same ingest_gap_closure_runs.json + engineering_tasks.json queue

Stage 2+ — Next library markets
  Reuse ftse-library ingest-loop --market {id} with the same escalation module
  when Phase 2/3 gates justify filing parity work
```

**Rule:** richness before breadth on the live path; library markets grow filing
depth offline using the same eng escalation semantics as FTSE.

## Artifacts (per market)

| Path | Purpose |
|------|---------|
| `docs/data/library/markets/{market_id}/ingest_health_log.json` | Before/after filing health snapshots |
| `docs/data/library/markets/{market_id}/ingest_summary.json` | Latest run targets + per-ticker results |
| `docs/data/library/euro_ingest_dispatch.json` | Completion gate (`euro_depth` only today) |
| `docs/data/ingest_gap_closure_runs.json` | Shared gap-closure run log (FTSE + library) |
| `docs/data/engineering_tasks.json` | Shared engineering queue |

Legacy `docs/data/library/euro_ingest_health_log.json` is still read for
`euro_depth` when the per-market log is absent.

## Escalation paths

### 1. Micro-compile on stall

After **`stall_runs`** consecutive library ingest runs (default **2**) where:

- buy-tier filing gaps (`unmeasured + zero_body`) are unchanged and &gt; 0, and
- no tickers improved in those runs,

`compile_library_ingest_engineering_tasks_micro` drafts one **ingest** task scoped
to `market_id` (`source=library_ingest_stall`).

### 2. Gap-closure compile

When a run is recorded with `--record-gap-closure` (or workflow
`record_gap_closure=true`) and the pinned / top-gap ticker still fails after the
pass, `compile_ingest_engineering_task_from_trial` queues a chained ingest task
(same chain limits as FTSE, max 3 rounds).

Gap runs carry `params.market_id` and `params.universe=library` so verification
and gap detection use the market canonical filing index.

## Commands

```bash
# Weekday deepen (automation default)
ftse-library ingest-loop --market euro_depth --max-targets 12

# Manual gap-closure pass
ftse-library ingest-loop --market euro_depth --max-targets 1 --record-gap-closure \
  --pin-ticker SHELL.AS --gap-closure-review-trigger horizon_scan

# Verification rerun after engineering merge
gh workflow run euro-ingest-loop.yml -f market=euro_depth -f record_gap_closure=true \
  -f pin_ticker=SHELL.AS -f gap_closure_parent_id=igc-YYYYMMDD-01

# Dispatch / gate status
ftse-library euro-ingest-dispatch --json
```

## Workflow hooks (FTSE parity)

| Hook | Workflow | Behaviour |
|------|----------|-----------|
| Micro-compile dispatch | `euro-ingest-loop.yml` | After `micro_compiled` or `gap_closure_compiled`, runs `engineering-queue.yml` immediately |
| Post-merge verify rerun | `engineering-queue.yml` | Tasks with `evidence.market_id` rerun **`euro-ingest-loop.yml`**; FTSE tasks still use `ingest-loop.yml` |
| Clean JSON for CI | `euro-ingest-loop.yml` | Uses `ingest-loop --json-path` / `euro-ingest-dispatch --json-path` (not `tee`) so stdout warnings (e.g. PyMuPDF `fitz`) cannot break `GITHUB_OUTPUT` parsing |

## Adding a new market

1. Ensure `ftse-library grow` + `screen-lite` produce a buy-tier shortlist.
2. Point `ingest-loop --market {id}` at the market (workflow or cron).
3. Confirm `markets/{id}/ingest_health_log.json` accumulates before expecting stall
   escalation (needs ≥2 runs).
4. Optionally add a market-specific completion gate (see `euro_depth_ingest_dispatch.py`).
5. Register cron via `scripts/import_cron_jobs.py` when the market graduates from
   manual pilot.

## Related

- [`euro-depth-sprint.md`](euro-depth-sprint.md) — sprint cadence and Phase 3 gates
- [`engineering-sync.md`](engineering-sync.md) — post-merge verify + gap-closure chain
- [`market-sharded-learning.md`](market-sharded-learning.md) — ladder / shard phases
