# Library ingest escalation (FTSE parity)

Reusable weekday filing-deepen escalation for **offline library markets**. The
`euro_depth` sprint is the first pilot; `sp500` is the first
**FTSE-equivalent** market (`policy.ftse_equivalent_markets`). Copy this pattern
when adding the next market shard (e.g. `asx200` offline depth).

Live FTSE reference: [`ingest-loop.yml`](../../.github/workflows/ingest-loop.yml),
[`docs/ops/horizon-scan.md`](horizon-scan.md) (gap-closure runs).

## Cascade model

```text
Stage 0 — Live FTSE 350
  ingest-loop.yml → ingest_health_log → stall → micro-compile ingest tasks
  gap-closure runs → eng queue → verify merged → ingest-loop rerun

Stage 1 — Library market pilot (euro_depth)
  euro-ingest-loop.yml (sprint) + library-ingest-maintenance.yml (parity)
  → markets/{id}/ingest_health_log → stall → micro-compile
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
| `docs/data/library/markets/{market_id}/learning_depth.json` | FTSE-equivalent filing + trajectory readiness (`ftse-library learning-depth --write`) |
| `docs/data/library/markets/{market_id}/screen/trajectory_*.json` | Library trajectory artifacts (refreshed after observe-sim on FTSE-equivalent markets) |
| `docs/data/library/euro_ingest_dispatch.json` | Sprint vs maintenance gate (focus market) |
| `docs/data/library/library_ingest_discovery_scan_summary.json` | Maintenance discovery scan summary |
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
# Weekday deepen (sprint automation)
ftse-library ingest-loop --market euro_depth --max-targets 24

# Daily maintenance (parity markets; discovery scan on by default)
ftse-library ingest-maintenance --json

# Parallel sprint (queue head-start while focus still sprinting)
ftse-library ingest-sprint --json

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
| Sprint ingest (focus) | `euro-ingest-loop.yml` | Runs only when focus `should_run_sprint_ingest` |
| Sprint ingest (parallel) | `library-ingest-sprint.yml` | Runs `ingest_parallel_sprint` markets with gaps (e.g. sp500) |
| Maintenance ingest | `library-ingest-maintenance.yml` | Daily scan-then-target for `ingest_parity_markets` + focus at parity |
| Micro-compile dispatch | `euro-ingest-loop.yml` | After `micro_compiled` or `gap_closure_compiled`, runs `engineering-queue.yml` immediately |
| Post-merge verify rerun | `engineering-queue.yml` | Tasks with `evidence.market_id` rerun **`euro-ingest-loop.yml`**; FTSE tasks still use `ingest-loop.yml` |
| Clean JSON for CI | `euro-ingest-loop.yml` | Uses `ingest-loop --json-path` / `euro-ingest-dispatch --json-path` (not `tee`) so stdout warnings (e.g. PyMuPDF `fitz`) cannot break `GITHUB_OUTPUT` parsing |

## FTSE-equivalent markets (`sp500`)

Policy `ftse_equivalent_markets: ["sp500"]` changes measurement and the parity bar:

1. **Canonical-only coverage.** `_filing_coverage_for_ticker(..., canonical_only=True)`
   reads only `markets/sp500/screen/research/{TICKER}/`. Bodies that exist only under
   `nasdaq100` (or any other shard) are **unmeasured** for S&P parity.
2. **`ingest_parity_met()`** for `health.ftse_equivalent` also requires
   `thin_body_buy_tier == 0` and `indexed_without_body == 0`. `euro_depth` stays
   unmeasured + zero-body only.
3. **Health snapshot** includes `indexed_without_body`, `bodies_min` / `median` /
   `max`, `coverage_scope`, and `ftse_equivalent`.
4. **Do not** append `sp500` to `ingest_parity_markets` until
   `ftse-library learning-depth --market sp500` is green (`learning_ready`).
5. Parallel sprint then sees real gaps (24 targets) instead of a 4-target
   maintenance pass that treated shard fallback as zero gaps.

```bash
ftse-library learning-depth --market sp500 --json
# expect filing_ready=false / trajectory_ready=false until depth matches FTSE
```

## Adding a new market

1. Ensure `ftse-library grow` + `screen-lite` produce a buy-tier shortlist.
2. Point `ingest-loop --market {id}` at the market (workflow or cron).
3. Confirm `markets/{id}/ingest_health_log.json` accumulates before expecting stall
   escalation (needs ≥2 runs).
4. Completion gate lives in `library_ingest_dispatch.py` (euro wrapper: `euro_depth_ingest_dispatch.py`).
5. Register cron via `scripts/import_cron_jobs.py` when the market graduates from
   manual pilot.

## Related

- [`euro-depth-sprint.md`](euro-depth-sprint.md) — sprint cadence and Phase 3 gates
- [`engineering-sync.md`](engineering-sync.md) — post-merge verify + gap-closure chain
- [`market-sharded-learning.md`](market-sharded-learning.md) — ladder / shard phases
